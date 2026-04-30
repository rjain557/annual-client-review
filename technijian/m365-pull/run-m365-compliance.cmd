@echo off
REM Technijian M365 Compliance Pull — monthly posture snapshot
REM Scheduled Task: Technijian-MonthlyM365CompliancePull  Day 2, 08:00 PT
REM See workstation.md for setup instructions.

setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

python scripts\pull_m365_compliance.py %*
if errorlevel 1 (
    echo [ERROR] M365 Compliance Pull failed with code %errorlevel%
    exit /b %errorlevel%
)
endlocal
