---
name: veeam-365-pull
description: "Use when the user asks to pull or query data from Veeam Backup for Microsoft 365 (VB365) — list protected tenants/organizations, count users being backed up, see per-user backup coverage (mailbox/OneDrive), break down backup storage per M365 module (Exchange/OneDrive/SharePoint/Teams), build branded monthly Word reports per client with 3/6/9/12-month storage trend projections, sum used backup size per tenant, inspect backup repositories or jobs, or run any other VB365 REST endpoint. The on-prem VB365 server lives at https://10.7.9.227:4443 with self-signed TLS; auth is OAuth2 password grant against /v8/token; credentials in the keys vault. Examples: \"pull veeam 365 tenant summary\", \"build veeam 365 monthly reports\", \"how many M365 users are we backing up\", \"how big is each veeam 365 tenant per module\", \"project veeam 365 storage out 12 months\", \"list veeam 365 backup repos\", \"what's the lastRun of every VB365 job\"."
---

# Veeam Backup for Microsoft 365 (VB365) REST Pull

The on-prem **Veeam Backup for Microsoft 365** server protects multiple
client M365 tenants from Technijian's datacenter. The REST API is at
`https://10.7.9.227:4443` (self-signed cert), OAuth2 password grant, base
path `/v8/`. Credentials live in the keys vault:

```
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\veeam-365.md
```

Reusable Python module: `scripts/veeam-365/veeam_client.py`
Pipelines (in build order):
  - `scripts/veeam-365/pull_tenant_summary.py` — quick per-tenant rollup (totals only)
  - `scripts/veeam-365/pull_full.py` — daily snapshot + per-user OneDrive coverage + per-module attribution
  - `scripts/veeam-365/build_monthly_report.py` — per-tenant DOCX with trend projections
  - `scripts/veeam-365/file_capacity_tickets.py` — opens CP tickets to CHD : TS1 for capacity / job-warning issues found in the latest snapshot (one ticket per issue, full step-by-step remediation in the body)
Tenant→client mapping: `scripts/veeam-365/_tenant_mapping.py`
(repo root: `c:/VSCode/annual-client-review/annual-client-review-1`)

## Auth flow

```python
from veeam_client import VeeamClient
c = VeeamClient()              # reads host/user/pwd from keys vault
c.get('/Organizations')        # leading-slash path, version auto-prefixed
c.get_paginated('/Organizations')  # iterates HAL `next` then offset bumps
```

The client probes `/v8 → /v7 → /v6 → /v5` on first call and caches the
working version. **Verified 2026-05-02: server speaks both /v8 and /v7
(it returns /v7 next-link URLs even on /v8 sessions — the client handles
that).**

Token lifetime ~24h; refreshed proactively at 90% of expires_in. All
requests run with `verify=False` (urllib3 InsecureRequestWarning is
suppressed at module load).

## Quick smoke test

```bash
cd c:/VSCode/annual-client-review/annual-client-review-1/scripts/veeam-365

# auth check + working API version
python veeam_client.py
# → OK  api_version=v8  base=https://10.7.9.227:4443

# raw GET any endpoint (PowerShell — git bash mangles leading slash)
python veeam_client.py /Organizations
python veeam_client.py /BackupRepositories
python veeam_client.py /Jobs
```

## Daily one-shot

```bash
# quick — totals + user counts only (csv + json + console table)
python pull_tenant_summary.py
python pull_tenant_summary.py --skip-users        # 10× faster (no user-count pagination)
python pull_tenant_summary.py --only JDH,BWH      # restrict by tenant name

# full — also writes per-tenant feeds + dated snapshot + per-module attribution
python pull_full.py                               # ~3 min for all 8 tenants (probes /onedrives per user)
python pull_full.py --skip-user-onedrives         # 10× faster; no OneDrive coverage flag per user
python pull_full.py --only JDH,BWH
```

## Monthly report

After `pull_full.py` has populated `clients/<slug>/veeam-365/<date>/data.json`:

```bash
python build_monthly_report.py                    # all tenants, this month
python build_monthly_report.py --month 2026-04
python build_monthly_report.py --only JDH,BWH
```

Each report passes through `proofread_docx.py` (8/8 checks) before delivery.
**Verified 2026-05-02:** all 8 tenant reports built and proofread cleanly.

## Capacity / job-warning tickets

`file_capacity_tickets.py` reads `clients/_veeam_365/tenant_summary.json`,
spots issues, and opens one CP ticket per issue against the affected
client's contract — assigned to **CHD : TS1** (DirID 205), India tech
support — with full step-by-step remediation in the body.

