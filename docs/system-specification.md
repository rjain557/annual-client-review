# Technijian Annual-Client-Review — System Specification

**Version:** 1.7
**Date:** 2026-05-02
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
6. **Email archive operations** — On-prem MailStore SPE at `archive.technijian.com:8474` hosts the email archives for 3 client tenants (icmlending, icm-realestate, orthoxpress). The Management API (122 functions) drives per-instance snapshots, mailbox-storage reporting, alert surfacing, and store-health remediation.

**Read/write posture:** Most pipelines are read-only toward external systems. The following pipelines write back to the Client Portal:
- **Sophos alert router** (`route_alerts.py --apply`) — creates billable client tickets.
- **M365 ticket creator** (`create_m365_tickets.py`) — creates billable client tickets for threat events.
- **MailStore alert router** (`route_alerts.py --apply`) — creates billable client tickets for archive-store / instance issues.
- **Veeam VBR ticket filer** (`scripts/veeam-vbr/file_2026_backup_tickets.py`) — opens capacity / health / RPC tickets per yearly run.
- **Veeam 365 ticket filer** (`scripts/veeam-365/file_capacity_tickets.py`) — opens capacity / job-warning tickets after each `pull_full.py` run.

All five callers should converge on the **cp-ticket-management** layer (added 2026-05-02 — see §5.13.1 and §7.1.1). Pipelines that have migrated use `cp_tickets.create_ticket_for_code_tracked()` for idempotency and let the central monitor at `scripts/clientportal/ticket_monitor.py check` (recommended daily 06:00 PT on the production workstation) email `support@technijian.com` 24h reminders for any open ticket. As of 2026-05-02 only the Veeam 365 caller is fully migrated; the rest still call the raw create but their tickets are backfilled into central state via `_backfill_orphan_tickets.py` so the monitor covers them today.

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
| 13 | **Veeam ONE 13 REST** | `https://10.7.9.135:1239/api/v2.2` (TE-DC-VONE-01) | JWT (`POST /api/token` form-encoded; **DOMAIN\User format MANDATORY**) + `x-api-version: 2.2` header | Backup config (VBR servers, repositories, scale-out repos, agents), per-repo capacity / free / `outOfSpaceInDays` / `isImmutable`, alarm catalog (524 templates), Business View categories/groups (per-client SLA + datastore tags), `POST /reports` for tabular VM/perf/triggered-alarm data | Reporter REST surface only; live VM perf + triggered-alarm lists are NOT direct endpoints — must execute predefined reports by templateId; `/vms`, `/inventory/*`, `/alarms/triggered` confirmed 404 in v13.0.1.6168 (probed 2026-05-02) |
| 13 | **MailStore SPE Management API** | `https://archive.technijian.com:8474/api/invoke/` | HTTP Basic (admin) | Instances, users + GetUserInfo, archive stores, instance/folder statistics, jobs, profiles, credentials, system + per-instance alerts, instance/index/compliance/directory-services config | Read + write (122 functions); long-running ops auto-poll `/api/get-status`; web console on port 8470, Client Access Server on 8473, Instance Host vmtechmss on 8472; 3 hosted instances |
| 14 | **Veeam Backup & Replication v13 REST** | `https://10.7.9.220:9419/api/v1` (TE-DC-BK-VBR-01, build 13.0.1.2067) | OAuth2 password grant (`POST /api/oauth2/token`) → JWT Bearer + `x-api-version: 1.2-rev0` header | Backup jobs (config + selectors + schedules), session history with throughput (`speed`, `transferredSize`, `processedObjects`), backup repositories with capacity/free/used (GB-scaled fields: `capacityGB`/`freeGB`/`usedSpaceGB`), proxies + managed servers, restore points, malware-detection events (12.1+), security analyzer findings (`/securityAnalyzer/bestPractices`). **Verified 2026-05-02:** 24 jobs across 9 hosted clients + Technijian internal, 10 repos = 93.3 TB capacity / 54 TB used (58%); bkp_VAF at 97.5% capacity. | Self-signed TLS; **`/jobs/states` returns 500** on this build (helper falls back to `recentSessions[0]`); **`/scaleOutRepositories/states` and `/proxies/states` return 400** ('states' parsed as id); **no `/alarms` endpoints** (alarms are Veeam ONE — see row 13); `1.2-rev1` header times out (use `1.2-rev0`); pagination via `?skip=&limit=`; no IOPS/latency counters — throughput proxy is per-session `transferredSize/duration` |
| 15 | **Veeam Backup for Microsoft 365 (VB365) REST** | `https://10.7.9.227:4443/v8` | OAuth2 password grant (`POST /v8/token` form-encoded) → Bearer token (~24h TTL, refresh-token supported) | Protected M365 tenants (`/Organizations`), per-tenant M365 directory (`/Organizations/{id}/users` plus `/groups`, `/sites`, `/teams`), per-tenant per-repo used backup space (`/Organizations/{id}/usedRepositories` → `usedSpaceBytes` + `localCacheUsedSpaceBytes` + `objectStorageUsedSpaceBytes`), backup repositories + capacity/free/retention (`/BackupRepositories`), backup jobs + lastRun/nextRun/lastStatus + selectedItems (`/Jobs`), proxies, RBAC roles. **Verified 2026-05-02:** 8 tenants, 1,210 backed-up users, 20.70 TB across 10 repos. | Self-signed TLS; **server speaks both /v8 and /v7** (returns /v7 next-link URLs even on /v8 sessions — clients must leave any /vN/ prefix alone); pagination via `?limit=N&offset=M` plus HAL `_links.next` (no `totalCount` field — count by walking pages); `/Backups`, `/BackupRepositories/{id}/OrganizationUsers`, `/Mailboxes`, `/ServerInfo` all 404 on this build (use VB365 PowerShell `Get-VBOEntityData` for per-user/per-team backup sizes) |
| 16 | **VMware vCenter Server REST + pyVmomi** | `https://172.16.9.252/api` (REST) + SOAP via pyVmomi | Basic-auth POST `/api/session` -> `vmware-api-session-id` JWT; pyVmomi `SmartConnect` for SOAP fallback | Datacenter/cluster/host/folder/network inventory; full per-VM config (CPU/RAM/disks/NICs/guest OS/power/tools); datastore catalog (capacity/free/type/path); per-LUN backing (canonicalName/NAA/vendor/model/SSD/multipath); active alarms; daily-rollup VM perf for the past year (CPU %, MHz, mem consumed/active, disk usage, net usage); host-aggregate storage perf | Self-signed cert (verify=False or pin CA bundle); REST `/api/vcenter/vm` caps at 4000 VMs; per-LUN detail + historical perf + triggered alarms (pre-vSphere-8) require pyVmomi SOAP; `vpxd.stats.maxQueryMetrics=64` forces one-VM-per-QueryPerf; daily-rollup datastore metrics retain only host-aggregate (per-datastore IO requires raising vCenter stats collection level from 1 to 3) |

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
| **MailStore SPE Snapshot Pull** | **On demand (recommend daily)** | `technijian/mailstore-pull/scripts/pull_mailstore.py` | Manual / scheduled task (not yet installed) | `clients/<code>/mailstore/<YYYY-MM-DD>/snapshot-<instanceID>.json` | **Active (3 instances)** |
| **MailStore Year Activity Pull** | **On demand (annual or quarterly)** | `technijian/mailstore-pull/scripts/pull_year_activity.py` | Manual | `clients/<code>/mailstore/<year>/{worker,job}-results-<instanceID>.json` | **Active; auto-bisects on SPE "Nullable object" bug** |
| **MailStore Alerts Dashboard** | **On demand** | `technijian/mailstore-pull/scripts/show_alerts.py` | Manual (intended for ops dashboard) | stdout / `--json` | **Active** |
| **MailStore Monthly Report** | **1st of month** | `technijian/mailstore-pull/scripts/build_monthly_report.py` | Manual | `clients/<code>/mailstore/monthly/<YYYY-MM>/<CODE>-Email-Archive-Monthly-<YYYY-MM>.docx` | **Active; 2/2 pass 8/8 May 2026** |
| **Veeam ONE Pull (REST)** | **On demand (cadence TBD)** | `scripts/veeam-one/pull_all.py` | Manual | `clients/_veeam_one/<YYYY-MM-DD>/` | **Active (built 2026-05-02)** |
| **Veeam VBR Pull (REST)** | **On demand** | `.claude/skills/veeam-vbr/scripts/{get_vm_backups,get_storage,get_alerts}.py` | Manual (skill `veeam-vbr`) | TBD — likely `clients/_veeam_vbr/<YYYY-MM-DD>/` for a single MSP-wide server | **Active (built 2026-05-02)** |
| **Veeam 365 Tenant Summary (REST)** | **On demand (cadence TBD)** | `scripts/veeam-365/pull_tenant_summary.py` | Manual (skill `veeam-365-pull`) | `clients/_veeam_365/tenant_summary.{json,csv}` | **Active (built 2026-05-02; 8 tenants / 1,210 users / 20.70 TB)** |
| **Veeam 365 Full Pull + Snapshot (REST)** | **Recommend monthly, 1st of month** | `scripts/veeam-365/pull_full.py` | Manual (skill `veeam-365-pull`) — scheduled task pending | `clients/<slug>/veeam-365/<YYYY-MM-DD>/data.json` + `clients/_veeam_365/snapshots/<YYYY-MM-DD>.json` | **Active (built 2026-05-02; per-user OneDrive coverage + per-module proportional attribution from RP service flags + dated snapshot for trend math)** |
| **Veeam 365 Monthly Report** | **1st of month** | `scripts/veeam-365/build_monthly_report.py` | Manual (skill `veeam-365-pull`) | `clients/<slug>/veeam-365/reports/<Tenant> - Veeam 365 Monthly - YYYY-MM.docx` | **Active; 8/8 tenants pass 8/8 proofread May 2026** — branded DOCX with KPI cards, posture table, per-module breakdown (Exchange/OneDrive/SharePoint/Teams), per-user mailbox+OneDrive coverage table, storage trend & 3/6/9/12-month projection chart (linear regression on log-bytes once ≥2 monthly snapshots accumulate; defaults to 4% MoM until then), recommendations, methodology appendix |
| **CP Ticket Monitor (24h reminders)** | **Daily 06:00 PT** | `scripts/clientportal/ticket_monitor.py check` | Scheduled task on production workstation (registration pending) | M365 Graph `sendMail` to support@technijian.com + state mutations to `state/cp_tickets.json` | **Active 2026-05-02** — central monitor for all CP tickets opened by automation. Idempotent ticket creation via `cp_tickets.create_ticket_for_code_tracked()` (deduplicates on `issue_key`); sends one reminder per open ticket every 24h until `ticket_monitor.py resolve <id>`. **15 open tickets centrally tracked** as of 2026-05-02 (4 veeam-365-pull native + 3 mailstore + 8 veeam-vbr backfilled). All 17 SKILL.md files carry awareness/migration block |
| **vCenter Daily Pull (inventory + 5-min perf + aggregate)** | **Daily 06:00 PT** | `scripts/vcenter/run-daily-vcenter.cmd` -> `daily_run.py` | Scheduled task (pending install) | `.work/vcenter-<DATE>/` master (gitignored) + `clients/<code>/vcenter/<YEAR>/` snapshot + `vm_perf_daily.json` / `storage_perf_daily.json` accumulators | **Active (built 2026-05-02; 205 VMs / 25 datastores / 14 hosts / 336 LUN rows)** |
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

