# annual-client-review — Repository Specification

**Scope:** This is the system-of-record document for the
`annual-client-review` repo. It catalogs every pipeline, skill, schedule,
data source, credential, output convention, and known gap as of
**2026-04-29**. Read this before starting work in this repo. Update this
when you ship a new pipeline or change a cadence.

The repo's purpose is to capture, classify, and report on Technijian
client-service delivery data so that:

1. **Annual reviews** for each client can be produced on a per-client basis
   with branded Word + Excel deliverables and per-client savings analyses.
2. **Weekly time-entry hygiene** is enforced by flagging outliers and emailing
   each tech personalized coaching before Friday evening's invoice run.
3. **Monthly archives** of tickets + time entries per client are kept
   git-diffable so quarterly and annual reviews don't have to re-pull.
4. **Daily Huntress EDR snapshots** per client power monthly activity reports
   and daily license-usage rollups.

This is a **data + reporting** repo. It is not a service. There is no
deployable application; every pipeline is a Python script driven either
on-demand or by a Windows Scheduled Task on a dedicated workstation.

---

## 1. Top-level layout

```text
annual-client-review/
  .gitignore
  workstation.md                  legacy / monthly-pull workstation setup (will be unified)
  SPEC.md                         this file
  clients/                        per-client folders (70 clients, see Section 7)
  scripts/                        ad-hoc per-client analysis + the cp_api shared module
  technijian/                     pipelines, skills' worker code, audit outputs
    tech-training/                annual time-entry audit (existing)
    weekly-audit/                 Friday 07:00 PT outlier audit + email
    monthly-pull/                 1st-of-month CP ticket+time-entry snapshot
    huntress-pull/                Daily 01:00 PT Huntress EDR snapshot
```

| Path | Owner | Cadence | Reads | Writes |
|---|---|---|---|---|
| `clients/` | manual + every pipeline | n/a | n/a | per-client outputs |
| `scripts/` | manual ad-hoc + shared CP API client | n/a | CP API | one-off per-client analyses |
| `scripts/clientportal/` | shared library | n/a | CP API | n/a |
| `technijian/tech-training/` | annual review | once / year | every client's data | branded annual reports |
| `technijian/weekly-audit/` | weekly skill | **Fri 07:00 PT** | CP API, last 7 days | per-tech Word + email |
| `technijian/monthly-pull/` | monthly skill | **1st of month 07:00 PT** | CP API, prior month | `clients/<code>/monthly/` |
| `technijian/huntress-pull/` | huntress skill | **daily 01:00 PT** | Huntress v1 API | `clients/<code>/huntress/` |

---

## 2. Data sources

### 2.1 Technijian Client Portal (CP)

- Base URL: `https://api-clientportal.technijian.com`
- Auth: bearer token via `POST /api/auth/token`
  with `{ "userName": ..., "password": ... }`.
- Generic SP execution: `POST /api/modules/{module}/stored-procedures/{db}/{schema}/{name}/execute`
  with `{ "Parameters": {...} }`.
- Helper module: [`scripts/clientportal/cp_api.py`](scripts/clientportal/cp_api.py)
  — handles auth, token reuse, SP execution, and `<Root>/<TimeEntry>/...`
  flat-XML parsing.
- Stored procedures used:

  | SP | Purpose | Returns |
  |---|---|---|
  | `GetAllContracts` | active-contract resolution per client | rows |
  | `[timeentry].[Reporting].[stp_xml_TktEntry_List_Get]` | time entries by `(ClientID, Start, End)` | XML out param |
  | `[invoices].[dbo].[stp_xml_Inv_Org_Loc_Inv_List_Get]` | full invoice history by `DirID` | XML out param |
  | `GET /api/clients/active` | active client list with `LocationCode`/`DirID`/`Location_Name` | JSON rows |

- **Stable per-time-entry ID:** `InvDetID` in the time-entry XML. This is
  the only field reliable enough to use for diffing and fingerprinting.
  See `memory/reference_cp_api_invdetid.md`.
- **Read-only.** No skill in this repo writes to the CP API. A delete
  endpoint spec exists at
  [`technijian/weekly-audit/API-DELETE-ENDPOINT-SPEC.md`](technijian/weekly-audit/API-DELETE-ENDPOINT-SPEC.md)
  for a future hardening pass; do not wire it without explicit re-approval.

### 2.2 Microsoft 365 Graph (Mail)

- Auth: client-credentials flow against
  `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token` with scope
  `https://graph.microsoft.com/.default`.
- Mailbox: `RJain@technijian.com` (overridable via `M365_MAILBOX` env var).
- Required application permissions on the app registration:
  `Mail.Read`, `Mail.Send`, `Mail.ReadWrite` (admin-consented).
