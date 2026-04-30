# Technijian Annual-Client-Review — System Specification

**Version:** 1.1
**Date:** 2026-04-30
**Owner:** rjain@technijian.com
**Repo:** `c:\vscode\annual-client-review\annual-client-review`

Read this before working in the repo. Update it when a new pipeline ships or a cadence changes.

---

## 1. System Overview

This repo is the **data capture, audit, reporting, and automated-ticketing system** for Technijian's managed-IT client base. It is not a deployed application. Every pipeline is a Python script driven on-demand or by a Windows Scheduled Task on a dedicated production workstation.

**Primary goals:**

1. **Annual client reviews** — produce branded Word + Excel deliverables per client showing service delivery, security posture, and billing accuracy for the year.
2. **Ongoing security reporting** — daily EDR/DNS/DLP snapshots (Huntress, CrowdStrike, Umbrella, Teramind, Sophos, Meraki) feed monthly branded DOCX reports delivered to client signers.
3. **Time-entry hygiene** — weekly Friday audit flags outlier entries and emails each tech coaching before the invoice run.
4. **Security alert routing** — Sophos Central connectivity events and M365 threat detections are automatically classified and routed as billable client tickets to the India support pod (CHD : TS1) via `stp_xml_Tkt_API_CreateV3`.
5. **Firewall change management** — Cisco Meraki admin change logs + daily config snapshots provide a full audit trail of who changed what on each client's network. Sophos XGS on-box config pull is pending whitelist setup.

**Read/write posture:** Most pipelines are read-only toward external systems. The following pipelines write back to the Client Portal:
- **Sophos alert router** (`route_alerts.py --apply`) — creates billable client tickets.
- **M365 ticket creator** (`create_m365_tickets.py`) — creates billable client tickets for threat events.

The weekly audit is recommend-only (no auto-deletion). See `technijian/weekly-audit/API-DELETE-ENDPOINT-SPEC.md` for the deferred enforcement path.

---

## 2. Architecture Overview

```
                         DATA SOURCES
  +------------------+------------------+---------------------+
  |  Client Portal   |  Security APIs   |  Network/Cloud      |
  |  (CP API)        |                  |                      |
  |  CP_USERNAME/    |  Huntress v1     |  Cisco Meraki API    |
  |  CP_PASSWORD     |  CrowdStrike     |  Sophos Central API  |
  |  + ticket write  |  Cisco Umbrella  |  Sophos XGS on-box   |
  |                  |  Teramind DLP    |  M365 Graph API      |
  +--------+---------+--------+---------+----------+----------+
           |                  |                    |
           v                  v                    v
  +------------------------------------------------------------+
  |                    PIPELINE LAYER                          |
  |                                                            |
  |  monthly-pull    huntress-pull    sc-recording-pull        |
  |  weekly-audit    crowdstrike-pull  teramind-pull           |
  |  cumul-pull      umbrella-pull    sc-video-analysis        |
  |  annual-review   contacts-pipeline                         |
  |  meraki-pull     sophos-pull      m365-pull                |
  +------------------------+-----------------------------------+
                           |
         +-----------------+-----------------+
         v                 v                 v
  +---------------+  +-------------+  +-------------+
  | clients/<code>|  | technijian/ |  | Client Portal|
  |  monthly/     |  |  weekly-/   |  | (tickets via |
  |  huntress/    |  |  contacts/  |  |  cp_tickets) |
  |  crowdstrike/ |  |  tech-train |  +-------------+
  |  umbrella/    |  |  teramind/  |
  |  meraki/      |  |  sophos/    |
  |  sophos/      |  |  m365-pull/ |
  |  m365/        |  +-------------+
  |  screenconnect|
  |  data/        |
  +---------------+

  SHARED MODULES
  +------------------------------------------------------------+
  |  scripts/clientportal/cp_api.py     (CP auth + SPs)        |
  |  scripts/clientportal/cp_tickets.py (ticket creation)      |
  |  scripts/contacts/contacts_lib.py   (tech-legal bridge)    |
  |  technijian/shared/scripts/_brand.py         (DOCX)        |
  |  technijian/shared/scripts/proofread_docx.py (QA gate)     |
  |  technijian/tech-training/scripts/_secrets.py (M365)       |
  +------------------------------------------------------------+
```

---

## 3. Data Sources

| # | System | Endpoint / Location | Auth | What Is Pulled | Retention / Limits |
|---|--------|---------------------|------|----------------|--------------------|
| 1 | **Technijian Client Portal** | `https://api-clientportal.technijian.com` | Bearer token (username/password) | Active clients, time entries, tickets, invoices, contracts, directory | Read-only; also writes tickets via `stp_xml_Tkt_API_CreateV3` |
| 2 | **Huntress v1 REST API** | `https://api.huntress.io/v1` | HTTP Basic (API Key ID + Secret) | Agent inventory, incident reports, signals, reports | Agents: point-in-time only; incidents/signals/reports: supports date filter |
| 3 | **CrowdStrike Falcon API** | `https://api.us-2.crowdstrike.com` | OAuth2 client_credentials | Hosts, alerts, policies, MSSP children | Token TTL ~30 min; alerts queryable by date |
| 4 | **Cisco Umbrella** | `https://api.umbrella.com` | OAuth2 client_credentials (per org) | Roaming computers, sites, activity, blocked threats, top destinations | Activity retention ~90 days; 10K record offset cap per window |
| 5 | **Teramind (on-prem)** | `https://myaudit2.technijian.com` | `X-Access-Token` header | Agents, computers, departments, DLP policies, activity cubes, risk scores | Self-signed SSL (verification disabled) |
| 6 | **ScreenConnect (SQLite + file share)** | `\\10.100.14.10\C$\...\Session.db` + `R:\` | Admin credentials (UNC share) | Session metadata, tech names, recording files (CRV) | 30-day session event purge; recordings on E:\ (417 GB free) |
| 7 | **tech-legal repo** | `C:\vscode\tech-legal\tech-legal\clients\<CODE>\CONTACTS.md` | Local filesystem | Per-client contact designations, portal DirIDs, signer info | Local filesystem; updated manually |
| 8 | **Microsoft 365 Graph (single-tenant)** | `https://graph.microsoft.com` | OAuth2 client_credentials | Mail.Send for tech coaching emails (HiringPipeline-Automation app) | Standard Graph limits |
| 9 | **Microsoft 365 Graph (multi-tenant / MSP)** | `https://graph.microsoft.com` | OAuth2 client_credentials per tenant | Sign-in logs, risky users, secure score, license inventory (Technijian-Partner-Graph-Read app) | 11/18 tenants consented; GDAP required for remaining 7 |
| 10 | **Cisco Meraki Dashboard API** | `https://api.meraki.com/api/v1` | Bearer API key | Network events, IDS/IPS, firewall rules, VLANs, SSIDs, VPN tunnels, admin change log | 9 orgs (7 active, 2 dormant); event retention ~90 days; Bearer header (NOT X-Cisco-Meraki-API-Key) |
| 11 | **Sophos Central Partner API** | `https://api.central.sophos.com` | OAuth2 client_credentials (partner) | Tenant list, admin roles, firewall inventory, SIEM connectivity events, open alerts | 11 tenants, 9 mapped; SIEM 24h lookback ceiling; IPS/IDS NOT exposed (syslog required) |
| 12 | **Sophos XGS on-box API** | `https://<fw-wan-ip>:4444/webconsole/APIController` | Username + password (per-device XML) | Full firewall config: rules, NAT, VPN, interfaces, DHCP, static routes | Self-signed cert; requires whitelist of scanner IP per firewall — PENDING SETUP |

