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

点按钮后的完整链路：

```
点「开始竞技」
  → GC 收到 MatchmakingStart(9103)，下发 9104/9107
  → csgc 在 RetrieveMessage 拿到 9107（内含 server_address）
  → 8 秒后把 "connect <ip>:<port>" 塞进引擎的命令缓冲区
  → 引擎主线程执行它 → 进服
```

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

## 未完成：接受弹窗

原版那个「您的比赛已准备完毕！」弹窗**没能做成**。已经确认的事实：

- 弹窗由 `party.js` 的 `PartyMenu.ShowMatchAcceptPopUp(map)` 创建，
  靠 `code.pbin`（明文 zip，可直接读改）
- 事件派发侧是死代码：`ServerReserved` 的唯一派发者（`client.dll+0x427FD0` 的唯一调用者
  `0x45613`）零引用
- 改用 JS 侧自己判断时机可行（轮询 `game.mmqueue`，收到 reservation 时会从
  `searching` 翻成 `reserved`），弹窗确实能弹出来
- 但**关不掉**：那个 `<PopupCustomLayout>` 缺 `PopupPanel` class，不在 PopupManager
  管辖内，`UIPopupButtonClicked` / `CloseAllVisiblePopups` 对它全都无效；
  而通过 JS 改它的面板状态会破坏 UI（先按键全失效，后崩溃）

要接着做，建议**直接改 `popup_accept_match.xml`**（把不要的节点删掉、加自动关闭），
而不是在运行时用 JS 去戳它。

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
```

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
