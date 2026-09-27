"""在 hook 里加：引擎取走 9107 / 发出 9102(MatchmakingStop) 时抓调用栈。

目的：静态找不到 9107 的分发点（消息号不是立即数，只出现在数据表里）。
但 csgc.dll 在进程内，可以在两个关键时刻抓栈：
  - RetrieveMessage 且 type == 9107  → 引擎**消费** 9107 的位置
  - SendMessage   且 type == 9102   → 引擎**决定放弃匹配**的位置（最有价值）

用 RtlCaptureStackBackTrace（ntdll，运行时取地址），把每帧解析成"模块+偏移"。
注意：源文件是 GBK，用 GBK 读写；字符串里的 \\n 用 chr(92)+'n' 拼，避免被转义吃掉。
"""
import io

P = r"C:\Users\Administrator\csgc-src\src\steam_hook_lite.cpp"
s = io.open(P, encoding="gbk", errors="replace").read()
NL = chr(92) + "n"

if "CaptureBacktrace" in s:
    raise SystemExit("已经加过了")

BLOCK = (
"// [自定义] 抓调用栈：静态找不到 9107 的分发点（消息号只以数据形式存在），\n"
"// 但我们在进程内，可以在关键时刻抓栈并解析成 模块+偏移。\n"
"typedef USHORT (WINAPI *RtlCaptureStackBackTrace_t)(ULONG, ULONG, PVOID*, PULONG);\n"
"static void CaptureBacktrace(const char *why)\n"
"{\n"
"    static RtlCaptureStackBackTrace_t pCapture = nullptr;\n"
"    if (!pCapture) {\n"
"        HMODULE nt = GetModuleHandleA(\"ntdll.dll\");\n"
"        if (nt) pCapture = (RtlCaptureStackBackTrace_t)GetProcAddress(nt, \"RtlCaptureStackBackTrace\");\n"
"    }\n"
"    if (!pCapture) { GCLog(\"[BT] %s: 拿不到 RtlCaptureStackBackTrace\\n\", why); return; }\n"
"    void *frames[24] = {0};\n"
"    USHORT n = pCapture(0, 24, frames, nullptr);\n"
"    GCLog(\"[BT] ===== %s（%u 帧）=====\\n\", why, (unsigned)n);\n"
"    for (USHORT i = 0; i < n; i++) {\n"
"        HMODULE mod = nullptr;\n"
"        if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |\n"
"                               GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,\n"
"                               (LPCSTR)frames[i], &mod) && mod) {\n"
"            char path[MAX_PATH] = {0};\n"
"            GetModuleFileNameA(mod, path, MAX_PATH);\n"
"            const char *base = strrchr(path, '\\\\');\n"
"            GCLog(\"[BT]   #%02u %p  %s+0x%llX\\n\", i, frames[i], base ? base + 1 : path,\n"
"                  (unsigned long long)((uintptr_t)frames[i] - (uintptr_t)mod));\n"
"        } else {\n"
"            GCLog(\"[BT]   #%02u %p  <未知>\\n\", i, frames[i]);\n"
"        }\n"
"    }\n"
"}\n\n"
)

# 放在 RetrieveMessage 那个类之前（用 GCLog 之前先声明）
anchor = "class GameCoordinatorProxyLite final : public ISteamGameCoordinator"
if anchor not in s:
    raise SystemExit("找不到 GC 代理类")
s = s.replace(anchor, BLOCK + anchor, 1)

# 1) 引擎发 9102 时抓栈
old_send = 'GCLog("[GC] SendMessage: type=0x%08X, size=%u, steamId=%llu' + NL + '",'
new_send = ('if (unMsgType == 0x8000238E) CaptureBacktrace("引擎发出 9102 MatchmakingStop");   // 决定放弃匹配的地方' + NL +
            '        GCLog("[GC] SendMessage: type=0x%08X, size=%u, steamId=%llu' + NL + '",')
if old_send not in s:
    raise SystemExit("SendMessage 的日志行没对上")
s = s.replace(old_send, new_send, 1)

# 2) 引擎取走 9107 时抓栈
old_ret = 'GCLog("[GC] RetrieveMessage: type=%u, size=%u' + NL + '", *punMsgType, *pcubMsgSize);'
new_ret = ('if (*punMsgType == 2147492755u) CaptureBacktrace("引擎取走 9107 GC2ClientReserve");' + NL +
           '        GCLog("[GC] RetrieveMessage: type=%u, size=%u' + NL + '", *punMsgType, *pcubMsgSize);')
if old_ret not in s:
    raise SystemExit("RetrieveMessage 的日志行没对上")
s = s.replace(old_ret, new_ret, 1)

io.open(P, "w", encoding="gbk", errors="replace", newline="").write(s)
print("已加：9102 发送时 + 9107 取走时 各抓一份调用栈")
