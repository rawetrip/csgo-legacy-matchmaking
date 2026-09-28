# 交接：CS:GO Legacy「点开始竞技自动进局」

> 把本文件全文粘进新会话的第一条消息即可。最后更新：2026-09-28（全部打通）。

## 0. 一句话现状

**全线打通并可用**：点「开始竞技」→ 官方弹窗 → 自动就绪 → 自动连服 → 真正进图能打；
**同一局游戏进程内可以反复匹配**，不需要重启客户端。

```
点「开始竞技」
  → [客户端] 发 9101 MatchmakingStart 给自建 GC
  → [GC]     回 9104 更新 + 9107 ClientReserve（含服务器地址、reservationid="Hello :)"）
  → [csgc]   在 RetrieveMessage 截到 9107：排一个 2.6s 后发 connect 的任务
  → [party.js] 轮询到 mmqueue=reserved：派发官方事件 ServerReserved("@de_cache")
  → [客户端] 官方弹窗以「公告式/休闲」形态出现，1.9s 后官方 _OnNqmmAutoReadyUp 自己
             ready-up 并关弹窗（播 mm_success_lets_roll）
  → [csgc]   2.6s 到了：Cbuf_AddText("connect 192.168.1.64:27015", flag=2)
  → [引擎主线程] 执行 connect → 进加载 → INGAME
```

## 1. 环境与每次测试前要起的三样

| 组件 | 位置 | 启动方式 |
|---|---|---|
| 虚拟机 | `Ubuntu-CSGO`（VirtualBox 7.2.20，桥接 `192.168.1.64`） | `VBoxManage startvm "Ubuntu-CSGO" --type headless`（`C:\Program Files\Oracle\VirtualBox\VBoxManage.exe`） |
| Linux srcds | VM 内 `192.168.1.64:27015` | `py vmssh.py "cd /home/csgo && setsid nohup ./start-srcds.sh >/dev/null 2>&1 </dev/null & sleep 10"` |
| 自建 GC | 宿主机 `127.0.0.1:3257` | `cd gc-replacement && node Server_v3.js` |
| CS:GO 客户端 | 宿主机 `192.168.1.7`，目录 `…/common/csgo legacy` | **必须由 Steam 启动**（Steam 里点开始，或 `steam.exe -applaunch 4465480`） |

**环境细节**

- VM 用户 `csgo`（免密 sudo）；SSH 凭据写在 `vmscp.py` / `vmssh.py` 里。
- srcds 装在 VM `/home/csgo/csgo-server`（steamcmd `app_update 740`），启动脚本 `/home/csgo/start-srcds.sh`，
  日志 `/home/csgo/srcds-run.log`（`script(1)` 包了个伪终端，所以能实时看到输出）。
- srcds 的启动参数里关键几项：`-dev`（开 DevMsg）、`+sv_lan 1`（**见 §3.1，这是能进服的根因**）、
  `+sv_setsteamaccount <GSLT>`、`+map de_cache`。
- LD_PRELOAD 两个自写补丁：`csgo_appidfix.so`（让 legacy 客户端票据能过 appid 校验）、
  `csgo_srvfix.so`（只在切回 `sv_lan 0` 时才需要，见 §3.2）。
- 客户端侧被改动的四件：`csgo.exe`（自编译 launcher）、`bin/panorama.dll`、
  `csgo/panorama/code.pbin`、新增 `csgc/csgc.dll`。原始备份在 `csgo-legacy-backup/`。
- csgc 的 GC 转发地址在 `forwarder.cpp` 里**硬编码**（上游是 `176.196.110.121`，我们改成了
  `127.0.0.1`），改地址要重新编译。

## 2. 主要机制（都是实测打出来的）

### 2.1 让客户端自己发起连接：`Cbuf_AddText` + 标记 `2`

引擎命令路径上有 `FCVAR_CLIENTCMD_CAN_EXECUTE` 检查，只放行"玩家亲手敲的"命令，
判断依据是命令的**来源标记**：

| 路径 | 标记 | 结果 |
|---|---|---|
| 玩家控制台 → 直接执行 | `2` | 放行 |
| `IVEngineClient::ClientCmd` → Cbuf | `0/1`（反汇编里被 `setne cl` 布尔化） | **被拒** |
| **汇编桩直接调 `Cbuf_AddText`，标记传 2** | `2` | **放行** |

