@echo off
setlocal EnableExtensions

REM ============================================================
REM Windows publish entry (wraps publish.sh)
REM Usage:
REM   publish.bat
REM   publish.bat ui_builder
REM   publish.bat video_analyze
REM   publish.bat ui_builder video_analyze
REM
REM Optional environment variables:
REM   REMOTE_USER
REM   REMOTE_PASS
REM ============================================================

if /I "%~1"=="-h" goto :usage
if /I "%~1"=="--help" goto :usage

set "SCRIPT_DIR=%~dp0"
set "SH_SCRIPT=%SCRIPT_DIR%publish.sh"
set "BASH_EXE=C:\Program Files\Git\bin\bash.exe"
if exist "%BASH_EXE%" goto :bash_ok

set "BASH_EXE=C:\Program Files\Git\usr\bin\bash.exe"
if exist "%BASH_EXE%" goto :bash_ok

where bash >nul 2>nul
if errorlevel 1 goto :no_bash
set "BASH_EXE=bash"
goto :bash_ok

:no_bash
echo [ERROR] Git Bash (bash.exe) not found.
echo [HINT ] Install Git for Windows, or add bash.exe to PATH.
echo [HINT ] Common path: C:\Program Files\Git\bin\bash.exe
exit /b 1

:bash_ok
if exist "%SH_SCRIPT%" goto :run
echo [ERROR] Script not found: %SH_SCRIPT%
exit /b 1

:run
echo [INFO ] Using Git Bash: "%BASH_EXE%"
echo [INFO ] Running: "%SH_SCRIPT%" %*
call "%BASH_EXE%" "%SH_SCRIPT%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if "%EXIT_CODE%"=="0" (
    echo [OK   ] Publish finished
) else (
    echo [ERROR] Publish failed with exit code: %EXIT_CODE%
)

endlocal & exit /b %EXIT_CODE%

:usage
echo Usage:
echo   publish.bat [ui_builder] [video_analyze]
echo.
echo Examples:
echo   publish.bat
echo   publish.bat ui_builder
echo   publish.bat video_analyze
echo.
echo Optional env:
echo   set REMOTE_USER=root
echo   set REMOTE_PASS=your_password
exit /b 0
