// ⚠️ 本文件已脱敏（相对 gc-replacement/Server_v3.js 的可用副本）：
//     作者 SteamID64      -> 7656119XXXXXXXXXX
//     默认 accountId      -> 100000000
//     主机局域网 IP       -> HOST_LAN_IP
//     游戏服 SteamID      -> YOUR_GS_STEAMID
//     本机路径 / 用户名   -> 提成 config.json 的 csgoDir / vmSshPath
//                            （两项留空 = 外部换图通道不启用，默认如此）
//   官方 SteamID64 基准 76561197960265728 与 GameServerCookieId "Hello :)"
//   是公开常量，未替换。
//   （同步到 2026-09-29 的完整匹配流程版本 + ongoingmatch 那次试错与其回退原因。）
//
const net = require('node:net');
const protobuf = require('protobufjs');
const fs = require('fs');

// config settings

const CONFIG_FILE = './config.json'

let config;
try {
    config = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
    console.log('[Notification] loaded config file!')
} catch (err) {
    console.log('[Notification] config file not found! if its first start its okay')
    const default_config = {
        host: '127.0.0.1',
        port: 3257,
        PlayerData: './playerData',
        protoPath: './proto',
        devmode: false,
        serverVersion: '13881',
        serverIp: '0.0.0.0'
    }
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(default_config, null, 2));
    config = default_config;
    console.log('[Notification] created config file')
    console.log('[Advice] specify your ip in config file')
}

const root = protobuf.loadSync([
    `${config.protoPath}/base_gcmessages.proto`,
    `${config.protoPath}/cstrike15_gcmessages.proto`,
    `${config.protoPath}/econ_gcmessages.proto`,
    `${config.protoPath}/engine_gcmessages.proto`,
    `${config.protoPath}/gcsdk_gcmessages.proto`,
    `${config.protoPath}/gcsystemmsgs.proto`
]);

const DEVMODE = config.devmode; //debug mode
const DATA_DIR = config.PlayerData; //self-explanatory
const SERV_VER = config.serverVersion; //version that srcds requires
const SERV_IP = config.serverIp; //ip for srcds, not used at that moment

// [自定义] 匹配成功后要分配的自建服务器。原项目未实现此块，这里补上。
const MATCH_SERVER_IP = config.matchServerIp || 'HOST_LAN_IP';
const MATCH_SERVER_PORT = Number(config.matchServerPort || 27015);

// [2026-09-28 深夜] 服务器在「veto 环节」该加载的地图 —— **不是**正式比赛图。
//
// gamemodes.txt 里 mg_lobby_mapveto 的定义（mapgroupsMP 里排 0 号，注释写着
// "team lobby map veto"）：
//     "competitivemod" "lobby"   // activates custom lobby logic in the map
//     "maps" { "lobby_mapveto" "" }
// 官方形态是：服务器先加载这张专门的选图大厅图，图里自带 lobby 逻辑跑选/禁图，
// 定完图再 changelevel 到正式图。
//
// 我们原来把 9106 里的预约地图写成正式比赛图（de_cache），服务器就直接加载
// de_cache —— 没有任何 veto 环节。改成这张图，veto 才有地方发生。
const LOBBY_MAPVETO = 'lobby_mapveto';


// veto 候选图。mapid 用 **veto 日志里那套编号**（de_inferno=5、de_nuke=6、
// de_overpass=32、de_anubis=91），不是 mapids.txt 里那套（那边 de_inferno=23）。
// 这两套编号不同，填错客户端就认不出图。
const kMapVetoPool = [5, 6, 32, 91];
// [自定义] 匹配局 ID，客户端(9107)与服务器(9105)必须一致
const MATCH_ID = Number(config.matchId || 1488);
// [自定义] 预留玩家 accountId（7656119XXXXXXXXXX 的低 32 位）。
// 服务器建立 reservation 时必须带上授权玩家，否则会以
// "#Valve_Reject_Connect_From_Lobby" 拒绝所有连接。
const KNOWN_ACCOUNT_ID = Number(config.accountId || 100000000);

// [自定义] reservation cookie —— 与上游 csgo_gc 保持一致。
//
// 上游定义（csgo_gc/gc_const_csgo.h:6）：
//     constexpr uint64_t GameServerCookieId = 0x293A206F6C6C6548;
// 并且**同一个常量用在两处**：
//     gc_server.cpp:260  csWelcome.set_gscookieid(GameServerCookieId);   // 服务器欢迎包
//     gc_client.cpp:398  res.set_reservationid(GameServerCookieId);      // 客户端进服数据
//
// 你的 GC 原来给服务器的 gscookieid 就已经是 '2970722567136765256'
// （= 0x293A206F6C6C6548 = "Hello :)"，服务端日志里那句
//  "-> Reservation cookie 293a206f6c6c6548" 就是它），
// 但给客户端的 gscookieid 写的是 1488 —— 两边不一致，于是被
// #Valve_Reject_Connect_From_Lobby 拒掉。
//
// 正解就是把客户端那边也改成同一个常量（而不是我先前试的 0xFFFFFFFFFFFFFFFF）。
// 注意 0x293A206F6C6C6548 超过 2^53，必须用字符串传（protobufjs 的 uint64 接受字符串）。
const GC_COOKIE = '2970722567136765256';

// [诊断] 9164（ClientRequestJoinServerData）回复的变体轮换计数器。
// 引擎取走这条回复后就会死，所以逐字段二分：每次连接换下一个变体，
// 日志里会打印用的是哪个，连试几轮即可定位到出问题的那一段。
let v9164Counter = 0;

if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
}

if (DEVMODE === true) {
    console.log('[Notification] GC started in debug mode')
} else {
    console.log('[Notification] GC started in normal mode')
}

// id dictionary

const IDict = {
    93: 'CMsgAccountDetails',
    94: 'CMsgAccountDetailsResponse',
    4004: 'CMsgClientWelcome',
    4005: 'CMsgGCServerWelcome',
    4006: 'CMsgClientHello',
    4007: 'CMsgGCServerHello',
    9101: 'CMsgGCCStrike15_v2_MatchmakingStart',
    9102: 'CMsgGCCStrike15_v2_MatchmakingStop',
    9103: 'CMsgGCCStrike15_v2_MatchmakingClient2ServerPing',
    9104: 'CMsgGCCStrike15_v2_MatchmakingGC2ClientUpdate',
    9106: 'CMsgGCCStrike15_v2_MatchmakingServerReservationResponse',
    9107: 'CMsgGCCStrike15_v2_MatchmakingGC2ClientReserve',
    9109: 'CMsgGCCStrike15_v2_MatchmakingClient2GCHello',
    9110: 'CMsgGCCStrike15_v2_MatchmakingGC2ClientHello',
    9112: 'CMsgGCCStrike15_v2_MatchmakingGC2ClientAbandon',
    9189: 'CMsgGCCStrike15_v2_Party_Register',
    9190: 'CMsgGCCStrike15_v2_Party_Unregister',
    9194: 'CMsgGCCStrike15_v2_ClientGCRankUpdate',
    9201: 'CMsgGCCStrike15_v2_GetEventFavorites_Request',
    9203: 'CMsgGCCStrike15_v2_GetEventFavorites_Response',
    9105: 'CMsgGCCStrike15_v2_MatchmakingGC2ServerReserve',
    9153: 'CMsgGCCStrike15_v2_Server2GCClientValidate',
    9164: 'CMsgGCCStrike15_v2_ClientRequestJoinServerData',
    4009: 'CMsgGCClientConnectionStatus',
    // [新增] SO 缓存刷新请求（客户端收到 outofdate 的订阅后会来要新鲜数据）。
    // 以前没登记，日志里表现为 "[ERROR] Unknown message"。
    28: 'CMsgSOCacheSubscriptionRefresh',
};

function getMessageNameById(id) {
    return IDict[id] || null;
}

const ReverseIDict = {};
for (const id in IDict) {
    ReverseIDict[IDict[id]] = Number(id);
}

// functions

function encodeGCMessage(messageName, object) {
    const msgId = ReverseIDict[messageName];
    if (!msgId) {
        console.log(`[ERROR] Unknown message: ${messageName}`);
        return null;
    }
    try {
        const MessageType = root.lookupType(messageName);
        const message = MessageType.fromObject(object);
        const payload = MessageType.encode(message).finish();
        const finalMsgType = (0x80000000 | msgId) >>> 0;
        return JSON.stringify({
            msgType: finalMsgType,
            data: payload.toString('hex')
        });
    } catch (err) {
        console.error(`[ERROR] encodeGCMessage:`, err.message);
        return null;
    }
}

