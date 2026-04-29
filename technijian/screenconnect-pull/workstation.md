# Workstation setup - ScreenConnect recording converter + Teams uploader

This skill takes ScreenConnect (`.crv`) session recordings and produces
web-friendly `.mp4` files, then uploads them to a Microsoft Teams channel.
Conversion runs on a workstation that can reach the SC server's recordings
share. **Do not install on the development laptop** unless you are doing
local testing against a sample `.crv`.

Two scripts live under `technijian/screenconnect-pull/scripts/`:

1. `convert_recording.py` - takes a `.crv` (or a directory of them) and
   writes `.mp4` next to the source or into a `--output-dir`.
2. `upload_to_teams.py` - takes one or more `.mp4` files (or a manifest from
   step 1) and uploads them to the Teams channel configured in
   `state/teams-destination.json`.

## Prerequisites

1. **Python 3.14** at `C:\Python314\python.exe` (matches `huntress-pull`,
   `umbrella-pull`, `crowdstrike-pull`).
2. **ScreenConnect.RecordingConverter.exe** on this host. Auto-detected at:
   - `C:\Program Files (x86)\ScreenConnect\ScreenConnect.RecordingConverter.exe`
   - `C:\Program Files\ScreenConnect\ScreenConnect.RecordingConverter.exe`
   - `C:\ProgramData\ScreenConnect\ScreenConnect.RecordingConverter.exe`

   Override with `--converter <path>` or env var `SC_CONVERTER`. If the
   workstation is not the SC server itself, copy the `.exe` from the SC
   server's install dir — it is self-contained and does not need a running
   SC service.
3. **FFmpeg** on PATH:
   ```powershell
   winget install --id Gyan.FFmpeg -e
   ```
   Verify: `ffmpeg -version`
4. **Access to the `.crv` recordings.** Either run on the SC server, or
   mount its `App_Data\Session Recordings` folder as a UNC share accessible
   to the workstation user (read-only is fine).
5. **OneDrive sync active** so the M365 keyfile resolves:
   `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\m365-graph.md`
6. **App registration permissions** (admin-consented application perms):
   - `Files.ReadWrite.All` - write to the Teams channel's SharePoint folder
   - `Group.Read.All` - resolve `/teams/{id}/channels/{id}/filesFolder`

## Confirmed server paths (TE-DC-MYRMT-01 — 10.100.14.10)

Access via admin share with Administrator credentials (stored in `screenconnect-web.md`):

```powershell
net use \\10.100.14.10\IPC$ /user:Administrator "T3chn!j2n92618!!"
```

| What | UNC Path |
| --- | --- |
| SQLite DB | `\\10.100.14.10\C$\Program Files (x86)\ScreenConnect\App_Data\Session.db` |
| Recordings | `\\10.100.14.10\E$\Myremote Recording\` (flat, no file extension) |
| SC install | `\\10.100.14.10\C$\Program Files (x86)\ScreenConnect\` |
| Security DB | `\\10.100.14.10\C$\Program Files (x86)\ScreenConnect\App_Data\Security.db` |

Recording filenames follow the pattern:
`{SessionID(UUID)}-{ConnectionID(UUID)}-{YYYY}-{MM}-{DD}-{HH}-{mm}-{ss}-{YYYY}-{MM}-{DD}-{HH}-{mm}-{ss}`

Session IDs in the SQLite DB are stored as 16-byte BLOBs in **.NET mixed-endian** byte order.
Use `uuid.UUID(bytes_le=raw_bytes)` to convert to string for matching against recording filenames.

**Scope as of 2026-04-29:** 2758 recordings, ~19 GB raw, across 22 clients. All in April 2026
(the maintenance plan purges sessions >30 days old, so older session→client mappings are gone).

## Get the RecordingConverter

The recording files use ScreenConnect's proprietary Extended Auditing format. You need
`ScreenConnect.RecordingConverter.exe` to convert them to `.avi` first.

**Option A — Download from your SC admin panel (fastest):**

```
https://myremote.technijian.com → Administration → Downloads
→ "ConnectWise Control Recording Converter"
```

**Option B — ConnectWise partner portal:**

[https://home.connectwise.com](https://home.connectwise.com) → Software → ConnectWise Control
→ download v26.1 installer zip → extract `ScreenConnect.RecordingConverter.exe`

**Install location for scripts:**

```text
C:\tools\ScreenConnect.RecordingConverter.exe
```

`pull_screenconnect_2026.py` auto-detects this path. Override with `SC_CONVERTER` env var.

## 2026 batch pull (convert + upload + audit log)

`pull_screenconnect_2026.py` does everything end-to-end from the server:

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM Step 1: audit only (no conversion) — verify scope, generates audit_log.csv
C:\Python314\python.exe technijian\screenconnect-pull\scripts\pull_screenconnect_2026.py ^
    --audit-only --output-dir C:\converted\sc-2026

REM Step 2: dry run (plan without converting)
C:\Python314\python.exe technijian\screenconnect-pull\scripts\pull_screenconnect_2026.py ^
    --dry-run --output-dir C:\converted\sc-2026

REM Step 3: one client first (BWH) as a pilot
C:\Python314\python.exe technijian\screenconnect-pull\scripts\pull_screenconnect_2026.py ^
    --client BWH --output-dir C:\converted\sc-2026

REM Step 4: full 2026 batch (all clients)
C:\Python314\python.exe technijian\screenconnect-pull\scripts\pull_screenconnect_2026.py ^
    --output-dir C:\converted\sc-2026
```

