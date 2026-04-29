# Workstation Setup — ScreenConnect Recording Pipeline

Converts all ScreenConnect session recordings to MP4, organises them into
`OneDrive - Technijian, Inc\Technijian - My Remote - FileCabinet\{CLIENT}-{YEAR}-{MONTH}\`,
then regenerates per-client audit CSVs with the OneDrive video link in every row.

Run this **once per month** (before the 30-day SC session purge closes the window).
The pipeline is designed to run on any domain-joined workstation that can reach
`\\10.100.14.10` — it does not need to be the SC server itself.

---

## Prerequisites

| Component | Version | Notes |
| --- | --- | --- |
| Python | 3.11+ | Tested on 3.14.3 at `C:\Python314\python.exe` |
| FFmpeg | any modern | `winget install --id Gyan.FFmpeg -e` then verify: `ffmpeg -version` |
| OneDrive (Technijian tenant) | signed in | Syncs FileCabinet folder; keyfiles at `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\` |
| Network access to 10.100.14.10 | on-LAN or VPN | SC server (TE-DC-MYRMT-01) must be reachable |

The `SessionCaptureProcessor.exe` converter is **bundled in the repo** — no separate
download needed:

```text
technijian\screenconnect-pull\bin\SessionCaptureProcessor\ScreenConnectSessionCaptureProcessor.exe
```

---

## Step 1 — Map the recordings share

Run once per session (or make persistent with `/persistent:yes`):

```cmd
net use R: "\\10.100.14.10\E$\Myremote Recording" /persistent:yes
```

Verify: `dir R:\ | find /c ""` should show ~2800+ files.

---

## Step 2 — Transcode CRV → AVI (GUI, one-time or monthly)

The SessionCaptureProcessor converts ScreenConnect's proprietary `.crv` format
to `.avi`. It is a GUI tool; use the automation script to drive it hands-free.

### Option A — fully automated (recommended for scheduled / remote runs)

```powershell
# From an elevated PowerShell
Start-Process python -ArgumentList "technijian\screenconnect-pull\scripts\sc_automate.ps1" -WindowStyle Normal
```

Or run the PowerShell script directly:

```powershell
powershell -ExecutionPolicy Bypass -File technijian\screenconnect-pull\scripts\sc_automate.ps1
```

`sc_automate.ps1` (kept in `c:\tmp\` — generated at runtime, not committed) will:

1. Find the running `ScreenConnectSessionCaptureProcessor.exe` window
2. Check the **"Transcode after download"** box
3. Click **"Choose Capture Files to Transcode"**
4. Navigate to `R:\` and select all files (Ctrl+A)
5. Click **Open** to start transcoding

The GUI must be open before running the script. Launch it from the repo:

```cmd
start "" "c:\vscode\annual-client-review\annual-client-review\technijian\screenconnect-pull\bin\SessionCaptureProcessor\ScreenConnectSessionCaptureProcessor.exe"
```

Wait ~2 seconds for it to fully load, then run the automation script.

### Option B — manual

1. Open `technijian\screenconnect-pull\bin\SessionCaptureProcessor\ScreenConnectSessionCaptureProcessor.exe`
2. **Check "Transcode after download"**
3. Click **"Choose Capture Files to Transcode"**
4. In the file picker: navigate to `R:\`, press **Ctrl+A**, click **Open**
5. Leave the window open — do not close it while transcoding

**Output location:** AVIs are written alongside the source files on `R:\` (same
directory), with `.avi` appended to the original filename. The "Download Directory"
field (`C:\tmp\sc_avis`) applies only to the server-download workflow, not local
transcoding.

**Time estimate:** ~8 hours for 2,800 files. Run overnight.

---

## Step 3 — Watch + auto-convert (background, hands-free)

Start the watcher immediately after launching the GUI transcoding. It polls every
5 minutes and automatically triggers Steps 4 and 5 when the AVI count stabilises.

```powershell
Start-Process python -ArgumentList "technijian\screenconnect-pull\scripts\sc_watch_and_convert.py" -WindowStyle Hidden `
    -RedirectStandardOutput "c:\tmp\sc_watch_stdout.txt" `
    -RedirectStandardError  "c:\tmp\sc_watch_stderr.txt"
```

Monitor progress anytime:

```powershell
Get-Content "c:\tmp\sc_watch.log" -Tail 20
```

---

## Step 4 — Compress AVI → MP4 into OneDrive FileCabinet

> Handled automatically by the watcher — only run manually if watcher was not started.

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

python technijian\screenconnect-pull\scripts\pull_screenconnect_2026.py ^
    --from-avi-dir R:\ --no-refresh-db
```

Output per client:

```text
C:\Users\rjain\OneDrive - Technijian, Inc\Technijian - My Remote - FileCabinet\
  {CLIENT}-{YEAR}-{MONTH}\
    {YYYYMMDD}_{CLIENT}_{session8}_{conn8}.mp4
  _audit\
    audit_log.json
    audit_log.csv
```

