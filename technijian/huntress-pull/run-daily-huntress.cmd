@echo off
REM ---------------------------------------------------------------
REM  Technijian daily Huntress pull entry point.
REM  Triggered by Windows Scheduled Task "Technijian-DailyHuntressPull"
REM  every day at 1:00 AM local (Pacific) time.
REM
REM  - cd's to the repo
REM  - runs pull_huntress_daily.py with default args (last 24h)
REM  - tees stdout/stderr to technijian/huntress-pull/state/run-<YYYY-MM-DD>.log
REM ---------------------------------------------------------------
setlocal

pushd "%~dp0..\.."
set "REPO=%CD%"
popd
set "PY=py.exe"
set "PYARGS=-3"
set "SCRIPT=%REPO%\technijian\huntress-pull\scripts\pull_huntress_daily.py"
set "STATE=%REPO%\technijian\huntress-pull\state"

if not exist "%STATE%" mkdir "%STATE%"

REM YYYY-MM-DD without locale-dependent date formatting.
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TS=%%i"
set "LOG=%STATE%\run-%TS%.log"

set PYTHONIOENCODING=utf-8

cd /d "%REPO%"
echo === %TS% huntress daily pull start === >> "%LOG%"
"%PY%" %PYARGS% "%SCRIPT%" >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo === %TS% huntress daily pull end (exit %RC%) === >> "%LOG%"
exit /b %RC%
