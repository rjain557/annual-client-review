# Workstation setup - Daily Cisco Umbrella pull

The daily Umbrella pull is wired to a Windows Scheduled Task on the production
workstation. **Do not install the task on the development laptop.** This file
documents the manual install steps for the production box; nothing here gets
auto-installed.

## Prerequisites

1. Python 3.14 at `C:\Python314\python.exe` (matches `huntress-pull`,
   `monthly-pull`, `weekly-audit` schedules).
2. Repo cloned at `c:\vscode\annual-client-review\annual-client-review`.
3. OneDrive sync active for the `Technijian, Inc` tenant so the keyfile at
   `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\cisco-umbrella.md`
   is present.
4. Both `**API Key:**` and `**API Secret:**` lines in that keyfile must
   contain the live values (no `TODO` placeholders). Cisco Umbrella shows the
   Secret exactly once when the key pair is created in
   `Umbrella Dashboard -> Admin -> API Keys -> Create Key`. If the secret was
   lost, revoke the existing key and generate a new pair.
5. Client Portal credentials at
   `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\client-portal.md`
   (same path used by `cp_api.py`). The pull script needs them to resolve
   active client LocationCodes.

## Verify the credentials work

```cmd
cd c:\vscode\annual-client-review\annual-client-review
C:\Python314\python.exe -c "import sys; sys.path.insert(0, r'technijian\umbrella-pull\scripts'); import umbrella_api as u; print('token_len:', len(u.get_token())); print('users:', len(u.list_users()))"
```

A clean run prints a token length (~5780 chars for a JWT) and the user count
for the parent Umbrella org. A `RuntimeError` containing
`Cisco Umbrella credentials not found` means the keyfile is missing or both
fields are still blank/TODO. A `401` from any endpoint means the key/secret
pair is wrong, revoked, or expired.

## Smoke test

```cmd
cd c:\vscode\annual-client-review\annual-client-review

REM print the hostname-prefix -> LocationCode mapping the pull would use,
REM no per-client API calls (no activity sample either)
C:\Python314\python.exe technijian\umbrella-pull\scripts\pull_umbrella_daily.py --map-only

REM full run for one client (writes clients\vaf\umbrella\<YYYY-MM-DD>\)
C:\Python314\python.exe technijian\umbrella-pull\scripts\pull_umbrella_daily.py --only VAF
```

After a successful single-client run there should be a directory at
`clients\vaf\umbrella\<YYYY-MM-DD>\` containing `roaming_computers.json`,
`roaming_computers.csv`, `internal_networks.json`, `sites.json`,
`activity_summary.json`, `top_destinations.json`, `blocked_threats.json`,
`pull_summary.json`.

## Install the scheduled task

Run as the workstation user (NOT SYSTEM - OneDrive paths must resolve), in an
elevated PowerShell:

```powershell
$action  = New-ScheduledTaskAction -Execute "c:\vscode\annual-client-review\annual-client-review\technijian\umbrella-pull\run-daily-umbrella.cmd"
$trigger = New-ScheduledTaskTrigger -Daily -At 2:00am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest

Register-ScheduledTask -TaskName "Technijian-DailyUmbrellaPull" `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Daily 2 AM PT pull of last 24h Cisco Umbrella data per active client. See technijian/umbrella-pull/workstation.md."
```

**Cadence rationale:** 2:00 AM PT runs **after** the 1:00 AM Huntress pull
(`Technijian-DailyHuntressPull`) and **before** the 7:00 AM monthly-pull /
Friday weekly-audit. This avoids API/DB contention. The activity sample
(/reports/v2/activity, capped at 5000 records) is the most expensive call
per run; budgeting one hour is plenty.

To remove later:

```powershell
Unregister-ScheduledTask -TaskName "Technijian-DailyUmbrellaPull" -Confirm:$false
```

## Per-day artifacts

After a 2 AM run completes:

