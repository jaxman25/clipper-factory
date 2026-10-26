@echo off
setlocal enabledelayedexpansion
rem ---------------------------------------------------------------------------
rem kill-port.bat - force-kill whatever is stuck on a TCP port.
rem
rem Stuck Next.js dev servers keep the port bound after the terminal is closed,
rem so the next "npm run dev" fails with EADDRINUSE. Double-click this file
rem (or run it from a shell) to clean the port up again.
rem
rem   kill-port.bat              kill whatever holds port 3000 (default)
rem   kill-port.bat 8080         kill whatever holds port 8080
rem   kill-port.bat 8080 --no-pause   ...and skip the "Press any key" prompt
rem
rem "npm run dev" does its own cleanup with the kill-port package, so it never
rem reaches this file - this script is the manual fallback.
rem ---------------------------------------------------------------------------

set "PORT=3000"
set "NOPAUSE="

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--no-pause" (
    set "NOPAUSE=1"
) else if /i "%~1"=="--help" (
    goto :usage
) else if /i "%~1"=="-h" (
    goto :usage
) else if "%~1"=="/?" (
    goto :usage
) else (
    set "PORT=%~1"
)
shift
goto :parse_args

:args_done
echo(%PORT%| findstr /R /C:"^[0-9][0-9]*$" >nul
if errorlevel 1 goto :usage

set "SEEN= "
set "KILLED="
set "FAILED="

echo Looking for a process listening on port %PORT%...

rem netstat columns are Proto Local Foreign State PID, so token 5 is the PID.
rem The same PID is listed twice (IPv4 + IPv6 bind), hence the SEEN list.
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /C:"LISTENING" ^| findstr /C:":%PORT% "') do (
    if "!SEEN: %%P =!"=="!SEEN!" (
        set "SEEN=!SEEN!%%P "
        echo   killing PID %%P
        taskkill /F /PID %%P >nul 2>&1
        if errorlevel 1 (
            echo   FAILED to kill PID %%P - try running this script as administrator
            set "FAILED=1"
        ) else (
            set "KILLED=1"
        )
    )
)

if not defined KILLED (
    if defined FAILED goto :kill_failed
    echo Port %PORT% is already free.
    exit /b 0
)

rem Give the socket a moment to be released, then confirm (ping = 1s wait).
rem findstr exits 1 when it finds nothing, i.e. no listener = port is free.
ping -n 2 127.0.0.1 >nul
netstat -ano | findstr /C:"LISTENING" | findstr /C:":%PORT% " >nul
if not errorlevel 1 goto :port_still_bound

echo Done. Port %PORT% is free.
if defined NOPAUSE exit /b 0
pause
exit /b 0

:port_still_bound
echo WARNING: port %PORT% is still bound after killing it. 1>&2
>>"%~dp0kill-port.log" echo [%date% %time%] WARNING: port %PORT% still bound after kill - retry as administrator
if defined NOPAUSE exit /b 1
pause
exit /b 1

:kill_failed
echo WARNING: could not free port %PORT%. 1>&2
>>"%~dp0kill-port.log" echo [%date% %time%] WARNING: could not free port %PORT% - taskkill was denied
if defined NOPAUSE exit /b 1
pause
exit /b 1

:usage
echo Usage: kill-port.bat [port] [--no-pause]
echo.
echo Force-kills any process listening on the given port (default 3000).
echo Handy when a stopped Next.js dev server still holds the port and
echo "npm run dev" fails with EADDRINUSE.
exit /b 0
