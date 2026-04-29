# Workstation Setup

What you need to install on a new workstation to run the automation in this
repo (annual reviews, weekly time-entry audit, monthly client pull, daily
Huntress AV pull, etc.). Source paths below match
`c:\vscode\annual-client-review\annual-client-review` because that's where the
helper `.cmd` wrappers and scheduled-task examples hard-code the repo
location. If you clone elsewhere, update the paths in:

- `technijian\monthly-pull\run-monthly-pull.cmd`
- `technijian\huntress-pull\run-daily-huntress.cmd`
- any other `run-*.cmd` you create

## 1. Prerequisites

| Component | Required | Notes |
|---|---|---|
| Python | 3.11+ (tested on 3.14.3) | Default install path used in `.cmd` wrappers: `C:\Python314\python.exe`. Update the wrappers if Python lives elsewhere. |
| Git | any modern | Used to clone this repo. |
| OneDrive (Technijian tenant) | yes | Provides the keyvault files at `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\client-portal.md` (Client Portal) and `...\keys\huntress.md` (Huntress API). |
| Claude Code (optional) | latest | If you want to invoke the skills (`/monthly-client-pull`, `/weekly-time-audit`, `/huntress-daily-pull`) via Claude Code. The Python scripts run standalone without it. |

The Python scripts use only the standard library (`urllib`, `xml.etree`,
`csv`, `json`, `pathlib`, `datetime`, `zoneinfo`) — no `pip install` step.

## 2. Clone the repo

```cmd
git clone <repo-url> c:\vscode\annual-client-review\annual-client-review
```

If you clone to a different path, also update the hard-coded `REPO=` line in
every `technijian\*\run-*.cmd` wrapper.

## 3. Client Portal credentials

The Python helper in `scripts\clientportal\cp_api.py` reads credentials from
either env vars or a OneDrive-synced markdown file. Pick one:

### Option A — environment variables (recommended for headless runs)

```cmd
setx CP_USERNAME "you@technijian.com"
setx CP_PASSWORD "<password>"
```

`setx` is permanent (writes to user profile). New shells will pick it up.

### Option B — OneDrive keyvault file

Make sure OneDrive has finished syncing this file:

```
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\client-portal.md
```

It must contain lines like:

```markdown
**UserName:** you@technijian.com
**Password:** <password>
```

`cp_api.get_credentials()` falls back to this file when env vars are absent.

## 4. Smoke test

From the repo root:

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM No API call - just confirms imports/paths
python technijian\monthly-pull\scripts\pull_monthly.py --dry-run

REM One client, one month - confirms auth + write paths
python technijian\monthly-pull\scripts\pull_monthly.py --month 2026-03 --only AAVA
```

Expected output for the second command:

```
[hh:mm:ss] month=2026-03 window=2026-03-01 -> 2026-03-31
[hh:mm:ss] fetching active clients...
  got NN active clients
  [k/NN] AAVA     DirID=6989   entries=  22 tickets=  19
[hh:mm:ss] DONE
```

Files land at `clients\aava\monthly\2026-03\` (5 files) and the run log at
`technijian\monthly-pull\state\2026-03.json`.

## 5. Claude Code skills (optional)

The skills are user-scoped; copy them to the same path on the new machine:

```
%USERPROFILE%\.claude\skills\monthly-client-pull\SKILL.md
%USERPROFILE%\.claude\skills\weekly-time-audit\SKILL.md     (if present)
%USERPROFILE%\.claude\skills\huntress-daily-pull\SKILL.md
```

Once present, Claude Code recognizes `/monthly-client-pull`,
`/huntress-daily-pull`, and natural-language triggers ("pull last month",
"monthly client pull", "pull huntress", "huntress 24h", etc.).

## 6. Schedule the monthly pull (recommended)

The repo ships a wrapper at
`technijian\monthly-pull\run-monthly-pull.cmd` that:

- changes into the repo,
- runs `pull_monthly.py` with default args (prior calendar month),
- tees stdout/stderr to `technijian\monthly-pull\state\run-YYYY-MM-DD.log`.

Register it as a Windows Scheduled Task that fires the **1st of every month
at 7:00 AM local time**. Do NOT change this cadence without also updating
`%USERPROFILE%\.claude\skills\monthly-client-pull\SKILL.md`.

### Option A — schtasks command (one-liner)

Run this once in an elevated cmd / PowerShell:

```cmd
schtasks /create ^
  /tn "Technijian-MonthlyClientPull" ^
  /tr "\"c:\vscode\annual-client-review\annual-client-review\technijian\monthly-pull\run-monthly-pull.cmd\"" ^
  /sc MONTHLY ^
  /d 1 ^
  /st 07:00 ^
  /rl LIMITED ^
  /f
