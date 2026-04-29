# Technijian Annual-Client-Review — System Specification

**Version:** 1.0
**Date:** 2026-04-29
**Owner:** rjain@technijian.com
**Repo:** `c:\vscode\annual-client-review\annual-client-review`

Read this before working in the repo. Update it when a new pipeline ships or a cadence changes.

---

## 1. System Overview

This repo is the **data capture, audit, and reporting system** for Technijian's managed-IT client base. It is not a deployed application. Every pipeline is a Python script driven on-demand or by a Windows Scheduled Task on a dedicated production workstation.

**Three primary goals:**

1. **Annual client reviews** — produce branded Word + Excel deliverables per client showing service delivery, security posture, and billing accuracy for the year.
2. **Ongoing security reporting** — daily EDR snapshots (Huntress, CrowdStrike, Umbrella, Teramind) feed monthly branded DOCX reports delivered to client signers.
3. **Time-entry hygiene** — weekly Friday audit flags outlier entries and emails each tech coaching before the invoice run.

**Scope guard: this repo is read-only toward every external system.** No skill writes to, deletes from, or modifies any data in the Client Portal, Huntress, CrowdStrike, Umbrella, or Teramind. The weekly audit is recommend-only (no auto-deletion). See `SPEC.md` section 13.3 and `API-DELETE-ENDPOINT-SPEC.md` for the deferred enforcement path.

---

## 2. Architecture Overview

```
                         DATA SOURCES
  ┌─────────────────┬────────────────┬──────────────────────┐
  │  Client Portal  │  Security APIs │  Internal Systems    │
  │  (CP API)       │                │                      │
  │  CP_USERNAME/   │  Huntress v1   │  ScreenConnect       │
  │  CP_PASSWORD    │  CrowdStrike   │  (SQLite + R:\)      │
  │                 │  Cisco Umbrella│  Teramind on-prem    │
  └────────┬────────┴───────┬────────┴──────────┬───────────┘
           │                │                   │
           ▼                ▼                   ▼
  ┌────────────────────────────────────────────────────────┐
  │                  PIPELINE LAYER                        │
  │                                                        │
  │  monthly-pull   huntress-pull   sc-recording-pull      │
  │  weekly-audit   crowdstrike-pull  teramind-pull        │
  │  cumul-pull     umbrella-pull   sc-video-analysis      │
  │  annual-review  contacts-pipeline                      │
  └──────────────────────────┬─────────────────────────────┘
                             │
           ┌─────────────────┼──────────────────┐
           ▼                 ▼                  ▼
  ┌────────────────┐  ┌────────────────┐  ┌──────────────┐
  │ clients/<code>/│  │ technijian/    │  │ M365 Graph   │
  │   monthly/     │  │   weekly-audit/│  │ (email to    │
  │   huntress/    │  │   contacts/    │  │  techs +     │
  │   crowdstrike/ │  │   tech-training│  │  clients)    │
  │   umbrella/    │  │   teramind-pull│  └──────────────┘
  │   screenconnect│  │   crowdstrike/ │
  │   data/        │  │   umbrella/    │
  └────────────────┘  └────────────────┘

  SHARED MODULES
  ┌────────────────────────────────────────────────────────┐
  │  scripts/clientportal/cp_api.py  (CP auth + SPs)       │
  │  scripts/contacts/contacts_lib.py (tech-legal bridge)  │
  │  technijian/huntress-pull/scripts/_brand.py (DOCX)     │
  │  technijian/shared/scripts/proofread_docx.py (QA gate) │
  │  technijian/tech-training/scripts/_secrets.py (M365)   │
  └────────────────────────────────────────────────────────┘
```

---

## 3. Data Sources

| # | System | Endpoint / Location | Auth | What Is Pulled | Retention / Limits |
|---|--------|---------------------|------|----------------|--------------------|
| 1 | **Technijian Client Portal** | `https://api-clientportal.technijian.com` | Bearer token (username/password) | Active clients, time entries, tickets, invoices, contracts, directory | Read-only; no stated retention cap |
| 2 | **Huntress v1 REST API** | `https://api.huntress.io/v1` | HTTP Basic (API Key ID + Secret) | Agent inventory, incident reports, signals, reports | Agents: point-in-time only; incidents/signals/reports: supports date filter |
| 3 | **CrowdStrike Falcon API** | `https://api.us-2.crowdstrike.com` | OAuth2 client_credentials | Hosts, alerts, policies, MSSP children | Token TTL ~30 min; alerts queryable by date |
| 4 | **Cisco Umbrella** | `https://api.umbrella.com` | OAuth2 client_credentials (per org) | Roaming computers, sites, activity, blocked threats, top destinations | Activity retention ~90 days; 10K record offset cap per window |
| 5 | **Teramind (on-prem)** | `https://myaudit2.technijian.com` | `X-Access-Token` header | Agents, computers, departments, DLP policies, activity cubes, risk scores | Self-signed SSL (verification disabled); newly deployed, 0 activity currently |
| 6 | **ScreenConnect (SQLite + file share)** | `\\10.100.14.10\C$\...\Session.db` + `R:\` | Admin credentials (UNC share) | Session metadata, tech names, recording files (CRV) | 30-day session event purge; recordings on E:\ (417 GB free) |
| 7 | **tech-legal repo** | `C:\vscode\tech-legal\tech-legal\clients\<CODE>\CONTACTS.md` | Local filesystem | Per-client contact designations, portal DirIDs, signer info | Local filesystem; updated manually in the tech-legal repo |
| 8 | **Microsoft 365 Graph** | `https://graph.microsoft.com` | OAuth2 client_credentials | Mail.Send for tech coaching emails and client reports | Standard Graph limits |

### 3.1 Client Portal stored procedures used

| SP | Purpose |
|----|---------|
| `GET /api/clients/active` | Active client list with LocationCode / DirID / Location_Name |
| `[timeentry].[Reporting].[stp_xml_TktEntry_List_Get]` | Time entries by (ClientID, Start, End) |
| `[invoices].[dbo].[stp_xml_Inv_Org_Loc_Inv_List_Get]` | Invoice history by DirID |
| `GetAllContracts` | Active contract resolution per client |
| `stp_Get_All_Dir` | Full directory lookup by DirID |

**Stable per-entry ID:** `InvDetID` in the time-entry XML. Use for diffing/fingerprinting. See `scripts/clientportal/cp_api.py` and `memory/reference_cp_api_invdetid.md`.

---

## 4. Pipeline Inventory