```bash
python file_capacity_tickets.py --dry-run          # build XML only, no API call
python file_capacity_tickets.py                    # file the tickets
```

The ticket bodies include:
- repository name, path, used / capacity / free bytes
- the M365 tenant + user count affected
- step-by-step RDP-and-fix instructions (extend volume vs add new repo)
- the verification command (`python pull_full.py --only <CODE>`)
- a "reply with" checklist for the assigned tech

**Filed 2026-05-02 — 4 tickets opened, all to CHD : TS1:**

| Ticket | Client | Priority | Issue key |
|---|---|---|---|
| **#1452721** | AFFG | 1255 Same Day | `veeam-365:repo-capacity:AFFG-O365` |
| **#1452722** | Technijian | 1256 Next Day | `veeam-365:repo-capacity:TECH-O365` |
| **#1452723** | ALG | 1255 Same Day | `veeam-365:repo-capacity-and-warning:ALG-O365` |
| **#1452724** | ORX | 1256 Next Day | `veeam-365:migration-cleanup:ORX` |

**Idempotency** — `file_capacity_tickets.py` uses
`cp_tickets.create_ticket_for_code_tracked()` (the cp-ticket-management
skill). Re-running it will SKIP any ticket whose `issue_key` is already
in `state/cp_tickets.json` and unresolved — no duplicate filings. To
mark one resolved (so the script CAN re-file the same issue if it
recurs):

```bash
python scripts/clientportal/ticket_monitor.py resolve 1452721 --note "extended to 5 TB"
```

**Reminders** — `cp-ticket-management` will email
`support@technijian.com` every 24h while these tickets stay open. Set
up the monitor schedule via the `cp-ticket-management` skill.

## Output

```
clients/_veeam_365/
  tenant_summary.json                          # latest pull_full output (every tenant in one file)
  snapshots/<YYYY-MM-DD>.json                  # dated snapshot — feeds the trend projection
  internal/<date>/data.json                    # per-tenant feed (Technijian internal only)
  internal/reports/                            # Technijian internal monthly reports

clients/<slug>/veeam-365/
  <YYYY-MM-DD>/data.json                       # per-tenant per-day feed
  reports/<Tenant> - Veeam 365 Monthly - YYYY-MM.docx
```

## Per-tenant feed shape (data.json)

```jsonc
{
  "id": "<vb365-org-id>", "name": "BWH", "displayName": "Brandywine Homes",
  "clientSlug": "bwh", "officeName": "brandywinehomes.onmicrosoft.com",
  "msid": "<azure-tenant-id>",
  "services": { "exchange": true, "sharepoint": true, "teams": true, "teamsChats": true },
  "userCount": 115,
  "onedriveCoveredUserCount": 68,
  "totals": { "usedSpaceBytes": 5234567890123, "localCacheUsedSpaceBytes": 0,
              "objectStorageUsedSpaceBytes": 0 },
  "repositories": [{ "repositoryName": "BWH-O365", "usedSpaceBytes": ..., "capacityBytes": ..., ...}],
  "jobs":         [{ "name": "BWH-O365", "backupType": "EntireOrganization",
                     "lastRun": "...", "lastStatus": "Success", "isEnabled": true }],
  "modules": {
    "Exchange":   { "estimatedBytes": 3120000000000, "estimatedShare": 0.596,
                    "rpFlagCount": 475, "rpTotalCount": 496 },
    "OneDrive":   { ... }, "SharePoint": { ... }, "Teams": { ... }
  },
  "users": [
    { "id": "...", "displayName": "Jane Doe", "email": "jane@brandywine-homes.com",
      "hasMailbox": true, "hasOneDrive": true, "userType": "User", ... },
    ...
  ]
}
```

## Per-module attribution method

REST does **not** expose per-mailbox / per-OneDrive byte counts on this build
(`/Mailboxes`, `/OneDrives`, `/RestorePoints/{id}/Mailboxes` all 404). The
puller derives per-module bytes by:

1. fetching every restore point in the trailing **90 days** via
   `/RestorePoints?backupTimeFrom=<iso>` (server-side filter, verified 2026-05-02)
2. counting how many of those RPs have each `isExchange`/`isOneDrive`/`isSharePoint`/`isTeams`
   flag set
3. weighting raw flag share by industry-default ratios (mail 55, OneDrive 25,
   SharePoint 15, Teams 5) and normalizing to 1
4. attributing the tenant's total `usedSpaceBytes` proportionally

The result is an **informed estimate**, not invoiced ground truth. The
report includes a callout flagging this. For per-user / per-team exact
sizes, use VB365 PowerShell `Get-VBOEntityData`.