// Steam GC protobuf wire format:
// uint32 type | 0x80000000, uint32 headerSize, [header], [protobuf payload]
function encodeProto(msgType, protoName, object) {  // im too lazy to comment all its strings
    const Proto = root.lookupType(protoName);
    const payload = Proto.encode(Proto.fromObject(object)).finish();
    const type = (0x80000000 | msgType) >>> 0;
    const buffer = Buffer.alloc(8 + payload.length);
    buffer.writeUInt32LE(type, 0);
    buffer.writeUInt32LE(0, 4); // empty CMsgProtoBufHeader
    payload.copy(buffer, 8);
    return buffer;
}

function sendProto(socket, msgType, protoName, object, steamid = 0) {
    try {
        const Proto = root.lookupType(protoName);
        const message = Proto.fromObject(object);
        const payload = Proto.encode(message).finish();

        const finalMsgType = (0x80000000 | msgType) >>> 0;
        
        const totalLen = 8 + payload.length; // msgType (4) + header (4) + payload
        const buffer = Buffer.alloc(4 + totalLen);
        
        buffer.writeUInt32LE(totalLen, 0);   // ← ПРЕФИКС ДЛИНЫ!
        buffer.writeUInt32LE(finalMsgType, 4);
        buffer.writeUInt32LE(0, 8);          // пустой CMsgProtoBufHeader
        payload.copy(buffer, 12);

        console.log(`[SENT] ${protoName} (${finalMsgType}) ${buffer.length} bytes, totalLen=${totalLen}`);
        socket.write(buffer);
        return true;
    } catch (err) {
        console.error(`[ERROR] sendProto:`, err.message);
        return false;
    }
}

// SOID 的 id 必须是 **SteamID64**，不是 accountId。
// 事件分发层（getMSGdata）把 steamid 归一化成了 AccountId（= SteamID64 & 0xFFFFFFFF），
// 直接拿来当 owner_soid.id 客户端是认不出来的：它拿这个 SOID 去匹配「本地玩家自己的
// SOID」，而那个值（client.dll 里 host+8）实测就是 { id: SteamID64, type: 1 }
// ——0x01100001_06DC41E8 这种带 0x01100001 高位的 64 位数。
// 用 AccountId 的后果：客户端找不到宿主对象，本地玩家的 SOCache 永远挂不上
// （host+0xB4 == NULL），GetElevatedState() 于是一路返回 "none"，
// 优先相关 UI 全按非优先渲染 —— 这就是为什么单靠下发 econ 对象“看着发了却没生效”。
const STEAMID64_BASE = 76561197960265728n;   // universe=1, type=1, instance=1
function toSteamId64(id) {
    const v = BigInt(id);
    return v > 0xFFFFFFFFn ? v : STEAMID64_BASE + v;   // 已经是 SteamID64 就原样返回
}

// [新增] 构造发给客户端的 econ SO 缓存。客户端 MyPersonaAPI.GetElevatedState()
// 读的就是这里下发的 CSOEconGameAccountClient.elevated_state（field 14）。
// 4004 ClientWelcome 和 28 CacheSubscriptionRefresh 的响应共用这个构造。
// 两个坑都踩过：① 字段名必须驼峰（protobufjs 对 type_id / object_data 这类
// snake_case 键名静默忽略，会编码出一个空对象）② SO 类型号见函数内注释。
function buildEconSOCache(steamid) {
    // CSOEconGameAccountClient 的 SO 类型号是 7 —— 不是 1！
    // ESOType 里 1 是 CSOEconItem、2 是 CSOPersonaDataPublic、7 才是
    // CSOEconGameAccountClient。写错类型号的话客户端会拿别的 proto 去解这段字节，
    // 静默解出一个不相干的对象（踩过：用 1 时被当成 CSOEconItem）。
    // elevated_state = 5 表示"已购买优先（Prime）"，这是客户端
    // MyPersonaAPI.GetElevatedState() 的数据源（1 不是"elevated"，别想当然）。
    const EconAccountClient = root.lookupType('CSOEconGameAccountClient');
    const econAccountData = EconAccountClient.encode(EconAccountClient.create({
        additionalBackpackSlots: 0,
        bonusXpTimestampRefresh: 0,
        bonusXpUsedflags: 0,
        elevatedState: 5,                                 // 5 = 已购买优先（Prime）
        elevatedTimestamp: Math.floor(Date.now() / 1000)
    })).finish();

    // CSOPersonaDataPublic（ESOType 2）也带一个 elevated_state（bool）。
    // 一并下发，覆盖另一种可能的读取路径，成本只是一个额外的对象。
    const PersonaData = root.lookupType('CSOPersonaDataPublic');
    const personaData = PersonaData.encode(PersonaData.create({
        playerLevel: 40,
        commendation: { cmdFriendly: 1, cmdTeaching: 2, cmdLeader: 3 },
        elevatedState: true
    })).finish();

    return {
        objects: [
            { typeId: 7, objectData: [econAccountData] }, // CSOEconGameAccountClient
            { typeId: 2, objectData: [personaData] }      // CSOPersonaDataPublic
        ],
        version: 1575,
        ownerSoid: { type: 1, id: toSteamId64(steamid) }
    };
}

function getMSGdata(buffer) {
    try {
        // Пакет от форвардера: steamid (8 байт) + msgType (4 байта) + Protobuf-данные
        if (buffer.length < 12) {
            console.log('[ERROR] Buffer too small');
            return null;
        }
        const steamId = buffer.readBigUInt64LE(0);
        const AccountId = Number(steamId & 0xFFFFFFFFn);
        const msgId = buffer.readUInt32LE(8);
        const cleanMsgId = msgId & 0x7FFFFFFF;
        const messageName = getMessageNameById(cleanMsgId);

        // [自定义] csgc 转发头 = steamId(8) + msgType(4) + headerSize(4) = 16 字节
        // 原代码写死 subarray(120)：小消息被截成空 buffer 而侥幸通过，
        // 超过 120 字节的消息（如 9103 ping）会从中间截断导致 invalid end group tag。
        const headerSize = buffer.readUInt32LE(12);
        const protoData = buffer.subarray(16 + headerSize);
        if (DEVMODE === 1) {
            console.log(`[DEBUG] steamId: ${AccountId}, msgId: ${msgId}, cleanMsgId: ${cleanMsgId}, name: ${messageName}`);
            console.log(`[DEBUG] hex: ${buffer.toString('hex')}`);
        }
        if (!messageName) {
            console.log('[ERROR] Unknown message');
            return null;
        }
        // [自定义] GCServerHello(4007) 在 proto 里只是枚举值、没有消息体定义，
        // 直接 lookupType 会抛错。按空消息处理即可（内容我们不关心）。
        if (messageName === 'CMsgGCServerHello') {
            return { name: messageName, steamid: AccountId, data: {} };
        }
        const MessageType = root.lookupType(messageName);
        const decoded = MessageType.decode(protoData);
        return { name: messageName, steamid: AccountId, data: decoded };
    } catch (err) {
        console.error(`[ERROR] getMSGdata:`, err.message);
        return null;
    }
}

function savePlayer(accountId) {
    const session = sessions.get(accountId);
    if (!session) return;
    const filePath = `${DATA_DIR}/${accountId}.json`;
    fs.writeFileSync(filePath, JSON.stringify(session, null, 2));
}

function loadPlayer(accountId) {
    const filePath = `${DATA_DIR}/${accountId}.json`;
    if (fs.existsSync(filePath)) {
        return JSON.parse(fs.readFileSync(filePath, 'utf8'));
    }
    return null;
}

function getOrCreateSession(steamId) {

//    const accountId = Number(steamId & 0xFFFFFFFFn); // if steam id is bigint
    const accountId = steamId % 2**32;

    let session = loadPlayer(accountId);
    if (!session) {
        session = {
            accountId: AccountId,
            rankings: {
                competitive: {
                    rank: 1,
                    wins: 0
                },
                wingman: {
                    rank: 1,
                    wins: 0
                },
                dangerzone: {
                    rank: 1,
                    wins: 0
                }
            },
            playerLevel: 1,
            playerCurXp: 0,
            matchId: null,
            partyId: null,
            matchmaking: false,
            lastPing: Date.now(),
            isInitiatedMMSearchStop: false,
            vacBanned: 0,
            inventory: [],
            cmd: {
                friendly: 1,
                teaching: 2,
                leader: 3
            },
            vacBanned: 0
        };
        savePlayer(accountId, session);
    };
    sessions.set(accountId, session);
    return { accountId, session };
}