| Pipeline | Cadence | Primary Script | Trigger | Output Root | Status |
|----------|---------|----------------|---------|-------------|--------|
| Monthly Client Pull | 1st of month, 07:00 PT | `technijian/monthly-pull/scripts/pull_monthly.py` | Scheduled task | `clients/<code>/monthly/` | Active |
| Weekly Time-Entry Audit | Friday, 07:00 PT | `technijian/weekly-audit/scripts/run_weekly.py` | Scheduled task | `technijian/weekly-audit/<cycle>/` | Active |
| Huntress Daily Pull | Daily, 01:00 PT | `technijian/huntress-pull/scripts/pull_huntress_daily.py` | Scheduled task | `clients/<code>/huntress/` | Active |
| Huntress Backfill | On demand | `technijian/huntress-pull/scripts/backfill_huntress.py` | Manual | `clients/<code>/huntress/monthly/` | 2026-01–04 complete |
| Huntress Monthly Report | On demand | `technijian/huntress-pull/scripts/build_monthly_report.py` | Manual | `clients/<code>/huntress/monthly/<YYYY-MM>/` | Active |
| CrowdStrike Daily Pull | Daily, 03:00 PT | `technijian/crowdstrike-pull/scripts/pull_crowdstrike_daily.py` | Scheduled task | `clients/<code>/crowdstrike/` | Task pending install |
| CrowdStrike Backfill | On demand | `technijian/crowdstrike-pull/scripts/backfill_crowdstrike.py` | Manual | `clients/<code>/crowdstrike/monthly/` | 2026-01–04 complete |
| CrowdStrike Monthly Report | On demand | `technijian/crowdstrike-pull/scripts/build_monthly_report.py` | Manual | `clients/<code>/crowdstrike/monthly/<YYYY-MM>/` | Active |
| Cisco Umbrella Daily Pull | Daily, 02:00 PT | `technijian/umbrella-pull/scripts/pull_umbrella_daily.py` | Scheduled task | `clients/<code>/umbrella/` | Task pending install (VAF only mapped) |
| Umbrella Backfill | On demand | `technijian/umbrella-pull/scripts/backfill_umbrella.py` | Manual | `clients/<code>/umbrella/` | Available |
| Umbrella MSP Key Creation | One-time per org | `technijian/umbrella-pull/scripts/create_customer_api_keys.py` | Manual (Playwright) | `state/customer-api-keys.json` | Pending (per-customer keys not yet created) |
| Umbrella Monthly Report | On demand | `technijian/umbrella-pull/scripts/build_umbrella_monthly_report.py` | Manual | `clients/<code>/umbrella/monthly/<YYYY-MM>/` | Pending per-org keys |
| Teramind Daily Pull | Daily, 04:00 PT | `technijian/teramind-pull/scripts/pull_teramind_daily.py` | Scheduled task | `technijian/teramind-pull/` | Active (3 clients mapped) |
| Teramind Compliance Report | On demand | `technijian/teramind-pull/scripts/build_teramind_compliance_report.py` | Manual | `technijian/teramind-pull/<date>/reports/` | Active |
| ScreenConnect Recording Pull | Monthly, 28th, 20:00 | `technijian/screenconnect-pull/run-monthly-sc.cmd` | Scheduled task | `clients/<code>/screenconnect/` + OneDrive FileCabinet | Active (first run in progress 2026-04-29) |
| ScreenConnect Video Analysis | Daily, ~04:00 PT | `technijian/screenconnect-pull/scripts/analyze_sessions_gemini.py` | Scheduled task (not installed) | `clients/<code>/screenconnect/<year>/session_analysis/` | Blocked (no Gemini key yet) |
| Contacts / Send-List | On demand | `scripts/contacts/build_contacts_report.py` | Manual | `technijian/contacts/` | Active |
| Annual Client Review | Manually per client | `technijian/tech-training/scripts/_audit-all-clients.py` + report builders | Manual | `technijian/tech-training/<YEAR>/` | Manual (2026 cycle complete) |
| Cumulative Full-History Pull | On demand | `scripts/clientportal/pull_all_active.py` | Manual | `clients/<code>/data/` | Active (on demand) |

---

## 5. Per-Pipeline Detail

### 5.1 Monthly Client Pull

**Purpose:** Snapshot the prior calendar month of time entries and derived tickets for every active CP client. Feeds quarterly and annual reviews without requiring a re-pull.

**Cadence:** 1st of every month at 07:00 PT.

**Data flow:**
1. Call `GET /api/clients/active` to get all active clients.
2. For each client, call `stp_xml_TktEntry_List_Get(ClientID, month-start, month-end)`.
3. Parse XML to JSON and CSV. Derive unique tickets from time entries.
4. Write five files per client per month. Write run log.

**Key scripts:**

| Script | Purpose |
|--------|---------|
| `technijian/monthly-pull/scripts/pull_monthly.py` | Worker |
| `technijian/monthly-pull/run-monthly-pull.cmd` | Wrapper (used by scheduled task) |
| `scripts/clientportal/cp_api.py` | Shared CP API client |

**Output schema (per client per month):**
```
clients/<code>/monthly/YYYY-MM/
  time_entries.xml          raw XML from stp_xml_TktEntry_List_Get
  time_entries.json         parsed list [{InvDetID, Client, Date, Title, Tech, ...}]
  time_entries.csv          flat CSV
  tickets.json              unique tickets derived from time entries
  pull_summary.json         {time_entry_count, ticket_count, errors[], run_at}

technijian/monthly-pull/state/YYYY-MM.json   run log
technijian/monthly-pull/state/run-YYYY-MM-DD.log   stdout/stderr from wrapper
```

**Scheduled task:** `Technijian-MonthlyClientPull` — monthly on day 1 at 07:00.

**Backfill:** `python pull_monthly.py --month 2026-01` (overwrites in place).

**Constraints:** Does NOT pull invoices (that is `pull_all_active.py`). Does NOT delete or modify CP data.

---

### 5.2 Weekly Time-Entry Audit

**Purpose:** Flag time-entry outliers (H1–H5 rules) before Friday evening's invoice run. Email each affected tech a personalized branded Word doc + CSV with suggested rewrites and hour adjustments.

**Cadence:** Every Friday at 07:00 PT.

**Flag rules (H1–H5):**

| Code | Trigger |
|------|---------|
| H1 | Routine work over per-category cap (0.75–4.0h depending on category) |
| H2 | Vague title (Help/Fix/Issue/Test) + > 0.5h |
| H3 | Single entry > 8 hours |
| H4 | Daily total > 12 hours across tickets |
| H5 | Same tech + ticket + day with sum > 2× category cap |

Category caps (32 entries) live in `technijian/weekly-audit/scripts/_shared.py::CATEGORY_CAP`.

**Data flow (4-script pipeline):**
```
1_pull_weekly.py   → raw/<client>/{time_entries.xml, time_entries.csv}
2_audit_weekly.py  → SUMMARY.md, all-flagged-entries.csv, by-client/, by-tech/
3_build_weekly_docs.py → by-tech/<slug>/<slug>-Weekly-Training.docx
4_email_weekly.py  → Graph API create draft → send; manifests written
run_weekly.py      → orchestrates 1→2→3→4, aborts on failure
```

**Key scripts:**

