@echo off
REM Daily Teramind compliance pull — run by Scheduled Task "Technijian-DailyTeramindPull"
REM Registered on the production workstation per workstation.md §18.

pushd "%~dp0..\.." & set "REPO=%CD%" & popd
cd /d "%REPO%"

set LOG=%~dp0state\run-%DATE:~10,4%-%DATE:~4,2%-%DATE:~7,2%.log
echo [%DATE% %TIME%] Starting Teramind daily pull >> "%LOG%"

py.exe -3 technijian\teramind-pull\scripts\pull_teramind_daily.py >> "%LOG%" 2>&1

echo [%DATE% %TIME%] Done (exit %ERRORLEVEL%) >> "%LOG%"