### 3.1 Client Portal stored procedures used

| SP | Purpose |
|----|---------|
| `GET /api/clients/active` | Active client list with LocationCode / DirID / Location_Name |
| `[timeentry].[Reporting].[stp_xml_TktEntry_List_Get]` | Time entries by (ClientID, Start, End) |
| `[invoices].[dbo].[stp_xml_Inv_Org_Loc_Inv_List_Get]` | Invoice history by DirID |
| `GetAllContracts` | Active contract resolution per client |
| `stp_Get_All_Dir` | Full directory lookup; also provides LocationTopFilter per DirID |
| `stp_xml_Tkt_API_CreateV3` | **Create billable client ticket** (XML_IN envelope; confirmed working 2026-04-30) |

**Stable per-entry ID:** `InvDetID` in the time-entry XML. Use for diffing/fingerprinting.

**Per-client meta cache:** `clients/<code>/_meta.json` — populated by `scripts/clientportal/build_client_meta.py`. Contains DirID, ContractID, LocationTopFilter, Location_Name, and recipient emails. Rebuild after client changes.

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
| Cisco Umbrella Daily Pull | Daily, 02:00 PT | `technijian/umbrella-pull/scripts/pull_umbrella_daily.py` | Scheduled task | `clients/<code>/umbrella/` | Task pending install; 29/29 per-org keys complete 2026-04-29 |
| Umbrella Backfill | On demand | `technijian/umbrella-pull/scripts/backfill_umbrella.py` | Manual | `clients/<code>/umbrella/` | Available |
| Umbrella Monthly Report | On demand | `technijian/umbrella-pull/scripts/build_umbrella_monthly_report.py` | Manual | `clients/<code>/umbrella/monthly/<YYYY-MM>/` | Active (per-org keys complete) |
| Teramind Daily Pull | Daily, 04:00 PT | `technijian/teramind-pull/scripts/pull_teramind_daily.py` | Scheduled task | `technijian/teramind-pull/` | Active (3 clients mapped) |
| Teramind Compliance Report | On demand | `technijian/teramind-pull/scripts/build_teramind_compliance_report.py` | Manual | `technijian/teramind-pull/<date>/reports/` | Active |
| **Cisco Meraki Daily Pull** | **Daily, 05:00 PT** | `scripts/meraki/pull_all.py` | Scheduled task | `clients/<code>/meraki/` | **Active** |
| **Meraki Monthly Report** | **1st of month** | `scripts/meraki/generate_monthly_docx.py` | Manual | `clients/<code>/meraki/reports/` | **Active; 28/28 pass 8/8 Jan–Apr 2026** |
| **Sophos Hourly Alert Pull** | **Hourly :15** | `technijian/sophos-pull/scripts/pull_sophos_daily.py` | Scheduled task | `clients/<code>/sophos/<date>/` | **Active (9 clients)** |
| **Sophos Alert Router** | **Hourly :15** | `technijian/sophos-pull/scripts/route_alerts.py` | Run by hourly wrapper | `state/alert-tickets.json` | **Active (--apply mode)** |
| **Sophos Monthly Report** | **1st of month** | `technijian/sophos-pull/scripts/build_sophos_monthly_report.py` | Manual | `clients/<code>/sophos/reports/` | **Active; 9/9 pass 8/8 Apr 2026** |
| **Sophos XGS Config Scan** | **On demand** | `technijian/sophos-pull/scripts/scan_sophos_fw_api.py` | Manual | `clients/<code>/sophos/<date>/config.json` | **Pending (whitelist required per firewall)** |
| **M365 Security Pull** | **Every 4h** | `technijian/m365-pull/scripts/pull_m365_security.py` | Scheduled task | `clients/<code>/m365/` | **Active (11/18 tenants)** |
| **M365 Compliance Pull** | **Daily** | `technijian/m365-pull/scripts/pull_m365_compliance.py` | Scheduled task | `clients/<code>/m365/` | **Active (11/18 tenants)** |
| **M365 License/Storage Pull** | **Weekly** | `technijian/m365-pull/scripts/pull_m365_storage.py` | Scheduled task | `clients/<code>/m365/` | **Active (11/18 tenants)** |
| **M365 Monthly Report** | **1st of month** | `technijian/m365-pull/scripts/build_m365_monthly_report.py` | Manual | `clients/<code>/m365/reports/` | **Active** |
| **M365 Security Ticket Creator** | **Automated (post-pull)** | `technijian/m365-pull/scripts/create_m365_tickets.py` | Called by security pull | CP API | **Active; 63 tickets created 2026-04-30** |
| ScreenConnect Recording Pull | Monthly, 28th, 20:00 | `technijian/screenconnect-pull/run-monthly-sc.cmd` | Scheduled task | `clients/<code>/screenconnect/` + OneDrive FileCabinet | Active |
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
```

**Scheduled task:** `Technijian-MonthlyClientPull` — monthly on day 1 at 07:00.

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
| H5 | Same tech + ticket + day with sum > 2x category cap |

Category caps (32 entries) live in `technijian/weekly-audit/scripts/_shared.py::CATEGORY_CAP`.

**Data flow (4-script pipeline):**
```
1_pull_weekly.py   -> raw/<client>/{time_entries.xml, time_entries.csv}
2_audit_weekly.py  -> SUMMARY.md, all-flagged-entries.csv, by-client/, by-tech/
3_build_weekly_docs.py -> by-tech/<slug>/<slug>-Weekly-Training.docx
4_email_weekly.py  -> Graph API create draft -> send; manifests written
run_weekly.py      -> orchestrates 1->2->3->4, aborts on failure
```

**Scheduled task:** `Technijian Weekly Time-Entry Audit` — weekly on Friday at 07:00.

**Constraint:** Recommend-only — no auto-deletion. `CEO R-Jain` excluded from recipient list. Draft-only path via `run_weekly.py --drafts-only`.

---

### 5.3 Huntress Daily Pull + Backfill + Report

**Purpose:** Daily agent inventory snapshot per client. Backfill of historical incidents, signals, and reports. Monthly branded DOCX for client delivery.

**Cadence:** Daily at 01:00 PT.

**Key facts:**
- Agent inventory is point-in-time only — no historical filter on `/v1/agents`. Do not attempt to backfill agents.
- Incidents/signals/reports DO support date filtering and are covered by `backfill_huntress.py`.
- SAT (Security Awareness Training) is NOT in the Huntress v1 API as of 2026-04.
- Cursor pagination: `limit` + `page_token` -> `pagination.next_page_token`.

**Output schema:**
```
clients/<code>/huntress/YYYY-MM-DD/
  agents.json + agents.csv + incident_reports.json + signals.json + reports.json + pull_summary.json

