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
| Linux `srcds` 启动、客户端直连进服 | **已通**（客户端能稳定停在 `INGAME`） |
| 自建 GC 与客户端握手、走完匹配协议 | **已通** |
| 点「开始竞技」自动匹配进局 | **未完成**（当前卡点见下） |

**当前卡点**：客户端收到 GC 下发的 `9107`（`GC2ClientReserve`）后不发起连接。
`9107` 的 ClientJob 对象确实被创建了，但其处理体未被调度执行，
`ServerReserved` 事件从未派发，UI 的「接受比赛」弹窗因此不出现。

## 目录

```
docs/
  csgo-session-summary.md    较晚一次会话的完整技术总结（逐条解析 transcript）
  csgo-session-summary-2.md  更早一次会话的总结
  csgo-match-handoff.md      交接文档：环境拓扑、已修问题、踩过的坑、当前卡点
tools/
  appidfix.c              LD_PRELOAD 补丁：绕过引擎对归档 appid 的拒绝
  fix_stack.py            原地修改 PE 头（栈保留大小 / LARGE_ADDRESS_AWARE）
  vpk_get.py              从 pak01 VPK 中取出指定文件（只读）
  pbin_ls.py              读取 panorama code.pbin（明文 zip）里面的 JS
  run_cdb_attach.bat      cdb 附加到 Steam 启动的游戏（必须附加，不能直接启动）
  start-srcds.sh          虚拟机内启动 srcds 的脚本
  add_backtrace.py        给 hook 加上调用栈抓取
  rebuild_gc.py           重建 GC 侧 handler
  readd_validate.py       补回 Server2GCClientValidate
```

## 常用手法（详见 docs/）

- **cdb 必须「附加」而不能直接启动游戏**：直接用调试器拉起 `csgo.exe` 会让 Steam 认为
  不是它启动的，客户端进入 insecure 状态，匹配按钮被禁用。
- **放行 `OutputDebugString` 的异常码**：`sxd 40010006; sxd 4001000a`，否则日志被淹没。
- **别对附加中的 cdb 用 timeout 强杀**：被调试的游戏会跟着一起死。
- **改源文件注意编码**：C++ 侧是 GBK（MSVC 按 936 读），GC 的 JS 是 UTF-8，别混。

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
