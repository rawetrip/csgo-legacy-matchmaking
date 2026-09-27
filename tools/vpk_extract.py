"""Extract all sound entries from CS:GO's pak01 VPK set.

VPK v2 layout (all little-endian):
  header : magic 0x55aa1234 | version | tree_size
  tree   : repeated [ ext\0 [ path\0 [ name\0 crc preload_len archive_idx off len term ]* \0 ]* \0 ]
  data   : pak01_%03d.vpk, seek to `off` (plus preload bytes that live inline)

usage: py vpk_audio_extract.py [filter]     # filter defaults to "sound/"
"""
import os
import struct
import sys

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\csgo legacy\csgo"
DIRVPK = os.path.join(GAME, "pak01_dir.vpk")
OUT = r"C:\Users\Administrator\csgo_audio"
FILTER = (sys.argv[1] if len(sys.argv) > 1 else "sound/").lower()
if FILTER in ("wav","mp3"):
    pass

d = open(DIRVPK, "rb").read()
magic, ver, treesize = struct.unpack_from("<III", d, 0)
assert magic == 0x55AA1234, "not a VPK (magic %08x)" % magic
# VPK v2 has four extra section sizes after tree_size (data/archMd5/otherMd5/sig)
HDR = 28 if ver == 2 else 12
print("VPK version %d, tree %d bytes, header %d" % (ver, treesize, HDR))

entries = []          # (fullpath, archive_idx, offset, length, preload_bytes)
off = HDR
tree_end = HDR + treesize
while off < tree_end:
    e = d.index(b"\0", off)
    ext = d[off:e].decode("ascii", "replace")
    off = e + 1
    if ext == "":
        break
    while True:
        e = d.index(b"\0", off)
        path = d[off:e].decode("ascii", "replace")
        off = e + 1
        if path == "":
            break
        while True:
            e = d.index(b"\0", off)
            name = d[off:e].decode("ascii", "replace")
            off = e + 1
            if name == "":
                break
            crc, preload, arc, eoff, elen, term = struct.unpack_from("<IHHIIH", d, off)
            off += 18
            full = ("%s/%s.%s" % (path, name, ext)) if path else ("%s.%s" % (name, ext))
            pre = d[off:off + preload]
            off += preload
            if FILTER in full.lower():
                entries.append((full, arc, eoff, elen, pre))

print("matching entries: %d" % len(entries))
if not entries:
    sys.exit("nothing matched filter %r" % FILTER)

# group by archive so we only open each data vpk once
handles = {}
written = 0
total_bytes = 0
for full, arc, eoff, elen, pre in entries:
    dest = os.path.join(OUT, full.replace("/", os.sep))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        if pre:
            f.write(pre)
        if elen:
            if arc not in handles:
                p = os.path.join(GAME, "pak01_%03d.vpk" % arc)
                handles[arc] = open(p, "rb")
            h = handles[arc]
            h.seek(eoff)
            left = elen
            while left:
                chunk = h.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
    written += 1
    total_bytes += len(pre) + elen
    if written % 500 == 0:
        print("  ... %d files, %.1f MB" % (written, total_bytes / 1048576.0))

for h in handles.values():
    h.close()
print("done: %d files (%.1f MB) -> %s" % (written, total_bytes / 1048576.0, OUT))