#### 5.13.1 Tracked-wrapper layer — `cp-ticket-management` (added 2026-05-02)

A second wrapper sits above `create_ticket_for_code()` to give every pipeline:

1. **Idempotency** — `cp_tickets.create_ticket_for_code_tracked(...)` checks a central state file before calling the SP. If a ticket for the same `issue_key` already exists and is unresolved, it returns the existing ticket id without creating a new one.
2. **Central state** — `state/cp_tickets.json` records every pipeline-opened ticket: ticket id, client code, source skill, title, priority, assignee, `created_at`, `last_reminder_at`, `reminder_count`, `resolved_at`, `metadata{}`, and a `history[]` audit trail.
3. **24h reminder emails** — `scripts/clientportal/ticket_monitor.py check` scans state, finds open tickets older than the reminder threshold (default 24h since `created_at` or `last_reminder_at`), and emails `support@technijian.com` a "please action ticket #X" reminder via the M365 Graph send pattern (same auth flow as the Sophos `email_support.py` reminder loop). Increments `reminder_count` and stamps `last_reminder_at`.
4. **Manual resolution** — `python ticket_monitor.py resolve <ticket_id|issue_key> --note "..."` stops further reminders.

**Issue-key convention:** `<source-skill>:<issue-type>:<resource-id>`. Examples in current state:

| Issue key | Ticket | Source |
|---|---|---|
| `veeam-365:repo-capacity:AFFG-O365` | #1452721 | veeam-365-pull |
| `veeam-365:repo-capacity:TECH-O365` | #1452722 | veeam-365-pull |
| `veeam-365:repo-capacity-and-warning:ALG-O365` | #1452723 | veeam-365-pull |
| `veeam-365:migration-cleanup:ORX` | #1452724 | veeam-365-pull |
| `mailstore:smtp-failures:Technijian` | #1452674 | mailstore-spe-pull (backfilled) |
| `mailstore:index-rebuild:ORX` | #1452675 | mailstore-spe-pull (backfilled) |
| `mailstore:archive-jobs-failing:ICML` | #1452676 | mailstore-spe-pull (backfilled) |
| `veeam-vbr:repo-capacity:bkp_VAF` | #1452728 | veeam-vbr (backfilled) |
| `veeam-vbr:imt-threshold-check:Bkp_VAF_IMT` | #1452729 | veeam-vbr (backfilled) |
| `veeam-vbr:rpc-timeouts:VAF` | #1452730 | veeam-vbr (backfilled) |
| `veeam-vbr:repo-capacity:bkp_ORX` | #1452731 | veeam-vbr (backfilled) |
| `veeam-vbr:imt-threshold-check:Bkp_ORX_IMT` | #1452732 | veeam-vbr (backfilled) |
| `veeam-vbr:rpc-timeouts:ORX` | #1452733 | veeam-vbr (backfilled) |
| `veeam-vbr:vsphere-tag-missing:MAX` | #1452734 | veeam-vbr (backfilled) |
| `veeam-vbr:imt-and-shared-nfs:MAX` | #1452735 | veeam-vbr (backfilled) |

**Status (2026-05-02):** 15 open tickets centrally tracked. veeam-365-pull `file_capacity_tickets.py` is the only caller fully migrated to the tracked wrapper. mailstore-spe-pull / sophos-pull / veeam-vbr callers still use the raw `create_ticket(...)` and have their own state files; their tickets are backfilled into central state via `scripts/clientportal/_backfill_orphan_tickets.py` so the monitor covers them now. Source-code migration of those callers is pending. **All 17 SKILL.md files** in `.claude/skills/` carry an awareness or migration block (injected by `_inject_ticket_management_note.py`, idempotent on `<!-- ticket-management-note -->` marker) so future Claude instances reading any skill route ticket creation through the tracked wrapper.

**Files:**
- `scripts/clientportal/ticket_state.py` — state CRUD (`load/save/get/has_open/add/backfill/mark_reminder_sent/mark_resolved/list_open/list_all`)
- `scripts/clientportal/ticket_email.py` — generic Graph send (lifted from `email_support.py`)
- `scripts/clientportal/ticket_monitor.py` — CLI: `list [--open] [--json]`, `check [--hours N] [--to ADDR] [--dry-run]`, `resolve <id|key> [--note ...]`
- `scripts/clientportal/cp_tickets.py::create_ticket_for_code_tracked()` — the wrapper itself
- `scripts/clientportal/_inject_ticket_management_note.py` — one-shot doc-pass driver (idempotent)
- `scripts/clientportal/_backfill_orphan_tickets.py` — one-shot backfill of pre-existing tickets
- `scripts/veeam-365/_backfill_state.py` — first backfill template (4 native veeam-365 tickets)
- `state/cp_tickets.json` — central state file (created on first write)
- `.claude/skills/cp-ticket-management/SKILL.md` — full skill writeup with migration guide

**Recommended schedule:** daily 06:00 PT on the production workstation (NOT the dev box per `feedback_no_dev_box_schedules`):
```
python scripts/clientportal/ticket_monitor.py check
```

**Future enhancement (not built):** CP polling for status / time-entry activity so the monitor can detect "actually being worked on" and skip reminders. Gated on identifying the right read SP — likely `stp_xml_Tkt_API_Read` candidates from the existing `reference_cp_user_role_sps` notes. Today the monitor sends reminders based purely on age; manual `resolve` is the only way to stop the loop short of a status check.

---

### 5.14 Veeam ONE Pull (REST)

**Purpose:** Snapshot the backup posture for the Technijian-hosted VMware estate from the Veeam ONE Reporting Service — VBR server inventory, repository capacity / free / runway, scale-out repos, alarm catalog, and Business View groupings (which carry the per-client SLA + datastore tags).

**Cadence:** On demand (built 2026-05-02). Cadence will be wired once the per-client fan-out for the annual review is decided. Lightweight enough to run hourly if alerting on `outOfSpaceInDays` is needed.

**Host:** TE-DC-VONE-01 (10.7.9.135), Veeam ONE Reporting Service v13.0.1.6168, license: rental ONE 830-instance until 2026-06-15 (held by Opti9 Technologies LLC).

**Auth:** JWT (`POST /api/token`, form-encoded), `username` MUST be `DOMAIN\User` format (e.g. `TE-DC-VONE-01\Administrator`). Bare `Administrator` returns 400. All subsequent calls send `Authorization: Bearer <jwt>` + `x-api-version: 2.2`.

**Confirmed REST surface (v13.0.1.6168, port 1239):**

