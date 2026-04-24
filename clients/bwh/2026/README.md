# BWH (Brandywine Homes) — 2026 Annual Review

**Client:** Brandywine Homes
**DirID:** 6245
**Contract ID:** 4924 (IT Services Proposal, Monthly Service)
**Contract Period:** 2023-05-02 → 2026-01-29 (active)
**Data Pulled:** 2026-04-24
**Total Hours Delivered (life of contract):** 4,050.10

Path: `clients/bwh/2026/`

---

## Folder structure

| Folder | What's in it |
|---|---|
| [02_Invoices](02_Invoices/) | 149 weekly invoice ledger (CSV + XML), parsed monthly invoice email bodies |
| [03_Accounting](03_Accounting/) | All CSV aggregations, master XLSX, accounting markdown analyses |
| [04_Raw_Data](04_Raw_Data/) | Raw XML pulled from client portal (time entries, tickets, invoice details) |
| [05_Reports](05_Reports/) | Client-facing deliverables (DOCX + MD) |
| [06_Scripts](06_Scripts/) | Python scripts that produced everything in 03_Accounting |

**Note:** Legal documents (MSA, Schedule A/B/C, contract, contacts) live in the tech-legal repo at `C:\VSCode\tech-legal\tech-legal\clients\BWH\` and are not duplicated here.

---

## Documents to read

| Document | Audience | Purpose |
|---|---|---|
| [05_Reports/BWH-Hours-Savings-Analysis.docx](05_Reports/BWH-Hours-Savings-Analysis.docx) | **Dave / BWH** | Branded client-facing report — 4,050 hours explained + $88,251 savings story |
| [03_Accounting/GLOBAL-REVIEW.md](03_Accounting/GLOBAL-REVIEW.md) | Internal | Full analytical narrative, including data caveats and recommendations |
| [03_Accounting/ACCOUNTING.md](03_Accounting/ACCOUNTING.md) | Internal | Original hours reconciliation (4/1 vs 4/24 figures, overage math) |
| [03_Accounting/tech-outliers-summary.md](03_Accounting/tech-outliers-summary.md) | **Tech training** | 105 flagged time entries (190 hrs, 4.7%) — trivial work with excessive hours, vague titles, same-day duplicates, ranked by tech |

---

## Headline numbers

| Metric | Value |
|---|---:|
| Total delivered hours (36 months) | 4,050.10 |
| Total weekly invoices sent (all Paid) | 149 |
| Contract over-contract / proposal rate | $150.00 /hr |
| **Project-style hours absorbed into monthly support** | **588.34** |
| **Proposal billing BWH avoided at $150/hr** | **$88,251.00** |
| — of which India-pod delivered | 435.39 hrs / $65,309 |
| — of which USA-pod delivered | 152.95 hrs / $22,943 |
| Routine monthly-support hours (correctly in scope) | ~2,466 (60.9%) |
| Short ad-hoc / uncategorized tickets | ~996 (24.6%) |

---

## Project-type deliverables identified (billed under monthly support)

| Project | Hours | Proposal value at $150/hr |
|---|---:|---:|
| NewStar ERP upgrades and support | 188.26 | $28,239 |
| RMM / tooling install on new machines | 103.37 | $15,506 |
| Server / VM / ESXi / VMware upgrades | 87.55 | $13,133 |
| Windows 11 / PC refresh / laptop deploy | 65.95 | $9,893 |
| OneDrive / SharePoint data migration | 65.49 | $9,824 |
| Backup / Veeam / Replication projects | 33.39 | $5,009 |
| Firewall / VPN / Network buildout | 18.83 | $2,825 |
| File server / data migration | 13.50 | $2,025 |
| Security / EDR / SSL / MFA rollouts | 12.00 | $1,800 |
| **TOTAL** | **588.34** | **$88,251** |

Complete ticket-level backup: [03_Accounting/project-candidate-tickets.csv](03_Accounting/project-candidate-tickets.csv) (588 rows, dated, with requestor/role/hours).

---

## Data artifacts — quick reference

### Source-of-truth CSVs (in [03_Accounting](03_Accounting/))

| File | Rows | Description |
|---|---:|---|
| `time-entries.csv` | 93,582 | Every time-entry block logged against BWH (atomic grain) |
| `ticket-by-ticket.csv` | 25,654 | One row per (Date × Ticket × Role × POD × Shift) |
| `monthly-summary.csv` | 129 | Month × POD × Role × Shift × Invoice-Description pivot |
| `hours-by-month.csv` | 36 | Wide: months × 4 role buckets |
| `hours-cumulative.csv` | 36 | Same, with running totals |
| `work-categories-summary.csv` | 33 | Category × Hours × % × unique ticket count |
| `work-categories-by-month.csv` | 36 | Month × 32 work-category columns |
| `work-categories-by-role.csv` | 33 | Category × India NH / India AH / USA NH / USA AH |
| `project-candidate-tickets.csv` | 588 | Every project-classified ticket enumerated |
| `savings-per-project.csv` | 10 | Per-project hours × $150 savings table |

### Invoice artifacts (in [02_Invoices](02_Invoices/))

- `invoices.csv` — 149 weekly invoice ledger (all Paid)
- `invoices-weekly-list.xml` — raw portal XML
- `monthly-invoice-emails/` — parsed bodies + attachments of Tharunaa's monthly invoice review emails

### Raw portal data ([04_Raw_Data](04_Raw_Data/))

- `time-entries-raw/` — 40 monthly XML files from `stp_xml_TktEntry_List_Get`
- `tickets-raw/` — 40 monthly XML files with ticket titles/requestors/status
- `invoice-details-raw/` — 149 per-invoice detail XML files from portal SP

### Scripts ([06_Scripts](06_Scripts/))

| Script | What it does |
|---|---|
| `_pull-bwh-data.py` | Pulls time entries + tickets from client portal stored procedures |
| `_pull-invoices.py` | Pulls weekly invoice list + per-invoice detail XML |
| `_build-master-xlsx.py` | Builds `BWH-Hours-Accounting-Life-of-Contract.xlsx` from CSVs |
| `_build-reconciliation.py` | Reconciles 4/1 vs 4/24 hour-balance figures |
| `_categorize-work.py` | Classifies all 25,654 ticket rows by work theme |
| `_project-timeline.py` | Month-by-month project-hour timeline analysis |
| `_dump-uncat.py` | Debug helper for categorization refinement |
| `_savings-analysis.py` | Computes per-project $150/hr proposal savings |
| `_parse-eml.py` | Parses monthly invoice emails (source .eml in tech-legal/05_Invoices) |
| `_build-word-report.py` | Builds the branded Word report for Dave |

All scripts use repo-relative paths — `ROOT = Path(__file__).resolve().parent.parent` resolves to `clients/bwh/2026/`.

---

## Key caveats

1. **All 149 portal invoices are type "Weekly Invoice"** — zero separate project/SOW invoices exist there. Monthly/recurring QuickBooks invoices (#28148, #28116) live outside the portal SP set; source .eml + PDFs remain in `tech-legal/clients/BWH/05_Invoices/`.
2. **Systems Architect: 0 hours** across 36 months. If architect hours were contractually allocated but never delivered, that arguably offsets a portion of the support overage.
3. **Oct/Nov 2025 India NH: 0 hrs** — anomalous vs. ~45–60 typical. Likely a data-capture gap (POD coding migration) rather than actual zero delivery. Confirm with Tharunaa.

---

## How to regenerate everything

```bash
cd 06_Scripts
python _pull-bwh-data.py         # refreshes 04_Raw_Data/time-entries-raw, tickets-raw + time-entries.csv + monthly-summary.csv
python _pull-invoices.py         # refreshes 04_Raw_Data/invoice-details-raw + invoices.csv
python _categorize-work.py       # refreshes work-categories-*.csv + project-candidate-tickets.csv
python _project-timeline.py      # prints project-hour timeline
python _savings-analysis.py      # refreshes savings-per-project.csv
python _build-master-xlsx.py     # rebuilds the master XLSX
python _build-word-report.py     # rebuilds the client-facing Word doc
```

The two `_pull-*.py` scripts depend on the client-portal API at `C:\VSCode\tech-legal\tech-legal\.codex\skills\client-portal-core\scripts\client_portal_api.py` (platform dependency, not in this repo). All other scripts run self-contained.

---

*Prepared for Technijian internal use and BWH 2026 annual client review. Confidential.*
