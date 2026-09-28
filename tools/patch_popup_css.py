"""把 accept-match 弹窗的地图背景区压矮，逼近官方休闲版（NQMM）的高度。

popup_accept_match.css 的 .accept-match__map 写死 height: 300px —— 那是竞技版
（带阵容区）的尺寸，自动就绪（官方 '@' 公告式）模式下没有阵容区，300px 就显得空大。

只改这一条高度，其余布局不动（改多了容易把 title 的垂直居中弄歪）。
"""
import sys

SRC = r"C:\Users\Administrator\popup_accept.css"
DST = r"C:\Users\Administrator\popup_accept_new.css"

# 注意：code.pbin 里的 CSS 是 CRLF 行尾，锚点必须带上 \r\n，否则一处都匹配不到
OLD = b".accept-match__map\r\n{\r\n\tvertical-align: center;\r\n\thorizontal-align: center;\r\n\twidth: 100%;\r\n\theight: 300px;"
NEW = b".accept-match__map\r\n{\r\n\tvertical-align: center;\r\n\thorizontal-align: center;\r\n\twidth: 100%;\r\n\theight: 150px;"

data = open(SRC, "rb").read()
n = data.count(OLD)
if n != 1:
    sys.exit("锚点出现 %d 次，放弃" % n)
data = data.replace(OLD, NEW)
assert b"height: 150px;" in data
open(DST, "wb").write(data)
print("CSS 已改：.accept-match__map 300px -> 150px（%d 字节）" % len(data))
