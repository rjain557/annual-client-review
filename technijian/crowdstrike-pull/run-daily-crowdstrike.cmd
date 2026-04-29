@echo off
REM ---------------------------------------------------------------
REM  Technijian daily CrowdStrike Falcon pull entry point.
REM  Triggered by Windows Scheduled Task "Technijian-DailyCrowdStrikePull"
REM  every day at 3:00 AM local (Pacific) time.
REM
REM  - cd's to the repo
REM  - runs pull_crowdstrike_daily.py with default args (last 24h)
REM  - tees stdout/stderr to technijian/crowdstrike-pull/state/run-<YYYY-MM-DD>.log
REM ---------------------------------------------------------------
setlocal

set "REPO=c:\vscode\annual-client-review\annual-client-review"
set "PY=C:\Python314\python.exe"
set "SCRIPT=%REPO%\technijian\crowdstrike-pull\scripts\pull_crowdstrike_daily.py"
set "STATE=%REPO%\technijian\crowdstrike-pull\state"

if not exist "%STATE%" mkdir "%STATE%"

REM YYYY-MM-DD without locale-dependent date formatting.
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TS=%%i"
set "LOG=%STATE%\run-%TS%.log"

set PYTHONIOENCODING=utf-8

cd /d "%REPO%"
echo === %TS% crowdstrike daily pull start === >> "%LOG%"
"%PY%" "%SCRIPT%" >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo === %TS% crowdstrike daily pull end (exit %RC%) === >> "%LOG%"
exit /b %RC%
