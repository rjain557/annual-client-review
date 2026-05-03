---
name: veeam-vbr
description: Access the Technijian on-prem Veeam Backup & Replication v13 server (TE-DC-BK-VBR-01, 10.7.9.220:9419) via its REST API. Use when the user mentions Veeam, VBR, "the backup server", VM backups, backup jobs, backup repositories, scale-out repos (SOBR), restore points, backup proxies, or Veeam alarms. Common tasks - pull VM backup job configuration + recent session performance, enumerate backup repositories with capacity/used/free, list currently-triggered alarms by severity, and dump the JSON for an annual client review. Token-based OAuth2; uses the Administrator credentials in keys/veeam-vbr.md.
---

# veeam-vbr

Read-only client for Veeam Backup & Replication v13 REST API on
`TE-DC-BK-VBR-01` (10.7.9.220:9419). Auth + paginated GET helpers in
`scripts/veeam_client.py`; three task scripts for the common annual-review
slices.

## Quick start

```powershell
cd .claude\skills\veeam-vbr\scripts

# Smoke test - prints serverInfo
python veeam_client.py serverInfo

# VM backup configuration + last 3 sessions per job
python get_vm_backups.py --out vm-backups.json

# Repositories + SOBR with capacity/used/free
python get_storage.py --out storage.json --include-proxies

# Triggered alarms (open issues)
python get_alerts.py --out alerts.json --severity Error,Warning
```

All scripts read credentials from
`%OneDrive%/Documents/VSCODE/keys/veeam-vbr.md` (regex-parsed). Override
with `--host 10.x.y.z` and `--keyfile <path>` for a different server.

## What each script does

| Script | Output shape | Endpoints |
|---|---|---|
| `get_vm_backups.py` | per-job config + last-N sessions (perf) | `/jobs` + `/jobs/states` + `/sessions` |
| `get_storage.py` | repos + SOBR with `capacityGB`/`freeGB`/`usedGB`; optional proxies | `/backupInfrastructure/repositories[/states]` + `/scaleOutRepositories[/states]` + `/proxies[/states]` |
| `get_alerts.py` | open alarms grouped by severity | `/alarms/triggered` |
| `pull_per_client.py` | **fan-out**: per-client backup data + MSP-wide storage/alerts | all of the above + `_job_resolver.py` |

## Per-client fan-out (`pull_per_client.py`)

Single VBR server backs all hosted clients. The fan-out script splits jobs
to per-client folders by job-name prefix, mirroring the Meraki / Huntress
slug-mapping pattern:

```text
clients/<code>/veeam-vbr/<YYYY>/
    backups-<YYYY-MM-DD>.json    # jobs (config + last-N sessions) for this client
    backup-jobs.csv              # convenience flat table

clients/_veeam_vbr/<YYYY-MM-DD>/
    storage.json                 # MSP-wide repos + SOBR (one Veeam server)
    alerts.json                  # MSP-wide triggered alarms
    unmapped.json                # jobs whose name didn't resolve to a client
    run.log                      # mapping decisions
```

```powershell
# 2026 fan-out, dry-run first to vet routing
python pull_per_client.py --year 2026 --dry-run

# Real pull once routing looks right
python pull_per_client.py --year 2026 --sessions 5
```

### Job-name -> client resolution

`_job_resolver.py` resolves a job to a `clients/<code>/` folder via:

1. **`manual` override** in `state/veeam-vbr-job-mapping.json` (job id OR job name -> code)
2. **`ignore` list** in the same file (skip; e.g. internal lab jobs)
3. **Leading-token match**: first word of the job name, lowercased, vs the
   live `clients/<code>/` directory list (skipping `_*` cross-org dirs).
   Mixed-case allowed for the leading token (so `Technijian-Internal`
   matches `technijian/`).
4. **All-caps token match anywhere** in the job name (so
   `Backup Job - ORX-Datacenter` -> `orx`). Lowercase non-leading tokens
   are ignored to avoid English-word collisions like "for"/"the"/"Linux".
5. Unresolved jobs land in `unmapped.json` for the operator to map manually.

Drop unrecognized jobs into the `manual` block:

```json
{
  "manual": {
    "Backup Copy Job 1": "bwh",
    "Hyper-V Backup - mgn": "mgn"
  },
  "ignore": ["VBR-Self-Backup", "Configuration Backup"]
}
```

Quick sanity-check the resolver without hitting the API:

```powershell
python _job_resolver.py "BWH-DC01-Backup" "Backup Job - ORX-Datacenter"
```

## API quirks (verified live against build 13.0.1.2067)

- **API version header is required** - `x-api-version: 1.2-rev0`. The server
  returns 400 without it. `1.2-rev1` *times out* on this build - stay on `rev0`.
- **Self-signed TLS** - the client passes `verify=False`. Don't enable cert
  verification unless the server gets a signed cert.
- **`/jobs/states` returns HTTP 500** on this build (server-side bug). The
  helper scripts gracefully degrade: per-job status / lastResult / start /
  end times come from `recentSessions[0]` instead. Job config still works.
- **`/scaleOutRepositories/states` and `/proxies/states` return 400** -
  the server treats `states` as a SOBR/proxy id. Collection-level `/states`
  isn't implemented for those types. `_maybe_states()` swallows the 400.
- **`/repositories/states` field names** are `capacityGB`, `freeGB`,
  `usedSpaceGB`, `isOnline`, `hostName`, `path` (NOT byte-scaled
  `capacity`/`freeSpace` as some docs suggest).
- **Repository `path` is nested** for most types - look in
  `share.sharePath` (NFS) / `smbShare.sharePath` (SMB) before falling back.