| Endpoint | Returns |
|---|---|
| `GET /api/v2.2/about` | service name, version, machine, log path |
| `GET /api/v2.2/license` | rental info, instances, expiration, partner ID |
| `GET /api/v2.2/agents` | Veeam ONE Agent state per VBR server (log analyzer, remediation flags) |
| `GET /api/v2.2/alarms/templates` | 524 alarm definitions (knowledge base, severity, isEnabled, assignments) |
| `GET /api/v2.2/businessView/categories` | 9 categories (SLA, Storage Type, Last Backup Date, VM Location, ...) |
| `GET /api/v2.2/businessView/groups` | 28 groups (Mission Critical, `DS-NBD1-<CODE>` per client, snapshot-age buckets) |
| `GET /api/v2.2/vbr/backupServers` | VBR servers (id, version, platform, connection, configuration backup, BPC) |
| `GET /api/v2.2/vbr/repositories` | repos with **live capacity, free, runningTasks, outOfSpaceInDays, isImmutable, path** |
| `GET /api/v2.2/vbr/scaleOutRepositories` | SOBR (empty in current install) |
| `POST /api/v2.2/reports` | execute predefined report by `templateId` (returns tabular data — required path for VM perf, triggered alarms, backup-job history) |

**Confirmed NOT exposed in REST (v13.0.1.6168, all 404):** `/vms`, `/inventory/{vms,hosts,datastores}`, `/alarms` list, `/alarms/triggered`, `/alarms/active`, `/events`, `/users`, `/vbr/{jobs,sessions,proxies,protectedVMs}`, `/topology/vms`, `/monitoring/*`, `/license/usage`, `/remedies`, `/loganalyzer`, `/telemetry/usage`. Re-probe with `python scripts/veeam-one/explore.py` after each Veeam service-pack — the canonical probe list lives in `explore.py:DEFAULT_PROBES`.

**What we can do today (REST list endpoints):**
- **Backup configuration audit** — VBR server version, configuration-backup status, best-practice-check status, agent connection.
- **Storage capacity + runway report** — per-repository capacity, free %, `outOfSpaceInDays`, immutability flag, ReFS flag. Current snapshot (2026-05-02): 91 TB total, 60 % used, **bkp_ORX runway = 3 days**, **bkp_VAF runway = 6 days**.
- **Alarm posture** — full catalog of 524 alarm definitions, what's enabled vs disabled, distribution by object type.
- **Per-client mapping** — Business View `DS-NBD1-<CODE>` groups + `bkp_<CODE>` repos identify the hosted-client tenants on the cluster (TOR, TECH/TECH1, FOR, VG, ORX, RFPS, VAF, CCC, CSS, MAX).

**What requires `/reports` POST (templateId from Web UI):**
- VM-level inventory and configuration (CPU/RAM/disk/snapshot count per VM).
- VM performance counters (CPU, memory, disk IOPS, network) — tabular with date range.
- Triggered/active alarms and historical alarm summary.
- Per-VM backup status and last successful backup date.
- Backup-job history and success/failure summary.

**What requires SQL or vCenter REST (out of scope for this skill):**
- Sub-minute granularity perf history -> Veeam ONE Reporter SQL data warehouse.
- Live per-VM topology and counters -> use the existing `vcenter-rest` skill against vCenter `172.16.9.252` (Veeam ONE just monitors that same vCenter).

**Key scripts:**

| Script | Purpose |
|--------|---------|
| `scripts/veeam-one/veeam_one_api.py` | Reusable client (token + refresh + paged GET); reads `keys/veeam-one.md` |
| `scripts/veeam-one/pull_vbr.py` | VBR servers + repositories + SOBR + agents + summary KPIs |
| `scripts/veeam-one/pull_alarms.py` | Alarm catalog + counts by object type + enabled/disabled split |
| `scripts/veeam-one/pull_business_view.py` | BV categories + groups (per-client tags) |
| `scripts/veeam-one/pull_all.py` | Orchestrator — runs all of the above into one dated folder |
| `scripts/veeam-one/explore.py` | Endpoint discovery probe — re-run after Veeam service-packs |

**Output schema:**
```
clients/_veeam_one/<YYYY-MM-DD>/
  backup_servers.json              # VBR server inventory (id, version, BPC, connection state)
  repositories.json                # all repos: capacity, free, runningTasks, outOfSpaceInDays, isImmutable, path
  scaleout_repositories.json       # SOBR (empty in current install)
  agents.json                      # Veeam ONE Agent state per VBR server
  alarm_templates.json             # 524 alarm definitions (knowledge base, severity, scope)
  alarm_summary.json               # rollup counts (predefined/custom, enabled/disabled, by object type)
  business_view_categories.json    # 9 categories
  business_view_groups.json        # 28 groups (incl. DS-NBD1-<CODE> per client)
  backup_summary.json              # rolled-up KPIs: total cap, free %, repos <30d runway, immutable count
```

**Per-client mapping (current install, derived from repo names + BV groups):**

| Repo / BV tag | NFS path | CP code | Notes |
|---------------|----------|---------|-------|
| `bkp_TOR` / `DS-NBD1-TOR` | `nfs3://10.7.9.230:/bkp_TOR` | `tor` | |
| `bkp_TECH` / `DS-NBD1-TECH(1)` | `nfs3://10.7.9.230:/bkp_TECH` | `technijian` | largest (60 TB, 27 TB free) |
| `bkp_FOR` / `DS-NBD1-FOR` | `nfs3://10.7.9.230:/bkp_FOR` | `for` | |
| `bkp_VG` / `DS-NBD1-VG` | `nfs3://10.7.9.225:/bkp_VG` | `vg` | |
| `bkp_ORX` / `DS-NBD1-ORX` | `nfs3://10.7.9.225:/bkp_ORX` | `orx` | **3-day runway** |
| `bkp_RFPS` / `DS-NBD1-RFPS` | `nfs3://10.7.9.230:/bkp_RFPS` | (no folder) | client folder not yet provisioned |
| `bkp_VAF` / `DS-NBD1-VAF` | `nfs3://10.7.9.225:/bkp_VAF` | `vaf` | **6-day runway** |
| `bkp_CCC` / `DS-NBD1-CCC` | `nfs3://10.7.9.225:/bkp_CCC` | `ccc` | |
| `bkp_CSS` / `DS-NBD1-CSS` | `nfs3://10.7.9.230:/bkp_CSS` | `css` | |
| (no repo) / `DS-NBD1-MAX` | shared storage | `max` | datastore-only — no dedicated Veeam repo yet |

**Skill registration:** `.claude/skills/veeam-one-pull/SKILL.md` — full endpoint surface, auth gotchas, discovery workflow.

---

### 5.15 vCenter REST Pull (VMware inventory + performance + alerts)

**Purpose:** Snapshot the entire Technijian-hosted VMware estate from vCenter directly — VM configuration, daily VM perf for the year, datastore + LUN backing detail, and active alarms. Complements the Veeam ONE pull (which only sees what Veeam ONE Reporter exposes) by going to the source of truth for every VM running on the cluster, then splits the dump into per-client folders for the annual review.

**Cadence:** On demand (built 2026-05-02). For the annual review, run once at the start of the cycle. Lightweight enough to schedule daily (~5 min for inventory) or weekly (~20 min with full daily-rollup VM perf for 200+ VMs).

**Host:** `172.16.9.252` — vCenter Server 8.0.0.10200 (build 21216066, patch released 2023-02-14, last updated 2025-10-12). Single datacenter "Technijian DC", single DRS-enabled cluster "Cluster-01", 14 ESXi hosts (10.100.1.41–10.100.1.56 range), 25 datastores, 205 VMs.

**Auth:** Basic-auth `POST /api/session` returns a session token; subsequent calls send `vmware-api-session-id: <token>`. Sessions idle-timeout in 30 min; client refreshes on 401. SOAP fallback (pyVmomi) reuses the same `administrator@vsphere.local` credential.

**Confirmed REST surface (vSphere 8):**

| Endpoint | Returns |
|---|---|
| `GET /api/appliance/system/version` | vCenter version + build (8.0.0.10200) |
| `GET /api/vcenter/datacenter` | Datacenters (1: Technijian DC) |
| `GET /api/vcenter/cluster` | Clusters (1: Cluster-01, DRS on, HA off) |
| `GET /api/vcenter/host` | Hosts (14, all CONNECTED + POWERED_ON) |
| `GET /api/vcenter/folder` | Folders by type (44 VM folders incl. per-client folders) |
| `GET /api/vcenter/network` | Port groups |
| `GET /api/vcenter/vm` (+ filters) | VM list |
| `GET /api/vcenter/vm/{id}` | Full VM detail (cpu, memory, hardware, identity, guest_OS, nics, disks, boot, sata/scsi/nvme adapters) |
| `GET /api/vcenter/vm/{id}/hardware/disk` + `/{disk}` | Per-disk: backing.vmdk_file, capacity, scsi/sata/nvme bus, type |
| `GET /api/vcenter/vm/{id}/hardware/ethernet` + `/{nic}` | Per-NIC: backing, MAC, type |
| `GET /api/vcenter/vm/{id}/guest/identity` | Guest OS family/version/host name (when VMware Tools running) |
| `GET /api/vcenter/vm/{id}/guest/networking/interfaces` | In-guest IPs |
| `GET /api/vcenter/vm/{id}/power` | Live power state |
| `GET /api/vcenter/datastore` + `/{id}` | All 25 datastores: name, type, capacity, free_space, accessible, multiple_host_access, thin_provisioning |
| `GET /api/vcenter/alarm` | Active alarms (vSphere 8+); 0 active 2026-05-02 |
| `GET /api/vcenter/alarm/definition` | Alarm catalog |
| `GET /api/vstats/counters` + `rsrc-types` + `data/dp-query` | vSphere 8 stats API (limited; pyVmomi `QueryPerf` is the practical path) |