function uint32ToIp(uint32) {
    const octet1 = (uint32 >>> 24) & 0xFF;
    const octet2 = (uint32 >>> 16) & 0xFF;
    const octet3 = (uint32 >>> 8) & 0xFF;
    const octet4 = uint32 & 0xFF;
    return `${octet1}.${octet2}.${octet3}.${octet4}`;
}

// [自定义] uint32ToIp 的逆运算，供 direct_udp_ip 使用
function ipToUint32(ip) {
    const p = ip.split('.').map(Number);
    return (((p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3]) >>> 0);
}

// [自定义] 匹配界面统计：数据源为 CS2 官方实时在线数
let liveStats = {
    playersOnline: 582385,
    serversOnline: 48532,
    playersSearching: 7000,
    serversAvailable: 40000
};

async function refreshLiveStats() {
    try {
        const res = await fetch('https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=730');
        const j = await res.json();
        const n = j && j.response && j.response.player_count;
        if (n && n > 0) {
            liveStats.playersOnline = n;
            liveStats.serversOnline = Math.round(n / 12);
            liveStats.playersSearching = Math.round(n * 0.012) + Math.floor(Math.random() * 200);
            liveStats.serversAvailable = Math.round((n / 12) * 0.85);
            console.log('[STATS] CS2 在线 ' + n + ' 服务器约 ' + liveStats.serversOnline);
        }
    } catch (e) {
        console.log('[STATS] 拉取失败，沿用上次数据: ' + e.message);
    }
}
refreshLiveStats();
setInterval(refreshLiveStats, 60000);

function getGlobalStats() {
    return {
        playersOnline: liveStats.playersOnline,
        serversOnline: liveStats.serversOnline,
        playersSearching: liveStats.playersSearching,
        serversAvailable: liveStats.serversAvailable,
        ongoingMatches: Math.round(liveStats.playersOnline / 10),
        searchTimeAvg: 30,
        requiredAppidVersion: 1575,
        rtime32Cur: Math.floor(Date.now() / 1000)
    };
}

function sendWithDelay(socket, msgType, protoName, object, delay = 100) {
    // Do not use this on per-request TCP. The client opens one connection,
    // reads the reply, then the socket is closed. Delayed writes get dropped.
    sendProto(socket, msgType, protoName, object);
}

// event handler

class EventBus {
    constructor() {
        this.handlers = new Map();
    }

    on(eventName, handler) {
        if (!this.handlers.has(eventName)) {
            this.handlers.set(eventName, []);
        }
        this.handlers.get(eventName).push(handler);
//        console.log(`[EVENT] Subscribed: ${eventName}`);
    }

    emit(eventName, data, socket, steamid) {
        if (this.handlers.has(eventName)) {
            for (const handler of this.handlers.get(eventName)) {
                handler(data, socket, steamid);
            }
            return true;
        }
        return false;
    }
}

const events = new EventBus();

// events(reqs from client)

const sessions = new Map();

// [自定义] 服务器池：srcds 启动后发 GCServerHello 注册进来
const gameServers = new Map();   // steamId -> { steamid, lastSeen }

events.on('CMsgGCServerHello', (data, socket, steamid) => {
    console.log(`[SERVER] GCServerHello from ${steamid}`);
    gameServers.set(String(steamid), { steamid, lastSeen: Date.now() });
    console.log(`[SERVER] 服务器池现有 ${gameServers.size} 台`);

    // 回复方式与 csgo_gc 一致：消息体复用 CMsgClientWelcome，
    // game_data 里放 CMsgCStrike15Welcome（gscookieid = "Hello :)" 那个彩蛋常量）
    try {
        const CsWelcome = root.lookupType('CMsgCStrike15Welcome');
        const csBytes = CsWelcome.encode(CsWelcome.create({
            gscookieid: GC_COOKIE
        })).finish();
        sendProto(socket, 4005, 'CMsgClientWelcome', {
            version: 0,
            gameData: csBytes,
            rtime32GcWelcomeTimestamp: Math.floor(Date.now() / 1000)
        });
        console.log('[SERVER] 已回复 GCServerWelcome');

        // [自定义] 同一响应里再捎带一条 9106（让服务器注册即建立 reservation）。
        // 服务器侧 SplitGCMessages 支持一条响应含多条消息，因此无需推送通道，
        // 也就避免了在 srcds 里额外起线程/长连接（那会撞上引擎生命周期，触发 assert）。
        sendProto(socket, 9106, 'CMsgGCCStrike15_v2_MatchmakingServerReservationResponse', {
            reservationid: '0',
            // [已移除] 原来这里塞了一整套 reservation（accountIds/gameType/matchId/
            // serverVersion/rankings/encryptionKey/encryptionKeyPub/whitelist/preMatchData）。
            // 依据：直连用的 9164 回复改用上游最小配方后就通了，而引擎对带 reservation
            // 的消息是明确拒绝的（连空的都崩），所以 9106/9107 都不再带它。
            map: LOBBY_MAPVETO,   // 预约地图 -> 选图大厅图（veto 发生的地方）
            gcReservationSent: Math.floor(Date.now() / 1000),
            serverVersion: Number(SERV_VER) || 13881
        });
    } catch (e) {
        console.error(`[ERROR] GCServerWelcome 构造失败: ${e.message}`);
    }

    // [自定义] 同时把 9106 推给游戏服务器，告知"接一局匹配"。
    // 这是服务器建立 reservation 的正规途径——原来因为短连接推不了，
    // 现在 csgo_gc 有了长连接推送通道，就能送了。
    try {
        const ReservResp = root.lookupType('CMsgGCCStrike15_v2_MatchmakingServerReservationResponse');
        const reservPayload = ReservResp.encode(ReservResp.create({
            reservationid: '0',
            // ★ 用 buildServerReserve()：它含 account_ids（预约的玩家名单）与
            // preMatchData.draft —— **这正是服务器 `reserved(yes), clients(no)` 缺的字段**。
            //
            // 原来这里是手写的，用了两个本 handler 里根本不存在的变量
            // （形参只有 data/socket/steamid）：
            //     accountIds: [AccountId], gameType: gameType,
            // 于是每次都抛 `ReferenceError: AccountId is not defined`（日志实证），
            // 这段自称"服务器建立 reservation 的正规途径"的推送**从来没执行过**。
            reservation: buildServerReserve(KNOWN_ACCOUNT_ID),
            map: LOBBY_MAPVETO,   // 预约地图 -> 选图大厅图（veto 发生的地方）
            gcReservationSent: Math.floor(Date.now() / 1000),
            serverVersion: Number(SERV_VER) || 13881
        })).finish();
        pushToServers(9106, 0, reservPayload);
    } catch (e) {
        console.error(`[ERROR] 9106 构造失败: ${e.message}`);
    }
});

// [新增] 客户端收到 outofdate 的 SO 缓存后会来要新鲜数据（消息 28，
// CMsgSOCacheSubscriptionRefresh）。原来这条没人处理 —— 日志里就是
// "[ERROR] Unknown message"，客户端则一直拿不到 econ 账号对象，
// GetElevatedState() 永远拿不到 elevated（优先/Prime 相关 UI 全按非优先走）。
// 按协议回一帧 CMsgSOCacheSubscribed(24)，内容与 4004 里下发的一致。
events.on('CMsgSOCacheSubscriptionRefresh', (data, socket, steamid) => {
    console.log(`[SOCACHE] 客户端请求刷新 owner_soid=${JSON.stringify(data && data.ownerSoid)}`);
    const ok = sendProto(socket, 24, 'CMsgSOCacheSubscribed', buildEconSOCache(steamid), steamid);
    if (ok) {
        console.log('[SOCACHE] 已回 CMsgSOCacheSubscribed(24)');
    }
});

