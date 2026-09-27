/*
 * appidfix.c — 让 CS:GO Legacy（归档 appid 4465480）客户端能进 srcds。
 *
 * 背景：Valve 把 CS:GO 归档成独立 Steam app 后，legacy 客户端的认证票据
 * 带的是 4465480，服务器引擎按 appid 校验后走"拒绝"分支：
 *     S3: Client connected with ticket for the wrong game
 *     RejectConnection: STEAM validation rejected
 * 现象是客户端能完成握手（日志里出现 "Connected to ..."），随后立刻断开。
 *
 * 原理：引擎用 `jmp ds:jpt[eax*4]` 分派 appid 校验结果，
 *       jt[0]=默认/OK，jt[4]=归档版走的拒绝分支。
 *       把 jt[0] 拷进 jt[4] 即可。
 *
 * 特征（Linux）：FF 24 85 ?? ?? ?? ??  8D B4 26 ?? ?? ?? ??  31 F6
 *   命中处 +3 的四字节就是跳转表的绝对地址（PIC 已重定位）。
 *   本机 engine.so 实测：分派点 vaddr 0x18a2ba，表 vaddr 0x501b64，
 *   jt[0]=0x18a498，jt[4]=0x18a3d8。
 *
 * 用法：LD_PRELOAD=/path/csgo_appidfix.so ./srcds_run -game csgo ...
 * 构建：gcc -m32 -shared -fPIC -O2 -o csgo_appidfix.so appidfix.c -ldl
 *
 * 本文件由我们自行编写，不加载任何第三方二进制。
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <link.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>

/* FF 24 85 <disp32> 8D B4 26 <disp32> 31 F6 */
static const unsigned char SIG[16] = {
    0xFF, 0x24, 0x85, 0x00, 0x00, 0x00, 0x00,
    0x8D, 0xB4, 0x26, 0x00, 0x00, 0x00, 0x00,
    0x31, 0xF6
};
static const unsigned char MASK[16] = {
    1, 1, 1, 0, 0, 0, 0,
    1, 1, 1, 0, 0, 0, 0,
    1, 1
};

static uintptr_t g_lo, g_hi;

static int find_engine(struct dl_phdr_info *info, size_t sz, void *data)
{
    (void)sz; (void)data;
    /* 目标模块名里含 "engine"（bin/engine.so） */
    if (!info->dlpi_name || !strstr(info->dlpi_name, "engine"))
        return 0;

    uintptr_t lo = (uintptr_t)-1, hi = 0;
    for (int i = 0; i < info->dlpi_phnum; i++) {
        const ElfW(Phdr) *ph = &info->dlpi_phdr[i];
        if (ph->p_type != PT_LOAD) continue;
        uintptr_t s = (uintptr_t)info->dlpi_addr + ph->p_vaddr;
        uintptr_t e = s + ph->p_memsz;
        if (s < lo) lo = s;
        if (e > hi) hi = e;
    }
    if (hi <= lo) return 0;

    g_lo = lo; g_hi = hi;
    fprintf(stderr, "[appidfix] 找到引擎 %s base=%p size=%#lx\n",
            info->dlpi_name, (void *)lo, (unsigned long)(hi - lo));
    return 1;   /* 停在第 1 个 */
}

static int sig_match(const unsigned char *p)
{
    for (int i = 0; i < 16; i++) {
        if (MASK[i] && p[i] != SIG[i]) return 0;
    }
    return 1;
}

/* 返回 1 = 已打过补丁（或确定打不了），0 = 引擎还没出现 */
static int try_patch(void)
{
    g_lo = g_hi = 0;
    dl_iterate_phdr(find_engine, NULL);
    if (!g_lo) return 0;

    uintptr_t hit = 0;
    for (uintptr_t a = g_lo; a + sizeof(SIG) <= g_hi; a++) {
        if (sig_match((const unsigned char *)a)) { hit = a; break; }
    }
    if (!hit) return 0;

    /* 分派指令内嵌的绝对地址就是跳转表 */
    uint32_t disp;
    memcpy(&disp, (void *)(hit + 3), sizeof(disp));
    uintptr_t table = (uintptr_t)disp;

    if (table < g_lo || table + 5 * sizeof(uintptr_t) > g_hi) {
        fprintf(stderr, "[appidfix] 表地址 %#lx 不在引擎范围内，放弃\n",
                (unsigned long)table);
        return 1;   /* 别再重试 */
    }

    uintptr_t *jt = (uintptr_t *)table;
    fprintf(stderr, "[appidfix] 分派点=%p 表=%p jt[0]=%#lx jt[4]=%#lx\n",
            (void *)hit, (void *)table,
            (unsigned long)jt[0], (unsigned long)jt[4]);

    if (jt[4] == jt[0]) {
        fprintf(stderr, "[appidfix] jt[4] 已经是 jt[0]，无需修改\n");
        return 1;
    }

    /* 表在 R+X 段里，要先放开写权限 */
    long pagesz = sysconf(_SC_PAGESIZE);
    uintptr_t pg = table & ~((uintptr_t)pagesz - 1);
    size_t len = (table + 5 * sizeof(uintptr_t)) - pg;
    if (mprotect((void *)pg, len, PROT_READ | PROT_WRITE | PROT_EXEC) != 0) {
        perror("[appidfix] mprotect 失败");
        return 1;
    }

    jt[4] = jt[0];

    if (mprotect((void *)pg, len, PROT_READ | PROT_EXEC) != 0)
        perror("[appidfix] 恢复保护属性失败");

    fprintf(stderr, "[appidfix] 已打补丁：jt[4] = jt[0] = %#lx\n",
            (unsigned long)jt[0]);
    return 1;
}

static void *worker(void *arg)
{
    (void)arg;
    /* engine.so 是 main() 之后才 dlopen 的，所以只能在后台等 */
    for (int i = 0; i < 1200; i++) {        /* 最多 120 秒 */
        if (try_patch()) return NULL;
        usleep(100 * 1000);
    }
    fprintf(stderr, "[appidfix] 放弃：120 秒内没等到引擎\n");
    return NULL;
}

__attribute__((constructor))
static void appidfix_init(void)
{
    /* 注意：构造函数跑在 main() 之前，绝不能在这里阻塞轮询——
     * 那样会把整个进程卡在启动阶段（引擎还没加载，等也等不到）。
     * 必须丢给后台线程。 */
    fprintf(stderr, "[appidfix] 已注入，等待引擎加载..\n");

    pthread_t t;
    if (pthread_create(&t, NULL, worker, NULL) != 0) {
        fprintf(stderr, "[appidfix] 起线程失败\n");
        return;
    }
    pthread_detach(t);
}