```

Verify:

```cmd
schtasks /query /tn "Technijian-MonthlyClientPull" /v /fo LIST
```

To run it on demand without waiting for the 1st:

```cmd
schtasks /run /tn "Technijian-MonthlyClientPull"
```

### Option B — Task Scheduler GUI

1. Open **Task Scheduler** -> Create Task...
2. Name: `Technijian-MonthlyClientPull`
3. Triggers tab -> New -> Monthly -> Days: `1` -> Months: All -> Start: 07:00 local
4. Actions tab -> New -> Program/script: `c:\vscode\annual-client-review\annual-client-review\technijian\monthly-pull\run-monthly-pull.cmd`
5. Conditions tab -> uncheck "Start the task only if the computer is on AC power" if it's a laptop
6. Settings tab -> check "Run task as soon as possible after a scheduled start is missed" (catches up if the laptop was off at 7 AM on the 1st)

### Sleep / off-hours behavior

Scheduled Tasks do not run when the workstation is asleep or powered off. With
"Run task as soon as possible after a scheduled start is missed" enabled, the
job catches up the next time the machine wakes. If you need stronger
guarantees, move the runner to a server or commit the same script to a
GitHub Actions cron schedule (out of scope for this doc).

## 7. What the monthly pull writes

```
clients\<code>\monthly\YYYY-MM\
  time_entries.xml          raw XML from stp_xml_TktEntry_List_Get
  time_entries.json         parsed list
  time_entries.csv          flat
  tickets.json              unique tickets derived from time entries
  pull_summary.json         counts, errors, run timestamp

technijian\monthly-pull\state\YYYY-MM.json   run log
technijian\monthly-pull\state\run-YYYY-MM-DD.log   stdout/stderr from .cmd wrapper
```

It does NOT pull invoices (that's `scripts\clientportal\pull_all_active.py`)
and does NOT modify or delete anything in the Client Portal.

## 8. Backfill or rerun a month

```cmd
python technijian\monthly-pull\scripts\pull_monthly.py --month 2026-01
python technijian\monthly-pull\scripts\pull_monthly.py --month 2026-03 --only AAVA,BWH
```

Reruns overwrite the per-client snapshot folder for that month.

## 9. Troubleshooting (monthly pull)

| Symptom | Cause | Fix |
|---|---|---|
| `Client Portal credentials not found` | Env vars unset and OneDrive keyvault missing/unsynced | See section 3. |
| `got 0 active clients` | Auth succeeded but token role is wrong | Confirm the account has `clients:read`; otherwise contact Technijian portal admin. |
| HTTP 401 from `/api/auth/token` | Wrong creds | Re-check `client-portal.md`. |
| `time_entry_count: 0` for every client | Wrong month window | Check the `start`/`end` printed at the top of the run; if you mistyped `--month` re-run. |
| Scheduled task ran but no files written | Task ran as `SYSTEM` and OneDrive isn't visible to that account | Edit task -> "Run only when user is logged on" OR set `CP_USERNAME`/`CP_PASSWORD` machine-wide so the keyvault file isn't needed. |

## 10. Huntress API credentials

The daily Huntress AV pull (`technijian\huntress-pull\scripts\pull_huntress_daily.py`)
calls the Huntress v1 REST API using HTTP Basic auth with an **API Key ID +
API Secret** pair. Read in priority order:

### Option A - environment variables (recommended for headless runs)

```cmd
setx HUNTRESS_API_KEY "hk_..."
setx HUNTRESS_API_SECRET "hs_..."
```

### Option B - OneDrive keyvault file

Make sure OneDrive has finished syncing this file:

```text
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\huntress.md
```

It must contain lines like:

```markdown
**API Key ID:** hk_...
**API Secret:** hs_...
```

The active key pair as of 2026-04-29 is `hk_ee8ddb711c3c959cc7dd` + the
matching `hs_*` secret stored in the keyfile. The previous
`hk_f567a96492585118c32a` was superseded. Generate / regenerate the key pair
in the Huntress Portal at **Account Settings -> API Credentials** — the
Secret is shown exactly once, there is no recovery.

The Client Portal credentials from section 3 are also required (the pull
script cross-references active CP clients to map Huntress organizations to
LocationCodes).

## 11. Smoke test the Huntress pull

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM Confirm credentials work - prints the account JSON, no per-client work
python -c "import sys; sys.path.insert(0, r'technijian\huntress-pull\scripts'); import huntress_api as h; print(h.get_account())"

REM Show how Huntress orgs would map to LocationCodes - no per-client API calls
python technijian\huntress-pull\scripts\pull_huntress_daily.py --map-only

REM One client, full pull - confirms write paths
python technijian\huntress-pull\scripts\pull_huntress_daily.py --only BWH
```