**Confirmed pyVmomi (SOAP) usage (where REST is insufficient):**

- **Per-LUN backing** — `host.configManager.storageSystem.storageDeviceInfo.scsiLun` for each of the 14 ESXi hosts; emits `canonicalName` (NAA / `naa.6c81f660...`), `vendor`, `model`, `lunType`, `ssd`, `displayName`, `capacity_mb`, plus per-LUN multipath rows (`paths[].name/pathState`, `policy`). 336 LUN/multipath rows pulled 2026-05-02.
- **Historical VM performance** — `pm.QueryPerf(querySpec=[QuerySpec(entity=vm, ..., intervalId=86400, instance="")])` per VM. 8 default counters: `cpu.usage.average`, `cpu.usagemhz.average`, `mem.consumed.average`, `mem.active.average`, `disk.usage.average`, `disk.read.average`, `disk.write.average`, `net.usage.average`. 2026-05-02 pull captured **122 daily samples for 210 VMs** (Jan 1 → May 2 window).
- **Triggered alarms (pre-vSphere-8 fallback)** — walks `triggeredAlarmState` on root + all entities. On this 8.0 vCenter, REST `/api/vcenter/alarm` returns the same data.
- **Datastore performance** — host-level `QueryPerf` against `datastore.*` counters. **Limited on this vCenter** because stats collection level=1 only retains host-aggregate (empty `instance=""`) for the daily/weekly/monthly rollups; per-datastore breakdown requires raising the level to 3 in vCenter advanced settings.

**Performance interval cheat sheet (vCenter 8.0.0.10200, default config):**

| Interval | Sampling | Retention | Use for |
|---|---|---|---|
| key=1 (5-min) | 300 s | 1 day | Live troubleshooting; per-instance available |
| key=2 (30-min) | 1800 s | 7 days | Last week trend; per-instance available |
| key=3 (2-hour) | 7200 s | 30 days | Last month trend; per-instance available |
| key=4 (daily) | 86400 s | 365 days | **Annual review trend; aggregate-only at level 1** |

**Critical limit — `vpxd.stats.maxQueryMetrics`:** vCenter caps a single QueryPerf at 64 returned metrics. The skill's perf scripts query **one entity at a time** (1 VM × 8 counters = 8 metrics) to stay under it. Batching multiple VMs into one query throws `vim.fault.RestrictedByAdministrator`.

**What we can do today:**
- **Full annual VM inventory** — every VM's CPU/RAM/disk/NIC/guest OS/power state in one JSON; per-client subset under `clients/<code>/vcenter/<year>/vms.json`.
- **VM utilization trend over the past year** — daily samples for CPU/mem/disk/net, used to build "this VM is over-provisioned" or "this VM hit 90% sustained" findings for the annual review.
- **Storage sizing/capacity** — every datastore's capacity, free space, type (VMFS/NFS), thin-provisioning support; per-client VMs grouped under their `DS-NBD1-<CODE>` datastore.
- **LUN inventory** — vendor/model/SSD-vs-HDD/multipath status across all 14 hosts (336 rows), useful for "is this client on flash or spinning rust?" findings.
- **Alarm posture** — active alarms list, alarm definition catalog (which alarms are enabled vs disabled). Currently 0 active alarms.
- **Cross-source correlation with Veeam ONE** — vCenter datastore names match Veeam ONE Business View tags (`DS-NBD1-CCC` etc.) and Veeam ONE repo names (`bkp_CCC`), so per-client storage/backup posture lines up across both pulls.

**Daily-aggregate workaround for per-instance perf:** The 5-min interval is the only one whose source is real-time (which always captures everything at level 4 internally). All coarser intervals (30-min/2-hour/daily) are built by rolling up from the next-finer interval, and per-instance data is stripped during rollup unless the destination level retains it — so setting daily=3 with 5-min=1 silently stores nothing extra. Setting **only the 5-min interval to level 3** captures per-instance data into the 1-day-retention bucket, which the daily pull (`scripts/vcenter/daily_run.py`) grabs before it ages out and rolls into per-day peak/avg/p95 in `clients/<code>/vcenter/<year>/{vm_perf_daily,storage_perf_daily}.json`. After 365 daily runs we have the full-year per-instance trend without ever asking vCenter to retain it long-term. DB cost: ~500 MB – 2 GB sustained on `/storage/seat`. **Applied 2026-05-02** via `~/.claude/skills/vcenter-rest/scripts/set_perf_level.py --key 1 --level 3` (wraps pyVmomi `pm.UpdatePerfInterval`). Reversible: `--key 1 --level 1`. Other intervals stay at level 1.

**What requires deeper work (out of scope for this skill):**
- **Sub-day perf granularity at long retention** — the 30-min interval only retains 7 days, the 2-hour interval only 30 days. The daily-aggregate workaround above gives per-day peak/avg/p95 for full-year, which is the practical answer; for finer grain over longer windows, query Veeam ONE Reporter SQL.
- **VM-to-LUN mapping** — current splitter matches datastores to clients by name convention (`DS-NBD1-<CODE>`), not by walking `extents -> diskName -> LUN`. Would need extents traversal in pyVmomi for full VM-to-physical-LUN trace.

**Key scripts:**

| Script | Purpose |
|--------|---------|
| `~/.claude/skills/vcenter-rest/scripts/vcenter_client.py` | Reusable REST client (`/api` -> `/rest` fallback, session refresh on 401, TLS-verify-off, pyVmomi connect helper); reads `keys/vcenter.md` |
| `scripts/get_vms.py` | List VMs + enrich each (detail/disks/nics/guest/power) |
| `scripts/get_datastores.py [--with-luns]` | Datastores via REST + per-LUN/multipath via pyVmomi |
| `scripts/get_vm_perf.py [--hours --interval]` | Per-VM `QueryPerf` (one VM at a time to satisfy `maxQueryMetrics`) |
| `scripts/get_storage_perf.py [--hours --interval]` | Per-host datastore counters with `instance="*"` -> `""` fallback |
| `scripts/get_alerts.py [--via auto\|rest\|pyvmomi]` | Active alarms (REST first, pyVmomi fallback) |
| `scripts/dump_all.py [--with-luns --with-perf]` | Orchestrator → writes one folder with all of the above + `summary.xlsx` |
| `scripts/per_client_split.py --src ... --out clients/ --year 2026 --overrides client_overrides.json` | Splits the master dump into `clients/<code>/vcenter/<year>/` using name-prefix client mapping (`<CODE>-DC-*`) + override JSON for non-prefix VMs |
| `~/.claude/skills/vcenter-rest/scripts/aggregate_perf.py` | Generic 5-min → daily aggregator (peak/avg/p95 + UTC date bucketing); idempotent same-day overwrites; appends to per-client `{vm_perf,storage_perf}_daily.json` accumulators |
| `scripts/vcenter/daily_run.py` (repo) | Production daily runner: pulls inventory + 5-min perf, runs `per_client_split`, runs `aggregate_perf` per client, deletes the master dump |
| `scripts/vcenter/run-daily-vcenter.cmd` (repo) | Windows scheduled-task wrapper for the daily runner; logs to `scripts/vcenter/state/run-<DATE>.log` |
| `scripts/vcenter/client_overrides.json` (repo) | Pins non-prefix VMs to clients (JRMEDSVR01/OXPLIVE/OXPTEST → ORX; rest → TECHNIJIAN) |
| `~/.claude/skills/vcenter-rest/scripts/set_perf_level.py` | Admin helper — `--show` dumps all 4 intervals; `--key N --level M` raises/lowers via pyVmomi `pm.UpdatePerfInterval`. Used 2026-05-02 to flip `key=1` (5-min) from level 1 → 3. |
| `scripts/vcenter/file_register_task_ticket.py` (repo) | One-shot CP ticket filer for India support; filed #1452736 routing scheduled-task registration to CHD : TS1 |

**Output schema:**

```
.work/vcenter-<YYYY-MM-DD>/                            # master pull (gitignored / temp)
  vms.json                  # enriched (detail/disks/nics/guest/power)
  datastores.json           # 25 datastores with detail
  luns.json                 # 336 LUN + multipath rows (--with-luns)
  vm_perf.json              # daily-rollup perf per VM
  storage_perf.json         # host-aggregate datastore perf (per-DS pending stats level raise)
  alerts.json               # active alarms (REST)
  alerts_pyvmomi.json       # cross-check via pyVmomi
  hosts.json + clusters.json + datacenters.json + networks.json
  summary.xlsx              # one tab per resource (openpyxl, no Excel install needed)

clients/<code>/vcenter/<YYYY>/                         # per-client subset (committed)
  vms.json + vm_perf.json + datastores.json + luns.json
  storage_perf.json + alerts.json
  summary.json + summary.xlsx
```

