# CS:GO Legacy 自建 GC / 匹配逆向笔记

把 **CS:GO Legacy**（归档 appid `4465480`）的「开始竞技」真正送进一局所做的事后记录。

这不是一个能开箱跑起来的成品，而是一份**结案记录 + 可复用工具**：记录了做到哪一步、
哪些路走通了、哪些是被证据推翻的弯路，以及途中造出来的一批小工具。

## 背景

CS:GO Legacy 的官方 GC 早已下线，因此「竞技」按钮点了不会有任何反应。本项目通过：

- **客户端侧**：向 `csgo.exe` 注入 `csgc.dll`（funchook 拦 Steam API），并在 launcher 上打补丁
- **服务端侧**：外部 JS 编写的自建 GC（监听 `127.0.0.1:3257`）+ TCP forwarder
- **游戏服务器**：Linux `srcds`（虚拟机内运行，`LD_PRELOAD` 打 appid 补丁）

搭出一条能用的链路。

## 目前状态

| 环节 | 状态 |
|---|---|
| Linux `srcds` 启动、客户端直连进服 | **已通** |
| 自建 GC 与客户端握手、走完匹配协议 | **已通** |
| **点「开始竞技」自动进局** | **已通** |
| 同一游戏进程内反复匹配进服 | **已通** |
| 「比赛已准备完毕」弹窗（CS2 样式 + 音效 + 时序） | **已通** |

点按钮后的完整链路：

```
点「开始竞技」
  → GC 收到 MatchmakingStart，下发 9104/9107
  → csgc 在 RetrieveMessage 拿到 9107（内含 server_address）
  → party.js 轮询到 mmqueue=reserved，派发官方事件 ServerReserved（地图名前面加 '@'）
  → 官方弹窗以「公告式/休闲」形态出现，1.9 秒后自己自动就绪并关闭
  → 2.6 秒时 csgc 把 "connect <ip>:<port>" 塞进引擎命令缓冲区（执行标记传 2）
  → 引擎主线程执行它 → 进服
```

## 真正卡住的地方：服务器的 reservation cookie

服务端 `engine.so`（32 位，`Addr == Off`）在 `0x1d0776` 起的判定：

```asm
mov 0x2ec(%esi),%eax        ; 服务器自己的 reservation cookie
xor  ...                    ; 与客户端 connect 包里带的 cookie 比对
je  1d2790                  ; 相等 → 放行
or  %ebx,%ecx
je  1d2790                  ; ★ 服务器 cookie == 0 → 也放行
                            ; 否则 → 踢（#Valve_Reject_Reserved_For_Lobby）
```

`sv_lan 0` 的 srcds 会从 Valve 侧拿到一个**非零**的 reservation cookie，而客户端带的是
GC 下发的 `Hello :)`（`0x293A206F6C6C6548`），两者不等 → 连接被静默拒绝。

**解法：srcds 用 `sv_lan 1` 跑** —— 不登录 Steam 就拿不到那个 cookie，保持 0 → 走放行分支。

> 日志里 `-> Reservation cookie 0:  reason reserved(yes), clients(no), reservationexpires(0.00)`
> 那个 **`0` 是写死的常量**，而且**这行只在「服务器 cookie != 0」时才打印** ——
> 它恰恰是 cookie 非零的证据。早期据此去改 GC 的 `GC_COOKIE`，方向完全反了。

### 另一个坑：连上就被踢（无限重连）

`sv_lan 0` 下，连接处理里有一整块「服务器已预留 → 直接开局」逻辑，会执行
`nextlevel <map>` + `map <map> reserved` + `Cbuf_Execute` → **每次连接都重载关卡**把客户端
踢下线，客户端自动重连 → 又重载 → 死循环。`sv_lan 1` 下不触发；要回到 `sv_lan 0`
则需要 `tools/srvfix.c`（LD_PRELOAD 运行时 NOP 掉那条 map 命令）。

## 让连接真正发生的那一步

**核心是 `Cbuf_AddText(engine.dll+0x1DB910)`，并且执行标记必须传 `2`。**

引擎的命令执行路径上有一道 `FCVAR_CLIENTCMD_CAN_EXECUTE` 检查，它只放行「玩家亲手敲的」
命令。判断依据是一个来源标记：

| 进入路径 | 标记值 | 结果 |
|---|---|---|
| 玩家控制台 → 直接执行 | `2` | 放行 |
| `IVEngineClient::ClientCmd` → Cbuf | `0/1`（被 `setne` 布尔化） | **被拒** |
| **直接驱动 `Cbuf_AddText`，标记传 2** | `2` | **放行** |

`ClientCmd` 不能用的原因是它把标记压成了布尔值（反汇编里那句 `setne cl`）。
绕开它、用一小段汇编桩直接调 `Cbuf_AddText`（`ecx`=缓冲索引、`edx`=字符串、栈上传标记，
调用者清栈）就能带上正确的值。