OneDrive desktop sync auto-uploads everything in that folder to Teams.

---

## Step 5 — Regenerate per-client audit CSVs

> Handled automatically by the watcher — only run manually if watcher was not started.

```cmd
python technijian\screenconnect-pull\scripts\build_client_audit.py ^
    --all --year 2026 --no-refresh-db
```

Output per client:

```text
clients\{client}\screenconnect\2026\
  {CLIENT}-SC-Audit-2026.csv    (recording_start, tech_name, machine, teams_url, ...)
  {CLIENT}-SC-Audit-2026.json
```

---

## Monthly wrapper (all steps combined)

```cmd
c:\vscode\annual-client-review\annual-client-review\technijian\screenconnect-pull\run-monthly-sc.cmd
```

This wrapper:

1. Launches the SessionCaptureProcessor GUI
2. Runs `sc_automate.ps1` to start GUI transcoding
3. Starts `sc_watch_and_convert.py` in the background
4. Logs to `technijian\screenconnect-pull\state\run-YYYY-MM-DD.log`

**The wrapper requires an interactive logged-in user session** (the GUI tool will
not run as SYSTEM or in a non-interactive session). Schedule it via Task Scheduler
with the option "Run only when user is logged on".

### Register as a monthly Task Scheduler job

```cmd
schtasks /create ^
  /tn "Technijian-MonthlyScreenConnectPull" ^
  /tr "\"c:\vscode\annual-client-review\annual-client-review\technijian\screenconnect-pull\run-monthly-sc.cmd\"" ^
  /sc MONTHLY /d 28 /st 20:00 ^
  /ru "%USERNAME%" ^
  /f
```

Runs on the **28th of each month at 8 PM** — before the 30-day purge would remove
recordings from the beginning of the month.

Verify:

```cmd
schtasks /query /tn "Technijian-MonthlyScreenConnectPull" /v /fo LIST
```

Run on demand:

```cmd
schtasks /run /tn "Technijian-MonthlyScreenConnectPull"
```

---

## Server paths (TE-DC-MYRMT-01 — 10.100.14.10)

| What | Path |
| --- | --- |
| SQLite DB | `\\10.100.14.10\C$\Program Files (x86)\ScreenConnect\App_Data\Session.db` |
| Raw recordings (CRV) | `\\10.100.14.10\E$\Myremote Recording\` (no file extension) |
| Mapped drive | `R:\` → `\\10.100.14.10\E$\Myremote Recording` |
| SC install | `\\10.100.14.10\C$\Program Files (x86)\ScreenConnect\` |
| Converter (bundled) | `technijian\screenconnect-pull\bin\SessionCaptureProcessor\ScreenConnectSessionCaptureProcessor.exe` |

**SC API key** (for SessionCaptureProcessor GUI): stored in SC admin panel at
`https://myremote2.technijian.com → Administration → Extensions → Session Capture
Processor → Edit Settings → Custom ApiKey`. Current key: `TechSCCapture2026!`
(stored in `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\screenconnect-web.md`).

Recording filename pattern:

```text
{SessionID}-{ConnectionID}-{YYYY}-{MM}-{DD}-{HH}-{mm}-{ss}-{YYYY}-{MM}-{DD}-{HH}-{mm}-{ss}
```

Session IDs in the SQLite DB are 16-byte .NET mixed-endian BLOBs.
Use `uuid.UUID(bytes_le=raw)` to match against recording filenames.

**30-day purge:** SC purges session events older than 30 days. As of 2026-04-29
only April 2026 events exist. Run before the 28th of each month to capture the
full previous month.

---

## Scope (2026-04-29 snapshot)

- 2,838 recordings across 22 clients, ~19.2 GB raw
- Largest: JDH (1,016 recs / 14 GB), Technijian (696 / 1.9 GB), ORX (348 / 902 MB)
- Tech name coverage gaps: where SessionEvent purged before 30-day window

---

## Triage

| Symptom | Fix |
| --- | --- |
| `R:\` not accessible | Run `net use R: "\\10.100.14.10\E$\Myremote Recording" /persistent:yes` |
| `ffmpeg not found` | `winget install --id Gyan.FFmpeg -e`, restart shell |
| GUI "Unable to read beyond the end of the stream" | Normal on startup; only appears when using the API query path, not "Choose Capture Files to Transcode" |
| 0-byte AVI file on R:\ | Source recording is empty or was in-progress; script skips it |
| Watcher log stuck at 0% | Check `c:\tmp\sc_watch_stdout.txt` for errors; verify GUI is showing "Transcoding..." in status bar |
| `mp4_path` missing from audit CSV | Watcher hasn't finished yet; re-run `build_client_audit.py --all` after watcher completes |
| SC session purged (no client in DB) | Expected for older sessions; recording skipped automatically |
