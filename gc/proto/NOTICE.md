# `gc/proto/` —— 归属与许可（NOTICE）

本目录下的 6 个 `.proto` 文件是 **Valve Corporation 的协议定义**：

```
base_gcmessages.proto      cstrike15_gcmessages.proto   econ_gcmessages.proto
engine_gcmessages.proto    gcsdk_gcmessages.proto       gcsystemmsgs.proto
```

它们是 CS:GO / Steam 的 Game Coordinator 消息定义，本项目为了**互操作性**（让自建的 GC
能与客户端、游戏服务器通信）而收录。**版权归 Valve Corporation 所有，本项目作者不对其
主张任何权利。**

## 两点声明

1. **它们不在本仓库的 GPL-3.0 覆盖范围内。** 根目录的 [`LICENSE`](../../LICENSE)
   （GPL-3.0）只覆盖本仓库作者自己编写的部分。把 Valve 的文件以 GPL 授权出去，是
   作者无权做的事，此处明确排除。
2. **不要把它们当作"可自由再分发"的内容。** 如果你要 fork 或再分发本仓库，请自行评估
   这 6 个文件在你所在司法辖区内的地位。最稳妥的做法是：从你自己的游戏安装中取得，
   或只保留你实际用到的那部分消息定义。

## 用途限制

本项目仅用于**自建服务器 / 离线环境下的兼容性研究**。所有测试都在非 VAC secure 的自建服
上完成，请勿用于官方服务器或任何在线竞技环境。

---

# `gc/proto/` — Attribution and licence (NOTICE)

The six `.proto` files in this directory are **Valve Corporation's protocol definitions**
(CS:GO / Steam Game Coordinator messages). They are included here solely for
**interoperability** — so that this project's self-hosted GC can talk to the client and the
game server. **Copyright remains with Valve Corporation; the authors of this project claim
no rights over them.**

1. **They are NOT covered by this repository's GPL-3.0 licence.** The root
   [`LICENSE`](../../LICENSE) covers only the parts written by this project's authors.
   Licensing Valve's files under the GPL is not something the authors are entitled to do,
   and is explicitly excluded here.
2. **Do not treat them as freely redistributable.** If you fork or redistribute this
   repository, assess these six files under your own jurisdiction. The safest route is to
   take them from your own game installation, or to keep only the message definitions you
   actually use.

This project is intended solely for **compatibility research on self-hosted servers /
offline environments**. All testing was done on non-VAC-secure self-hosted servers. Do not
use it on official servers or in any online competitive environment.
