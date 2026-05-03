@echo off
REM ---------------------------------------------------------------
REM  Technijian daily VMware vCenter pull entry point.
REM  Triggered by Windows Scheduled Task "Technijian-DailyVCenterPull"
REM  every day at 06:00 AM local (Pacific) time.
REM
REM  - cd's to the repo
REM  - runs daily_run.py: pulls inventory + 5-min perf, splits per client,
REM    aggregates to daily peak/avg/p95, appends to per-client accumulators.
REM  - tees stdout/stderr to scripts/vcenter/state/run-<YYYY-MM-DD>.log
REM ---------------------------------------------------------------
setlocal

pushd "%~dp0..\.."
set "REPO=%CD%"
popd
set "PY=py.exe"
set "PYARGS=-3"
set "SCRIPT=%REPO%\scripts\vcenter\daily_run.py"
set "STATE=%REPO%\scripts\vcenter\state"

if not exist "%STATE%" mkdir "%STATE%"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TS=%%i"
set "LOG=%STATE%\run-%TS%.log"

set PYTHONIOENCODING=utf-8

cd /d "%REPO%"
echo === %TS% vcenter daily pull start === >> "%LOG%"
"%PY%" %PYARGS% "%SCRIPT%" >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo === %TS% vcenter daily pull end (exit %RC%) === >> "%LOG%"
exit /b %RC%
