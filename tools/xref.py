"""Find xrefs to a RVA in a 32-bit PE: dword pointers (vtables/IAT) + rel32 call/jmp.

usage: py xref.py 427FD0 45613 ...
"""
import os
import sys
import struct
import numpy as np

PATH = os.environ.get(
    "DLL",
    r"C:\Program Files (x86)\Steam\steamapps\common\csgo legacy\csgo\bin\client.dll")


def main():
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

    def off2rva(off):
        for name, vaddr, vsize, rawptr, rawsize in secs:
            if rawptr <= off < rawptr + rawsize:
                return vaddr + (off - rawptr), name
        return None, None

    print("ImageBase = %08x" % imagebase)

    # pre-scan every E8/E9 in .text once
    tname, tvaddr, tvsize, trawptr, trawsize = [s for s in secs if s[0] == ".text"][0]
    text = data[trawptr:trawptr + trawsize]
    arr = np.frombuffer(text, dtype=np.uint8)
    cand = np.where((arr == 0xE8) | (arr == 0xE9))[0]
    print(".text RVA %x raw %x size %x | E8/E9 candidates: %d" % (tvaddr, trawptr, trawsize, len(cand)))

    for arg in sys.argv[1:]:
        rva = int(arg, 16)
        print("\n================ xrefs to RVA %x ================" % rva)

        # 1) absolute dword pointers (VA form, PE standard)
        tgt_va = imagebase + rva
        for label, pat in (("dword VA ", struct.pack("<I", tgt_va)),
                           ("dword RVA", struct.pack("<I", rva))):
            hits = []
            idx = 0
            while True:
                i = data.find(pat, idx)
                if i < 0:
                    break
                hits.append(i)
                idx = i + 1
            print("  %s (%08x): %d" % (label, struct.unpack("<I", pat)[0], len(hits)))
            for h in hits[:20]:
                r, sec = off2rva(h)
                ctx = data[max(0, h - 4):h + 8].hex()
                print("     file %08x -> RVA %08x  .%s   [.. %s ..]" % (h, r or 0, sec or "?", ctx))

        # 2) rel32 call/jmp
        print("  rel32 call/jmp:")
        n = 0
        for pos in cand:
            rel = struct.unpack_from("<i", text, pos + 1)[0]
            src_rva = tvaddr + int(pos)
            if src_rva + 5 + rel == rva:
                op = "call" if text[pos] == 0xE8 else "jmp "
                print("     %s at RVA %08x" % (op, src_rva))
                n += 1
        if n == 0:
            print("     (none)")


main()
