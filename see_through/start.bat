@echo off
setlocal

set "APP_NAME=see_through"
set "APP_HOME=%~dp0"
if "%APP_HOME:~-1%"=="\" set "APP_HOME=%APP_HOME:~0,-1%"

set "APP_PORT=9004"
set "WAIT_SECONDS=30"
set "VENV_DIR=%APP_HOME%\venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PID_FILE=%APP_HOME%\%APP_NAME%.pid"
set "LOG_DIR=%APP_HOME%\logs"
set "OUT_LOG=%LOG_DIR%\startup.out"
set "ERR_LOG=%LOG_DIR%\startup.err"

set "CMD=%~1"
if "%CMD%"=="" set "CMD=restart"

if /I "%CMD%"=="init" goto init
if /I "%CMD%"=="start" goto start
if /I "%CMD%"=="stop" goto stop
if /I "%CMD%"=="restart" goto restart
if /I "%CMD%"=="status" goto status
goto usage

:init
echo [%APP_NAME%] Initializing Python 3.11 venv...
if not exist "%PYTHON_EXE%" goto create_venv

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 goto install_deps

echo [%APP_NAME%] Recreating venv because it is not Python 3.11.
rmdir /s /q "%VENV_DIR%"

:create_venv
py -3.11 -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [ERROR] Python 3.11 is required. Install it or make sure "py -3.11" works.
    exit /b 1
)

:install_deps
call "%PYTHON_EXE%" -m pip install --upgrade pip
call "%PYTHON_EXE%" -m pip install -r "%APP_HOME%\requirements.txt"
echo [%APP_NAME%] Init done.
exit /b 0

:start
call :find_pid
if defined PID (
    echo [%APP_NAME%] Existing process found, restarting. PID=%PID%.
    call :stop
)

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Missing venv. Run: start.bat init
    exit /b 1
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
echo [%APP_NAME%] Starting on port %APP_PORT%...
start "" /min cmd /c "cd /d ""%APP_HOME%"" && .\venv\Scripts\python.exe run.py >> ""%OUT_LOG%"" 2>> ""%ERR_LOG%"""

for /l %%I in (1,1,%WAIT_SECONDS%) do (
    call :find_pid
    if defined PID goto started
    timeout /t 1 /nobreak >nul
)

echo [ERROR] Start failed. Check logs:
echo   %OUT_LOG%
echo   %ERR_LOG%
exit /b 1

:started
echo [%APP_NAME%] Started, PID=%PID%.
echo   http://127.0.0.1:%APP_PORT%/api/see-through/health
exit /b 0

:stop
call :find_pid
if not defined PID (
    echo [%APP_NAME%] Not running.
    exit /b 0
)

echo [%APP_NAME%] Stopping, PID=%PID%...
taskkill /PID %PID% >nul 2>&1
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "exit [int](-not (Get-Process -Id %PID% -ErrorAction SilentlyContinue))" >nul 2>&1
if not errorlevel 1 taskkill /F /PID %PID% >nul 2>&1
del "%PID_FILE%" >nul 2>&1
echo [%APP_NAME%] Stopped.
exit /b 0

:restart
call :stop
call :start
exit /b %errorlevel%

:status
call :find_pid
if not defined PID (
    echo [%APP_NAME%] Not running.
    exit /b 0
)

echo [%APP_NAME%] Running, PID=%PID%.
powershell -NoProfile -Command "Get-Process -Id %PID% | Select-Object Id,ProcessName,CPU,WorkingSet,StartTime | Format-Table -AutoSize"
exit /b 0

:find_pid
set "PID="
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    echo(%PID%| findstr /R "^[0-9][0-9]*$" >nul
    if not errorlevel 1 (
        powershell -NoProfile -Command "exit [int](-not (Get-Process -Id %PID% -ErrorAction SilentlyContinue))" >nul 2>&1
        if not errorlevel 1 exit /b 0
    )
    del "%PID_FILE%" >nul 2>&1
    set "PID="
)

for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:":%APP_PORT% .*LISTENING"') do (
    set "PID=%%I"
    >"%PID_FILE%" echo %%I
    exit /b 0
)
exit /b 1

:usage
echo Usage: %~nx0 ^<init^|start^|stop^|restart^|status^>
exit /b 1
