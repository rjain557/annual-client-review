@echo off
REM ---------------------------------------------------------------
REM  Technijian daily Cisco Umbrella pull entry point.
REM  Triggered by Windows Scheduled Task "Technijian-DailyUmbrellaPull"
REM  every day at 2:00 AM local (Pacific) time, after the 1 AM
REM  Huntress pull and before the 7 AM monthly-pull / Friday weekly-audit.
REM
REM  - cd's to the repo
REM  - runs pull_umbrella_daily.py with default args (last 24h)
REM  - tees stdout/stderr to technijian/umbrella-pull/state/run-<YYYY-MM-DD>.log
REM ---------------------------------------------------------------
setlocal

set "REPO=c:\vscode\annual-client-review\annual-client-review"
set "PY=C:\Python314\python.exe"
set "SCRIPT=%REPO%\technijian\umbrella-pull\scripts\pull_umbrella_daily.py"
set "STATE=%REPO%\technijian\umbrella-pull\state"

if not exist "%STATE%" mkdir "%STATE%"

REM YYYY-MM-DD without locale-dependent date formatting.
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TS=%%i"
set "LOG=%STATE%\run-%TS%.log"

set PYTHONIOENCODING=utf-8

cd /d "%REPO%"
echo === %TS% umbrella daily pull start === >> "%LOG%"
"%PY%" "%SCRIPT%" >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo === %TS% umbrella daily pull end (exit %RC%) === >> "%LOG%"
exit /b %RC%