clients/<code>/huntress/monthly/YYYY-MM/
  incident_reports.json + signals.json + reports.json + pull_summary.json
  <CODE>-Cybersecurity-Activity-YYYY-MM.docx   (branded client report)
```

**Scheduled task:** `Technijian-DailyHuntressPull` — daily at 01:00.

**Backfill status:** 2026-01 through 2026-04 completed 2026-04-29 (29 mapped clients, 116 client-months).

---

### 5.4 CrowdStrike Daily Pull

**Purpose:** Daily Falcon EDR snapshot per client. Multi-tenant via Flight Control (36 child CIDs). Monthly branded DOCX for client delivery.

**Cadence:** Daily at 03:00 PT.

**Key facts — Flight Control quirk (critical):** The `/alerts/queries/alerts/v2`, `/detects/queries/detects/v1`, and `/incidents/queries/incidents/v1` endpoints **silently ignore `member_cid`** for Flight Control parent CIDs. Pull once at the parent level, then bucket by the `cid` field on each record. The Hosts API correctly honors `member_cid`.

**Output schema:**
```
clients/<code>/crowdstrike/YYYY-MM-DD/
  hosts.json + alerts.json + pull_summary.json

clients/<code>/crowdstrike/monthly/YYYY-MM/
  alerts.json + incidents.json + behaviors.json + pull_summary.json
  <CODE>-CrowdStrike-Activity-YYYY-MM.docx
```

**Scheduled task:** `Technijian-DailyCrowdStrikePull` — daily at 03:00. **Task not yet installed on production workstation.**

---

### 5.5 Cisco Umbrella Daily Pull

**Purpose:** Daily DNS security snapshot per client. Captures roaming computer inventory, sites, activity, top destinations, and blocked threats.

**Cadence:** Daily at 02:00 PT.

**Tenancy model:** MSP parent org `8163754` with **29 child orgs** (one per client). Per-customer keys completed 2026-04-29 for all 29 orgs via Playwright automation.

**MSP child org IDs (29 orgs):** B2I=8182603, ANI=8182605, TECH=8182611, TDC=8182613, ISI=8182639, NOR=8182646, ORX=8182647, RSPMD=8182655, SAS=8182656, VAF=8182659, AAVA=8212809, KSS=8213557, AOC=8219569, BWH=8219571, CCC=8219573, MAX=8219576, ACU=8228246, JDH=8256091, HHOC=8262496, TALY=8270949, CBI=8298405, RMG=8315328, SGC=8316182, ALG=8316664, KES=8323805, JSD=8324833, DTS=8347026, EBRMD=8347471, AFFG=8390093.

**Scheduled task:** `Technijian-DailyUmbrellaPull` — daily at 02:00. **Task not yet installed on production workstation.**

---

### 5.6 Teramind Daily Pull

**Purpose:** Daily compliance and DLP activity snapshots from the on-premise Teramind server.

**Cadence:** Daily at 04:00 PT.

**Auth quirk:** Uses `X-Access-Token: <token>` header — NOT `Authorization: Bearer`. SSL verification disabled for self-signed cert.

**Valid cubes:** `activity`, `keystrokes`, `web_search`, `social_media`. Other cubes return "unknown cube" — not licensed.

**Scheduled task:** `Technijian-DailyTeramindPull` — daily at 04:00.

---

### 5.7 ScreenConnect Recording Pipeline

**Purpose:** Convert monthly ScreenConnect session recordings to MP4, archive to OneDrive/Teams FileCabinet, produce per-client audit CSVs.

**Cadence:** Monthly on the 28th at 20:00 (before the 30-day SC session purge).

**Full specification:** `docs/screenconnect-recording-pipeline.md`.

**Scheduled task:** `Technijian-MonthlyScreenConnectPull` — monthly on day 28 at 20:00. Requires interactive session.

---

### 5.8 Contacts / Send-List Pipeline

**Purpose:** Resolve the client contact email address for each active managed-IT client. Produce the `send_list_<YYYY-MM>.csv` used by report-delivery pipelines.

**Two-layer recipient resolution:**
- **Layer 1:** Portal designation (Primary Contact, Invoice Recipient, or Contract Signer section).
- **Layer 2:** Most-recent active contract's `Signed_DirID` via `stp_Get_All_Dir`. Excludes `@technijian.com`.
- **Never fall back to C1/C2/C3 portal role lists.**

---

### 5.9 Annual Client Review

**Purpose:** Per-client branded annual deliverables — Word + Excel reports showing service delivery, billing analysis, security posture, and time-entry coaching.

**Cadence:** Manual — once per year per client. 2026 cycle complete.

---

### 5.10 Cisco Meraki Daily Pull + Monthly Report

**Purpose:** Daily firewall event, IDS/IPS, configuration, and admin change-log snapshot across all Meraki organizations. Monthly branded DOCX for client delivery covering firewall config, security posture, and change management.

**Cadence:** Daily at 05:00 PT.

**Scope:** 9 organizations (7 licensed/active, 2 dormant); 11 networks; ~30 devices. Org-to-LocationCode mapping in `scripts/meraki/_org_mapping.py`.

**Auth:** Bearer API key in `keys/meraki.md`. Do NOT use the legacy `X-Cisco-Meraki-API-Key` header — newer keys reject it.

**Key scripts:**

| Script | Purpose |
|--------|---------|
| `scripts/meraki/pull_all.py` | Daily one-shot (events + config + change log) |
| `scripts/meraki/pull_security_events.py` | IDS/IPS + AMP events |
| `scripts/meraki/pull_network_events.py` | Firewall/VPN/DHCP activity log per network |
| `scripts/meraki/pull_configuration.py` | Full config snapshot (WAN IPs, L3 rules, VLANs, SSIDs, VPN tunnels) |
| `scripts/meraki/pull_change_log.py` | Admin change log (who changed what, before/after values) |
| `scripts/meraki/aggregate_monthly.py` | Monthly rollup for report builder |
| `scripts/meraki/generate_monthly_docx.py` | Branded DOCX per client per month |
| `scripts/meraki/meraki_api.py` | Shared API client |

**Output schema:**
```
clients/<code>/meraki/YYYY-MM-DD/
  security_events.json      IDS/IPS + AMP events
  network_events.json       firewall/VPN/DHCP activity
  configuration.json        full config snapshot (rules, VLANs, SSIDs, VPN)
  change_log.json           admin change log
  pull_summary.json

