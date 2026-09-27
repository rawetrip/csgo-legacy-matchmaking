"""从 git 原版重建被我误删的三个 handler，并把已知的修改重新应用上去。

丢失的：CMsgClientHello / MatchmakingStart / MatchmakingClient2ServerPing
（9106 那一段也被改花了，一并从原版恢复）

已知需要重新应用的修改：
  1. gscookieid / uniqueid: 1488 -> GC_COOKIE（与服务器端统一）
  2. MatchmakingStart: data.game_type -> data.gameType（驼峰，否则恒 undefined）
     + 记录 mmGameType（直接落盘 + 同步 map）
     + 打印客户端上报的 lobby_id 与全字段
  3. MatchmakingClient2ServerPing: 打印 9103 全字段/候选服务器数；
     用 session.mmGameType 覆盖（9103 里恒为 0）；然后下发 9107
"""
import io
import subprocess

REPO = r"C:\Users\Administrator\gc-replacement"
CUR = REPO + r"\Server_v3.js"

head = subprocess.check_output(
    ["git", "show", "HEAD:Server_v3.js"], cwd=REPO).decode("utf-8")
hlines = head.split("\n")


def grab(name):
    """从原版里取出某个 events.on('name'...) 到下一个 events.on 之间的整块。"""
    start = None
    for i, l in enumerate(hlines):
        if l.startswith("events.on('" + name + "'"):
            start = i
            break
    if start is None:
        raise SystemExit("原版里找不到 handler: " + name)
    end = len(hlines)
    for j in range(start + 1, len(hlines)):
        if hlines[j].startswith("events.on("):
            end = j
            break
    # 往前吞掉紧挨着的注释行
    while start > 0 and hlines[start - 1].strip().startswith("//"):
        start -= 1
    return "\n".join(hlines[start:end]).rstrip()


client_hello = grab("CMsgClientHello")
mm_start = grab("CMsgGCCStrike15_v2_MatchmakingStart")
mm_ping = grab("CMsgGCCStrike15_v2_MatchmakingClient2ServerPing")

print("取到: ClientHello %d 行, MatchmakingStart %d 行, Ping %d 行"
      % (client_hello.count("\n"), mm_start.count("\n"), mm_ping.count("\n")))

# ---- 修改 1：cookie 统一 ----
client_hello = client_hello.replace("gscookieid: 1488", "gscookieid: GC_COOKIE")
client_hello = client_hello.replace("uniqueid: 1488", "uniqueid: GC_COOKIE")

# ---- 修改 2：MatchmakingStart ----
mm_start = mm_start.replace(
    "const gameType = data?.game_type || 0;",
    "// [修复] protobufjs 解出来是驼峰 gameType，写 data.game_type 恒为 undefined\n"
    "    const gameType = data?.gameType ?? data?.game_type ?? 0;\n"
    "    console.log(`[MATCH] MatchmakingStart gameType=${gameType}`);\n"
    "    const lobbyIdRaw = data?.lobbyId ?? data?.lobby_id;\n"
    "    console.log(`[MATCH] MatchmakingStart 全字段: ${JSON.stringify(data)}`);\n"
    "    console.log(`[MATCH] >>> 客户端上报的 lobby_id = ${lobbyIdRaw === undefined ? '(未携带)' : lobbyIdRaw}`);")

old_save = "session.matchmaking = true;\n        savePlayer(AccountId);"
new_save = ("session.matchmaking = true;\n"
            "        // [修复] 记住客户端搜索用的 gameType。注意 loadPlayer 返回磁盘副本、\n"
            "        // savePlayer 存的是 sessions map 里那份，只改副本等于没改。\n"
            "        session.mmGameType = gameType;\n"
            "        const inMem = sessions.get(AccountId) ?? sessions.get(String(AccountId));\n"
            "        if (inMem) {\n"
            "            inMem.matchmaking = true;\n"
            "            inMem.mmGameType = gameType;\n"
            "            savePlayer(AccountId);\n"
            "        } else {\n"
            "            fs.writeFileSync(`${DATA_DIR}/${AccountId}.json`, JSON.stringify(session, null, 2));\n"
            "        }\n"
            "        console.log(`[MATCH] 已记录 mmGameType=${gameType}（account ${AccountId}）`);")
if old_save in mm_start:
    mm_start = mm_start.replace(old_save, new_save)
else:
    print("  !! MatchmakingStart 的 savePlayer 片段没对上，需手工确认")

# ---- 修改 3：Ping handler —— 打印 9103 + 用正确 gameType + 下发 9107 ----
PING_TAIL = r'''
    // [诊断] 把客户端上报的 9103 整个打出来。它带的是 dataCenterPings（数据中心延迟），
    // gameserverpings 为空是正常的 —— 协议里没有"GC 下发候选服务器"的消息。
    console.log(`[MATCH] 9103 全字段: ${JSON.stringify(data)}`);
    const pings = data?.gameserverping ?? data?.gameServerPing ?? [];
    console.log(`[MATCH] 9103 候选服务器数: ${Array.isArray(pings) ? pings.length : 'n/a'}`);

    // [修复] 9103 里的 gameType 恒为 0（这个包不带它），用 MatchmakingStart 记录的值
    const sess = loadPlayer(AccountId);
    if (sess && sess.mmGameType != null) gameType = sess.mmGameType;
    console.log(`[MATCH] 实际下发用 gameType=${gameType}`);

    // [自定义] 客户端 ping 完毕即下发服务器（原项目从不发这条）。
    // reservationid 必须与服务器手里的 reservation cookie 一致，否则连服被拒。
    // 注意：这里**不带 reservation 子消息** —— 实测引擎对带 reservation 的消息
    // 是明确拒绝的（连空的都崩），直连用的 9164 也是去掉它才通的。
    const reservationId = GC_COOKIE;
    console.log(`[MATCH] 下发服务器 ${MATCH_SERVER_IP}:${MATCH_SERVER_PORT} (map=${MATCH_MAP}) 给 ${AccountId}`);
    sendProto(socket, 9107, 'CMsgGCCStrike15_v2_MatchmakingGC2ClientReserve', {
        serverid: String(config.gsSteamId || '85568392936273507'),
        directUdpIp: ipToUint32(MATCH_SERVER_IP),
        directUdpPort: MATCH_SERVER_PORT,
        reservationid: reservationId,
        map: MATCH_MAP,
        serverAddress: `${MATCH_SERVER_IP}:${MATCH_SERVER_PORT}`
    });
});'''

# 原版 Ping handler 的结尾是 "});"，把它替换成「原体 + 新尾部」
mm_ping = mm_ping.rstrip()
assert mm_ping.endswith("});"), mm_ping[-80:]
mm_ping = mm_ping[:-3].rstrip("\n") + "\n" + PING_TAIL

# Ping handler 里 gameType 原本是 const，要能重新赋值
mm_ping = mm_ping.replace("const gameType = data?.gameType", "let gameType = data?.gameType")

# ---- 组装 ----
cur = io.open(CUR, encoding="utf-8").read()

anchor = "events.on('CMsgGCCStrike15_v2_GetEventFavorites_Request'"
if anchor not in cur:
    raise SystemExit("找不到插入锚点")
cur = cur.replace(anchor, client_hello + "\n\n" + mm_start + "\n\n" + mm_ping + "\n\n" + anchor, 1)

io.open(CUR, "w", encoding="utf-8", newline="\n").write(cur)
print("已插回三个 handler")
