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

## 5. Claude Code skills

**New convention (as of 2026-04-29):** repo-specific skills live in the repo
itself at `<repo>/.claude/skills/<skill-name>/SKILL.md`. Claude Code
auto-discovers them when opened in the workspace — no copy step required.
Newly added skills (Meraki) ship inside the repo; they travel with the clone.

Skills currently bundled in this repo:

```
.claude\skills\meraki-pull\SKILL.md            (raw data pull, all orgs)
.claude\skills\meraki-monthly-report\SKILL.md  (monthly Word reports)
.claude\skills\proofread-report\SKILL.md       (DOCX quality gate)
```

**Legacy convention** (still applies to older Technijian skills):
some skills are still user-scoped on the original workstation. Copy these
to the same path on the new machine if you intend to use them:

```
%USERPROFILE%\.claude\skills\monthly-client-pull\SKILL.md
%USERPROFILE%\.claude\skills\weekly-time-audit\SKILL.md     (if present)
%USERPROFILE%\.claude\skills\huntress-daily-pull\SKILL.md
```

When migrating those, prefer moving them into the repo's
`.claude\skills\` so they become portable. The Python scripts these
skills wrap have always lived in the repo and run standalone — the
`%USERPROFILE%` location only governs Claude Code skill discovery.

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

Converts all ScreenConnect session recordings to MP4, organises them into
`OneDrive - Technijian, Inc\Technijian - My Remote - FileCabinet\{CLIENT}-{YEAR}-{MONTH}\`,
then regenerates per-client audit CSVs (`clients\{code}\screenconnect\{year}\{CLIENT}-SC-Audit-{year}.csv`)
with the OneDrive video link in every row.

**Run monthly on the 28th** — before the 30-day SC session purge closes the window.
The pipeline is designed to run on any domain-joined workstation that can reach
`\\10.100.14.10` — it does not need to be the SC server itself.

### 26.1 Prerequisites

| Component | Version | Notes |
| --- | --- | --- |
| Python | 3.11+ | Tested on 3.14.3 at `C:\Python314\python.exe` |
| FFmpeg | any modern | `winget install --id Gyan.FFmpeg -e` then verify: `ffmpeg -version` |
| OneDrive (Technijian tenant) | signed in | Syncs FileCabinet folder; keyfiles at `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\` |
| Network access to 10.100.14.10 | on-LAN or VPN | SC server (TE-DC-MYRMT-01) must be reachable |

The `SessionCaptureProcessor.exe` converter is **bundled in the repo** — no
separate download needed:

```text
technijian\screenconnect-pull\bin\SessionCaptureProcessor\ScreenConnectSessionCaptureProcessor.exe
```

### 26.2 Map the recordings share

Run once per session (or make persistent with `/persistent:yes`):

```cmd
net use R: "\\10.100.14.10\E$\Myremote Recording" /persistent:yes
```

Verify: `dir R:\ | find /c ""` should show ~2800+ files.

### 26.3 Transcode CRV → AVI (GUI, one-time or monthly)

The SessionCaptureProcessor converts ScreenConnect's proprietary `.crv` format
to `.avi`. It is a GUI tool; use the automation script to drive it hands-free.

#### Option A — fully automated (recommended for scheduled / remote runs)

```powershell
# From an elevated PowerShell
Start-Process python -ArgumentList "technijian\screenconnect-pull\scripts\sc_automate.ps1" -WindowStyle Normal
```

Or run the PowerShell script directly:

```powershell
powershell -ExecutionPolicy Bypass -File technijian\screenconnect-pull\scripts\sc_automate.ps1
```

`sc_automate.ps1` (committed at `technijian\screenconnect-pull\scripts\sc_automate.ps1`) will:

1. Find the running `ScreenConnectSessionCaptureProcessor.exe` window
2. Check the **"Transcode after download"** box
3. Click **"Choose Capture Files to Transcode"**
4. Navigate to `R:\` and select all files (Ctrl+A)
5. Click **Open** to start transcoding

The GUI must be open before running the script. Launch it from the repo:

```cmd
start "" "c:\vscode\annual-client-review\annual-client-review\technijian\screenconnect-pull\bin\SessionCaptureProcessor\ScreenConnectSessionCaptureProcessor.exe"
```

Wait ~2 seconds for it to fully load, then run the automation script.

#### Option B — manual

1. Open `technijian\screenconnect-pull\bin\SessionCaptureProcessor\ScreenConnectSessionCaptureProcessor.exe`
2. **Check "Transcode after download"**
3. Click **"Choose Capture Files to Transcode"**
4. In the file picker: navigate to `R:\`, press **Ctrl+A**, click **Open**
5. Leave the window open — do not close it while transcoding

**Output location:** AVIs are written alongside the source files on `R:\` (same
directory), with `.avi` appended to the original filename. The "Download Directory"
field (`C:\tmp\sc_avis`) applies only to the server-download workflow, not local
transcoding.

**Time estimate:** ~8 hours for 2,800 files. Run overnight.

### 26.4 Watch + auto-convert (background, hands-free)

Start the watcher immediately after launching the GUI transcoding. It polls every
5 minutes and automatically triggers AVI→MP4 compression and audit CSV regeneration
when the AVI count stabilises.

```powershell
Start-Process python -ArgumentList "technijian\screenconnect-pull\scripts\sc_watch_and_convert.py" -WindowStyle Hidden `
    -RedirectStandardOutput "c:\tmp\sc_watch_stdout.txt" `
    -RedirectStandardError  "c:\tmp\sc_watch_stderr.txt"
```

Monitor progress anytime:

```powershell
Get-Content "c:\tmp\sc_watch.log" -Tail 20
```

### 26.5 Compress AVI → MP4 into OneDrive FileCabinet

> Handled automatically by the watcher — only run manually if the watcher was
> not started.

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

python technijian\screenconnect-pull\scripts\pull_screenconnect_2026.py ^
    --from-avi-dir R:\ --no-refresh-db
```

Output per client:

```text
C:\Users\rjain\OneDrive - Technijian, Inc\Technijian - My Remote - FileCabinet\
  {CLIENT}-{YEAR}-{MONTH}\
    {YYYYMMDD}_{CLIENT}_{session8}_{conn8}.mp4
  _audit\
    audit_log.json
    audit_log.csv
```

OneDrive desktop sync auto-uploads everything in that folder to Teams.

### 26.6 Regenerate per-client audit CSVs

> Handled automatically by the watcher — only run manually if the watcher was
> not started.

```cmd
python technijian\screenconnect-pull\scripts\build_client_audit.py ^
    --all --year 2026 --no-refresh-db
```

Output per client:

```text
clients\{client}\screenconnect\2026\
  {CLIENT}-SC-Audit-2026.csv    (recording_start, tech_name, machine, teams_url, ...)
  {CLIENT}-SC-Audit-2026.json
```

### 26.7 Monthly wrapper (all steps combined)

```cmd
c:\vscode\annual-client-review\annual-client-review\technijian\screenconnect-pull\run-monthly-sc.cmd
```

This wrapper:

1. Launches the SessionCaptureProcessor GUI
2. Runs `sc_automate.ps1` to start GUI transcoding
3. Starts `sc_watch_and_convert.py` in the background
4. Logs to `technijian\screenconnect-pull\state\run-YYYY-MM-DD.log`

**The wrapper requires an interactive logged-in user session** (the GUI tool
will not run as SYSTEM or in a non-interactive session). Schedule it via Task
Scheduler with the option "Run only when user is logged on".

### 26.8 Register as a monthly Task Scheduler job

```cmd
schtasks /create ^
  /tn "Technijian-MonthlyScreenConnectPull" ^
  /tr "\"c:\vscode\annual-client-review\annual-client-review\technijian\screenconnect-pull\run-monthly-sc.cmd\"" ^
  /sc MONTHLY /d 28 /st 20:00 ^
  /ru "%USERNAME%" ^
  /f
```

