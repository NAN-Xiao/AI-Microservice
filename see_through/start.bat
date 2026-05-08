@echo off
setlocal

set "APP_NAME=see_through"
set "APP_HOME=%~dp0"
if "%APP_HOME:~-1%"=="\" set "APP_HOME=%APP_HOME:~0,-1%"
set "PID_FILE=%APP_HOME%\%APP_NAME%.pid"
set "LOG_DIR=%APP_HOME%\logs"
set "STARTUP_LOG=%LOG_DIR%\startup.out"
set "STARTUP_ERR_LOG=%LOG_DIR%\startup.err"
set "SCRIPT_LOG=%LOG_DIR%\start.bat.log"
set "VENV_DIR=%APP_HOME%\venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "APP_PORT=9004"

if /I "%~1"=="init" goto init
if /I "%~1"=="start" goto start
if /I "%~1"=="stop" goto stop
if /I "%~1"=="restart" goto restart
if /I "%~1"=="status" goto status
if "%~1"=="" goto restart
goto usage

:init
echo [%APP_NAME%] Initializing virtual environment...
if not exist "%VENV_DIR%" py -m venv "%VENV_DIR%"
if not exist "%PYTHON_EXE%" python -m venv "%VENV_DIR%"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Failed to create venv. Please ensure Python is installed and available in PATH.
    exit /b 1
)
call "%PYTHON_EXE%" -m pip install --upgrade pip
call "%PYTHON_EXE%" -m pip install -r "%APP_HOME%\requirements.txt"
echo [%APP_NAME%] Initialization complete.
exit /b 0

:log
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
>> "%SCRIPT_LOG%" echo [%date% %time%] %*
exit /b 0

:checkvenv
if exist "%PYTHON_EXE%" exit /b 0
call :log CHECK_VENV failed. Missing %PYTHON_EXE%
echo [ERROR] Virtual environment not found: %VENV_DIR%
echo [TIP] Run: start.bat init
exit /b 1

:resolvepid
set "FOUND_PID="
if exist "%PID_FILE%" (
    set /p FOUND_PID=<"%PID_FILE%"
    tasklist /FI "PID eq %FOUND_PID%" | findstr /R /C:" %FOUND_PID% " >nul 2>&1
    if not errorlevel 1 (
        call :log RESOLVEPID hit pid file. PID=%FOUND_PID%
        exit /b 0
    )
    call :log RESOLVEPID stale pid file removed. PID=%FOUND_PID%
    del "%PID_FILE%" >nul 2>&1
    set "FOUND_PID="
)
for /f "tokens=5" %%I in ('netstat -ano ^| findstr ":%APP_PORT% " ^| findstr LISTENING') do (
    set "FOUND_PID=%%I"
    goto resolved
)
goto unresolved

:resolved
call :log RESOLVEPID matched listening port %APP_PORT%. PID=%FOUND_PID%
> "%PID_FILE%" echo %FOUND_PID%
exit /b 0

:unresolved
call :log RESOLVEPID no listening process found for port %APP_PORT%
set "FOUND_PID="
exit /b 1

:start
call :resolvepid
if defined FOUND_PID (
    echo [%APP_NAME%] Running process found, restarting. PID=%FOUND_PID%
    call :stop
)

call :checkvenv || exit /b 1
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%APP_NAME%] Starting...
echo   Home: %APP_HOME%
echo   Python: %PYTHON_EXE%
echo   Port: %APP_PORT%
echo   Log: %STARTUP_LOG%
call :log START requested. Home=%APP_HOME% Python=%PYTHON_EXE% Port=%APP_PORT%
call :log START using background command: "%PYTHON_EXE%" run.py

start "" /min cmd /c "cd /d ""%APP_HOME%"" && ""%PYTHON_EXE%"" run.py >> ""%STARTUP_LOG%"" 2>> ""%STARTUP_ERR_LOG%"""

call :log START waiting for port %APP_PORT% to become ready
timeout /t 10 /nobreak >nul
call :resolvepid
if not defined FOUND_PID (
    echo [ERROR] %APP_NAME% start failed.
    echo   Port: %APP_PORT%
    echo   Logs:
    echo     %STARTUP_LOG%
    echo     %STARTUP_ERR_LOG%
    call :log START failed. No listening process found on port %APP_PORT%.
    exit /b 1
)

echo [%APP_NAME%] Start succeeded.
echo   PID: %FOUND_PID%
echo   URL: http://127.0.0.1:%APP_PORT%/api/see-through/health
echo   Logs:
echo     %STARTUP_LOG%
echo     %STARTUP_ERR_LOG%
call :log START success. PID=%FOUND_PID% URL=http://127.0.0.1:%APP_PORT%/api/see-through/health
exit /b 0

:stop
call :resolvepid
if not defined FOUND_PID (
    echo [%APP_NAME%] Not running.
    exit /b 0
)

echo [%APP_NAME%] Stopping, PID=%FOUND_PID%...
call :log STOP requested. PID=%FOUND_PID%
taskkill /PID %FOUND_PID% >nul 2>&1
timeout /t 2 /nobreak >nul
tasklist /FI "PID eq %FOUND_PID%" | findstr /R /C:" %FOUND_PID% " >nul 2>&1
if not errorlevel 1 (
    echo [%APP_NAME%] Force killing...
    call :log STOP force kill required. PID=%FOUND_PID%
    taskkill /F /PID %FOUND_PID% >nul 2>&1
)
del "%PID_FILE%" >nul 2>&1
echo [%APP_NAME%] Stopped.
call :log STOP completed.
exit /b 0

:restart
call :stop
timeout /t 2 /nobreak >nul
call :start
exit /b %errorlevel%

:status
call :resolvepid
if not defined FOUND_PID (
    echo [%APP_NAME%] Not running.
    exit /b 0
)
echo [%APP_NAME%] Running, PID=%FOUND_PID%
tasklist /FI "PID eq %FOUND_PID%"
exit /b 0

:usage
echo Usage: %~nx0 ^<init^|start^|stop^|restart^|status^>
echo.
echo   init    Create venv and install dependencies
echo   start   Start service in background
echo   stop    Stop service
echo   restart Restart service
echo   status  Show service status
exit /b 1
