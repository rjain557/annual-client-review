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

## Locate the .crv files

Default SC server paths (the actual root is set by `<add key="AppData" .../>`
in `web.config` in the SC install dir):

```
C:\Program Files (x86)\ScreenConnect\App_Data\Session Recordings\<YYYY>\<MM>\<sessionGuid>.crv
C:\ProgramData\ScreenConnect\App_Data\Session Recordings\<YYYY>\<MM>\<sessionGuid>.crv
```

List them from the SC server:
```powershell
Get-ChildItem "C:\Program Files (x86)\ScreenConnect\App_Data\Session Recordings" `
    -Recurse -Filter *.crv | Select-Object FullName, Length, LastWriteTime
```

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
  apps -> HiringPipeline-Automation -> API permissions -> grant admin consent.
- `HTTP 401` mid-upload - token expired during a large batch. Re-run the
  uploader; it skips already-uploaded files if you use the manifest and the
  file exists in Teams (Graph returns `409 nameAlreadyExists` with
  `conflictBehavior: fail`; switch to `replace` in the source if needed).

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