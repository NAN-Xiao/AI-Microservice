@echo off
setlocal

cd /d "%~dp0"

call venv\Scripts\activate.bat
python main.py --listen 0.0.0.0 --port 8188
