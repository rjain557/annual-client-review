@echo off
REM ---------------------------------------------------------------
REM  Technijian daily Sophos Central Partner pull entry point.
REM  Triggered by Windows Scheduled Task "Technijian-DailySophosPull"
REM  every day at 5:00 AM local (Pacific) time.
REM
REM  - cd's to the repo
REM  - runs pull_sophos_daily.py with default args (last 24h)
REM  - regenerates the rsyslog tenant-map from today's firewall inventory
REM  - tees stdout/stderr to technijian/sophos-pull/state/run-<YYYY-MM-DD>.log
REM ---------------------------------------------------------------
setlocal

pushd "%~dp0..\.."
set "REPO=%CD%"
popd
set "PY=py.exe"
set "PYARGS=-3"
set "SCRIPT=%REPO%\technijian\sophos-pull\scripts\pull_sophos_daily.py"
set "SEEDER=%REPO%\technijian\sophos-pull\scripts\seed_tenant_map.py"
set "STATE=%REPO%\technijian\sophos-pull\state"

if not exist "%STATE%" mkdir "%STATE%"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TS=%%i"
set "LOG=%STATE%\run-%TS%.log"

set PYTHONIOENCODING=utf-8

cd /d "%REPO%"
echo === %TS% sophos daily pull start === >> "%LOG%"
"%PY%" %PYARGS% "%SCRIPT%" >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo === %TS% sophos rsyslog tenant-map seed === >> "%LOG%"
"%PY%" %PYARGS% "%SEEDER%" >> "%LOG%" 2>&1
echo === %TS% sophos daily pull end (exit %RC%) === >> "%LOG%"
exit /b %RC%
