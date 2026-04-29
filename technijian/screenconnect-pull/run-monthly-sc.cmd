@echo off
REM Monthly ScreenConnect recording pipeline
REM Launches GUI transcoder, starts background watcher, logs output.
REM REQUIRES interactive logged-in session (GUI tool will not run as SYSTEM).

pushd "%~dp0..\.."
set REPO=%CD%
popd
set SCRIPTS=%REPO%\technijian\screenconnect-pull\scripts
set BIN=%REPO%\technijian\screenconnect-pull\bin\SessionCaptureProcessor
set AUTOMATE=%SCRIPTS%\sc_automate.ps1
set WATCHER=%SCRIPTS%\sc_watch_and_convert.py
set LOGDIR=%REPO%\technijian\screenconnect-pull\state
set LOGFILE=%LOGDIR%\run-%DATE:~10,4%-%DATE:~4,2%-%DATE:~7,2%.log

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo [%TIME%] Monthly SC pull starting >> "%LOGFILE%"

REM --- Step 1: map recordings drive ---
net use R: "\\10.100.14.10\E$\Myremote Recording" /persistent:yes >> "%LOGFILE%" 2>&1

REM --- Step 2: launch GUI ---
echo [%TIME%] Launching SessionCaptureProcessor... >> "%LOGFILE%"
start "" "%BIN%\ScreenConnectSessionCaptureProcessor.exe"
timeout /t 3 /nobreak > nul

REM --- Step 3: automate GUI (select all R:\ files + start transcoding) ---
echo [%TIME%] Running GUI automation... >> "%LOGFILE%"
powershell -ExecutionPolicy Bypass -File "%AUTOMATE%" >> "%LOGFILE%" 2>&1

REM --- Step 4: start background watcher (auto-runs pipeline when transcoding done) ---
echo [%TIME%] Starting background watcher... >> "%LOGFILE%"
powershell -Command "Start-Process python -ArgumentList '%WATCHER%' -WindowStyle Hidden -RedirectStandardOutput 'c:\tmp\sc_watch_stdout.txt' -RedirectStandardError 'c:\tmp\sc_watch_stderr.txt'"

echo [%TIME%] Watcher started. Transcoding in progress - check c:\tmp\sc_watch.log for status. >> "%LOGFILE%"
echo Transcoding started. Monitor: type c:\tmp\sc_watch.log
echo Pipeline will auto-run when transcoding finishes (~8 hours).