**Per-client mapping (current install, derived from VM name prefix + folder + override JSON):**

| Client folder | VM count | Datastore(s) | Notes |
|---|---|---|---|
| `clients/ccc/vcenter/2026/` | 3 | `DS-NBD1-CCC` | |
| `clients/css/vcenter/2026/` | 3 | `DS-NBD1-CSS` | |
| `clients/for/vcenter/2026/` | 2 | `DS-NBD1-FOR` | |
| `clients/max/vcenter/2026/` | 5 | `DS-NBD1-MAX` | datastore-only on Veeam side |
| `clients/orx/vcenter/2026/` | 27 | `DS-NBD1-ORX` | largest hosted client; includes `JRMEDSVR01`/`OXPLIVE`/`OXPTEST` overrides |
| `clients/rfps/vcenter/2026/` | 2 | `DS-NBD1-RFPS` | |
| `clients/tor/vcenter/2026/` | 2 | `DS-NBD1-TOR` | |
| `clients/vaf/vcenter/2026/` | 10 | `DS-NBD1-VAF` + `DS-NBD1-TECH` | uses some shared TECH storage |
| `clients/vg/vcenter/2026/` | 1 | `DS-NBD1-VG` | |
| `clients/technijian/vcenter/2026/` | 139 | `DS-NBD1-TECH(1)` + 13× `LS-9.4*` (host-local) + `VeeamBackup_TE-DC-BK-VBR-01` | internal infra (TE-DC-*, TECH-*); excluded from client billing |

11 vSphere-system VMs (`vCLS-*`, `cp-replica-*`, `cp-template-*`) are skipped by the splitter.

**Skill registration:** `~/.claude/skills/vcenter-rest/SKILL.md` — full endpoint catalog (`references/api_endpoints.md`), auth + quirks (`references/auth_and_quirks.md`), and the 7 fetcher scripts above.

**Scheduled task:** None yet. Per-client fan-out (writing under `clients/<code>/veeam-one/<YYYY-MM>/`) is pending the scope decision.

---

### 5.16 MailStore SPE Pull + Monthly Report

**Purpose:** Operational read of the on-prem MailStore Service Provider Edition email-archive server, plus a client-facing monthly DOCX showing mailboxes-archived, datastore size, archive job health, and storage projections at 3/6/9/12 months. Captures per-instance state (users, archive stores, jobs, profiles, configuration), surfaces system + per-store alerts, and provides an escape hatch for any of the 122 SPE Management API functions including write operations (rebuild indexes, sync directory services, run profiles).

**Cadence:** Snapshot on demand (recommend daily once a Windows Scheduled Task is installed). Year-activity pull when refreshing annual review data. Monthly report on the 1st of every month.

**Topology (snapshot 2026-05-02, SPE 25.3.1.23021):**

| instanceID | client folder | size | messages | mailboxes (excl. service) | notes |
|---|---|---|---|---|---|
| icmlending | `clients/icml/mailstore/` | 52.1 GB | 632,651 | 2 | 1 store; **2026 archive runs all FAILED — broken** |
| icm-realestate | `clients/icml/mailstore/` | 2.4 GB | 49,080 | 2 | 1 store; **2026 archive runs all FAILED — broken** |
| orthoxpress | `clients/orx/mailstore/` | 896 GB | 12,423,896 | 148 | 13 stores; **search indexes need rebuild**; ~155k items/30d archived |

Mapping is `INSTANCE_TO_CLIENT_CODE` at the top of `spe_client.py`. Without a mapping, the puller falls back to `clients/<instance-id>/mailstore/`.

**Server roles:**
- Management Server: port 8474 — Management API endpoint (`/api/invoke/<Function>`, `/api/get-metadata`, `/api/get-status`)
- Client Access Server: port 8473 — end-user web client + IMAP/MAPI
- Instance Host: vmtechmss, port 8472 — runs the per-instance worker processes
- Web admin console: port 8470 → `/web/login.html`

**Key facts (gotchas):**
- Every call is **POST**, even reads. Empty body still requires `Content-Length: 0` (Microsoft-HTTPAPI returns HTTP 411 otherwise).
- Body is `application/x-www-form-urlencoded` — never JSON. Booleans serialize as `"true"`/`"false"`.
- Param naming inconsistencies: `instanceFilter` (not `filter`), `instanceID` (not `instanceId`), `timeZoneID` for most calls but `timeZoneId` (lowercase d) for `GetJobResults`.
- Datetime format for `GetWorkerResults` / `GetJobResults`: `2026-01-01T00:00:00` *without* trailing `Z` and without fractional seconds.
- `profileID` and `userName` on `GetWorkerResults` are nullable — passing `0` or `""` errors. Omit them entirely.
- `GetProfiles` only accepts `raw=true` in this SPE version.
- **SPE bug:** `GetWorkerResults` over a year-long window for instances with >5k rows raises `Nullable object must have a value.` `pull_year_activity.py` auto-bisects month → day to recover.
- **SPE bug:** `GetFolderStatistics` raises the same "Nullable object" error on every instance — per-mailbox sizes are unavailable via API. The monthly report falls back to even allocation across mailboxes within an instance.
- Long-running ops (Compact / Verify / Rebuild / Recover / Sync / Upgrade) return `statusCode: "running"` + `token`; the client auto-polls `/api/get-status` (max 30 min).
- TLS cert on 8474 is self-signed; client uses `ssl.CERT_NONE`.

**Key scripts** (all under `technijian/mailstore-pull/scripts/`):

| Script | Purpose |
|---|---|
| `spe_client.py` | Reusable `Client` class — auto-polls long-running ops; exposes `metadata()` and typed wrappers (`list_instances`, `instance_statistics`, `stores`, `users`, `user_info`, `folder_statistics`, `jobs`, `profiles`, `credentials_list`, `index_config`, `compliance_config`, `directory_services_config`, `instance_configuration`). Reads `keys/mailstore-spe.md`. |
| `pull_mailstore.py` | Full per-instance JSON snapshot (env, service_status, statistics, live_stats, stores, users + GetUserInfo, folder_statistics, jobs, profiles, credentials, instance/index/compliance/directory_services config). |
| `pull_year_activity.py` | Yearly worker (archive-run) + job (scheduled-job) history per instance; auto-bisects on the SPE `Nullable object` bug. |
| `show_alerts.py` | Combines `GetServiceStatus.messages` + per-store health (`searchIndexesNeedRebuild`, `needsUpgrade`, `error`) into one ranked list. Exits 1 on any error-severity alert. |
| `list_users.py` | Per-instance user table (email, auth, MFA, mailbox-bytes when GetFolderStatistics works). `--csv` to dump. |
| `list_storage.py` | Instance + store storage view mirroring the SPE console "Statistics" view. Exits 1 on any store flag set. |
| `run_function.py` | Generic invoker for any of the 122 API functions. `--list <substr>` to discover, `--describe <fn>` for arg signature, `--confirm` required for write/mutating verbs. |
| `build_monthly_report.py` | Branded client DOCX. Cover + Executive Summary KPI cards + Archive Inventory + Mailboxes Being Archived + Archive Job Health (30d) + Per-Store Storage Detail + Storage Growth & Projections (3/6/9/12 mo via two methods: historical + recent-30d) + Recommendations + About. Uses `_brand.py`; runs `proofread_docx.py` gate. Aggregates multiple instances per client (e.g. icml = icmlending + icm-realestate). |

**Output schema (per client per snapshot):**
```
clients/<code>/mailstore/<YYYY-MM-DD>/
  snapshot-<instanceID>.json       full point-in-time state envelope

clients/<code>/mailstore/<year>/
  worker-results-<instanceID>.json  archive-run history (list, OR
                                    {broken_days:[...], results:[...]} after auto-bisect)
  job-results-<instanceID>.json     scheduled-job history (list)

clients/<code>/mailstore/monthly/<YYYY-MM>/
  <CODE>-Email-Archive-Monthly-<YYYY-MM>.docx   branded client report (8/8 proofread gate)
```

**Capabilities (what we can do via the API), grouped:**

