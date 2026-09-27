"""从 CS:GO 的 pak01 VPK 里取出指定文件（只读）。

用法: py vpk_get.py <vpk内路径,如 resource/csgo_english.txt> [输出文件]
VPK v2 格式（简化）:
  dir 文件头: sig(0x55AA1234) ver u32 treeSize u32 [fileDataSize u32 archiveMD5Size u32 ...]
  tree: 一串以 \\0 结尾的路径段；空串=该扩展名段结束
        条目: crc u32 preloadBytes u16 archiveIndex u16 entryOffset u32 entryLength u32
              terminator u16  [preload 数据]
"""
import os
import struct
import sys

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\csgo legacy\csgo"
DIRVPK = os.path.join(GAME, "pak01_dir.vpk")


def read_tree(data):
    sig, ver, treesz = struct.unpack_from("<III", data, 0)
    pos = 28 if ver == 2 else 8   # v2 表头是 28 字节
    entries = []
    while True:
        end = data.find(b"\x00", pos)
        if end < 0:
            break
        ext = data[pos:end].decode("ascii", "replace")
        pos = end + 1
        if ext == "":
            break
        while True:
            end = data.find(b"\x00", pos)
            if end < 0:
                return entries
            apath = data[pos:end].decode("ascii", "replace")
            pos = end + 1
            if apath == "":
                break
            end = data.find(b"\x00", pos)
            name = data[pos:end].decode("ascii", "replace")
            pos = end + 1
            crc, preload, arch, off, ln = struct.unpack_from("<IHHII", data, pos)
            pos += 16
            term = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            pre = data[pos:pos + preload]
            pos += preload
            full = (apath + "/" if apath != " " else "") + name + ("." + ext if ext != " " else "")
            entries.append((full, arch, off, ln, pre))
    return entries


def get(inner, out=None):
    data = open(DIRVPK, "rb").read()
    sig, ver, treesz = struct.unpack_from("<III", data, 0)
    print("VPK ver=%d treeSize=%d dirSize=%d" % (ver, treesz, len(data)))
    ents = read_tree(data)
    print("树里 %d 个条目" % len(ents))
    want = inner.lower().replace("\\", "/")
    for full, arch, off, ln, pre in ents:
        if full.lower() == want:
            print("找到: %s  archive=%d off=%#x len=%d preload=%d" % (full, arch, off, ln, len(pre)))
            blob = bytearray(pre)
            if ln:
                if arch == 0x7FFF:
                    src = data
                else:
                    src = open(os.path.join(GAME, "pak01_%03d.vpk" % arch), "rb").read()
                blob += src[off:off + ln]
            if out:
                open(out, "wb").write(bytes(blob))
                print("已写出 %s (%d 字节)" % (out, len(blob)))
            return bytes(blob)
    print("没找到 %s" % inner)
    return None


if __name__ == "__main__":
    get(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
