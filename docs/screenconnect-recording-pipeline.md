# ScreenConnect Recording Pipeline — Specification

**Version:** 1.0  
**Date:** 2026-04-29  
**Status:** Active — first run in progress  
**Owner:** Technijian (rjain@technijian.com)

---

## 1. Purpose

Produce a permanent, searchable record of every remote-support session
conducted by Technijian technicians across all managed-IT clients for a
given calendar year. For each session, the pipeline captures:

- Who connected (technician name, connect timestamp)
- What machine they connected to
- How long the session lasted
- A compressed video recording stored in Microsoft Teams / OneDrive

The output is used during the **annual client review** to demonstrate service
delivery, verify billing accuracy, and provide a chain-of-custody record of
all remote access.

---

## 2. Data Sources

### 2.1 ScreenConnect Server — TE-DC-MYRMT-01

| Attribute | Value |
| --- | --- |
| Hostname | TE-DC-MYRMT-01 |
| IP Address | 10.100.14.10 |
| Product | ConnectWise Control (ScreenConnect) v26.1.25.9592 |
| URL | https://myremote2.technijian.com |
| Admin panel | https://myremote2.technijian.com/Administration |

### 2.2 Session Database (SQLite)

| Attribute | Value |
| --- | --- |
| File | `\\10.100.14.10\C$\Program Files (x86)\ScreenConnect\App_Data\Session.db` |
| Local copy | `C:\tmp\sc_db\Session.db` (copied at run time) |
| Format | SQLite 3 |
| Access | Read-only; copied locally to avoid WAL lock issues |

**Key tables:**

| Table | Purpose |
| --- | --- |
| `Session` | One row per support/access session. `CustomProperty1` = client code (e.g. `BWH`). `SessionID` = 16-byte .NET mixed-endian UUID BLOB. |
| `SessionEvent` | One row per event per session. `EventType = 1` (Connected), `Host` = technician full name, `Time` = .NET ticks (100-nanosecond intervals since 0001-01-01). |

**Critical constraint — 30-day purge:** ConnectWise Control is configured to
purge `SessionEvent` rows older than 30 days. This means technician attribution
data (`Host` field) is only available for the current rolling 30-day window.
Sessions older than 30 days will show an empty `tech_name` in the audit output.

**UUID conversion:** Session IDs in the DB are 16-byte BLOBs stored in
.NET mixed-endian byte order (bytes_le). Use `uuid.UUID(bytes_le=raw)` in Python
to convert to a standard UUID string for matching against recording filenames.

### 2.3 Recordings Directory

| Attribute | Value |
| --- | --- |
| UNC path | `\\10.100.14.10\E$\Myremote Recording\` |
| Mapped drive | `R:\` (persistent; `net use R: "\\10.100.14.10\E$\Myremote Recording" /persistent:yes`) |
| Format | Proprietary ScreenConnect Extended Auditing format (no file extension) |
| Structure | Flat directory — all recordings in a single folder, no subdirectories |
| Volume (2026-04-29) | 2,838 files, ~19.2 GB |
| Server free space | ~418 GB on E: drive |

**Filename pattern:**

```text
{SessionID}-{ConnectionID}-{YYYY}-{MM}-{DD}-{HH}-{mm}-{ss}-{YYYY}-{MM}-{DD}-{HH}-{mm}-{ss}
```

- First datetime = recording start (UTC)
- Second datetime = recording end (UTC)
- Both UUIDs are in standard string form (matching the converted `Session.SessionID`)

### 2.4 Client Code Mapping

Client codes are stored in `Session.CustomProperty1` (e.g. `BWH`, `JDH`, `ORX`).
These codes are Technijian's internal location codes — the same ones used across
all other pipelines (Huntress, CrowdStrike, Umbrella, monthly pull).

As of 2026-04-29: **38 distinct client codes** in the DB; **22 have recordings**
in the current month.

---

## 3. Pipeline Architecture

```text
[R:\ recordings drive]          [Session.db (local copy)]
        |                                 |
        | raw .crv files                  | session + event rows
        v                                 v
[SessionCaptureProcessor.exe]    [build_session_map()]
   GUI transcoder                         |
   (CRV → AVI, written to R:\)    [scan_recordings()]
        |                                 |
        | .avi files on R:\               | matched recording list
        v                                 v
[pull_screenconnect_2026.py]     [build_client_audit.py]
  --from-avi-dir R:\               --all --year 2026
  FFmpeg: AVI → MP4                         |
  CRF 28, preset slow                       |
        |                                   |
        v                                   v