## Trend projection

`build_monthly_report.py` reads every dated file under
`clients/_veeam_365/snapshots/` and looks for the matching tenant.

- **<2 snapshots** → projection uses **4% MoM compound** (industry default).
  Reports include a note that accuracy improves after 2+ monthly snapshots.
- **≥2 snapshots** → linear regression on `log(usedSpaceBytes)` vs months
  elapsed; growth rate = `exp(slope) - 1`. Reports apply that compound rate
  to project +3, +6, +9, +12 months. Trend chart (matplotlib PNG, embedded
  via python-docx) shows observed history + projected curve.

To get real history: schedule `pull_full.py` to run **once per month**
(e.g. on the 1st at 04:00 PT — same window as the other monthly pulls).
After 3 monthly snapshots the projection becomes data-driven.

Console prints a table sorted by used backup size:

```
  Tenant      M365 tenant                         Users     Backup size  Jobs  Backup types
  ----------  -------------------------------  --------  --------------  ----  ------------
  Technijian  Technijian365.onmicrosoft.com         297         6.01 TB     1  EntireOrganization
  BWH         brandywinehomes.onmicrosoft.com       115         4.76 TB     1  EntireOrganization
  ORX         ORX365.onmicrosoft.com                467         4.07 TB     1  EntireOrganization
  ...
  TOTAL (8)                                        1210        20.70 TB
```

Verified 2026-05-02 against live server: 8 tenants, 1,210 users, 20.70 TB.

## Tenants currently protected (verified 2026-05-02)

| Tenant code | M365 tenant | Job type | Notes |
|---|---|---|---|
| JDH        | JDHPac.onmicrosoft.com           | EntireOrganization | |
| BWH        | brandywinehomes.onmicrosoft.com  | EntireOrganization | |
| ALG        | NETORG672839.onmicrosoft.com     | EntireOrganization | |
| ORX        | ORX365.onmicrosoft.com           | EntireOrganization | |
| AFFG       | NETORGFT9014011.onmicrosoft.com  | EntireOrganization | |
| Technijian | Technijian365.onmicrosoft.com    | EntireOrganization | internal |
| ACU        | segco.onmicrosoft.com            | EntireOrganization | |
| CBI        | cbinteriorsdba.onmicrosoft.com   | EntireOrganization | |

All 8 jobs are `EntireOrganization` → `userCount` from the API equals the
count of M365 directory users that get backed up. If a future tenant runs
a `PartialOrganization` or `SelectedItems` job, the user count will need
to come from `/Jobs/{jobId}/SelectedItems` instead.

## Endpoint map

### Discovery / inventory
| Method | Path | Returns |
|---|---|---|
| POST | `/v8/token` | OAuth2 token (form-encoded body) |
| GET  | `/v8/Organizations` | all protected M365 tenants |
| GET  | `/v8/Organizations/{id}` | one tenant (verified by `_links` block lists per-org sub-resources) |
| GET  | `/v8/Organizations/{id}/users` | M365 directory users for a tenant (paginated; `eTag` per row) |
| GET  | `/v8/Organizations/{id}/groups` | groups |
| GET  | `/v8/Organizations/{id}/sites` | SharePoint sites |
| GET  | `/v8/Organizations/{id}/teams` | Teams |
| GET  | `/v8/Organizations/{id}/jobs` | jobs scoped to one tenant |
| GET  | `/v8/Organizations/{id}/usedRepositories` | per-tenant per-repo `usedSpaceBytes` + cache + object-storage bytes |
| GET  | `/v8/Organizations/{id}/rbacRoles` | RBAC role assignments |
| GET  | `/v8/BackupRepositories` | all repos w/ `capacityBytes`, `freeSpaceBytes`, retention policy, proxy |
| GET  | `/v8/BackupRepositories/{id}` | one repo |
| GET  | `/v8/Proxies` | backup proxies |
| GET  | `/v8/Jobs` | all backup jobs (organizationId + repositoryId per job, `lastRun`/`nextRun`/`lastStatus`) |
| GET  | `/v8/Jobs/{id}` | one job |
| GET  | `/v8/Jobs/{id}/SelectedItems` | what items the job selects (when `backupType != EntireOrganization`) |
| GET  | `/v8/Jobs/{id}/excludedItems` | exclusions |
| GET  | `/v8/Jobs/{id}/jobsessions` | execution history for a job |

