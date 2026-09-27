"""补回被误删的 CMsgGCCStrike15_v2_Server2GCClientValidate (9153) 处理器。

原版 git 里没有这个（是用户自己加的），所以按之前读到的内容重建。
作用：玩家连入服务器时，服务器会来问"这人合法吗"，GC 回 9105 告知这是匹配局。
"""
import io

P = r"C:\Users\Administrator\gc-replacement\Server_v3.js"
s = io.open(P, encoding="utf-8").read()

if "events.on('CMsgGCCStrike15_v2_Server2GCClientValidate'" in s:
    raise SystemExit("已经有了，不用补")

BLOCK = r'''// [自定义] 玩家连入服务器时，服务器会来问"这人合法吗"（9153）。
// 原项目直接忽略；我们回 9105 GC2ServerReserve，告知服务器这属于一局匹配。
// 这是 GC 唯一能"主动影响服务器"的通道（因为是服务器先来问的）。
events.on('CMsgGCCStrike15_v2_Server2GCClientValidate', (data, socket, steamid) => {
    const accountId = Number(data && data.accountid) || 0;
    console.log(`[SERVER] Server2GCClientValidate: account ${accountId}`);
    try {
        sendProto(socket, 9105, 'CMsgGCCStrike15_v2_MatchmakingGC2ServerReserve', {
            accountIds: accountId ? [accountId] : [],
            gameType: 0,
            matchId: MATCH_ID,
            serverVersion: Number(SERV_VER) || 13881,
            rankings: [],
            encryptionKey: Math.floor(Math.random() * 1000000),
            encryptionKeyPub: Math.floor(Math.random() * 1000000),
            whitelist: [],
            preMatchData: { teamStats: [], draft: [], stats: [], wins: 0 }
        });
        console.log('[SERVER] 已回 GC2ServerReserve（告知服务器这是匹配局）');
    } catch (e) {
        console.error(`[ERROR] GC2ServerReserve 构造失败: ${e.message}`);
    }
});

'''

anchor = "events.on('CMsgGCCStrike15_v2_GetEventFavorites_Request'"
if anchor not in s:
    raise SystemExit("找不到锚点")
s = s.replace(anchor, BLOCK + anchor, 1)
io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("已补回 Server2GCClientValidate")
