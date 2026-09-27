"""Disassemble a RVA range of client.dll (32-bit PE) with capstone.

usage: py disasm.py 422C70 422F20     # RVA start end
       py disasm.py --secs             # dump section table
"""
import os
import sys
import struct
import capstone

PATH = os.environ.get(
    "DLL",
    r"C:\Program Files (x86)\Steam\steamapps\common\csgo legacy\csgo\bin\client.dll")


def load():
    data = open(PATH, "rb").read()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    optsize = struct.unpack_from("<H", data, pe + 20)[0]
    secoff = pe + 24 + optsize
    secs = []
    for i in range(nsec):
        o = secoff + i * 40
        name = data[o:o + 8].rstrip(b"\0").decode("ascii", "replace")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, o + 8)
        secs.append((name, vaddr, vsize, rawptr, rawsize))
    return data, secs


data, secs = load()

if "--secs" in sys.argv:
    print("name      vaddr      vsize      rawptr     rawsize")
    for n, va, vs, rp, rs in secs:
        print("%-9s %08x   %08x   %08x   %08x" % (n, va, vs, rp, rs))
    sys.exit()


def rva2off(rva):
    for name, vaddr, vsize, rawptr, rawsize in secs:
        if vaddr <= rva < vaddr + max(vsize, rawsize):
            return rawptr + (rva - vaddr)
    return None


start = int(sys.argv[1], 16)
end = int(sys.argv[2], 16)
off = rva2off(start)
if off is None:
    sys.exit("rva %x not mapped" % start)

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True

for ins in md.disasm(data[off:off + (end - start)], start):
    tag = ""
    if ins.group(capstone.CS_GRP_JUMP) or ins.group(capstone.CS_GRP_CALL):
        try:
            op = ins.operands[0]
            if op.type == capstone.x86.X86_OP_IMM:
                tgt = op.imm
                tag = "-> %06x" % tgt
                if not (start <= tgt < end):
                    tag += "   <<< OUTSIDE"
        except (IndexError, capstone.CsError):
            pass
    text = "%s %s" % (ins.mnemonic, ins.op_str)
    print("%06x  %-22s %s%s" % (ins.address, ins.bytes.hex(), text, ("    " + tag) if tag else ""))