- Helper module:
  [`technijian/tech-training/scripts/_secrets.py`](technijian/tech-training/scripts/_secrets.py)
  — resolves `(tenant, client_id, secret, mailbox)` from env vars or the
  `m365-graph.md` keyfile.
- Used by: weekly-audit's email step. Drafts are created with both
  attachments, then `POST /messages/{id}/send` is called per draft. The
  weekly skill cleans up its prior-cycle drafts before creating new ones,
  using the `outlook-drafts-created.csv` manifest.

### 2.3 tech-legal repo (client contacts, read-only)

The neighbouring `tech-legal` repo at
`C:\vscode\tech-legal\tech-legal\clients\<CODE>\CONTACTS.md` is the
authoritative source for client contact data. Each markdown file has the
shape:

```markdown
# <Full Client Name> (<CODE>)
**Client Code:** <CODE>
**Portal DirID:** <int>

## Contract Signer
*Not designated in portal*

## Invoice Recipient
*Not designated in portal*

## Primary Contact
*Not designated in portal*

## All Active Users (N)

### <Name>
- **Email:** <email>
- **Phone:** <phone or N/A>
- **Role:** <C1|C2|C3|...>
```

This repo never copies contact data into its own files. Every read goes
through [`scripts/contacts/contacts_lib.py`](scripts/contacts/contacts_lib.py)
so tech-legal stays the single source of truth. The library exposes:

| Function | Purpose |
|---|---|
| `parse_contacts_md(path)` | parse a single CONTACTS.md → `ClientContacts` |
| `load_all_tech_legal_contacts()` | walk `clients/<CODE>/CONTACTS.md` → `{CODE: ClientContacts}` |
| `cross_reference(legal, active_cp_clients)` | match by DirID first, LocationCode fallback |
| `stale_legal(legal, active_cp_clients)` | tech-legal entries with no active CP match |
| `report_recipients(legal)` | derive send-to list (Primary > Invoice > Signer; falls back to all C1 users) |

The coverage report ([`scripts/contacts/build_contacts_report.py`](scripts/contacts/build_contacts_report.py))
writes outputs to `technijian/contacts/` (see Section 11.1).

### 2.4 Huntress v1 REST API

- Base URL: `https://api.huntress.io/v1`
- Auth: HTTP Basic with **API Key ID + API Secret**, base64-encoded.
- Helper module:
  [`technijian/huntress-pull/scripts/huntress_api.py`](technijian/huntress-pull/scripts/huntress_api.py)
  — handles cursor pagination (`limit` + `page_token` →
  `pagination.next_page_token`), 429 back-off + retry once, and reseller-403
  tolerance.
- **SAT (Security Awareness Training) is NOT in v1.** Verified against
  `https://api.huntress.io/v1/swagger_doc.json` on 2026-04-29. SAT exports
  remain manual until Huntress publishes those endpoints.
- Used by: huntress-pull skill only.

---

## 3. Skills catalog (Claude Code)

Three skills currently exist for this repo. All three live under
`%USERPROFILE%\.claude\skills\<name>\SKILL.md` and call worker scripts
inside `technijian/<pipeline>/scripts/`.

| Skill | Cadence (PT) | Window | Read-only? | Output |
|---|---|---|---|---|
| `weekly-time-audit` | **Fri 07:00** | last 7 days | yes (recommend-only emails) | per-tech Word + email + per-cycle CSV/MD audit |
| `monthly-client-pull` | **1st of month 07:00** | prior calendar month | yes | `clients/<code>/monthly/YYYY-MM/` |
| `huntress-daily-pull` | **daily 01:00** | `[run-24h, run)` UTC | yes | `clients/<code>/huntress/YYYY-MM-DD/` |

None of the three are auto-installed as scheduled tasks on the dev
workstation by design. Production scheduling is done once on a separate
production workstation. See Section 9.

---

## 4. Skill: weekly-time-audit (Fri 07:00 PT)

### 4.1 What it does

For every active client returned by `GET /api/clients/active`:

1. Pull `stp_xml_TktEntry_List_Get(ClientID, today-7d, today)`.
2. Normalize entries to `{Fingerprint, InvDetID, Client, Date, Title, Tech, POD, Shift, Hours, Requestor, ...}`.
3. Apply five flag rules (see 4.2) to identify entries likely to draw a
   client question on the upcoming invoice.
4. Build a per-tech personalized branded Word doc with suggested rewrites
   and suggested adjusted hours.
5. Email each affected tech via Microsoft Graph; CC RJain via the from-mailbox.
6. Append every flagged entry to `technijian/weekly-audit/by-tech/<slug>/history.csv`
   (rolling, append-only, committed).

The skill is **recommend-only**. It does not delete or modify any time
entry. The email asks each tech to either rewrite a flagged title or
reduce the hours through the Client Portal UI before Friday evening's
in-contract invoice run.