The `.cmd` file is self-locating — it derives all paths from its own location,
so the only hardcoded value is the path to the `.cmd` itself.

Runs on the **28th of each month at 8 PM** — before the 30-day purge would
remove recordings from the beginning of the month.

Verify:

```cmd
schtasks /query /tn "Technijian-MonthlyScreenConnectPull" /v /fo LIST
```

Run on demand:

```cmd
schtasks /run /tn "Technijian-MonthlyScreenConnectPull"
```

### 26.9 Output locations

| Output | Path |
| --- | --- |
| MP4 videos | `C:\Users\rjain\OneDrive - Technijian, Inc\Technijian - My Remote - FileCabinet\{CLIENT}-{YEAR}-{MONTH}\` |
| Audit log | `...FileCabinet\_audit\audit_log.json` |
| Per-client CSV | `clients\{code}\screenconnect\{year}\{CLIENT}-SC-Audit-{year}.csv` |

### 26.10 Server paths (TE-DC-MYRMT-01 — 10.100.14.10)

| What | Path |
| --- | --- |
| SQLite DB | `\\10.100.14.10\C$\Program Files (x86)\ScreenConnect\App_Data\Session.db` |
| Raw recordings (CRV) | `\\10.100.14.10\E$\Myremote Recording\` (no file extension) |
| Mapped drive | `R:\` → `\\10.100.14.10\E$\Myremote Recording` |
| SC install | `\\10.100.14.10\C$\Program Files (x86)\ScreenConnect\` |
| Converter (bundled) | `technijian\screenconnect-pull\bin\SessionCaptureProcessor\ScreenConnectSessionCaptureProcessor.exe` |

**SC API key** (for SessionCaptureProcessor GUI): stored in SC admin panel at
`https://myremote2.technijian.com → Administration → Extensions → Session
Capture Processor → Edit Settings → Custom ApiKey`. Current key:
`TechSCCapture2026!` (stored in
`%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\screenconnect-web.md`).

Recording filename pattern:

```text
{SessionID}-{ConnectionID}-{YYYY}-{MM}-{DD}-{HH}-{mm}-{ss}-{YYYY}-{MM}-{DD}-{HH}-{mm}-{ss}
```

Session IDs in the SQLite DB are 16-byte .NET mixed-endian BLOBs.
Use `uuid.UUID(bytes_le=raw)` to match against recording filenames.

**30-day purge:** SC purges session events older than 30 days. As of 2026-04-29
only April 2026 events exist. Run before the 28th of each month to capture the
full previous month.

### 26.11 Scope (2026-04-29 snapshot)

- 2,838 recordings across 22 clients, ~19.2 GB raw
- Largest: JDH (1,016 recs / 14 GB), Technijian (696 / 1.9 GB), ORX (348 / 902 MB)
- Tech name coverage gaps: where SessionEvent purged before 30-day window

## 27. Troubleshooting (ScreenConnect pipeline)

| Symptom | Fix |
| --- | --- |
| `R:\` not accessible | `net use R: "\\10.100.14.10\E$\Myremote Recording" /persistent:yes` |
| `ffmpeg not found` | `winget install --id Gyan.FFmpeg -e`, restart shell |
| GUI does not open | Check that the EXE exists at `technijian\screenconnect-pull\bin\SessionCaptureProcessor\` |
| GUI "Unable to read beyond the end of the stream" | Normal on startup; only appears when using the API query path, not "Choose Capture Files to Transcode" |
| `sc_automate.ps1` can't find window | Wait 5 seconds after GUI launches, then re-run the script manually |
| Watcher shows 0% progress after 10 min | GUI status bar should show "Transcoding..."; if blank, manually click "Choose Capture Files to Transcode", navigate to `R:\`, Ctrl+A, Open |
| Watcher log stuck at 0% | Check `c:\tmp\sc_watch_stdout.txt` for errors; verify GUI is showing "Transcoding..." in status bar |
| 0-byte AVI on R:\ | Source recording is empty or was in-progress; script skips it |
| `mp4_path` / `teams_url` missing from audit CSV | Watcher hasn't finished yet; re-run `build_client_audit.py --all --no-refresh-db` after watcher completes |
| SC session purged (no client in DB) | Expected for older sessions; recording skipped automatically |

---

## 28. Cisco Meraki API credentials

The daily Cisco Meraki pull (`scripts\meraki\pull_all.py`) reads
credentials from either an env var or the OneDrive-synced markdown file.
Pick one.

### Option A — environment variable (recommended for headless runs)

```cmd
setx MERAKI_API_KEY "<40 hex chars>"
```

### Option B — OneDrive keyvault file

Make sure OneDrive has finished syncing this file:

```text
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\meraki.md
```

It must contain a line like:

```markdown
**API Key:** 53417a9ed1031c8221ac961eb88eca2ec3d5b529
```

`meraki_api.get_api_key()` falls back to this file when the env var is
absent (regex grabs the first 40-hex token under `**API Key:**`).

The key is generated in **Meraki Dashboard → My Profile → API access**.
Auth uses **Bearer** (`Authorization: Bearer <key>`) — the legacy
`X-Cisco-Meraki-API-Key` header is rejected by keys created in 2026+.

The key gives admin access to every Meraki organization the owning user is
administered on. The current personal key (`rjain@technijian.com`) covers
**9 orgs**: `technijian_inc`, `technijian` (dormant), `vaf`, `aranda_tooling`,
`aoc`, `bwh`, `gsc` (dormant), `orx`, `vg`. Two orgs return 403 because
they have no active device licenses; the pipeline skips them silently.

**Long-term recommendation:** generate a fresh key from a service-account
user (`meraki-api@technijian.com`) and replace this one. Personal keys die
with 2FA rotations or staff changes.

## 29. Meraki pull smoke test

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM Auth + key vault probe — prints owner identity
python -c "import sys; sys.path.insert(0, r'scripts\meraki'); import meraki_api as m; me = m.whoami(); print(me['name'], '-', me['email'])"

REM Org list — should print 9 orgs with API status
python -c "import sys; sys.path.insert(0, r'scripts\meraki'); import meraki_api as m; [print(o['id'], o['name']) for o in m.list_organizations()]"

REM One org, last 24h — confirms write paths
python scripts\meraki\pull_security_events.py --only vaf --days 1
python scripts\meraki\pull_network_events.py --only technijian_inc --days 1
python scripts\meraki\pull_configuration.py --only aoc
```

After the third command, expect output at:
- `clients\<code>\meraki\security_events\YYYY-MM-DD.json`
- `clients\<code>\meraki\network_events\<network_slug>\YYYY-MM-DD.json`
- `clients\<code>\meraki\networks\<network_slug>\<endpoint>.json` (~30 files per network)

Where `<code>` is the existing client folder name (`technijian`, `arnd`, `aoc`, `bwh`, `orx`, `vaf`, `vg`). Mapping from Meraki org slug to client code lives in `scripts\meraki\_org_mapping.py`.

## 30. Schedule the Meraki pulls (recommended)

With India running 24×7, run **two separate cadences** for Meraki:

| Task | Cadence | What it runs | Why |
|---|---|---|---|
| `Technijian-MerakiSecurityPull` | Every 4 hours | `pull_security_events.py` | IDS/IPS + AMP detections — 24×7 team can respond within one watch rotation |
| `Technijian-DailyMerakiPull` | Daily 05:00 | `pull_all.py` (network events + config) | Network events and config snapshots don't require intraday cadence |

### Task 1 — every-4-hour security events pull

Register a task that fires daily at midnight and repeats every 4 hours:

```cmd
schtasks /create ^
  /tn "Technijian-MerakiSecurityPull" ^
  /tr "C:\Python314\python.exe c:\vscode\annual-client-review\annual-client-review\scripts\meraki\pull_security_events.py --skip technijian,gsc --days 1" ^
  /sc DAILY ^
  /st 00:00 ^
  /ri 240 ^
  /du 0024:00 ^
  /ru "%USERNAME%" ^
  /f
```