events.on('CMsgClientHello', (data, socket, steamid) => {

    console.log(`[Notification] ClientHello from ${steamid}`)

    let session = loadPlayer(steamid);
    if (!session) {
        session = {
            accountId: steamid,
            rankings: {
                competitive: { rank: 1, wins: 0 },
                wingman: { rank: 1, wins: 0 },
                dangerzone: { rank: 1, wins: 0 }
            },
            playerLevel: 1,
            playerCurXp: 0,
            matchId: null,
            partyId: null,
            matchmaking: false,
            lastPing: Date.now(),
            isInitiatedMMSearchStop: false,
            vacBanned: 0,
            inventory: [],
            cmd: { friendly: 1, teaching: 2, leader: 3 }
        };
        sessions.set(steamid, session);
        savePlayer(steamid);
    }

    const competitiverank = session.rankings.competitive.rank || 1;
    const wingmanrank = session.rankings.wingman.rank || 1;
    const dzrank = session.rankings.dangerzone.rank || 1;
    const playerlevel = session.playerLevel || 1;
    const playercurxp = session.playerCurXp || 1;
    const cmdfriendly = session.cmd.friendly || 1;
    const cmdteaching = session.cmd.teaching || 1;
    const cmdleader = session.cmd.leader || 1;

    const csWelcome1 = {
        storeItemHash: 0,
        timeplayedconsecutively: 0,
        timeFirstPlayed: 0,
        lastTimePlayed: 0,
        lastIpAddress: 0,
        gscookieid: GC_COOKIE,
        uniqueid: GC_COOKIE
    };

    const csWelcome2 = {
        accountId: steamid,
        globalStats: getGlobalStats(),   // [恢复] 走 API 的在线数据（重建时误退回成写死的 2/1/1/1）
        vacBanned: 0,
        ranking: {
            accountId: steamid,
            rankId: competitiverank,
            wins: session.rankings.competitive.wins || 0,
            rankTypeId: 6,
            rankWindowStats: 0,
            rankIfWin: Math.min(competitiverank + 1, 18),
            rankIfLose: Math.max(competitiverank - 1, 1),
            rankIfTie: competitiverank        },
        commendation: {
            cmdFriendly: cmdfriendly,
            cmdTeaching: cmdteaching,
            cmdLeader: cmdleader
        },
        medals: [],
        // [修复] 客户端靠等级判断竞技是否解锁：等级 < 2 时 Competitive/Wingman 显示
        // "已锁定：需在其他模式完成比赛才能解锁"，于是根本不走匹配流程。
        // player_xp_bonus_flags 的 bit0 是 Prime 标志 —— 一并置上。
        playerLevel: Math.max(playerlevel, 40),
        playerCurXp: 5000,
        playerXpBonusFlags: 1,
        rankings: [
            {
                accountId: steamid,
                rankId: wingmanrank,
                wins: session.rankings.wingman.wins || 0,
                rankTypeId: 7,
                rankWindowStats: 0,
                rankIfWin: Math.min(wingmanrank + 1, 18),
                rankIfLose: Math.max(wingmanrank - 1, 1),
                rankIfTie: wingmanrank
            },
            {
                accountId: steamid,
                rankId: dzrank,
                wins: session.rankings.dangerzone.wins || 0,
                rankTypeId: 10,
                rankWindowStats: 0,
                rankIfWin: Math.min(dzrank + 1, 18),
                rankIfLose: Math.max(dzrank - 1, 1),
                rankIfTie: dzrank
            }
        ]
    }

    const csWelcome3 = {
        valid: true,
        accountName: steamid,
        publicProfile: true,
        publicInventory: true,
        vacBanned: false,
        cyberCafe: false,
        schoolAccount: false,
        freeTrialAccount: false,
        subscribed: true,
        lowViolence: false,
        limited: false,
        trusted: true,
        package: 0,
        accountLocked: false,
        communityBanned: false,
        eligibleForCommunityMarket: true
    };

    // [修复] 原来这里用 snake_case 写字段名（type_id / object_data / owner_soid），
    // protobufjs 对这类键名是静默忽略的，编码出来是个空对象 —— 客户端从来没收到过
    // econ 账号对象，GetElevatedState() 自然拿不到 elevated。
    // 字段名已改成驼峰，数据统一由 buildEconSOCache() 构造。
    const socacheSubscribed = buildEconSOCache(steamid);

    const socacheCheck = {
        version: 1575,
        ownerSoid: { type: 1, id: toSteamId64(steamid) }
    };

    const ConnectionStatus = {
        status: 0,
        clientSessionNeed: 0,
        queuePosition: 0,
        queueSize: 0,
        waitSeconds: 0,
        estimatedWaitSecondsRemaining: 0
    };

    const CsWelcomeType1 = root.lookupType('CMsgCStrike15Welcome');
    const gamedata1 = CsWelcomeType1.encode(csWelcome1).finish();

    const CsWelcomeType2 = root.lookupType('CMsgGCCStrike15_v2_MatchmakingGC2ClientHello');
    const gamedata2 = CsWelcomeType2.encode(csWelcome2).finish();

    const CsWelcomeType3 = root.lookupType('CMsgAccountDetails');
    const gamedata3 = CsWelcomeType3.encode(csWelcome3).finish();

    const CsWelcomeType4 = root.lookupType('CMsgConnectionStatus');
    const gamedata4 = CsWelcomeType4.encode(ConnectionStatus).finish();

    sendProto(socket, 4004, 'CMsgClientWelcome', {
        version: 1575,
        gameData: gamedata1,
        // 带对象的缓存只能走 outofdate —— 它的元素类型是 CMsgSOCacheSubscribed，能装
        // objects；uptodate 的元素类型是 CMsgSOCacheSubscriptionCheck（只有 version +
        // owner_soid），塞对象进去会被静默丢掉。客户端收到 outofdate 后会回一条
        // CMsgSOCacheSubscriptionRefresh(28) 来要新鲜数据，那条由下面
        // events.on('CMsgSOCacheSubscriptionRefresh') 负责回真正的内容。
        outofdateSubscribedCaches: [socacheSubscribed],
        uptodateSubscribedCaches: [socacheCheck],
        location: {
            latitude: 55.7558,
            longitude: 37.6173,
            country: "RU"
        },
        gameData2: gamedata2,
        rtime32GcWelcomeTimestamp: Math.floor(Date.now() / 1000),
        currency: 0,
        balance: 0,
        balanceUrl: "",
        txnCountryCode: "RU",
    }, steamid);

    sendProto(socket, 9110, 'CMsgGCCStrike15_v2_MatchmakingGC2ClientHello', {
        accountId: steamid,
        globalStats: getGlobalStats(),   // [恢复] 走 API 的在线数据（重建时误退回成写死的 2/1/1/1）
        vacBanned: 0,
        ranking: {
            accountId: steamid,
            rankId: competitiverank,
            wins: session.rankings.competitive.wins || 0,
            rankTypeId: 6,
            rankWindowStats: 0,
            rankIfWin: Math.min(competitiverank + 1, 18),
            rankIfLose: Math.max(competitiverank - 1, 1),
            rankIfTie: competitiverank        },
        commendation: {
            cmdFriendly: cmdfriendly,
            cmdTeaching: cmdteaching,
            cmdLeader: cmdleader
        },
        medals: [],
        // [修复] 客户端靠等级判断竞技是否解锁：等级 < 2 时 Competitive/Wingman 显示
        // "已锁定：需在其他模式完成比赛才能解锁"，于是根本不走匹配流程。
        // player_xp_bonus_flags 的 bit0 是 Prime 标志 —— 一并置上。
        playerLevel: Math.max(playerlevel, 40),
        playerCurXp: 5000,
        playerXpBonusFlags: 1,
        rankings: [
            {
                accountId: steamid,
                rankId: wingmanrank,
                wins: session.rankings.wingman.wins || 0,
                rankTypeId: 7,
                rankWindowStats: 0,
                rankIfWin: Math.min(wingmanrank + 1, 18),
                rankIfLose: Math.max(wingmanrank - 1, 1),
                rankIfTie: wingmanrank
            },
            {
                accountId: steamid,
                rankId: dzrank,
                wins: session.rankings.dangerzone.wins || 0,
                rankTypeId: 10,
                rankWindowStats: 0,
                rankIfWin: Math.min(dzrank + 1, 18),
                rankIfLose: Math.max(dzrank - 1, 1),
                rankIfTie: dzrank
            }
        ]
    }, steamid);

    sendProto(socket, 9194, 'CMsgGCCStrike15_v2_ClientGCRankUpdate', {
        rankings: [
            {
                accountId: steamid,
                rankId: competitiverank,
                wins: session.rankings.competitive.wins || 0,
                rankTypeId: 6,
                rankWindowStats: 0,
                rankIfWin: Math.min(competitiverank + 1, 18),
                rankIfLose: Math.max(competitiverank - 1, 1),
                rankIfTie: competitiverank
            },
            {
                accountId: steamid,
                rankId: wingmanrank,
                wins: session.rankings.wingman.wins || 0,
                rankTypeId: 7,
                rankWindowStats: 0,
                rankIfWin: Math.min(wingmanrank + 1, 18),
                rankIfLose: Math.max(wingmanrank - 1, 1),
                rankIfTie: wingmanrank
            },
            {
                accountId: steamid,
                rankId: dzrank,
                wins: session.rankings.dangerzone.wins || 0,
                rankTypeId: 10,
                rankWindowStats: 0,
                rankIfWin: Math.min(dzrank + 1, 18),
                rankIfLose: Math.max(dzrank - 1, 1),
                rankIfTie: dzrank
            }
        ]
    }, steamid);

    sendProto(socket, 4009, 'CMsgConnectionStatus', {
        status: 0,
        clientSessionNeed: 0,
        queuePosition: 0,
        queueSize: 0,
        waitSeconds: 0,
        estimatedWaitSecondsRemaining: 0 
    }); 


    socket.end();

});