这样做还有个额外好处：命令由**引擎主线程**执行，和玩家手敲完全同路，天然安全。

## 明确不能做的两件事（都实测崩过）

| 做法 | 后果 |
|---|---|
| 在 csgc 自己的线程里调用 `connect` 命令体（`engine.dll+0xDA6A0`） | 那函数会碰 UI，V8 直接 `Fatal: HandleScope::CreateHandle0`；即便被 `__try` 兜住也会留下破坏，随后加载地图时崩 |
| hook Panorama 的事件派发函数（`panorama.dll+0x417F0`） | 打乱事件泵（一帧积压几千个待派发事件），最后 `eip` 跳到未映射地址崩溃 |

## 崩溃源：大厅回调

崩溃栈指向 `SteamAPI_RunCallbacks` 内部，`eip` 在任何模块之外。根因是 csgc 早期
「骗引擎进大厅」路线的遗留代码：

- `RequestLobbyOnce()` 主动 `CreateLobby`，其 `LobbyCreated` 回调在
  `SteamAPI_RunCallbacks` 里炸掉
- `InstallMatchmakingVtableHooks()` 把 `ISteamMatchmaking` 的 vtable 转发给
  steamclient，参数对不上（那些钩子槽位是从 SDK 头文件推的，没验证过真实 vtable）

两者都已停用（`return` 掉）。那条路线本身也早已证明无效 —— 引擎从不调用
`ISteamMatchmaking`，连接现在走 `Cbuf`。

## 接受弹窗（已完成）

> 早期结论「这个弹窗关不掉」是**错的**，在此更正：`<PopupCustomLayout>` 虽然缺
> `PopupPanel` class，但 `$.DispatchEvent("PanoramaComponent_Lobby_ReadyUpForMatch", false, 0, 0)`
> 能正常关掉它。当时真正的坑是在**运行时用 JS 去戳它的子面板**，把 UI 状态搞坏了
> （先按键全失效，后崩溃）。

最终做法（`code.pbin` 里的资源全是明文 zip，可直接改）：

- **显示**：`party.js` 轮询 `LobbyAPI.GetSessionSettings().game.mmqueue`，翻到 `reserved` 时
  派发官方事件 `ServerReserved`，**地图名前面加一个 `@`** —— 这是官方「公告式自动就绪」
  模式的开关（`popup_accept_match.js` 里的 `map.charAt(0) === '@'`）。好处一次拿三个：
  - 弹窗直接就是 CS2 那种「只有标题 + 模式·地图」的形态（官方 `auto` 样式）
  - `m_hasPressedAccept` 被置真 → 倒计时用安静的 `waitquiet`（**这就是休闲模式没有 beep 的原因**）
  - 1.9 秒后官方 `_OnNqmmAutoReadyUp` 自动跑：播 `mm_success_lets_roll`、
    `LobbyAPI.SetLocalPlayerReady('deferred')`、用官方路径关弹窗
- **音效**：官方是引擎在抛 `ServerReserved` 时播「比赛就绪」音；我们既然自己抛事件，
  就得自己补播 `popup_accept_match_found`（`game_ready_02.wav`）
- **精简面板**：给 `id-map-draft-phase-teams`（假阵容）和 `accept-match__slots-count`
  （0/10 计数行）加内联 `visibility:collapse`。**只能隐藏、不能删节点** —— 弹窗 JS 会对着
  这些 id 做 `RemoveAndDeleteChildren()` / `SetDialogVariableInt()` / `RemoveClass()`，
  节点缺失直接抛异常把 UI 搞坏（`tools/patch_popup.py`）
- **尺寸**：`.accept-match__map` 高度 300px → 200px（300 是竞技版给阵容区留的，
  公告式模式用不上；`tools/patch_popup_css.py`）

> 顺带记录一个官方 bug：`mm_success_lets_roll.wav` 在 CS2/CS:GO 官方客户端里**会放两遍**
> （`_OnNqmmAutoReadyUp` 与另一条路径各播一次）。我们的实现只播一遍 —— 想复现官方行为
> 就在 `party.js` 的 `_closePopup()` 里再补一次 `popup_accept_match_confirmed`。

## 目录