| Script | Purpose |
|--------|---------|
| `technijian/weekly-audit/scripts/run_weekly.py` | Orchestrator |
| `technijian/weekly-audit/scripts/_shared.py` | Flag rules, cycle naming, fingerprinting |
| `technijian/weekly-audit/scripts/1_pull_weekly.py` | CP pull |
| `technijian/weekly-audit/scripts/2_audit_weekly.py` | Flag pass |
| `technijian/weekly-audit/scripts/3_build_weekly_docs.py` | DOCX builder |
| `technijian/weekly-audit/scripts/4_email_weekly.py` | Graph email send |
| `technijian/tech-training/scripts/_secrets.py` | M365 credential resolver (reused) |
| `technijian/tech-training/scripts/tech-emails.json` | Tech slug → email cache (reused) |

**Output schema:**
```
technijian/weekly-audit/<YYYY-WWnn>/
  SUMMARY.md                        committed
  all-flagged-entries.csv           committed
  audit_log.json                    committed
  run_log.json                      committed
  raw/                              gitignored (large API payloads)
  by-client/<client>/
    tech-outliers-summary.md        committed
    tech-outliers-detail.csv        committed
  by-tech/<slug>/
    flagged-entries.csv             committed
    training.md                     committed
    <slug>-Weekly-Training.docx     committed (emailed attachment)
    outlook-drafts-created.csv      committed
    outlook-drafts-sent.csv         committed

technijian/weekly-audit/by-tech/<slug>/history.csv   rolling, append-only, committed
technijian/weekly-audit/state/last-run.log           gitignored
```

**Scheduled task:** `Technijian Weekly Time-Entry Audit` — weekly on Friday at 07:00.

**Constraint:** Recommend-only — no auto-deletion. `CEO R-Jain` excluded from recipient list (`EXCLUDE_SLUGS`). Draft-only path available via `run_weekly.py --drafts-only`.

**Delete-endpoint spec:** Deferred — `technijian/weekly-audit/API-DELETE-ENDPOINT-SPEC.md`. Do not wire without explicit re-approval.

---

### 5.3 Huntress Daily Pull + Backfill + Report

**Purpose:** Daily agent inventory snapshot per client. Backfill of historical incidents, signals, and reports. Monthly branded DOCX for client delivery.

**Cadence:** Daily at 01:00 PT.

**Key facts:**
- Agent inventory is point-in-time only — no historical filter on `/v1/agents`. Do not attempt to backfill agents.
- Incidents/signals/reports DO support date filtering and are covered by `backfill_huntress.py`.
- Org → LocationCode mapping: (1) manual override in `state/huntress-org-mapping.json`, (2) exact normalized-name match. No fuzzy matching.
- SAT (Security Awareness Training) is NOT in the Huntress v1 API as of 2026-04.
- Cursor pagination: `limit` + `page_token` → `pagination.next_page_token`. Handled in `huntress_api.py`.

**Key scripts:**

| Script | Purpose |
|--------|---------|
| `technijian/huntress-pull/scripts/pull_huntress_daily.py` | Daily worker |
| `technijian/huntress-pull/scripts/backfill_huntress.py` | Historical incidents/signals/reports |
| `technijian/huntress-pull/scripts/build_monthly_report.py` | Branded DOCX per client per month |
| `technijian/huntress-pull/scripts/huntress_api.py` | Shared API client |
| `technijian/huntress-pull/scripts/_brand.py` | Reusable DOCX brand helpers |

**Output schema:**
```
clients/<code>/huntress/YYYY-MM-DD/
  agents.json + agents.csv          hostname, OS, version, last_callback_at,
                                    isolated, ipv4, defender/firewall status
  incident_reports.json
  signals.json
  reports.json
  pull_summary.json                 active/offline/isolated/called_back_in_window counts

clients/<code>/huntress/monthly/YYYY-MM/
  incident_reports.json + signals.json + reports.json + pull_summary.json
  <CODE>-Cybersecurity-Activity-YYYY-MM.docx   (branded client report)

technijian/huntress-pull/YYYY-MM-DD/
  account.json + organizations.json + mapping.json + unmapped.json + run_log.json

technijian/huntress-pull/state/huntress-org-mapping.json   persistent mapping overrides
```

**Scheduled task:** `Technijian-DailyHuntressPull` — daily at 01:00.

**Backfill status:** 2026-01 through 2026-04 completed 2026-04-29 (29 mapped clients, 116 client-months, 48 incidents + 52 signals + 598 reports).

---

### 5.4 CrowdStrike Daily Pull

**Purpose:** Daily Falcon EDR snapshot per client. Multi-tenant via Flight Control (36 child CIDs). Monthly branded DOCX for client delivery.

**Cadence:** Daily at 03:00 PT (after Huntress at 01:00 and Umbrella at 02:00).

**Key facts — Flight Control quirk (critical):** The `/alerts/queries/alerts/v2`, `/detects/queries/detects/v1`, and `/incidents/queries/incidents/v1` endpoints **silently ignore `member_cid`** for Flight Control parent CIDs. Pull once at the parent level, then bucket by the `cid` field on each record. The Hosts API (`/devices/`) correctly honors `member_cid`. See `memory/feedback_falcon_flight_control_member_cid.md`.

**Confirmed read scopes (2026-04-29):** Hosts, Host Groups, Alerts, MSSP, Sensor Update, Prevention, IOCs, Users. Incidents/Discover/Spotlight/CCID return 4xx — scope or license missing, pull degrades gracefully.

**Key scripts:**

| Script | Purpose |
|--------|---------|
| `technijian/crowdstrike-pull/scripts/pull_crowdstrike_daily.py` | Daily worker |
| `technijian/crowdstrike-pull/scripts/backfill_crowdstrike.py` | Historical backfill |
| `technijian/crowdstrike-pull/scripts/build_monthly_report.py` | Branded DOCX per client per month |
| `technijian/crowdstrike-pull/scripts/cs_api.py` | Shared API client (all Falcon read surfaces) |

**Output schema:**
```
clients/<code>/crowdstrike/YYYY-MM-DD/
  hosts.json + hosts.csv            per-child hosts via member_cid
  alerts.json + alerts.csv          bucketed from parent pull by cid
  pull_summary.json

clients/<code>/crowdstrike/monthly/YYYY-MM/
  alerts.json + incidents.json + behaviors.json + pull_summary.json
  <CODE>-CrowdStrike-Activity-YYYY-MM.docx   (branded client report)

technijian/crowdstrike-pull/YYYY-MM-DD/
  children.json + mapping.json + unmapped.json + run_log.json

technijian/crowdstrike-pull/state/crowdstrike-cid-mapping.json   persistent overrides
```

**Scheduled task:** `Technijian-DailyCrowdStrikePull` — daily at 03:00. **Task not yet installed on production workstation as of 2026-04-29.**

**Backfill status:** 2026-01 through 2026-04 completed 2026-04-29 (29 mapped clients, 116 client-months, 3,767 total alerts). 95 DOCX reports generated.