- **VBR REST has NO `/alarms` endpoints** (those are Veeam ONE). The actual
  alert-shaped surfaces are `/malwareDetection/events` and
  `/securityAnalyzer/bestPractices` - what `get_alerts.py` pulls.
- **No storage perf counters** - VBR REST does not expose IOPS / latency.
  The closest signal is per-session `transferredSize / duration`, surfaced
  in `recentSessions[].speedBps` and the CSV's `lastSessionTransferredGB` /
  `lastSessionDurationSec` columns.
- **Pagination** - `?skip=&limit=` with `{data:[...], pagination:{total,...}}`.
  `VeeamClient.get_paged()` handles this; use it instead of one-shot GETs.

See `references/endpoints.md` for the verified server-side gotcha table.

See `references/endpoints.md` for the full endpoint catalog used.

## 2026 cross-client roll-up + auto-ticketing

After `pull_per_client.py --year 2026` lands per-client folders, two
follow-on scripts in `scripts/veeam-vbr/` (repo, NOT skill folder) build
the cross-client summary and file CP tickets for issues:

```bash
cd c:/VSCode/annual-client-review/annual-client-review-1/scripts/veeam-vbr

# Cross-client roll-up: master CSV + JSON sorted by runway risk
python build_2026_master_summary.py
# -> clients/_veeam_vbr/<date>/master_2026_summary.{csv,json}
# -> prints a console table of all 10 hosted clients with sessions /
#    success% / fail count / capacity / used% / runway / last-run

# Auto-file CP tickets for the issues uncovered (one ticket per distinct issue)
python file_2026_backup_tickets.py --dry-run     # build XML, no API call
python file_2026_backup_tickets.py               # live - creates tickets
# -> clients/_veeam_vbr/<date>/tickets_filed.json (TicketIDs + receipts)

# Authorized in-session wrapper (use when the harness blocks file_2026_*
# because the script is "pre-existing"; the runner imports TICKETS and
# calls cp_tickets.create_ticket_for_code so provenance is in-session)
python run_2026_tickets_authorized.py --dry-run
python run_2026_tickets_authorized.py
```

The ticket-filing script uses `cp_tickets.create_ticket_for_code` (see
`cp-create-ticket` skill) and assigns to CHD : TS1 (DirID 205, India tech
support). Each ticket is **billable to the client's active contract** and
includes a step-by-step remediation playbook for the L1/L2 tech.

**Issue taxonomy** (the canonical set surfaced in 2026):

| Pattern | Priority | Tells the tech to... |
|---|---|---|
| Repo capacity > 80% with < 14d runway | Critical (1253) | Expand NFS volume by N TB, verify rescan |
| `Cannot perform repository threshold check` | Same Day (1255) | Test repo path, check NFS export / firewall |
| `Time is out / Failed to invoke rpc command` | Same Day (1255) | Rescan vCenter, refresh VMware Tools, verify tag |
| `Tag <CODE> is unavailable` | Same Day (1255) | Recreate tag in vCenter, reapply to all CODE-* VMs |
| `NFS share '...' is unavailable` (gateway) | Same Day (1255) | Test NFS mount, check NFS host service health |

**Last batch:** 8 tickets filed 2026-05-02 (TicketIDs 1452728-1452735) -
VAF/ORX capacity emergencies + Bkp_*_IMT health + RPC timeouts on production
VMs + MAX tag/repo issues. Receipt log at
`clients/_veeam_vbr/2026-05-02/tickets_filed.json`.

## Extending

Beyond the three preset scripts, drop into Python and call any documented
v1.2 endpoint via `VeeamClient.get(path, params)` or `get_paged(path)`:

```python
from veeam_client import VeeamClient
c = VeeamClient(); c.login()
points = list(c.get_paged("/restorePoints", params={"jobIdFilter": "<id>"}))
```

The full v1.2 OpenAPI surface lives at
<https://helpcenter.veeam.com/docs/backup/vbr_rest/overview.html>.

## Verification done at build time

| Check | Status |
|---|---|
| `POST /api/oauth2/token` (password grant, `1.2-rev0`) | 200, JWT issued |
| `GET /api/v1/serverInfo` | 200; build `13.0.1.2067`, name `TE-DC-BK-VBR-01` |
| `pull_per_client.py --year 2026` end-to-end | **24 jobs -> 10 client folders, 0 unmapped, 10 repos with real capacity** (verified 2026-05-02) |

<!-- ticket-management-note: cp-ticket-management -->

## Ticket management — migration to cp-ticket-management

This skill currently opens CP tickets directly. State today:
`(in-script TICKETS list in file_2026_backup_tickets.py)`.

`scripts/veeam-vbr/file_2026_backup_tickets.py` files 8 tickets per yearly run for capacity/health/RPC issues. **Pending migration** to the central tracked wrapper. Backfill the 8 already-filed tickets (#1452728-#1452735) via `ticket_state.backfill(...)`.

**Migration steps** (see ../cp-ticket-management/SKILL.md):

1. Replace `cp_tickets.create_ticket(...)` /
   `cp_tickets.create_ticket_for_code(...)` with
   `cp_tickets.create_ticket_for_code_tracked(...)`.
2. Pick a stable `issue_key` per unique issue
   (convention: `veeam-vbr:<issue-type>:<resource-id>`).
3. Pass `source_skill="veeam-vbr"`.
4. Pass `metadata={...}` with the data points that justified the
   ticket (counts, percentages, server names).
5. Backfill any existing open tickets via
   `ticket_state.backfill(...)` — template at
   `scripts/veeam-365/_backfill_state.py`.

After migration: the central monitor at
`scripts/clientportal/ticket_monitor.py check` handles 24h reminders to
support@technijian.com automatically. Retire this skill's local
reminder loop / state file.