events.on('CMsgGCCStrike15_v2_MatchmakingStart', (data, socket, steamid) => {

    const AccountId = steamid ? Number(BigInt(steamid) & 0xFFFFFFFFn) : 0;
    if (!AccountId) {
        console.log(`[HANDLER] MatchmakingStart from unknown id`);
        return;
    } else {
            console.log(`[HANDLER] MatchmakingStart from ${AccountId}`);
    };
    
    let session = loadPlayer(AccountId);
    // [修复] protobufjs 解出来是驼峰 gameType，写 data.game_type 恒为 undefined
    const gameType = data?.gameType ?? data?.game_type ?? 0;
    console.log(`[MATCH] MatchmakingStart gameType=${gameType}`);
    const lobbyIdRaw = data?.lobbyId ?? data?.lobby_id;
    console.log(`[MATCH] MatchmakingStart 全字段: ${JSON.stringify(data)}`);
    console.log(`[MATCH] >>> 客户端上报的 lobby_id = ${lobbyIdRaw === undefined ? '(未携带)' : lobbyIdRaw}`);
    
    // [新增] 优先（Prime）匹配请求。客户端把本地的 prime 开关打开时会在 9101 里带上
    // prime_only（来源见 mainmenu_play.js 的 settings.update.Game.prime）。
    // 原来这个字段是直接丢掉的，GC 根本不知道这次搜索要的是不是优先队列。
    // 实测日志里 51 次全是 true —— 客户端一直认为自己在走优先队列。
    const primeOnly = !!(data?.primeOnly ?? data?.prime_only);
    console.log(`[MATCH] 优先队列 prime_only=${primeOnly}`);
    if (session) session.mmPrimeOnly = primeOnly;

    if (session) {
        session.matchmaking = true;
        savePlayer(AccountId);
    }

    sendProto(socket, 9104, 'CMsgGCCStrike15_v2_MatchmakingGC2ClientUpdate', {
        matchmaking: 1,
        waitingAccountIdSessions: [AccountId || 100000000],
        globalStats: getGlobalStats(),   // [恢复] 走 API 的在线数据（重建时误退回成写死的 2/1/1/1）
        notes: [
            {
                type: gameType,
                regionId: 0,
                regionR: 0,
                distance: 0
            }
        ]
    });
});

events.on('CMsgGCCStrike15_v2_MatchmakingClient2ServerPing', (data, socket, steamid) => {

    // protobufjs 解出来是驼峰 gameType；原来是 const 且读 game_type（恒 undefined），
    // 下面还要用 session 里的值覆盖它，所以必须是 let。
    let gameType = data?.gameType ?? data?.game_type ?? 0;

    const AccountId = steamid ? Number(BigInt(steamid) & 0xFFFFFFFFn) : 0;
    if (!AccountId) {
        console.log(`[HANDLER] MatchmakingClient2ServerPing from unknown id`);
        return;
    } else {
            console.log(`[HANDLER] MatchmakingClient2ServerPing from ${AccountId}`);
    };

    sendProto(socket, 9104, 'CMsgGCCStrike15_v2_MatchmakingGC2ClientUpdate', {
        matchmaking: 1,
        waitingAccountIdSessions: [100000000],
        globalStats: getGlobalStats(),   // [恢复] 走 API 的在线数据（重建时误退回成写死的 2/1/1/1）
        notes: [
            {
                type: 462552584,
                regionId: 0,
                regionR: 0,
                distance: 0
            }
        ]
    });

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
    // 必须与服务器手上的 cookie 一致（服务器日志里的 "Reservation cookie 293a206f6c6c6548"
    // 就是 GC_COOKIE）。原来是 '0'，和服务器对不上 —— srvfix 把整段判定绕过去时看不出问题，
    // 一旦关掉补丁就表现为「reservation 永远耗不掉 → 每次连接重放换图 → 死循环」。
    const reservationId = '0';
    console.log(`[MATCH] 下发服务器 ${MATCH_SERVER_IP}:${MATCH_SERVER_PORT} (map=${LOBBY_MAPVETO}) 给 ${AccountId}`);
    sendProto(socket, 9107, 'CMsgGCCStrike15_v2_MatchmakingGC2ClientReserve', {
        serverid: String(config.gsSteamId || 'YOUR_GS_STEAMID'),
        directUdpIp: ipToUint32(MATCH_SERVER_IP),
        directUdpPort: MATCH_SERVER_PORT,
        reservationid: reservationId,
        // [重测] 把 reservation 加回来。之前去掉它是从"9164 带 reservation 就崩"推的，
        // 但 9107 从没崩过；而且早先的匹配测试都在栈/LAA 修好之前，不作数。
        reservation: {
            // [修复] 单排竞技时客户端显示 "1/5"、等 GC 把队伍补满才继续。
            // 我们一直只报自己一个人，所以它永远卡在 1/5。
            // 这里补成 10 个（5v5）：你自己 + 9 个占位 accountId。
            accountIds: [AccountId, 900000001, 900000002, 900000003, 900000004,
                         900000005, 900000006, 900000007, 900000008, 900000009],
            // [修复] 客户端在 client.dll+0x422E33 检查 reservation 的 game_type 低四位，
            // 只接受 9(竞技)/11(搭档)/13；原来填的是 MatchmakingStart 里的 519
            // (519 & 0xF = 7) 会被判为无效而放弃。"搜索用类型"和"reservation 里的
            // 模式编号"本来就不是一回事，之前把它们统一是错的。
            gameType: 9,
            matchId: MATCH_ID,
            serverVersion: Number(SERV_VER) || 13881,
            rankings: (() => {
                const s = loadPlayer(AccountId);
                const r = (s && s.rankings && s.rankings.competitive && s.rankings.competitive.rank) || 1;
                const w = (s && s.rankings && s.rankings.competitive && s.rankings.competitive.wins) || 0;
                return [{
                    accountId: AccountId, rankId: r, wins: w, rankTypeId: 6,
                    rankWindowStats: 0, rankIfWin: Math.min(r + 1, 18),
                    rankIfLose: Math.max(r - 1, 1), rankIfTie: r
                }];
            })(),
            encryptionKey: Math.floor(Math.random() * 1000000),
            encryptionKeyPub: Math.floor(Math.random() * 1000000),
            whitelist: [],
            preMatchData: buildPreMatchData(),   // ★ 必须是对象形态，传 [] 会被静默丢弃
        },
        map: LOBBY_MAPVETO,   // 客户端会话的 game.map 就是从这里来的，它决定接受弹窗上显示的地图名；
                               // 此刻服务器跑的正是大厅图，所以这里写大厅图才一致
        serverAddress: `${MATCH_SERVER_IP}:${MATCH_SERVER_PORT}`
    });

    // [新增] 紧接着告诉客户端「已进入对局」—— 否则 UI 上的「正在确认比赛」在对局中
    // 和结束后都不消失（用户报的 bug）。
    //
    // proto 里 CMsgGCCStrike15_v2_MatchmakingGC2ClientUpdate 有：
    //     optional int32  matchmaking                        = 1;   // 0=空闲 1=搜索中
    //     repeated uint32 waiting_account_id_sessions        = 2;   // 排队中的人
    //     repeated uint32 ongoingmatch_account_id_sessions   = 6;   // ★ 正在一局里的人
    // 我们此前只发过 matchmaking:1 + waiting（搜索中），**从来没发过 ongoingmatch** ——
    // 客户端因此一直停在"已预约/确认中"的状态。
    //
    // 必须**同步**发（不能 setTimeout）：GC 的 socket 是「发完就关」的短连接，
    // 延迟发送时 socket 早就没了。
    // [已回退 2026-09-29] 这条 ongoingmatch 的 9104 **会把匹配弄坏**：
    // 它紧跟在 9107 之后发，客户端于是认为"已经在局里了"，
    // 下次点「开始竞技」会闪一下就弹回（实测）。
    // 正确时机应该是**对局真正开始之后**，而 GC 的 socket 是发完就关的短连接，
    // 没地方挂延时发送 —— 要做得对得等客户端主动来消息时再回。
    // 暂时关掉：这个 bug（"正在确认比赛"不消失）比起"根本匹配不了"是小问题。
    if (process.env.JSO_ONGOING_MATCH === '1') {
        sendProto(socket, 9104, 'CMsgGCCStrike15_v2_MatchmakingGC2ClientUpdate', {
            matchmaking: 0,
            waitingAccountIdSessions: [],
            ongoingmatchAccountIdSessions: [AccountId],
            globalStats: getGlobalStats(),
            notes: []
        });
        console.log(`[MATCH] 已告知客户端进入对局（ongoingmatch=${AccountId}）`);
    }
});