After the third command there should be a directory at
`clients\bwh\huntress\<YYYY-MM-DD>\` containing `agents.json`, `agents.csv`,
and `pull_summary.json`.

If `--map-only` lists Huntress organizations under `----` (unmapped), edit
`technijian\huntress-pull\state\huntress-org-mapping.json` and add entries
under the `manual` block:

```json
{ "manual": { "<huntress_org_id>": "<LocationCode>" }, "ignore": [] }
```

Re-run `--map-only` to confirm.

## 12. Schedule the daily Huntress pull

The repo ships a wrapper at
`technijian\huntress-pull\run-daily-huntress.cmd` that:

- changes into the repo,
- runs `pull_huntress_daily.py` with default args (last 24h),
- tees stdout/stderr to `technijian\huntress-pull\state\run-YYYY-MM-DD.log`.

Register it as a Windows Scheduled Task that fires **every day at 1:00 AM
local time**. Do NOT change this cadence without also updating
`%USERPROFILE%\.claude\skills\huntress-daily-pull\SKILL.md`.

### Option A - schtasks command (one-liner)

Run this once in an elevated cmd / PowerShell:

```cmd
schtasks /create ^
  /tn "Technijian-DailyHuntressPull" ^
  /tr "\"c:\vscode\annual-client-review\annual-client-review\technijian\huntress-pull\run-daily-huntress.cmd\"" ^
  /sc DAILY ^
  /st 01:00 ^
  /rl LIMITED ^
  /f
```

Verify:

```cmd
schtasks /query /tn "Technijian-DailyHuntressPull" /v /fo LIST
```

To run it on demand without waiting for 1 AM:

```cmd
schtasks /run /tn "Technijian-DailyHuntressPull"
```

### Option B - Task Scheduler GUI

1. Open **Task Scheduler** -> Create Task...
2. Name: `Technijian-DailyHuntressPull`
3. Triggers tab -> New -> Daily -> Start: 01:00 local -> recur every 1 day
4. Actions tab -> New -> Program/script: `c:\vscode\annual-client-review\annual-client-review\technijian\huntress-pull\run-daily-huntress.cmd`
5. Conditions tab -> uncheck "Start the task only if the computer is on AC power" if it's a laptop
6. Settings tab -> check "Run task as soon as possible after a scheduled start is missed" (catches up if the laptop was off at 1 AM)

### Sleep / off-hours behavior (Huntress)

Same caveat as section 6: Scheduled Tasks do not run when the workstation is
asleep. The "run as soon as possible after a missed start" flag covers
same-day misses; multi-day outages will skip the corresponding nights and the
affected `clients\<code>\huntress\YYYY-MM-DD\` folders simply won't exist for
those dates.

## 13. What the Huntress pull writes

```
clients\<code>\huntress\YYYY-MM-DD\
  agents.json + agents.csv      full agent inventory: hostname, platform,
                                 status, version, last_callback_at,
                                 isolated, ipv4_address, organization_id
  pull_summary.json             per-client counts (active / offline /
                                 isolated / called_back_in_window) + errors

