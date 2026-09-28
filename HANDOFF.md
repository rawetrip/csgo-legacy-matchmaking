# 交接：CS:GO Legacy「点开始竞技自动进局」

> 把本文件全文粘进新会话的第一条消息即可。

## 一句话现状（2026-09-28 更）

**已全线打通。** 点「开始竞技」→ 弹窗 → 自动连接 → **真正进入服务器并能打**
（服务器日志 `Client "as_R4nd0m" connected (192.168.1.7:27005).`）。

最终卡点的解法是 **把 srcds 换成 `sv_lan 1` 跑**，下面是为什么。

## 环境（每次测试前要点的三样）

| 组件 | 位置 | 启动方式 |
|---|---|---|
| 虚拟机 | `Ubuntu-CSGO` | `VBoxManage startvm "Ubuntu-CSGO" --type headless` |
| Linux srcds | VM `192.168.1.64:27015` | `py vmssh.py "cd /home/csgo && ./start-srcds.sh"`（脚本内已是 `sv_lan 1` + `-dev`） |
| 自建 GC | 宿主机 `127.0.0.1:3257` | `cd gc-replacement && node Server_v3.js` |

- **srcds 必须用 `setsid nohup ... & sleep 10` 起**，否则后台进程随 SSH 会话一起被回收。
- 客户端必须**由 Steam 启动**（`steam.exe -applaunch 4465480` 或点 Steam 的「开始」）；
  用 `Start-Process csgo.exe` 直接拉会进 insecure 状态，**匹配按钮被禁**。
- `py vmssh.py "<cmd>"` / `py vmscp.py <本地> <远端>`：**vmscp 远端路径只能用相对路径**
  （绝对路径报 `ENOENT`，paramiko 的老毛病）。
- **pkill 自匹配坑**：`pkill -f 'srcds_linux'` 会连自己的 ssh 会话一起杀（命令行里含该串）。
  写成 `pkill -f 'srcds_[l]inux'`。

## 卡点的真相（这次查清了）

### 1. 服务器那个「Reservation cookie 0」是假的

日志里 `-> Reservation cookie 0:  reason reserved(yes), clients(no), reservationexpires(0.00)`
**只在「服务器 cookie != 0」时才打印**，而那个 `0` 是**写死的常量**：

```asm
1a182d  mov 0x2f0(%esi),%eax     ; 服务器自己的 cookie
1a1833  or  0x2ec(%esi),%eax
1a1839  je  1a1624               ; cookie == 0 → 直接返回，什么都不打印
1a187f  call 1d7970              ; 打印 "reserved(...)"，cookie 参数 push $0x0
```

上一轮会话把那个 `0` 当成了真值，跑去改 GC 的 `GC_COOKIE`（无效，已回滚）。
**真实情况是：服务器持有一个非零 reservation cookie，客户端带的是 `Hello :)`（=GC 的 GC_COOKIE），两者不等。**

放行条件在 `engine.so`（32 位，Addr==Off）0x1d0776 起：

```asm
mov 0x2ec(%esi),%eax   ; 服务器 cookie
xor ... 客户端 cookie
je  1d2790             ; 相等 → 放行
or  %ebx,%ecx
je  1d2790             ; ★ 服务器 cookie == 0 → 也放行
                       ; 否则 → 拒绝（#Valve_Reject_Reserved_For_Lobby）
```

**所以只要服务器 cookie 是 0 就放行 → `sv_lan 1`**（不登录 Steam → 拿不到那个 cookie → 保持 0）。
这一条也解释了为什么之前 `sv_lan 1` "能绕过 reservation"。

顺带否掉一个担心：客户端 `engine.dll` 里那条判定是
`Cannot direct-connect to Valve CS:GO Server` —— 规则是**「是 Valve 官方服才不允许直连」**，
我们这台本来就不是 Valve ds（服务器侧对应打印 `Not Valve ds: Direct-connect is allowed`），
所以客户端不会因为 `sv_lan` 把它当 LAN 服丢弃。

### 2. 每连一次就换图（死循环的直接原因）

连接处理函数里有一整块「服务器已预留 → 直接开局」的逻辑（0x1d8314~0x1d8389）：