clients/<code>/meraki/reports/
  <CODE> - Meraki Monthly Activity - YYYY-MM.docx   (branded client report)

technijian/sophos-pull/
  (Meraki runs under scripts/meraki/, not technijian/)
```

**Report sections:** Executive Summary (metric cards), Network & Device Inventory, Firewall Configuration (WAN IPs, L3 rules, VLANs, SSIDs, VPN), Security Posture, Configuration Changes, IDS/IPS & AMP Events, Firewall/Network Activity, Daily Trend.

**Proofreader gate:** 8/8 checks. Section string:
`"Executive Summary,Network & Device Inventory,Firewall Configuration,Security Posture,Configuration Changes,IDS/IPS & AMP Events,Firewall / Network Activity,Daily Trend"`

**Status:** 28/28 reports pass 8/8 checks for Jan–Apr 2026, 7 active orgs.

**Scheduled task:** `Technijian-DailyMerakiPull` — daily at 05:00.

---

### 5.11 Sophos Central Partner Pipeline

**Purpose:** Hourly snapshot of firewall inventory, SIEM connectivity events, and open alerts across all Sophos Central tenants. Routes open alerts as billable client tickets to the India support pod. Monthly branded DOCX for client delivery. On-demand config pull from individual XGS appliances (pending whitelist).

**Cadence:** Hourly at :15 (3-step pipeline in `run-hourly-sophos.cmd`).

**Scope:** 11 tenants, 9 mapped to LocationCodes (Yebo unmapped, Technijian ignored as house tenant). 14 firewalls (virtual SFV/XGS, SFOS 19.5–22.0). All alerts in CONNECTIVITY group — gateway up/down, lost connection, reconnected. 0 endpoint events (Intercept-X not deployed in any tenant as of 2026-04-30).

**Auth:** OAuth2 client_credentials to `https://id.sophos.com/api/v2/oauth2/token`. Partner ID: `c73e576d-f324-4d00-8834-8815bab742c9`. Credential name in Sophos Central: "ClaudeCode".

**Three pipeline steps:**

1. `pull_sophos_daily.py` — snapshots per-tenant firewalls + last-24h SIEM events + open alerts to `clients/<code>/sophos/<date>/`
2. `seed_tenant_map.py` — regenerates the rsyslog allowlist `state/sophos-tenant-ipmap.json` from live firewall WAN IPs
3. `route_alerts.py --apply` — classifies alerts NEW/AGING/QUIET/RESOLVED; creates client-billable CP tickets assigned to CHD : TS1 (DirID 205); sends reminder emails after 24h

**Key scripts:**

| Script | Purpose |
|--------|---------|
| `technijian/sophos-pull/scripts/pull_sophos_daily.py` | Hourly data pull |
| `technijian/sophos-pull/scripts/route_alerts.py` | Alert classification + CP ticket creation |
| `technijian/sophos-pull/scripts/seed_tenant_map.py` | Rsyslog WAN IP allowlist |
| `technijian/sophos-pull/scripts/build_sophos_monthly_report.py` | Monthly branded DOCX |
| `technijian/sophos-pull/scripts/scan_sophos_fw_api.py` | On-box XGS config scanner + puller |
| `technijian/sophos-pull/scripts/cp_tickets.py` | Sophos shim (re-exports canonical via importlib) |

**CP ticket creation:**
- Uses `stp_xml_Tkt_API_CreateV3` via canonical `scripts/clientportal/cp_tickets.py`
- Priority: 1255 (Same Day) if any high-severity alert; 1257 (When Convenient) otherwise
- One consolidated ticket per client per run (not per alert) — prevents ticket flood
- State tracked in `state/alert-tickets.json` (per-client ticket_id, created_at, last_email_sent_at)
- **Known issue (2026-04-30):** 8 tickets created before `extract_ticket_id` bug was fixed — IDs are null in state. Do not run `--apply` again until state is patched.

**Output schema:**
```
clients/<code>/sophos/YYYY-MM-DD/
  firewalls.json         firewall inventory (model, serial, firmware, WAN IPs, status)
  events.json            SIEM connectivity events (last 24h)
  alerts.json            open alerts
  config.json            on-box config pull (when whitelist enabled + credentials available)
  pull_summary.json

clients/<code>/sophos/reports/
  <CODE> - Sophos Monthly Activity - YYYY-MM.docx   (branded client report)

technijian/sophos-pull/state/
  alert-tickets.json            per-client ticket routing state
  sophos-tenant-ipmap.json      rsyslog WAN IP allowlist
  firewall-api-inventory.json   on-box scan results + WAN IP registry
```

**Report sections:** Executive Summary (metric cards), Firewall Inventory, Alert Summary, Connectivity Events, Firmware Updates, Recommendations, About This Report.

**Proofreader gate:** 8/8 checks. Section string:
`"Executive Summary,Firewall Inventory,Alert Summary,Connectivity Events,Recommendations,About This Report"`

**Status:** 9/9 April 2026 reports pass 8/8.

**On-box XGS config API:** Scanner runs at port 4444; scanner IP `64.58.160.218` must be whitelisted on each client's XGS (Administration > Device Access > WAN > HTTPS + API). All 10 firewalls currently NOT_WHITELISTED. Keyfile per client: `keys/sophos-fw-<CODE>.md`. Run `scan_sophos_fw_api.py --pull` after whitelist + credentials configured.

**API gaps (do not re-probe):**
- Per-signature IPS/IDS events: NOT in Partner API — requires syslog to Technijian DC (rsyslog TLS-6514).
- Firewall config: NOT in Partner API — use on-box API (port 4444) per above.
- License provisioning: NOT in Partner API — use partnerportal.sophos.com or Pax8.
- Admin account DELETE: NOT in Partner API — roles can be stripped via API; account deletion requires Playwright UI automation.

**Scheduled task:** `Technijian-MonthlySophosPull` (monthly, Day 1, 07:00 for report generation). Hourly alert pull: `Technijian-HourlySophosPull` at :15.

---

### 5.12 Microsoft 365 Security + Compliance Monitoring

**Purpose:** Daily sign-in threat detection and compliance posture scoring across all managed M365 tenants. Routes high-severity detections as billable client tickets to the India support pod.

**Cadence:** Security pull every 4h (India tech pod covered 24x7); compliance pull daily; license/storage pull weekly.