The `--days 1` flag means each run refreshes today's IDS/IPS event file. Reruns are idempotent — same-day files are overwritten. If an org has an active intrusion, India sees the updated event list within 4 hours of the alert appearing in the Meraki Dashboard.

### Task 2 — daily full pull (network events + config)

```cmd
schtasks /create ^
  /tn "Technijian-DailyMerakiPull" ^
  /tr "C:\Python314\python.exe c:\vscode\annual-client-review\annual-client-review\scripts\meraki\pull_all.py --skip technijian,gsc" ^
  /sc DAILY ^
  /st 05:00 ^
  /ru "%USERNAME%" ^
  /f
```

1 AM = Huntress, 2 AM = Umbrella, 3 AM = CrowdStrike, 4 AM = Teramind, 5 AM = Meraki full pull.

Verify / run on demand:

```cmd
schtasks /query /tn "Technijian-MerakiSecurityPull" /v /fo LIST
schtasks /query /tn "Technijian-DailyMerakiPull"    /v /fo LIST
schtasks /run   /tn "Technijian-MerakiSecurityPull"
schtasks /run   /tn "Technijian-DailyMerakiPull"
```

Same SYSTEM-vs-user caveat as the other pulls — task must run as the
workstation user so the OneDrive keyvault file is readable.

## 31. What the Meraki pull writes

```text
clients\<code>\meraki\
  org_meta.json
  networks.json
  devices.json
  config_snapshot_at.json                      coverage report
  security_events\YYYY-MM-DD.json              IDS/IPS + AMP per day (org-wide)
  network_events\<network_slug>\YYYY-MM-DD.json  firewall/VPN/DHCP events per day
  networks\<network_slug>\<endpoint>.json      ~30 config endpoints (firewall L3/L7/inbound,
                                               IDS/IPS settings, AMP, content filtering,
                                               VLANs, S2S VPN, SSIDs, switch ACLs, etc.)
  monthly\YYYY-MM.json                         aggregated summary (input to docx)
  reports\<Org Name> - Meraki Monthly Activity - YYYY-MM.docx

clients\_meraki_logs\
  security_events_pull_log.json
  network_events_pull_log.json
  configuration_pull_log.json
  monthly_index.json
```

`<code>` is the existing client folder name (e.g. `aoc`, `bwh`, `vaf`, `orx`, `vg`,
`technijian`, `arnd`). The Meraki-org-slug → client-code mapping lives in
`scripts\meraki\_org_mapping.py` — add an entry there when onboarding a new org.

Daily event files are **idempotent on re-run** — same-day reruns overwrite
that day's file. Configuration snapshots overwrite the whole snapshot tree.

## 32. Backfill historical Meraki data

```cmd
REM Full year-to-date for all licensed orgs
python scripts\meraki\pull_security_events.py --skip technijian,gsc --since 2026-01-01 --until 2026-04-29
python scripts\meraki\pull_network_events.py  --skip technijian,gsc --since 2026-01-01 --until 2026-04-29

REM One org, range
python scripts\meraki\pull_security_events.py --only vaf --since 2026-03-01 --until 2026-03-31
```

The 2026-01 to 2026-04 backfill takes ~5 minutes for security events
(org-wide endpoint, only ~1 call per org per day) and ~30-60 minutes
for network events (per-network, paginated through the events endpoint
which doesn't natively accept time bounds — see gotcha in `meraki-pull`
SKILL.md).

## 33. Generate monthly activity reports

After daily files are present:

```cmd
REM Aggregate -> JSON summary
python scripts\meraki\aggregate_monthly.py --month 2026-03

REM Render Word reports (auto-runs proofread_docx.py at the end)
python scripts\meraki\generate_monthly_docx.py --month 2026-03
```

Each report goes through the proofread gate
(`technijian\shared\scripts\proofread_docx.py` — 7 scored checks + 2
warnings). The generator exits non-zero if any report fails.

`generate_monthly_docx.py` requires `pip install python-docx`; the pull
scripts use stdlib only.

## 34. Troubleshooting (Meraki pull)

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Meraki API key not found` | env var unset and keyfile placeholder still present | Paste the API key into `keys\meraki.md` under `**API Key:**` or `setx MERAKI_API_KEY`. |
| `HTTP 401 No valid authentication method found` | Sent the legacy `X-Cisco-Meraki-API-Key` header | Switch to `Authorization: Bearer <key>`. The shipped client already does this; only relevant if you write custom scripts. |
| `HTTP 403 Meraki API services are available for licensed Meraki devices only` | Org has no active device licenses | Add the org slug to `--skip`, or renew licensing in Dashboard → Organization → License info. The pipeline already skips `technijian` and `gsc` by default in scheduled runs. |
| Network events return 1000 events per day always | Direct call to `/networks/{id}/events` with `t0`/`t1` (the endpoint silently ignores time params) | Use `meraki_api.get_network_events()` — it walks back via `endingBefore=pageStartAt` and filters client-side to the requested window. |
| Some networks show "0 events" while others show thousands | Wrong `--product-type` for the network's hardware mix | VAF is wireless-only, AOC has a single appliance, etc. Re-run with `--product-type wireless` or `switch` for the right layer. |
| Configuration endpoint returns 400 | "Feature not enabled / not licensed" on this network (e.g., VLANs disabled, IDS not licensed) | Recorded in `config_snapshot_at.json` coverage report. Normal — no action needed. |
| Report fails proofread "Missing section: 'X'" | Section name in `EXPECTED_SECTIONS` doesn't match rendered text | Open the doc, find the actual heading, update the constant in `generate_monthly_docx.py`. |
| Monthly report shows "0" for events but daily files exist | Day boundaries: monthly aggregation uses YYYY-MM-DD prefix; verify file names match | Check `clients\<code>\meraki\security_events\` filenames are `YYYY-MM-DD.json`, not Excel-style or anything else. |
| Scheduled task ran but per-org folders are absent | Task ran as `SYSTEM` (no OneDrive sync for keyfile) | Run the task as the workstation user (`/ru "%USERNAME%"`), not SYSTEM. |

---

## 35. Microsoft 365 / Graph API credentials

The M365 pull scripts (`technijian\m365-pull\scripts\`) authenticate via an
Azure AD **application registration** using the client-credentials flow
(app-only, no interactive login). Each client tenant must have admin-consented
this app before data can be pulled.

### App registration details

| Field | Value |
|---|---|
| App name | Technijian-Partner-Graph-Read |
| App (client) ID | `5cbc8ba3-2795-4129-9258-b41102cac82e` |
| Tenant | Technijian (`cab8077a-3f42-4277-b7bd-5c9023e826d8`) |
| Auth flow | Client credentials (app-only) |
| Redirect URI | `https://login.microsoftonline.com/common/oauth2/nativeclient` (Mobile and desktop) |

### Credentials — Option A: environment variables (recommended for headless)

```cmd
setx M365_CLIENT_ID     "5cbc8ba3-2795-4129-9258-b41102cac82e"
setx M365_CLIENT_SECRET "<secret from Azure AD>"
setx M365_TENANT_ID     "cab8077a-3f42-4277-b7bd-5c9023e826d8"
```

### Credentials — Option B: OneDrive keyvault file

```text
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\m365.md
```

Must contain:

```markdown
**Client ID:** 5cbc8ba3-2795-4129-9258-b41102cac82e
**Client Secret:** <secret>
**Tenant ID:** cab8077a-3f42-4277-b7bd-5c9023e826d8
```

`m365_api.py` reads env vars first; falls back to this file via regex.

### GDAP client list

`technijian\m365-pull\state\gdap_status.csv` is the single source of truth
for which client tenants to pull. Each row requires `status=approved` and a
valid `tenant_id`. Remove a row to skip a client; set `status=pending` to
pause without deleting.

**Tenants approved and consented (as of 2026-04-30):** TECHNIJIAN, B2I, CBI,
NOR, VAF, SAS, AOC, ACU, BWH, HHOC, ORX (11 tenants).

