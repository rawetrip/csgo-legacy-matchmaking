"""在 Linux srcds 的 engine.so 里定位 reservation 相关字符串的虚拟地址。

usage: py vmssh.py "python3 /tmp/srvre.py"
"""
import struct
import sys

PATH = "/home/csgo/csgo-server/bin/engine.so"
data = open(PATH, "rb").read()
assert data[:4] == b"\x7fELF"

e_shoff = struct.unpack_from("<Q", data, 0x28)[0]
e_shentsize = struct.unpack_from("<H", data, 0x3A)[0]
e_shnum = struct.unpack_from("<H", data, 0x3C)[0]
e_shstrndx = struct.unpack_from("<H", data, 0x3E)[0]

def read_sh(i):
    off = e_shoff + i * e_shentsize
    name, typ, flags, addr, offset, size = struct.unpack_from("<IIQQQQ", data, off)
    link, info = struct.unpack_from("<II", data, off + 0x28)
    return dict(namoff=name, typ=typ, addr=addr, offset=offset, size=size, link=link, info=info)

sec0 = read_sh(0)
if e_shnum == 0:
    e_shnum = sec0["size"]
if e_shstrndx == 0xFFFF:
    e_shstrndx = sec0["link"]
print("e_shoff=%#x entsize=%d shnum=%d shstrndx=%d" % (e_shoff, e_shentsize, e_shnum, e_shstrndx))

secs = [read_sh(i) for i in range(e_shnum)]
shstr = secs[e_shstrndx]


def sname(n):
    s = data[shstr["offset"] + n:]
    return s[: s.index(b"\0")].decode(errors="replace")


for s in secs:
    s["sname"] = sname(s["namoff"])

SHT_NOBITS = 8


def off2va(o):
    for s in secs:
        if s["typ"] != SHT_NOBITS and s["offset"] <= o < s["offset"] + s["size"]:
            return s["addr"] + (o - s["offset"]), s["sname"]
    return None, None


def va2off(va):
    for s in secs:
        if s["typ"] != SHT_NOBITS and s["addr"] <= va < s["addr"] + s["size"]:
            return s["offset"] + (va - s["addr"]), s["sname"]
    return None, None


NEEDLES = [
    b"-> Reservation cookie",
    b"reserved(%s), clients(%s), reservationexpires(%.2f)",
    b"[R] Connect from %s",
    b"Rejecting connection request from %s, client's reservation cookie",
    b"Rejecting connection request from %s (reservation cookie 0x%llx)",
    b"#Valve_Reject_Connect_From_Lobby",
    b"#Valve_Reject_Reserved_For_Lobby",
    b"ReplyReservationRequest",
    b"map %s reserved",
    b"Reservation response to %s",
    b"sv_mmqueue_reservation",
    b"sv_reservation_timeout",
    b"sv_reservation_grace",
    b"[SESSION] Updating reservation cookie: %llx, keeping %d players.",
    b"Server confirmed all players reservation%u/%d",
    b"Server reservation%u is awaiting %d/%d",
]

for n in NEEDLES:
    pos = 0
    hits = []
    while True:
        i = data.find(n, pos)
        if i < 0:
            break
        va, sn = off2va(i)
        hits.append("off=%#x va=%s sec=%s" % (i, hex(va) if va else "?", sn))
        pos = i + 1
    print("%-70s %s" % (n.decode(errors="replace")[:68], " | ".join(hits) or "NOT FOUND"))

print("\n--- 节表（只看有地址的 PROGBITS）---")
for s in secs:
    if s["typ"] != SHT_NOBITS and s["addr"]:
        print("%-20s addr=%#010x off=%#010x size=%#x" % (s["sname"], s["addr"], s["offset"], s["size"]))