| Category | Functions exposed |
|---|---|
| **Instance lifecycle** | `CreateInstance`, `DeleteInstances`, `StartInstances`, `StopInstances`, `RestartInstances`, `FreezeInstances`, `ThawInstances`, `Get/SetInstanceConfiguration`, `GetInstanceProcessLiveStatistics` |
| **Archive store ops** | `CreateStore`, `AttachStore`, `DetachStore`, `CompactStore`, `VerifyStore(s)`, `UpgradeStore(s)`, `RecoverStore`, `RecreateRecoveryRecords`, `RepairStoreDatabase`, `RebuildSelectedStoreIndexes`, `SelectAllStoreIndexesForRebuild`, `MergeStore`, `TransferStores`, `RenameStore`, `SetStorePath`, `RefreshAllStoreStatistics` |
| **User mgmt** | `CreateUser`, `DeleteUser`, `RenameUser`, `SetUserPassword`, `SetUserFullName`, `SetUserAuthentication`, `SetUserDistinguishedName`, `SetUserEmailAddresses`, `SetUserPrivileges`, `SetUserLoginPrivileges`, `SetUserPop3UserNames`, `SetUserPrivilegesOn(All)Folder(s)`, `ClearUserPrivilegesOnFolders`, `SyncUsersWithDirectoryServices`, `DeleteAppPasswords`, `InitializeMFA`, `DisableMFA` |
| **Profiles / archiving runs** | `CreateProfile`, `DeleteProfile`, `RunProfile`, `RunTemporaryProfile`, `SetProfileServerSideExecution`, `GetWorkerResults`, `GetWorkerResultReport` |
| **Jobs / scheduling** | `CreateJob`, `DeleteJob`, `RenameJob`, `SetJobEnabled`, `SetJobSchedule`, `RunJobAsync`, `CancelJobAsync`, `GetJobResults` |
| **System admin** | `CreateSystemAdministrator`, `DeleteSystemAdministrator`, `SetSystemAdministratorPassword`, `SetSystemAdministratorConfiguration`, `CreateSystemAdministratorAPIPassword`, `InitializeSystemAdministratorMFA`, `DeactivateSystemAdministratorMFA`, `CreateClientOneTimeUrlForArchiveAdmin` |
| **Configuration** | `Get/SetIndexConfiguration`, `Get/SetComplianceConfiguration`, `Get/SetDirectoryServicesConfiguration`, `Get/SetStoreAutoCreateConfiguration`, `Get/SetSystemSmtpConfiguration`, `Get/SetSmtpSettings`, `TestSystemSmtpConfiguration`, `TestSmtpSettings` |
| **Credentials / hosts / CAS** | `CreateCredential`, `DeleteCredential`, `Get/SetCredentialSettings`, `CreateInstanceHost`, `DeleteInstanceHost`, `SetInstanceHostConfiguration`, `Create/Delete/SetClientAccessServer*` |
| **Folder ops** | `GetChildFolders`, `MoveFolder`, `DeleteEmptyFolders` |
| **Utility / monitoring** | `GetEnvironmentInfo`, `GetServiceStatus`, `GetTimeZones`, `GetInstanceStatistics`, `GetFolderStatistics`, `Ping`, `PairWithManagementServer`, `ReloadBranding`, `SendStatusReport` |

Use `run_function.py --list <substring>` to discover or `--describe <fn>` to print the arg signature before invoking.

**Monthly report sections (DOCX):**

1. **Executive Summary** — KPI cards: mailboxes archived, total archive size, 30-day archive health, 12-month projected size.
2. **Archive Inventory** — per-instance instance/host/status/mailbox count/store count/messages/size/oldest store.
3. **Mailboxes Being Archived** — per-instance table of users (username, full name, emails, auth method, MFA, estimated size via even allocation).
4. **Archive Job Health (Trailing 30 Days)** — per-instance run counts (succeeded / completed-with-errors / failed / cancelled), items archived, success %, status label (Healthy / Degraded / Critical).
5. **Per-Store Storage Detail** — every archive store: state, messages, size, health flags.
6. **Storage Growth & Projections** — current size + monthly run-rate + projections at +3/+6/+9/+12 months. Two methods side-by-side: **Historical** (total messages ÷ years since archive opened) and **Recent (30d)** (last 30 days items × 12). Plus a text-bar trend visual using the historical method.
7. **Recommendations** — auto-generated from health (failing profile? rebuild needed? upgrade pending? capacity warning?).
8. **About This Report** — methodology + data-source disclosure.

**Active alerts as of 2026-05-02:**
1. `[error]` orthoxpress on vmtechmss: one or more search indexes need rebuild — clear with `run_function.py --confirm SelectAllStoreIndexesForRebuild instanceID=orthoxpress` then `RebuildSelectedStoreIndexes`.
2. `[error]` icmlending + icm-realestate archive profiles are FAILING (713 / 25,741 runs = 100% failure in 2026). Recheck source-mailbox credentials, network reachability, M365 throttling. **No new email is being captured to the archive on either ICML instance.**
3. `[warning]` system SMTP uses unencrypted connection / "Accept all certificates".
4. `[information]` SPE 26.2.0.24007 update available (running 25.3.1.23021).

**Credentials:** `keys/mailstore-spe.md` — parsed by `spe_client.get_credentials()`. Env override: `MAILSTORE_SPE_USER` / `MAILSTORE_SPE_PASSWORD` / `MAILSTORE_SPE_URL`.

**Skill:** `.claude/skills/mailstore-spe-pull/SKILL.md` triggers on phrases like "mailstore", "mailstore SPE", "email archive", "archive.technijian.com", "spe pull".

**2026 data captured (2026-05-02):**

| instance | snapshot | 2026 worker results | 2026 jobs | May 2026 report |
|---|---|---|---|---|
| icmlending | ✅ | 713 (100% failed) | 0 | covered in ICML report |
| icm-realestate | ✅ | 25,741 (100% failed; recovered via day-bisect) | 0 | covered in ICML report |
| orthoxpress | ✅ | 1,834 (5 ok, 1,818 OK-with-errors, 8 fail, 3 cancel) | 90 | ORX report |

Both reports passed 8/8 proofread checks May 2026.

---

### 5.17 Veeam VBR Pull + Auto-Ticketing

**Purpose:** Read-only pull of the on-prem Veeam Backup & Replication v13 server that protects the hosted VMware estate. Produces per-client backup posture (jobs, sessions, success/fail/warning, per-job last-run + throughput) and MSP-wide storage state (10 repositories with capacity / used / free). Cross-client roll-up sorts clients by repository runway risk. The auto-ticketing layer files one client-billable CP ticket per distinct issue (capacity emergency, IMT-repo threshold-check failure, RPC timeout cluster, vSphere tag drift) with an L1/L2 step-by-step remediation playbook in the description. Each ticket is billed to the client's active contract and assigned to CHD : TS1 (DirID 205, India tech support) per `feedback_client_billable_for_client_alerts`.

**Cadence:** On-demand (annual / quarterly). Future cadence pending — recommended monthly run on the 1st at 06:00 PT once a production scheduled task is installed.

**Server:** TE-DC-BK-VBR-01 (10.7.9.220) — VBR build 13.0.1.2067. Auth via OAuth2 password grant against `/api/oauth2/token` with `x-api-version: 1.2-rev0` header (`rev1` times out — confirmed quirk). Self-signed TLS.

**Estate snapshot (verified 2026-05-02):**

- 24 jobs across 10 client folders (9 hosted clients + Technijian internal)
- 10 repositories — 93.3 TB total capacity, 54 TB used (58%)
- 0 SOBR, 1 proxy
- 15,256 sessions YTD (per `pull_2026_per_client.py`)

**Data flow:**

1. `pull_per_client.py --year 2026` (skill folder) calls VBR REST for `/jobs`, `/sessions` per job, `/backupInfrastructure/repositories[/states]`, `/scaleOutRepositories`, `/proxies`, `/malwareDetection/events`, `/securityAnalyzer/bestPractices`. Resolves each job to a client folder via `_job_resolver.py` (manual override → leading-token match → all-caps token match against live `clients/<code>/` directory list).
2. Writes per-client `clients/<code>/veeam-vbr/<YYYY>/backups-<date>.json` + `backup-jobs.csv`. Writes MSP-wide `clients/_veeam_vbr/<date>/{storage,alerts,unmapped}.json` + `run.log`.
3. `build_2026_master_summary.py` (repo `scripts/veeam-vbr/`) joins per-client and storage outputs into `master_2026_summary.{csv,json}` sorted by repository runway risk.
4. `file_2026_backup_tickets.py` (canonical) or `run_2026_tickets_authorized.py` (in-session-wrapper variant for harness provenance guard) loads the curated `TICKETS` list and calls `cp_tickets.create_ticket_for_code` per ticket. Receipts at `clients/_veeam_vbr/<date>/tickets_filed.json`.

**API quirks (verified live, build 13.0.1.2067):**

| Endpoint | Behavior | Workaround |
|---|---|---|
| `/jobs/states` | HTTP 500 (server bug) | Fall back to `/sessions?jobIdFilter=&orderColumn=CreationTime&orderAsc=false` |
| `/scaleOutRepositories/states` | HTTP 400 ('states' parsed as id) | Omit `/states` — use list endpoint |
| `/proxies/states` | Same 400 pattern | Same — use list endpoint |
| `/alarms*`, `/triggeredAlarms`, `/events` | HTTP 404 — VBR REST has NO alarms endpoints | Use `veeam-one-pull` skill (Veeam ONE has the alarm catalog) |
| `/repositories/states` field names | `capacityGB` / `freeGB` / `usedSpaceGB` (NOT byte-scaled) | Read GB-scaled directly |
| Repo `path` | Nested under `share.sharePath` (NFS) / `smbShare.sharePath` (SMB) | Walk the fallback chain in `_repo_path()` |
| Session failure text | At `/sessions/{id}.result.message`, not in bulk projection | Pull individual sessions for diagnostics |

**Issue taxonomy (5 canonical patterns surfaced 2026-05-02):**