**Tenants approved but pending app consent:** CBL, CCC, JRM, MRM, KES, JDH,
RMG (7 tenants). Run `consent_clients.ps1` to grant consent interactively
(see section 36).

## 36. Granting app consent to new client tenants

Admin consent must be granted once per tenant before the app can read that
tenant's Graph data. The consent URL opens a browser tab; a GA for that
tenant must accept.

```powershell
# Run from the repo root — opens one browser tab per tenant, prompts Enter between each
.\technijian\m365-pull\scripts\consent_clients.ps1
```

For GDAP tenants (where Technijian has Global Administrator via Partner
Center), sign in as the Technijian admin first, then run the script. For
Cloud Reseller tenants, the client's own GA must accept.

After consenting, verify access:

```cmd
python technijian\m365-pull\scripts\check_access.py
```

Expected output: `HAVE_ACCESS` for every newly consented tenant. Tenants that
still show `NO_ACCESS` need re-consent or a GDAP relationship check.

## 37. M365 pull smoke test

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM Access probe — token + subscribed SKUs for each approved tenant
python technijian\m365-pull\scripts\check_access.py

REM Compliance dry-run — shows which tenants would be pulled, no API calls
python technijian\m365-pull\scripts\pull_m365_compliance.py --dry-run

REM Security dry-run
python technijian\m365-pull\scripts\pull_m365_security.py --dry-run

REM One tenant, compliance only — confirms write paths
python technijian\m365-pull\scripts\pull_m365_compliance.py --only BWH --month 2026-04

REM One tenant, last 6h security
python technijian\m365-pull\scripts\pull_m365_security.py --only BWH --hours 6
```

Files land at `clients\bwh\m365\compliance\2026-04\` (9 files) and
`clients\bwh\m365\<YYYY-MM-DD>\` (3 files). Run logs at
`technijian\m365-pull\state\`.

## 38. Schedule the M365 security pull (every 4 hours)

India runs 24×7. Every-4-hour cadence means the team sees new sign-in
threats within one watch rotation (≤4h detection lag).

**Standard cadence — all tenants, every 4 hours:**

```cmd
schtasks /create ^
  /tn "Technijian-M365SecurityPull" ^
  /tr "C:\Python314\python.exe c:\vscode\annual-client-review\annual-client-review\technijian\m365-pull\scripts\pull_m365_security.py --hours 6 --workers 6" ^
  /sc DAILY ^
  /st 00:00 ^
  /ri 240 ^
  /du 0024:00 ^
  /ru "%USERNAME%" ^
  /f
```

`--hours 6` gives a 6-hour window with 2h overlap on each end to avoid
missing events at the seam between runs.

**Escalation cadence — active-attack tenants only, every 2 hours:**

Use this when a tenant is under an active credential-stuffing or password-
spray campaign (e.g., AAOC at 82% failure rate, BWH at 68%). Remove the
`--only` flag once the failure rate drops below 10% in consecutive pulls.

```cmd
schtasks /create ^
  /tn "Technijian-M365SecurityPull-ActiveThreats" ^
  /tr "C:\Python314\python.exe c:\vscode\annual-client-review\annual-client-review\technijian\m365-pull\scripts\pull_m365_security.py --only AAOC,BWH --hours 3 --workers 2" ^
  /sc DAILY ^
  /st 00:00 ^
  /ri 120 ^
  /du 0024:00 ^
  /ru "%USERNAME%" ^
  /f
```

Verify / run on demand:

```cmd
schtasks /query /tn "Technijian-M365SecurityPull"               /v /fo LIST
schtasks /query /tn "Technijian-M365SecurityPull-ActiveThreats" /v /fo LIST
schtasks /run   /tn "Technijian-M365SecurityPull"
```

## 39. Schedule the M365 compliance pull (weekly)

Compliance posture (MFA %, CA policies, admin roles, Secure Score) does not
change intraday — weekly is the right cadence.

```cmd
schtasks /create ^
  /tn "Technijian-WeeklyM365CompliancePull" ^
  /tr "C:\Python314\python.exe c:\vscode\annual-client-review\annual-client-review\technijian\m365-pull\scripts\pull_m365_compliance.py --workers 6" ^
  /sc WEEKLY ^
  /d MON ^
  /st 07:00 ^
  /ru "%USERNAME%" ^
  /f
```

Verify / run on demand:

```cmd
schtasks /query /tn "Technijian-WeeklyM365CompliancePull" /v /fo LIST
schtasks /run   /tn "Technijian-WeeklyM365CompliancePull"
```

## 40. Schedule the M365 storage pull (weekly)

```cmd
schtasks /create ^
  /tn "Technijian-WeeklyM365StoragePull" ^
  /tr "C:\Python314\python.exe c:\vscode\annual-client-review\annual-client-review\technijian\m365-pull\scripts\pull_m365_storage.py --period D7 --workers 6" ^
  /sc WEEKLY ^
  /d MON ^
  /st 07:30 ^
  /ru "%USERNAME%" ^
  /f
```

Storage runs 30 minutes after compliance to avoid API rate-limit contention
on the same tenants.

Verify / run on demand:

```cmd
schtasks /query /tn "Technijian-WeeklyM365StoragePull" /v /fo LIST
schtasks /run   /tn "Technijian-WeeklyM365StoragePull"
```

## 41. Generate M365 monthly reports

After compliance + storage data is on disk for the target month:

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM Build all reports for the current month
python technijian\m365-pull\scripts\build_m365_monthly_report.py

REM Specific month
python technijian\m365-pull\scripts\build_m365_monthly_report.py --month 2026-04

REM One client only
python technijian\m365-pull\scripts\build_m365_monthly_report.py --only BWH,ORX
```

Each report is automatically proofread (8/8 checks) before being written to
`clients\<code>\m365\reports\<YYYY-MM>\<CODE>-M365-Activity-<YYYY-MM>.docx`.
The generator exits non-zero if any report fails the gate.

Tenants with `pending app consent` in their `gdap_status.csv` notes row are
skipped automatically — they have no real data on disk yet.

## 42. What the M365 pulls write

```text
clients\<code>\m365\
  compliance\<YYYY-MM>\
    secure_score.json
    conditional_access.json
    security_defaults.json
    mfa_registration.json
    admin_roles.json
    guest_users.json
    subscribed_skus.json
    user_licenses.json          per-user SKU assignments (license inventory)
    compliance_summary.json     posture checks: pass/warn/fail per item

  storage\<YYYY-Wnn>\
    mailbox_usage.json
    onedrive_usage.json
    sharepoint_usage.json
    storage_summary.json        alerts at >=75% / >=90% quota

  <YYYY-MM-DD>\                 security pull output (one dir per run date)
    signins.json                sign-in events for the window
    threat_summary.json         brute-force targets, spray IPs, flags
    risky_signins.json          atRisk / remediated events (P2 only)
    pull_summary.json           counts, window, errors

  reports\<YYYY-MM>\
    <CODE>-M365-Activity-<YYYY-MM>.docx

technijian\m365-pull\state\
  gdap_status.csv               source of truth: approved tenants + tenant IDs
  compliance-<YYYY-MM>.json     compliance run log
  storage-<YYYY-Wnn>.json       storage run log
  security-<YYYY-MM-DD>.json    security run log
  tickets-<YYYY-MM>-<ts>.json   CP ticket creation receipt
```

## 43. Troubleshooting (M365 pulls)

