#!/bin/bash
# Launch the Linux CS:GO srcds inside a pty (script(1)) so the log is readable live.
#
# ★ 两处要换成你自己的值（**不要把真实值提交进仓库**，这是公开仓库）：
#     +sv_setsteamaccount <你的 GSLT>     Steam 游戏服务器登录令牌
#     +rcon_password      <你的密码>      rcon 实际没跑起来（TCP 27015 不监听），留着备用
#
# ── 这套参数是 2026-09-29 打通完整匹配流程（含选/禁图）时的最终配方 ──────────
#
# +sv_lan 0
#   服务器按真实 Steam 身份上线（需要 GSLT）。代价：会从 Valve 拿到一个**非零**
#   reservation cookie，与客户端带的 "Hello :)" 不等 → 连接被静默拒绝。
#   这就是 csgo_srvfix.so 那个 cookie 补丁要绕过的东西。
#   （历史解法是 sv_lan 1 —— 但那会让服务器的预留状态不成立，veto 那条链走不了。）
#
# +game_type 0 +game_mode 1
#   competitive。**必须显式指定**：默认是 casual，而选图大厅图在 gamemodes.txt 里
#   只挂在 competitive 的 mapgroupsMP 下 —— casual 时 mapgroup 关联不上
#   （status 里 `mapgroup` 为空），图内的大厅逻辑（competitivemod = lobby）不激活，
#   表现为「能进服但只能热身、不能选边、过一会儿退回大厅」。
#
# +map lobby_mapveto
#   **起点必须是这张「选图大厅图」**，不是正式比赛图。
#   gamemodes.txt 里 mg_lobby_mapveto 的定义（mapgroupsMP 排 0 号，
#   注释写着 "team lobby map veto"）里有 `"competitivemod" "lobby"` —— 激活图内大厅逻辑。
#   BP 结束后由服务器里的 `Map veto pick controller` 实体自己 changelevel 到选中的图，
#   所以一台服务器能服务任意地图，**不需要一图一服务器**。
#
#   ⚠️ 注意：服务器加载哪张图**不由 GC 的 9106 `map` 字段决定**（试过，无效），
#      就是这里的 +map。
#
# -nowatchdog
#   关掉看门狗。不关的话，玩家连入、地图加载完之后会
#       **** WARNING: Watchdog timer exceeded, aborting!      (退出码 134)
#   gdb 抓过现场：主线程栈完全正常（在 ThreadNanoSleep 的帧循环里），不是死锁，
#   是"在等一个不来的东西"然后被定时器 abort。libtier0.so 里有 -nowatchdog /
#   -nonabortingwatchdog 两个开关。
#
# -dev / developer 1
#   打开 DevMsg。`Rejecting connection request ...` 这类关键行只有开发者模式才打印；
#   代价是地图加载会刷上万行 DISP_VPHYSICS。
#
# LD_PRELOAD 里两个补丁：
#   csgo_appidfix.so  改 appid 校验跳转表，让 legacy 客户端票据能过
#   csgo_srvfix.so    reservation cookie 放行 + 换图相关（见 srvfix.c 头部注释）
cd /home/csgo/csgo-server
exec script -q -f -c "env LD_PRELOAD=/home/csgo/csgo_appidfix.so:/home/csgo/csgo_srvfix.so ./srcds_run -game csgo -console -dev -norestart -nowatchdog -ip 0.0.0.0 -port 27015 +sv_setsteamaccount YOUR_GSLT_HERE +sv_lan 0 +sv_hibernate_when_empty 0 +sv_pure 0 +rcon_password YOUR_RCON_PASSWORD +game_type 0 +game_mode 1 +map lobby_mapveto" /home/csgo/srcds-run.log < /dev/null