**Scope:** 11/18 tenants consented via Technijian-Partner-Graph-Read multi-tenant app. Remaining 7 require GDAP (Granular Delegated Admin Privileges) setup. Gate file: `technijian/m365-pull/state/gdap_status.csv`.

**Auth:** OAuth2 client_credentials per tenant using the Technijian-Partner-Graph-Read app (multi-tenant, admin-consented per client tenant). Credentials in `keys/m365-partner.md`.

**Key scripts:**

| Script | Purpose |
|--------|---------|
| `technijian/m365-pull/scripts/pull_m365_security.py` | Sign-in risk + risky users + threat detections |
| `technijian/m365-pull/scripts/pull_m365_compliance.py` | Secure Score + compliance posture |
| `technijian/m365-pull/scripts/pull_m365_storage.py` | License inventory + mailbox/OneDrive storage |
| `technijian/m365-pull/scripts/build_m365_monthly_report.py` | Monthly branded DOCX |
| `technijian/m365-pull/scripts/create_m365_tickets.py` | CP ticket creation for security events |
| `technijian/m365-pull/scripts/m365_api.py` | Shared Graph API client |
| `technijian/m365-pull/scripts/discover_gdap.py` | GDAP consent status discovery |
| `technijian/m365-pull/scripts/check_access.py` | Pre-flight access verification per tenant |

**CP ticket creation:**
- Uses `stp_xml_Tkt_API_CreateV3` via canonical `scripts/clientportal/cp_tickets.py`
- Escalation: active-attack severity tickets escalated with 2h follow-up
- 63 tickets created 2026-04-30 across 11 tenants

**Output schema:**
```
clients/<code>/m365/YYYY-MM-DD/
  security.json          sign-in risk events, risky users, threat detections
  compliance.json        Secure Score, control scores
  licenses.json          license SKUs, assigned/unassigned counts
  storage.json           mailbox + OneDrive usage
  pull_summary.json

clients/<code>/m365/reports/
  <CODE> - M365 Monthly Activity - YYYY-MM.docx

technijian/m365-pull/state/
  gdap_status.csv        per-tenant GDAP activation status
```

**License filtering:** Viral SKUs (>= 1,000 seats or "FREE"/"VIRAL" in name) are excluded from the license inventory to avoid noise. TECHNIJIAN tenant: 16 recoverable seats identified.

**Scheduled tasks:**
- `Technijian-M365SecurityPull` — every 4h
- `Technijian-M365CompliancePull` — daily
- `Technijian-M365LicensePull` — weekly

---

### 5.13 Client Portal Ticket Creation

**Purpose:** Reusable billable-ticket creation layer used by Sophos and M365 pipelines. Creates tickets in the Technijian Client Portal via `stp_xml_Tkt_API_CreateV3`.

**Canonical module:** `scripts/clientportal/cp_tickets.py`

**SP endpoint:**
```
POST /api/modules/dbo/stored-procedures/client-portal/dbo/stp_xml_Tkt_API_CreateV3/execute
Body: {"Parameters": {"XML_IN": "<Root><Ticket>...</Ticket></Root>"}}
Response: outputParameters.XML_OUT = "<Root><Tickets><TicketID>N</TicketID></Tickets></Root>"
```

**Defaults:**

| Parameter | Value | Meaning |
|-----------|-------|---------|
| AssignTo_DirID | 205 | CHD : TS1 (India Tech Support pod) |
| Priority | 1257 | When Convenient |
| Status | 1259 | New |
| RoleType | 1232 | Tech Support |
| RequestType | "ClientPortal" | |
| Category | "API" | |

Helpers accept both numeric IDs and human-readable names: `priority="Same Day"`, `role_type="Off-Shore Tech Support"`, etc.

**LocationTopFilter** is read from `clients/<code>/_meta.json` (populated by `build_client_meta.py`) — format `Tech.Clients.<CODE>`. Pipelines must pass this to ensure tickets appear in the correct client filter in the CP UI.

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
| `clients/<code>/meraki/YYYY-MM-DD/` | Meraki Daily Pull | Meraki Monthly Report |
| `clients/<code>/meraki/reports/` | Meraki Monthly Report | Client delivery |
| `clients/<code>/sophos/YYYY-MM-DD/` | Sophos Hourly Pull | Sophos Monthly Report, alert routing |
| `clients/<code>/sophos/reports/` | Sophos Monthly Report | Client delivery |
| `clients/<code>/m365/YYYY-MM-DD/` | M365 Security/Compliance/License Pull | M365 Monthly Report, ticket creation |
| `clients/<code>/m365/reports/` | M365 Monthly Report | Client delivery |
| `clients/<code>/screenconnect/<year>/` | SC Recording Pull | Annual Review |
| `clients/<code>/screenconnect/<year>/session_analysis/` | SC Video Analysis (Gemini) | Annual Review |
| `clients/<code>/data/` | Cumulative Pull (`pull_all_active.py`) | Annual Review |
| `clients/<code>/_meta.json` | `build_client_meta.py` | cp_tickets.py, Sophos router, M365 router |
| `technijian/weekly-audit/<cycle>/` | Weekly Audit | Committed audit history |
| `technijian/huntress-pull/YYYY-MM-DD/` | Huntress Daily Pull | Audit trail |
| `technijian/crowdstrike-pull/YYYY-MM-DD/` | CrowdStrike Daily Pull | Audit trail |
| `technijian/umbrella-pull/YYYY-MM-DD/` | Umbrella Daily Pull | Audit trail |
| `technijian/teramind-pull/YYYY-MM-DD/` | Teramind Daily Pull | Compliance reports |
| `technijian/sophos-pull/state/` | Sophos router + scanner | Alert routing, config inventory |
| `technijian/m365-pull/state/` | M365 pipelines | GDAP status, run state |
| `technijian/contacts/` | Contacts Pipeline | All email-delivery pipelines |
| `OneDrive FileCabinet\<CLIENT>-<year>-<month>\` | SC Recording Pull | Teams/client |

---

## 7. Shared Infrastructure

### 7.1 CP API Client — `scripts/clientportal/cp_api.py`

Handles all Client Portal read interactions:
- `login()` — bearer token auth, caches token, re-auths on expiry
- `get_active_clients()` — returns list of `{DirID, LocationCode, Location_Name, ...}`
- `get_time_entries_xml(client_dir_id, start, end)` — calls `stp_xml_TktEntry_List_Get`
- `get_all_contracts()` / `find_active_signed_contract()` — contract resolution
- `parse_flat_xml(xml_str)` — parses `<Root><TimeEntry>` format to list of dicts
- `get_all_dir()` — calls `stp_Get_All_Dir` for directory lookups + LocationTopFilter
- `build_ticket_xml(...)` — builds XML envelope for `stp_xml_Tkt_API_CreateV3`
- `create_ticket_v3(xml_payload)` — calls the create SP
- `extract_ticket_id(result)` — parses `outputParameters.XML_OUT` XML to get new TicketID

**High-level ticket helper:** `scripts/clientportal/cp_tickets.py` — `create_ticket_for_code(code, *, title, description, **kwargs)` reads `_meta.json` and calls `create_ticket()`. Accepts human-readable priority/status/role_type names.

**Credentials:** `CP_USERNAME` / `CP_PASSWORD` env vars, or `OneDrive keys\client-portal.md`.

### 7.2 Contacts Library — `scripts/contacts/contacts_lib.py`

Bridge to the tech-legal repo. Never read contact data directly — always go through this library.

### 7.3 Brand Helpers — `technijian/shared/scripts/_brand.py`

Reusable `python-docx` helpers for all branded DOCX outputs. **Import this; do not fork it.**

The canonical copy is `technijian/shared/scripts/_brand.py`. A historical copy at `technijian/huntress-pull/scripts/_brand.py` is preserved for compatibility but is not the authoritative source.

Colors: `#006DB6` (core blue), `#F67D4B` (orange), `#1EAAC8` (teal), `#1A1A2E` (dark charcoal), `#59595B` (brand grey). Font: Open Sans 11pt.

