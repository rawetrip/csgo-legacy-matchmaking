# 安装：把 CS:GO Legacy 的完整匹配流程跑起来

> 目标形态：
> ```
> 点「开始竞技」→ 自动就绪 → 自动连服 → 服务器加载 lobby_mapveto（选图大厅图）
>   → 大厅热身窗口 → BP 选/禁图（客户端 UI）→ 选初始队伍
>   → 服务器自己 changelevel 到选定的图 → 正常对局
> ```
> 2026-09-29 实测走通：BP 选中 `de_ancient`，服务器日志
> `Map veto pick controller: pick = de_ancient` → `initiating level transition` → `*** Map Load: de_ancient`，
> 随后正常分队、开局、打完整回合。

## ⚠️ 适用范围

| 维度 | 范围 |
|---|---|
| **服务端** | **仅限 Linux 端 srcds**。换图补丁按 `engine.so`（32 位 ELF）的硬编码偏移写 |
| **客户端版本** | **构建 1575**（`ClientVersion 1575` / `PatchVersion 1.38.8.1` / 2023-10-12）—— **最终版 legacy 客户端** |
| **模式** | ★ **只实现了「优先」（Prime）这一个队列。竞技、休闲等其他模式尚未实现** |
| **构建偏移** | 硬编码偏移基于**构建 1575**定位（CS:GO 已停止更新，该构建已冻结；换分支/地区版仍需重新定位） |

---

## 0. 你需要自己准备什么（本包不含）

本包**只有我们自己写的代码和配置**。以下这些因为版权原因不能打包，必须你自己搞到：