实现：`csgc-src/src/steam_hook_lite.cpp` 的 `IssueConnect()` / `CallCbufAddText()`
（`ecx`=缓冲索引、`edx`=字符串、栈上传 (标记,0)，**调用者清栈**）。
好处是命令由**引擎主线程**执行，和玩家手敲同路。

### 2.2 弹窗：官方"公告式自动就绪"模式（`@` 前缀）

`popup_accept_match.js` 里：

```js
var map = settings.split( ',' )[ 0 ];
if ( map.charAt( 0 ) === '@' )        // ← 地图名前面加一个 @
{
    m_isNqmmAnnouncementOnly = true;  // 公告式（休闲）形态
    m_hasPressedAccept = true;        // 倒计时改用安静的 waitquiet —— 这就是"没有 beep"的原因
    map = map.substr( 1 );
}
...
if ( m_isNqmmAnnouncementOnly )
    m_jsTimerUpdateHandle = $.Schedule( 1.9, _OnNqmmAutoReadyUp );
```

`_OnNqmmAutoReadyUp` 会：播 `popup_accept_match_confirmed`（`mm_success_lets_roll.wav`）、
`LobbyAPI.SetLocalPlayerReady('deferred')`、`CloseAcceptPopup` + `UIPopupButtonClicked`。

**所以只要在派发 `ServerReserved` 时把地图名写成 `"@" + map`**，就一次拿到：
官方极简形态、无 beep、1.9s 自动就绪、官方关闭路径。
（`SetLocalPlayerReady` 这一条尤其重要 —— 以前没调，控制台一直刷
`server reservation1 is awaiting ... / will not queue connect`。）

### 2.3 二次匹配：9101 重新武装

`ScheduleConnect()` 里 `InterlockedExchange(&g_connectScheduled, 1)` 是**一次性**的，
第一次 9107 之后所有 9107 都被 `[CONN] duplicate 9107 ignored` 吞掉 → 第二次点按钮永远不连。
修法：`GameCoordinatorProxyLite::SendMessage` 里收到 **9101 MatchmakingStart（`0x8000238D`）**
就清零 `g_connectScheduled` / `g_connectFired`（`patch_rearm.py`）。

> 客户端发给 GC 的消息类型统计（1 次会话）：9164×2298、9103×1832、4006×68、
> **9101×66**、9201×64、9102×23、9193×1。

### 2.4 两条实测会崩的路（别重走）

- 在 csgc 自己的线程里调 `connect` 命令体（`engine.dll+0xDA6A0`）：它碰 UI，
  V8 报 `HandleScope::CreateHandle0` 致命错误；即使 `__try` 兜住也已留下破坏，之后加载地图时崩。
- hook Panorama 事件派发（`panorama.dll+0x417F0`）：打乱事件泵（一帧积压几千个待派发），
  最后 `eip` 跳到未映射地址崩溃。

## 3. 三个卡点的根因（这次查清的）

### 3.1 ★ 服务器那个 reservation cookie（**能进服的关键**）

`engine.so`（**32 位 ELF，注意 Addr == Off，文件偏移即 vaddr**）0x1d0776 起：

```asm
mov 0x2ec(%esi),%eax   ; 服务器自己的 reservation cookie
xor ...                ; 与客户端 connect 包里带的 cookie 比对
je  1d2790             ; 相等 → 放行
or  %ebx,%ecx
je  1d2790             ; ★ 服务器 cookie == 0 → 也放行
                       ; 否则 → #Valve_Reject_Reserved_For_Lobby（静默踢，DevMsg 里才有）
```

`sv_lan 0` 的 srcds 会从 Valve 侧拿到一个**非零**的 reservation cookie，而客户端带的是
GC 下发的 `Hello :)`（`0x293A206F6C6C6548` = `GC_COOKIE`），两者不等 → 连接被静默拒绝。

**解法：srcds 用 `sv_lan 1`** —— 不登录 Steam 就拿不到那个 cookie，保持 0 → 走放行分支。

> **务必记住这个更正**：日志里
> `-> Reservation cookie 0:  reason reserved(yes), clients(no), reservationexpires(0.00)`
> 的 **`0` 是写死的常量**（`1a187a: push $0x0; push $0x0`），而且**这行只在
> 「服务器 cookie != 0」时才打印**（`1a1839: je 1a1624` 会跳过打印）——
> 它恰恰是 cookie **非零**的证据。早期据此去改 GC 的 `GC_COOKIE`，方向完全反了。