---

### 5.5 Cisco Umbrella Daily Pull

**Purpose:** Daily DNS security snapshot per client. Captures roaming computer inventory, sites, activity, top destinations, and blocked threats.

**Cadence:** Daily at 02:00 PT.

**Tenancy model:** MSP parent org `8163754` with **29 child orgs** (one per client). Per-client reporting requires per-org OAuth2 keys. The current daily pull uses a single-tenant token covering only VAF (org `8182659`). Per-customer keys need to be created via Playwright automation (`create_customer_api_keys.py`) before the full 29-client pull is possible.

**Key facts:**
- Activity retention ~90 days. Activity API hard cap: 5,000 records per pull, 10,000 offset per window.
- For backfill, use aggregation endpoints (`top-identities`, `top-threats`, `requests-by-hour`, `categories-by-hour`) — ~30–50x faster than raw activity walks.
- Hostname-prefix mapping: `state/umbrella-prefix-mapping.json` → `{"manual": {"PREFIX": "LOCATIONCODE"}, "ignore": [...]}`.
- Per-customer MSP keys require Playwright + 2FA (interactive session). State file: `state/customer-api-keys.json`.

**Key scripts:**

| Script | Purpose |
|--------|---------|
| `technijian/umbrella-pull/scripts/pull_umbrella_daily.py` | Daily worker |
| `technijian/umbrella-pull/scripts/backfill_umbrella.py` | Historical aggregations backfill |
| `technijian/umbrella-pull/scripts/create_customer_api_keys.py` | Playwright MSP key creation |
| `technijian/umbrella-pull/scripts/build_umbrella_monthly_report.py` | Branded DOCX (pending per-org keys) |
| `technijian/umbrella-pull/scripts/umbrella_api.py` | Shared API client |

**MSP child org IDs (29 orgs):** B2I=8182603, ANI=8182605, TECH=8182611, TDC=8182613, ISI=8182639, NOR=8182646, ORX=8182647, RSPMD=8182655, SAS=8182656, VAF=8182659, AAVA=8212809, KSS=8213557, AOC=8219569, BWH=8219571, CCC=8219573, MAX=8219576, ACU=8228246, JDH=8256091, HHOC=8262496, TALY=8270949, CBI=8298405, RMG=8315328, SGC=8316182, ALG=8316664, KES=8323805, JSD=8324833, DTS=8347026, EBRMD=8347471, AFFG=8390093.

**Output schema:**
```
clients/<code>/umbrella/YYYY-MM-DD/
  roaming_computers.json + .csv     filtered to hostname prefix
  internal_networks.json + sites.json
  activity_summary.json + top_destinations.json + blocked_threats.json
  pull_summary.json

technijian/umbrella-pull/YYYY-MM-DD/
  account.json + deployment.json + mapping.json + unmapped.json + run_log.json

technijian/umbrella-pull/state/umbrella-prefix-mapping.json
technijian/umbrella-pull/state/customer-api-keys.json   (per-org OAuth2 keys)
```

**Scheduled task:** `Technijian-DailyUmbrellaPull` — daily at 02:00. **Task not yet installed on production workstation as of 2026-04-29.**

---

### 5.6 Teramind Daily Pull

**Purpose:** Daily compliance and DLP activity snapshots from the on-premise Teramind server. Feeds per-client compliance DOCX reports.

**Cadence:** Daily at 04:00 PT.

**Auth quirk:** Uses `X-Access-Token: <token>` header — NOT `Authorization: Bearer`. SSL verification disabled for self-signed cert.

**Valid cubes (2026-04-29):** `activity`, `keystrokes`, `web_search`, `social_media`. Other cubes (`sessions`, `alerts`, `file_transfers`, `emails`, `cli`, `printing`) return "unknown cube" — not licensed on this installation.

**Current state:** 5 agents, 2 active computers, 3 clients mapped (LAG, MKC, QOSNET). Newly deployed; 0 activity data currently.

**Time filter format:** `data_filters.time = [{"dimension": "time", "dateRange": [iso_start, iso_end]}]`. Timestamps are Unix seconds (not milliseconds).

**Key scripts:**

| Script | Purpose |
|--------|---------|
| `technijian/teramind-pull/scripts/pull_teramind_daily.py` | Daily worker |
| `technijian/teramind-pull/scripts/build_teramind_compliance_report.py` | Branded DOCX per client |
| `technijian/teramind-pull/scripts/teramind_api.py` | Shared API client |

**Output schema:**
```
technijian/teramind-pull/YYYY-MM-DD/
  account.json + agents.json + agents.csv
  computers.json + computers.csv
  departments.json + behavior_groups.json + behavior_policies.json
  activity.json + keystrokes.json + web_search.json + social_media.json
  risk_scores.json + agent_details.json + last_devices.json
  run_log.json
  reports/<CODE>-Compliance-YYYY-MM.docx   (branded report)

technijian/teramind-pull/state/YYYY-MM-DD.json
```

**Scheduled task:** `Technijian-DailyTeramindPull` — daily at 04:00.

---

### 5.7 ScreenConnect Recording Pipeline

**Purpose:** Convert monthly ScreenConnect session recordings to MP4, archive to OneDrive/Teams FileCabinet, and produce per-client audit CSVs for the annual review.

**Cadence:** Monthly on the 28th at 20:00 (before the 30-day SC session purge).

**Important constraint:** Requires an interactive logged-in user session — the `SessionCaptureProcessor.exe` GUI will not run as SYSTEM. Must be scheduled with "Run only when user is logged on."

**Pipeline steps:**
1. Map `R:\` → `\\10.100.14.10\E$\Myremote Recording` (SC recordings share)
2. Launch `ScreenConnectSessionCaptureProcessor.exe` GUI
3. `sc_automate.ps1` checks "Transcode after download", selects all R:\ files (Ctrl+A), starts CRV→AVI transcoding (~8 hours for 2,800 files)
4. `sc_watch_and_convert.py` polls R:\ every 5 min; when AVI count stabilises, auto-triggers FFmpeg AVI→MP4 (CRF 28/slow) into OneDrive FileCabinet, then rebuilds audit CSVs
5. `build_client_audit.py --all` writes per-client audit CSV/JSON with tech attribution and OneDrive Teams URL

**Full specification:** `docs/screenconnect-recording-pipeline.md` — cross-reference that file for detailed data model, SQLite schema, and session ID format.

**Key scripts:**

| Script | Purpose |
|--------|---------|
| `technijian/screenconnect-pull/run-monthly-sc.cmd` | Monthly wrapper (all steps) |
| `technijian/screenconnect-pull/scripts/pull_screenconnect_2026.py` | AVI→MP4 + audit_log.json |
| `technijian/screenconnect-pull/scripts/build_client_audit.py` | Per-client CSV/JSON audit |
| `technijian/screenconnect-pull/scripts/sc_watch_and_convert.py` | Background watcher/coordinator |
| `technijian/screenconnect-pull/scripts/analyze_sessions_gemini.py` | Gemini video analysis (blocked) |

**Output schema:**
```
clients/<code>/screenconnect/<year>/
  <CLIENT>-SC-Audit-<year>.csv    recording_start, tech_name, machine, teams_url, ...
  <CLIENT>-SC-Audit-<year>.json
  session_analysis/<stem>.json    Gemini per-session analysis (pending)

