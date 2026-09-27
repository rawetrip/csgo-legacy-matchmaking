"""Unpack / repack csgo/panorama/code.pbin.

Layout: 16-byte header (magic 'PAN\x02') + standard zip (all entries stored) +
32-byte trailing comment ('XZP1 ...'). Both the header and the comment must be
preserved byte-for-byte on repack.

usage:
  py pbin_tool.py ls                       # list entries
  py pbin_tool.py get <entry> <outfile>    # extract one entry
  py pbin_tool.py put <entry> <infile>     # replace one entry in place (makes .bak)
"""
import io
import os
import shutil
import sys
import zipfile

PBIN = r"C:\Program Files (x86)\Steam\steamapps\common\csgo legacy\csgo\panorama\code.pbin"


def load():
    raw = open(PBIN, "rb").read()
    zstart = raw.find(b"PK\x03\x04")     # 0x204 in practice, not 16
    assert zstart > 0, "no local file header"
    zend = raw.rfind(b"PK\x05\x06")
    assert zend > 0, "no end-of-central-directory"
    comment_len = int.from_bytes(raw[zend + 20:zend + 22], "little")
    zip_end = zend + 22 + comment_len
    return raw, raw[:zstart], raw[zstart:zip_end], raw[zip_end:]


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ls"
    raw, header, zipbytes, tail = load()
    print("file=%d bytes  header=%s  zip=%d  tail=%d (%s)"
          % (len(raw), header.hex(" "), len(zipbytes), len(tail), tail[:8]))

    if cmd == "ls":
        zf = zipfile.ZipFile(io.BytesIO(zipbytes))
        for n in zf.namelist():
            i = zf.getinfo(n)
            print("  %-70s %8d  compress=%d" % (n, i.file_size, i.compress_type))
        return

    if cmd == "get":
        entry, outp = sys.argv[2], sys.argv[3]
        zf = zipfile.ZipFile(io.BytesIO(zipbytes))
        open(outp, "wb").write(zf.read(entry))
        print("wrote %s (%d bytes)" % (outp, os.path.getsize(outp)))
        return

    if cmd == "put":
        entry, inp = sys.argv[2], sys.argv[3]
        newdata = open(inp, "rb").read()
        zf = zipfile.ZipFile(io.BytesIO(zipbytes))
        infos = zf.infolist()
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zo:
            for i in infos:
                data = newdata if i.filename == entry else zf.read(i.filename)
                zi = zipfile.ZipInfo(i.filename, date_time=i.date_time)
                zi.compress_type = zipfile.ZIP_STORED   # keep everything stored
                zi.external_attr = i.external_attr
                zo.writestr(zi, data)
        newzip = out.getvalue()
        shutil.copy2(PBIN, PBIN + ".bak")
        open(PBIN, "wb").write(header + newzip + tail)
        print("replaced %r (%d -> %d bytes); total %d -> %d; backup at %s.bak"
              % (entry, zf.getinfo(entry).file_size, len(newdata),
                 len(raw), len(header) + len(newzip) + len(tail), PBIN))
        return

    sys.exit("unknown command %r" % cmd)


main()