顺带否掉一个担心：客户端 `engine.dll` 里那条判定是
`Cannot direct-connect to Valve CS:GO Server` —— 规则是**「是 Valve 官方服才不允许直连」**，
我们这台从来不是 Valve ds（服务器侧对应打印 `Not Valve ds: Direct-connect is allowed`），
所以客户端不会因为 `sv_lan` 把它当 LAN 服丢弃。

### 3.2 连上就被踢 → 无限重连（`sv_lan 0` 时）

连接处理里有一整块「服务器已预留 → 直接开局」（engine.so 0x1d8314~0x1d8389）：

```asm
1d8327  push $0x50cc2e      ; "nextlevel %s"
1d8333  call 1288e0         ; sprintf(buf, "nextlevel de_cache")
1d8340  push $0x2
1d8342  call 1e7150         ; 入队执行
1d8367  push $0x50cc3c      ; "map %s reserved"
1d836d  call 1288e0         ; sprintf(buf, "map de_cache reserved")
1d837c  call 1e7150         ; ★ 入队执行 → 立刻重载关卡
1d8384  call 1e8090         ; Cbuf_Execute（"Executing command outside main loop thread"）
```

`map <map> reserved` 一执行就重载关卡（日志里 `---- Host_Changelevel ----`，
以及 `GameTypes: could not find matching game mode value of "reserved"`），
客户端被踢 → 引擎自动重连（`Retrying public(...)`）→ 服务器又重放 → 死循环。
把关的是 `0x288(%ebx)`（「已预留」标志），我们那个假 reservation 永远耗不掉。

`sv_lan 1` 下根本不触发；**要回到 `sv_lan 0` 就必须挂 `csgo_srvfix.so`**
（它把 0x1d837c 的 `call 1e7150` NOP 掉，即不执行那条 map 命令，保留 nextlevel 和 Cbuf_Execute）。

### 3.3 服务器自己的 GC 也是断的（背景噪声，暂不解决）

srcds 启动时会通过 Steam 客户端的 GC 代理向 GC 发 9106，得到
`[GC] No response from external GC for msg 2147492754`。这不是当前卡点
（客户端走的是我们的 GC），但意味着**服务器侧拿不到真 reservation**，
也解释了 §3.1 里那个非零 cookie 的来历不明。

## 4. 已完成清单

| # | 事项 | 关键做法 |
|---|---|---|
| 1 | 客户端直连进服 | 稳定停在 `INGAME` |
| 2 | 点「开始竞技」→ 弹窗出现 | 官方事件路径 `$.DispatchEvent("ServerReserved", "@"+map)` |
| 3 | 弹窗自动关闭 + 就绪 | 官方 `@` 公告式 → 1.9s 后 `_OnNqmmAutoReadyUp` |
| 4 | csgc 自动发起连接 | `Cbuf_AddText(engine.dll+0x1DB910)`，标记传 `2` |
| 5 | **真正进服不被打回** | srcds 用 `+sv_lan 1` |
| 6 | **同进程内可反复匹配** | csgc 收到 9101 时清零一次性标记 |
| 7 | 弹窗精简（CS2 样式） | 隐藏假阵容/计数行（内联 `visibility:collapse`，**不删节点**） |
| 8 | 弹窗布局与尺寸 | 数据块移到地图**之前**；外层盒子内联钉死 `620×278` |
| 9 | 音效 | 补播 `popup_accept_match_found`（`game_ready_02.wav`） |

## 5. 补丁/工具与「改完怎么生效」

### 5.1 客户端（`code.pbin` 是明文 zip，可直接改）

| 脚本 | 作用 | 生效方式 |
|---|---|---|
| `make_party.py` | 生成 `party.js`（触发/音效/时序/重新武装都在这） | `py make_party.py party_orig.js party_new.js` → `py pbin_tool.py put panorama/scripts/party.js party_new.js` |
| `patch_popup.py` | 生成精简版 `popup_accept_match.xml` | `put panorama/layout/popups/popup_accept_match.xml …` |
| `patch_popup_css.py` | 压缩地图区高度（300→150） | `put panorama/styles/popups/popup_accept_match.css …` |