// ── 服务器 9106 的应答：一份完整的 9105 GC2ServerReserve ──────────────────
//
// 背景：服务器注册后会把 9106 MatchmakingServerReservationResponse 发给 GC，然后
// **同步等回包** —— csgo_gc 的 SteamGameCoordinatorProxy::SendMessage 里
// ForwardToExternalServer 是阻塞的，拿不到就打印 "No response from external GC for
// msg %u" 并重试。上游原版和本项目此前都只有 9106 的名字表、没有处理器。
//
// 【迭代记录 2026-09-28】
//  v0（无处理器）：`No response` 刷屏；服务器不把连入的玩家记进名单
//      （`but they're not on the list! ignoring`）→ 不发 9153 → 没有 draft。
//  v1（只有 reservationid + serverVersion）：`No response` 消失，服务器出现
//      `GC Connection established`，但**预约里一个玩家都没有**
//      （CMsgGCCStrike15_v2_MatchmakingGC2ServerReserve 的 field 1 就是 account_ids）。
//      玩家连入时引擎走进「已预留 → 直接开局」，执行 `map <map> reserved` 重载关卡，
//      随后卡死：`GameTypes: could not find matching game mode value of "reserved"`
//      → `Created class baseline` → `**** WARNING: Watchdog timer exceeded, aborting!`
//      （退出码 134 = SIGABRT，不是段错误 —— 顺带证明 srvfix 的 NX 修复生效了。）
//  v2（本版）：补上 account_ids 与 preMatchData.draft，与 9153 走同一份构造。
// [2026-09-28 深夜] 选/禁图（draft）数据 —— 服务器与客户端**共用**这一份构造。
//
// proto 里它是 CDataGCCStrike15_v2_TournamentMatchDraft **对象**，里面才有一层
// repeated Entry drafts。传 []（空数组）类型不符，protobufjs **静默丢弃** ——
// 收到的那一侧就等于完全没有 draft 数据。
//
// 这个坑踩过两次：
//   · 先是在服务器的 9105 里（已修）—— 服务器因此不跑选/禁图
//   · 后在客户端的 9107 里（本次修）—— **客户端因此永远不显示 veto 界面**
//     9107 的 preMatchData 原来写的是 { draft: [] }，类型错 → 客户端拿不到 draft
//     → MatchDraftAPI.GetDraft() 永远不是 'ingame' → mapdraft.js 永不显示。
//     （局内 draft 是客户端侧特性：MatchDraftAPI 在 client.dll，服务器模块里没有。）
function buildPreMatchData() {
    return {
        predictionsPct: 0,
        draft: {
            eventId: 0,
            eventStageId: 0,
            teamId0: KNOWN_ACCOUNT_ID || 1,
            teamId1: KNOWN_ACCOUNT_ID || 1,
            mapsCount: kMapVetoPool.length,
            mapsCurrent: 0,
            teamIdStart: KNOWN_ACCOUNT_ID || 1,
            teamIdVeto1: KNOWN_ACCOUNT_ID || 1,
            teamIdPickn: KNOWN_ACCOUNT_ID || 1,
            drafts: kMapVetoPool.map(function (id) { return { mapid: id, teamIdCt: 2 }; })
        },
        stats: [],
        wins: 0
    };
}

function buildServerReserve(accountId) {
    return {
        accountIds: accountId ? [accountId] : [],
        gameType: 0,
        matchId: MATCH_ID,
        serverVersion: Number(SERV_VER) || 13881,
        rankings: [],
        encryptionKey: Math.floor(Math.random() * 1000000),
        encryptionKeyPub: Math.floor(Math.random() * 1000000),
        whitelist: [],
        preMatchData: buildPreMatchData()
    };
}

// 【默认关闭】SRVGC_PROBE=1 才注册这个处理器（重启 GC 时用环境变量开）。
//
// 为什么默认关掉 —— 2026-09-28 晚的实测结论：
// 应答 9106 确实让服务器进入「已预约」状态（`GC Connection established`、
// `reason reserved(yes)`），但**它同时把客户端挡在门外**：
//     -> Reservation cookie 293a206f6c6c6548:  reason [R] Connect from HOST_LAN_IP:27005
//     -> Reservation cookie 0:  reason reserved(yes), clients(no), reservationexpires(0.00)
//     然后没有任何后续日志 —— 客户端连不进去，无限 retry。
// 而不应答时的行为是：`No response from external GC` 刷屏（无害），
// **客户端能正常进服、能打完一局**。
//
// 也就是说「让服务器 reserved」是 draft/veto 的前提，但当前先要保证能进服。
// 想继续做 veto 那条线时，用 SRVGC_PROBE=1 打开，配合 srvfix 的
// SRVFIX_DETOUR / 默认 NOP 三种组合继续二分。
if (process.env.SRVGC_PROBE === '1') {
events.on('CMsgGCCStrike15_v2_MatchmakingServerReservationResponse', (data, socket, steamid) => {
    const d = data || {};
    console.log(`[SRVGC] 收到服务器 9106（from ${steamid}）: ` +
                `reservationid=${d.reservationid} map=${d.map} serverVersion=${d.serverVersion}`);
    try {
        sendProto(socket, 9105, 'CMsgGCCStrike15_v2_MatchmakingGC2ServerReserve',
                  buildServerReserve(KNOWN_ACCOUNT_ID));
        console.log(`[SRVGC] 已回完整 9105（accountIds=[${KNOWN_ACCOUNT_ID}]，` +
                    `draft pool=${JSON.stringify(kMapVetoPool)}）`);
    } catch (e) {
        console.error(`[ERROR] 9105 构造失败: ${e.message}`);
    }
});
}

// [自定义] 玩家连入服务器时，服务器会来问"这人合法吗"（9153）。
// 原项目直接忽略；我们回 9105 GC2ServerReserve，告知服务器这属于一局匹配。
// 这是 GC 唯一能"主动影响服务器"的通道（因为是服务器先来问的）。
events.on('CMsgGCCStrike15_v2_Server2GCClientValidate', (data, socket, steamid) => {
    const accountId = Number(data && data.accountid) || 0;
    console.log(`[SERVER] Server2GCClientValidate: account ${accountId}`);
    try {
        sendProto(socket, 9105, 'CMsgGCCStrike15_v2_MatchmakingGC2ServerReserve',
                  buildServerReserve(accountId || KNOWN_ACCOUNT_ID));
        console.log('[SERVER] 已回 GC2ServerReserve（告知服务器这是匹配局）');
    } catch (e) {
        console.error(`[ERROR] GC2ServerReserve 构造失败: ${e.message}`);
    }
});


// [新增] 玩家档案构造 —— 9110 和 9128 共用同一个结构
function buildClientProfile(accountId) {
    const sess = loadPlayer(accountId) || {};
    const rank = (sess.rankings && sess.rankings.competitive && sess.rankings.competitive.rank) || 1;
    const wins = (sess.rankings && sess.rankings.competitive && sess.rankings.competitive.wins) || 0;
    return {
        accountId: accountId,
        globalStats: getGlobalStats(),
        vacBanned: 0,
        ranking: { accountId: accountId, rankId: rank, wins: wins, rankTypeId: 6, rankWindowStats: 0,
                   rankIfWin: Math.min(rank + 1, 18), rankIfLose: Math.max(rank - 1, 1), rankIfTie: rank },
        commendation: { cmdFriendly: 1, cmdTeaching: 2, cmdLeader: 3 },
        medals: [],
        // 和 9110 一致：等级必须 >= 2，否则竞技被判"未解锁"
        playerLevel: Math.max(sess.playerLevel || 1, 40),
        playerCurXp: 5000,
        playerXpBonusFlags: 1,
        rankings: [{ accountId: accountId, rankId: rank, wins: wins, rankTypeId: 6, rankWindowStats: 0,
                     rankIfWin: Math.min(rank + 1, 18), rankIfLose: Math.max(rank - 1, 1), rankIfTie: rank }]
    };
}

