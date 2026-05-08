@echo off
setlocal

title see_through 一键启动
cd /d "%~dp0"
".\venv\Scripts\python.exe" run.py

endlocal