technijian\huntress-pull\YYYY-MM-DD\
  account.json                  account info
  organizations.json            full Huntress org list as returned
  mapping.json                  resolved huntress_org_id -> LocationCode
  unmapped.json                 orgs with no LocationCode match (action item)
  run_log.json                  per-day rollup

technijian\huntress-pull\state\YYYY-MM-DD.json   same as run_log
technijian\huntress-pull\state\run-YYYY-MM-DD.log   stdout/stderr from .cmd wrapper
```

**Scope (v1):** AV/EDR agent activity only. Incident reports, signals,
external ports, identities, and reseller license line items are intentionally
out of scope and the helpers in `huntress_api.py` are dormant. Add per-client
outputs only when explicitly asked for.

**Out of scope entirely:** Huntress Managed Security Awareness Training (SAT)
is not exposed in the Huntress v1 REST API as of 2026-04. SAT exports remain
a manual SAT-portal action until Huntress publishes those endpoints.

## 14. Backfill or rerun a Huntress day / month

Daily reruns:

```cmd
python technijian\huntress-pull\scripts\pull_huntress_daily.py --only AAVA,BWH
python technijian\huntress-pull\scripts\pull_huntress_daily.py --hours 72
python technijian\huntress-pull\scripts\pull_huntress_daily.py --date 2026-04-28
```

Reruns overwrite the per-client snapshot folder for that date.

Historical backfill of incidents/signals/reports per client per month
(the `/v1/agents` endpoint has no historical filter, so agent inventory is
NOT backfilled — that data only exists from the daily pull onward):

```cmd
REM Full year-to-date (Jan through current month)
python technijian\huntress-pull\scripts\backfill_huntress.py --year 2026

REM Specific window
python technijian\huntress-pull\scripts\backfill_huntress.py --from 2026-01 --to 2026-03

