---
name: veeam-one-pull
description: "Use when the user asks to pull from Veeam ONE — backup configuration, repository (storage) capacity & state, alarm catalog, or to discover/probe new endpoints on the Veeam ONE 13 REST API at TE-DC-VONE-01. Also handles the per-hosted-client fan-out (writing under clients/<code>/veeam-one/<date>/). Reads creds from the OneDrive key vault, handles JWT auth + refresh. Examples: \"pull veeam one backup config\", \"snapshot veeam repos and free space\", \"check veeam alarm posture\", \"refresh veeam one data for the annual review\", \"fan out per client\", \"explore veeam one rest api endpoints\"."
---

# Veeam ONE 13 REST Pull

The Veeam ONE Reporting Service (v13.0.1.6168, on **TE-DC-VONE-01 / 10.7.9.135**)
exposes a JWT-authenticated REST API on **TCP/1239**. The on-box "Reporter" surface
is the only REST surface in v13 — there is no separate Monitor REST endpoint.

Credentials live in the key vault at:

```
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\veeam-one.md
```

Reusable Python module: `scripts/veeam-one/veeam_one_api.py`
Pipeline scripts: `scripts/veeam-one/pull_*.py`
Repo root: `c:/VSCode/annual-client-review/annual-client-review-1`

## Auth flow

```python
import veeam_one_api as v
v.whoami()                  # service info + token TTL
v.list_backup_servers()     # GET /api/v2.2/vbr/backupServers
v.list_repositories()       # GET /api/v2.2/vbr/repositories
v.list_alarm_templates()    # GET /api/v2.2/alarms/templates
```

The module reads credentials from env vars (`VONE_USERNAME` / `VONE_PASSWORD`)
when set, otherwise from the keyfile. Token is acquired on first call and
refreshed automatically before expiry (~15-min lifetime).

**Username MUST be in `DOMAIN\User` format.** Plain `Administrator` returns 400
with `Please specify credentials in the DOMAIN\UserName or UserName@UPNSuffix
format`. The local-machine domain is `TE-DC-VONE-01` for this host.

## Daily one-shot

```bash
cd c:/VSCode/annual-client-review/annual-client-review-1/scripts/veeam-one
python pull_all.py                          # vbr + alarms + business view
python pull_all.py --skip-alarms            # vbr + bv only
python pull_all.py --date 2026-05-01        # backfill date stamp
```

Per-component scripts:

```bash
python pull_vbr.py            # backup servers, repositories, SOBR, agents, summary
python pull_alarms.py         # alarm templates + counts by object type
python pull_business_view.py  # categories + groups
python explore.py             # probe full discovery list — see what's exposed today
python explore.py --shape vbr/repositories    # GET + dump body for one path

# AFTER pull_all.py: fan global data out per hosted client
python fan_out_clients.py                  # all clients with bkp_<CODE>/DS-NBD1-<CODE>
python fan_out_clients.py --only vaf,orx   # restrict
```

The fan-out script reads `clients/_veeam_one/<date>/` and writes to
`clients/<code>/veeam-one/<date>/` for every code that has a `bkp_<CODE>`
repository OR `DS-NBD1-<CODE>` BV group. Output per client:
`repository.json`, `business_view.json`, `backup_summary.json` (rolled-up
KPIs: capacity_human, free_human, used_percent, runway_days_min).

## Output structure

Veeam ONE has no native client-org concept — it monitors the entire VMware
estate as one. Output lands in a cross-org log folder:

```
clients/_veeam_one/<YYYY-MM-DD>/
  backup_servers.json              # VBR servers (id, version, connection, BPC status)
  repositories.json                # all repos: capacity, free, runningTasks, outOfSpaceInDays, isImmutable, path
  scaleout_repositories.json       # SOBR (empty in current install)
  agents.json                      # Veeam ONE Agent state per VBR server
  alarm_templates.json             # 524 alarm definitions (knowledge base, severity, scope)
  alarm_summary.json               # rollup: count by object type, enabled/disabled
  business_view_categories.json    # 9 categories (SLA, Storage Type, Last Backup, VM Location, ...)
  business_view_groups.json        # 28 groups (Mission Critical, DS-NBD1-<CODE>, ...)
  backup_summary.json              # rolled-up KPIs: total cap, free %, repos <30d runway, immutable count
```