Functions: `new_branded_document()`, `render_cover()`, `add_section_header()`, `add_body()`, `add_bullet()`, `styled_table()`, `add_metric_card_row()`, `add_callout_box()`.

### 7.4 DOCX Proofreader — `technijian/shared/scripts/proofread_docx.py`

Structural + content QA gate for all branded DOCX outputs. **8 checks** (as of 2026-04-30):

| Check | Notes |
|-------|-------|
| File size >= 10 KB | Configurable via --min-kb |
| Cover page not blank/placeholder | First non-empty paragraph |
| Expected section headers present | Searches all text including table cells |
| Table widths <= 6.5" | Added 2026-04-30; skips color bars + section-header tables |
| No all-blank tables | Excludes color bar tables and bar+title section headers |
| No placeholder text | TODO, TBD, [placeholder], [Your Name] |
| No mojibake | cp1252 double-encoding artifacts |
| Callout boxes present (warn) | Single-cell table |

**Wire into every report builder.** Exit code 0 = pass.

**Wired into:** Teramind, Huntress, Meraki, Sophos report builders.

**Verified passing (2026-04-30):** 219 reports total: 3 Teramind + 116 Huntress monthly + 54 tech-training + 9 annual/quarterly + 28 Meraki monthly (Jan–Apr 2026) + 9 Sophos monthly (Apr 2026).

### 7.5 M365 Credential Resolver — `technijian/tech-training/scripts/_secrets.py`

Returns `(tenant_id, client_id, client_secret, mailbox)` from env vars or `OneDrive keys\m365-graph.md`. Default mailbox: `RJain@technijian.com`. Used by weekly audit, annual review emails.

For M365 MSP multi-tenant pulls, credentials are resolved per-tenant from `keys/m365-partner.md`.

### 7.6 Keyfile Convention

All secrets live in OneDrive-synced markdown files at `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\`. Each file uses `**Label:** value` format parseable by the corresponding `_api.py` helper. Env vars take precedence over keyfiles for headless/CI environments. Never commit keyfiles.

---

## 8. Credentials and Keys

| Bundle | Env Vars | Keyfile Path | Used By | Notes |
|--------|----------|--------------|---------|-------|
| Client Portal | `CP_USERNAME`, `CP_PASSWORD` | `keys\client-portal.md` | All CP-touching pipelines | Read + write (ticket creation) |
| M365 Graph (single-tenant) | `M365_TENANT_ID`, `M365_CLIENT_ID`, `M365_CLIENT_SECRET`, `M365_MAILBOX` | `keys\m365-graph.md` | Weekly audit, Annual review email | App: HiringPipeline-Automation; Mail.Read + .Send + .ReadWrite |
| M365 Graph (multi-tenant MSP) | — | `keys\m365-partner.md` | M365 Security/Compliance/License pull | App: Technijian-Partner-Graph-Read; 11 tenants consented; GDAP for remaining 7 |
| Huntress | `HUNTRESS_API_KEY`, `HUNTRESS_API_SECRET` | `keys\huntress.md` | Huntress pull | |
| CrowdStrike | `CROWDSTRIKE_CLIENT_ID`, `CROWDSTRIKE_CLIENT_SECRET`, `CROWDSTRIKE_BASE_URL` | `keys\crowdstrike.md` | CrowdStrike pull | OAuth2 US-2; read-only scopes |
| Cisco Umbrella (per-customer MSP) | — | `keys\cisco-umbrella.md` | Umbrella pull (29 orgs) | 29/29 per-customer keys complete 2026-04-29 |
| Teramind | `TERAMIND_HOST`, `TERAMIND_ACCESS_TOKEN` | `keys\teramind.md` | Teramind pull | X-Access-Token header |
| **Cisco Meraki** | `MERAKI_API_KEY` | `keys\meraki.md` | Meraki pull | Personal API key; 9 orgs admin; Bearer header only |
| **Sophos Central Partner** | `SOPHOS_CLIENT_ID`, `SOPHOS_CLIENT_SECRET` | `keys\sophos-central.md` | Sophos pull | OAuth2; partner_id = c73e576d-...; credential name "ClaudeCode" |
| **Sophos XGS on-box** | — | `keys\sophos-fw-<CODE>.md` | Sophos config scan | One file per client; Firewall N sections with WAN IP + credentials; PENDING (whitelist not yet configured) |
| ScreenConnect | — | `keys\screenconnect-web.md` | SC recording pull | |
| Gemini | `GEMINI_API_KEY` | `keys\gemini.md` | SC video analysis | Currently TODO — get from aistudio.google.com/apikey |

---

## 9. Workstation Requirements

### 9.1 Software

| Component | Version | Install |
|-----------|---------|---------|
| Python | 3.11+ (tested on 3.14.3) | `winget install -e --id Python.Python.3.12` |
| Git | Any modern | `winget install -e --id Git.Git` |
| FFmpeg | Any modern | `winget install --id Gyan.FFmpeg -e` (SC recording pipeline only) |
| Playwright for Python | Latest | `pip install playwright && python -m playwright install msedge` |
| python-docx, openpyxl | Latest | `pip install python-docx openpyxl` |
| OneDrive (Technijian tenant) | Signed in | Provides keyfiles; MUST be syncing before first run |

**Python path used in .cmd wrappers:** `C:\Python314\python.exe`.

### 9.2 Network access required

| Endpoint | Pipeline |
|----------|---------|
| `https://api-clientportal.technijian.com` | Monthly pull, Weekly audit, Annual review, ticket creation |
| `https://api.huntress.io` | Huntress pull |
| `https://api.us-2.crowdstrike.com` | CrowdStrike pull |
| `https://api.umbrella.com` + `https://login.umbrella.com` | Umbrella pull |
| `https://myaudit2.technijian.com` | Teramind pull |
| `https://api.meraki.com` | Meraki pull |
| `https://api.central.sophos.com` + `https://id.sophos.com` | Sophos pull |
| `https://<client-fw-wan-ip>:4444` | Sophos XGS config pull (pending per-firewall whitelist) |
| `\\10.100.14.10` (LAN or VPN) | ScreenConnect recording pipeline |
| `https://login.microsoftonline.com` + `https://graph.microsoft.com` | Weekly audit, Annual review email, M365 pull |
| `https://generativelanguage.googleapis.com` | SC video analysis (Gemini) |