REM One client across the year
python technijian\huntress-pull\scripts\backfill_huntress.py --year 2026 --only BWH
```

Backfill outputs land at `clients\<code>\huntress\monthly\YYYY-MM\` (4 files
per client per month: `incident_reports.json`, `signals.json`, `reports.json`,
`pull_summary.json`) plus account-level run dirs at
`technijian\huntress-pull\backfill\YYYY-MM\`. Re-runs overwrite cleanly.

The 2026-01 through 2026-04 backfill was completed on 2026-04-29 (29 mapped
clients, 116 client-month folders, 48 incidents + 52 signals + 598 reports).
Re-run the backfill any time the org -> LocationCode mapping changes (a newly
mapped client gets its history filled in retroactively).

## 15. Troubleshooting (Huntress pull)

| Symptom | Cause | Fix |
|---|---|---|
| `Huntress credentials not found` | Env vars unset and `huntress.md` still has `TODO_PASTE_SECRET_HERE` | Paste the API Secret into the keyfile or set the env vars (section 10). |
| HTTP 401 `Missing or invalid credentials` | Secret rotated, key revoked, or pasted wrong | Regenerate the key pair in the Huntress Portal -> Account Settings -> API Credentials. |
| `unmapped.json` non-empty | Huntress org name does not exact-match an active CP client name | Add an explicit `manual` entry in `technijian\huntress-pull\state\huntress-org-mapping.json` and re-run. |
| One client has `errors[]` in its `pull_summary.json` but the rest succeeded | Partial endpoint failure | Re-run `python pull_huntress_daily.py --only <CODE>` once the underlying issue is resolved. |
| Scheduled task ran but per-client folders are absent | Task ran as `SYSTEM` (no OneDrive sync) | Same fix as section 9: run the task as the workstation user, not SYSTEM. |

## 16. CrowdStrike Falcon API credentials

The daily CrowdStrike Falcon pull
(`technijian\crowdstrike-pull\scripts\pull_crowdstrike_daily.py`) reads
credentials from either env vars or a OneDrive-synced markdown file. Pick one.

### Option A — environment variables (recommended for headless runs)

```cmd
setx CROWDSTRIKE_CLIENT_ID "<oauth client uuid>"
setx CROWDSTRIKE_CLIENT_SECRET "<secret>"
setx CROWDSTRIKE_BASE_URL "https://api.us-2.crowdstrike.com"
```

### Option B — OneDrive keyvault file

Make sure OneDrive has finished syncing this file:

```text
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\crowdstrike.md
```

It must contain lines like:

```markdown
- **Base URL:** https://api.us-2.crowdstrike.com
- **Client ID:** <oauth client uuid>
- **Client Secret:** <secret>
```

`cs_api.get_credentials()` falls back to this file when env vars are absent
and auto-populates `CROWDSTRIKE_BASE_URL` from the `**Base URL:**` line.
Token TTL is ~30 min; the helper caches and force-refreshes on 401.

The OAuth client must be created in **Falcon Console -> Support and Resources
-> API clients and keys -> Create API client**. Tick **only the read scopes**
listed in `keys/crowdstrike.md`. The Secret is shown exactly once at creation.

## 17. CrowdStrike pull smoke test

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM Auth + scope probe — token lookup + child CID count, no per-client API calls
python -c "import sys; sys.path.insert(0,'technijian\crowdstrike-pull\scripts'); import cs_api; print('children:', len(cs_api.list_mssp_children()))"

REM Mapping resolution only — print member_cid -> LocationCode mapping
python technijian\crowdstrike-pull\scripts\pull_crowdstrike_daily.py --map-only

REM One client, last 24h — confirms write paths
python technijian\crowdstrike-pull\scripts\pull_crowdstrike_daily.py --only AAVA
```

Expected output for `--map-only` on a Flight Control parent tenant:

```text
[hh:mm:ss] CrowdStrike daily Falcon pull
  window: ...
  fetching active CP clients...
    got NN active CP clients
  checking Flight Control / MSSP children...
    multi-tenant: 36 child CID(s)
  mapped: M    unmapped: U    ignored: I

  MAP    AAVA    <- AAVA - Aventine at Aliso Viejo                 (code_prefix)
  ...
```

Files land at `clients\<code>\crowdstrike\YYYY-MM-DD\` (5 files per mapped
client per day) plus account-level outputs at
`technijian\crowdstrike-pull\YYYY-MM-DD\` and a run log at
`technijian\crowdstrike-pull\state\YYYY-MM-DD.json`.

## 18. Schedule the daily CrowdStrike pull (recommended)

The repo ships a wrapper at
`technijian\crowdstrike-pull\run-daily-crowdstrike.cmd`. Register it as a
Windows Scheduled Task that fires **every day at 3:00 AM local time**. 1 AM
is taken by Huntress, 2 AM by Umbrella; 3 AM avoids contention with both.

### Option A — schtasks command (one-liner)

```cmd
schtasks /create ^
  /tn "Technijian-DailyCrowdStrikePull" ^
  /tr "\"c:\vscode\annual-client-review\annual-client-review\technijian\crowdstrike-pull\run-daily-crowdstrike.cmd\"" ^
  /sc DAILY ^
  /st 03:00 ^
  /rl LIMITED ^
  /f
