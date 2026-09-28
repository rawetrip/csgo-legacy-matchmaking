"""给 csgc 加「收到 9101 MatchmakingStart 就重新武装连接闸门」。

源码是 GBK，这里全程按 bytes 处理，绝不解码/重编码，保证不碰坏中文注释。

背景：ScheduleConnect() 里 `InterlockedExchange(&g_connectScheduled, 1)` 是一次性的，
第一次 9107 之后所有 9107 都被 "[CONN] duplicate 9107 ignored" 挡掉，
所以第二次点「开始竞技」永远不会再连服。

插入点为 SendMessage 里那行判断（纯 ASCII，唯一）：
    if (unMsgType == 0x8000238E) CaptureBacktrace(
9101 带高位 = 0x8000238D（9102 = 0x8000238E，与现有代码一致）。
"""
import sys

PATH = r"C:\Users\Administrator\csgc-src\src\steam_hook_lite.cpp"
ANCHOR = b"        if (unMsgType == 0x8000238E) CaptureBacktrace("

INSERT = b"""        // [custom] A fresh 9101 MatchmakingStart means the player began a new
        // search; re-arm the one-shot connect so the next reservation connects too.
        // (Without this, the second click is swallowed by "duplicate 9107 ignored".)
        if (unMsgType == 0x8000238D) {
            InterlockedExchange(&g_connectScheduled, 0);
            g_connectFired = 0;
            GCLog("[CONN] 9101 MatchmakingStart: connect re-armed\\n");
        }

"""

data = open(PATH, "rb").read()
n = data.count(ANCHOR)
print("锚点出现次数: %d" % n)
if n != 1:
    sys.exit("锚点不唯一或不存在，放弃")

if b"9101 MatchmakingStart: connect re-armed" in data:
    sys.exit("看起来已经打过补丁了")

i = data.index(ANCHOR)
out = data[:i] + INSERT + data[i:]
open(PATH, "wb").write(out)
print("已插入 %d 字节" % len(INSERT))