### 9.3 First-run smoke tests

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM Monthly pull
python technijian\monthly-pull\scripts\pull_monthly.py --dry-run

REM Huntress
python -c "import sys; sys.path.insert(0, r'technijian\huntress-pull\scripts'); import huntress_api as h; print(h.get_account())"

REM CrowdStrike
python -c "import sys; sys.path.insert(0,'technijian\crowdstrike-pull\scripts'); import cs_api; print('children:', len(cs_api.list_mssp_children()))"

REM Meraki
python -c "import sys; sys.path.insert(0, r'scripts\meraki'); import meraki_api as m; print('orgs:', len(m.list_organizations()))"

REM Sophos
python -c "import sys; sys.path.insert(0, r'technijian\sophos-pull\scripts'); import sophos_api; print('tenants:', len(sophos_api.list_tenants()))"

REM M365 + CP auth
python -c "import sys; sys.path.insert(0, r'technijian\tech-training\scripts'); from _secrets import get_m365_credentials; t,c,s,m = get_m365_credentials(); print('M365 OK; mailbox =', m)"

REM CP ticket creation (dry-run)
python scripts\clientportal\cp_tickets.py --help
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
| `Technijian-DailyMerakiPull` | Daily 05:00 PT | `scripts\meraki\run-daily-meraki.cmd` | `meraki-pull` | Active |
| `Technijian-HourlySophosPull` | Hourly :15 | `technijian\sophos-pull\run-hourly-sophos.cmd` | `sophos-pull` | Active |
| `Technijian-M365SecurityPull` | Every 4h | `technijian\m365-pull\run-m365-security.cmd` | `m365-security-pull` | Active (11/18 tenants) |
| `Technijian-M365CompliancePull` | Daily | `technijian\m365-pull\run-m365-compliance.cmd` | `m365-compliance-pull` | Active |
| `Technijian-M365LicensePull` | Weekly | `technijian\m365-pull\run-m365-license.cmd` | `m365-storage-pull` | Active |
| `Technijian-MonthlyClientPull` | 1st of month 07:00 PT | `technijian\monthly-pull\run-monthly-pull.cmd` | `monthly-client-pull` | Active |
| `Technijian Weekly Time-Entry Audit` | Weekly Friday 07:00 PT | `technijian\weekly-audit\run_weekly.bat` | `weekly-time-audit` | Active |
| `Technijian-MonthlyScreenConnectPull` | Monthly 28th 20:00 | `technijian\screenconnect-pull\run-monthly-sc.cmd` | — | Active (interactive session required) |
| `Technijian-DailySessionAnalysis` | Daily ~04:00 PT | `analyze_sessions_gemini.py` | `screenconnect-video-analysis` | Pending (Gemini key + MP4s needed) |

**Stagger rationale:** 01:00 Huntress -> 02:00 Umbrella -> 03:00 CrowdStrike -> 04:00 Teramind -> 05:00 Meraki -> :15 Sophos hourly. Avoids CP API and disk contention.

---

## 11. Known Constraints and Limitations

### 11.1 API constraints

| System | Constraint | Impact |
|--------|-----------|--------|
| Huntress v1 `/agents` | No historical date filter | Agent inventory is point-in-time only |
| Huntress v1 | No SAT endpoints | Security Awareness Training requires manual export |
| Falcon Flight Control alerts/incidents | `member_cid` silently ignored | Must pull at parent level, bucket by `cid` field |
| Cisco Umbrella activity | 5,000 record cap per pull; 10,000 offset cap per window | Busy 24h windows truncate; use aggregation endpoints for backfill |
| Sophos Partner API SIEM | 24h lookback ceiling enforced by HTTP 400 | Cannot backfill historical alert events via API |
| Sophos Partner API | Firewall config NOT exposed | Use on-box XGS API at port 4444 (pending whitelist) |
| Sophos Partner API | Per-signature IPS/IDS NOT exposed | Requires syslog forwarding from each XGS to Technijian DC |
| Sophos Partner API | Admin account DELETE NOT exposed | Roles strippable via API; account removal requires Playwright UI |
| Meraki | 403 on unlicensed/dormant org endpoints | Degrades gracefully; logged in pull_summary.json |
| Meraki | Legacy `X-Cisco-Meraki-API-Key` header rejected | Always use `Authorization: Bearer` |

### 11.2 Tool constraints

| Tool | Constraint |
|------|-----------|
| `SessionCaptureProcessor.exe` | GUI-only; requires interactive Windows session; cannot run as SYSTEM |
| SC recordings share | 30-day purge on session events; run monthly pipeline before the 28th |
| Gemini video analysis | Requires Gemini API key (not yet provisioned) and MP4s in FileCabinet |
| `python-docx` logo dependency | Logo must exist at `C:\VSCode\tech-branding\tech-branding\assets\logos\png\technijian-logo-full-color-600x125.png` |
| Sophos XGS on-box API | Self-signed cert (expected); scanner IP `64.58.160.218` must be whitelisted per firewall |

### 11.3 Mapping coverage

| System | Mapped clients (2026-04-30) |
|--------|----------------------------|
| Huntress | 29 of 29 orgs |
| CrowdStrike | 29 of 36 child CIDs |
| Umbrella | 29 of 29 customer orgs (per-org keys complete 2026-04-29) |
| Teramind | 3 clients (LAG, MKC, QOSNET) |
| Meraki | 7 active orgs (2 dormant) |
| Sophos Central | 9 of 11 tenants (Yebo unmapped, Technijian ignored) |
| M365 MSP | 11 of 18 tenants consented; 7 need GDAP |

---

## 12. Future Work

### 12.1 Install pending scheduled tasks

`Technijian-DailyCrowdStrikePull` and `Technijian-DailyUmbrellaPull` are not yet installed on the production workstation.

### 12.2 ScreenConnect video analysis (Gemini)