```

Verify:

```cmd
schtasks /query /tn "Technijian-DailyCrowdStrikePull" /v /fo LIST
schtasks /run /tn "Technijian-DailyCrowdStrikePull"
```

### Option B — Task Scheduler GUI

1. Open **Task Scheduler** -> Create Task...
2. Name: `Technijian-DailyCrowdStrikePull`
3. Triggers tab -> New -> Daily -> Start: 03:00 local
4. Actions tab -> New -> Program/script: `c:\vscode\annual-client-review\annual-client-review\technijian\crowdstrike-pull\run-daily-crowdstrike.cmd`
5. Conditions tab -> uncheck "Start the task only if the computer is on AC power"
6. Settings tab -> check "Run task as soon as possible after a scheduled start is missed"
7. **Run as the workstation user, not SYSTEM** — SYSTEM cannot read the
   OneDrive-synced keyfile.

Do NOT change the cadence without also updating
`%USERPROFILE%\.claude\skills\crowdstrike-daily-pull\SKILL.md`.

## 19. CrowdStrike tenancy: Flight Control vs single CID

The script auto-detects Falcon Flight Control by calling
`GET /mssp/queries/children/v1`. As of 2026-04-29, Technijian's tenant is a
**Flight Control parent with 36 child CIDs**, so the multi-tenant path is
active and per-client mapping is by `member_cid -> LocationCode`.

If Technijian ever consolidates to a single CID, the script falls back to a
hostname/tag-prefix bucketing scheme. Define prefixes in
`technijian\crowdstrike-pull\state\crowdstrike-cid-mapping.json` under the
`hostname_prefix` key. Same convention as Cisco Umbrella's prefix mapping.

## 20. Troubleshooting (CrowdStrike pull)

| Symptom | Cause | Fix |
| --- | --- | --- |
| `CrowdStrike credentials not found` | env vars unset and keyfile placeholder still present | Paste the Client Secret into the keyfile or set the env vars (section 16). |
| `HTTP 401` on every call | Secret rotated or client disabled | Reset Secret in Falcon Console -> Support and Resources -> API clients and keys; refresh the keyfile. |
| `HTTP 403` or `HTTP 404` on a specific service (e.g. Spotlight, Discover, CCID) | Scope not granted on this OAuth client, or product not licensed | Edit the API client in Falcon Console and tick the `<service>: Read` box. The pull continues with empty output for the missing scope. |
| `unmapped.json` non-empty | Child name does not match an active CP client name | Add a manual override in `technijian\crowdstrike-pull\state\crowdstrike-cid-mapping.json` and re-run. |
| One client has `errors[]` in its `pull_summary.json` but the rest succeeded | Partial endpoint failure | Re-run `python pull_crowdstrike_daily.py --only <CODE>`. |
| Wrong region (api.crowdstrike.com instead of api.us-2.crowdstrike.com) | Tenant migrated, env vars stale | Edit `**Base URL:**` in `crowdstrike.md` (auto-loaded into env by cs_api) or `setx CROWDSTRIKE_BASE_URL`. |
| Scheduled task ran but per-client folders are absent | Task ran as `SYSTEM` (no OneDrive sync) | Run the task as the workstation user, not SYSTEM. |

---

## 21. Teramind API credentials

Teramind on-premise server lives at `https://myaudit2.technijian.com`.
Auth uses an opaque access token sent via `X-Access-Token` header.

Keyfile: `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\teramind.md`

Required fields in the keyfile (already populated — verify before first run):

```markdown
**Base URL:** `https://myaudit2.technijian.com`
**Access Token:** `<40-char hex token>`
```

To regenerate the token if a 401 appears: log into the Teramind web portal
at `https://myaudit2.technijian.com` as `support@technijian.com`, go to
Settings -> Access Tokens, generate a new token, and paste the value back
into the keyfile.

Env-var override (headless / CI):

```cmd
setx TERAMIND_HOST        "https://myaudit2.technijian.com"
setx TERAMIND_ACCESS_TOKEN "2fd3b7a08c6cd..."
```

## 22. Teramind pull smoke test

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM Dry run -- no API calls
python technijian\teramind-pull\scripts\pull_teramind_daily.py --dry-run

