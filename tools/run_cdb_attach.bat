@echo off
REM 附加到已由 Steam 启动的 csgo.exe。
REM sxd 80000003：忽略 break instruction（int 3）。
REM   之前每次都在 int 3 上停下、从没让它继续跑过 —— 而 first-chance 异常是
REM   可以被程序自己处理的，那条材质报错可能根本不是致命的。
REM   忽略之后，真正让进程死掉的异常才会暴露出来。
set CDB=C:\Program Files (x86)\Windows Kits\10\Debuggers\x86\cdb.exe

for /f "tokens=2 delims=," %%p in ('tasklist /fi "imagename eq csgo.exe" /fo csv /nh') do set PID=%%p
set PID=%PID:"=%

if "%PID%"=="" (
    echo 没找到 csgo.exe
    exit /b 1
)
echo 附加到 csgo.exe PID=%PID%

"%CDB%" -p %PID% -o -c ".logopen /u C:\Users\Administrator\cdb_out.txt; sxd 40010006; sxd 4001000a; sxd 80000003; g; r; u @eip L6; kb 120; .logclose; qd"