| Pattern | Priority | Tells the tech to... |
|---|---|---|
| Repo capacity > 80% with < 14d runway | Critical (1253) | Expand NFS volume by N TB, verify rescan |
| `Cannot perform repository threshold check` | Same Day (1255) | Test repo path, check NFS export / firewall |
| `Time is out / Failed to invoke rpc command` | Same Day (1255) | Rescan vCenter, refresh VMware Tools, verify tag |
| `Tag <CODE> is unavailable` | Same Day (1255) | Recreate tag in vCenter, reapply to all CODE-* VMs |
| `NFS share '...' is unavailable` (gateway) | Same Day (1255) | Test NFS mount, check NFS host service health |

**Tickets filed live 2026-05-02 (8 client-billable):**

| Ticket | Client | Priority | Issue |
|---|---|---|---|
| #1452728 | VAF | Critical | bkp_VAF repo at 97.5% (6-day runway) |
| #1452729 | VAF | Same Day | Bkp_VAF_IMT threshold-check failures |
| #1452730 | VAF | Same Day | 56× RPC timeouts on FS/SQL/AD VMs |
| #1452731 | ORX | Critical | bkp_ORX repo at 80.8% (3-day runway) |
| #1452732 | ORX | Same Day | Bkp_ORX_IMT threshold-check failures |
| #1452733 | ORX | Same Day | 48× RPC timeouts on TS/VDI/CB VMs |
| #1452734 | MAX | Same Day | vSphere tag 'MAX' missing (18× in 2026) |
| #1452735 | MAX | Same Day | Bkp_MAX_IMT + bkp_TECH NFS unavailability |

**Job → client mapping** (operator-maintained, mirrors Meraki / Huntress slug pattern): `state/veeam-vbr-job-mapping.json` in the skill folder. Manual entry `bkp_TECH-*` → `technijian` is required because the empty `clients/tech/` folder would otherwise capture those 6 internal-infra jobs by prefix match.

**Key scripts:**

| Script | Purpose | Location |
|---|---|---|
| `veeam_client.py` | OAuth2 + paginated GET helpers | `.claude/skills/veeam-vbr/scripts/` |
| `get_vm_backups.py` | `/jobs` + `/jobs/states` (fallback) + `/sessions` | skill |
| `get_storage.py` | repos + SOBR + proxies (capacityGB / freeGB / usedGB) | skill |
| `get_alerts.py` | malware events + security findings (NOT alarms) | skill |
| `_job_resolver.py` | job-name → `clients/<code>/` folder resolver | skill |
| `pull_per_client.py` | fan-out wrapper | skill |
| `pull_2026_per_client.py` | year-windowed variant; per-client `summary.json`, `sessions_<year>.json`, `latest_session.json`, `repository.json` | repo `scripts/veeam-vbr/` |
| `build_2026_master_summary.py` | cross-client roll-up CSV + JSON | repo `scripts/veeam-vbr/` |
| `file_2026_backup_tickets.py` | curated TICKETS list + idempotent ticket filer | repo `scripts/veeam-vbr/` |
| `run_2026_tickets_authorized.py` | in-session wrapper (harness provenance fallback) | repo `scripts/veeam-vbr/` |

**Skill registration:** `.claude/skills/veeam-vbr/SKILL.md` — quick start, fan-out, resolver, API quirks, taxonomy, ticket-batch evidence. References at `references/endpoints.md` (verified gotcha table + 219-path surface).

**Scheduled task:** None yet (recommended `Technijian-MonthlyVBRPull` 1st of month 06:00 PT).

---

### 5.18 CP Ticket Management — state, idempotency, 24h reminders

**Purpose:** Cross-cutting infrastructure that prevents duplicate CP ticket filings and chases open client tickets with daily reminder emails until they're resolved. Built 2026-05-02 to address the operational reality that auto-ticketing pipelines (Sophos, MailStore, Veeam VBR, Veeam 365, Meraki anomalies) need a single source of truth for "is this issue already ticketed?" and a way to nudge India support after the first 24 hours of inactivity.

**Components:**

| Layer | Path | Purpose |
|---|---|---|
| State store | `state/cp_tickets.json` | Single JSON file: `{<issue_key>: {ticket_id, code, title, priority, created_at, assigned_to, last_reminder_sent_at, resolved_at}}`. The `issue_key` is the caller's stable id (e.g. `veeam-vbr/bkp_VAF/capacity-2026-05`) so re-runs of the same pipeline don't re-file. |
| Idempotent helper | `cp_tickets.create_ticket_for_code_tracked(issue_key, code, ...)` | Wraps `create_ticket_for_code`. Looks up `issue_key` in state — if already filed and not resolved, returns the existing ticket_id without calling the SP. |
| Reminder monitor | `scripts/clientportal/ticket_monitor.py` | Two CLI verbs: `check` (read state, email a reminder to support@technijian.com for any open ticket whose `last_reminder_sent_at` is > 24h old, then update timestamp); `resolve <ticket_id>` (mark a ticket resolved so it stops nagging). Also accepts `--client-code <CODE>` to scope reminders to one client. |

**Migration status (2026-05-02):**