### 4.2 Flag rules (H1–H5)

Identical to the rules in
[`technijian/tech-training/scripts/_audit-all-clients.py`](technijian/tech-training/scripts/_audit-all-clients.py)
and re-implemented in
[`technijian/weekly-audit/scripts/_shared.py`](technijian/weekly-audit/scripts/_shared.py)
so the weekly run is self-contained.

| Code | Trigger | Rationale |
|---|---|---|
| H1 | Routine work over the per-category cap | Patches/agent updates/monitoring alerts shouldn't take hours |
| H2 | Vague title (Help/Fix/Issue/Test) with > 0.5h | Client cannot tell what the work was |
| H3 | Single entry > 8 hours | Whole-day dump rather than itemized work |
| H4 | Daily total > 12 hours across tickets | Suggests dating error or double-claim |
| H5 | Same tech + same ticket + same day with sum > 2× cap | Looks like duplicate billing on the invoice |

Per-category caps live in `_shared.py::CATEGORY_CAP` (32 entries; routine
ranges 0.75–3.0h, projects 3.0–4.0h, default 2.5h).

### 4.3 Pipeline

```text
1_pull_weekly.py    → technijian/weekly-audit/<cycle>/raw/<client>/*.csv,json,xml
2_audit_weekly.py   → SUMMARY.md, all-flagged-entries.csv, by-client/, by-tech/
3_build_weekly_docs.py → by-tech/<slug>/<slug>-Weekly-Training.docx
4_email_weekly.py   → outlook-drafts-created.csv → outlook-drafts-sent.csv
run_weekly.py       → invokes 1→2→3→4 in order, aborts on failure
```

Cycle ID = `<year>-W<week>` from `datetime.isocalendar()` in Pacific time.
Backfill / replay via `run_weekly.py --cycle 2026-W17`.

### 4.4 Email body

