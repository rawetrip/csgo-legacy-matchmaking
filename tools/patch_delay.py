"""把 csgc 的连接延时从 8s 改成 5s（对齐 CS2：弹窗只出现约 5 秒）。

源码是 GBK，全程 bytes 级替换，不解码、不重编码。
"""
import sys

PATH = r"C:\Users\Administrator\csgc-src\src\steam_hook_lite.cpp"

REPL = [
    (b"Sleep(8000);    // keep the 'confirming match' window the user wants to see",
     b"Sleep(5000);    // ~5s window, matching CS2's accept prompt"),
]

data = open(PATH, "rb").read()
for old, new in REPL:
    if data.count(new) == 1:
        sys.exit("看起来已经改过了")
    n = data.count(old)
    if n != 1:
        sys.exit("锚点出现 %d 次，放弃: %r" % (n, old[:40]))
    data = data.replace(old, new)

assert data.count(b"Sleep(5000)") == 1
open(PATH, "wb").write(data)
print("已改：连接延时 8s -> 5s")