REM Live run (today's 24 h window)
python technijian\teramind-pull\scripts\pull_teramind_daily.py
```

Expected output:

```text
Teramind daily pull
  Window : 2026-04-28T19:00:00+00:00 -> 2026-04-29T19:00:00+00:00
  Output : ...teramind-pull\2026-04-29
  Dry run: False

Pulling account info...
Pulling agents...
  5 active agent(s)
Pulling computers...
  2 active computer(s)
...
Done. 5 agents, 2 computers, 4 activity rows, 0 error(s)
```

Output files land in `technijian\teramind-pull\YYYY-MM-DD\` plus a run
log at `technijian\teramind-pull\state\YYYY-MM-DD.json`.

## 23. Schedule the daily Teramind pull (recommended)

Run this **once on the production workstation** (not the dev laptop).
Scheduled to 04:00 AM PT: 1 AM = Huntress, 2 AM = Umbrella, 3 AM = CrowdStrike.

```cmd
schtasks /create ^
  /tn "Technijian-DailyTeramindPull" ^
  /sc DAILY /st 04:00 ^
  /tr "c:\vscode\annual-client-review\annual-client-review\technijian\teramind-pull\run-daily-teramind.cmd" ^
  /ru "%USERNAME%" ^
  /f
```

Verify registration:

```cmd
schtasks /query /tn "Technijian-DailyTeramindPull" /fo LIST /v
```

Run manually:

```cmd
schtasks /run /tn "Technijian-DailyTeramindPull"
```

## 24. What the Teramind pull writes

```text
technijian/teramind-pull/YYYY-MM-DD/
  account.json              account settings (name, timezone, currency)
  agents.json + .csv        monitored employees (email, department, role)
  computers.json + .csv     monitored endpoints (name, fqdn, OS, IP, status)
  departments.json          department list
  behavior_groups.json      DLP rule group definitions
  behavior_policies.json    individual DLP policies (25 sample rules)
  activity.json             general app/productivity activity cube (24 h)
  keystrokes.json           keystroke log cube (24 h)
  web_search.json           web search query cube (24 h)
  social_media.json         social media activity cube (24 h)
  risk_scores.json          per-agent insider-threat score + percentile
  agent_details.json        per-agent activity detail (insider-threat API)
  last_devices.json         per-agent last-used devices
  run_log.json              pull summary: counts, window, errors

technijian/teramind-pull/state/YYYY-MM-DD.json    copy of run_log for state tracking
```

**Valid cubes on this installation (verified 2026-04-29):** `activity`,
`keystrokes`, `web_search`, `social_media`. Other cube names from Teramind
SaaS docs (`sessions`, `alerts`, `file_transfers`, `emails`, `cli`,
`printing`) return "unknown cube" on this server -- likely not licensed yet.
Update `CUBE_NAMES` in `teramind_api.py` when new modules are activated.

## 25. Troubleshooting (Teramind pull)

| Symptom | Cause | Fix |
| --- | --- | --- |
| `keyfile: **Base URL:** not found` | Keyfile missing `**Base URL:** \`https://...\`` line | Verify `keys/teramind.md` format matches section 21. |
| `HTTP 401: {"error":"Unauthorized"}` | Access token revoked or expired | Regenerate token in Teramind portal -> Settings -> Access Tokens; update keyfile. |
| `HTTP 500: Cube name provided '...' is unknown` | Cube not licensed on this server | Expected for non-activated modules; remove from `CUBE_NAMES` in `teramind_api.py`. |
| `SSL certificate verify failed` | On-premise self-signed cert | `teramind_api.py` already disables SSL verification for self-signed certs -- no action needed. |
| Zero activity rows but agents and computers show up | No monitoring agents have reported data yet | Normal for a newly enrolled system; data flows once agents are installed on client computers. |
| Scheduled task ran but output dir is absent | Task ran as `SYSTEM` (no OneDrive sync for keyfile path) | Run the task as the workstation user, not SYSTEM. |

---

## 26. ScreenConnect recording pipeline

Converts all monthly ScreenConnect session recordings to MP4 and drops them into
`OneDrive - Technijian, Inc\Technijian - My Remote - FileCabinet\{CLIENT}-{YEAR}-{MONTH}\`
(OneDrive auto-syncs to Teams). Also generates per-client audit CSVs
(`clients\{code}\screenconnect\{year}\{CLIENT}-SC-Audit-{year}.csv`) with
tech name, machine, duration, and Teams video link for every session.

**Run monthly on the 28th** — before the 30-day SC session purge closes the window.

Full setup details: `technijian\screenconnect-pull\workstation.md`

### Prerequisites

| Component | Notes |
| --- | --- |
| Python 3.11+ | Same as other pipelines |
| FFmpeg on PATH | `winget install --id Gyan.FFmpeg -e` |
| OneDrive signed in | FileCabinet folder must be syncing |
| Network access to 10.100.14.10 | TE-DC-MYRMT-01 (SC server) |
| R:\ mapped | `net use R: "\\10.100.14.10\E$\Myremote Recording" /persistent:yes` |

The converter EXE is bundled in the repo — no separate download:

```text
technijian\screenconnect-pull\bin\SessionCaptureProcessor\ScreenConnectSessionCaptureProcessor.exe
```

### Run the monthly pipeline

```cmd
c:\vscode\annual-client-review\annual-client-review\technijian\screenconnect-pull\run-monthly-sc.cmd
```

This script:

1. Maps `R:\` to the recordings share
2. Launches `SessionCaptureProcessor.exe` (GUI)
3. Runs `c:\tmp\sc_automate.ps1` to select all `R:\` files and start transcoding
4. Starts `c:\tmp\sc_watch_and_convert.py` in the background — monitors progress,
   then auto-runs FFmpeg compression (CRV AVI → MP4) and audit CSV regeneration

Monitor progress anytime:

```powershell
Get-Content c:\tmp\sc_watch.log -Tail 20
```

**Requires interactive session** — the GUI tool will not run as SYSTEM.
Schedule with "Run only when user is logged on".

### Register as monthly Task Scheduler job

```cmd
schtasks /create ^
  /tn "Technijian-MonthlyScreenConnectPull" ^
  /tr "\"c:\vscode\annual-client-review\annual-client-review\technijian\screenconnect-pull\run-monthly-sc.cmd\"" ^
  /sc MONTHLY /d 28 /st 20:00 ^
  /ru "%USERNAME%" ^
  /f
```

Verify / run on demand:

```cmd
schtasks /query /tn "Technijian-MonthlyScreenConnectPull" /v /fo LIST
schtasks /run   /tn "Technijian-MonthlyScreenConnectPull"
```

### Output locations

| Output | Path |
| --- | --- |
| MP4 videos | `C:\Users\rjain\OneDrive - Technijian, Inc\Technijian - My Remote - FileCabinet\{CLIENT}-{YEAR}-{MONTH}\` |
| Audit log | `...FileCabinet\_audit\audit_log.json` |
| Per-client CSV | `clients\{code}\screenconnect\{year}\{CLIENT}-SC-Audit-{year}.csv` |

## 27. Troubleshooting (ScreenConnect pipeline)

| Symptom | Fix |
| --- | --- |
| `R:\` not accessible | `net use R: "\\10.100.14.10\E$\Myremote Recording" /persistent:yes` |
| `ffmpeg not found` | `winget install --id Gyan.FFmpeg -e`, restart shell |
| GUI does not open | Check that the EXE exists at `technijian\screenconnect-pull\bin\SessionCaptureProcessor\` |
| `sc_automate.ps1` can't find window | Wait 5 seconds after GUI launches, then re-run the script manually |
| Watcher shows 0% progress after 10 min | GUI status bar should show "Transcoding..."; if blank, manually click "Choose Capture Files to Transcode", navigate to `R:\`, Ctrl+A, Open |
| 0-byte AVI on R:\ | Source file empty or in-progress — skipped automatically |
| `teams_url` empty in audit CSV | Watcher hasn't completed yet; re-run `build_client_audit.py --all --no-refresh-db` after watcher finishes |
