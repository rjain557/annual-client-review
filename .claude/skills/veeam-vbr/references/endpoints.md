# Veeam VBR REST v1.2 — Endpoint Reference

VBR v13 server `TE-DC-BK-VBR-01` (10.7.9.220:9419), API version `1.2-rev0`.
Read-only endpoints used by the helper scripts. Full surface at
<https://helpcenter.veeam.com/docs/backup/vbr_rest/overview.html>.

## Auth

```
POST /api/oauth2/token
Headers: x-api-version: 1.2-rev0
         Content-Type: application/x-www-form-urlencoded
Body:    grant_type=password&username=<u>&password=<p>
Returns: { access_token, refresh_token, expires_in, token_type: "Bearer" }
```

Use the JWT as `Authorization: Bearer <token>` on every subsequent call.
Token TTL is server-config dependent (~24h access, ~7d refresh).

## Pagination convention

Most list endpoints accept `?skip=N&limit=M` and return:

```
{ "data": [...], "pagination": {"total": N, "count": M, "skip": S, "limit": L} }
```

`veeam_client.VeeamClient.get_paged()` walks pages until exhausted.

## Endpoints used

### Server / health

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/serverInfo` | VBR id, name, build, DB engine |
| GET | `/api/v1/license` | License edition, expiry, instance counters |

### Jobs (backup configuration)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/jobs` | Per-job config; `?typeFilter=Backup,BackupCopy,Replica,...` |
| GET | `/api/v1/jobs/states` | Per-job last result, last run, next run, destination repo |
| GET | `/api/v1/jobs/{id}` | Full single-job config (object selectors, retention, schedule) |

### Sessions (backup performance)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/sessions` | All session history; filter via `?jobIdFilter=&orderColumn=CreationTime&orderAsc=false` |
| GET | `/api/v1/sessions/{id}` | Single session detail (state, result, progress, throughput) |

Session payload includes: `creationTime`, `endTime`, `state`, `result`,
`progressPercent`, `processedObjects`, `totalSize`, `transferredSize`,
`speed` (bytes/sec). Use these for "how long did backups take, how much data
was transferred" annual-review metrics.

### Backups & restore points

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/backups` | All backup chains across jobs |
| GET | `/api/v1/backupObjects` | VMs / computers / file shares being protected |
| GET | `/api/v1/restorePoints` | Recoverable points (date, size, type) |

### Inventory (workload sources)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/inventory/vmware/vms` | VMs visible to VBR (vCenter-based) |
| GET | `/api/v1/inventory/hyperv/vms` | Hyper-V VMs |
| GET | `/api/v1/inventory/agent/computers` | Agent-protected physical/cloud servers |

### Backup infrastructure (storage)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/backupInfrastructure/repositories` | Regular repos (Win/Linux/NFS/Dedupe/Object) |
| GET | `/api/v1/backupInfrastructure/repositories/states` | Capacity / free / status per repo |
| GET | `/api/v1/backupInfrastructure/scaleOutRepositories` | SOBR config (perf/capacity/archive tiers) |
| GET | `/api/v1/backupInfrastructure/scaleOutRepositories/states` | SOBR aggregate capacity |
| GET | `/api/v1/backupInfrastructure/proxies` | VMware/HyperV/Agent proxies |
| GET | `/api/v1/backupInfrastructure/proxies/states` | Proxy availability |
| GET | `/api/v1/backupInfrastructure/managedServers` | Hosts registered to VBR |

VBR REST does **not** expose IOPS / latency counters for repositories.
Throughput proxies live in session statistics (transferredSize ÷ duration).

**Field names on `/repositories/states`** (verified against build 13.0.1.2067):
`capacityGB`, `freeGB`, `usedSpaceGB`, `isOnline`, `hostName`, `path`. NOT
`capacity`/`freeSpace` (bytes) as some Veeam docs suggest — the REST surface
returns GB-scaled values directly.

**Repository path** is *not* on the resource root for most types — check
`share.sharePath` (NFS) / `smbShare.sharePath` (SMB) / `repository.path`
before falling back.

### Alerts (VBR has NO `/alarms` endpoints in REST)

VBR v13 REST does **not** expose `/alarms` or `/alarms/triggered` —
those are Veeam ONE features. The only alert-shaped surfaces on VBR REST:

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/malwareDetection/events` | Ransomware / suspicious-activity events from inline + on-restore scans |
| GET | `/api/v1/securityAnalyzer/bestPractices` | Security posture findings (CIS-like checks) |
| GET | `/api/v1/securityAnalyzer/lastRun` | Last security analyzer run metadata |
| POST | `/api/v1/securityAnalyzer/start` | Trigger an on-demand security scan |

For job-failure / repo-full / system alarms, use the separate `veeam-one-pull`
skill (Veeam ONE 13 REST has the full alarm catalog) or syslog forwarding.

## Server-side gotchas (build 13.0.1.2067, verified 2026-05-02)

| Endpoint | Behavior |
|---|---|
| `/jobs/states` | **HTTP 500** consistently (server-side bug). Fall back to per-job state via single-job GET or via `/sessions?jobIdFilter=<id>&orderColumn=CreationTime&orderAsc=false`. |
| `/backupInfrastructure/scaleOutRepositories/states` | **400** "value 'states' is not valid" — server treats `states` as a SOBR id. The collection-level `/states` endpoint isn't implemented for SOBR or proxies on this build. SOBR capacity must be inferred from the resource itself. |
| `/backupInfrastructure/proxies/states` | Same 400 pattern. |
| `/alarms/*`, `/triggeredAlarms`, `/events`, `/notifications` | **404** — not implemented on VBR REST (Veeam ONE territory). |
| `x-api-version: 1.2-rev1` | **Read timeout** on auth. Use `1.2-rev0`. |

## Common filters

- `?nameFilter=<glob>` — substring/glob name match
- `?typeFilter=<csv>` — comma-list of types
- `?jobIdFilter=<id>` — limit sessions / restore points to one job
- `?orderColumn=<field>&orderAsc=<bool>` — sort
- `?createdAfterFilter=<iso8601>` — time-window for sessions/events
