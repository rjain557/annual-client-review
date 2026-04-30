@echo off
REM Technijian M365 Security Pull — daily sign-in log monitoring
REM Scheduled Task: Technijian-DailyM365SecurityPull  06:00 PT daily
REM See workstation.md for setup instructions.

setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

python scripts\pull_m365_security.py %*
if errorlevel 1 (
    echo [ERROR] M365 Security Pull failed with code %errorlevel%
    exit /b %errorlevel%
)
endlocal