```asm
1d8327  push $0x50cc2e      ; "nextlevel %s"
1d8333  call 1288e0         ; sprintf(buf, "nextlevel de_cache")
1d8340  push $0x2           ; 执行标记 2
1d8342  call 1e7150         ; 入队执行 nextlevel
1d8367  push $0x50cc3c      ; "map %s reserved"
1d836d  call 1288e0         ; sprintf(buf, "map de_cache reserved")
1d837a  push $0x2
1d837c  call 1e7150         ; ★ 入队执行 map <map> reserved
1d8384  call 1e8090         ; Cbuf_Execute（"Executing command outside main loop thread"）
```

`map <map> reserved` 一执行就**立刻重载关卡**（日志里的 `---- Host_Changelevel ----`，
以及 `GameTypes: could not find matching game mode value of "reserved" in any game type.`）。
客户端被换图踢下线 → 引擎自动重连（`Retrying public(...)`）→ 服务器又重放这一块 → 死循环。
这块由 `0x288(%ebx)`（服务器「已预留」标志）把关，而我们的服务器那个假 reservation 永远耗不掉。

在 `sv_lan 1` 下这条根本不触发，所以现在不需要它；但 `csgo_srvfix.so` 还挂在 LD_PRELOAD 里
（它把 0x1d837c 的 `call 1e7150` NOP 掉，即不执行 `map ... reserved`），
**如果哪天要回到 `sv_lan 0`，这层补丁是必须的**。

### 3. 服务器侧自己的 GC 也是断的（背景噪声，暂时无解）

启动时服务器会向 GC 发 9106 并收到
`[GC] No response from external GC for msg 2147492754`（Steam 客户端的 GC 代理，
转发到 Valve 那侧没人应）。这不是当前卡点，但说明服务器侧没有真 GC。

## 已做成的（重要，别再重走）

| # | 事项 | 关键 |
|---|---|---|
| 1 | 客户端直连进服 | 稳定停在 `INGAME` |
| 2 | 点「开始竞技」→ 弹窗出现 | `$.DispatchEvent("ServerReserved", 真实map)`（官方事件路径） |
| 3 | 弹窗自动关闭 | `$.DispatchEvent("PanoramaComponent_Lobby_ReadyUpForMatch", false, 0, 0)` |
| 4 | csgc 自动发起连接 | **`Cbuf_AddText(engine.dll+0x1DB910)`，执行标记传 `2`** |
| 5 | **真正进服不被打回** | **srcds 用 `sv_lan 1`** |
| 6 | **同一进程内可反复匹配进服** | csgc 收到 **9101**（`0x8000238D`）时清零一次性标记 |

### 4. 为什么是 `Cbuf_AddText` + flag=2

引擎命令路径上有 `FCVAR_CLIENTCMD_CAN_EXECUTE` 检查，只放行"玩家亲手敲的"命令，
依据是命令的**来源标记**：玩家控制台 → `2` 放行；`IVEngineClient::ClientCmd` → `0/1`（被 `setne` 布尔化）被拒；
汇编桩直接调 `Cbuf_AddText` 传 `2` → 放行。实现见 `csgc-src/src/steam_hook_lite.cpp` 的
`IssueConnect()` / `CallCbufAddText()`。

### 两条实测会崩的路（别重走）

- 在 csgc 自己的线程里调 `connect` 命令体（`engine.dll+0xDA6A0`）：碰 UI，V8 报
  `HandleScope::CreateHandle0` 致命错误。
- hook Panorama 事件派发（`panorama.dll+0x417F0`）：打乱事件泵，`eip` 跳到未映射地址崩溃。

## 未完成 / 已知问题

- ~~二次匹配不进服~~ **已修**：csgc 的 `g_connectScheduled` 原本是**一次性**的
  （`ScheduleConnect()` 里 `InterlockedExchange(&g_connectScheduled, 1)`），
  第一次 9107 之后所有 9107 都被 `[CONN] duplicate 9107 ignored` 吞掉，第二次点按钮永远不连。
  修法：在 `GameCoordinatorProxyLite::SendMessage` 里，收到 **9101 MatchmakingStart
  （`0x8000238D`）就清零 `g_connectScheduled` / `g_connectFired`**（补丁脚本 `~/patch_rearm.py`，
  bytes 级替换保住 GBK 注释）。**实测通过**：一次游戏进程内两次匹配都能进服
  （csgc 日志 `[CONN] 9101 MatchmakingStart: connect re-armed`，服务器两次
  `Client "as_R4nd0m" connected`）。
  （客户端发给 GC 的消息类型统计，便于以后定位：9164×2298、9103×1832、4006×68、
  **9101×66**、9201×64、9102×23。）