Blocked by: (1) Gemini API key not yet in `keys/gemini.md`; (2) MP4s need to be in OneDrive FileCabinet. Free tier: 1,500 req/day; initial ~2,576-session backfill ~2 days.

### 12.3 Huntress SAT data

Huntress Managed Security Awareness Training has no v1 API endpoint as of 2026-04. SAT exports are manual.

### 12.4 Contacts designation gaps

Active managed-IT clients without a contact designation set in the Client Portal appear in `technijian/contacts/needs_designation_set.csv`. Have portal admin set Primary Contact for each.

### 12.5 Weekly audit enforcement

The deferred auto-deletion spec lives at `technijian/weekly-audit/API-DELETE-ENDPOINT-SPEC.md`. Do not wire without explicit re-approval.

### 12.6 Unify workstation.md files

Three workstation setup files exist. Consolidate into a single top-level `workstation.md` with per-pipeline subsections.

### 12.7 Teramind data growth

Teramind is newly deployed. Add new clients to `DOMAIN_MAP` in `build_teramind_compliance_report.py` when they enroll.

### 12.8 MyRMM / ManageEngine SQL Server

TE-DC-MYRMM-SQL (10.100.13.11) credentials in `keys/myrmm-sql.md` are marked TODO — not yet wired.

### 12.9 Sophos XGS on-box config API (PENDING)

10 firewalls identified; all need whitelist of `64.58.160.218` on port 4444 (Administration > Device Access > WAN > HTTPS + API). After whitelist:
1. Create `technijian-api` read-only user on each firewall
2. Add credentials to `keys/sophos-fw-<CODE>.md`
3. Run `scan_sophos_fw_api.py --pull --only <CODE>` to verify
4. Add `--pull` to `run-hourly-sophos.cmd` for automated daily config snapshots + change diffing

See skill `sophos-fw-config-pull` and `technijian/sophos-pull/state/firewall-api-inventory.json` for current status.

### 12.10 Sophos alert ticket ID backfill

8 CP tickets (ANI, B2I, BWH, JDH, KSS, ORX, TALY, VAF) were created 2026-04-30 before `extract_ticket_id` was fixed. `state/alert-tickets.json` has `ticket_id: null` for all 8. Running `route_alerts.py --apply` again will create duplicates. Action required: look up the 8 ticket IDs in CP (by client + date) and manually patch the state file, or add a same-day deduplication guard to the router.

### 12.11 M365 GDAP completion

7 of 18 tenants blocked on GDAP (Granular Delegated Admin Privileges). Status in `state/gdap_status.csv`. Complete GDAP to unlock full MSP monitoring coverage.

### 12.12 M365 Pax8 margin reconciliation

Phase 1 (license inventory) is live. Phase 2 (Pax8 cost vs CP recurring invoice margin analysis) gated on per-client GDAP and the Pax8 MCP connector. Playbook at `docs/m365-license-reconciliation-setup.md`.

### 12.13 Sophos rsyslog per-signature IPS/IDS

The Sophos Partner API SIEM endpoint returns only CONNECTIVITY-class events. Full per-signature IPS/IDS events require syslog forwarding from each XGS to a Technijian DC TLS-6514 receiver. The rsyslog allowlist (`state/sophos-tenant-ipmap.json`) is maintained by `seed_tenant_map.py`. IDS event parsing and per-client bucketing pipeline is not yet built.

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

REM Huntress
python technijian\huntress-pull\scripts\pull_huntress_daily.py --map-only
python technijian\huntress-pull\scripts\backfill_huntress.py --year 2026
python technijian\huntress-pull\scripts\build_monthly_report.py --month 2026-04

REM CrowdStrike
python technijian\crowdstrike-pull\scripts\pull_crowdstrike_daily.py --only AAVA
python technijian\crowdstrike-pull\scripts\backfill_crowdstrike.py --year 2026
python technijian\crowdstrike-pull\scripts\build_monthly_report.py --all-months

REM Umbrella
python technijian\umbrella-pull\scripts\pull_umbrella_daily.py --map-only
python technijian\umbrella-pull\scripts\backfill_umbrella.py --start 2026-01-30 --end 2026-04-28 --only VAF

REM Teramind
python technijian\teramind-pull\scripts\pull_teramind_daily.py --dry-run
python technijian\teramind-pull\scripts\build_teramind_compliance_report.py --month 2026-04

REM Meraki
python scripts\meraki\pull_all.py
python scripts\meraki\pull_all.py --only VAF,BWH --days 7
python scripts\meraki\pull_all.py --skip-config
python scripts\meraki\generate_monthly_docx.py --month 2026-04
python scripts\meraki\generate_monthly_docx.py --month 2026-04 --only BWH,KSS

REM Sophos
python technijian\sophos-pull\scripts\pull_sophos_daily.py
python technijian\sophos-pull\scripts\route_alerts.py --dry-run
python technijian\sophos-pull\scripts\route_alerts.py --apply
python technijian\sophos-pull\scripts\build_sophos_monthly_report.py --month 2026-04
python technijian\sophos-pull\scripts\build_sophos_monthly_report.py --month 2026-04 --only BWH,ORX
python technijian\sophos-pull\scripts\scan_sophos_fw_api.py --update-ip
python technijian\sophos-pull\scripts\scan_sophos_fw_api.py --pull --only BWH

REM M365
python technijian\m365-pull\scripts\pull_m365_security.py
python technijian\m365-pull\scripts\pull_m365_compliance.py
python technijian\m365-pull\scripts\pull_m365_storage.py
python technijian\m365-pull\scripts\build_m365_monthly_report.py --month 2026-04
python technijian\m365-pull\scripts\create_m365_tickets.py
python technijian\m365-pull\scripts\discover_gdap.py
python technijian\m365-pull\scripts\check_access.py

REM CP ticket creation
python scripts\clientportal\build_client_meta.py
python scripts\clientportal\cp_tickets.py --help

REM ScreenConnect
technijian\screenconnect-pull\run-monthly-sc.cmd
python technijian\screenconnect-pull\scripts\build_client_audit.py --all --year 2026

REM Contacts
python scripts\contacts\build_contacts_report.py

REM Annual review
python technijian\tech-training\scripts\_audit-all-clients.py 2026
python technijian\tech-training\scripts\_build-all-reports.py 2026
python technijian\tech-training\scripts\_create-outlook-drafts.py 2026
python technijian\tech-training\scripts\_send-drafts.py 2026

REM DOCX proofreader
python technijian\shared\scripts\proofread_docx.py clients\bwh\sophos\reports\BWH - Sophos Monthly Activity - 2026-04.docx
python technijian\shared\scripts\proofread_docx.py clients\bwh\meraki\reports\BWH - Meraki Monthly Activity - 2026-04.docx
```

---

*Last updated 2026-04-30. When a new pipeline ships or a cadence changes, update this file and bump the date.*
