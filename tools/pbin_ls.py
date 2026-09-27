"""Read-only poke at code.pbin: it is a plain zip behind a 16-byte "PAN\x02" header."""
import io
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PBIN = r"C:\Program Files (x86)\Steam\steamapps\common\csgo legacy\csgo\panorama\code.pbin"

raw = open(PBIN, "rb").read()
print("magic:", raw[:4].hex(" "), "  hdr16:", raw[:16].hex(" "))

bio = io.BytesIO(raw)
zf = zipfile.ZipFile(bio)
names = zf.namelist()
print("entries:", len(names))

hits = []
for n in names:
    try:
        data = zf.read(n)
    except Exception as e:
        print("  !! read fail %s: %s" % (n, e))
        continue
    if b"ServerReserved" in data or b"ShowMatchAcceptPopUp" in data:
        hits.append((n, len(data), data.count(b"ServerReserved")))

print("\n=== files mentioning ServerReserved / ShowMatchAcceptPopUp ===")
for n, sz, c in hits:
    print("  %-60s %7d bytes  ServerReserved x%d" % (n, sz, c))

print("\n=== zip info sample ===")
for n in names[:3]:
    i = zf.getinfo(n)
    print("  %s compress=%d size=%d csize=%d" % (i.filename, i.compress_type, i.file_size, i.compress_size))