[OneDrive FileCabinet]           [clients/{code}/screenconnect/{year}/]
  {CLIENT}-{YEAR}-{MONTH}/         {CLIENT}-SC-Audit-{year}.csv
    *.mp4                           {CLIENT}-SC-Audit-{year}.json
  _audit/audit_log.json
        |
        | auto-sync
        v
[Microsoft Teams — My Remote FileCabinet channel]
```

---

## 4. Pipeline Steps

### Step 1 — Map recordings drive

```cmd
net use R: "\\10.100.14.10\E$\Myremote Recording" /persistent:yes
```

Runs once per workstation. Persistent across reboots.

### Step 2 — Copy Session.db locally

Script: `pull_screenconnect_2026.py::refresh_local_db()`

Copies `Session.db` (and `Session.db-wal` if present) to `C:\tmp\sc_db\Session.db`.
Local copy avoids WAL-lock failures during remote SQLite access.

Skip on re-runs with `--no-refresh-db`.

### Step 3 — Build session map

Script: `pull_screenconnect_2026.py::build_session_map()`  
SQL: `SELECT SessionID, CustomProperty1, GuestMachineName, Name, SessionType FROM Session`

Produces `{session_uuid_str: {client, machine, name, type}}` for all sessions.
UUID conversion: `uuid.UUID(bytes_le=row[0])`.

### Step 4 — Transcode recordings: CRV → AVI

Tool: `technijian/screenconnect-pull/bin/SessionCaptureProcessor/ScreenConnectSessionCaptureProcessor.exe`

**GUI tool — no headless/CLI mode.** Automated via `sc_automate.ps1` (Windows UI
Automation):

1. Opens GUI, checks "Transcode after download"
2. Clicks "Choose Capture Files to Transcode"
3. Navigates to `R:\`, presses Ctrl+A, clicks Open

Output: `.avi` files written alongside source files on `R:\` (same directory).
The "Download Directory" field in the GUI applies only to the server-download
workflow, not local transcoding.

**SC API key:** `TechSCCapture2026!` (set in SC admin → Extensions → Session
Capture Processor → Edit Settings → Custom ApiKey field).

Time estimate: ~8 hours for 2,838 files on a LAN connection.

### Step 5 — Compress: AVI → MP4

Script: `pull_screenconnect_2026.py --from-avi-dir R:\`

For each `.avi` file on `R:\`:

1. Parses filename to extract session ID, connection ID, start datetime
2. Looks up client code from session map
3. Creates output folder: `{FileCabinet}\{CLIENT}-{YEAR}-{MONTH}\`
4. Runs FFmpeg: `libx264 -crf 28 -preset slow -c:a aac -b:a 128k -movflags +faststart`
5. Skips files where the `.mp4` already exists

Output path:

```text
C:\Users\rjain\OneDrive - Technijian, Inc\Technijian - My Remote - FileCabinet\
  {CLIENT}-{YEAR}-{MONTH}\
    {YYYYMMDD}_{CLIENT}_{session8}_{conn8}.mp4
  _audit\
    audit_log.json
    audit_log.csv
```

OneDrive desktop sync auto-uploads MP4s to Teams.

### Step 6 — Build per-client audit CSVs

Script: `build_client_audit.py --all --year 2026`

For each client with recordings:

1. Loads session map for that client (filtered by `CustomProperty1`)
2. Loads `SessionEvent` rows (`EventType = 1`, `Host != ''`) for those sessions
3. Scans `R:\` for matching `.avi` recordings (same filename pattern, `.avi` suffix)
4. Derives start/end time, duration from filename
5. Attaches tech name(s) from SessionEvent
6. Merges `teams_url` from `_audit/audit_log.json` if present

**Tech attribution logic:**

- `tech_name` = first `Host` who connected during the session (EventType=1)
- `all_techs` = all unique `Host` values in connect order (comma-separated)
- `tech_connect_time` = timestamp of first connect event
- If no events (purged): `tech_name = ""`, `all_techs = ""`

Output columns:

```text
recording_start, recording_end, duration_minutes, tech_name, all_techs,
machine, end_user, session_type, session_id, connection_id,
month, day, file_size_bytes, teams_url
```

Output location: `clients/{client_lower}/screenconnect/{year}/`

---

## 5. Automation

### Monthly wrapper

```cmd
technijian\screenconnect-pull\run-monthly-sc.cmd
```

Executes all steps in order:

1. Maps `R:\`
2. Launches `ScreenConnectSessionCaptureProcessor.exe`
3. Runs `sc_automate.ps1` — drives GUI to start transcoding
4. Starts `sc_watch_and_convert.py` in background

### Background watcher

Script: `technijian/screenconnect-pull/scripts/sc_watch_and_convert.py`

- Polls `R:\` every 5 minutes
- Compares AVI count to CRV count
- When AVI count stabilises for 3 consecutive checks → triggers Steps 5 and 6 automatically
- Log: `C:\tmp\sc_watch.log`

### Scheduled task (remote workstation)

```cmd
schtasks /create /tn "Technijian-MonthlyScreenConnectPull" ^
  /tr "...run-monthly-sc.cmd" /sc MONTHLY /d 28 /st 20:00 ^
  /ru "%USERNAME%" /f