**每一步装完必须回读校验**：`pbin_tool.py get` 回同一路径 + `xml.etree` 解析（XML）/字节比对（JS、CSS）。
**改这些文件时游戏必须关着** —— 否则运行中的游戏用的还是启动时读进内存的旧副本（踩过，白测一轮）。

### 5.2 csgc（`~/csgc-src`）

```bash
py patch_rearm.py / py patch_delay.py     # 改源码（bytes 级，见坑 13）
cd csgc-src && cmake --build build --config Release
cp dist/csgc/csgc.dll "<游戏目录>/csgc/csgc.dll"     # 游戏关着才能覆盖
```

### 5.3 服务端（VM）

```bash
py vmscp.py srvfix.c srvfix.c
py vmssh.py "cd /home/csgo && gcc -m32 -shared -fPIC -O2 -o csgo_srvfix.so srvfix.c -ldl"
# 重启 srcds 才生效
```

### 5.4 工具清单

| 脚本 | 用途 |
|---|---|
| `auto_cdb.py` | 看门狗：csgo.exe 一启动就自动附加 cdb（**新会话先拉起来**，崩溃能直接抓现场） |
| `pbin_tool.py` | `code.pbin` 读写（ls/get/put，保留 16 字节头与尾部 zip 注释） |
| `disasm.py` / `xref.py` / `rdstr.py` | capstone 反汇编 / 交叉引用 / 字符串 dump（按 RVA，不怕 ASLR） |
| `srvre.py` | **服务端专用**：解析 ELF32 节表、给出字符串 vaddr（server 的 engine.so 是 32 位 ELF） |
| `vpk_extract.py` / `vpk_get.py` | VPK 批量解包 / 取单文件（**v2 头部是 28 字节不是 12**） |
| `vmssh.py` / `vmscp.py` | 虚拟机命令 / 传文件 |
| `rcon_check.py` | Source RCON 客户端（**本机 Linux srcds 实测 TCP 27015 不监听，用不上**） |
| `find_cookie.py` | 在 csgo.exe 内存里搜 cookie（`"Hello :)"` 那 8 字节） |
| `appidfix.c` / `srvfix.c` | 两个 LD_PRELOAD 服务端补丁（见 §1） |

## 6. 踩过的坑（真金白银，按主题）

**客户端资源**
1. `code.pbin` 是明文 zip，但改它要保留 16 字节头 + 尾部注释；**改坏一个 `>` 会让整个资源
   解析失败**（弹窗直接不出现），改完必须回读 + `xml.etree` 验证。
2. 改完不重启游戏 = 没改（游戏启动时读进内存）。
3. Panorama 音效要用事件名（`PlaySoundEffect` 传后缀，定义在 VPK 的
   `scripts/game_sounds_ui_panorama.txt`，实际事件名带 `UIPanorama.` 前缀）。
   例：`popup_accept_match_found` → `game_ready_02.wav`；`..._confirmed` → `mm_success_lets_roll.wav`。
4. `$.DispatchEvent` 拒绝未注册的事件名（`Invalid event name`）。
5. `party.js` 是两个独立 IIFE；在 `PartyMenu` 自己的 IIFE 内写 `PartyMenu.xxx = …` 会 `ReferenceError`。
6. **弹窗面板只能隐藏不能删**：`popup_accept_match.js` 会做
   `RemoveAndDeleteChildren()` / `SetDialogVariableInt()` / `RemoveClass()`，
   节点缺失直接抛异常把 UI 搞坏（这正是早期"关不掉弹窗"的真凶）。
7. **只改地图高度压不小弹窗**：`.accept-match__bg` 的 CSS 是 `height: fit-children`、
   背景是视频 `videos/gobutton.webm`，实测面板高度不随内容变（一直 480）→ 必须内联钉死外层尺寸。
8. CSS 锚点注意 **CRLF** 行尾（不然一条都匹配不到）。
9. 用 `<Panel …/>` 配平计数找块尾时，**自闭合标签不能计 +1**，否则永远配不平。

**客户端进程**
10. **游戏必须由 Steam 启动**（Steam 里点开始 / `steam.exe -applaunch 4465480`）；
    用 `Start-Process csgo.exe` 直接拉会进 insecure 状态，**匹配按钮被禁**。