Built by `4_email_weekly.py::build_html_body()` using Technijian branding
(#006DB6 / #F67D4B / Open Sans). Eight sections:
greeting, summary line, top-flag callout (H1–H5), orange-bar deadline
("tonight at end of day"), two attachments (Word + CSV), what-happens-if-
nothing-changes, reply-with-corrections invitation, RJain signature.

CEO `R-Jain` is excluded from the recipient list (`EXCLUDE_SLUGS`).

### 4.5 Recipient resolution

Reuses `technijian/tech-training/scripts/tech-emails.json` (built by the
annual pipeline's `_resolve-tech-emails.py`). If a slug is missing, falls
back to `<first><last>@technijian.com`. Refresh:

```cmd
python technijian\tech-training\scripts\_resolve-tech-emails.py 2026 --refresh
```text

### 4.6 Per-cycle outputs (committed)

```
technijian/weekly-audit/<YYYY-WWnn>/
  SUMMARY.md
  all-flagged-entries.csv
  audit_log.json
  run_log.json
  by-client/<client>/
    tech-outliers-summary.md
    tech-outliers-detail.csv
    tech-outliers-by-tech.csv
  by-tech/<slug>/
    flagged-entries.csv               InvDetID + suggested hours + suggested rewrite
    training.md
    <slug>-Weekly-Training.docx       branded Word doc emailed to tech
  by-tech/outlook-drafts-created.csv
  by-tech/outlook-drafts-sent.csv
```text

The `raw/` subfolder under each cycle is **gitignored** (large XML/CSV,
reproducible from API). The rolling `by-tech/<slug>/history.csv` outside
the cycle folder IS committed for cross-cycle pattern detection.

### 4.7 Files

| Layer | Path |
|---|---|
| Skill | `~/.claude/skills/weekly-time-audit/SKILL.md` |
| Worker | [`technijian/weekly-audit/scripts/`](technijian/weekly-audit/scripts/) |
| Workstation setup | [`workstation.md`](workstation.md) (sections 51–59) |
| Future-delete spec | [`technijian/weekly-audit/API-DELETE-ENDPOINT-SPEC.md`](technijian/weekly-audit/API-DELETE-ENDPOINT-SPEC.md) |
| Vault page | `Knowledge/weekly-time-audit-skill.md` (in Obsidian vault) |

---

## 5. Skill: monthly-client-pull (1st of month 07:00 PT)

### 5.1 What it does

For every active client returned by `GET /api/clients/active`, pulls the
prior calendar month of time entries (and derives unique tickets) and
writes per-client snapshots:

```
clients/<code>/monthly/YYYY-MM/
  time_entries.xml             raw XML
  time_entries.json            parsed
  time_entries.csv             flat
  tickets.json                 unique tickets derived from time entries
  pull_summary.json            counts, errors, run timestamp
```text

Run-level log: `technijian/monthly-pull/state/<YYYY-MM>.json` plus an
optional `run-YYYY-MM-DD.log` from the wrapper.

### 5.2 Window logic

Default = prior calendar month (`[YYYY-MM-01, last-day]` inclusive).
Boundary days don't double-count because the next run starts at day 1 of
the following month.

Backfill: `python pull_monthly.py --month 2026-01`.

### 5.3 Why per-client per-month folders

- Each client's history is git-diffable in isolation.
- Quarterly / annual reviews `git log clients/<code>/monthly/` to see
  which months have been captured.
- Reruns are idempotent — overwriting one month doesn't touch others.
- Doesn't clobber the cumulative `clients/<code>/data/` written by
  `scripts/clientportal/pull_all_active.py`.

### 5.4 Files

| Layer | Path |
|---|---|
| Skill | `~/.claude/skills/monthly-client-pull/SKILL.md` |
| Worker | [`technijian/monthly-pull/scripts/pull_monthly.py`](technijian/monthly-pull/scripts/pull_monthly.py) |
| Wrapper | `technijian/monthly-pull/run-monthly-pull.cmd` |
| Workstation setup | [`workstation.md`](workstation.md) (repo root, sections 1–9) |
| Vault page | `Knowledge/monthly-client-pull-skill.md` |
| Scheduled task | `Technijian-MonthlyClientPull` (production-only) |

---

## 6. Skill: huntress-daily-pull (daily 01:00 PT)

### 6.1 What it does (v1 scope = agent inventory only)

For every Huntress organization that maps to a Client Portal `LocationCode`,
calls the Huntress v1 REST API and writes per-org snapshots. **v1 captures
the agent inventory only** — every endpoint the Huntress AV/EDR sensor
reports on:

```
clients/<code>/huntress/YYYY-MM-DD/
  agents.json + agents.csv       hostname, OS, version, last_callback_at, isolated, ipv4
  pull_summary.json              counts, errors, mapping_source, window
```text

That is enough to drive:

- "which computers have Huntress installed" reporting,
- daily delta of healthy vs offline agents,
- monthly activity summaries (count of active sensors per client).

Other Huntress data (incident reports, signals, external ports, M365 ITDR
identities, reseller invoice line items) is **intentionally not captured in
v1**. The shared client `huntress_api.py` already exposes those helpers; the
worker (`pull_org()` in `pull_huntress_daily.py`) only calls the agents
endpoint until the user explicitly asks for the rest.

Account-level outputs at `technijian/huntress-pull/<YYYY-MM-DD>/` cover
account info, the full Huntress org list, the resolved
`huntress_org_id → LocationCode` mapping, an `unmapped.json` action list,
and `run_log.json`. (Reseller subscriptions + latest invoice are captured
opportunistically when the account has reseller access; if the account is
not a reseller, these endpoints 403 and the pull tolerates it.)

### 6.2 Mapping (org → LocationCode)

Conservative on purpose to avoid mis-classifying one client's EDR data
into another's folder:

1. Manual override in `technijian/huntress-pull/state/huntress-org-mapping.json`
   (`{ "manual": {...}, "ignore": [...] }`).
2. Otherwise exact match on the normalized organization name (lowercased,
   stripped of Inc/LLC/Co/etc. punctuation).

Anything still unmatched lands in `unmapped.json` for manual triage.
**No fuzzy matching.**

### 6.3 Window logic

`[run_time - 24h, run_time)` UTC, right-exclusive. `--hours 72` for
backfills; `--date YYYY-MM-DD` anchors window-end to ~01:00 PT of that date
so the per-day directory tag matches.

### 6.4 Scope guard rails

Read-only. **Do not** wire any of:

- `/incident_reports/{id}/resolution` write
- `/escalations/{id}/resolution` write
- agent isolation (POST)
- remediation bulk approve / reject

Incident response stays in the SOC workflow. The skill only captures and
stores; report generation is a downstream consumer.

### 6.5 SAT gap

Huntress Managed Security Awareness Training is **not in v1**. Do not add a
SAT pull script speculatively. When endpoints ship, extend
`huntress_api.py` and add per-client SAT outputs alongside `agents.json`.

### 6.6 Files

| Layer | Path |
|---|---|
| Skill | `~/.claude/skills/huntress-daily-pull/SKILL.md` |
| Shared client | [`technijian/huntress-pull/scripts/huntress_api.py`](technijian/huntress-pull/scripts/huntress_api.py) |
| Worker | [`technijian/huntress-pull/scripts/pull_huntress_daily.py`](technijian/huntress-pull/scripts/pull_huntress_daily.py) |
| Wrapper | `technijian/huntress-pull/run-daily-huntress.cmd` |
| Mapping overlay | `technijian/huntress-pull/state/huntress-org-mapping.json` |
| Workstation setup | `technijian/huntress-pull/workstation.md` |
| Keyfile | `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\huntress.md` |
| Vault page | `Knowledge/huntress-daily-pull-skill.md` |
| Scheduled task | `Technijian-DailyHuntressPull` (production-only) |

---

## 7. Per-client folder layout

There are **70 client folders** under `clients/`. Two layout patterns
exist; both are valid.

### 7.1 Pattern A — Annual-review-rich client (e.g. `bwh/`, `aava/`)

```
clients/<code>/
  <YYYY>/                          per-year annual-review folder
    02_Invoices/
    03_Accounting/                 CSV aggregations + master XLSX + GLOBAL-REVIEW.md
    04_Raw_Data/                   raw XML pulled from CP SPs
    05_Reports/                    branded Word + MD client-facing deliverables
    06_Scripts/                    per-client _pull-*.py / _build-*.py
    README.md
  data/                            cumulative pull (every entry since contract signed)
    contract_summary.json
    time_entries.{xml,json,csv}
    invoices.{xml,json,csv}
    tickets.json
  monthly/                         set by monthly-client-pull skill
    YYYY-MM/
      time_entries.{xml,json,csv}
      tickets.json
      pull_summary.json
  huntress/                        set by huntress-daily-pull skill
    YYYY-MM-DD/
      agents.{json,csv}
      incident_reports.{json,csv}
      signals.json
      external_ports.json
      identities.json
      reports.json
      license_line_items.json
      pull_summary.json
```text

`02_Invoices/` ... `06_Scripts/` are filled in by hand or by per-client
`_pull-*.py` scripts during an annual review. The `data/` folder is
written by `scripts/clientportal/pull_all_active.py`. The `monthly/` and
`huntress/` folders are written by the scheduled skills.

### 7.2 Pattern B — Active-but-not-yet-reviewed client

Most of the 70 clients have only `data/`, `monthly/`, `huntress/` (no
hand-curated `<YYYY>/` folder yet). When the annual review for that client
runs, the year folder is created.

### 7.3 Cross-pipeline data flow

```
              ┌──────────────────────────────┐
              │      Client Portal API       │
              └───────────────┬──────────────┘
                              │
      ┌───────────────────────┼─────────────────────────────────┐
      │                       │                                 │
      ▼                       ▼                                 ▼
 pull_all_active           monthly-pull                    weekly-audit
 (cumulative)              (prior month)                   (last 7 days)
      │                       │                                 │
      ▼                       ▼                                 ▼
clients/<code>/         clients/<code>/                 technijian/
  data/                   monthly/                       weekly-audit/
                          YYYY-MM/                       <cycle>/
                                                           ├─ raw/ (gitignored)
                                                           ├─ by-client/
                                                           └─ by-tech/<slug>/
                                                                ├─ Word doc
                                                                ├─ flagged CSV
                                                                └─ M365 Graph email

                                  ┌─────────────────────┐
                                  │   Huntress v1 API   │
                                  └──────────┬──────────┘
                                             │
                                       huntress-pull
                                       (last 24h)
                                             │
                                             ▼
                                    clients/<code>/
                                      huntress/YYYY-MM-DD/
```text

The annual-review pipeline (`technijian/tech-training/`) draws from
`clients/<code>/data/` and `clients/<code>/<YYYY>/03_Accounting/time-entries.csv`
to produce its outputs.

---

## 8. Annual review pipeline (existing)

Lives at [`technijian/tech-training/`](technijian/tech-training/). Outputs
under `technijian/tech-training/<YEAR>/`:

```
technijian/tech-training/<YEAR>/
  SUMMARY.md                       cross-client rollup
  all-flagged-entries.csv          master CSV
  by-client/<client>/
    *.docx + *.xlsx                branded annual deliverables
    tech-outliers-summary.md
  by-tech/<slug>/
    training.md
    flagged-entries.csv
    <slug>-Training.docx
```text

### 8.1 Scripts in `technijian/tech-training/scripts/`

| Script | Purpose |
|---|---|
| `_audit-all-clients.py` | scans every client + flags + per-client/per-tech artifacts |
| `_flag-outliers.py` | client-scoped flag pass (older / single-client variant) |
| `_build-docx-report.py` | branded Technijian Word builder |
| `_build-xlsx-report.py` | per-client XLSX |
| `_build-all-reports.py` | wraps the above for all clients |
| `_coaching.py` | `build_coaching(title, category, hours)` — rewrite suggestions |
| `_resolve-tech-emails.py` | tech-name → email resolver via Graph mail history |
| `_create-outlook-drafts.py` | branded HTML email drafts via Graph |
| `_send-drafts.py` | sends the manifest of drafts |
| `_check-bounces.py` | post-send bounce triage |
| `_fetch-signature.py` / `_dump-sent-html.py` | extract signature from Sent Items |
| `_secrets.py` | M365 credential resolver |
| `_draft-tech-emails.py` | (.eml local-file variant of draft creation) |
| `tech-emails.json` | directory cache (slug → email) |
| `signature.html` / `signature.txt` | RJain's email signature (extracted) |

These modules are the **reusable infrastructure** that every other skill
in this repo imports rather than duplicates. See `memory/reference_techtraining_reusable_modules.md`.

### 8.2 Status

The annual pipeline is **driven manually** today — no scheduled task. It's
run when an annual review is being prepared for a specific client or set of
clients. The 2026 cycle has been run; results are committed under
`technijian/tech-training/2026/`. Future cycles will use the same pattern.

---

## 9. Schedules + workstation

### 9.1 Production schedules

| Task name | Cron | Command | Skill |
|---|---|---|---|
| `Technijian-DailyHuntressPull` | daily 01:00 PT | `technijian\huntress-pull\run-daily-huntress.cmd` | huntress-daily-pull |
| `Technijian-MonthlyClientPull` | 1st of month 07:00 PT | `technijian\monthly-pull\run-monthly-pull.cmd` | monthly-client-pull |
| `Technijian Weekly Time-Entry Audit` | Friday 07:00 PT | `technijian\weekly-audit\run_weekly.bat` | weekly-time-audit |

### 9.2 Why staggered cadence

- **01:00 PT Huntress** — after Huntress's nightly summary report
  generation finishes; gives the dataset 24 stable hours; doesn't contend
  with the 07:00 PT jobs.
- **07:00 PT Monthly** (only 1st of month) — pulls the entire prior month;
  fires before any business activity creates entries that would stretch
  the window.
- **07:00 PT Weekly** (only Fridays) — runs before the Friday-evening
  in-contract invoice run, so techs have the same business day to fix
  flagged entries before clients see them.

### 9.3 Dev box vs production

**Never install the Windows Scheduled Task on the development laptop.**
Production schedules live on a dedicated workstation. The dev box is for
authoring scripts and committing changes only. See
`memory/feedback_no_dev_box_schedules.md`.

### 9.4 Workstation setup docs (consolidated)

All workstation setup lives in a single top-level [`workstation.md`](workstation.md)
with per-skill subsections covering the monthly pull, Huntress, CrowdStrike,
Teramind, ScreenConnect, Meraki, Umbrella, Sophos, and the weekly time-entry
audit. Per-pipeline `workstation.md` files were merged into the root on
2026-04-30.

---

## 10. Credentials

Three credential bundles, all defaulting to OneDrive-synced markdown
keyfiles for the rjain user, with env-var overrides for headless setups.

| Bundle | Env vars | Keyfile | Used by |
|---|---|---|---|
| Client Portal | `CP_USERNAME` / `CP_PASSWORD` | `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\client-portal.md` | every CP-touching skill |
| M365 Graph | `M365_TENANT_ID` / `M365_CLIENT_ID` / `M365_CLIENT_SECRET` (+ `M365_MAILBOX`) | `keys/m365-graph.md` | weekly-audit + annual email steps |
| Huntress | `HUNTRESS_API_KEY` / `HUNTRESS_API_SECRET` | `keys/huntress.md` | huntress-daily-pull |

The Huntress keyfile ships with a `TODO_PASTE_SECRET_HERE` placeholder —
the script raises a readable `RuntimeError` until the real secret is
pasted (Huntress shows the secret exactly once at key-pair creation).

The CP service-account user must have the `clients:read` token role and
permission to read time entries across all active clients (existing
reporting role suffices). The M365 app registration must have
`Mail.Read` + `Mail.Send` + `Mail.ReadWrite` application permissions with
admin consent.

---

## 11. Outputs: committed vs gitignored

### 11.1 Committed (kept in git history)

```
clients/<code>/<YYYY>/**                       annual review materials (manually curated)
clients/<code>/data/{summary,csv,json}         cumulative pull (small JSON/CSV)
clients/<code>/monthly/<YYYY-MM>/**            monthly-pull outputs
clients/<code>/huntress/<YYYY-MM-DD>/**        huntress daily outputs
technijian/tech-training/<YEAR>/**             annual audit reports + per-tech docs
technijian/weekly-audit/<YYYY-WWnn>/SUMMARY.md, all-flagged-entries.csv,
                                  audit_log.json, run_log.json,
                                  by-client/, by-tech/<slug>/{training.md, flagged-entries.csv,
                                  *-Weekly-Training.docx, outlook-drafts-*.csv}
technijian/weekly-audit/by-tech/<slug>/history.csv  rolling per-tech flag history
technijian/monthly-pull/state/<YYYY-MM>.json
technijian/huntress-pull/<YYYY-MM-DD>/{account,organizations,mapping,unmapped,
                                       reseller_subscriptions,latest_invoice,run_log}.json
technijian/contacts/{COVERAGE.md,                       contacts coverage report
                     active_client_contacts.csv,         flat per-recipient CSV
                     active_client_recipients.csv,       per-client send-to list
                     missing_legal.csv,                  active CP clients with no tech-legal file
                     no_designated_recipient.csv,        files exist but no recipient set
                     stale_legal.csv}                    tech-legal entries with no active CP match
```text

### 11.2 Gitignored (reproducible / local-only)

```
__pycache__/, *.py[cod], *.egg-info/, .venv/, venv/, .env*
**/_sent-samples-raw.html, **/signature-source.md   (raw email scrapes — never commit)
technijian/weekly-audit/*/raw/                       large per-cycle XML/CSV from API
technijian/weekly-audit/state/                       runtime state JSON
technijian/huntress-pull/state/*.log                 daily run-log files
technijian/huntress-pull/state/[0-9]*.json           daily run state
```text

---

## 12. Memory + vault integration

### 12.1 Project memory

Path: `~/.claude/projects/c--vscode-annual-client-review-annual-client-review/memory/`

| File | Type | Purpose |
|---|---|---|
| `MEMORY.md` | index | one-line pointer to each entry; auto-loaded into Claude context |
| `project_weekly_audit_cadence.md` | project | Friday 07:00 PT, recommend-only, no enforcement loop |
| `project_monthly_pull_skill.md` | project | 1st of month 07:00 PT cadence + scope |
| `project_huntress_daily_pull.md` | project | daily 01:00 PT cadence + read-only constraint + SAT gap |
| `feedback_recommend_only_for_destructive.md` | feedback | for pay/invoice/shared-data automations, build report-only first |
| `feedback_no_dev_box_schedules.md` | feedback | never run `Register-ScheduledTask` on the dev box |
| `reference_cp_api_invdetid.md` | reference | InvDetID is the stable per-entry ID |
| `reference_techtraining_reusable_modules.md` | reference | what's reusable under tech-training/scripts |

### 12.2 Obsidian vault

Path: `C:\Users\rjain\OneDrive - Technijian, Inc\Documents\obsidian\annual-client-review\`

```
Knowledge/
  weekly-time-audit-skill.md
  monthly-client-pull-skill.md
  huntress-daily-pull-skill.md
  recommend-only-pattern.md
  no-dev-box-schedules.md
  cp-api-invdetid.md
  tech-training-reusable-modules.md
conversation-log/
  YYYY-MM-DD.md                       auto-mirrored verbatim chat log
```text

The vault is mapped via `~/.claude/obsidian-vault-map.json`:

```json
"c:/vscode/annual-client-review": "C:/Users/rjain/OneDrive - Technijian, Inc/Documents/obsidian/annual-client-review"
```

The `log-turn.js` hook auto-appends every prompt + response to both the
primary log (`~/.claude/projects/<slug>/conversation-log/`) and the vault
mirror. Curated knowledge pages under `Knowledge/` are written by hand and
should be updated when a skill changes.

---

## 13. Known gaps and future work

### 13.1 Workstation setup is fragmented

Three different `workstation.md` files exist (Section 9.4). Consolidating
into a single top-level `workstation.md` with sections per skill (or per
skill with cross-references from a top-level index) would make new-machine
provisioning a single read-through.

### 13.2 Huntress SAT data is not captured

Huntress Managed Security Awareness Training has no v1 API. SAT exports
(learners, assignments, courses, completions, phishing campaigns) are
manual. When endpoints ship, extend `huntress_api.py` and add per-client
SAT outputs.

### 13.3 Weekly audit is recommend-only

The original spec was auto-deletion of unadjusted entries after a 48-hour
window. Pivoted to recommend-only because:

- False-positive auto-delete = tech loses pay irreversibly.
- Friday-evening invoice run is an existing business rhythm; adding a
  second deadline (48h timer) creates a parallel accountability path.

The future-delete spec is preserved at
`technijian/weekly-audit/API-DELETE-ENDPOINT-SPEC.md` (soft-delete column,
SP signatures, audit table, REST URL, Python helpers, deployment
checklist). Do not wire it without explicit re-approval.

### 13.4 Monthly pattern report

The rolling `technijian/weekly-audit/by-tech/<slug>/history.csv` is the
seed for a future `5_pattern_report.py` that emails team leads a monthly
per-tech pattern summary (top categories flagged, repeat offenders,
trend). Out of scope for v1.

### 13.5 Annual pipeline isn't scheduled

The annual review (`technijian/tech-training/`) is driven manually per
client. Could be wrapped into a yearly scheduled job once the cycle's
inputs and human-review steps are codified, but that's a 2027+ concern.

### 13.6 Huntress account-level state directory exists

`technijian/huntress-pull/state/` is created by the worker but the
account-level `<YYYY-MM-DD>/` directory is the canonical run log location.
Daily `state/<date>.json` files are gitignored to avoid log noise; the
account-level run log is committed.

### 13.7 Huntress v1 captures agents only

By design — incident reports, signals, external ports, M365 ITDR
identities, reports, and reseller license line items are out of scope in
v1. When a downstream consumer (monthly activity report, daily license
rollup, SOC reporting) actually needs that data, extend `pull_org()` in
`pull_huntress_daily.py` to call the corresponding helpers in
`huntress_api.py` and write the additional per-client files. Until then
the daily pull is fast and the disk footprint stays small.

### 13.8 70 clients but only some have annual-review folders

The other ~60 clients have monthly + huntress + cumulative-data folders
populated automatically, but no curated `<YYYY>/` annual-review materials.
That's expected — annual reviews are produced on demand per client; the
monthly + huntress + audit pipelines run for all 70.

---

## 14. How to invoke (cheat sheet)

```cmd
cd /d c:\vscode\annual-client-review\annual-client-review

REM ── Weekly time-entry audit (recommend-only) ─────────────────────
python technijian\weekly-audit\scripts\run_weekly.py
python technijian\weekly-audit\scripts\run_weekly.py --drafts-only
python technijian\weekly-audit\scripts\4_email_weekly.py --send-existing
python technijian\weekly-audit\scripts\run_weekly.py --cycle 2026-W17

REM ── Monthly client pull ──────────────────────────────────────────
python technijian\monthly-pull\scripts\pull_monthly.py
python technijian\monthly-pull\scripts\pull_monthly.py --month 2026-04
python technijian\monthly-pull\scripts\pull_monthly.py --only AAVA,BWH
python technijian\monthly-pull\scripts\pull_monthly.py --dry-run

REM ── Huntress daily pull ──────────────────────────────────────────
python technijian\huntress-pull\scripts\pull_huntress_daily.py
python technijian\huntress-pull\scripts\pull_huntress_daily.py --map-only
python technijian\huntress-pull\scripts\pull_huntress_daily.py --hours 72
python technijian\huntress-pull\scripts\pull_huntress_daily.py --only AAVA

REM ── Annual cross-client audit (manual cadence) ───────────────────
python technijian\tech-training\scripts\_audit-all-clients.py 2026
python technijian\tech-training\scripts\_build-all-reports.py 2026
python technijian\tech-training\scripts\_resolve-tech-emails.py 2026 --refresh
python technijian\tech-training\scripts\_create-outlook-drafts.py 2026
python technijian\tech-training\scripts\_send-drafts.py 2026

REM ── Cumulative full-history pull (overwrites clients/<code>/data/) ─
python scripts\clientportal\pull_all_active.py
python scripts\clientportal\pull_all_active.py --only BWH
```text

---

## 15. Conventions

- **Python only**, standard library where possible (`urllib`, `xml.etree`,
  `csv`, `json`, `pathlib`, `datetime`, `zoneinfo`). The annual pipeline +
  weekly Word builder require `python-docx`; everything else is stdlib.
- **No service code, no controllers, no DI containers.** Every pipeline is
  a script with `argparse` and a `main()`.
- **Cycle / window naming:** ISO week (`YYYY-WWnn`) for weekly, calendar
  month (`YYYY-MM`) for monthly, calendar date (`YYYY-MM-DD`) for daily.
  Pacific time for derivation.
- **Per-client folders are the unit of organization** — `clients/<code>/`
  is git-diffable in isolation; pipelines append never overwrite each
  other's subdirectories.
- **Branded Word doc styling lives in
  `technijian/tech-training/scripts/_build-docx-report.py`** and is reused
  by the weekly skill via copy-of-helpers in
  `technijian/weekly-audit/scripts/3_build_weekly_docs.py`. Brand colors:
  `#006DB6` blue, `#F67D4B` orange, `#1A1A2E` dark, `#1EAAC8` teal.
  Body font: Open Sans 11pt #59595B.
- **Drafts are reviewed before send.** The weekly skill supports
  `--drafts-only` so a human can spot-check via Outlook on
  `RJain@technijian.com` before the send pass runs. The default
  `run_weekly.py` does both in one go on the schedule.
- **Reruns are idempotent.** Per-client snapshot folders and per-cycle
  audit folders can be overwritten without affecting any other cycle's
  output.

---

*Last updated 2026-04-29 by Claude (Opus 4.7). When you ship a new pipeline
or change a cadence, update this file and bump the date.*
