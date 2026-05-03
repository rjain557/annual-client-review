---
name: mailstore-spe-pull
description: Pull data from the on-prem MailStore Service Provider Edition (SPE) Management API for every hosted client archive. Surfaces users, mailbox storage sizes, system + per-instance alerts, archive store health, jobs, profiles, credentials, and full instance configuration through the SPE REST API. Also generates branded monthly client DOCX reports and routes detected alerts into client-billable Client Portal tickets (assigned to CHD : TS1, India tech support) with full remediation steps inline. Use when the user asks to gather mailstore information, list email-archive clients/users/sizes, check mailstore alerts/issues, build monthly mailstore reports, create CP tickets for mailstore problems, run any MailStore SPE Management API function, or refresh per-client mailstore data under clients/&lt;code&gt;/mailstore/. Trigger phrases include "mailstore", "mailstore SPE", "email archive", "archive.technijian.com", "spe pull", "route mailstore alerts", "open tickets for mailstore alerts".
---

# Skill: mailstore-spe-pull

Pull a full operational snapshot from Technijian's on-prem MailStore Service
Provider Edition (SPE) Management API at `archive.technijian.com:8474` and
write per-client JSON under `clients/<code>/mailstore/<YYYY-MM-DD>/`.

## When to invoke

- "pull mailstore data", "mailstore SPE info", "email archive snapshot"
- "what users are in the mailstore for &lt;client&gt;"
- "how big is the mailbox for &lt;user&gt;", "storage usage per archive"
- "any mailstore alerts", "what needs to be fixed in the archive"
- "build mailstore monthly report" / "email archive monthly report for &lt;CODE&gt;"
- "open CP tickets for mailstore alerts" / "route mailstore alerts to india support"
- "rebuild the search indexes on orthoxpress" (any write op — use `run_function.py --confirm`)
- Any time the SPE Management API is needed — this skill covers all 122 functions

## Operational policy: alerts → CP tickets

Whenever this skill **detects actionable alerts** (any non-information message
in `GetServiceStatus.messages`, any store with `searchIndexesNeedRebuild` /
`needsUpgrade` / `error`, any instance with sustained archive-run failure, or
any instance not in `running` state), the skill SHOULD:

1. Run `route_alerts.py` (dry-run) to preview the tickets it would open.
2. If the user has authorized ticketing or this is part of a daily run, run
   `route_alerts.py --apply` to actually create the tickets.
3. Tickets are auto-deduplicated via `state/alert-tickets.json` — re-running
   is safe and will not create duplicates of the same active alert.

Mapping of alert → ticket destination:

| Alert | Client routed to | Reason |
|---|---|---|
| Per-instance alerts (search index rebuild, archive run failures, store error/upgrade, instance not running) | The instance's mapped client (`icmlending`/`icm-realestate` → `ICML`, `orthoxpress` → `ORX`) | Client-billable on the active contract |
| Server-wide messages (SMTP unencrypted, version available, etc.) | `Technijian` internal | Server-wide housekeeping; bills against ContractID 3977 (Internal Contract) |

All tickets default to `AssignTo_DirID 205` (CHD : TS1 — Chandigarh Tech
Support) with `RoleType="Off-Shore Tech Support"`. Priority is set per
alert severity:

| Alert type | Priority |
|---|---|
| `archive_runs_failing` | Critical |
| `instance_not_running` | Critical |
| `search_index_rebuild` | Same Day |
| `store_error` | Same Day |
| `store_needs_upgrade` | When Convenient |
| `system_message` (SMTP, etc.) | When Convenient |

Each ticket body contains a full step-by-step remediation walkthrough so
the receiving tech can fix the issue without prior MailStore SPE knowledge:

