@echo off
REM Technijian M365 Storage Pull — weekly storage usage monitoring
REM Scheduled Task: Technijian-WeeklyM365StoragePull  Monday 07:00 PT
REM See workstation.md for setup instructions.

setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

python scripts\pull_m365_storage.py %*
if errorlevel 1 (
    echo [ERROR] M365 Storage Pull failed with code %errorlevel%
    exit /b %errorlevel%
)
endlocal