| Symptom | Cause | Fix |
|---|---|---|
| `M365 credentials not found` | Env vars unset and `m365.md` keyfile missing | Set env vars (section 35) or create the keyfile. |
| `AADSTS7000229: Service principal not found` | App has not been admin-consented in this tenant | Run `consent_clients.ps1` (section 36) for that tenant. |
| `AADSTS500113: No reply address registered` | Redirect URI missing from the Azure app registration | In Azure Portal → App registrations → Authentication → Add platform → Mobile and desktop → add `https://login.microsoftonline.com/common/oauth2/nativeclient`. |
| `AADSTS65001: User has not consented` | Consent URL used wrong tenant GUID | Verify `tenant_id` in `gdap_status.csv` matches the client's actual Azure tenant ID (check Partner Center or Azure AD). |
| `HTTP 403` on sign-in log endpoint | Tenant does not have Azure AD Premium P1 | Sign-in audit logs require P1 or above. The compliance and storage pulls still work. The security pull records the 403 in `errors[]` and continues. |
| `HTTP 403` on risky sign-in / risky user endpoint | Requires Azure AD Premium P2 | Expected for tenants without P2. Section omitted from the report automatically. |
| `HTTP 403` on usage reports | Report anonymization enabled on tenant | `m365_api.py` auto-falls back to CSV format. Display names appear as hashed values — toggle anonymization off in M365 Admin Center → Reports → Settings to restore real names. |
| Chunked sign-in pull times out for large tenants | Tenant has 10k+ sign-ins in the window | Add `--chunk-hours 12` (or lower) to the security pull command. Default is 24h per chunk; TECHNIJIAN and BWH needed 24h chunks to complete. |
| One tenant shows `errors[]` but others succeeded | Partial API failure for that tenant | Re-run `--only <CODE>` once the issue clears. |
| `pending app consent` tenant keeps being skipped | Notes field in `gdap_status.csv` still has the phrase | Update or remove the phrase after consent is granted and `check_access.py` confirms `HAVE_ACCESS`. |
| Scheduled task ran but folders are absent | Task ran as `SYSTEM` (no OneDrive sync for keyfile) | Run the task as the workstation user, not SYSTEM. |
## 44. Cisco Umbrella API credentials

The daily Umbrella pull (`technijian\umbrella-pull\scripts\pull_umbrella_daily.py`)
reads credentials from a OneDrive-synced markdown file. **Do not install the
task on the development laptop** — only the production workstation runs the
schedule.

### Prerequisites

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

### Verify the credentials work

```cmd
cd c:\vscode\annual-client-review\annual-client-review
C:\Python314\python.exe -c "import sys; sys.path.insert(0, r'technijian\umbrella-pull\scripts'); import umbrella_api as u; print('token_len:', len(u.get_token())); print('users:', len(u.list_users()))"
```

A clean run prints a token length (~5780 chars for a JWT) and the user count
for the parent Umbrella org. A `RuntimeError` containing
`Cisco Umbrella credentials not found` means the keyfile is missing or both
fields are still blank/TODO. A `401` from any endpoint means the key/secret
pair is wrong, revoked, or expired.

## 45. Umbrella pull smoke test

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

## 46. Schedule the daily Umbrella pull

Run as the workstation user (NOT SYSTEM — OneDrive paths must resolve), in an
elevated PowerShell:

```powershell
$action  = New-ScheduledTaskAction -Execute "c:\vscode\annual-client-review\annual-client-review\technijian\umbrella-pull\run-daily-umbrella.cmd"
$trigger = New-ScheduledTaskTrigger -Daily -At 2:00am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest

Register-ScheduledTask -TaskName "Technijian-DailyUmbrellaPull" `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Daily 2 AM PT pull of last 24h Cisco Umbrella data per active client."
```

**Cadence rationale:** 2:00 AM PT runs **after** the 1:00 AM Huntress pull
(`Technijian-DailyHuntressPull`) and **before** the 7:00 AM monthly-pull /
Friday weekly-audit. This avoids API/DB contention. The activity sample
(`/reports/v2/activity`, capped at 5000 records) is the most expensive call
per run; budgeting one hour is plenty.

To remove later:

```powershell
Unregister-ScheduledTask -TaskName "Technijian-DailyUmbrellaPull" -Confirm:$false
```

## 47. Per-day Umbrella artifacts

After a 2 AM run completes:

- `clients\<code>\umbrella\<YYYY-MM-DD>\` for every mapped client (currently
  just VAF until additional clients are mapped via
  `state/umbrella-prefix-mapping.json`).
- `technijian\umbrella-pull\<YYYY-MM-DD>\` with the account-level summary,
  full deployment inventory, mapping resolution, activity sample, and run log.
- `technijian\umbrella-pull\state\<YYYY-MM-DD>.json` — the same run log,
  surfaced where the other Technijian schedules write their state.
- `technijian\umbrella-pull\state\run-<YYYY-MM-DD>.log` — stdout/stderr from
  the cmd wrapper.

## 48. Triage (Umbrella pull)

- `unmapped.json` non-empty → a hostname-prefix has no CP `LocationCode`
  match. Either add an entry to `state/umbrella-prefix-mapping.json`'s
  `manual` block (`"<PREFIX>": "<LOCATIONCODE>"`) or add the prefix to
  `ignore` if it should never produce a per-client folder (e.g. `DESKTOP-*`
  default Windows hostnames).
- `401 Missing or invalid credentials` from any endpoint → the API Key /
  Secret was rotated. Refresh the keyfile and rerun the smoke test.
- A particular client's `pull_summary.json` has entries in `errors[]` but the
  rest of the run succeeded → partial failure for that client. The other
  artifacts captured what was reachable. Re-run with `--only <CODE>` once the
  underlying issue is resolved.
- `activity sample failed: HTTP 400 invalid timestamp` → the activity
  endpoint expects Unix-millis or relative time (`-24hours`, `now`), not
  ISO. The `umbrella_api.py` helper auto-converts ISO; if you see this, the
  conversion logic regressed.
- `pulled 5000 activity records (sample)` and the count is exactly 5000 →
  the cap is hit. The 24h window had more than 5000 events; the per-client
  rollups are still accurate for the events sampled but a downstream
  consumer doing month aggregation should walk activity in 1-hour chunks
  rather than relying on the daily snapshot.

## 49. Backfilling Umbrella history (one-time)

Cisco Umbrella's `/reports/v2/activity` retention is **~90 days** for
Technijian's plan (verified 2026-04-29: data available back to ~2026-01-30,
nothing older). Snapshot data (roaming computers, sites, internal networks,
destination lists) does **not** have a per-day history at all — the API only
returns the current state.

### API hard limits (verified 2026-04-29)

| Limit | Value | Implication |
|---|---|---|
| `/reports/v2/activity` page_limit | <= 5000 | bigger pages cut API calls 4-5x; HTTP 400 if you exceed |
| `/reports/v2/activity` offset | <= 10000 | hard cap of 10K records per (from, to) window |
| Activity retention | ~90 days | older windows return [] silently |

Walking raw activity for a busy day means the offset cap kicks in around
hour 2 — meaning 24h windows cap out at 240K records and busy hours alone
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

This is on-demand only — **no scheduled task for the backfill**. Re-run when
a fresh client onboards onto Umbrella, or to refresh inventory after a
significant fleet change.

## 50. Umbrella next steps

- After a few daily runs, review `unmapped.json` and add manual prefix
  overrides for any client whose Umbrella hostnames don't share a prefix
  with their CP LocationCode (e.g. if BWH agents register as `BWHFD-*`).
- When more clients onboard onto Umbrella, their hostname prefixes will
  appear in `unmapped.json` until mapped — this is the correct
  human-in-the-loop signal.
- This skill is read-only. Do **not** wire any of the write/POST endpoints
  (creating policies, updating destination lists, etc.) without explicit
  re-approval — policy changes belong in the Umbrella Dashboard or a
  separate change-managed pipeline, not the data-capture layer.

## 51. Playwright: Create per-customer Umbrella OAuth2 API keys (one-time)

Cisco Umbrella requires per-customer OAuth2 keys to pull reporting data (DNS
activity, blocked threats, top identities) for each of the 29 MSP child orgs.
These keys cannot be created via the Management API — they must be created
from within each customer's own Umbrella dashboard. The Playwright script
automates this across all 29 orgs using your existing logged-in Edge session.

### Playwright prerequisites

Playwright is already installed (`playwright` package present in Python 3.14
venv). The Edge WebDriver binaries must also be installed once:

```cmd
C:\Python314\python.exe -m playwright install msedge
```

If that fails (channel not found), install Chromium instead:

```cmd
C:\Python314\python.exe -m playwright install chromium
```

### Option A — Reuse existing Edge profile (Edge must be closed)

Close all Edge windows first, then run:

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review
C:\Python314\python.exe technijian\umbrella-pull\scripts\create_customer_api_keys.py
```

