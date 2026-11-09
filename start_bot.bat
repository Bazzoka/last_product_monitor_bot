@echo off
cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

echo Starting Product Monitor Bot...
echo Dashboard: http://127.0.0.1:8080
echo Press Ctrl+C to stop.
python run.py
