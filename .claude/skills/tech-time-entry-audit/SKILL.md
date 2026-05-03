---
name: tech-time-entry-audit
description: Audits time entries against reasonable-hours caps per work category and flags outliers for tech training. Generates branded Excel + Word reports per client and personalized training documents per tech. Trigger when user asks to "flag outliers in time entries", "tech training analysis", "audit time entries for <client>", "find unreasonable time entries", or "analyze techs' time entries".
---

# Tech Time-Entry Audit

## Overview

Reviews all time entries logged against one or more clients and flags those where the hours claimed appear outside a reasonable range given the work described. Designed to surface training opportunities — not to imply fraud — by highlighting patterns like:

- Routine alerts (CPU, patch, agent update) logged at 2+ hours when they should resolve in <1 hour
- Vague titles like "Help", "Fix", "Test" on any entry > 0.5 hour
- Whole-day dumps into a single time block (> 8 hours)
- Tech daily totals > 12 hours (cross-ticket over-claim)
- Same tech + ticket + day with multiple entries stacking to > 2× category cap

## Flag codes

| Code | Rule |
|---|---|
| H1 | Routine/low-complexity title with hours > category cap |
| H2 | Generic/vague title with > 0.5 hour |
| H3 | Single entry > 8 hours |
| H4 | One tech's day total > 12 hours |
| H5 | Same tech + same ticket + same day, entries summing > 2× cap |

## When to use

- User asks for tech-training analysis of time entries
- User wants to flag unreasonable time entries by description vs. hours
- User wants per-tech or per-client training reports
- User mentions "outlier analysis", "time entry quality", or "audit techs"

## Prerequisites

The target repo must contain a time-entries CSV at one of these paths per client:

- `clients/<code>/<year>/03_Accounting/time-entries.csv` (canonical year-folder layout)
- `clients/<code>/data/time_entries.csv` (generic portal-pull layout)

Required columns (either name works):

- `TimeEntryDate` / `Date`
- `Title`
- `AssignedName` / `Resource` (the tech)
- `Qty` / `Hours` / `AH_HoursWorked`+`NH_HoursWorked` / `TimeDiff` — hours

## Outputs

Creates a folder hierarchy rooted at `technijian/tech-training/<year>/`:

```
technijian/tech-training/<year>/
  SUMMARY.md                           ← cross-client rollup
  all-flagged-entries.csv              ← master CSV (every flagged row)
  by-client/<client>/
    tech-outliers-summary.md
    tech-outliers-by-tech.csv
    tech-outliers-detail.csv
    <CLIENT>-Tech-Time-Entry-Audit.xlsx   ← branded Excel
    <CLIENT>-Tech-Time-Entry-Audit.docx   ← branded Word report
  by-tech/<tech-slug>/
    training.md
    flagged-entries.csv
    <tech-slug>-Training.docx             ← personalized training doc
```

## Scripts

The reference implementation lives in the `annual-client-review` repo at
`technijian/tech-training/scripts/`:

| Script | Purpose |
|---|---|
| `_flag-outliers.py` | Single-client audit. Usage: `python _flag-outliers.py <client> <year>` |
| `_audit-all-clients.py` | All-clients audit. Writes per-client + per-tech CSVs and markdown. Usage: `python _audit-all-clients.py <year>` |
| `_build-xlsx-report.py` | Single-client branded Excel. Usage: `python _build-xlsx-report.py <client> <year>` |
| `_build-docx-report.py` | Single-client branded Word. Usage: `python _build-docx-report.py <client> <year>` |
| `_build-all-reports.py` | Batch-build Excel + Word for every client, plus per-tech training docs. Usage: `python _build-all-reports.py <year>` |

## Category caps

Each work category has a single-entry cap (hours) above which an H1 flag is raised. Edit `CATEGORY_CAP` dict in `_audit-all-clients.py` or `_flag-outliers.py` to tighten/loosen.

### Routine (tight caps)
| Category | Cap (hrs) |
|---|---:|
| Monitoring alerts (CPU / memory / disk / device down) | 0.75 |
| User login / password / lockout | 1.0 |
| ScreenConnect / MyRemote updates | 1.0 |
| Admin / meetings / approvals | 1.0 |
| Patch management | 1.5 |
| CrowdStrike / EDR / MyRMM / ManageEngine agent updates | 1.5 |
| Antivirus / Malware scan | 1.5 |
| Email / Outlook / spam | 1.5 |
| File access / Shared drive / permissions | 1.5 |
| Printer / Scanner | 1.5 |
| Phone / Voice / Teams | 1.5 |
| VPN troubleshoot | 1.5 |
| Generic help / support | 1.5 |
| Backup job / Veeam alert | 1.5 |
| Network / Internet / Wi-Fi | 2.0 |
| Weekly Maintenance Window | 2.0 |
| Hardware troubleshoot | 2.5 |
| Server/DC issue | 3.0 |
| Individual user / PC / laptop (named) | 3.0 |
| Onboarding / Offboarding | 3.0 |

