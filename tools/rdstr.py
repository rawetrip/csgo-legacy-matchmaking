"""Dump C strings at given RVAs, and search for literal strings, in client.dll.

usage: py rdstr.py 10c08b94 10c15b10 ...        # dump strings at RVAs
       py rdstr.py -s "ServerReserved" ...      # search literals (count + locations)
"""
import os
import sys
import struct

PATH = os.environ.get(
    "DLL",
    r"C:\Program Files (x86)\Steam\steamapps\common\csgo legacy\csgo\bin\client.dll")
data = open(PATH, "rb").read()
pe = struct.unpack_from("<I", data, 0x3C)[0]
nsec = struct.unpack_from("<H", data, pe + 6)[0]
optsize = struct.unpack_from("<H", data, pe + 20)[0]
opt = pe + 24
imagebase = struct.unpack_from("<I", data, opt + 28)[0]
secoff = opt + optsize
secs = []
for i in range(nsec):
    o = secoff + i * 40
    name = data[o:o + 8].rstrip(b"\0").decode("ascii", "replace")
    vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, o + 8)
    secs.append((name, vaddr, vsize, rawptr, rawsize))


def rva2off(rva):
    for name, vaddr, vsize, rawptr, rawsize in secs:
        if vaddr <= rva < vaddr + max(vsize, rawsize):
            return rawptr + (rva - vaddr), name
    return None, None


def rva2off_raw(rva):
    """only if backed by file data (not bss)"""
    for name, vaddr, vsize, rawptr, rawsize in secs:
        if vaddr <= rva < vaddr + rawsize:
            return rawptr + (rva - vaddr), name
    return None, None


def off2rva(off):
    """file offset -> RVA. NOTE: rawptr is NOT always == vaddr (engine.dll .rdata
    differs by 0xE00), so never feed an offset into rva2off*()."""
    for name, vaddr, vsize, rawptr, rawsize in secs:
        if rawptr <= off < rawptr + rawsize:
            return vaddr + (off - rawptr), name
    return None, None


if "-s" in sys.argv:
    for arg in sys.argv[sys.argv.index("-s") + 1:]:
        b = arg.encode()
        hits = []
        idx = 0
        while True:
            i = data.find(b, idx)
            if i < 0:
                break
            hits.append(i)
            idx = i + 1
        print("\n== literal %r : %d hit(s) ==" % (arg, len(hits)))
        for h in hits[:25]:
            o, sec = off2rva(h)
            print("   file %08x -> RVA %08x  .%s" % (h, o or 0, sec or "?"))
        if len(hits) > 25:
            print("   ... %d more" % (len(hits) - 25))
    sys.exit()

for arg in sys.argv[1:]:
    rva = int(arg, 16)
    o, sec = rva2off_raw(rva)
    if o is None:
        o2, sec2 = rva2off(rva)
        print("%08x  .%s  NOT FILE-BACKED (bss/runtime)" % (rva, sec2 or "?"))
        continue
    end = data.find(b"\0", o)
    s = data[o:end]
    try:
        txt = s.decode("utf-8")
    except UnicodeDecodeError:
        txt = repr(s)
    print("%08x  .%-7s  %r" % (rva, sec, txt[:120]))