Output per run:

| File | Contents |
| --- | --- |
| `C:\converted\sc-2026\audit_log.json` | All recording records with session metadata + Teams `webUrl` (OneDrive link) |
| `C:\converted\sc-2026\audit_log.csv` | Same data as CSV for Excel |
| `C:\converted\sc-2026\{client}\{YYYY-MM}\{date}_{client}_{session}_{conn}.mp4` | Converted MP4s |

The `teams_url` column in the audit log is the direct OneDrive share link for each recording, so every session event can be linked to its video.

**Flags:**

| Flag | Effect |
| --- | --- |
| `--audit-only` | Skip conversion entirely; just write the audit log manifest |
| `--dry-run` | Plan everything, convert nothing |
| `--client CODE` | Process one client only |
| `--no-upload` | Convert to MP4 but skip Teams upload |
| `--no-refresh-db` | Reuse the cached local DB copy (skip the copy-from-server step) |

## Smoke test (single .crv)

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM dry-run first - prints plan without executing
C:\Python314\python.exe technijian\screenconnect-pull\scripts\convert_recording.py ^
    "<full path to a sample .crv>" --output-dir C:\temp\sc-test --dry-run

REM real conversion
C:\Python314\python.exe technijian\screenconnect-pull\scripts\convert_recording.py ^
    "<full path to a sample .crv>" --output-dir C:\temp\sc-test
```

Open `C:\temp\sc-test\<sessionid>.mp4` in your default player. It should
play in any browser, Teams (inline), VLC, Quicktime, or Windows Media.

Typical sizes for a 1-hour single-monitor session:

| Stage | Size | Codec |
|---|---|---|
| .crv | 80-300 MB | proprietary |
| .avi | 2-8 GB | MJPEG (intermediate, deleted after) |
| .mp4 | 100-400 MB | H.264 + AAC, faststart |

The `.avi` is huge but transient. Ensure `--output-dir` has ~10x the source
`.crv` size free during conversion.

## Encode tuning

| Flag | Default | Effect |
|---|---|---|
| `--crf <n>` | 23 | Lower = bigger+higher quality. 18 = near-lossless, 28 = small/grainy. |
| `--preset <s>` | medium | `ultrafast` ~3x speed at ~1.3x size; `slow` ~0.7x speed at ~0.9x size. |
| `--keep-intermediate` | off | Keep `.avi` for debugging a corrupt MP4. |
| `--overwrite` | off | Re-encode an MP4 that already exists. |
| `--dry-run` | off | Print plan, run nothing. |
| `--manifest <path>` | none | Write a JSON manifest (consumed by `upload_to_teams.py --from-manifest`). |

Batch conversion of a whole month:
```cmd
C:\Python314\python.exe technijian\screenconnect-pull\scripts\convert_recording.py ^
    "\\<sc-server>\recordings$\2026\04" ^
    --output-dir "C:\converted\2026-04" ^
    --manifest "C:\converted\2026-04\manifest.json"
