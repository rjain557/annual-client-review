@echo off
REM ---------------------------------------------------------------
REM  Technijian hourly Sophos Central Partner pull + alert router.
REM  Triggered by Windows Scheduled Task "Technijian-HourlySophos"
REM  every hour at :15 past the hour.
REM
REM  Steps:
REM    1. pull_sophos_daily.py        (per-tenant snapshot, last 24h)
REM    2. seed_tenant_map.py          (regenerate rsyslog allowlist)
REM    3. route_alerts.py             (REPORT mode by default; switch to
REM                                    --apply once cp_tickets is wired
REM                                    AND the user has approved going live)
REM
REM  Logs to technijian/sophos-pull/state/run-<YYYY-MM-DD>.log (appended).
REM ---------------------------------------------------------------
setlocal

set "REPO=c:\vscode\annual-client-review\annual-client-review"
set "PY=C:\Python314\python.exe"
set "PULL=%REPO%\technijian\sophos-pull\scripts\pull_sophos_daily.py"
set "SEED=%REPO%\technijian\sophos-pull\scripts\seed_tenant_map.py"
set "ROUTE=%REPO%\technijian\sophos-pull\scripts\route_alerts.py"
set "STATE=%REPO%\technijian\sophos-pull\state"

REM Routing mode. Default REPORT (safe). Set ROUTER_MODE=apply to actually
REM create CP tickets and send reminder emails. The cp_tickets.create_ticket
REM SP must be wired before --apply will produce real tickets; until then
REM --apply still tracks state and sends reminder emails for alerts that
REM age past the threshold (any alert with ticket_id=null and first_seen
REM older than --reminder-hours).
if "%ROUTER_MODE%"=="" set "ROUTER_MODE=report"

if not exist "%STATE%" mkdir "%STATE%"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "TS=%%i"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format HH:mm"') do set "HM=%%i"
set "LOG=%STATE%\run-%TS%.log"

set PYTHONIOENCODING=utf-8

cd /d "%REPO%"

echo === %TS% %HM% sophos hourly start ROUTER_MODE=%ROUTER_MODE% === >> "%LOG%"

"%PY%" "%PULL%" >> "%LOG%" 2>&1
set "RC_PULL=%ERRORLEVEL%"

"%PY%" "%SEED%" >> "%LOG%" 2>&1
set "RC_SEED=%ERRORLEVEL%"

if /I "%ROUTER_MODE%"=="apply" (
  "%PY%" "%ROUTE%" --apply >> "%LOG%" 2>&1
) else (
  "%PY%" "%ROUTE%" >> "%LOG%" 2>&1
)
set "RC_ROUTE=%ERRORLEVEL%"

echo === %TS% %HM% sophos hourly end (pull=%RC_PULL% seed=%RC_SEED% route=%RC_ROUTE%) === >> "%LOG%"

REM Surface any non-zero exit so Task Scheduler can show "Last Run Result" != 0
if not "%RC_PULL%"=="0" exit /b %RC_PULL%
if not "%RC_ROUTE%"=="0" exit /b %RC_ROUTE%
exit /b 0