Edge will launch using your saved profile (login cookies intact). The browser
window stays open so you can watch each step.

### Option B — Connect to already-running Edge (via remote debugging)

If you want to keep your existing Edge session open:

1. Close Edge completely, then relaunch it with the remote debugging port:

```cmd
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --user-data-dir="C:\Users\rjain\AppData\Local\Microsoft\Edge\User Data"
```

2. Log in to Umbrella if needed, then run the script with `--cdp`:

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review
C:\Python314\python.exe technijian\umbrella-pull\scripts\create_customer_api_keys.py --cdp
```

### Subset and resume

```cmd
REM Create keys for just two orgs first (test run)
C:\Python314\python.exe technijian\umbrella-pull\scripts\create_customer_api_keys.py --only VAF,BWH

REM Resume after an interruption (skips orgs already saved in state)
C:\Python314\python.exe technijian\umbrella-pull\scripts\create_customer_api_keys.py --resume

REM Verify keys already captured without launching browser
C:\Python314\python.exe technijian\umbrella-pull\scripts\create_customer_api_keys.py --verify-only
```

### What the script does per org

1. Opens `https://dashboard.umbrella.com/o/{org_id}/#/admin/apikeys`
2. Clicks "Add API Key" (or "+" button)
3. Fills key name = "ClaudeCode" and selects all scopes
4. Submits and captures the key+secret from the one-time confirmation modal
5. Immediately writes to state file (survives interruption)
6. Tests the key via `POST api.umbrella.com/auth/v2/token`

### Output

| Artifact | Path |
|---|---|
| State (JSON, resumable) | `technijian/umbrella-pull/state/customer-api-keys.json` |
| Keyfile section | `%USERPROFILE%\OneDrive...\cisco-umbrella.md` → "Per-Customer OAuth2 Keys" |

### After key creation

Once all 29 keys are captured, rebuild the per-client reporting pipeline:

1. Update `umbrella_api.py` to accept `org_id` + per-org key credentials
2. Run backfill for each org: `backfill_umbrella.py --all-orgs`
3. Regenerate monthly reports: `build_umbrella_monthly_report.py --all`

### Playwright troubleshooting

- **Redirected to login mid-run**: The Edge session timed out. Log back in
  manually in the browser window, then re-run with `--resume`.
- **"Key named ClaudeCode already exists"**: Delete it from the customer's
  Admin → API Keys page, then re-run `--only <CODE>`.
- **Script can't find the Add button**: Umbrella's React UI may have changed
  its selectors. In that case, manually create the key for that one org and
  enter the credentials directly into `state/customer-api-keys.json`:
  ```json
  { "VAF": { "code": "VAF", "org_id": 8182659, "api_key": "...", "api_secret": "..." } }
  ```
  Then re-run `--verify-only` to test it.

---

## 52. Sophos Central Partner — hourly pull + alert router

Per-machine setup playbook for the production workstation that runs the
`Technijian-HourlySophos` scheduled task. Mirrors the Huntress / CrowdStrike
patterns in this repo, with one twist: this pipeline writes to the Client
Portal API (creates client-billable tickets) and sends email via Microsoft
Graph (reminders to support@technijian.com). It is the first repo pipeline
that is NOT read-only.

DO NOT install this scheduled task on the development laptop. See
`memory/feedback_no_dev_box_schedules.md`.

### Sophos prereqs

- Windows 10/11 logged in as the workstation user (NOT SYSTEM — SYSTEM
  cannot read OneDrive-synced keyfiles).
- Python 3.11+ at `C:\Python314\python.exe` (matches the .cmd wrapper).
- OneDrive (Technijian tenant) signed in and syncing.
- Repo cloned to `c:\vscode\annual-client-review\annual-client-review`.
- Internet access to:
  - `https://id.sophos.com` + `https://api.central.sophos.com` + `https://api-us01.central.sophos.com`
  - `https://api-clientportal.technijian.com`
  - `https://login.microsoftonline.com` + `https://graph.microsoft.com`

### Verify the keyvault state

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

## 53. Sophos first-run smoke tests

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
the router would do under `--apply`.

## 54. Register the Sophos hourly scheduled task

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

## 55. Switch the Sophos router from REPORT to APPLY (gated)

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

## 56. Switch back to REPORT during incidents

If something goes wrong (duplicate tickets, wrong assignment, runaway emails):

```cmd
schtasks /change /tn "Technijian-HourlySophos" /disable
```

Or revert the wrapper's `ROUTER_MODE` env var to `report` (default). The
state file persists, so resuming APPLY later picks up where it left off.

## 57. Sophos daily ops

- Daily run log (gitignored): `technijian\sophos-pull\state\run-<YYYY-MM-DD>.log`
- Per-run snapshots (committed): `technijian\sophos-pull\<YYYY-MM-DD>\`
- Routing plan (committed each run): `technijian\sophos-pull\<YYYY-MM-DD>\routing-plan.json`
- Persistent state (committed): `technijian\sophos-pull\state\alert-tickets.json`
- rsyslog tenant-map (regenerated each run): `technijian\sophos-pull\state\sophos-tenant-ipmap.{txt,json}`

To check what's currently tracked:

```cmd
C:\Python314\python.exe -c "import json; d=json.loads(open(r'technijian\sophos-pull\state\alert-tickets.json').read()); a=d.get('alerts',{}); print(f'tracked={len(a)} pending_create={sum(1 for v in a.values() if not v.get(\"ticket_id\"))}')"
```

## 58. rsyslog tenant-map handoff

The hourly wrapper auto-regenerates `state\sophos-tenant-ipmap.json` from
the live firewall inventory. To deliver to the receiver in the DC:

```cmd
scp ^
  c:\vscode\annual-client-review\annual-client-review\technijian\sophos-pull\state\sophos-tenant-ipmap.json ^
  rjain@siem-ingest.technijian.com:/etc/rsyslog.d/sophos/tenant-map.json
ssh rjain@siem-ingest.technijian.com "sudo systemctl reload rsyslog"
```

## 59. Sophos decommission

```cmd
schtasks /delete /tn "Technijian-HourlySophos" /f
```

---

## 60. Weekly time-entry audit — workstation setup

This is the playbook for the **production workstation** that runs the weekly
time-entry audit every Friday at 7:00 AM PST. Follow these steps once on the
target box, then leave the scheduled task running.

The development environment (the box where this code is authored and committed)
does **not** need any of this — it just commits the scripts. Only the
production workstation needs the secrets, the scheduled task, and the Outlook
mailbox access.

### 60.1 OS

- Windows 10 / 11, 64-bit.
- Admin rights on the local machine for the initial install steps; the
  scheduled task itself runs as the signed-in user (no admin needed at run time).

### 60.2 Hardware / network

- Always-on or wake-on-schedule machine. Friday 7am PST runs assume the box
  is awake or wakes itself.
- Outbound internet to:
  - `https://api-clientportal.technijian.com` (Client Portal API)
  - `https://login.microsoftonline.com` (M365 token endpoint)
  - `https://graph.microsoft.com` (M365 Graph)
  - `https://github.com` (only for the initial git clone + push)

### 60.3 Accounts

