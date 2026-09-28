/*
 * srvfix.c — srcds 运行时补丁：阻止「预留开局」逻辑把每个连进来的客户端踢掉。
 *
 * 反汇编依据（bin/engine.so，32 位，Addr==Off，故文件偏移即 vaddr）：
 *
 *   1d82f5  movzbl 0x288(%ebx),%eax        ; ebx = CGameServer，+0x288 = 「服务器已预留」标志
 *   1d82fc  test   %al,%al
 *   1d82fe  je     1d7feb                  ; 未预留 → 跳过下面整块
 *   1d8314  lea    0x10(%ebx),%eax         ; 预留地图名
 *   1d8327  push   $0x50cc2e               ; "nextlevel %s"
 *   1d8333  call   1288e0                  ; sprintf(buf, "nextlevel de_cache")
 *   1d8340  push   $0x2                    ; 执行标记 = 2
 *   1d8342  call   1e7150                  ; 执行 "nextlevel de_cache"
 *   1d8367  push   $0x50cc3c               ; "map %s reserved"
 *   1d836d  call   1288e0                  ; sprintf(buf, "map de_cache reserved")
 *   1d837a  push   $0x2
 *   1d837c  call   1e7150                  ; 执行 "map de_cache reserved" → ★ 立刻重载关卡
 *   1d8384  call   1e8090
 *
 * 日志实证：每条 "[R] Connect from <client>" 后面紧跟一条 "---- Host_Changelevel ----"，
 * 以及 "GameTypes: could not find matching game mode value of \"reserved\" in any game type."
 * （来自 "map de_cache reserved" 里的 "reserved" 被当成 game mode 查表）。
 *
 * 于是：客户端连上 → 服务器重载关卡 → 客户端被踢 → 自动重连（"Retrying public(...)"）
 *       → 服务器又重载 → 死循环。
 *
 * 我们的服务器手上那个 reservation 是假的（cookie 非 0，但没有真正的对局数据，
 * 也永远耗不掉），所以这一块每次连接都会重放。把 1d82fe 的 je 改成 jmp 直接跳过整块。
 *
 * 位置：0x1d82fe 处 6 字节  0F 84 E7 FC FF FF (je 1d7feb, disp=-793)
 *   改为                     E9 E8 FC FF FF 90 (jmp 1d7feb, disp=-792)
 *
 * ★ 坑：rel32 是相对「指令末尾」的。je rel32 长 6 字节，jmp rel32 只长 5 字节，
 *   所以不能沿用原位移 —— 直接照抄会差 1 字节，跳进 0x1d7fea（`add $0x10,%esp`
 *   的指令中间），解码成垃圾指令后写坏内存 → SIGSEGV（实测 dmesg 报的正是
 *   ip=base+0x1d7fea）。必须按 target - (jmp_地址 + 5) 重新算。
 *
 * 用法：LD_PRELOAD=/home/csgo/csgo_srvfix.so ./srcds_run ...
 * 构建：gcc -m32 -shared -fPIC -O2 -o csgo_srvfix.so srvfix.c -ldl
 * 关闭：环境变量 SRVFIX_OFF=1
 *
 * 本文件由我们自行编写，不加载任何第三方二进制。
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <limits.h>
#include <link.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>

/* 25 字节签名：movzbl 0x288(%ebx),%eax / test %al,%al / je rel32 /
 *              mov (%ebx),%eax / mov 0x3c(%eax),%eax / cmp $vtbl,%eax
 * 其中两处 32 位立即数在装载时会被重定位（vtable 地址）或本就可变，
 * 用 MASK 排除掉，不做比对。 */
static const unsigned char SIG[25] = {
    0x0F, 0xB6, 0x83, 0x88, 0x02, 0x00, 0x00,   /* movzbl 0x288(%ebx),%eax */
    0x84, 0xC0,                                 /* test   %al,%al          */
    0x0F, 0x84, 0x00, 0x00, 0x00, 0x00,         /* je     rel32            */
    0x8B, 0x03,                                 /* mov    (%ebx),%eax      */
    0x8B, 0x40, 0x3C,                           /* mov    0x3c(%eax),%eax  */
    0x3D, 0x00, 0x00, 0x00, 0x00                /* cmp    $vtbl,%eax       */
};
static const unsigned char MASK[25] = {
    1, 1, 1, 1, 1, 1, 1,
    1, 1,
    1, 1, 0, 0, 0, 0,
    1, 1,
    1, 1, 1,
    1, 0, 0, 0, 0
};