- Affected instance / store identifiers
- Severity statement (what's at risk operationally)
- "WHAT TO DO" — Option A (Management Console UI) and Option B (REST API command)
- Expected verification command (`show_alerts.py`, `list_storage.py`, `pull_year_activity.py`)
- "CLOSE THE TICKET WHEN" exit criterion
- Common root causes and the fix for each (especially for archive-run failures: M365 throttling, scope error, MFA, password rotation, network egress)

## Topology (snapshot 2026-05-02)

- **Web console:** https://archive.technijian.com:8470/web/login.html (admin browser UI)
- **Management API:** https://archive.technijian.com:8474/api/invoke/&lt;Function&gt; (HTTP Basic, POST, x-www-form-urlencoded)
- **Metadata feed:** https://archive.technijian.com:8474/api/get-metadata (lists all 122 functions w/ args)
- **Long-running status:** https://archive.technijian.com:8474/api/get-status (auto-polled by client)
- **Management Server:** archive.technijian.com (port 8474)
- **Client Access Server:** archive.technijian.com (port 8473) — end-user web client + IMAP/MAPI
- **Instance Host:** vmtechmss (port 8472) — Windows Server 2022, 8 GB RAM, 4×Xeon E5-2660v4
- **Running version:** 25.3.1.23021 (26.2.0.24007 update available — informational alert)

## Hosted client archives

Three running instances. Mapping to `clients/<code>/`:

| instanceID | client code | folder |
|---|---|---|
| icmlending | icml | clients/icml/mailstore/ |
| icm-realestate | icml | clients/icml/mailstore/ (filenames keep them separate via `snapshot-icm-realestate.json`) |
| orthoxpress | orx | clients/orx/mailstore/ |

To add a new client archive: register the instance in MailStore, then add the
mapping in `INSTANCE_TO_CLIENT_CODE` at the top of `spe_client.py`.

## Credentials

`%USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/mailstore-spe.md`

Read by `spe_client.get_credentials()` at runtime; never embed secrets in
shell commands. Env vars `MAILSTORE_SPE_USER` / `MAILSTORE_SPE_PASSWORD` /
`MAILSTORE_SPE_URL` override the keyfile if set.

## Scripts

All scripts live in `technijian/mailstore-pull/scripts/`.

| Script | Purpose |
|---|---|
| `spe_client.py` | Reusable `Client` class. Auto-polls long-running ops, exposes `metadata()`, plus typed wrappers (`list_instances`, `instance_statistics`, `stores`, `users`, `user_info`, `folder_statistics`, `jobs`, `profiles`, ...). |
| `pull_mailstore.py` | Full per-instance snapshot → `clients/<code>/mailstore/<date>/snapshot-<instanceID>.json`. Includes env, service_status, statistics, live_stats, stores, users + GetUserInfo, folder_statistics (per-mailbox sizes — currently always errors due to SPE bug), jobs, profiles, credentials, and four config blocks (instance/index/compliance/directory_services). Use `--no-folder-stats` to skip the broken folder query. |
| `pull_year_activity.py` | Yearly archive-run + scheduled-job history per instance → `clients/<code>/mailstore/<year>/{worker,job}-results-<instanceID>.json`. Auto-bisects month → day on the SPE "Nullable object must have a value" bug; records day-level fetch failures in `broken_days[]`. Default year = current. |
| `show_alerts.py` | Combines `GetServiceStatus.messages` + per-store health (`searchIndexesNeedRebuild`, `needsUpgrade`, `error`) into one ranked list. Exits 1 on any error-severity alert. |
| `list_users.py` | Per-instance user table with email, auth method, MFA, and rolled-up mailbox bytes/messages from `GetFolderStatistics`. `--csv` to dump. |
| `list_storage.py` | Instance + store storage report mirroring the SPE console "Statistics" view. Exits 1 if any store flag is set. |
| `run_function.py` | Generic invoker for any of the 122 API functions. `--list <substr>` to discover, `--describe <fn>` to print the arg signature, `--confirm` required for write/mutating verbs (Create*/Delete*/Set*/Run*/Compact*/Verify*/Rebuild*/Recover*/Repair*/Sync*/Initialize*/Disable*/Test*/Stop*/Start*/Restart*/Freeze*/Thaw*/Attach*/Detach*/Clear*/Retry*/Rename*/Reset*/Recreate*/Merge*/Move*/Transfer*/Upgrade*/Maintain*/Refresh*/Cancel*/Pair*/Reload*/Send*). |
| `build_monthly_report.py` | Branded client DOCX (Cover + Executive Summary KPI cards + Archive Inventory + Mailboxes Being Archived + Archive Job Health (30d) + Per-Store Storage Detail + Storage Growth & Projections at +3/+6/+9/+12 months [historical + recent-30d methods, with text-bar trend visual] + Recommendations + About). Aggregates multiple instances per client (icml = icmlending + icm-realestate). Imports `_brand.py` and runs `proofread_docx.py` gate. |
| `route_alerts.py` | Detect alerts (system messages + per-store health + 30-day archive run health) and create remediation tickets in Client Portal via `cp_tickets.create_ticket_for_code()`. Per-instance alerts bill the mapped client (icml/orx); server-wide alerts bill Technijian internal. Default dry-run; `--apply` to create. State at `technijian/mailstore-pull/state/alert-tickets.json` deduplicates re-runs. Tickets default to `AssignTo_DirID 205` (CHD : TS1 / India tech support). |

## Common workflows

```bash
# Detect alerts and route them to CP tickets (DRY-RUN first, then --apply)
python technijian/mailstore-pull/scripts/route_alerts.py
python technijian/mailstore-pull/scripts/route_alerts.py --apply

# Daily-style full pull for all 3 instances
python technijian/mailstore-pull/scripts/pull_mailstore.py

# Single instance, skipping per-folder breakdown for speed
python technijian/mailstore-pull/scripts/pull_mailstore.py --instance orthoxpress --no-folder-stats

# Operations dashboard (alerts + store health)
python technijian/mailstore-pull/scripts/show_alerts.py

# Monthly client report (branded DOCX, runs proofread gate)
python technijian/mailstore-pull/scripts/build_monthly_report.py --month 2026-05

# Per-mailbox usage table for all clients
python technijian/mailstore-pull/scripts/list_users.py --csv mailbox-usage.csv

# Storage by instance + per-store breakdown
python technijian/mailstore-pull/scripts/list_storage.py

# Discover what API functions exist for any topic
python technijian/mailstore-pull/scripts/run_function.py --list compliance
python technijian/mailstore-pull/scripts/run_function.py --describe RebuildSelectedStoreIndexes

# Pull a year's worth of archive-run + job history per instance (auto-bisect on SPE bug)
python technijian/mailstore-pull/scripts/pull_year_activity.py --year 2026

# Pull worker results manually via the generic invoker (note datetime format: NO 'Z')
python technijian/mailstore-pull/scripts/run_function.py GetWorkerResults \
    instanceID=icmlending fromIncluding=2026-01-01T00:00:00 \
    toExcluding=2027-01-01T00:00:00 timeZoneID='$Local'

# Write op (search indexes need rebuild on orthoxpress) — must --confirm
python technijian/mailstore-pull/scripts/run_function.py --confirm \
    SelectAllStoreIndexesForRebuild instanceID=orthoxpress
python technijian/mailstore-pull/scripts/run_function.py --confirm \
    RebuildSelectedStoreIndexes instanceID=orthoxpress
```

## API conventions (gotchas)

- Every call is **POST** even for reads. An empty body still requires `Content-Length: 0` (Microsoft-HTTPAPI/2.0 returns HTTP 411 otherwise). The client handles this.
- Body is `application/x-www-form-urlencoded` — never JSON. Booleans serialize as the literal strings `"true"` / `"false"`.
- Param names are exact: `instanceFilter` (not `filter`), `instanceID` (not `instanceId`), `timeZoneID` (capital ID) — but `GetJobResults` uses `timeZoneId` (lowercase d). When in doubt, `run_function.py --describe <fn>` first.
- **Datetime format** for `GetWorkerResults` / `GetJobResults`: `2026-01-01T00:00:00` — *no* trailing `Z`, no fractional seconds. Both forms with `Z` and with `.000` return "String was not recognized as a valid DateTime."
- **Nullable params**: `profileID` and `userName` on `GetWorkerResults` are nullable. Passing `0` raises `Specified argument was out of the range of valid values`; passing `""` errors too. Omit them entirely.
- **`GetProfiles`** only accepts `raw=true` in this SPE version. The client wrapper passes `raw=False` by default for backwards compatibility — pass `raw=True` explicitly when calling.
- **SPE bug — `Nullable object must have a value` (long-running):** Hits `GetWorkerResults` over a year-long window for instances with >5k rows (icm-realestate has 25,741 in 2026), and hits `GetFolderStatistics` on every instance. `pull_year_activity.py` bisects month → day to recover. `pull_mailstore.py --no-folder-stats` skips the folder query. `route_alerts.py` falls back to the on-disk year-activity file when the live 30-day query trips this bug.
- Most instance-targeted ops require **service provider access enabled** on the instance (set via the management console). Store/index ops bypass this.
- Long-running ops (Compact/Verify/Rebuild/Recover/Sync/Upgrade) return `statusCode: "running"` + `token`. The client auto-polls `/api/get-status` until `statusCode != "running"` (max 30 min).
- `GetServiceStatus.messages[]` is the canonical alert feed. Severity values: `information` | `warning` | `error`.
- TLS cert on 8474 is self-signed; client uses `ssl.CERT_NONE` (expected).
- **Per-mailbox size:** Because `GetFolderStatistics` errors, individual user mailbox sizes are not retrievable via the API in this SPE version. `build_monthly_report.py` falls back to **even allocation** within an instance (total instance size ÷ user-facing mailbox count). Service accounts (`$archiveadmin`, `admin`) are excluded from the user-facing count.

## Output layout

```
clients/<code>/mailstore/<YYYY-MM-DD>/snapshot-<instanceID>.json    daily snapshot
clients/<code>/mailstore/<year>/worker-results-<instanceID>.json    yearly archive-run history
clients/<code>/mailstore/<year>/job-results-<instanceID>.json       yearly job history
clients/<code>/mailstore/monthly/<YYYY-MM>/<CODE>-Email-Archive-Monthly-<YYYY-MM>.docx
                                                                    branded client monthly report
technijian/mailstore-pull/state/alert-tickets.json                  ticket dedup state (per alert key)
```

Each snapshot is self-contained — easy to diff between dates. The full
122-function feature surface is reachable via `run_function.py` for anything
the dedicated scripts don't already wrap.

## Active alerts as of 2026-05-02 (and CP tickets opened)

| Alert | Severity | Client | CP Ticket |
|---|---|---|---|
| Instance `orthoxpress`: search indexes need rebuild | error | ORX | **#1452675** |
| Archive jobs failing on icmlending + icm-realestate (100% failure rate, 0 items archived in 30 days) | error | ICML | **#1452676** |
| System SMTP unencrypted / "Accept all certificates" enabled | warning | Technijian | **#1452674** |
| SPE 26.2.0.24007 update available | information | — | none (informational only) |

All three tickets are assigned to `CHD : TS1` (DirID 205, India tech support) with full remediation walkthroughs. Re-running `route_alerts.py --apply` is safe — the state file `state/alert-tickets.json` dedupes against the same alert/client key.

Quick remediation for the orthoxpress index rebuild:
```bash
python run_function.py --confirm SelectAllStoreIndexesForRebuild instanceID=orthoxpress
python run_function.py --confirm RebuildSelectedStoreIndexes instanceID=orthoxpress
```

<!-- ticket-management-note: cp-ticket-management -->

## Ticket management — migration to cp-ticket-management

This skill currently opens CP tickets directly. State today:
`technijian/mailstore-pull/state/<auto>`.

`route_alerts.py` opens CP tickets for archive-store alerts. **Pending migration** to the central tracked wrapper. Backfill the 3 existing tickets (#1452674 Technijian SMTP, #1452675 ORX index, #1452676 ICML archive-jobs FAILING) via `ticket_state.backfill(...)`.

**Migration steps** (see ../cp-ticket-management/SKILL.md):

1. Replace `cp_tickets.create_ticket(...)` /
   `cp_tickets.create_ticket_for_code(...)` with
   `cp_tickets.create_ticket_for_code_tracked(...)`.
2. Pick a stable `issue_key` per unique issue
   (convention: `mailstore-spe-pull:<issue-type>:<resource-id>`).
3. Pass `source_skill="mailstore-spe-pull"`.
4. Pass `metadata={...}` with the data points that justified the
   ticket (counts, percentages, server names).
5. Backfill any existing open tickets via
   `ticket_state.backfill(...)` — template at
   `scripts/veeam-365/_backfill_state.py`.

After migration: the central monitor at
`scripts/clientportal/ticket_monitor.py check` handles 24h reminders to
support@technijian.com automatically. Retire this skill's local
reminder loop / state file.