```

**Run day: 28th of every month at 8 PM.** Chosen to capture the full prior month
before the 30-day SessionEvent purge would remove tech attribution data from
recordings made on the 1st.

**Requires interactive session.** The SessionCaptureProcessor GUI will not run
as SYSTEM or in a non-interactive session. Schedule with "Run only when user
is logged on."

---

## 6. Output Locations

| Output | Path | Consumed by |
| --- | --- | --- |
| AVI intermediates | `R:\{filename}.avi` | pull_screenconnect_2026.py |
| Compressed MP4s | `OneDrive\Technijian - My Remote - FileCabinet\{CLIENT}-{YEAR}-{MONTH}\*.mp4` | Teams (auto-sync), audit CSV |
| Audit log (all clients) | `...FileCabinet\_audit\audit_log.json` + `.csv` | build_client_audit.py merge step |
| Per-client audit CSV | `clients\{code}\screenconnect\{year}\{CLIENT}-SC-Audit-{year}.csv` | Annual client review |
| Per-client audit JSON | `clients\{code}\screenconnect\{year}\{CLIENT}-SC-Audit-{year}.json` | Annual client review |
| Watcher log | `C:\tmp\sc_watch.log` | Monitoring |

---

## 7. Client Scope (2026-04-29 snapshot)

| Metric | Value |
| --- | --- |
| Total clients in SC DB | 38 |
| Clients with 2026-04 recordings | 22 |
| Total recordings (April 2026) | 2,838 |
| Total raw size | ~19.2 GB |
| Estimated compressed size | ~2–4 GB (CRF 28) |

**Top clients by volume:**

| Client | Recordings | Raw Size |
| --- | --- | --- |
| JDH | 1,016 | ~14 GB |
| Technijian (internal) | 696 | ~1.9 GB |
| ORX | 348 | ~902 MB |
| ANI | 176 | ~594 MB |
| BWH | 163 | ~888 MB |
| VAF | 170 | ~316 MB |

**Tech attribution coverage gaps** (where SessionEvent rows were purged before
the 30-day window closed):

| Client | With Tech Name | Total | Coverage |
| --- | --- | --- | --- |
| BWH | 69 | 163 | 42% |
| JDH | 198 | 1,016 | 19% |
| ORX | 17 | 348 | 5% |

Sessions older than 30 days will always have empty `tech_name`. This is a
platform constraint — ScreenConnect does not retain event rows indefinitely.

---

## 8. Components and File Map

### Scripts

| File | Role |
| --- | --- |
| `technijian/screenconnect-pull/scripts/pull_screenconnect_2026.py` | DB copy → session map → AVI→MP4 compression → audit log |
| `technijian/screenconnect-pull/scripts/build_client_audit.py` | Per-client CSV/JSON with tech attribution + Teams URL merge |
| `technijian/screenconnect-pull/scripts/sc_automate.ps1` | Windows UI Automation — drives SessionCaptureProcessor GUI |
| `technijian/screenconnect-pull/scripts/sc_watch_and_convert.py` | Background watcher — polls AVI count, auto-triggers pipeline |
| `technijian/screenconnect-pull/run-monthly-sc.cmd` | Monthly wrapper — all steps in order |

### Bundled binary

| File | Role |
| --- | --- |
| `technijian/screenconnect-pull/bin/SessionCaptureProcessor/ScreenConnectSessionCaptureProcessor.exe` | Official ConnectWise CRV→AVI transcoder (GUI-only) |
| `technijian/screenconnect-pull/bin/SessionCaptureProcessor/*.dll` | 35 dependency DLLs (~17 MB total), required at runtime |
| `technijian/screenconnect-pull/bin/SessionCaptureProcessor/ScreenConnectSessionCaptureProcessor.exe.config` | Pre-configured: `ExtensionBaseUrl = https://myremote2.technijian.com` |

### Documentation

| File | Contents |
| --- | --- |
| [`workstation.md`](../workstation.md) (repo root, §26–27) | Full setup guide + scheduled task registration |
| `docs/screenconnect-recording-pipeline.md` | This specification |

---

## 9. Dependencies

| Dependency | Version | Install |
| --- | --- | --- |
| Python | 3.11+ | Pre-installed |
| FFmpeg | any modern | `winget install --id Gyan.FFmpeg -e` |
| OneDrive desktop sync | active, signed in | Required for Teams auto-sync of MP4s |
| Network access to 10.100.14.10 | LAN or VPN | R:\ mapping + DB copy |
| SessionCaptureProcessor.exe | bundled in repo | No install needed |

Python standard library only — no `pip install` required.

---

## 10. Known Constraints and Limitations

| Constraint | Impact | Mitigation |
| --- | --- | --- |
| 30-day SessionEvent purge | Tech attribution unavailable for sessions >30 days old | Run on 28th of each month to maximise coverage |
| GUI-only transcoder | Cannot run headless or as a scheduled service | `sc_automate.ps1` drives GUI via UI Automation; requires interactive session |
| AVI output to source dir | Transcoded AVIs land on R:\ (not local) | FFmpeg reads from R:\ during compression; no extra copy step needed |
| SC service WAL lock | Remote SQLite queries are unreliable | DB copied locally before querying |
| Session purge (not just events) | If sessions are purged, recording filename can't be matched to a client | Only affects recordings older than the session retention window |
| 0-byte AVI files | Some source recordings are empty (session ended before any frames captured) | Script detects size=0 and skips automatically |

---

## 11. Run Timeline (Monthly)

```text
Day 28 of month  20:00 PT   run-monthly-sc.cmd fires (scheduled task)
                             ↳ R:\ mapped
                             ↳ SessionCaptureProcessor.exe launched
                             ↳ sc_automate.ps1 selects all R:\ files → transcoding starts
                             ↳ sc_watch_and_convert.py starts in background

Day 29 of month  ~04:00 PT  Transcoding complete (~8 hrs for ~2,800 files)
                             ↳ Watcher detects stable AVI count
                             ↳ pull_screenconnect_2026.py --from-avi-dir R:\ runs
                               (FFmpeg AVI→MP4, ~2–4 hrs depending on total size)
                             ↳ build_client_audit.py --all runs (~5 min)
                             ↳ All outputs written + OneDrive sync begins

Day 29–30         morning    OneDrive sync completes; MP4s visible in Teams
                             Per-client audit CSVs available in clients/*/screenconnect/
