@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "APP_HOME=%~dp0"
cd /d "%APP_HOME%"

set "JAR_FILE=%APP_HOME%target\llm_queue-1.0-SNAPSHOT.jar"

if "%SERVER_PORT%"=="" set "SERVER_PORT=8080"
if "%LLM_QUEUE_TARGET_BASE_URL%"=="" set "LLM_QUEUE_TARGET_BASE_URL=http://127.0.0.1:8188"
if "%LLM_QUEUE_CAPACITY%"=="" set "LLM_QUEUE_CAPACITY=2"
if "%LLM_QUEUE_REQUEST_TIMEOUT%"=="" set "LLM_QUEUE_REQUEST_TIMEOUT=5m"
if "%LLM_QUEUE_UPSTREAM_TIMEOUT%"=="" set "LLM_QUEUE_UPSTREAM_TIMEOUT=5m"
if "%LLM_QUEUE_LOG_PATH%"=="" set "LLM_QUEUE_LOG_PATH=%APP_HOME%logs"

if exist "%LLM_QUEUE_LOG_PATH%" goto CHECK_JAVA
mkdir "%LLM_QUEUE_LOG_PATH%"

:CHECK_JAVA
where java >nul 2>nul
if not errorlevel 1 goto CHECK_JAR
echo [ERROR] java not found. Please install JDK 17 and add java to PATH.
goto FAIL

:CHECK_JAR
if exist "%JAR_FILE%" goto RESOLVE_CONFIG
echo [ERROR] jar file not found: %JAR_FILE%
echo Please run: mvn clean package
goto FAIL

:RESOLVE_CONFIG
set "CONFIG_ARGS="
set "RESOLVED_CONFIG_FILE="
if "%LLM_QUEUE_CONFIG_FILE%"=="" goto PRINT_CONFIG

set "RESOLVED_CONFIG_FILE=%LLM_QUEUE_CONFIG_FILE%"
if "%LLM_QUEUE_CONFIG_FILE:~1,1%"==":" goto CHECK_CONFIG_FILE
if "%LLM_QUEUE_CONFIG_FILE:~0,2%"=="\\" goto CHECK_CONFIG_FILE
set "RESOLVED_CONFIG_FILE=%APP_HOME%%LLM_QUEUE_CONFIG_FILE%"

:CHECK_CONFIG_FILE
if exist "%RESOLVED_CONFIG_FILE%" goto SET_CONFIG_ARGS
echo [ERROR] config file not found: %RESOLVED_CONFIG_FILE%
goto FAIL

:SET_CONFIG_ARGS
set "CONFIG_ARGS=--spring.config.additional-location=file:%RESOLVED_CONFIG_FILE% --llm.queue.config-file=%RESOLVED_CONFIG_FILE%"

:PRINT_CONFIG
echo ========================================
echo Start llm_queue
echo Jar: %JAR_FILE%
echo Port: %SERVER_PORT%
echo Target: %LLM_QUEUE_TARGET_BASE_URL%
echo Capacity: %LLM_QUEUE_CAPACITY%
echo LogPath: %LLM_QUEUE_LOG_PATH%
if not "%RESOLVED_CONFIG_FILE%"=="" echo ConfigFile: %RESOLVED_CONFIG_FILE%
echo ========================================

java %JAVA_OPTS% -Dfile.encoding=UTF-8 -jar "%JAR_FILE%" --server.port=%SERVER_PORT% --llm.queue.target-base-url=%LLM_QUEUE_TARGET_BASE_URL% --llm.queue.capacity=%LLM_QUEUE_CAPACITY% --llm.queue.request-timeout=%LLM_QUEUE_REQUEST_TIMEOUT% --llm.queue.upstream-timeout=%LLM_QUEUE_UPSTREAM_TIMEOUT% %CONFIG_ARGS% %*

set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" goto END
echo.
echo [ERROR] llm_queue stopped with exit code %EXIT_CODE%.
goto FAIL

:FAIL
echo.
echo Press any key to close this window.
pause >nul
exit /b 1

:END
endlocal