OneDrive FileCabinet\<CLIENT>-<year>-<month>\
  <YYYYMMDD>_<CLIENT>_<session8>_<conn8>.mp4

OneDrive FileCabinet\_audit\
  audit_log.json + audit_log.csv
```

**Scheduled task:** `Technijian-MonthlyScreenConnectPull` — monthly on day 28 at 20:00.

**Blocked sub-pipeline:** `analyze_sessions_gemini.py` — requires Gemini API key at `keys/gemini.md` (currently `TODO_PASTE_KEY_HERE`). See section 12 Future Work.

---

### 5.8 Contacts / Send-List Pipeline

**Purpose:** Resolve the client contact email address for each active managed-IT client. Produce the `send_list_<YYYY-MM>.csv` used by report-delivery pipelines.

**Cadence:** On demand (run when contacts change or before a send cycle).

**Two-layer recipient resolution:**
- **Layer 1 (portal designation):** `report_recipients()` in `contacts_lib.py` — returns non-empty when the Primary Contact, Invoice Recipient, or Contract Signer section has a parseable email.
- **Layer 2 (contract signer fallback):** When Layer 1 is empty and the client is managed-IT-active, resolve the most-recent active contract's `Signed_DirID` via `stp_Get_All_Dir`. Technijian-internal `@technijian.com` emails are excluded.
- **Never fall back to C1/C2/C3 portal role lists.**

**Coverage snapshot (2026-04-29):** 30 managed-IT active clients; 20/30 send-ready (5 portal-designated, 15 via contract signer); 10 still need designation (see `technijian/contacts/needs_designation_set.csv`).

**Key scripts:**

| Script | Purpose |
|--------|---------|
| `scripts/contacts/build_contacts_report.py` | Generates all contacts outputs |
| `scripts/contacts/contacts_lib.py` | Parsing + resolution library |
| `scripts/contacts/data_signals.py` | Determines "managed-IT active" from security tool data |

**Source of truth:** `C:\vscode\tech-legal\tech-legal\clients\<CODE>\CONTACTS.md`. This repo never duplicates contact data.

**Output schema:**
```
technijian/contacts/
  active_client_recipients.csv      per-client with Recipient_Source column
  send_list_YYYY-MM.csv             managed-IT-active AND send-ready
  needs_designation_set.csv         neither layer resolved a recipient
  cp_only_YYYY-MM.csv               CP-only clients (not in annual review scope)
  missing_legal.csv                 active CP clients with no tech-legal file
  stale_legal.csv                   tech-legal entries with no active CP match
  COVERAGE.md                       human-readable coverage summary
```

---

### 5.9 Annual Client Review

**Purpose:** Per-client branded annual deliverables — Word + Excel reports showing service delivery, billing analysis, security posture, and time-entry coaching.

**Cadence:** Manual — driven once per year per client (or client group). The 2026 cycle is complete.

**Pipeline scripts (all in `technijian/tech-training/scripts/`):**

| Script | Purpose |
|--------|---------|
| `_audit-all-clients.py` | Scans all clients, applies H1–H5 flags, produces per-client/per-tech artifacts |
| `_build-all-reports.py` | Wrapper calling docx + xlsx builders for all clients |
| `_build-docx-report.py` | Branded Word doc builder |
| `_build-xlsx-report.py` | Per-client XLSX |
| `_coaching.py` | `build_coaching(title, category, hours)` → suggested rewrite |
| `_resolve-tech-emails.py` | Populates `tech-emails.json` from RJain's mailbox history |
| `_create-outlook-drafts.py` | Graph API draft creation with attachments |
| `_send-drafts.py` | Sends manifest of drafts |
| `_check-bounces.py` | Post-send bounce triage |

**Output schema:**
```
technijian/tech-training/<YEAR>/
  SUMMARY.md
  all-flagged-entries.csv
  by-client/<client>/
    *.docx + *.xlsx               branded annual deliverables
    tech-outliers-summary.md
  by-tech/<slug>/
    training.md + flagged-entries.csv + <slug>-Training.docx