11. cdb 必须「附加」不能直接启动游戏；`-c` 串里不能有嵌套引号（会等 stdin 干挂）；
    必须 `sxd 40010006; sxd 4001000a`（否则 `OutputDebugString` 的日志淹没一切）；
    **别对附加中的 cdb 用 timeout 强杀**（游戏会跟着死）。
12. `GameStateAPI.IsPlayerConnected()` 在「正在连接至服务器…」阶段仍是 false、
    `IsLocalPlayerPlayingMatch()` 更晚 —— **都不能用来判断"进加载了"**。

**源码/补丁**
13. **改 `csgc-src` 下的 C++ 必须用 bytes 级替换**（文件是 GBK，MSVC 按 936 读）；
    用会解码/重编码的编辑器会写出莫名其妙的东西。
14. **`je rel32`(6 字节) 改成 `jmp rel32`(5 字节) 时位移不能照抄** —— rel32 是相对
    「指令末尾」的，照抄会差 1 字节、跳进指令中间，解码成垃圾后写坏内存 → SIGSEGV。
    排查：`sudo dmesg | grep segfault`，会直接给出 `ip=base+偏移`。
15. 签名扫描里**绝对地址要屏蔽**（会被重定位），相对位移和结构体偏移不用屏蔽。

**工具/运维**
16. `vmscp.py` **远端只能用相对路径**（绝对路径报 `ENOENT`，paramiko 老毛病）。
17. `pkill -f 'srcds_linux'` 会**连自己的 ssh 会话一起杀**（命令行里含该串）→ 写 `'srcds_[l]inux'`。
18. VM 里后台起进程要 `setsid nohup … & sleep 10`，否则随 SSH 会话被回收（日志都还没建就被杀）。
19. **`-dev` 才有 DevMsg**：`Rejecting connection request …` 这类关键行只有开发者模式才打印；
    代价是地图加载会刷上万行 `DISP_VPHYSICS`，grep 时先过滤。

## 7. 未完成 / 可选

- **弹窗的每秒 beep 没有**（可选）：官方逻辑是「倒计时在走且没人按接受」就每秒播
  `popup_accept_match_beep`；我们的 GC 在 9107 里没下发「预留截止时间」，
  弹窗的 `m_numSecondsRemaining` 压根没跑起来。要补得改 `gc-replacement/Server_v3.js` 的 9107 字段。
- **服务器侧 GC**（根本解法）：让 srcds 也能拿到我们的 GC 的 reservation（即回答它的 9106），
  就不用 `sv_lan 1` 了。之前试过服务器侧 hook（`csgo_gc-mm`）编译通过但运行崩溃 —— Steam hook
  是客户端专用的，服务器侧要重写。
- **弹窗尺寸/宽度微调**：现在是 `620×278`，想更贴近某个参考继续调 `patch_popup.py` 的内联值即可。
- 弹窗里的**假玩家名**（`[unknown]`/好友名）：GC 不发真实阵容，客户端拿垃圾 XUID 去
  `FriendsListAPI.GetFriendName()` 解析出来的，无实际影响（现在那整块已经被隐藏了）。

## 8. 参考：弹窗面板树（改布局时用）

```
[]                                  ← 弹窗根 PopupCustomLayout
  [id-accept-match-chat-container]  ← 聊天容器（可隐藏）
  [id-accept-match]
    [AcceptMatchWarning]
    []                              ← bg（尺寸由内联样式钉死 620x278）
      [AcceptMatchDataContainer] → 标题 + 分隔线 + [AcceptMatchModeIcon][AcceptMatchModeMap]  ← 保留
      [AcceptMatchMapImage]         ← 地图底图（150px）
      [id-map-draft-phase-teams] → …假阵容…          ← 隐藏
      [accept-match__slots-count] → [AcceptMatchSlots][AcceptMatchPlayersAccepted]  ← 隐藏
      [AcceptMatchBtn]
      [AcceptMatchCountdown]
    [Agreement]                     ← 已 collapse
```

## 9. 相关文档

- 仓库 `csgo-legacy-matchmaking`（GitHub，公开）：README 是结案记录，`tools/` 是可复用工具，
  `HANDOFF.md` 是本文件的副本（**注意：仓库里不含任何令牌/密码，全部占位符**）。
- 记忆文件：`csgo-legacy-gc-matchmaking.md`（结论摘要）、
  `csgo-legacy-private-server.md`、`virtualbox-linux-srcds.md`（环境搭建）。