| 需要的东西 | 从哪来 | 说明 |
|---|---|---|
| CS:GO Legacy **专用服务器**（Linux） | SteamCMD `app_update 740` | srcds |
| CS:GO Legacy **客户端** | Steam（appid `4465480`） | |
| **GSLT** 游戏服务器登录令牌 | <https://steamcommunity.com/dev/managegameservers> | 一个令牌同时只能被一台服务器用 |
| `csgc.dll` + 改过的 `csgo.exe`(launcher) | 上游 [aka3257/csgc](https://github.com/aka3257/csgc) | 客户端注入框架，需自己编译 |
| `csgo_gc.so` + 它的 launcher | 移植自 csgo_gc-mm | **服务器侧的 GC 重定向**——没有它 srcds 连不上自建 GC（见 §4.1） |
| `csgo_appidfix.so` | 本仓库 `tools/appidfix.c`，自己编译 | 见 §2.2 |
| `csgo_srvfix.so` | 本仓库 `tools/srvfix.c`，自己编译 | 见 §2.3 |

> 换句话说：**这是一套配方，不是一个双击即用的 exe。** 最费事的是服务器侧那套
> `csgo_gc`（要编译、要替换 `srcds_linux`）。

---

## 1. 三块架构

```
┌─────────────┐        GC 协议(TCP)        ┌──────────────────┐
│ CS:GO 客户端 │ ─────────────────────────► │  自建 GC (node)   │
│  + csgc.dll  │ ◄───────────────────────── │  0.0.0.0:3257    │
└──────┬──────┘                            └────────┬─────────┘
       │ 直连 27015                                  │ csgo_gc 转发
       ▼                                             ▼
┌──────────────────────────────────────────────────────────┐
│ Linux srcds（VM 或裸机）                                   │
│  LD_PRELOAD: csgo_appidfix.so + csgo_srvfix.so            │
│  启动: -nowatchdog +game_type 0 +game_mode 1 +map lobby_mapveto │
└──────────────────────────────────────────────────────────┘
```

---

## 2. 游戏服务器（Linux srcds）

### 2.1 启动参数（**逐项都有原因，别删**）

完整版见 [`tools/start-srcds.sh`](tools/start-srcds.sh)，关键几项：

| 参数 | 为什么 |
|---|---|
| `+sv_lan 0` | 真实 Steam 身份。代价：会从 Valve 拿到非零 reservation cookie，需 srvfix 绕过 |
| `+game_type 0 +game_mode 1` | competitive。**必须显式指定**——默认 casual 时选图大厅图不在它的 mapgroupsMP 里，mapgroup 关联不上（`status` 里 mapgroup 为空），图内大厅逻辑不激活，表现为「能进服但只能热身、不能选边、过一会儿退回大厅」 |
| `+map lobby_mapveto` | **起点必须是选图大厅图**。注意：服务器加载哪张图**不由 GC 的 9106 `map` 字段决定**，就是这个 `+map` |
| `-nowatchdog` | 否则玩家连入、地图加载完后会 `Watchdog timer exceeded, aborting!`（退出码 134） |
| `-dev` | 关键行（如 `Rejecting connection request ...`）只有开发者模式才打印 |

### 2.2 `csgo_appidfix.so`（让 legacy 客户端票据过 appid 校验）

```bash
py vmscp.py tools/appidfix.c appidfix.c
py vmssh.py "gcc -m32 -shared -fPIC -O2 -o csgo_appidfix.so appidfix.c -ldl"
```

### 2.3 `csgo_srvfix.so`（五个补丁，见 `tools/srvfix.c` 头部注释）

```bash
py vmscp.py tools/srvfix.c srvfix.c
py vmssh.py "gcc -m32 -shared -fPIC -O2 -o csgo_srvfix.so srvfix.c -ldl"
```

五个补丁：cookie 放行 · 换图 detour（**默认关**，`SRVFIX_DETOUR=1` 才开）·
**桩页设可执行**（mmap 出来是 NX 的，跳进去必崩）· NOP 非主线程的 `Cbuf_Execute` · 抹掉无效模式名 `reserved`。

### 2.4 用 `script(1)` 包伪终端（否则日志是块缓冲，看不到实时输出）

见 `tools/start-srcds.sh` 里的 `exec script -q -f -c "..."`。

---

## 3. 自建 GC（node）

```bash
cp -r gc/* <你的 gc-replacement>/          # Server_v3.js + proto/ + config.example.json
cd <你的 gc-replacement>
cp config.example.json config.json        # 然后照着下面的说明改
node Server_v3.js                          # 监听 0.0.0.0:3257
```

`config.json` 要填的：

| 键 | 说明 |
|---|---|
| `matchServerIp` | srcds 所在机器的地址 |
| `matchServerPort` | 默认 27015 |
| `accountId` | **你的 accountId**（= SteamID64 − `76561197960265728`） |
| `gsSteamId` | 你的游戏服 SteamID（服务器日志里 `Gameserver logged on to Steam, assigned identity steamid:...` 会给） |

> ⚠️ `gc/Server_v3.js` 里的作者 SteamID / IP / 游戏服 SteamID **已替换成占位符**，
> 你不需要改它——真正的值都从 `config.json` 读。

---

## 4. 客户端

### 4.1 必须能连上自建 GC

客户端靠 `csgc.dll` 把 GC 流量转发到你的 GC（`forwarder.cpp` 里的地址是**硬编码**的，改了要重编译）。
服务器侧则靠 §0 里那个 `csgo_gc` —— **两条都要通**，否则服务器收不到预约、`Map veto pick controller` 不会跑。

### 4.2 客户端资源：`code.pbin`（接受弹窗 + prime 兜底）

```bash
# 游戏必须关着！启动时会把资源读进内存，开着改等于没改
py tools/pbin_tool.py put panorama/scripts/party.js client/party.js   # ← 用 csgo-legacy-premier 仓库里那份
# 回读校验（每次都要做）
py tools/pbin_tool.py get panorama/scripts/party.js readback.js
cmp readback.js client/party.js && echo OK
```

判据：`code.pbin` 总大小 **4708665**；`party.js` 是 **19898** 字节（原始版是 13497）。

> ⚠️ `party.js` 被**两个功能**占用：接受弹窗（触发/音效/关闭）和 prime 的 JS 兜底。
> 若哪个补丁要求"把 party.js 还原成原始版"，另一个功能会**静默失效**——踩过。

---

## 5. 验证顺序（每一步都能单独确认）

| 步骤 | 怎么验 |
|---|---|
| GC 起来了 | `netstat` 里 3257 在 LISTENING |
| 服务器连上了 GC | GC 日志出现 `[SERVER] GCServerHello from ...` |
| 服务器加载大厅图 | srcds 日志 `Host_NewGame on map lobby_mapveto` |
| 进了服 | srcds 日志 `Client "xxx" connected` |
| **BP 界面出现** | 客户端屏幕（这一步的关键在 GC 的 9107 `preMatchData.draft`，见 §6.1） |
| 换图 | srcds 日志 `Map veto pick controller: pick = <地图>` → `initiating level transition` |

---

## 6. 排障：几个反直觉的坑

### 6.1 BP 界面不出现 → 检查 GC 的 9107 里 `preMatchData.draft`

proto 里它是 `CDataGCCStrike15_v2_TournamentMatchDraft` **对象**，传 `[]`（空数组）
类型不符会被 protobufjs **静默丢弃**，客户端永远拿不到 draft，
`MatchDraftAPI.GetDraft()` 永不等于 `'ingame'` → 界面不出现。
（这个坑在服务器侧的 9105 里修过一次，客户端 9107 漏了。）

### 6.2 连接被静默拒绝 → reservation cookie

`sv_lan 0` 时服务器 cookie 非零、与客户端带的 `Hello :)` 不等 → 连接被静默拒。
`csgo_srvfix.so` 的第一个补丁绕的就是它。
诊断行：`-> Reservation cookie 293a206f6c6c6548: reason [R] Connect from ...`
（**注意**：日志里 `-> Reservation cookie 0: reason reserved(yes)...` 的那个 `0` 是**写死的常量**，
它恰恰是「服务器 cookie 非零」的证据——早期据此调 GC 的 cookie 方向完全反了。）

### 6.3 `Watchdog timer exceeded, aborting!`

退出码 134，发生在玩家连入、地图加载完之后。gdb 抓过现场：**主线程栈完全正常**
（在 `ThreadNanoSleep` 的帧循环里），不是死锁，是"在等一个不来的东西"。
直接 `-nowatchdog`。

### 6.4 别用 cvar dump 猜值

服务器日志里的 cvar dump 只在地图加载**之前**打印，而 cfg 是在那之后才 exec 的——
反复读到旧值，会误判"设置没生效"。**用 `tmux send-keys` 直接问服务器**（见 §7）。

---

## 7. 手边好用的两张牌

### 7.1 直接给 srcds 控制台打字（**能看回显**）

```bash
tmux send-keys -t srcds 'mp_force_pick_time' Enter      # 查询
tmux send-keys -t srcds 'mp_force_pick_time 3' Enter    # 修改
```

前提：srcds 跑在 tmux 里且 stdout 包在 `script(1)` 里。这比 `tools/srvcmd.sh` 的 TIOCSTI 强——
**TIOCSTI 看不到回显**，以前只能靠 dump 猜。

### 7.2 `gamemodes_server.txt`：按模式覆盖 cvar

CS:GO 原生机制，与 `gamemodes.txt` **合并**。语法：cvar 要写在 gameMode 的 **`convars` 块**里，
直接写在 mapgroup 下不生效（试过）。示例见 [`server-config/gamemodes_server.txt`](server-config/gamemodes_server.txt)。

---

## 8. 已知限制（**没做完的**）

- **进服时仍会弹「选阵营」菜单**（大厅图那次、以及换图后那次都是）。
  `mp_force_assign_teams 1` + `mp_force_pick_time 3` 已生效（菜单 3 秒后自动分配），
  但菜单**仍会短暂出现**。怀疑最终答案在 GC 的预约数据（队伍归属），不在服务器 cvar。
- **BP 仍需手动操作**（阶段推进由地图的 `mapvetopick_controller` 控制）。
- 匹配成功后「正在确认比赛」状态不消失。
- 所有 RVA（`srvfix.c` 里那些硬编码的偏移）基于**构建 1575**定位，**换版本要重新定位**。

---

## 9. 法务

仅用于**自建服务器 / 离线环境下的兼容性研究**。所有测试都在非 VAC secure 的自建服上完成。
请勿用于官方服务器或任何在线竞技环境。
