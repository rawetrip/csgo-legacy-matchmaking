"""把「比赛已准备完毕」弹窗改成官方的休闲（公告式）形态。

三处改动：
 1. 数据块（标题 + 模式·地图）移到地图图**之前** —— 休闲版是「文字在上、小地图在下」，
    而原 XML 是竞技版顺序（地图在上、标题居中压着它）。
 2. 隐藏假阵容（id-map-draft-phase-teams）。
 3. 隐藏 0/10 计数行（accept-match__slots-count）。

★ 只隐藏、不删节点：popup_accept_match.js 会对这些面板做
  RemoveAndDeleteChildren() / SetDialogVariableInt() / RemoveClass('hidden')，
  节点不存在会直接抛异常，把弹窗/UI 状态搞坏（踩过）。
  id 一律保留，用内联 style="visibility:collapse" 盖住。
"""
import sys
import xml.etree.ElementTree as ET

SRC = r"C:\Users\Administrator\popup_accept_orig.xml"
DST = r"C:\Users\Administrator\popup_accept_new.xml"

REPL = [
    # 假阵容（两队 + 假 XUID 头像）
    (b'<Panel id="id-map-draft-phase-teams" class="map-draft-phase-teams">',
     b'<Panel id="id-map-draft-phase-teams" class="map-draft-phase-teams" style="visibility:collapse;">'),
    # "0/10 已接受" 计数行（含 AcceptMatchSlots / AcceptMatchPlayersAccepted）
    (b'<Panel class="accept-match__slots-count">',
     b'<Panel class="accept-match__slots-count" style="visibility:collapse;">'),
]

data = open(SRC, "rb").read()
for old, new in REPL:
    n = data.count(old)
    if n != 1:
        sys.exit("锚点 %r 出现 %d 次，放弃" % (old[:40], n))
    data = data.replace(old, new)

# ---------------------------------------------------------------- 交换两个面板
MAP = b'<Panel id="AcceptMatchMapImage" class="accept-match__map"/>'
DATA = b'<Panel id="AcceptMatchDataContainer" class="accept-match__data">'

i_map = data.index(MAP)
i_data = data.index(DATA)
if i_map > i_data:
    sys.exit("顺序已经是对的（地图在数据之后），无需交换")

# 数据块的结束位置：从 DATA 开始数 <Panel / </Panel>，配平处即结束。
# ★ 自闭合的 <Panel .../>（数据块里那个分隔条就是）必须只计 +0/-0，
#   否则永远配不平，会把后面整份文档都吃掉。
k = i_data
depth = 0
while True:
    a = data.find(b"<Panel", k)
    b = data.find(b"</Panel>", k)
    if b < 0:
        sys.exit("数据块没有配平的 </Panel>，放弃")
    if 0 <= a < b:
        gt = data.index(b">", a)
        if data[gt - 1:gt] != b"/":      # 不是自闭合才 +1
            depth += 1
        k = gt + 1
    else:
        depth -= 1
        k = b + len(b"</Panel>")
        if depth == 0:
            break
i_end = k

data_block = data[i_data:i_end]
map_block = data[i_map:i_data]
sep = b"\r\n\t\t\t\t" if b"\r\n" in data[:200] else b"\n\t\t\t\t"

data = data[:i_map] + data_block + sep + map_block.rstrip() + data[i_end:]

# ---------------------------------------------------------------- 回读校验
root = ET.fromstring(data)
ids = [e.get("id") for e in root.iter() if e.get("id")]
for must in ("id-map-draft-phase-teams", "AcceptMatchSlots",
             "AcceptMatchPlayersAccepted", "AcceptMatchBtn",
             "id-map-draft-phase-avatars", "AcceptMatchCountdown",
             "AcceptMatchModeMap", "AcceptMatchMapImage",
             "AcceptMatchDataContainer"):
    assert must in ids, "id %s 丢了！" % must
assert data.index(MAP) > data.index(DATA), "交换没生效"
print("XML 解析 OK，%d 个 id 全在；数据块已移到地图之前，新增 %d 字节"
      % (len(ids), len(data) - len(open(SRC, "rb").read())))
open(DST, "wb").write(data)
print("已写出 %s" % DST)