### Project (looser caps)
| Category | Cap (hrs) |
|---|---:|
| RMM / tooling install | 3.0 |
| Security / EDR / SSL rollout | 3.0 |
| ERP / app upgrade | 4.0 |
| Server / VM / ESXi upgrade or rebuild | 4.0 |
| Windows refresh / PC deploy | 4.0 |
| OneDrive / SharePoint data migration | 4.0 |
| Backup / Veeam / Replication (setup) | 4.0 |
| Firewall / VPN / Network buildout | 4.0 |
| File server / data migration | 4.0 |
| M365 / Exchange / Intune / Entra | 4.0 |

**Fallback:** 2.5 hrs for uncategorized entries.

## Branding

Reports follow the Technijian Brand Guide 2026:

- Logo: `C:\VSCode\tech-branding\tech-branding\assets\logos\png\technijian-logo-full-color-600x125.png`
- Colors: Core Blue `#006DB6`, Core Orange `#F67D4B`, Teal `#1EAAC8`, Dark Charcoal `#1A1A2E`, Brand Grey `#59595B`, Off White `#F8F9FA`
- Font: Open Sans
- Hours over cap are colored orange; hours > 1.5× cap are colored red

## Python dependencies

- `openpyxl` (Excel)
- `python-docx` (Word)

Both already installed in the default environment.

## Typical workflow

1. Ensure client data exists at one of the supported paths.
2. `python _audit-all-clients.py 2026` — generates CSVs and markdown for all clients + per-tech aggregates.
3. `python _build-all-reports.py 2026` — generates branded XLSX per client, DOCX per client, and personalized Training.docx per tech.
4. Review `technijian/tech-training/2026/SUMMARY.md` for the overall picture.
5. For coaching: open the per-tech `Training.docx` with that tech and walk through their personal data.

## Design principles

- **Client-agnostic classifier.** The `CATEGORIES` regex list matches routine MSP work and generic project keywords. BWH-specific patterns (NewStar, Brandywine-only hostnames) are not hard-coded.
- **Everything traces back to a specific time-entry row.** Every flagged hour is enumerated in `tech-outliers-detail.csv` with date, tech, title, flags, and reasons — no aggregate claims.
- **Personalized, not punitive.** The per-tech Training.docx leads with the tech's own data and offers concrete, rewrite-level advice on their top flag type.
- **Reproducible.** The full pipeline re-runs cleanly from the scripts folder with no hidden state.

## Known limitations

1. **English-only classifier.** Non-English titles will land in Uncategorized and only trigger H2/H3/H4/H5.
2. **Shared-window hours are not split automatically.** If "Weekly Maintenance Window" is logged wholesale to one client, the audit flags the hours but does not redistribute them.
3. **No lookup of ticket status.** An entry at 3 hours on a complex ticket may be fine if the ticket was a P1 incident; the audit doesn't read priority/severity, only title + hours.
4. **Threshold tuning.** Caps are opinionated defaults. Tighten or loosen per team's expectations before drawing conclusions.

## Triggers

Use this skill when the user says things like:

- "Flag outliers in the time entries"
- "Run a tech training analysis"
- "Audit techs' time entries for [client/year]"
- "Find unreasonable time entries"
- "Which techs are over-claiming hours"
- "Per-tech training folders"
- "Cross-client time-entry review"

<!-- ticket-management-note: cp-ticket-management -->

## Ticket management

If this skill ever needs to open a CP ticket for an issue it detects
(capacity warning, threshold breach, persistent failure), use the
tracked wrapper from the **cp-ticket-management** skill —
`cp_tickets.create_ticket_for_code_tracked(...)` in
`scripts/clientportal/cp_tickets.py`. The central state file at
`state/cp_tickets.json` deduplicates on `issue_key`
(convention: `<source-skill>:<issue-type>:<resource-id>`) and
`scripts/clientportal/ticket_monitor.py check` (daily 06:00 PT on the
production workstation) sends 24h reminder emails to
support@technijian.com for any open ticket. **Don't call
`cp_tickets.create_ticket(...)` directly** — the raw call bypasses
state and reminders.