```

## Configure the Teams destination

1. Get the team and channel IDs. Easiest: open Teams web, navigate to the
   channel, click **...** -> **Get link to channel**. The link contains
   `groupId=<team-guid>` and `channel/<urlencoded-id>`. URL-decode the
   channel id — it looks like `19:abcdef...@thread.tacv2`.

2. Copy the template and fill it in (the live config file is gitignored):
   ```cmd
   copy technijian\screenconnect-pull\state\teams-destination.json.template ^
        technijian\screenconnect-pull\state\teams-destination.json
   notepad technijian\screenconnect-pull\state\teams-destination.json
   ```
   Fields:
   - `team_id` - the group GUID from the Teams link
   - `channel_id` - the `19:...@thread.tacv2` id
   - `subfolder` - folder path to create inside the channel, supports tokens
     `{client_code}`, `{year}`, `{month}`, `{date}`. Default: `{client_code}/{year}-{month}`
   - `rename` - output filename pattern. Default: `{date}_{client_code}_{session_id}.mp4`

3. Verify resolution (dry-run, no upload):
   ```cmd
   C:\Python314\python.exe technijian\screenconnect-pull\scripts\upload_to_teams.py ^
       "C:\temp\sc-test\<one>.mp4" ^
       --vars client_code=TEST date=2026-04-29 session_id=smoketest --dry-run
   ```

4. Real upload:
   ```cmd
   C:\Python314\python.exe technijian\screenconnect-pull\scripts\upload_to_teams.py ^
       "C:\temp\sc-test\<one>.mp4" ^
       --vars client_code=BWH date=2026-04-29 session_id=abc123
   ```
   Check the Teams channel **Files** tab — the MP4 should be in the
   `{client_code}/{year}-{month}` subfolder and play inline in Teams.

## Upload from a conversion manifest (batch workflow)

```cmd
REM step 1: convert a directory and write a manifest
C:\Python314\python.exe technijian\screenconnect-pull\scripts\convert_recording.py ^
    "\\<sc-server>\recordings$\2026\04\<session>.crv" ^
    --output-dir "C:\converted\2026-04" --manifest "C:\converted\2026-04\manifest.json"

REM step 2: upload everything the manifest marks as ok=true
C:\Python314\python.exe technijian\screenconnect-pull\scripts\upload_to_teams.py ^
    --from-manifest "C:\converted\2026-04\manifest.json" ^
    --vars client_code=BWH year=2026 month=04
```

## Triage

- `ScreenConnect.RecordingConverter.exe not found` - SC isn't at any
  auto-detected path. Copy the `.exe` from the SC server or pass
  `--converter <path>`.
- `ffmpeg not found on PATH` - run `winget install Gyan.FFmpeg -e`, restart
  shell.
- `RecordingConverter exit <n>` - source `.crv` is corrupt or still being
  written (session in progress). Skip and retry later.
- `ffmpeg exit <n>` - usually a malformed `.avi`. Re-run with
  `--keep-intermediate` and inspect the `.avi` in VLC.
- `Teams destination config missing` - `state/teams-destination.json`
  doesn't exist or has placeholder values. See "Configure the Teams
  destination" above.
- `HTTP 403 Authorization_RequestDenied` on filesFolder - app registration
  missing `Group.Read.All` admin consent. Add in Entra ID -> Enterprise
  apps -> **Teams-Connector** -> API permissions -> grant admin consent.
- `HTTP 401` mid-upload - token expired during a large batch. Re-run the
  uploader; it skips already-uploaded files if you use the manifest and the
  file exists in Teams (Graph returns `409 nameAlreadyExists` with
  `conflictBehavior: fail`; switch to `replace` in the source if needed).

## SQLite MCP server (direct DB access from Claude Code)

ScreenConnect stores all its data in a **SQLite** file, not SQL Server.
The database lives on TE-DC-MYRMT-01 at a path like:

```text
C:\Program Files (x86)\ScreenConnect\App_Data\ScreenConnect.db
```

The `@modelcontextprotocol/server-sqlite` npm package gives Claude Code live
read access to that file via MCP tools (list tables, run a SELECT, etc.).
This is what powers the daily pull pipeline — Claude can query `Session`,
`SessionRecording`, `Audit`, etc. directly.

The config lives in `.mcp.json` at the repo root. **`.mcp.json` is gitignored**
so the file path is never committed.

### Step 1 — install Node.js (if not already on the workstation)

```powershell
winget install --id OpenJS.NodeJS.LTS -e
```

Verify: `node --version` and `npx --version`.

### Step 2 — share the ScreenConnect.db file (on TE-DC-MYRMT-01)

The MCP server needs a reachable path to `ScreenConnect.db`. Options:

**Option A — run Claude Code on TE-DC-MYRMT-01 itself**
Use the local path directly, e.g.:
`C:\Program Files (x86)\ScreenConnect\App_Data\ScreenConnect.db`

**Option B — map a UNC share from the workstation**
On TE-DC-MYRMT-01, share the `App_Data` folder (read-only, workstation
computer account or a service account). Then the path from the workstation is:
`\\10.100.14.10\SCAppData\ScreenConnect.db`

Also store the local path in the OneDrive key vault for Python scripts:

```text
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\screenconnect-sql.md
```

Format:

```markdown
# ScreenConnect Database
**DB Path:** \\10.100.14.10\SCAppData\ScreenConnect.db
```

`_sc_secrets.py:get_sc_db_path()` reads this for any Python script that
needs direct SQLite access.

### Step 3 — create .mcp.json from the template

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review
copy .mcp.json.template .mcp.json
notepad .mcp.json
```