```

**Reads from:** `clients/<code>/data/` (cumulative pull) and `clients/<code>/<YYYY>/03_Accounting/time-entries.csv` (per-year review folder).

---

## 6. Output Locations — Master Table

| Output Path | Written By | Consumed By |
|-------------|-----------|-------------|
| `clients/<code>/monthly/YYYY-MM/` | Monthly Pull | Annual Review, ad-hoc analysis |
| `clients/<code>/huntress/YYYY-MM-DD/` | Huntress Daily Pull | Huntress Monthly Report |
| `clients/<code>/huntress/monthly/YYYY-MM/` | Huntress Backfill + Report | Client delivery |
| `clients/<code>/crowdstrike/YYYY-MM-DD/` | CrowdStrike Daily Pull | CrowdStrike Monthly Report |
| `clients/<code>/crowdstrike/monthly/YYYY-MM/` | CrowdStrike Backfill + Report | Client delivery |
| `clients/<code>/umbrella/YYYY-MM-DD/` | Umbrella Daily Pull | Umbrella Monthly Report |
| `clients/<code>/screenconnect/<year>/` | SC Recording Pull | Annual Review |
| `clients/<code>/screenconnect/<year>/session_analysis/` | SC Video Analysis (Gemini) | Annual Review |
| `clients/<code>/data/` | Cumulative Pull (`pull_all_active.py`) | Annual Review |
| `clients/<code>/<YYYY>/` | Annual Review (manual) | Client delivery |
| `technijian/weekly-audit/<cycle>/` | Weekly Audit | Committed audit history |
| `technijian/weekly-audit/by-tech/<slug>/history.csv` | Weekly Audit | Future pattern report |
| `technijian/huntress-pull/YYYY-MM-DD/` | Huntress Daily Pull | Audit trail |
| `technijian/crowdstrike-pull/YYYY-MM-DD/` | CrowdStrike Daily Pull | Audit trail |
| `technijian/umbrella-pull/YYYY-MM-DD/` | Umbrella Daily Pull | Audit trail |
| `technijian/teramind-pull/YYYY-MM-DD/` | Teramind Daily Pull | Compliance reports |
| `technijian/teramind-pull/YYYY-MM-DD/reports/` | Teramind Compliance Report | Client delivery |
| `technijian/contacts/` | Contacts Pipeline | All email-delivery pipelines |
| `technijian/tech-training/<YEAR>/` | Annual Review | Manual delivery |
| `OneDrive FileCabinet\<CLIENT>-<year>-<month>\` | SC Recording Pull | Teams/client |

---

## 7. Shared Infrastructure

### 7.1 CP API Client — `scripts/clientportal/cp_api.py`

Handles all Client Portal interactions:
- `login()` / `get_session()` — bearer token auth, caches token, re-auths on 401
- `get_active_clients()` — returns list of `{DirID, LocationCode, Location_Name, ...}`
- `get_time_entries_xml(client_dir_id, start, end)` — calls `stp_xml_TktEntry_List_Get`
- `get_all_contracts()` / `get_active_contract(dir_id)` — contract resolution
- `parse_flat_xml(xml_str)` — parses `<Root><TimeEntry>` format to list of dicts
- `get_all_dir()` — calls `stp_Get_All_Dir` for directory lookups

**Credentials:** `CP_USERNAME` / `CP_PASSWORD` env vars, or `OneDrive keys\client-portal.md`.

### 7.2 Contacts Library — `scripts/contacts/contacts_lib.py`

Bridge to the tech-legal repo. Never read contact data directly — always go through this library:
- `load_all_tech_legal_contacts()` — walks tech-legal repo's `clients/*/CONTACTS.md`
- `cross_reference(legal, active_cp_clients)` — matches by DirID first, LocationCode fallback
- `report_recipients(legal)` — Layer 1 portal-designation resolution
- `stale_legal(legal, active_cp_clients)` — tech-legal entries with no active CP match

### 7.3 Brand Helpers — `technijian/huntress-pull/scripts/_brand.py`

Reusable `python-docx` helpers for all branded DOCX outputs. **Import this; do not fork it.**

Colors: `#006DB6` (core blue), `#F67D4B` (orange), `#1EAAC8` (teal), `#1A1A2E` (dark charcoal), `#59595B` (brand grey). Font: Open Sans 11pt.

Logo path: `C:\VSCode\tech-branding\tech-branding\assets\logos\png\technijian-logo-full-color-600x125.png`

Functions: `shade()`, `set_cell_border_color()`, `add_run()`, `styled_table()`, `add_metric_card_row()`, `add_section_header()`, `add_callout_box()`.

### 7.4 DOCX Proofreader — `technijian/shared/scripts/proofread_docx.py`

Structural + content QA gate for all branded DOCX outputs. 10 checks: file existence, size ≥ 10 KB, opens without error, cover page title, section headers, table header rows, no placeholder text (TODO/TBD/[Your Name]), no mojibake artifacts, callout boxes present, metric cards present. **Wire into every report builder.** Exit code 0 = pass. Called automatically by Teramind and Huntress report builders.

Usage: `python technijian/shared/scripts/proofread_docx.py path/to/report.docx`

### 7.5 M365 Credential Resolver — `technijian/tech-training/scripts/_secrets.py`

Returns `(tenant_id, client_id, client_secret, mailbox)` from:
1. `M365_TENANT_ID` / `M365_CLIENT_ID` / `M365_CLIENT_SECRET` / `M365_MAILBOX` env vars, else
2. `OneDrive keys\m365-graph.md` keyfile.

Default mailbox: `RJain@technijian.com`.

### 7.6 Tech Email Directory Cache — `technijian/tech-training/scripts/tech-emails.json`

Slug → email map built by `_resolve-tech-emails.py` from RJain's Graph mailbox history. Reuse this for any pipeline that needs to email techs. Refresh: `python _resolve-tech-emails.py 2026 --refresh`.

### 7.7 Keyfile Convention

All secrets live in OneDrive-synced markdown files at `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\`. Each file uses `**Label:** value` format parseable by the corresponding `_api.py` helper. Env vars take precedence over keyfiles for headless/CI environments.

---

## 8. Credentials and Keys

| Bundle | Env Vars | Keyfile Path | Used By | Notes |
|--------|----------|--------------|---------|-------|
| Client Portal | `CP_USERNAME`, `CP_PASSWORD` | `keys\client-portal.md` | All CP-touching pipelines | Account needs `clients:read` + reporting role |
| M365 Graph | `M365_TENANT_ID`, `M365_CLIENT_ID`, `M365_CLIENT_SECRET`, `M365_MAILBOX` | `keys\m365-graph.md` | Weekly audit, Annual review email | App: HiringPipeline-Automation; perms: Mail.Read + .Send + .ReadWrite (application, admin-consented) |
| Huntress | `HUNTRESS_API_KEY`, `HUNTRESS_API_SECRET` | `keys\huntress.md` | Huntress pull | Active key: `hk_ee8ddb711c3c959cc7dd`; Secret shown once at creation; previous key `hk_f567a96492585118c32a` superseded |
| CrowdStrike | `CROWDSTRIKE_CLIENT_ID`, `CROWDSTRIKE_CLIENT_SECRET`, `CROWDSTRIKE_BASE_URL` | `keys\crowdstrike.md` | CrowdStrike pull | OAuth2 US-2; token TTL ~30 min; read-only scopes only |
| Cisco Umbrella (single-tenant) | — | `keys\cisco-umbrella.md` (**API Key** + **API Secret** fields) | Umbrella pull (VAF only currently) | Shows Secret once at creation |
| Cisco Umbrella (per-customer MSP) | — | `keys\cisco-umbrella.md` (Per-Customer OAuth2 Keys section) + `state\customer-api-keys.json` | Future full-29-org Umbrella pull | Created via Playwright; 2FA required |
| Teramind | `TERAMIND_HOST`, `TERAMIND_ACCESS_TOKEN` | `keys\teramind.md` | Teramind pull | Token = `2fd3b7a08c6cd2318dbc27654b4f663e5a55d4c2`; regenerate in Teramind portal → Settings → Access Tokens |
| ScreenConnect | — | `keys\screenconnect-web.md` | SC recording pull (UNC share + GUI) | API key `TechSCCapture2026!`; admin credentials `T3chn!j2n92618!!` for UNC share |
| Gemini | `GEMINI_API_KEY` | `keys\gemini.md` | SC video analysis | Currently `TODO_PASTE_KEY_HERE`; get from aistudio.google.com/apikey |
| MyRMM SQL | — | `keys\myrmm-sql.md` | Not yet wired | `TODO` — credentials not yet supplied |

**Keyfile location (OneDrive base):** `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\`

**All keyfiles are gitignored.** They are never committed. OneDrive sync is the distribution mechanism.

---

## 9. Workstation Requirements

A production workstation needs the following. Do NOT install scheduled tasks on the development laptop.

### 9.1 Software

| Component | Version | Install |
|-----------|---------|---------|
| Python | 3.11+ (tested on 3.14.3) | `winget install -e --id Python.Python.3.12` |
| Git | Any modern | `winget install -e --id Git.Git` |
| FFmpeg | Any modern | `winget install --id Gyan.FFmpeg -e` (for SC recording pipeline only) |
| Playwright for Python | Latest | `pip install playwright && python -m playwright install msedge` (for Umbrella MSP key creation only) |
| python-docx | Latest | `pip install python-docx openpyxl` |
| OneDrive (Technijian tenant) | Signed in | Provides keyfiles; MUST be syncing before first run |
| Microsoft 365 / Outlook | Optional | Needed only for human spot-check of drafts before send |

**Python path used in .cmd wrappers:** `C:\Python314\python.exe`. Update wrappers if Python lives elsewhere.

### 9.2 Network access required

| Endpoint | Pipeline |
|----------|---------|
| `https://api-clientportal.technijian.com` | Monthly pull, Weekly audit, Annual review |
| `https://api.huntress.io` | Huntress pull |
| `https://api.us-2.crowdstrike.com` | CrowdStrike pull |
| `https://api.umbrella.com` + `https://login.umbrella.com` | Umbrella pull |
| `https://myaudit2.technijian.com` | Teramind pull |
| `\\10.100.14.10` (LAN or VPN) | ScreenConnect recording pipeline |
| `https://login.microsoftonline.com` + `https://graph.microsoft.com` | Weekly audit, Annual review email |
| `https://generativelanguage.googleapis.com` | SC video analysis (Gemini) |

### 9.3 Repo path

Clone to `c:\vscode\annual-client-review\annual-client-review`. All `.cmd` wrappers hard-code this path. If cloned elsewhere, update every `run-*.cmd` file.

### 9.4 First-run smoke tests

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM Monthly pull
python technijian\monthly-pull\scripts\pull_monthly.py --dry-run

REM Huntress
python -c "import sys; sys.path.insert(0, r'technijian\huntress-pull\scripts'); import huntress_api as h; print(h.get_account())"

REM CrowdStrike
python -c "import sys; sys.path.insert(0,'technijian\crowdstrike-pull\scripts'); import cs_api; print('children:', len(cs_api.list_mssp_children()))"

REM Umbrella
python -c "import sys; sys.path.insert(0, r'technijian\umbrella-pull\scripts'); import umbrella_api as u; print('token_len:', len(u.get_token()))"

REM Teramind
python technijian\teramind-pull\scripts\pull_teramind_daily.py --dry-run

REM M365 + CP auth (weekly audit)
python -c "import sys; sys.path.insert(0, r'technijian\tech-training\scripts'); from _secrets import get_m365_credentials; t,c,s,m = get_m365_credentials(); print('M365 OK; mailbox =', m)"
```

---

## 10. Scheduled Tasks

All tasks run as the **logged-in workstation user** (not SYSTEM). SYSTEM cannot read OneDrive-synced keyfiles.

| Task Name | Trigger | Command | Skill Ref | Status |
|-----------|---------|---------|-----------|--------|
| `Technijian-DailyHuntressPull` | Daily 01:00 PT | `technijian\huntress-pull\run-daily-huntress.cmd` | `huntress-daily-pull` | Active |
| `Technijian-DailyUmbrellaPull` | Daily 02:00 PT | `technijian\umbrella-pull\run-daily-umbrella.cmd` | `umbrella-daily-pull` | Pending install |
| `Technijian-DailyCrowdStrikePull` | Daily 03:00 PT | `technijian\crowdstrike-pull\run-daily-crowdstrike.cmd` | `crowdstrike-daily-pull` | Pending install |
| `Technijian-DailyTeramindPull` | Daily 04:00 PT | `technijian\teramind-pull\run-daily-teramind.cmd` | — | Active |
| `Technijian-MonthlyClientPull` | 1st of month 07:00 PT | `technijian\monthly-pull\run-monthly-pull.cmd` | `monthly-client-pull` | Active |
| `Technijian Weekly Time-Entry Audit` | Weekly Friday 07:00 PT | `technijian\weekly-audit\run_weekly.bat` | `weekly-time-audit` | Active |
| `Technijian-MonthlyScreenConnectPull` | Monthly 28th 20:00 | `technijian\screenconnect-pull\run-monthly-sc.cmd` | — | Active (interactive session required) |
| `Technijian-DailySessionAnalysis` | Daily ~04:00 PT | `analyze_sessions_gemini.py` (not yet wired) | `screenconnect-video-analysis` | Pending (Gemini key + MP4s needed) |

**Stagger rationale:** 01:00 Huntress → 02:00 Umbrella → 03:00 CrowdStrike → 04:00 Teramind → 07:00 Monthly/Weekly. Avoids CP API and disk contention.

**Registration commands** are in `workstation.md` sections 6, 12, 18, 23, and `technijian/umbrella-pull/workstation.md`, `technijian/weekly-audit/workstation.md`, `technijian/screenconnect-pull/workstation.md`.

**Settings for all tasks:**
- "Run as soon as possible after a scheduled start is missed" — catches up after sleep/power-off.
- "Run only when user is logged on" — required for tasks using OneDrive keyfiles.
- SC recording task additionally requires interactive session for the GUI tool.

---

## 11. Known Constraints and Limitations

### 11.1 API constraints

| System | Constraint | Impact |
|--------|-----------|--------|
| Huntress v1 `/agents` | No historical date filter | Agent inventory is point-in-time only; cannot backfill who had Huntress on a specific past date |
| Huntress v1 | No SAT endpoints | Security Awareness Training data requires manual export from SAT portal |
| Falcon Flight Control alerts/incidents | `member_cid` silently ignored | Must pull at parent level, bucket by `cid` field (already implemented) |
| Falcon Incidents/Discover/Spotlight | Scope not granted | Pull degrades gracefully; re-run after scope grant |
| Cisco Umbrella activity | 5,000 record cap per pull; 10,000 offset cap per window | Busy 24h windows truncate; use aggregation endpoints for backfill |
| Cisco Umbrella activity retention | ~90 days | Data older than ~90 days returns empty silently |
| Umbrella per-org keys | Cannot be created via Management API | Require Playwright browser automation with 2FA (interactive session, one-time per org) |
| Teramind cubes | Only 4 of ~10 cube types licensed | `sessions`, `alerts`, `file_transfers`, `emails`, `cli`, `printing` return "unknown cube" |
| Teramind SSL | Self-signed cert | SSL verification disabled in `teramind_api.py`; no action needed |

### 11.2 Tool constraints

| Tool | Constraint |
|------|-----------|
| `SessionCaptureProcessor.exe` | GUI-only; requires interactive Windows session; cannot run as SYSTEM |
| SC recordings share | 30-day purge on session events in SQLite; run monthly pipeline before the 28th |
| Gemini video analysis | Requires Gemini API key (not yet provisioned) and MP4s in FileCabinet (SC pipeline must complete first) |
| `python-docx` logo dependency | Logo must exist at `C:\VSCode\tech-branding\tech-branding\assets\logos\png\technijian-logo-full-color-600x125.png` |

### 11.3 Mapping coverage

| System | Mapped clients (2026-04-29) |
|--------|----------------------------|
| Huntress | 29 of 29 orgs (3 Technijian-internal in ignore list) |
| CrowdStrike | 29 of 36 child CIDs |
| Umbrella | 1 of 29 customer orgs (VAF only; per-org keys pending) |
| Teramind | 3 clients (LAG, MKC, QOSNET) |

### 11.4 Workstation-only operation

All pipelines run on Windows. No Linux/macOS compatibility has been tested. Scheduled Tasks require Windows Task Scheduler. OneDrive sync requires Windows OneDrive client signed into the Technijian tenant.

---

## 12. Future Work

### 12.1 Complete Cisco Umbrella MSP key creation

**What:** Run `create_customer_api_keys.py` to create OAuth2 keys for all 29 customer orgs via Playwright (requires 2FA, interactive session). Then update `umbrella_api.py` for multi-org operation, run full 90-day backfill, and generate monthly reports.

**Blocked by:** Interactive browser session + Cisco 2FA. Must run with `run_in_background=True` per `feedback_playwright_background_runs.md`.

### 12.2 Install pending scheduled tasks

`Technijian-DailyCrowdStrikePull` and `Technijian-DailyUmbrellaPull` are not yet installed on the production workstation. See `workstation.md` sections 18 and `technijian/umbrella-pull/workstation.md`.

### 12.3 ScreenConnect video analysis (Gemini)

**Blocked by:** (1) Gemini API key not yet in `keys/gemini.md`; (2) MP4s need to be in OneDrive FileCabinet (SC pipeline must complete). Once unblocked, run `analyze_sessions_gemini.py`. Free tier: 1,500 req/day; initial 2,576-session backfill ~2 days.

### 12.4 Huntress SAT data

Huntress Managed Security Awareness Training has no v1 API endpoint as of 2026-04. SAT exports are manual. When endpoints ship, extend `huntress_api.py` and add per-client SAT outputs.

### 12.5 Umbrella monthly report generator

`build_umbrella_monthly_report.py` exists but is blocked on per-org keys being created. After key creation, run to generate monthly branded DOCX per client.

### 12.6 Contacts designation gaps

10 active managed-IT clients still need a contact designation set in the Client Portal (`needs_designation_set.csv`). Have portal admin set Primary Contact for each. Next `build_contacts_report.py` run will auto-resolve them.

### 12.7 Weekly audit pattern report (`5_pattern_report.py`)

The rolling `technijian/weekly-audit/by-tech/<slug>/history.csv` accumulates cross-cycle flag history. A future `5_pattern_report.py` would email team leads a monthly per-tech pattern summary (top categories flagged, repeat offenders, trend). Out of scope for v1.

### 12.8 Weekly audit enforcement

The deferred auto-deletion spec lives at `technijian/weekly-audit/API-DELETE-ENDPOINT-SPEC.md` (soft-delete column, SP signatures, audit table, REST URL, Python helpers, deployment checklist). Do not wire without explicit re-approval.

### 12.9 Unify fragmented workstation.md files

Three workstation setup files exist: `workstation.md` (root), `technijian/weekly-audit/workstation.md`, `technijian/umbrella-pull/workstation.md`, `technijian/screenconnect-pull/workstation.md`. Consolidate into a single top-level `workstation.md` with per-pipeline subsections.

### 12.10 Teramind data growth

Teramind is newly deployed with 0 activity data as of 2026-04-29. As monitored employees generate data, the activity cubes will populate. Add new clients to `DOMAIN_MAP` in `build_teramind_compliance_report.py` when they enroll.

### 12.11 MyRMM / ManageEngine SQL Server

TE-DC-MYRMM-SQL (10.100.13.11) hosts ManageEngine Endpoint Central Plus + MyRMM on SQL Server. Credentials in `keys/myrmm-sql.md` are marked TODO — not yet supplied. No pipeline currently reads from this server.

### 12.12 Annual review automation

The annual review pipeline (`technijian/tech-training/`) is driven manually today. A future scheduled annual job is a 2027+ concern once the cycle's inputs and human-review steps are codified.

---

## Appendix A: Quick-Reference Command Cheat Sheet

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM Monthly client pull
python technijian\monthly-pull\scripts\pull_monthly.py
python technijian\monthly-pull\scripts\pull_monthly.py --month 2026-04 --only AAVA,BWH

REM Weekly audit
python technijian\weekly-audit\scripts\run_weekly.py --drafts-only
python technijian\weekly-audit\scripts\4_email_weekly.py --send-existing
python technijian\weekly-audit\scripts\run_weekly.py --cycle 2026-W17

REM Huntress
python technijian\huntress-pull\scripts\pull_huntress_daily.py --map-only
python technijian\huntress-pull\scripts\pull_huntress_daily.py --only BWH
python technijian\huntress-pull\scripts\backfill_huntress.py --year 2026
python technijian\huntress-pull\scripts\build_monthly_report.py --month 2026-03

REM CrowdStrike
python technijian\crowdstrike-pull\scripts\pull_crowdstrike_daily.py --map-only
python technijian\crowdstrike-pull\scripts\pull_crowdstrike_daily.py --only AAVA
python technijian\crowdstrike-pull\scripts\backfill_crowdstrike.py --year 2026
python technijian\crowdstrike-pull\scripts\build_monthly_report.py --all-months

REM Umbrella
python technijian\umbrella-pull\scripts\pull_umbrella_daily.py --map-only
python technijian\umbrella-pull\scripts\pull_umbrella_daily.py --only VAF
python technijian\umbrella-pull\scripts\backfill_umbrella.py --start 2026-01-30 --end 2026-04-28 --only VAF

REM Teramind
python technijian\teramind-pull\scripts\pull_teramind_daily.py --dry-run
python technijian\teramind-pull\scripts\pull_teramind_daily.py
python technijian\teramind-pull\scripts\build_teramind_compliance_report.py --month 2026-04

REM ScreenConnect
technijian\screenconnect-pull\run-monthly-sc.cmd
python technijian\screenconnect-pull\scripts\build_client_audit.py --all --year 2026
Get-Content c:\tmp\sc_watch.log -Tail 20

REM Contacts
python scripts\contacts\build_contacts_report.py

REM Annual review
python technijian\tech-training\scripts\_audit-all-clients.py 2026
python technijian\tech-training\scripts\_build-all-reports.py 2026
python technijian\tech-training\scripts\_resolve-tech-emails.py 2026 --refresh
python technijian\tech-training\scripts\_create-outlook-drafts.py 2026
python technijian\tech-training\scripts\_send-drafts.py 2026

REM Cumulative full-history pull
python scripts\clientportal\pull_all_active.py --only BWH

REM DOCX proofreader
python technijian\shared\scripts\proofread_docx.py clients\bwh\huntress\monthly\2026-03\BWH-Cybersecurity-Activity-2026-03.docx
```

---

*Last updated 2026-04-29. When a new pipeline ships or a cadence changes, update this file and bump the date.*
