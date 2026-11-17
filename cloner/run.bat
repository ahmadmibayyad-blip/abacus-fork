@echo off
REM Start Cloner on http://127.0.0.1:8765/ (first run installs everything)
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist node_modules call npm install --no-audit --no-fund
python -m cloner