- `clients\<code>\umbrella\<YYYY-MM-DD>\` for every mapped client (currently
  just VAF until additional clients are mapped via
  `state/umbrella-prefix-mapping.json`).
- `technijian\umbrella-pull\<YYYY-MM-DD>\` with the account-level summary,
  full deployment inventory, mapping resolution, activity sample, and run
  log.
- `technijian\umbrella-pull\state\<YYYY-MM-DD>.json` - the same run log,
  surfaced where the other Technijian schedules write their state.
- `technijian\umbrella-pull\state\run-<YYYY-MM-DD>.log` - stdout/stderr from
  the cmd wrapper.

## Triage

- `unmapped.json` non-empty -> a hostname-prefix has no CP `LocationCode`
  match. Either add an entry to `state/umbrella-prefix-mapping.json`'s
  `manual` block (`"<PREFIX>": "<LOCATIONCODE>"`) or add the prefix to
  `ignore` if it should never produce a per-client folder (e.g. `DESKTOP-*`
  default Windows hostnames).
- `401 Missing or invalid credentials` from any endpoint -> the API Key /
  Secret was rotated. Refresh the keyfile and rerun the smoke test.
- A particular client's `pull_summary.json` has entries in `errors[]` but the
  rest of the run succeeded -> partial failure for that client. The other
  artifacts captured what was reachable. Re-run with `--only <CODE>` once the
  underlying issue is resolved.
- `activity sample failed: HTTP 400 invalid timestamp` -> the activity
  endpoint expects Unix-millis or relative time (`-24hours`, `now`), not
  ISO. The `umbrella_api.py` helper auto-converts ISO; if you see this, the
  conversion logic regressed.
- `pulled 5000 activity records (sample)` and the count is exactly 5000 ->
  the cap is hit. The 24h window had more than 5000 events; the per-client
  rollups are still accurate for the events sampled but a downstream
  consumer doing month aggregation should walk activity in 1-hour chunks
  rather than relying on the daily snapshot.

## Backfilling history (one-time)

Cisco Umbrella's `/reports/v2/activity` retention is **~90 days** for
Technijian's plan (verified 2026-04-29: data available back to ~2026-01-30,
nothing older). Snapshot data (roaming computers, sites, internal networks,
destination lists) does **not** have a per-day history at all - the API only
returns the current state.

### API hard limits (verified 2026-04-29)

| Limit | Value | Implication |
|---|---|---|
| `/reports/v2/activity` page_limit | <= 5000 | bigger pages cut API calls 4-5x; HTTP 400 if you exceed |
| `/reports/v2/activity` offset | <= 10000 | hard cap of 10K records per (from, to) window |
| Activity retention | ~90 days | older windows return [] silently |

Walking raw activity for a busy day means the offset cap kicks in around
hour 2 - meaning 24h windows cap out at 240K records and busy hours alone
exceed the cap. **Aggregation endpoints are the right tool for backfill.**

### Aggregations vs raw

`backfill_umbrella.py --mode aggregations` (default) calls:
- `/reports/v2/top-identities?limit=1000` (one call/day, ~0.3s)
- `/reports/v2/top-threats?limit=1000` (one call/day, ~0.2s)
- `/reports/v2/requests-by-hour` (one call/day, ~0.3s)
- `/reports/v2/categories-by-hour` (one call/day, ~0.5s)
- `/reports/v2/activity?verdict=blocked` (small subset, capped at 10K)

Total = ~5-10s per day per client. **VAF 90-day backfill in ~15 min.**

`--mode raw` would walk activity in 1h chunks and is reserved for forensic
deep-dives of small ranges (not implemented in this build; use the daily
pull with `--date YYYY-MM-DD` for a 5000-record raw sample of a single
historical day).

### How to run

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM full available retention for one client (~90 days, aggregations)
C:\Python314\python.exe technijian\umbrella-pull\scripts\backfill_umbrella.py --start 2026-01-30 --end 2026-04-28 --only VAF

REM dry-run plan (no API calls)
C:\Python314\python.exe technijian\umbrella-pull\scripts\backfill_umbrella.py --start 2026-01-30 --end 2026-04-28 --only VAF --dry-run

REM include empty days (clients with 0 events in the day)
C:\Python314\python.exe technijian\umbrella-pull\scripts\backfill_umbrella.py --start 2026-04-01 --end 2026-04-28 --only VAF --include-empty-days
```

The master log lands at
`technijian\umbrella-pull\state\backfill-<start>-to-<end>.json` with one
entry per day. Per-day run logs at
`technijian\umbrella-pull\<YYYY-MM-DD>\run_log.json` use
`"mode": "backfill"` and `"data_source": "aggregations"`.

### Per-client artifacts written by backfill

```
clients/<code>/umbrella/YYYY-MM-DD/
  roaming_computers.json/csv  current snapshot, filtered to prefix
  internal_networks.json      current snapshot
  sites.json                  current snapshot
  top_identities.json         this client's identities by request count (day)
  top_threats.json            top blocked threats touching client identities
  blocked_threats.json        raw blocked-verdict activity for client identities
  top_destinations.json       top blocked destinations for the client (day)
  activity_summary.json       org-wide hourly curve + per-client request total
  requests_by_hour.json       org-wide hourly curve (separate file)
  pull_summary.json           mode=backfill, data_source=aggregations
```

Caveats:
- `client_requests_total` in pull_summary is the SUM of requests across the
  client's identities found in the org-wide top-1000. If a client has more
  than 1000 identities or any fall outside the top-1000, this undercounts.
  For VAF (52 agents), this is not an issue.
- `requests_by_hour` and `categories_by_hour` are **org-wide**. There is no
  per-identity hourly breakdown in the aggregation endpoints.
- Inventory (roaming computers, sites, networks, destination lists) is the
  CURRENT state, written into every backfilled day's folder. The
  `inventory_snapshot_at` field timestamps the snapshot.

This is on-demand only - **no scheduled task for the backfill**. Re-run when
a fresh client onboards onto Umbrella, or to refresh inventory after a
significant fleet change.

## What to do next

- After a few daily runs, review `unmapped.json` and add manual prefix
  overrides for any client whose Umbrella hostnames don't share a prefix
  with their CP LocationCode (e.g. if BWH agents register as `BWHFD-*`).
- When more clients onboard onto Umbrella, their hostname prefixes will
  appear in `unmapped.json` until mapped - this is the correct human-in-the-
  loop signal.
- This skill is read-only. Do **not** wire any of the write/POST endpoints
  (creating policies, updating destination lists, etc.) without explicit
  re-approval - policy changes belong in the Umbrella Dashboard or a
  separate change-managed pipeline, not the data-capture layer.
