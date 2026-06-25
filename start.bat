@echo off
title Ragnarok Market Watcher

echo Checking dependencies...
pip show playwright >nul 2>&1
if errorlevel 1 (
    echo Installing Python packages...
    pip install -r "%~dp0src\requirements.txt"
    echo Installing Playwright Chromium browser...
    playwright install chromium
) else (
    pip show discord.py >nul 2>&1
    if errorlevel 1 (
        echo Installing Python packages...
        pip install -r "%~dp0src\requirements.txt"
    )
)

echo.
echo Starting Ragnarok Market Watcher...
echo Press Ctrl+C to stop.
echo.

python "%~dp0src\main.py" run

pause