```
tools/
  appidfix.c              LD_PRELOAD 补丁：绕过引擎对归档 appid 的拒绝
  fix_stack.py            原地修改 PE 头（栈保留大小 / LARGE_ADDRESS_AWARE）
  run_cdb_attach.bat      cdb 附加到 Steam 启动的游戏（必须附加，不能直接启动）
  start-srcds.sh          虚拟机内启动 srcds 的脚本
  add_backtrace.py        给 hook 加上调用栈抓取
  rebuild_gc.py           重建 GC 侧 handler
  readd_validate.py       补回 Server2GCClientValidate

  # 静态分析（32 位 PE，按 RVA 定位，不受 ASLR 影响）
  disasm.py               用 capstone 反汇编指定 RVA 区间，标注跳转目标
  xref.py                 交叉引用：dword 指针（虚表/IAT）+ 全 .text 的 rel32 call/jmp
  rdstr.py                dump 指定 RVA 的字符串 / 搜索字符串并给出 RVA
  pbin_tool.py            code.pbin 读写（ls / get / put，保留 16 字节头与 zip 注释）

  # VPK
  vpk_get.py              从 pak01 VPK 中取出指定文件（只读）
  vpk_extract.py          按过滤条件批量解包 VPK（默认 sound/，2.4 万条目约 3.8 GB）
  pbin_ls.py              读取 panorama code.pbin（明文 zip）里面的 JS

  # 服务端运行时补丁（LD_PRELOAD 进 srcds，改 engine.so）
  srvfix.c                仅在 sv_lan 0 时需要：NOP 掉「预留开局」里的 map 命令
  srvre.py                ELF32 节表/字符串定位（server 侧 engine.so 是 32 位 ELF，
                          注意 Addr == Off，所以文件偏移即 vaddr）

  # 客户端资源/源码补丁生成器（改完必须 pbin_tool.py put 回读校验）
  make_party.py           生成 party.js：触发、关闭、音效、时序都在这
  patch_popup.py          精简 popup_accept_match.xml（隐藏假阵容/计数行，保留全部 id）
  patch_popup_css.py      压缩弹窗高度（.accept-match__map 300px -> 150px）
  patch_rearm.py          改 csgc 源码：收到 9101 时清零一次性连接标记
  patch_delay.py          改 csgc 源码：连接延时 8s -> 5s -> 2.6s
```

> 改 `csgc-src` 下的 C++ **必须用 bytes 级替换**（文件是 GBK，MSVC 按 936 读），
> 别用会解码/重编码的编辑器；编完把 `dist/csgc/csgc.dll` 拷到 `<游戏目录>/csgc/csgc.dll`。

> 这些脚本里的游戏路径是硬编码的，换机器时改开头的 `PATH` / `GAME` 常量即可。

## 常用手法

- **cdb 必须「附加」而不能直接启动游戏**：直接用调试器拉起 `csgo.exe` 会让 Steam 认为
  不是它启动的，客户端进入 insecure 状态，匹配按钮被禁用。
- **放行 `OutputDebugString` 的异常码**：`sxd 40010006; sxd 4001000a`，否则日志被淹没。
- **别对附加中的 cdb 用 timeout 强杀**：被调试的游戏会跟着一起死。
- **改源文件注意编码**：C++ 侧是 GBK（MSVC 按 936 读），GC 的 JS 是 UTF-8，别混。
- **改 `code.pbin` 要保留结构**：16 字节 `PAN\x02` 头 + 标准 zip（726 条目全 `compress=0`
  stored）+ 尾部 zip 注释。改完务必回读验证、并确认 XML/JS 能解析 —— 少一个 `>` 就会
  让整个资源解析失败。
- **找 Panorama 音效名**：音效事件定义在 VPK 里的 `scripts/game_sounds_ui_panorama.txt`，
  `PlaySoundEffect` 用的是事件名（带 `UIPanorama.` 前缀），不是文件名。例如
  `UIPanorama.popup_accept_match_found` → `UI/panorama/game_ready_02.wav`。

## 相关项目

本项目的多个环节参考或使用了以下上游 / 同类项目：

- **[mikkokko/csgo_gc](https://github.com/mikkokko/csgo_gc)** —— 同样是为 CS:GO legacy 写的自建 GC，
  用 funchook 拦 Steam API 并替换 launcher。**它是 `9164` 等消息的权威参照**
  （本项目统一使用的 reservation cookie `0x293A206F6C6C6548` 即出自它的
  `gc_const_csgo.h:6 GameServerCookieId`，该值与 `"Hello :)"` 的字面量一致）。
  需注意：**它没有实现匹配** —— `gc_shared.cpp` 里 9101/9103/9107 只有名字表、没有处理函数，
  所以匹配这一层没有现成参照，只能自己逆。
- **[aka3257/CSGO-GC-Replacement](https://github.com/aka3257/CSGO-GC-Replacement)** 与
  **[aka3257/csgc](https://github.com/aka3257/csgc)** —— 本项目所用的外部 JS GC 与
  客户端注入框架（`csgc.dll`）的出处。
- **[eonexdev/csgo-sv-fix-engine](https://github.com/eonexdev/csgo-sv-fix-engine)** ——
  归档 appid 被引擎拒绝这一问题的参考实现（有预编译 `.so`）；我们最终选择自己实现了
  `tools/appidfix.c`。

## Contributors

**DeepSeek** —— 逆向分析与调试（cdb 断点、反汇编、GC 侧补丁）

## 说明

仅用于**自建服务器 / 离线环境下的兼容性研究**。所有测试都在非 VAC secure 的自建
服务器上进行。请勿用于官方服务器。