- ~~弹窗~~ **已完成（走的是官方路径）**。核心是发现 `ServerReserved` 的 **map 参数前面加一个 `@`**
  就切到官方「公告式自动就绪」模式（`popup_accept_match.js` 里 `map.charAt(0) === '@'`），
  一次拿到三个东西：CS2 那种只剩标题+模式·地图的形态（官方 `auto` 样式）、
  安静的 `waitquiet`（**休闲模式没有 beep 的原因**）、以及 1.9 秒后官方
  `_OnNqmmAutoReadyUp` 自动执行（播 `mm_success_lets_roll`、`LobbyAPI.SetLocalPlayerReady('deferred')`、
  用官方路径关弹窗 —— 那句一直刷的 `will not queue connect` 就是之前没调 SetLocalPlayerReady）。
  - **只能隐藏、不能删节点** —— `popup_accept_match.js` 会对这些面板做
    `RemoveAndDeleteChildren()` / `SetDialogVariableInt()` / `RemoveClass('hidden')`，
    节点不存在直接抛异常把 UI 搞坏。给 `id-map-draft-phase-teams`（假阵容）和
    `accept-match__slots-count`（0/10 计数行）加**内联 `style="visibility:collapse;"`**，id 全保留。
  - **布局**：把 `AcceptMatchDataContainer` 移到 `AcceptMatchMapImage` **之前**（休闲形式是
    文字在上、小地图在下；原 XML 是竞技版顺序）。（`patch_popup.py` 用配平计数切块 ——
    注意自闭合 `<Panel .../>` 不能计 +1，否则永远配不平。）
  - **尺寸**（两处都得改，只改一处无效）：① `.accept-match__map` 高度 300px → **150px**；
    ② 给 `<Panel class="accept-match__bg">` 加内联 `style="min-width: 620px; height: 278px;"`。
    那层 CSS 是 `height: fit-children`、背景是视频 `gobutton.webm`，
    **只改地图高度面板高度纹丝不动（一直 480）**。
  - **时序**：官方 1.9s 自动就绪关弹窗 → `csgc` 连接延时设 **2.6s**（`Sleep(2600)`），
    衔接紧凑。`party.js` 里 12s 的定时器和 `GameState_LevelInitPreEntity` 只作兜底。
  - **音效**：官方由引擎在抛 `ServerReserved` 时播「就绪音」，我们自己抛就得自己补
    `popup_accept_match_found`（`game_ready_02.wav`）。**不要**再补 `..._confirmed` ——
    官方 `_OnNqmmAutoReadyUp` 已经播了，多播一次就是官方那个「lets roll 响两遍」的 bug。
  - **踩过的信号坑**：`GameStateAPI.IsPlayerConnected()` 在「正在连接至服务器…」阶段仍是 false、
    `IsLocalPlayerPlayingMatch()` 更晚，**都不能用来判断「进加载了」**。
- 弹窗里的**假玩家名**（`[unknown]`/好友名）：GC 不发真实阵容，客户端拿垃圾 XUID
  去解析出来的，无实际影响。

### 弹窗面板树（改精简时直接用）

```
[]                                  ← 弹窗根
  [id-accept-match]
    [AcceptMatchWarning]
    []                              ← bg
      [AcceptMatchMapImage]
      [AcceptMatchDataContainer] → [AcceptMatchModeIcon] [AcceptMatchModeMap]   ← 保留
      [id-map-draft-phase-teams] → [id-map-draft-phase-your-team/-other-team]
                                     → [id-map-draft-phase-avatars] → [假XUID...]  ← 可删
      [AcceptMatchSlots] [AcceptMatchPlayersAccepted]                             ← 可删
      [AcceptMatchBtn]                                                            ← 可删
      [AcceptMatchCountdown]
    [Agreement]
```

## 服务端补丁（这次新造）

