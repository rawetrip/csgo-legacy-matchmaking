/*
 * srvfix.c — srcds 运行时补丁 v2（detour 版）
 *
 * 目标：让 srcds 的「按 reservation 换图」**只发生一次**，而不是每次客户端连接
 *       都重放一遍（那会导致 连上→重载关卡→被踢→重连→重载… 死循环）。
 *
 * ── 背景（v1 做了什么，为什么不够）────────────────────────────────────────
 *
 * engine.so 里那段「服务器已预留 → 直接开局」逻辑：
 *
 *   1d82f5  movzbl 0x288(%ebx),%eax     ; ebx = CGameServer，+0x288 = 「已预留」标志
 *   1d82fc  test   %al,%al
 *   1d82fe  je     1d7feb               ; 标志为 0 → 跳过整块
 *   ...
 *   1d837a  push   $0x2
 *   1d837c  call   1e7150               ; 执行 "map <map> reserved" → 重载关卡
 *
 * v1 的做法是把 1d837c 那条 call 直接 NOP 掉 —— **换图也就跟着没了**。
 *
 * ── v2 的做法 ─────────────────────────────────────────────────────────────
 *
 * 把 `push $2; call 1e7150`（7 字节）换成 `jmp <stub>`（5 字节 + 2 字节 NOP），
 * stub 在我们自己 mmap 出来的内存里：
 *
 *     push $2
 *     call <1e7150>              ; 真正执行换图（恢复 v1 砍掉的功能）
 *     mov  byte [ebx+0x288], 0   ; ★ 清「已预留」标志
 *     jmp  <site+7>              ; 回到原流程继续
 *
 * **第一次换图照常发生；标志被清零后，后续连接读到的就是 0 → 跳过整块 → 不再重放。**
 *
 * 注意 ebx 在这段里一直是 CGameServer（原代码 `0x288(%ebx)` / `0x10(%ebx)` 都用它），
 * stub 里不碰 ebx。
 *
 * 用法：LD_PRELOAD=/home/csgo/csgo_srvfix.so ./srcds_run ...
 * 构建：gcc -m32 -shared -fPIC -O2 -o csgo_srvfix.so srvfix.c -ldl
 * 关闭：环境变量 SRVFIX_OFF=1
 *
 * 本文件由我们自行编写，不加载任何第三方二进制。
 */
#define _GNU_SOURCE
#include <dlfcn.h>
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

#define JE_OFF   9      /* 签名内 "0F 84" 的位置 */
#define SITE_OFF 0x85   /* 锚点 → "push $2; call 1e7150" 的偏移 */
#define CALLREL_OFF 0x88 /* 锚点 → call 的 rel32 位置（= site + 3） */

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

static int make_writable(void *addr, size_t len)
{
    long pagesz = sysconf(_SC_PAGESIZE);
    uintptr_t pg = (uintptr_t)addr & ~((uintptr_t)pagesz - 1);
    size_t total = ((uintptr_t)addr + len) - pg;
    return mprotect((void *)pg, total, PROT_READ | PROT_WRITE | PROT_EXEC);
}

