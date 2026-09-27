#!/bin/bash
# 用 script(1) 给 srcds 挂伪终端，让引擎 stdio 变行缓冲，日志实时可读
#（直接重定向到文件是全缓冲，尾部会截断在半个行上，关键信息看不到）。
#
# sv_lan 0：恢复服务器的 Steam 身份。
#   之前用 sv_lan 1 是为了绕开 reservation cookie 检查（#Valve_Reject_Connect_From_Lobby），
#   但代价是服务器在连接确认包里报的 SteamID 是 0
#   （抓包看到 `B.00000000.0000.0000.0000.0000.`），
#   而 9-26 那台能用的 Windows 服务器报的是正常的 `lobby id 0`。
#   认证票据问题（appid 4465480）已由 LD_PRELOAD 的 csgo_appidfix.so 补掉，
#   所以现在试试不靠 sv_lan 绕，让服务器以正式身份连接。
cd /home/csgo/csgo-server
exec script -q -f -c "env LD_PRELOAD=/home/csgo/csgo_appidfix.so ./srcds_run -game csgo -console -norestart -ip 0.0.0.0 -port 27015 +sv_setsteamaccount 47242565C3CFF2EB06C757EA3F31697B +sv_lan 0 +sv_hibernate_when_empty 0 +sv_pure 0 +map de_cache" /home/csgo/srcds-run.log < /dev/null
