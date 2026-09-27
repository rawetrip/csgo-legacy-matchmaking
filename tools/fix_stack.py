"""把 csgc launcher 的 SizeOfStackReserve 从 1MB 改成 2MB。

根因：引擎的 netchannel 虚方法（engine RVA 0x253D80）入口是
    mov eax, 0x100138      ; 帧大小 = 1,049,656 字节
    call __chkstk
而 csgc launcher 的栈只有 0x100000 = 1,048,576 字节 —— 差 1080 字节就爆。
CS:GO 原版 launcher 用的是 0x180000 = 1.5MB，所以原版没问题。

这里只改 PE 可选头里的一个 4 字节字段，不重编、不动其他任何东西。
"""
import shutil
import struct
import sys

SRC = r"C:\Users\Administrator\csgc-install\csgo.exe"
DST = r"C:\Program Files (x86)\Steam\steamapps\common\csgo legacy\csgo.exe"
NEW_RESERVE = 0x200000        # 2MB，比需要的 0x100138 宽裕

d = bytearray(open(SRC, "rb").read())
pe = struct.unpack_from("<I", d, 0x3C)[0]
assert d[pe:pe + 4] == b"PE\0\0", "不是 PE"
opt = pe + 24
magic = struct.unpack_from("<H", d, opt)[0]
assert magic == 0x10B, "不是 PE32（magic=%#x）" % magic

# PE32 可选头里 SizeOfStackReserve 在偏移 72 处（可选头内）
off_reserve = opt + 72
off_commit = opt + 76
old_reserve = struct.unpack_from("<I", d, off_reserve)[0]
old_commit = struct.unpack_from("<I", d, off_commit)[0]
print("原来的 SizeOfStackReserve = %#x (%d)" % (old_reserve, old_reserve))
print("原来的 SizeOfStackCommit  = %#x (%d)" % (old_commit, old_commit))

struct.pack_into("<I", d, off_reserve, NEW_RESERVE)
print("改成 %#x (%d)" % (NEW_RESERVE, NEW_RESERVE))

open(DST, "wb").write(d)
print("已写入 %s" % DST)

# 复核
chk = open(DST, "rb").read()
pe2 = struct.unpack_from("<I", chk, 0x3C)[0]
print("复核：SizeOfStackReserve = %#x" % struct.unpack_from("<I", chk, pe2 + 24 + 72)[0])
