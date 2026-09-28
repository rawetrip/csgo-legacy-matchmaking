#!/bin/bash
# Launch the Linux CS:GO srcds inside a pty (script(1)) so the log is readable live.
#
# ★ 两处要换成你自己的值（**不要把真实值提交进仓库**，这是公开仓库）：
#     +sv_setsteamaccount <你的 GSLT>     Steam 游戏服务器登录令牌
#     +rcon_password      <你的密码>      本文里 rcon 实际没跑起来（TCP 27015 不监听），
#                                          留着只是为了万一要用
#
# 为什么是 sv_lan 1 —— 见 README「真正卡住的地方：服务器的 reservation cookie」：
#   sv_lan 0 时 srcds 会从 Valve 侧拿到一个非零 reservation cookie，而客户端带的是
#   GC 下发的 "Hello :)"，两者不等 → 连接被静默拒绝。sv_lan 1 不登录 Steam，
#   cookie 保持 0 → 命中放行分支。
#
# -dev / developer 1：打开 DevMsg。`Rejecting connection request ...` 这类关键行
#   只有开发者模式才打印；代价是地图加载会刷上万行 DISP_VPHYSICS。
#
# LD_PRELOAD 里两个补丁：
#   csgo_appidfix.so  改 appid 校验跳转表，让 legacy 客户端票据能过
#   csgo_srvfix.so    仅在回到 sv_lan 0 时才需要：NOP 掉「预留开局」里的
#                     `map <map> reserved`，否则每次连接都会重载关卡把客户端踢掉
cd /home/csgo/csgo-server
exec script -q -f -c "env LD_PRELOAD=/home/csgo/csgo_appidfix.so:/home/csgo/csgo_srvfix.so ./srcds_run -game csgo -console -dev -norestart -ip 0.0.0.0 -port 27015 +sv_setsteamaccount YOUR_GSLT_HERE +sv_lan 1 +sv_hibernate_when_empty 0 +sv_pure 0 +rcon_password YOUR_RCON_PASSWORD +map de_cache" /home/csgo/srcds-run.log < /dev/null
