@echo off
setlocal

set "APP_NAME=see_through"
set "APP_HOME=%~dp0"
if "%APP_HOME:~-1%"=="\" set "APP_HOME=%APP_HOME:~0,-1%"
set "PID_FILE=%APP_HOME%\%APP_NAME%.pid"
set "LOG_DIR=%APP_HOME%\logs"
set "STARTUP_LOG=%LOG_DIR%\startup.out"
set "STARTUP_ERR_LOG=%LOG_DIR%\startup.err"
set "VENV_DIR=%APP_HOME%\venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "START_HELPER=%APP_HOME%\start_helper.ps1"
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

:checkvenv
if exist "%PYTHON_EXE%" exit /b 0
echo [ERROR] Virtual environment not found: %VENV_DIR%
echo [TIP] Run: start.bat init
exit /b 1

:resolvepid
set "FOUND_PID="
if exist "%PID_FILE%" (
    set /p FOUND_PID=<"%PID_FILE%"
    tasklist /FI "PID eq %FOUND_PID%" | findstr /R /C:" %FOUND_PID% " >nul 2>&1
    if not errorlevel 1 exit /b 0
    del "%PID_FILE%" >nul 2>&1
    set "FOUND_PID="
)
for /f "tokens=5" %%I in ('netstat -ano ^| findstr ":%APP_PORT% " ^| findstr LISTENING') do (
    set "FOUND_PID=%%I"
    goto resolved
)
goto unresolved

:resolved
> "%PID_FILE%" echo %FOUND_PID%
exit /b 0

:unresolved
set "FOUND_PID="
exit /b 1

:start
call :resolvepid
if defined FOUND_PID (
    echo [%APP_NAME%] Already running, PID=%FOUND_PID%
    exit /b 0
)

call :checkvenv || exit /b 1
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo [%APP_NAME%] Starting...
echo   Home: %APP_HOME%
echo   Python: %PYTHON_EXE%
echo   Port: %APP_PORT%
echo   Log: %STARTUP_LOG%

set "NEW_PID="
for /f %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%START_HELPER%" -PythonExe "%PYTHON_EXE%" -AppHome "%APP_HOME%" -StartupLog "%STARTUP_LOG%" -StartupErrLog "%STARTUP_ERR_LOG%"') do set "NEW_PID=%%I"

timeout /t 3 /nobreak >nul
call :resolvepid
if not defined FOUND_PID (
    echo [ERROR] Failed to start process. Check logs.
    exit /b 1
)

echo [%APP_NAME%] Started, PID=%FOUND_PID%
exit /b 0

:stop
call :resolvepid
if not defined FOUND_PID (
    echo [%APP_NAME%] Not running.
    exit /b 0
)

echo [%APP_NAME%] Stopping, PID=%FOUND_PID%...
taskkill /PID %FOUND_PID% >nul 2>&1
timeout /t 2 /nobreak >nul
tasklist /FI "PID eq %FOUND_PID%" | findstr /R /C:" %FOUND_PID% " >nul 2>&1
if not errorlevel 1 (
    echo [%APP_NAME%] Force killing...
    taskkill /F /PID %FOUND_PID% >nul 2>&1
)
del "%PID_FILE%" >nul 2>&1
echo [%APP_NAME%] Stopped.
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