#define JE_OFF 9        /* 签名内 "0F 84" 的位置 */
#define DISP_OFF 11     /* 签名内 rel32 的位置  */

static uintptr_t g_lo, g_hi;
static int g_done;

static int find_engine(struct dl_phdr_info *info, size_t sz, void *data)
{
    (void)sz; (void)data;
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
    fprintf(stderr, "[srvfix] 找到引擎 %s base=%p size=%#lx\n",
            info->dlpi_name, (void *)lo, (unsigned long)(hi - lo));
    return 1;
}

static int sig_match(const unsigned char *p)
{
    for (int i = 0; i < (int)sizeof(SIG); i++) {
        if (MASK[i] && p[i] != SIG[i]) return 0;
    }
    return 1;
}

/* 返回 1 = 处理完毕（成功或确定放弃），0 = 引擎还没出现 */
static int try_patch(void)
{
    g_lo = g_hi = 0;
    dl_iterate_phdr(find_engine, NULL);
    if (!g_lo) return 0;

    uintptr_t hit = 0;
    int nhit = 0;
    for (uintptr_t a = g_lo; a + sizeof(SIG) <= g_hi; a++) {
        if (sig_match((const unsigned char *)a)) {
            if (!hit) hit = a;
            nhit++;
        }
    }
    if (!hit) return 0;
    fprintf(stderr, "[srvfix] 签名命中 %d 处，取第一处 %p\n", nhit, (void *)hit);

    unsigned char *je = (unsigned char *)(hit + JE_OFF);
    if (je[0] != 0x0F || je[1] != 0x84) {
        fprintf(stderr, "[srvfix] 意外：该处不是 6 字节 je（%02x %02x），放弃\n",
                je[0], je[1]);
        return 1;
    }
    /* 锚点即 0x1d82f5（签名唯一命中处）。第二个 "push $0x2; call 1e7150"
     * —— 也就是执行 "map <map> reserved" 的地方 —— 固定在锚点 +0x85 处。 */
    unsigned char *site = (unsigned char *)(hit + 0x85);
    if (site[0] != 0x6A || site[1] != 0x02 || site[2] != 0xE8) {
        fprintf(stderr, "[srvfix] 意外：锚点+0x85 不是 push $2; call（%02x %02x %02x），放弃\n",
                site[0], site[1], site[2]);
        return 1;
    }

    long pagesz = sysconf(_SC_PAGESIZE);
    uintptr_t pg = (uintptr_t)(site + 2) & ~((uintptr_t)pagesz - 1);
    size_t len = ((uintptr_t)(site + 2) + 5) - pg;
    if (mprotect((void *)pg, len, PROT_READ | PROT_WRITE | PROT_EXEC) != 0) {
        perror("[srvfix] mprotect 失败");
        return 1;
    }

    memset(site + 2, 0x90, 5);     /* NOP 掉 call 1e7150（命令不入队） */

    if (mprotect((void *)pg, len, PROT_READ | PROT_EXEC) != 0)
        perror("[srvfix] 恢复保护属性失败");

    fprintf(stderr, "[srvfix] 已打补丁：%p 处 call 1e7150 已 NOP（不再执行 map <map> reserved）\n",
            (void *)je);
    return 1;
}

static void *worker(void *arg)
{
    (void)arg;
    for (int i = 0; i < 1200; i++) {        /* 最多 120 秒 */
        if (try_patch()) { g_done = 1; return NULL; }
        usleep(100 * 1000);
    }
    fprintf(stderr, "[srvfix] 放弃：120 秒内没等到引擎\n");
    return NULL;
}

__attribute__((constructor))
static void srvfix_init(void)
{
    if (getenv("SRVFIX_OFF")) {
        fprintf(stderr, "[srvfix] SRVFIX_OFF 已设置，跳过\n");
        return;
    }
    fprintf(stderr, "[srvfix] 已注入，等引擎加载..\n");

    pthread_t t;
    if (pthread_create(&t, NULL, worker, NULL) != 0) {
        fprintf(stderr, "[srvfix] 起线程失败\n");
        return;
    }
    pthread_detach(t);
}