```

**Total runtime estimate:** 10–12 hours end-to-end (dominated by transcoding).

---

## 12. Credentials and Keys

| Secret | Location | Used by |
| --- | --- | --- |
| SC API key (`TechSCCapture2026!`) | SC admin → Extensions → Session Capture Processor → Edit Settings | SessionCaptureProcessor GUI (server auth) |
| TE-DC-MYRMT-01 admin credentials | `keys/screenconnect-web.md` (OneDrive keyvault) | `net use` authentication if needed |

The SC API key enables the GUI's server-query mode ("Query Raw Captures").
It is **not required** for the local "Choose Capture Files to Transcode" workflow
used by this pipeline — but must be set for the GUI to start without errors.

---

## 13. Future Work

| Item | Notes |
| --- | --- |
| Gemini video analysis | `analyze_sessions_gemini.py` — uploads MP4s to Gemini Files API (gemini-2.0-flash, 1500/day free); outputs session summary JSON per recording. Blocked on API key in `keys/gemini.md`. Skill: `screenconnect-video-analysis`. |
| Extend coverage beyond 30 days | Not possible with current SC configuration. Would require SC admin to increase `SessionEvent` retention or enable extended auditing export. |
| Per-client Teams channel delivery | Currently all MP4s go to one shared FileCabinet folder. Could route per client via Graph API upload. |
| Automated headless transcoding | ConnectWise has not published a headless API for CRV transcoding. If they do, `sc_automate.ps1` becomes obsolete. |