// [新增] 队伍/好友界面拉玩家档案。原来 GC 完全不回，界面拿不到数据会卡死甚至崩。
events.on('CMsgGCCStrike15_v2_ClientRequestPlayersProfile', (data, socket, steamid) => {
    const reqId = data?.requestId ?? data?.request_id ?? 0;
    const acct = data?.accountId ?? data?.account_id ?? 0;
    const self = steamid ? Number(BigInt(steamid) & 0xFFFFFFFFn) : 0;
    console.log(`[PROFILE] 请求玩家档案 account=${acct} req=${reqId} (self=${self})`);
    try {
        sendProto(socket, 9128, 'CMsgGCCStrike15_v2_PlayersProfile', {
            requestId: reqId,
            accountProfiles: [ buildClientProfile(acct || self) ]
        });
        console.log('[PROFILE] 已回 PlayersProfile');
    } catch (e) {
        console.error(`[ERROR] PlayersProfile 构造失败: ${e.message}`);
    }
});

// [新增] 共同游玩数据（ClientGCRankUpdate 那一类界面的附属请求）
events.on('CMsgGCCStrike15_v2_Account_RequestCoPlays', (data, socket, steamid) => {
    console.log('[COPLAY] RequestCoPlays');
    try {
        sendProto(socket, 9193, 'CMsgGCCStrike15_v2_Account_RequestCoPlays', {
            servertime: Math.floor(Date.now() / 1000),
            players: []
        });
    } catch (e) {
        console.error(`[ERROR] RequestCoPlays 构造失败: ${e.message}`);
    }
});

events.on('CMsgGCCStrike15_v2_GetEventFavorites_Request', (data, socket, steamid) => {
    console.log('[HANDLER] GetEventFavorites');
    sendProto(socket, 9203, 'CMsgGCCStrike15_v2_GetEventFavorites_Response', {
        allEvents: false,
        jsonFavorites: "{}",
        jsonFeatured: "{}"
    });
});

events.on('CMsgGCCStrike15_v2_MatchmakingStop', (data, socket, steamid) => {
    const AccountId = steamid ? Number(BigInt(steamid) & 0xFFFFFFFFn) : 0;
    if (!AccountId) {
        console.log(`[HANDLER] MatchmakingStop from unknown id`);
        return;
    } else {
            console.log(`[HANDLER] MatchmakingStop from ${AccountId}`);
    };

    sendProto(socket, 9104, 'CMsgGCCStrike15_v2_MatchmakingGC2ClientUpdate', {
        matchmaking: 0,
        waitingAccountIdSessions: [],
        globalStats: getGlobalStats(),
        // [修复] 这里原来写的是 { prime: true }，但 proto 里的 Note 只有
        // type / region_id / region_r / distance（cstrike15_gcmessages.proto:325），
        // prime 不是有效字段，protobufjs 会静默丢弃 —— 实际发出去的一直是个空 note。
        // 保留空 note 是为了不改动线上的格式（停止匹配本来也不需要带 note），
        // 只是把那个误导性的假字段删掉。
        notes: [{}]
    });

    savePlayer(AccountId);
});


events.on('CMsgGCCStrike15_v2_ClientGCRankUpdate', (data, socket, steamid) => {

    let session = sessions.get(steamid);
    if (!session) {
        console.log(`[ERROR] Session not found for ${steamid}`);
        session = loadPlayer(steamid);
        if (!session) {
            console.log(`[ERROR] No session on disk for ${steamid}`);
            return;
        }
        sessions.set(steamid, session);
    }
    
    const competitiverank = session.rankings.competitive.rank || 1;
    const wingmanrank = session.rankings.wingman.rank || 1;
    const dzrank = session.rankings.dangerzone.rank || 1;
    
    const requestedRankTypeId = data?.rankings?.[0]?.rankTypeId || 6;

    console.log(`[RANK UPDATE] for ${steamid} for rank ${requestedRankTypeId}`);
    
    if (requestedRankTypeId === 6) {
        sendProto(socket, 9194, 'CMsgGCCStrike15_v2_ClientGCRankUpdate', {
            rankings: [
                {
                    accountId: steamid,
                    rankId: competitiverank,
                    wins: session.rankings.competitive.wins || 0,
                    rankTypeId: 6,
                    rankWindowStats: 0,
                    rankIfWin: Math.min(competitiverank + 1, 18),
                    rankIfLose: Math.max(competitiverank - 1, 1),
                    rankIfTie: competitiverank
                },
            ]
        });
    } else {
        sendProto(socket, 9194, 'CMsgGCCStrike15_v2_ClientGCRankUpdate', {
            rankings: [
                {
                    accountId: steamid,
                    rankId: wingmanrank,
                    wins: session.rankings.wingman.wins || 0,
                    rankTypeId: 7,
                    rankWindowStats: 0,
                    rankIfWin: Math.min(wingmanrank + 1, 18),
                    rankIfLose: Math.max(wingmanrank - 1, 1),
                    rankIfTie: wingmanrank
                },
                {
                    accountId: steamid,
                    rankId: dzrank,
                    wins: session.rankings.dangerzone.wins || 0,
                    rankTypeId: 10,
                    rankWindowStats: 0,
                    rankIfWin: Math.min(dzrank + 1, 18),
                    rankIfLose: Math.max(dzrank - 1, 1),
                    rankIfTie: dzrank
                }
            ]
        });
    }
    finishResponse(socket);
});

events.on('CMsgGCCStrike15_v2_Party_Register', (data, socket, steamid) => {
    console.log('[PARTY] Register');
    sendProto(socket, 9190, 'CMsgGCCStrike15_v2_Party_Unregister', {});
});

events.on('CMsgGCCStrike15_v2_ClientRequestJoinServerData', (data, socket, steamid) => {

    const AccountId = steamid ? Number(BigInt(steamid) & 0xFFFFFFFFn) : 0;
    if (!AccountId) {
        console.log(`[HANDLER] ClientRequestJoinServerData from unknown id`);
        return;
    } else {
            console.log(`[HANDLER] ClientRequestJoinServerData from ${AccountId}`);
    };

    // [诊断开关] 设 JSO_9164_REPLY=0 则完全不回这条消息。
    // 用途：cookie 修对之后（服务器会真正接受连接），验证"引擎取走 9164 回复"
    // 本身是不是崩溃的触发点 —— 之前"不崩"的几轮其实是服务器拒绝了连接，
    // 客户端根本没走到这一步，所以那个结论不成立。
    if (process.env.JSO_9164_REPLY === '0') {
        console.log('[9164] 按诊断开关跳过回复（不发任何东西）');
        return;
    }

    let session = loadPlayer(AccountId);

    const competitiverank = session.rankings.competitive.rank || 1;
    const wingmanrank = session.rankings.wingman.rank || 1;
    const dzrank = session.rankings.dangerzone.rank || 1;
    const playerlevel = session.playerLevel || 1;
    const playercurxp = session.playerCurXp || 1;
    const cmdfriendly = session.cmd.friendly || 1;
    const cmdteaching = session.cmd.teaching || 1;
    const cmdleader = session.cmd.leader || 1;

    const readableIp = uint32ToIp(data.serverIp)

    // ===== 按上游 csgo_gc 的配方回复 =====
    // 参照 https://github.com/mikkokko/csgo_gc 的 csgo_gc/gc_client.cpp
    // ClientRequestJoinServerData() —— 那是专门为 CS:GO legacy 客户端做的兼容实现：
    //
    //     response = request;                     // 先整体复制请求
    //     res.serverid        = request.version(); // 注意：填的是 version
    //     res.direct_udp_ip   = request.server_ip();
    //     res.direct_udp_port = request.server_port();
    //     res.reservationid   = GameServerCookieId;   // 0x293A206F6C6C6548
    //     res.server_address  = "ip:port";
    //
    // 关键：**没有 res.reservation 子消息，也没有 map**。
    // 我们原先自己编了一整套 reservation（rankings / encryptionKey / preMatchData …），
    // 逐字段二分证明"只要带 reservation 就闪退"（连空的 reservation 都崩），
    // 与上游做法正好吻合 —— 那段本来就不该发。
    // 严格照搬上游 csgo_gc/gc_client.cpp ClientRequestJoinServerData()，
    // 不再自己改动/二分（之前那些"实测偏离"是在连接被拒的无效前提下得出的，作废）：
    //     response = request;
    //     res.serverid        = request.version();
    //     res.direct_udp_ip   = request.server_ip();
    //     res.direct_udp_port = request.server_port();
    //     res.reservationid   = GameServerCookieId;   // 0x293A206F6C6C6548
    //     res.server_address  = "ip:port";
    // 没有 reservation、没有 map。
    sendProto(socket, 9164, 'CMsgGCCStrike15_v2_ClientRequestJoinServerData',
        Object.assign({}, data, {
            res: {
                serverid: data.version,
                directUdpIp: data.serverIp,
                directUdpPort: data.serverPort,
                reservationid: GC_COOKIE,   // 上游配方就是 GameServerCookieId
                serverAddress: `${readableIp}:${data.serverPort}`
            }
        }));
    console.log(`[9164] 上游原样回复：serverid=version(${data.version}) ` +
                `addr=${readableIp}:${data.serverPort} reservationid=${GC_COOKIE}`);
})