static int make_exec_only(void *addr, size_t len)
{
    long pagesz = sysconf(_SC_PAGESIZE);
    uintptr_t pg = (uintptr_t)addr & ~((uintptr_t)pagesz - 1);
    size_t total = ((uintptr_t)addr + len) - pg;
    return mprotect((void *)pg, total, PROT_READ | PROT_EXEC);
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

    /* 锚点即 1d82f5。第二个 "push $0x2; call 1e7150" —— 执行 "map <map> reserved"
     * 的地方 —— 固定在锚点 +0x85。 */
    unsigned char *site = (unsigned char *)(hit + SITE_OFF);
    if (site[0] != 0x6A || site[1] != 0x02 || site[2] != 0xE8) {
        fprintf(stderr, "[srvfix] 意外：锚点+0x85 不是 push $2; call（%02x %02x %02x），放弃\n",
                site[0], site[1], site[2]);
        return 1;
    }

    /* call 的目标地址（rel32 相对 call 指令末尾） */
    int32_t rel = *(int32_t *)(site + 3);
    uintptr_t target = (uintptr_t)(site + 7) + rel;      /* = 1e7150 */
    fprintf(stderr, "[srvfix] call 目标 %p\n", (void *)target);

    /* --- 选哪种打法：默认 NOP，SRVFIX_DETOUR=1 才用 detour 桩 -------------
     *
     * 默认（NOP）—— 这是 v1 的行为，2026-09-28 晚实测后改回来做默认：
     *   引擎那条 "map <map> reserved" 会**从非主线程触发关卡重载**，主循环回不来，
     *   被自家看门狗掐掉（退出码 134）。两轮实测都卡死在 `Created class baseline`
     *   之后：
     *     GameTypes: could not find matching game mode value of "reserved"
     *     ... Created class baseline: 27 classes, 15021 bytes.
     *     **** WARNING: Watchdog timer exceeded, aborting!
     *   NOP 掉这条 call 之后，`nextlevel X` 与后面的 Cbuf_Execute 都保留，
     *   只是引擎不再自己立刻重载关卡。换图改由外部通道补：
     *   veto_map.txt / server_map.txt -> GC 轮询 -> srvcmd.sh(TIOCSTI) -> changelevel。
     *
     * detour（需要 SRVFIX_DETOUR=1）—— v2 原设计：执行换图 + 清 [CGameServer+0x288]。
     *   它能让引擎原生换图，但会踩上面那个看门狗。保留是为了对比和将来排查。
     * ------------------------------------------------------------------- */
    int use_detour = getenv("SRVFIX_DETOUR") != NULL;
    unsigned char patch[7];
    int32_t d;

    if (use_detour) {
        /* --- 分配 stub ------------------------------------------------- */
        unsigned char *stub = mmap(NULL, 4096, PROT_READ | PROT_WRITE,
                                   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (stub == MAP_FAILED) {
            perror("[srvfix] mmap stub 失败");
            return 1;
        }
        unsigned char *w = stub;

        /* push $2 */
        *w++ = 0x6A; *w++ = 0x02;

        /* call <target> —— e8 rel32，rel 相对下一条指令（= stub+7） */
        *w++ = 0xE8;
        d = (int32_t)((intptr_t)target - (intptr_t)(w + 4));
        memcpy(w, &d, 4); w += 4;

        /* mov byte ptr [ebx+0x288], 0 —— c6 83 88 02 00 00 00 */
        *w++ = 0xC6; *w++ = 0x83;
        *w++ = 0x88; *w++ = 0x02; *w++ = 0x00; *w++ = 0x00;
        *w++ = 0x00;

        /* jmp <site+7> —— e9 rel32 */
        *w++ = 0xE9;
        d = (int32_t)((intptr_t)(site + 7) - (intptr_t)(w + 4));
        memcpy(w, &d, 4); w += 4;

        fprintf(stderr, "[srvfix] stub 位于 %p（%ld 字节）\n",
                (void *)stub, (long)(w - stub));
        __builtin___clear_cache((char *)stub, (char *)w);

        /* ★ 必须显式把 stub 页设成可执行：mmap(PROT_READ|PROT_WRITE) 出来的页在现代
         * 内核上是 NX 的，跳进去直接 SIGSEGV，特征是「执行地址 == 出错地址」：
         *     segfault at f3231000 ip 00000000f3231000 error 15
         * 失败时放弃打补丁，宁可不换图也不能让服务器在玩家连入时崩。 */
        if (mprotect(stub, 4096, PROT_READ | PROT_EXEC) != 0) {
            perror("[srvfix] mprotect(stub) 失败 —— stub 不可执行，放弃打补丁");
            return 1;
        }

        if (make_writable(site, 7) != 0) {
            perror("[srvfix] mprotect(site) 失败");
            return 1;
        }
        patch[0] = 0xE9;                                /* jmp rel32 */
        d = (int32_t)((intptr_t)stub - (intptr_t)(site + 5));
        memcpy(patch + 1, &d, 4);
        patch[5] = 0x90; patch[6] = 0x90;
        memcpy(site, patch, sizeof(patch));
        fprintf(stderr,
                "[srvfix] 已打补丁（detour）：%p 处改为跳桩 → 执行 map <map> reserved，"
                "再清 [CGameServer+0x288]\n", (void *)je);
    } else {
        if (make_writable(site, 7) != 0) {
            perror("[srvfix] mprotect(site) 失败");
            return 1;
        }
        /* 6A 02 90 90 90 90 90 —— 保留 push $2（它是后面 Cbuf_Execute 的参数，
         * 栈保持平衡），只 NOP 掉那条 call。 */
        patch[0] = 0x6A; patch[1] = 0x02;
        patch[2] = 0x90; patch[3] = 0x90; patch[4] = 0x90;
        patch[5] = 0x90; patch[6] = 0x90;
        memcpy(site, patch, sizeof(patch));
        fprintf(stderr,
                "[srvfix] 已打补丁（NOP）：%p 处不执行引擎自带的 map <map> reserved "
                "（那条会从非主线程重载关卡并卡死看门狗）；换图走外部通道\n", (void *)je);
    }

    if (make_exec_only(site, 7) != 0)
        perror("[srvfix] 恢复 site 保护属性失败");

    /* ── 补丁 2b：不要在这里立刻 flush 命令缓冲 ─────────────────────────────
     *
     * objdump 出来的真实指令序列（engine.so，Addr == Off）：
     *
     *   1d8379  push %esi
     *   1d837a  push $0x2                 ← site，我们的桩替换的 7 字节从这里开始
     *   1d837c  call 1e7150               ; 入队 "map <map> reserved"
     *   1d8381  add  $0x10,%esp
     *   1d8384  call 1e8090               ← ★ Cbuf_Execute
     *   1d8389  jmp  1d7feb               ; 跳出整块
     *
     * 那两条命令（nextlevel X / map X reserved）**已经入队**（1e7150 那个调用）。
     * 这条 Cbuf_Execute 只是"立刻执行"，而它是**从非主线程**调的 —— 关卡重载要的锁
     * 被主循环占着 → 死锁 → 看门狗掐死。实测症状就是日志停在
     *   Created class baseline: 27 classes, 15021 bytes.
     *   **** WARNING: Watchdog timer exceeded, aborting!      (退出码 134)
     *
     * 把它 NOP 掉：命令留在缓冲里，主循环稍后自己 flush —— 重载照样发生，但由主线程做。
     * ─────────────────────────────────────────────────────────────────── */
    unsigned char *cbuf_exec = site + 0x0A;
    if (cbuf_exec[0] == 0xE8) {
        if (make_writable(cbuf_exec, 5) == 0) {
            unsigned char nop5[5] = { 0x90, 0x90, 0x90, 0x90, 0x90 };
            memcpy(cbuf_exec, nop5, 5);
            make_exec_only(cbuf_exec, 5);
            fprintf(stderr,
                    "[srvfix] 已打补丁（2b）：%p 处 Cbuf_Execute 改为 NOP —— "
                    "换图命令交由主循环 flush，避免非主线程重载关卡死锁\n",
                    (void *)cbuf_exec);
        } else {
            perror("[srvfix] mprotect(Cbuf_Execute) 失败");
        }
    } else {
        fprintf(stderr,
                "[srvfix] 警告：%p 处不是 call（%02x），跳过 Cbuf_Execute 补丁\n",
                (void *)cbuf_exec, cbuf_exec[0]);
    }

    return 1;
}

/* ─────────────────────────────────────────────────────────────────────────
 * 补丁 2：绕过 reservation cookie 检查
 *
 * `sv_lan 0` 的 srcds 会从 Valve 侧拿到一个**非零**的 reservation cookie，
 * 而客户端 connect 包里带的是 GC 下发的 "Hello :)"（0x293A206F6C6C6548），
 * 两者不等 → 连接被静默拒绝（#Valve_Reject_Reserved_For_Lobby）。
 *
 * engine.so 里的判定（Addr == Off）：
 *
 *   1d0776  mov  eax, [esi+0x2ec]     ; 服务器 cookie 低 32
 *   1d077c  mov  edx, [esi+0x2f0]     ; 服务器 cookie 高 32
 *   1d078e  mov  ecx, eax
 *   1d0796  mov  ebx, edx
 *   1d079e  mov  edx, esi             ; 客户端 cookie 低
 *   1d07a0  xor  edx, eax
 *   1d07a2  mov  eax, edi             ; 客户端 cookie 高
 *   1d07a4  xor  eax, ebx
 *   1d07a6  or   edx, eax
 *   1d07a8  je   1d2790               ; 相等 → 放行
 *   1d07ae  or   ecx, ebx             ; ecx|ebx = 服务器 cookie
 *   1d07b0  je   1d2790               ; ★ 服务器 cookie == 0 → 放行
 *   1d07b6  ...                       ; 否则 → 拒绝
 *
 * 把 1d07b0 的 `je` 改成无条件 `jmp` —— 不管 cookie 是什么一律放行。
 *
 * ★ rel32 必须重算：`je rel32` 是 6 字节、`jmp rel32` 只有 5 字节，直接照抄
 *   位移会差 1 字节、跳进指令中间（README 记过这个坑）。
 * ───────────────────────────────────────────────────────────────────────── */
static const unsigned char CSIG[10] = {
    0x09, 0xD9,                     /* or  ecx, ebx            */
    0x0F, 0x84, 0x00, 0x00, 0x00, 0x00,  /* je rel32  (MASK 掉) */
    0x8B, 0x85                      /* mov eax, [ebp+...]      */
};
static const unsigned char CMASK[10] = {
    1, 1,
    1, 1, 0, 0, 0, 0,
    1, 1
};

static int cookie_patched;

static int try_patch_cookie(void)
{
    if (cookie_patched) return 1;
    if (!g_lo) return 0;

    uintptr_t hit = 0;
    for (uintptr_t a = g_lo; a + sizeof(CSIG) <= g_hi; a++) {
        const unsigned char *p = (const unsigned char *)a;
        int ok = 1;
        for (int i = 0; i < (int)sizeof(CSIG); i++) {
            if (CMASK[i] && p[i] != CSIG[i]) { ok = 0; break; }
        }
        if (ok) { hit = a; break; }
    }
    if (!hit) return 0;

    unsigned char *je = (unsigned char *)(hit + 2);      /* 指向 0F 84 */
    if (je[0] != 0x0F || je[1] != 0x84) {
        fprintf(stderr, "[srvfix] cookie: 意外，%p 不是 6 字节 je\n", (void *)je);
        cookie_patched = 1;
        return 1;
    }

    /* 原跳转目标 = je 指令末尾 + 原 rel32 */
    int32_t oldrel;
    memcpy(&oldrel, je + 2, 4);
    uintptr_t target = (uintptr_t)(je + 6) + oldrel;

    fprintf(stderr, "[srvfix] cookie: je 在 %p → 目标 %p\n", (void *)je, (void *)target);

    if (make_writable(je, 6) != 0) {
        perror("[srvfix] cookie: mprotect 失败");
        cookie_patched = 1;
        return 1;
    }

    unsigned char patch[6];
    patch[0] = 0xE9;                                     /* jmp rel32 */
    int32_t newrel = (int32_t)((intptr_t)target - (intptr_t)(je + 5));
    memcpy(patch + 1, &newrel, 4);
    patch[5] = 0x90;                                     /* 补齐 6 字节 */
    memcpy(je, patch, sizeof(patch));

    if (make_exec_only(je, 6) != 0)
        perror("[srvfix] cookie: 恢复保护属性失败");

    cookie_patched = 1;
    fprintf(stderr, "[srvfix] 已打补丁：%p 处 je → jmp（无条件放行，不再校验 reservation cookie）\n",
            (void *)je);
    return 1;
}

/* ── 补丁 3：抹掉引擎自带的无效游戏模式名 "reserved" ───────────────────────
 *
 * 引擎在「已预留 → 直接开局」里拼的命令是 `map <地图> reserved`，第三个参数被当成
 * **游戏模式**去 gametypes 里查，而服务器没有叫 reserved 的模式：
 *
 *   GameTypes: could not find matching game mode value of "reserved" in any game type.
 *
 * 查不到 → 模式初始化不了 → 紧接着就是
 *   **** WARNING: Watchdog timer exceeded, aborting!        (退出码 134)
 *
 * 把格式串里的 "reserved" 抹成 8 个空格（**长度不变**，不用挪任何代码）：
 *
 *   engine.so 0x50cc3c:  "map %s reserved\n"  ->  "map %s         \n"
 *
 * 拼出来就是 `map de_cache` —— 和服务器启动参数里的 `+map de_cache` 同一种形式，
 * 已知可用。（尾部多几个空格，命令解析按空白分词，无影响。）
 *
 * 不直接改 engine.so 文件，仍走 LD_PRELOAD —— 保持"不碰游戏文件"这条性质。
 */
static const unsigned char MAPFMT[16] = {
    'm','a','p',' ','%','s',' ','r','e','s','e','r','v','e','d','\n'
};
static const unsigned char MAPFMT_NEW[16] = {
    'm','a','p',' ','%','s',' ',' ',' ',' ',' ',' ',' ',' ',' ','\n'
};

static int mapfmt_patched;

static int try_patch_mapfmt(void)
{
    if (mapfmt_patched) return 1;
    if (!g_lo) return 0;

    for (uintptr_t a = g_lo; a + sizeof(MAPFMT) <= g_hi; a++) {
        if (memcmp((const void *)a, MAPFMT, sizeof(MAPFMT)) != 0) continue;

        if (make_writable((void *)a, sizeof(MAPFMT)) != 0) {
            perror("[srvfix] mprotect(map 格式串) 失败");
            mapfmt_patched = 1;
            return 1;
        }
        memcpy((void *)a, MAPFMT_NEW, sizeof(MAPFMT));
        make_exec_only((void *)a, sizeof(MAPFMT));

        mapfmt_patched = 1;
        fprintf(stderr,
                "[srvfix] 已打补丁（3）：%p 处 \"map %%s reserved\" 改为 \"map %%s\" "
                "—— 去掉不存在的游戏模式 reserved（它导致 GameTypes 查不到模式，随后看门狗 abort）\n",
                (void *)a);
        return 1;
    }
    fprintf(stderr, "[srvfix] 警告：没找到 \"map %%s reserved\" 格式串，跳过补丁 3\n");
    mapfmt_patched = 1;
    return 1;
}

static void *worker(void *arg)
{
    (void)arg;
    for (int i = 0; i < 1200; i++) {        /* 最多 120 秒 */
        if (try_patch()) {
            try_patch_cookie();
            try_patch_mapfmt();          /* 补丁 3：抹掉无效模式名 reserved */
            if (cookie_patched) { g_done = 1; return NULL; }
        }
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
    fprintf(stderr, "[srvfix] 已注入（v3：cookie 放行 + 默认 NOP 掉引擎自带换图；"
                    "SRVFIX_DETOUR=1 可切回 detour 桩），等引擎加载..\n");

    pthread_t t;
    if (pthread_create(&t, NULL, worker, NULL) != 0) {
        fprintf(stderr, "[srvfix] 起线程失败\n");
        return;
    }
    pthread_detach(t);
}
