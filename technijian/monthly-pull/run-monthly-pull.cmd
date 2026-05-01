@echo off
REM ---------------------------------------------------------------
REM  Technijian monthly client pull entry point.
REM  Triggered by Windows Scheduled Task "Technijian-MonthlyClientPull"
REM  on the 1st of every month at 7:00 AM local (Pacific) time.
REM
REM  - cd's to the repo
REM  - runs pull_monthly.py with default args (prior calendar month)
REM  - tees stdout/stderr to technijian/monthly-pull/state/<YYYY-MM-DD>.log
REM ---------------------------------------------------------------
setlocal

pushd "%~dp0..\.."
set "REPO=%CD%"
popd
set "PY=py.exe"
set "PYARGS=-3"
set "SCRIPT=%REPO%\technijian\monthly-pull\scripts\pull_monthly.py"
set "STATE=%REPO%\technijian\monthly-pull\state"

if not exist "%STATE%" mkdir "%STATE%"

REM YYYY-MM-DD without locale-dependent date formatting.
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TS=%%i"
set "LOG=%STATE%\run-%TS%.log"

set PYTHONIOENCODING=utf-8

cd /d "%REPO%"
echo === %TS% monthly pull start === >> "%LOG%"
"%PY%" %PYARGS% "%SCRIPT%" >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo === %TS% monthly pull end (exit %RC%) === >> "%LOG%"
exit /b %RC%
