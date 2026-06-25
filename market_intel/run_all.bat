@echo off
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs

echo [%date% %time%] Starting Collector... >> logs\collector.log
start /b "" .venv\Scripts\python.exe collector\runner.py >> logs\collector.log 2>&1

echo [%date% %time%] Starting API... >> logs\api.log
start /b "" .venv\Scripts\python.exe -m uvicorn api.main:app --port 8000 >> logs\api.log 2>&1

echo [%date% %time%] Starting Dashboard... >> logs\frontend.log
start /b "" cmd /c frontend\run_frontend.bat >> logs\frontend.log 2>&1

echo Market Intel: Collector + API + Dashboard started in this window.
echo Logs: %cd%\logs\collector.log / api.log / frontend.log
echo Closing this window stops all three. Ctrl+C also stops all three.

:keepalive
timeout /t 3600 /nobreak >nul
goto keepalive
