# Sophos Central Partner Hourly Pull + Alert Router — Workstation Setup

Per-machine setup playbook for the production workstation that runs the
`Technijian-HourlySophos` scheduled task. Mirrors the Huntress / CrowdStrike
patterns in this repo, with one twist: this pipeline writes to the Client
Portal API (creates client-billable tickets) and sends email via Microsoft
Graph (reminders to support@technijian.com). It is the first repo pipeline
that is NOT read-only.

DO NOT install this scheduled task on the development laptop. See
`memory/feedback_no_dev_box_schedules.md`.

## 1. Prereqs

- Windows 10/11 logged in as the workstation user (NOT SYSTEM — SYSTEM
  cannot read OneDrive-synced keyfiles).
- Python 3.11+ at `C:\Python314\python.exe` (matches the .cmd wrapper).
- OneDrive (Technijian tenant) signed in and syncing.
- Repo cloned to `c:\vscode\annual-client-review\annual-client-review`.
- Internet access to:
  - `https://id.sophos.com` + `https://api.central.sophos.com` + `https://api-us01.central.sophos.com`
  - `https://api-clientportal.technijian.com`
  - `https://login.microsoftonline.com` + `https://graph.microsoft.com`

## 2. Verify the keyvault state

All credentials are OneDrive-synced markdown files. Verify each is reachable
and parseable:

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM Sophos Central Partner (tenants + firewall inventory + events + alerts)
C:\Python314\python.exe -c "import sys; sys.path.insert(0, r'technijian\sophos-pull\scripts'); import sophos_api as s; print('partner:', s.whoami()['id'], 'tenants:', len(s.list_tenants()))"

REM Client Portal (DirID lookup + future ticket creation)
C:\Python314\python.exe -c "import sys; sys.path.insert(0, r'scripts\clientportal'); import cp_api; print('cp clients:', len(cp_api.get_active_clients()))"

REM M365 Graph (reminder emails to support@technijian.com)
C:\Python314\python.exe -c "import sys; sys.path.insert(0, r'technijian\tech-training\scripts'); import _secrets; t,c,s,m = _secrets.get_m365_credentials(); print('m365 tenant=', t, 'mailbox=', m)"
```

If any fails, see `keys\sophos.md`, `keys\client-portal.md`, `keys\m365-graph.md`
in the OneDrive vault.

## 3. First-run smoke tests

Map-only (no API writes, no per-client folders touched):

```cmd
C:\Python314\python.exe technijian\sophos-pull\scripts\pull_sophos_daily.py --map-only
```

Real pull (writes per-client snapshots):

```cmd
C:\Python314\python.exe technijian\sophos-pull\scripts\pull_sophos_daily.py
```

Router in REPORT mode (no CP writes, no emails — produces routing-plan.json):

```cmd
C:\Python314\python.exe technijian\sophos-pull\scripts\route_alerts.py
```

Inspect `technijian\sophos-pull\<YYYY-MM-DD>\routing-plan.json` to see what
the router would do under --apply.

## 4. Register the scheduled task — HOURLY

```cmd
schtasks /create ^
  /tn "Technijian-HourlySophos" ^
  /tr "c:\vscode\annual-client-review\annual-client-review\technijian\sophos-pull\run-hourly-sophos.cmd" ^
  /sc hourly ^
  /st 00:15 ^
  /ru "%USERNAME%" ^
  /it ^
  /rl LIMITED
```

In Task Scheduler GUI → Properties:

- **General → "Run only when user is logged on"** (required for OneDrive)
- **Settings → "Run task as soon as possible after a scheduled start is missed"**
- **Settings → "Stop the task if it runs longer than 30 minutes"**
- **Settings → "If the task is already running... Do not start a new instance"**

The :15-past-the-hour offset avoids contending with the daily skill slots
(01:00 Huntress, 02:00 Umbrella, 03:00 CrowdStrike, 04:00 Teramind).

## 5. Switch the router from REPORT to APPLY (gated)

The wrapper defaults to REPORT mode. Enabling APPLY is a deliberate,
two-condition switch:

1. **The CP ticket SP must be wired.** Until `cp_tickets.create_ticket`
   stops raising NotImplementedError, --apply mode will track state +
   send reminder emails but will NOT create real tickets. See
   `cp_tickets.py` module docstring for the wiring checklist.

2. **The user has explicitly approved going live.** APPLY mode creates
   billable tickets on the client's contract and sends production email.
   Do not flip this on speculatively.

Once both conditions are met, set the env var on the scheduled task:

- Task Scheduler → Properties → **Actions** → Edit the action →
  "Add arguments (optional)" stays empty
- **General → Properties** does not expose env vars; use a separate wrapper
  variant or edit `run-hourly-sophos.cmd` to set `set ROUTER_MODE=apply`.

Or run on demand with apply:

```cmd
set ROUTER_MODE=apply
c:\vscode\annual-client-review\annual-client-review\technijian\sophos-pull\run-hourly-sophos.cmd
```

## 6. Switch back to REPORT during incidents

If something goes wrong (duplicate tickets, wrong assignment, runaway emails):

```cmd
schtasks /change /tn "Technijian-HourlySophos" /disable
```

Or revert the wrapper's `ROUTER_MODE` env var to `report` (default). The
state file persists, so resuming APPLY later picks up where it left off.

## 7. Daily ops

- Daily run log (gitignored): `technijian\sophos-pull\state\run-<YYYY-MM-DD>.log`
- Per-run snapshots (committed): `technijian\sophos-pull\<YYYY-MM-DD>\`
- Routing plan (committed each run): `technijian\sophos-pull\<YYYY-MM-DD>\routing-plan.json`
- Persistent state (committed): `technijian\sophos-pull\state\alert-tickets.json`
- rsyslog tenant-map (regenerated each run): `technijian\sophos-pull\state\sophos-tenant-ipmap.{txt,json}`

To check what's currently tracked:

```cmd
C:\Python314\python.exe -c "import json; d=json.loads(open(r'technijian\sophos-pull\state\alert-tickets.json').read()); a=d.get('alerts',{}); print(f'tracked={len(a)} pending_create={sum(1 for v in a.values() if not v.get(\"ticket_id\"))}')"
```

## 8. rsyslog tenant-map handoff

The hourly wrapper auto-regenerates `state\sophos-tenant-ipmap.json` from
the live firewall inventory. To deliver to the receiver in the DC:

```cmd
scp ^
  c:\vscode\annual-client-review\annual-client-review\technijian\sophos-pull\state\sophos-tenant-ipmap.json ^
  rjain@siem-ingest.technijian.com:/etc/rsyslog.d/sophos/tenant-map.json
ssh rjain@siem-ingest.technijian.com "sudo systemctl reload rsyslog"
```

## 9. Decommission

```cmd
schtasks /delete /tn "Technijian-HourlySophos" /f
```