Replace `\\10.100.14.10\<share>\App_Data\ScreenConnect.db` with the actual
path from Step 2.

### Step 4 — allow the MCP server in Claude Code

Open Claude Code in this repo. You will see a one-time prompt:
> "Allow MCP server 'screenconnect-db' from .mcp.json?"

Click **Allow**. The `mcp__screenconnect_db__*` tools will become available
(tools like `read_query`, `list_tables`, `describe_table`).

To pre-approve without the prompt (optional, for the production workstation):

```json
// add to .claude/settings.json (project)
"enabledMcpjsonServers": ["screenconnect-db"]
```

### Step 5 — verify

In a Claude Code session in this repo, ask:
> "Use the screenconnect-db MCP server to list all tables."

You should see tables like: `Session`, `SessionEvent`, `SessionRecording`,
`Audit`, `User`, `Permission`, `SessionGroup`, `SecuritySetting`, etc.

### Note on write access

ScreenConnect holds a write lock on `ScreenConnect.db` while the service is
running. The SQLite MCP server is read-only by default — which is what we
want. Never write to the live database file.

## MyRMM / ManageEngine SQL Server MCP (TE-DC-MYRMM-SQL)

ManageEngine Endpoint Central Plus and MyRMM use a **SQL Server** instance on
TE-DC-MYRMM-SQL (10.100.13.11). The `myrmm-sql` entry in `.mcp.json` gives
Claude Code read access to that database.

### Setup

1. Create `.mcp.json` from the template (see above) and fill in the `myrmm-sql`
   connection string:

   | Placeholder | Replace with |
   | --- | --- |
   | `<sql-user>` | SQL login with `db_datareader` on the ManageEngine database |
   | `<sql-password>` | Password for that login |

   Store the connection string in the OneDrive key vault:

   ```text
   %USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\myrmm-sql.md
   ```

   Format:

   ```markdown
   # MyRMM SQL Server
   **Connection String:** Server=10.100.13.11,1433;Database=ManageEngine;User Id=<user>;Password=<pass>;TrustServerCertificate=true;Encrypt=true;
   ```

2. Allow the `myrmm-sql` MCP server in Claude Code (one-time prompt on next
   session start after creating `.mcp.json`).

3. Verify:
   > "Use the myrmm-sql MCP server to list all tables."

## What is NOT in this build yet

- **Daily pull pipeline.** The SQL query (`SessionRecording` table) -> per-
  client routing -> convert -> upload chain is a separate script that waits
  on two decisions: (a) the per-client routing key in this CW Control
  instance (session group? hostname prefix? custom property?); (b) the
  workstation that runs it. Schedule wiring will follow the same
  `Register-ScheduledTask` pattern as `umbrella-pull/workstation.md`.
- **Transcript / chat / command-history pull.** SQL-side data, separate
  pipeline.
- **Retention/cleanup.** The SC server keeps `.crv` files indefinitely.
  If you want auto-deletion of `.crv` after confirmed upload, that belongs
  in a separate gated pipeline (recommend-only first).