## Per-client mapping (current install)

The Veeam install identifies clients via repo name `bkp_<CODE>` and
business-view group `DS-NBD1-<CODE>`. Current mapping:

| Repo            | Path                       | CP code     | Notes |
|-----------------|----------------------------|-------------|-------|
| `bkp_TOR`       | nfs3://10.7.9.230:/bkp_TOR | `tor`       | |
| `bkp_TECH`      | nfs3://10.7.9.230:/bkp_TECH| `technijian`| largest (60 TB) |
| `bkp_FOR`       | nfs3://10.7.9.230:/bkp_FOR | `for`       | |
| `bkp_VG`        | nfs3://10.7.9.225:/bkp_VG  | `vg`        | |
| `bkp_ORX`       | nfs3://10.7.9.225:/bkp_ORX | `orx`       | |
| `bkp_RFPS`      | nfs3://10.7.9.230:/bkp_RFPS| (no folder) | not yet onboarded |
| `bkp_VAF`       | nfs3://10.7.9.225:/bkp_VAF | `vaf`       | |
| `bkp_CCC`       | nfs3://10.7.9.225:/bkp_CCC | `ccc`       | |
| `bkp_CSS`       | nfs3://10.7.9.230:/bkp_CSS | `css`       | |
| `Default Backup Repository` | `C:\Backup`    | (system)    | |

BV groups also reference `MAX` (datastore-only — no separate Veeam repo
yet — runs on shared storage). Check business_view_groups.json for the
authoritative list each pull.

## REST endpoint surface (Veeam ONE 13.0.1.6168, port 1239)

### ✅ Confirmed working

| Endpoint | Returns |
|---|---|
| `GET /api/v2.2/about` | service name, version, machine, log path |
| `GET /api/v2.2/license` | rental info, instances, expiration, partner ID |
| `GET /api/v2.2/agents` | Veeam ONE Agent state per VBR server (log analyzer, remediation flags) |
| `GET /api/v2.2/alarms/templates` | all alarm definitions (~524: knowledge base, severity, isEnabled, assignments) |
| `GET /api/v2.2/businessView/categories` | BV categories per object type |
| `GET /api/v2.2/businessView/groups` | BV groups (Mission Critical, DS-NBD1-* per client, etc.) |
| `GET /api/v2.2/vbr/backupServers` | VBR servers (version, platform, connection, configuration backup, BPC) |
| `GET /api/v2.2/vbr/repositories` | repos with **live capacity, free, runningTasks, outOfSpaceInDays, isImmutable** |
| `GET /api/v2.2/vbr/scaleOutRepositories` | SOBR (empty in current install) |
| `POST /api/v2.2/reports` | execute predefined report by `templateId` (returns tabular data) |
| `POST /api/token` | get/refresh JWT — form-encoded, DOMAIN\User format |

### ❌ Confirmed NOT exposed (404 in v13.0.1.6168)

The Reporter REST surface deliberately does **not** expose live inventory or
per-VM data as direct list endpoints. These all return 404:

`/api/v2.2/vms`, `/api/v2.2/inventory/vms|hosts|datastores`,
`/api/v2.2/alarms` (the active list), `/api/v2.2/alarms/triggered`,
`/api/v2.2/alarms/active`, `/api/v2.2/events`, `/api/v2.2/users`,
`/api/v2.2/vbr/jobs`, `/api/v2.2/vbr/sessions`, `/api/v2.2/vbr/proxies`,
`/api/v2.2/vbr/protectedVMs`, `/api/v2.2/topology/vms`,
`/api/v2.2/monitoring/vms`, `/api/v2.2/license/usage`,
`/api/v2.2/remedies`, `/api/v2.2/loganalyzer`, `/api/v2.2/telemetry/usage`.

Re-probe with `python explore.py` after each Veeam ONE service-pack to catch
new endpoints — the canonical probe list lives in `explore.py:DEFAULT_PROBES`.