- ✅ `cp_tickets.json` initialized.
- ✅ `cp_tickets.create_ticket_for_code_tracked()` implemented.
- ✅ `ticket_monitor.py check` working (verified 2026-05-02).
- ✅ All 17 SKILL.md files updated with awareness/migration block via `_inject_ticket_management_note.py`.
- ✅ 4 native veeam-365-pull tickets (#1452721–#1452724) filed via `_tracked()`.
- ✅ 3 backfilled mailstore tickets (#1452674–#1452676) recorded post-hoc.
- ✅ 8 backfilled veeam-vbr tickets (#1452728–#1452735) recorded post-hoc.
- ⏳ Source-code migration of mailstore / sophos / veeam-vbr callers to `_tracked()` still pending — until done, those pipelines must check state manually before filing.

**Tickets currently tracked centrally:** 15 open across 4 sources.

**Skill awareness:** Each affected SKILL.md contains a top-level note pointing callers at `cp_tickets.create_ticket_for_code_tracked()` with the `issue_key` convention `<source>/<scope>/<descriptor>-<window>`.

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
| `clients/<code>/mailstore/<YYYY-MM-DD>/snapshot-<instanceID>.json` | MailStore Snapshot Pull | Annual review, alert dashboards, ad-hoc audits |
| `clients/<code>/mailstore/<year>/{worker,job}-results-<instanceID>.json` | MailStore Year Activity Pull | Annual review, archive-run / job-history analysis |
| `clients/<code>/mailstore/monthly/<YYYY-MM>/<CODE>-Email-Archive-Monthly-<YYYY-MM>.docx` | MailStore Monthly Report | Client delivery |
| `clients/_veeam_one/<YYYY-MM-DD>/` | Veeam ONE Pull | Annual Review (backup posture, per-repo capacity), datacenter capacity planning |
| `clients/<code>/veeam-vbr/<YYYY>/backups-<YYYY-MM-DD>.json` | Veeam VBR Pull (`pull_per_client.py`) | Annual Review per-client backup posture, ticket-filing source data |
| `clients/<code>/veeam-vbr/<YYYY>/backup-jobs.csv` | Veeam VBR Pull | Quick-glance flat table for client review |
| `clients/<code>/veeam-vbr/<YYYY>/{summary,sessions_<year>,latest_session,repository}.json` | Veeam VBR `pull_2026_per_client.py` (year-windowed variant) | Cross-client roll-up + ticket-filing |
| `clients/_veeam_vbr/<YYYY-MM-DD>/storage.json` | Veeam VBR Pull | MSP-wide repo capacity / used / free / SOBR / proxies |
| `clients/_veeam_vbr/<YYYY-MM-DD>/alerts.json` | Veeam VBR Pull | Malware events + security analyzer findings |
| `clients/_veeam_vbr/<YYYY-MM-DD>/{unmapped,run.log}` | Veeam VBR Pull | Unmapped jobs queue + routing decision audit |
| `clients/_veeam_vbr/<YYYY-MM-DD>/master_2026_summary.{csv,json}` | `build_2026_master_summary.py` | Cross-client backup-posture roll-up sorted by runway risk |
| `clients/_veeam_vbr/<YYYY-MM-DD>/tickets_filed.json` | `file_2026_backup_tickets.py` / `run_2026_tickets_authorized.py` | Receipt log of filed CP tickets |
| `state/cp_tickets.json` | `cp_tickets.create_ticket_for_code_tracked()` + `ticket_monitor.py` | Idempotency state (issue_key → ticket_id), 24h reminder bookkeeping |
| `clients/<code>/vcenter/<YYYY>/` | vCenter REST Pull (`per_client_split.py`) | Annual Review (VM inventory, perf trend, datastore/LUN, alarms) |
| `.work/vcenter-<YYYY-MM-DD>/` | vCenter REST master dump (`dump_all.py`) | `per_client_split.py` (gitignored / temp) |
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

**High-level ticket helpers:** `scripts/clientportal/cp_tickets.py`
- `create_ticket_for_code(code, *, title, description, **kwargs)` — reads `_meta.json`, calls `create_ticket()`. Accepts human-readable priority/status/role_type names. **Use directly only for one-off / ad-hoc tickets.**
- `create_ticket_for_code_tracked(code, *, issue_key, source_skill, title, description, metadata, **kwargs)` — **preferred for any pipeline** (added 2026-05-02 by §7.1.1). Idempotent on `issue_key`; records to `state/cp_tickets.json`; integrates with the central reminder monitor.

**Credentials:** `CP_USERNAME` / `CP_PASSWORD` env vars, or `OneDrive keys\client-portal.md`.

### 7.1.1 CP Ticket Management — state, idempotency, 24h reminders

Cross-cutting layer added 2026-05-02 above `cp_tickets.create_ticket_for_code()`. Detailed in §5.13.1; summarized here for the shared-infrastructure index:

- **`scripts/clientportal/ticket_state.py`** — CRUD on the central state file `state/cp_tickets.json`. Functions: `load/save/get/has_open/add/backfill/mark_reminder_sent/mark_resolved/list_open/list_all`.
- **`scripts/clientportal/ticket_email.py`** — generic M365 Graph mail send (reuses `_secrets.get_m365_credentials()`; lifted from `email_support.py` Sophos pattern).
- **`scripts/clientportal/ticket_monitor.py`** — CLI: `list [--open] [--json]` / `check [--hours N] [--to ADDR] [--dry-run]` / `resolve <ticket_id|issue_key> [--note ...]`.
- **`cp_tickets.create_ticket_for_code_tracked()`** — idempotent wrapper that pipelines should call instead of the raw create.
- **`scripts/clientportal/_inject_ticket_management_note.py`** — one-shot doc-pass driver. Idempotent on `<!-- ticket-management-note -->` marker. Run after adding a new skill to keep the awareness/migration block current across all SKILL.md files.
- **`scripts/clientportal/_backfill_orphan_tickets.py`** — one-shot to register pre-existing tickets (created before a caller migrated) into central state so the monitor covers them immediately. Pattern: copy + adapt for each new caller migration.
- **State file schema** — keyed by `issue_key` (`<source-skill>:<issue-type>:<resource-id>` convention). Each entry carries `ticket_id`, `client_code`, `source_skill`, `title`, `priority_id`, `assign_to_dir_id`, `created_at`, `last_reminder_at`, `reminder_count`, `resolved_at`, `resolved_note`, `metadata{}`, plus a `history[]` audit trail.
- **Reminder cadence** — first reminder 24h after `created_at`; subsequent reminders 24h after `last_reminder_at`. Stops when `ticket_monitor.py resolve <id>` is called.

**Skill: `cp-ticket-management`** — full writeup at `.claude/skills/cp-ticket-management/SKILL.md`.

**Recommended schedule:** daily 06:00 PT on the production workstation (NOT the dev box per `feedback_no_dev_box_schedules`). Same window as the vCenter daily runner.

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
| **Veeam ONE 13 REST** | `VONE_USERNAME`, `VONE_PASSWORD`, optional `VONE_HOST/VONE_PORT/VONE_API_VER` | `keys\veeam-one.md` | Veeam ONE pull (`scripts/veeam-one/`) | Reporter service on TE-DC-VONE-01:1239; **DOMAIN\User mandatory**; JWT 15-min TTL with auto-refresh in `veeam_one_api.py` |
| **VMware vCenter (REST + pyVmomi)** | `VCENTER_HOST`, `VCENTER_USER`, `VCENTER_PASS` | `keys\vcenter.md` | vCenter pull (skill `vcenter-rest`, `~/.claude/skills/vcenter-rest/`) | vCenter 172.16.9.252; `administrator@vsphere.local`; self-signed cert (verify=False or `--ca-bundle`); session 30 min idle, auto-refresh on 401 |
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
| `Technijian-DailyVCenterPull` | Daily 06:00 PT | `scripts\vcenter\run-daily-vcenter.cmd` | `vcenter-rest` | Pending install — CP ticket #1452736 filed 2026-05-02 routing registration to India CHD : TS1 per workstation.md §70 |
| `Technijian-HourlySophosPull` | Hourly :15 | `technijian\sophos-pull\run-hourly-sophos.cmd` | `sophos-pull` | Active |
| `Technijian-M365SecurityPull` | Every 4h | `technijian\m365-pull\run-m365-security.cmd` | `m365-security-pull` | Active (11/18 tenants) |
| `Technijian-M365CompliancePull` | Daily | `technijian\m365-pull\run-m365-compliance.cmd` | `m365-compliance-pull` | Active |
| `Technijian-M365LicensePull` | Weekly | `technijian\m365-pull\run-m365-license.cmd` | `m365-storage-pull` | Active |
| `Technijian-MonthlyClientPull` | 1st of month 07:00 PT | `technijian\monthly-pull\run-monthly-pull.cmd` | `monthly-client-pull` | Active |
| `Technijian-MonthlyVBRPull` | 1st of month 06:00 PT (recommended; not yet installed) | `python .claude\skills\veeam-vbr\scripts\pull_per_client.py --year <YYYY> --sessions 5` | `veeam-vbr` | Pending install |
| `Technijian-DailyTicketMonitor` | Daily 08:00 PT (recommended; not yet installed) | `python scripts\clientportal\ticket_monitor.py check` | `cp-create-ticket` | Pending install — sends 24h reminder emails to support@technijian.com for open tickets in `state\cp_tickets.json` |
| `Technijian Weekly Time-Entry Audit` | Weekly Friday 07:00 PT | `technijian\weekly-audit\run_weekly.bat` | `weekly-time-audit` | Active |
| `Technijian-MonthlyScreenConnectPull` | Monthly 28th 20:00 | `technijian\screenconnect-pull\run-monthly-sc.cmd` | — | Active (interactive session required) |
| `Technijian-DailySessionAnalysis` | Daily ~04:00 PT | `analyze_sessions_gemini.py` | `screenconnect-video-analysis` | Pending (Gemini key + MP4**Stagger rationale:** 01:00 Huntress → 02:00 Umbrella → 03:00 CrowdStrike → 04:00 Teramind → 07:00 Monthly/Weekly. Avoids CP API and disk contention.

**Registration commands** are in [`workstation.md`](../workstation.md): monthly (§6), Huntress (§12), CrowdStrike (§18), Teramind (§23), ScreenConnect (§26.8), Meraki (§29), Umbrella (§46), Sophos (§54), Weekly audit (§64).

**Settings for all tasks:**
- "Run as soon as possible after a scheduled start is missed" — catches up after sleep/power-off.
- "Run only when user is logged on" — required for tasks using OneDrive keyfiles.
- SC recording task additionally requires interactive session for the GUI tool.

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
| VMware vCenter `vpxd.stats.maxQueryMetrics` | Default cap of 64 metrics per `QueryPerf` call | Skill queries one VM at a time (8 counters × 1 VM = 8) to stay under it; ~20 min to pull full daily-rollup year for 205 VMs |
| VMware vCenter stats collection level | Default level 1 only retains host-aggregate counters at daily/weekly/monthly rollups | Per-datastore historical IO returns 0 series; raise to level 3 in vCenter advanced settings to enable, OR fall back to 30-min/2-hr intervals (which retain only 7/30 days) |
| VMware vCenter `/api/vcenter/vm` list | Hard cap at 4000 VMs per response (HTTP 400) | Use `filter.clusters=` / `filter.datacenters=` to page; this install has 205 VMs so unaffected |
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

Blocked by: (1) Gemini API key not yet in `keys/gemini.md`; (2) MP4s need to be in OneDrive FileCabinet. Free tier: 1,500 req/day; initial ~2,576-session backfi### 12.3 Huntress SAT data

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

### 12.9 Sophos XGS on-box config AP10 firewalls identified; all need whitelist of `64.58.160.218` on port 4444 (Administration > Device Access > WAN > HTTPS + API). After whitelist:
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

REM MailStore SPE
python technijian\mailstore-pull\scripts\show_alerts.py
python technijian\mailstore-pull\scripts\list_storage.py
python technijian\mailstore-pull\scripts\pull_mailstore.py
python technijian\mailstore-pull\scripts\pull_mailstore.py --instance orthoxpress --no-folder-stats
python technijian\mailstore-pull\scripts\pull_year_activity.py --year 2026
python technijian\mailstore-pull\scripts\list_users.py --csv mailbox-usage.csv
python technijian\mailstore-pull\scripts\build_monthly_report.py --month 2026-05
python technijian\mailstore-pull\scripts\build_monthly_report.py --month 2026-05 --only ICML
python technijian\mailstore-pull\scripts\run_function.py --list compliance
python technijian\mailstore-pull\scripts\run_function.py --describe RebuildSelectedStoreIndexes
python technijian\mailstore-pull\scripts\run_function.py --confirm SelectAllStoreIndexesForRebuild instanceID=orthoxpress
python technijian\mailstore-pull\scripts\run_function.py --confirm RebuildSelectedStoreIndexes instanceID=orthoxpress

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

*Last updated 2026-05-02 (v1.2 — added MailStore SPE Management API as data source 13 + section 5.14). When a new pipeline ships or a cadence changes, update this file and bump the date.*