### Useful for per-module / history work
| Method | Path | Returns |
|---|---|---|
| GET | `/v8/RestorePoints?backupTimeFrom=YYYY-MM-DDTHH:MM:SSZ` | filtered RP stream — has `isExchange`, `isOneDrive`, `isSharePoint`, `isTeams` boolean flags + `backupTime` + `organizationId` + `repositoryId` (no size field) |
| GET | `/v8/Organizations/{id}/users/{uid}/onedrives` | per-user OneDrive enumeration (returns ≥1 entry → user has OneDrive backed up) |
| GET | `/v8/JobSessions` | per-session statistics including `transferredDataBytes` (incremental data per run) |
| GET | `/v8/License` | license info |

### Confirmed NOT exposed (404 against this server, 2026-05-02)
- `/v8/Backups` (top-level)
- `/v8/Mailboxes` / `/v8/OneDrives` / `/v8/Sites` (global per-entity collections)
- `/v8/BackupRepositories/{id}/OrganizationUsers|OrganizationGroups|OrganizationSites|OrganizationTeams`
- `/v8/Organizations/{id}/Mailboxes` / `Backups` / `Statistics` / `protectionStatus`
- `/v8/Organizations/{id}/users/{uid}/mailbox` / `archiveMailbox`
- `/v8/RestorePoints/{id}/Mailboxes|OneDrives|Sites|Teams|Statistics|EntityData`
- `/v8/Jobs/{id}/Statistics`, `/v8/Jobs/{id}/jobsessions`
- `/v8/Reports`, `/v8/Explorers`, `/v8/ServerInfo`, `/v8/ServerSettings`

For backed-up entity sizes per user/site/team, use the PowerShell module
(`Get-VBOEntityData`) — the REST surface on this build does not expose it.

## Pagination

Standard form: `?limit=N&offset=M`. Default page size = 30, max safely
tested = 500. Response shape:

```json
{
  "offset": 0,
  "limit": 30,
  "_links": {
    "self": { "href": "/v8/Organizations?offset=0&limit=30" },
    "next": { "href": "/v8/Organizations?offset=30&limit=30" }   // only when more
  },
  "results": [ ... ]
}
```

`get_paginated()` follows `_links.next` when present, otherwise bumps
offset until `len(results) < limit`. **There is no `totalCount` field**
on the paginated endpoints — count by walking pages.

## Programmatic use

```python
import sys
sys.path.insert(0, r"c:/VSCode/annual-client-review/annual-client-review-1/scripts/veeam-365")
from veeam_client import VeeamClient

c = VeeamClient()
orgs  = c.list_organizations()
repos = c.list_backup_repositories()
jobs  = c.list_jobs()

# per-org used backup space
for o in orgs:
    used = c.get(f"/Organizations/{o['id']}/usedRepositories")
    total = sum(u["usedSpaceBytes"] for u in used["results"])
    print(o["name"], total)

# count backed-up users (when job is EntireOrganization)
for o in orgs:
    n = sum(1 for _ in c.get_paginated(f"/Organizations/{o['id']}/users", limit=500))
    print(o["name"], n)
```

## Gotchas

- **Self-signed cert.** Every request runs `verify=False`. Never copy the
  `verify=True` pattern from other projects without pinning the cert.
- **Server returns `/v7/` next-links on `/v8/` sessions.** The client's
  `_full_url` leaves any `/vN/` prefix alone — don't "normalize" it.
- **Git Bash mangles leading slashes.** `python veeam_client.py /Foo`
  becomes `python veeam_client.py C:/Program Files/Git/Foo`. Use
  PowerShell, or quote/escape (`"//Foo"`).
- **No `totalCount` field.** Pagination requires walking pages — don't
  try to short-circuit by reading a count from the first response.
- **`backupType` ≠ `SelectedItems` shape.** A job with
  `backupType=EntireOrganization` may still return a `SelectedItems`
  array of one `PartialOrganization` row covering all service categories
  (mailbox/oneDrive/sites/teams). Trust the job-level `backupType` field.
- **`/Backups` and `/Mailboxes` 404 on this build.** For per-user backup
  size, use the VB365 PowerShell module (`Get-VBOEntityData`), not REST.
- **Same Administrator account as veeam-one and veeam-vbr.** Three
  separate Veeam servers, three separate keys files; password is
  currently identical but they will diverge over time.

## Related: key vault

```
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\veeam-365.md
```

Contains host, credentials, full endpoint table, auth flow, and the
versions probed.

## Related: other Veeam keys

- `keys/veeam-one.md`  — Veeam ONE Reporter REST (port 1239) on TE-DC-VONE-01
- `keys/veeam-vbr.md`  — Veeam Backup & Replication (TE-DC-BK-VBR-01)
- `keys/veeam-365.md`  — **this skill** — VB365 REST on TE-DC-BK-365-01 / 10.7.9.227