### How to get VM perf, triggered alarms, and backup-job history

Three options, in order of effort:

1. **Predefined reports (REST `/reports` POST)** — The Veeam ONE Web UI
   ships ~200 predefined reports (e.g. "VM Configuration", "Datastore
   Performance", "Alarms Active in the Last 24h"). Each has a numeric
   `templateId` discoverable via the Web UI under **Workspace → Reports**.
   Build the JSON payload as `{Name, ParentId, ReportTemplateId, Parameters: [...]}`
   and POST. Returns tabular data ready for downstream report generation.
   *Status: scaffolded but not wired — extend pull_vbr.py once the right
   templateIds are catalogued from the UI.*

2. **vCenter REST (already have a skill)** — For per-VM inventory + perf
   counters, the `vcenter-rest` skill against vCenter 172.16.9.252 is the
   canonical path. Veeam ONE just monitors the same vCenter — go to source.

3. **SQL data warehouse (last resort)** — The Reporter SQL DW on the Veeam
   ONE backend has every metric Veeam captures, including history. Schema
   is documented in Veeam's data model PDF; not currently wired.

## Programmatic use

```python
import sys
sys.path.insert(0, r"c:/VSCode/annual-client-review/annual-client-review-1/scripts/veeam-one")
import veeam_one_api as v

repos = v.list_repositories()
risky = [r for r in repos if (r.get("outOfSpaceInDays") or 9999) < 30]
print([(r["name"], r["outOfSpaceInDays"]) for r in risky])

# raw access for ad-hoc paths discovered later
result = v.get("vbr/scaleOutRepositories", params={"Limit": 100}, allow_404=True)
```

`v.get(path, params=, allow_403=True, allow_404=True)` returns `None` on
4xx-tolerant errors. `v.list_paged(path)` auto-follows Limit/Offset
pagination until exhausted.

## Auth gotchas

- **DOMAIN\\User is mandatory** for `/api/token`. Bare `Administrator`
  → 400. The keyfile already has the right format; don't strip the prefix.
- The vault's username uses backslash-escape (`TE-DC-VONE-01\\Administrator`)
  in markdown; `_read_keyfile()` un-escapes to a single `\` before sending.
- Token TTL is ~15 min. The client checks expiry before each call and
  refreshes via `grant_type=refresh_token`. If the refresh token has also
  expired the client re-logs in transparently.
- Cert is self-signed → `verify=False`. The `urllib3` insecure-request
  warnings are silenced at module import.

## Discovery / re-probe workflow

When a Veeam ONE patch lands or you suspect new endpoints:

```bash
python explore.py                                # run the canonical probe list
python explore.py vbr/jobs vbr/sessions          # probe specific guesses
python explore.py --shape vbr/repositories       # GET single + dump 4KB body
```

If a probe returns 200 and isn't in `veeam_one_api.py`, add a typed helper:

```python
# in veeam_one_api.py
def list_vbr_jobs() -> list[dict]:
    return list_paged("vbr/jobs")
```

…and update the SKILL.md endpoint surface table.

## Related: vcenter-rest skill

For per-VM inventory and performance, prefer the existing `vcenter-rest`
skill (vCenter at 172.16.9.252) — it's the source-of-truth that Veeam ONE
itself reads from. This skill's job is the *backup posture* layer.

<!-- ticket-management-note: cp-ticket-management -->

## Ticket management

If this skill ever needs to open a CP ticket for an issue it detects
(capacity warning, threshold breach, persistent failure), use the
tracked wrapper from the **cp-ticket-management** skill —
`cp_tickets.create_ticket_for_code_tracked(...)` in
`scripts/clientportal/cp_tickets.py`. The central state file at
`state/cp_tickets.json` deduplicates on `issue_key`
(convention: `<source-skill>:<issue-type>:<resource-id>`) and
`scripts/clientportal/ticket_monitor.py check` (daily 06:00 PT on the
production workstation) sends 24h reminder emails to
support@technijian.com for any open ticket. **Don't call
`cp_tickets.create_ticket(...)` directly** — the raw call bypasses
state and reminders.