- A signed-in Windows user account that the scheduled task will run under.
  Recommended: a dedicated `svc-tj-audit` local account; otherwise the
  primary user account (`rjain@technijian.com`'s local profile) works.
- That account must have read access to the OneDrive keyfiles listed below
  (or have its own copies).

## 61. Install software (weekly audit)

Run all of these in an elevated PowerShell, except where noted.

### 61.1 Git

```powershell
winget install -e --id Git.Git
```

After install, verify in a fresh shell:

```powershell
git --version
```

### 61.2 Python 3.10 or newer

```powershell
winget install -e --id Python.Python.3.12
```

Reopen the shell. Verify:

```powershell
python --version
python -m pip --version
```

If Python 3.12 is unavailable, 3.10 / 3.11 / 3.13 are all fine. The scripts
require **3.9+** (uses `zoneinfo`, type hints with `|`).

### 61.3 Microsoft 365 desktop apps (Outlook + Word)

Outlook is needed only if a human is going to spot-check the drafts before
they send. Word is **not** required — the scripts use `python-docx` and never
launch Word.

Click-to-Run install via Microsoft 365 portal under
`https://www.microsoft.com/account/services` for the user.

### 61.4 The git repo

Clone into the same path used in development so absolute paths in scripts
keep working:

```powershell
mkdir C:\vscode\annual-client-review
cd C:\vscode\annual-client-review
git clone https://github.com/<orgname>/annual-client-review.git
cd annual-client-review
```

Replace `<orgname>` with the org or user that owns the GitHub repo. (The
repo URL is whatever `git remote get-url origin` returns on the dev box.)

### 61.5 Python dependencies

```powershell
cd C:\vscode\annual-client-review\annual-client-review
python -m pip install --upgrade pip
python -m pip install python-docx openpyxl
```

The audit pipeline uses only `python-docx` (Word output) and the standard
library. `openpyxl` is installed for the existing annual reports the same
workstation may also run.

## 62. Weekly-audit credentials

Two keyfiles must exist on the workstation. They are **never committed** to
git. Either copy them from the OneDrive sync, or recreate them.

### 62.1 Microsoft Graph (M365)

Path: `C:\Users\<username>\OneDrive - Technijian, Inc\Documents\VSCODE\keys\m365-graph.md`

Format (the file is parsed for these exact strings — keep the labels):

```markdown
# M365 Graph - HiringPipeline-Automation App

**App Client ID:** <APP_CLIENT_ID>
**Tenant ID:**     <TENANT_ID>
**Client Secret:** <CLIENT_SECRET>
```

Required Graph **application** permissions on the app registration:

- `Mail.Read`
- `Mail.Send`
- `Mail.ReadWrite`

Admin consent must be granted on the tenant. Verify in Azure Portal —
App registrations — `<App Name>` — API permissions.

The skill mailbox is hard-coded to `RJain@technijian.com` (set in
`_secrets.py` `DEFAULT_MAILBOX`). If the workstation should send from a
different mailbox, set the env var `M365_MAILBOX` (see step 4 below) before
running.

### 62.2 Client Portal API

Path: `C:\Users\<username>\OneDrive - Technijian, Inc\Documents\VSCODE\keys\client-portal.md`

Format:

```markdown
# Client Portal API - svc-weekly-audit

**UserName:** <username>
**Password:** <password>
```

The account named here authenticates against
`https://api-clientportal.technijian.com/api/auth/token`. It must have
permission to read time entries across all active clients (the existing
reporting role is sufficient).

### 62.3 (Alternative) Environment variables

Instead of the keyfiles you can set:

```
M365_TENANT_ID
M365_CLIENT_ID
M365_CLIENT_SECRET
M365_MAILBOX            (optional, defaults to RJain@technijian.com)
CP_USERNAME
CP_PASSWORD
```

Env vars take precedence over the keyfiles. Use this option only if storing
secrets in OneDrive is not acceptable on this workstation.

## 63. Weekly-audit first run (smoke test)

Confirm everything is wired before scheduling.

### 63.1 Verify imports

```powershell
cd C:\vscode\annual-client-review\annual-client-review
python -c "
import sys
sys.path.insert(0, r'technijian\weekly-audit\scripts')
from _shared import cycle_id_for, week_window
print('cycle:', cycle_id_for())
print('window:', week_window())
"
```

Expected output: a recent ISO week and a 7-day window ending today.

### 63.2 Verify M365 + Client Portal auth

```powershell
python -c "
import sys
sys.path.insert(0, r'technijian\tech-training\scripts')
from _secrets import get_m365_credentials
t,c,s,m = get_m365_credentials()
print('M365 OK; mailbox =', m)
"

python -c "
import sys
sys.path.insert(0, r'scripts\clientportal')
import cp_api
print('CP login...'); s = cp_api.login()
print('  token len:', len(s.token))
"
```

Each should print one OK line. Any traceback means the keyfile or env var is
wrong — fix before proceeding.

### 63.3 Pipeline dry-run with one client only

```powershell
python technijian\weekly-audit\scripts\1_pull_weekly.py --only BWH
python technijian\weekly-audit\scripts\2_audit_weekly.py
python technijian\weekly-audit\scripts\3_build_weekly_docs.py
python technijian\weekly-audit\scripts\4_email_weekly.py --drafts-only
```

Then open Outlook on `RJain@technijian.com` → Drafts and check that:

- Each tech in the affected client received a draft.
- The draft has both attachments (.docx + .csv).
- The greeting and stats look right.
- The signature renders.

If everything looks right, send manually from Outlook (or run
`python technijian\weekly-audit\scripts\4_email_weekly.py --send-existing`).

### 63.4 Full pipeline trial

Once the smoke test passes:

```powershell
python technijian\weekly-audit\scripts\run_weekly.py --drafts-only
```

This pulls every active client, flags the week, builds docs, and creates
drafts without sending. Inspect 3-4 random drafts in Outlook. When happy:

```powershell
python technijian\weekly-audit\scripts\4_email_weekly.py --send-existing
```

This is also the recovery path if a future run creates drafts but the send
fails.

## 64. Schedule the Friday 7am PST run

Use Windows Task Scheduler. The skill file
`~/.claude/skills/weekly-time-audit/SKILL.md` describes the operational
contract; this section just wires the cron-equivalent.

### 64.1 Create a wrapper batch file

The task triggers a one-line batch wrapper instead of `python.exe`
directly — it gives clean stdout/stderr capture and a stable path.

Save as `C:\vscode\annual-client-review\annual-client-review\technijian\weekly-audit\run_weekly.bat`:

```bat
@echo off
setlocal
cd /d C:\vscode\annual-client-review\annual-client-review
set LOG=technijian\weekly-audit\state\last-run.log
echo. >> %LOG%
echo ==== %date% %time% ==== >> %LOG%
python technijian\weekly-audit\scripts\run_weekly.py >> %LOG% 2>&1
endlocal
```

Test the wrapper from a non-elevated shell:

```cmd
C:\vscode\annual-client-review\annual-client-review\technijian\weekly-audit\run_weekly.bat
```

### 64.2 Register the scheduled task

Open Task Scheduler → Create Task (NOT Create Basic Task).

**General tab:**
- Name: `Technijian Weekly Time-Entry Audit`
- Description: `Pulls last 7 days of time entries, flags outliers, emails techs.`
- Run only when user is logged on (default) — scripts need OneDrive paths,
  which require the user profile.
- Configure for: Windows 10 / 11.

**Triggers tab → New:**
- Begin the task: On a schedule
- Settings: Weekly
- Start: next Friday at `07:00:00 AM`
- Recur every: 1 weeks on **Friday**.
- Synchronize across time zones: **unchecked** (so it tracks local Pacific time).
- Workstation must be set to Pacific Time. Verify with
  `tzutil /g` → should print `Pacific Standard Time`.

**Actions tab → New:**
- Action: Start a program
- Program/script: `C:\vscode\annual-client-review\annual-client-review\technijian\weekly-audit\run_weekly.bat`
- Start in (optional): `C:\vscode\annual-client-review\annual-client-review`

**Conditions tab:**
- Wake the computer to run this task: **checked**.
- Start only if a network connection is available: **checked**.

**Settings tab:**
- Allow task to be run on demand: checked.
- Run task as soon as possible after a scheduled start is missed: checked.
- If the task fails, restart every: 15 minutes, attempt up to 3 times.
- Stop the task if it runs longer than: 1 hour (the full pipeline is
  typically 5-15 minutes; 1 hour is generous).

Click OK. Provide the user account password when prompted.

### 64.3 Equivalent PowerShell registration (one-liner)

If you prefer scripted registration over the GUI:

```powershell
$action  = New-ScheduledTaskAction `
    -Execute 'C:\vscode\annual-client-review\annual-client-review\technijian\weekly-audit\run_weekly.bat' `
    -WorkingDirectory 'C:\vscode\annual-client-review\annual-client-review'

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 7:00am

$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartInterval (New-TimeSpan -Minutes 15) -RestartCount 3

Register-ScheduledTask `
    -TaskName 'Technijian Weekly Time-Entry Audit' `
    -Description 'Pulls last 7 days of time entries, flags outliers, emails techs.' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -User $env:USERNAME
```

## 65. Weekly-audit post-run commit

The pipeline writes outputs into `technijian/weekly-audit/<YYYY-WWnn>/`. To
keep the audit history committed:

### 65.1 Manual

```powershell
cd C:\vscode\annual-client-review\annual-client-review
git pull --rebase
git add technijian/weekly-audit/<cycle> technijian/weekly-audit/by-tech
git commit -m "weekly audit <cycle>"
git push
```

### 65.2 (Optional) Auto-commit at end of pipeline

Append to `run_weekly.bat` after the python line:

```bat
git pull --rebase >> %LOG% 2>&1
git add technijian/weekly-audit/ >> %LOG% 2>&1
git commit -m "weekly audit %date%" >> %LOG% 2>&1
git push >> %LOG% 2>&1
```

Only enable auto-commit if the workstation has a configured git identity
and a credential helper that doesn't prompt. Test once interactively before
relying on it from the scheduled task.

## 66. Weekly-audit monitoring

### 66.1 Last-run log

`technijian/weekly-audit/state/last-run.log` (appended each run).

### 66.2 Per-cycle JSON

- `technijian/weekly-audit/<cycle>/run_log.json` — pipeline-level success / failures.
- `technijian/weekly-audit/<cycle>/audit_log.json` — audit summary.
- `technijian/weekly-audit/<cycle>/by-tech/outlook-drafts-sent.csv` — per-email status.

### 66.3 Self-check email (optional)

Add a simple watchdog in `run_weekly.bat` that emails on failure:

```bat
if %ERRORLEVEL% NEQ 0 (
    powershell -Command "Send-MailMessage -SmtpServer smtp.office365.com -UseSsl -Port 587 -From svc-tj-audit@technijian.com -To rjain@technijian.com -Subject 'Weekly audit FAILED' -Body 'see %LOG%' -Credential (Get-Credential)"
)
```

In practice the easier check is: every Friday by 8am PST, RJain expects to
see the run-log JSON committed. If it isn't there, investigate.

## 67. Updating the weekly-audit skill

Updates flow through git. On the workstation:

```powershell
cd C:\vscode\annual-client-review\annual-client-review
git pull --rebase
```

No re-registration of the scheduled task is required as long as the script
paths don't change.

If `_shared.py` `CATEGORY_CAP` rules are tuned, document the change in the
commit message — the per-tech history files at
`technijian/weekly-audit/by-tech/<slug>/history.csv` will then have a mix
of pre/post-tuning flags, which is fine but worth being aware of when
analyzing trends.

## 68. Decommission / move weekly-audit to a different workstation

To move the schedule to a different box:

1. Disable the scheduled task on the old box:
   `Disable-ScheduledTask -TaskName 'Technijian Weekly Time-Entry Audit'`
2. Run sections 60–64 on the new box.
3. Confirm one full run on the new box (drafts-only is fine).
4. Unregister the task on the old box:
   `Unregister-ScheduledTask -TaskName 'Technijian Weekly Time-Entry Audit' -Confirm:$false`

The repo and all per-cycle outputs follow git, so no data needs to be moved
manually.

## 69. VMware vCenter credentials + smoke test

Credentials live in the OneDrive keyvault at
`<OneDrive>\Documents\VSCODE\keys\vcenter.md`. Required fields: `Host`,
`Username`, `Password`. Username is `administrator@vsphere.local`. Host is
`172.16.9.252` on the management LAN — VPN required from off-site.

Skill: `~/.claude/skills/vcenter-rest/`. Auto-discovered by Claude Code; no
plugin install needed.

Required Python packages:

```cmd
py -3 -m pip install requests urllib3 pyvmomi openpyxl
```

`pyvmomi` is the SOAP fallback used for per-LUN backing detail and historical
performance queries — REST alone is not sufficient on vCenter 8.0.

Smoke test (lists VM count + datastore count + active alarms):

```cmd
set PYTHONIOENCODING=utf-8
py -3 "%USERPROFILE%\.claude\skills\vcenter-rest\scripts\vcenter_client.py"
```

Expected output: `vCenter version: ... 8.0.0.10200`, `VM count: 205`,
`Datastore count: 25`, `Host count: 14`, `Active alarms: 0`. Numbers will drift
as inventory changes.

### Required vCenter advanced setting (one-time)

The daily pull captures per-instance perf via the **5-minute** interval, which
is the only interval where per-instance data is recorded by vCenter (all coarser
intervals strip per-instance during rollup, regardless of their level). Set the
5-min interval to **collection level 3** so `datastore.*`, per-vDisk, per-vNIC
counters get retained for at least 24 hours.

vSphere Client → vCenter Server → Configure → General → Statistics → Edit:

| Interval | Recommended level | Reason |
|---|---|---|
| 5 minutes | **3** | Captures per-instance — required for daily pull aggregation |
| 30 minutes | 1 (default) | We pull daily; coarser rollups not needed |
| 2 hours | 1 (default) | Same |
| Daily | 1 (default) | Same |

Estimated DB impact on `/storage/seat`: **~500 MB – 2 GB sustained** for this
install (200 VMs / 14 hosts / 25 datastores). Verify with `df -h /storage/seat`
on the VCSA before/after the change.

## 70. Schedule the daily vCenter pull

The runner pulls inventory + 5-min perf, splits per client, and aggregates into
per-client per-year accumulators (`vm_perf_daily.json` + `storage_perf_daily.json`)
that grow one bucket per day. Designed to be idempotent — re-running on the same
day overwrites that day's bucket.

Run as the workstation user (must be logged on so OneDrive keyvault is mounted):

```cmd
schtasks /create ^
  /tn "Technijian-DailyVCenterPull" ^
  /tr "c:\vscode\annual-client-review\annual-client-review\scripts\vcenter\run-daily-vcenter.cmd" ^
  /sc DAILY ^
  /st 06:00 ^
  /ru "%USERNAME%" ^
  /f
```

Stagger: 1 AM Huntress → 2 AM Umbrella → 3 AM CrowdStrike → 4 AM Teramind →
5 AM Meraki → **6 AM vCenter**. Stays out of the 7 AM monthly/weekly window.

Verify / run on demand:

```cmd
schtasks /query /tn "Technijian-DailyVCenterPull" /v /fo LIST
schtasks /run   /tn "Technijian-DailyVCenterPull"
```

Logs land at `scripts\vcenter\state\run-<YYYY-MM-DD>.log`. Per-client outputs
under `clients\<code>\vcenter\<year>\`.

Skip the LUN walk (much faster, ~30 s end-to-end if you also skip perf):

```cmd
py -3 scripts\vcenter\daily_run.py --skip-luns --skip-perf
```

Skip everything except inventory (use when troubleshooting):

```cmd
py -3 scripts\vcenter\daily_run.py --skip-luns --skip-perf --keep-master
```

`--keep-master` preserves the dated master dump under `.work/vcenter-<DATE>/`
for inspection (default is to delete after the per-client split to keep disk
usage flat). The `.work` folder is gitignored.