| 文件 | 作用 |
|---|---|
| `~/srvfix.c` → VM `/home/csgo/csgo_srvfix.so` | 运行时改 `engine.so`：NOP 掉 `map <map> reserved` 的入队（见上文 §2）。随 `LD_PRELOAD` 加载，签名锚点唯一命中 0x1d82f5，补丁打在锚点+0x87。 |
| `~/appidfix.c`（早先） | 同框架：改 appid 校验跳转表，让 legacy 客户端票据能过。 |
| `~/patch_rearm.py` | 改 `csgc-src` 源码：收到 9101 清零 csgc 的一次性连接标记 |
| `~/patch_delay.py` | 改 `csgc-src` 源码：连接延时 8s → 5s |
| `~/patch_popup.py` | 生成精简版 `popup_accept_match.xml`（隐藏假阵容/计数行，保留全部 id） |
| `~/make_party.py` | 生成 `party.js`（触发/关闭/音效/时序都在这里，改完必须 `pbin_tool.py put` 回读校验） |

**改 `csgc-src` 源码一律走 bytes 级替换**（GBK 文件，见上文坑 5）；编完要把
`dist/csgc/csgc.dll` 拷到 `<游戏目录>/csgc/csgc.dll`（游戏关着才能覆盖）。

**写这类补丁的两个坑（都真踩过）**：

1. **`je rel32`(6 字节) 换成 `jmp rel32`(5 字节) 时位移不能照抄** —— rel32 是相对
   「指令末尾」的，照抄会差 1 字节、跳进指令中间，解码成垃圾后写坏内存 → SIGSEGV。
   排查靠 `sudo dmesg | grep segfault`（会直接给出 `ip=base+偏移`）。
2. **签名里的绝对地址要屏蔽**（会被重定位），相对位移和结构体偏移不用。

## 工具（主目录；已同步到仓库 `csgo-legacy-matchmaking/tools/`）

| 脚本 | 用途 |
|---|---|
| `auto_cdb.py` | 看门狗：csgo.exe 一启动就附加 cdb |
| `make_party.py` | 生成 party.js（官方事件路径版） |
| `pbin_tool.py` | code.pbin 读写（ls/get/put，保留头与 zip 注释） |
| `disasm.py` / `xref.py` / `rdstr.py` | capstone 反汇编 / 交叉引用 / 字符串 dump（按 RVA） |
| `vpk_extract.py` | VPK 批量解包（**v2 头部是 28 字节不是 12**） |
| `vmssh.py` / `vmscp.py` | 虚拟机命令 / 传文件（**远端用相对路径**） |
| `rcon_check.py` | Source RCON 客户端（**本机 Linux srcds 实测 TCP 27015 不监听，用不上**） |
| `srvre.py` | 解析 ELF32 节表 + 定位字符串 vaddr（`Addr == Off`，所以偏移即 vaddr） |

## 踩过的坑（真金白银）

1. **`code.pbin` 是明文 zip**，改它要保留 16 字节头 + 尾部注释；改坏一个 `>` 会让整个
   XML 解析失败（弹窗直接不出现），改完必须回读 + `xml.etree` 验证。
2. Panorama 音效要用事件名（带 `UIPanorama.` 前缀），定义在 VPK 的
   `scripts/game_sounds_ui_panorama.txt`。
3. `$.DispatchEvent` 拒绝未注册的事件名 —— 名字必须已被 `RegisterForUnhandledEvent` 过。
4. `party.js` 是两个独立 IIFE，在 `PartyMenu` 自己的 IIFE 内写 `PartyMenu.xxx = ...` 会
   `ReferenceError`。
5. **改 C++ 源注意编码**：`csgc-src` 下是 GBK（MSVC 按 936 读）。改它要用 **bytes 级替换**
   （见 `patch_rearm.py`），别用会解码/重编码的工具。构建：`cmake --build build --config Release`
   （VS 2022 / Win32），产物 `dist/csgc/csgc.dll` → 部署到 `<游戏目录>/csgc/csgc.dll`。
6. cdb 必须「附加」不能直接启动游戏；`-c` 串里不能有嵌套引号；必须
   `sxd 40010006; sxd 4001000a`。别对附加中的 cdb 用 timeout 强杀。
7. **`-dev` 才有 DevMsg**：`Rejecting connection request ...` 这类关键行只有开发者模式才打印，
   排 reservation 问题必须开。
8. 服务器启 `-dev` 后地图加载会刷上万行 `DISP_VPHYSICS`，grep 时先过滤。