// server body

// [自定义] 推送通道集合。
// srcds 侧改造（external_forwarder 的 PushLoop）会另开一条长连接专门等 GC 下发，
// 这条连接建立后不发任何数据、也不关闭；而普通 GC 请求是"发数据→等响应→关闭"。
// 因此：连接空闲 2 秒仍无数据 ⇒ 判定为推送通道。
const pushSockets = new Set();

// [自定义] 帧格式与 csgo_gc 的 PushLoop 约定一致：
//   [len 4][steamid 8][msgType 4][payload]
// msgType 需要带上 0x80000000 标志位（服务器侧按 TypeMasked 解读）。
function pushToServers(msgType, steamid, payload) {
    const len = payload.length;
    const buf = Buffer.alloc(16 + len);
    buf.writeUInt32LE(len, 0);
    buf.writeBigUInt64LE(BigInt(steamid || 0), 4);
    buf.writeUInt32LE((0x80000000 | msgType) >>> 0, 12);
    payload.copy(buf, 16);

    let sent = 0;
    for (const s of pushSockets) {
        if (!s.destroyed) {
            s.write(buf);
            sent++;
        }
    }
    console.log(`[PUSH] 向 ${sent} 条通道推送 msgType=${msgType} len=${len}`);
    return sent;
}

const server = net.createServer((socket) => {
    const peer = `${socket.remoteAddress}:${socket.remotePort}`;
    console.log(`client connected from ${peer}`);
    const chunks = [];
    let isPushChannel = false;

    const pushTimer = setTimeout(() => {
        if (chunks.length === 0 && !socket.destroyed) {
            isPushChannel = true;
            pushSockets.add(socket);
            console.log(`[PUSH] 登记推送通道 ${peer}，当前 ${pushSockets.size} 条`);
        }
    }, 2000);

    socket.on('data', (data) => {
        clearTimeout(pushTimer);
        chunks.push(data);
    });

    socket.on('end', () => {
        clearTimeout(pushTimer);
        if (isPushChannel) return;
        const packet = Buffer.concat(chunks);
        // [调试] 打印收到的原始帧，便于确认服务器发来的消息
        console.log(`[SOCKET] ${peer} 收到 ${packet.length} 字节` +
            (packet.length >= 12 ? `，msgType=0x${packet.readUInt32LE(8).toString(16)}` : ''));
        const decoded = getMSGdata(packet);
        if (decoded) {
            events.emit(decoded.name, decoded.data, socket, decoded.steamid);
        }
        console.log('[SOCKET] socket closed by server');
    });

    socket.on('close', () => {
        clearTimeout(pushTimer);
        if (isPushChannel) {
            pushSockets.delete(socket);
            console.log(`[PUSH] 推送通道断开，剩余 ${pushSockets.size} 条`);
        } else {
            console.log('[SOCKET] closed by client');
        }
    })

    socket.on('error', (err) => {
        console.log(`[ERROR] socket: ${err.message}`);
    });
});

// ============================================================================
// [新增] 客户端 veto 选图 -> 切换游戏服务器地图
// ============================================================================
// 背景：map veto 跑在**客户端的 server.dll** 里（本地服务器），不在 srcds 里。
// veto 定下地图时会打印 "Map veto pick controller: initiating level transition to %s"，
// csgc.dll 在那个调用点挂了 hook，把地图名写到 csgo.exe 同级的 veto_map.txt。
// 这里轮询该文件，收到新地图就让 srcds 换图 —— 否则 srcds 会一直停在启动时的
// +map 参数上，客户端看到的图和服务器实际跑的图对不上。
//
// 为什么用轮询而不是 fs.watch：GC 启动时该文件还不存在，fs.watch 会直接抛错；
// 轮询更省心，而且这个事件一场比赛最多发生几次。
const { execFile } = require('child_process');   // fs 已在文件顶部 require

// 外部换图通道的路径。**两项都留空 = 不启用**（默认）。
// 原先这里硬编码的是作者本机的路径与 Windows 用户名，读者跑起来必然失败。
const CSGO_DIR = config.csgoDir || '';       // 例: 'C:\\Program Files (x86)\\Steam\\steamapps\\common\\csgo legacy\\'
const VMSSH_PATH = config.vmSshPath || '';   // 自己写：能传文件进 VM + 在 VM 里跑命令
const MAP_SYNC_ENABLED = Boolean(CSGO_DIR && VMSSH_PATH);

const VETO_FILE = CSGO_DIR + 'veto_map.txt';       // csgc 在 veto 定图时自动写入
const MANUAL_FILE = CSGO_DIR + 'server_map.txt';   // 手写指定：想打哪张图就写哪张

let g_vetoMapApplied = null;

function applyServerMap(map) {
    if (!map || map === g_vetoMapApplied) return;
    g_vetoMapApplied = map;

    // srcds 被 script(1) 包在伪终端里、TCP RCON 又不监听，唯一的通道是往它的
    // pts 注入。注意：echo > /dev/pts/N 只是往终端"输出"，命令会被显示但不执行
    // —— 必须用 TIOCSTI 才是真正的 stdin 输入，这就是 VM 侧 srvcmd.sh 干的事。
    const remote = 'sudo ./srvcmd.sh "changelevel ' + map + '"';

    console.log(`[VETO] 切换游戏服务器地图 -> ${map}`);
    execFile('py', [VMSSH_PATH, remote], { timeout: 30000 }, (err, stdout) => {
        if (err) {
            console.error(`[VETO] !! 换图失败: ${err.message}`);
            g_vetoMapApplied = null;     // 允许下次重试
            return;
        }
        console.log(`[VETO] srcds 已收到 changelevel ${map} (${(stdout || '').trim()})`);
    });
}

// 两个来源：csgc 自动写的 veto 结果，以及手动指定的文件。
// 两者等价——谁的值变化谁生效（applyServerMap 按地图名去重）。
const MAP_SOURCES = [
    { path: VETO_FILE, label: 'veto' },
    { path: MANUAL_FILE, label: '手写' },
];

function pollMapFiles() {
    const lastSeen = new Map();
    setInterval(() => {
        for (const src of MAP_SOURCES) {
            let map = null;
            try {
                map = fs.readFileSync(src.path, 'utf8').trim();
            } catch (e) {
                continue;                    // 文件还不存在，属正常
            }
            if (!map || map === lastSeen.get(src.path)) continue;
            lastSeen.set(src.path, map);
            console.log(`[MAP] ${src.label} 指定 -> ${map}`);
            applyServerMap(map);
        }
    }, 2000);
    console.log(`[MAP] 轮询 ${VETO_FILE} 与 ${MANUAL_FILE}（每 2 秒）`);
}

// 没配路径就不轮询 —— 否则读者机器上每 2 秒一次必然失败的 execFile。
if (MAP_SYNC_ENABLED) {
    pollMapFiles();
} else {
    console.log('[MAP] 外部换图通道未启用（config.json 里没配 csgoDir / vmSshPath）');
}

// params

const PORT = config.port;
const HOST = config.host;

server.listen(PORT, HOST, () => {
    console.log(`[Notification] GC running on ${HOST}:${PORT}`);
});
