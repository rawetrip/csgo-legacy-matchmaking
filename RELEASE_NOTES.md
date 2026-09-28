# v3 —— 完整匹配流程打通（含选/禁图）

2026-09-29

## 适用范围（重要）

| 维度 | 范围 |
|---|---|
| **服务端** | **仅限 Linux 端 srcds**。换图补丁（`tools/srvfix.c`）按 `engine.so`（32 位 ELF）的硬编码偏移写，Windows 端不适用 |
| **客户端版本** | **狂牙大行动（Operation Broken Fang）那一版构建** |
| **模式** | ★ **只实现了「优先」（Prime）这一个队列。竞技、休闲等其他模式尚未实现** |
| 构建偏移 | 基于 2026-09-26 的构建（CS:GO 已停止更新，该构建是冻结的；换分支/地区版仍需重新定位） |

## 这一版做到了什么

自建 GC 环境下，CS:GO Legacy 的**完整匹配流程**首次跑通：

```
点「开始竞技」→ 自动就绪 → 自动连服 → 服务器加载 lobby_mapveto（选图大厅图）
  → 大厅热身窗口 → BP 选/禁图（客户端 UI，可正常操作）→ 选初始队伍
  → 服务器自己 changelevel 到选定的图 → 正常对局
```

实测：BP 选中 `de_ancient`，服务器日志
`Map veto pick controller: pick = de_ancient` → `initiating level transition to de_ancient`
→ `*** Map Load: de_ancient`，随后正常分队、开局、打完整回合。

**选图（veto）这一环此前没有任何公开实现。** 上游 `mikkokko/csgo_gc` 明确没实现匹配，
`aka3257/CSGO-GC-Replacement` 也只有框架。

## 四个反直觉的关键点

1. **选图大厅图由 `+map` 启动参数决定**，不是 GC 下发的地图字段（试过，无效）。
   服务器起点必须是 `lobby_mapveto`——`gamemodes.txt` 里那张
   `"competitivemod" "lobby"` 的图组才激活图内大厅逻辑。
2. **必须显式 `+game_type 0 +game_mode 1`**（competitive）。默认 casual 时那张图
   不在它的 mapgroupsMP 里，mapgroup 关联不上，大厅逻辑不激活。
3. **局内选/禁图是客户端侧特性**（`MatchDraftAPI` 在 `client.dll`，
   服务器模块里搜不到任何 draft 字符串），数据由 GC 的 **9107** 喂给客户端；
   而 **9107 里的 `preMatchData.draft` 写成空数组会被 protobufjs 静默丢弃**，
   客户端因此永远拿不到 draft → 界面永不出现。改成正确对象形态后界面立刻出现。
   （同一个坑在服务器侧的 9105 里修过一次，客户端 9107 漏了。）
4. **换图是服务器侧的**——大厅图里的 `Map veto pick controller` 实体自己 changelevel，
   **不需要 GC 参与**，也不需要 `server_map.txt`/`veto_map.txt` 那套外部通道
   （它降级为手动兜底）。

## 新增/变更

- **`INSTALL.md`**（新）—— 逐步安装、验证顺序、排障、已知限制。
  写清了那些"逐项都有原因、别删"的东西。
- **`gc/`**（新）—— `Server_v3.js` + `proto/*.proto` + `config.example.json`。
  **已脱敏**：作者 SteamID64 / accountId / 主机 IP / 游戏服 SteamID 全为占位符。
- **`server-config/`**（新）—— `gamemode_competitive_server.cfg`（热身 10 秒、选边自动分配）
  与 `gamemodes_server.txt`（CS:GO 原生按模式覆盖 cvar）。
- **`tools/srvfix.c`** —— 五个补丁：cookie 放行 · 换图 detour（默认关）·
  **桩页设可执行**（mmap 出来是 NX 的，跳进去必崩）· NOP 非主线程的 `Cbuf_Execute` ·
  抹掉无效模式名 `reserved`。
- **`tools/start-srcds.sh`** —— 最终启动配方，逐项注释。
- **`tools/gc-local-changes.patch`** —— GC 侧改动留档（上游仓库不是我们的，推不上去）。
- 删除过时的 `HANDOFF.md`（旧快照，与 README 矛盾）。

## 已知限制

- 进服时仍会弹「选阵营」菜单（`mp_force_assign_teams 1` + `mp_force_pick_time 3`
  已生效，3 秒后自动分配，但菜单仍会短暂出现）。
- BP 仍需手动操作。
- 匹配成功后「正在确认比赛」状态不消失。
- 所有硬编码 RVA 基于 2026-09-26 的构建，换版本要重新定位。

## 包里不含

客户端 / srcds / `csgc.dll` / `csgo_gc.so` 等 Valve 派生的二进制。
`INSTALL.md` §0 列了使用者需要自备的清单与获取途径。

---

仅用于**自建服务器 / 离线环境下的兼容性研究**，非 VAC secure。
