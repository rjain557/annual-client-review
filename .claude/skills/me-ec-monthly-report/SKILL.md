---
name: me-ec-monthly-report
description: "Use when the user asks to build, generate, or refresh monthly ManageEngine Endpoint Central patch activity reports — branded Word docs summarizing each client's patch deployment window, patches installed, success/failure rates, severity distribution, and per-machine patch detail. One Word doc per client per month, sourced live from the EC SQL backend at TE-DC-MYRMM-SQL. Wired with the proofread-report gate. Examples: \"generate ME EC monthly report for AAVA March 2026\", \"build Q1 2026 ME EC patch reports for all clients\", \"refresh ME EC monthly reports\", \"patch activity report for ORX last month\"."
---

# ME EC Monthly Patch Activity Report

Builds branded Word reports summarizing each MSP customer's Endpoint
Central patch activity for a calendar month. Reads live from the EC SQL
backend (`desktopcentral` database on TE-DC-MYRMM-SQL / 10.100.13.11)
via `me_ec_sql.py`. Wired with the proofreader at `proofread-report` so
a defective report fails the build instead of shipping.

## Prerequisites

1. **SQL backend reachable** with `pymssql` NTLM auth — see the
   `me-ec-pull` skill and `keys/myrmm-sql.md` for the credential setup.
2. **`python-docx`** must be installed (`pip install python-docx`).
3. **Brand helpers** at `technijian/shared/scripts/_brand.py` (already
   in the repo).

The report builder hits the SQL backend directly, so unlike the Meraki
monthly report there is **no separate aggregator step** — generation
and aggregation happen in one pass.

## Generate

```bash
cd c:/VSCode/annual-client-review/annual-client-review-1/scripts/me_ec

python generate_monthly_docx.py --month 2026-01            # one month, all clients
python generate_monthly_docx.py --from 2026-01 --to 2026-04  # range
python generate_monthly_docx.py --month 2026-03 --only AAVA,BWH
python generate_monthly_docx.py --month 2026-04 --skip RAVI-HOME
```

`generate_monthly_docx.py` invokes the proofreader on every doc it
produces and exits non-zero if any report fails. **Do not bypass with
`--no-proofread`** for delivery — that flag is debug-only.

## Output

```
clients/<slug>/me_ec/reports/<NAME> - ME EC Patch Activity - <YYYY-MM>.docx
```

## Sections in the report

1. **Executive Summary** — KPI strip: patches installed, succeeded,
   errored, machines patched. Plus a sentence-level summary for the
   month with success rate and a callout if zero installs.
2. **Patch Window** — the client's Automated Patch Deployment (APD)
   tasks: name, status (RUNNING / SUSPENDED), template, time window,
   day-of-week, week-of-month. Red callout if no APD task is
   configured (4 customers as of 2026-05-03: AFFG, EBRMD, KES, RMG).
3. **Per-Machine Summary** — one row per endpoint with total installed,
   succeeded, errored, status (Pass / Errored).
4. **Severity Breakdown** — Critical / Important / Moderate / Low
   counts and percentages.
5. **Vendor Breakdown** — Microsoft / Adobe / etc. patch counts.
6. **Patches Installed** — top 25 unique patches by endpoint count
   (truncated for very large months; full data is in the SQL view).
7. **Failed Installs** — every install with `ERROR_CODE > 0` this
   month, with machine, patch, severity, error code, time. Green
   callout if no failures.
8. **About This Report** — provenance + contact note.

## Proofreader expected sections (EXPECTED_SECTIONS)

The proofread gate checks for these 8 section headers (case-insensitive,
searched across all text including table cells):

```
Executive Summary
Patch Window
Per-Machine Summary
Severity Breakdown
Vendor Breakdown
Patches Installed
Failed Installs
About This Report
```

124/124 reports (Jan–Apr 2026, 31 customers — RAVI-HOME excluded) pass
8/8 proofread checks as of 2026-05-03.

## Customer → folder mapping

`CUSTOMER_TO_SLUG` in `generate_monthly_docx.py` maps EC's
`CustomerInfo.CUSTOMER_NAME` to the lowercase folder under `clients/`.
RAVI-HOME has no client folder and is skipped (it's a personal
endpoint, not an MSP client). ISH-KSS uses `ish-kss` even though no
folder existed before — the script creates it on first run.

## Brand styling

Uses the canonical Technijian brand helpers from
`technijian/shared/scripts/_brand.py` — Open Sans, CORE_BLUE `#006DB6`
header, CORE_ORANGE `#F67D4B` accents, alternating row fill, KPI cards.
Same look as the Meraki / Sophos / Veeam monthly reports.

## Severity / status mapping

| EC `SEVERITYID` | Label |
|---|---|
| 1 | Critical |
| 2 | Important |
| 3 | Moderate |
| 4 | Low |
| 0 / 5 / null | Unspecified |

| EC `DEPLOY_STATUS` | Outcome |
|---|---|
| 2 with `ERROR_CODE <= 0` | Succeeded |
| anything else | Failed (counted toward "errored" if `ERROR_CODE > 0`) |

## Gotchas

- **Empty months are real.** A small client (TALY, AFFG, RAVI-HOME) may
  legitimately have zero installs in a given month. The report shows
  "0 patches installed" with a yellow callout rather than omitting
  sections. The proofreader doesn't fail on legitimate zeros — only
  on missing sections / placeholders.
- **Customers without an APD task** (AFFG, EBRMD, KES, RMG today) get
  a red callout in the Patch Window section recommending an India
  ticket to configure deployment. They will still show installs if
  any patches were applied via on-demand deployments outside an APD
  schedule.
- **Customer name vs slug.** The Word doc title uses
  `CustomerInfo.CUSTOMER_NAME` (e.g. "Technijian-MSP"); the folder
  path uses the lowercase slug from `CUSTOMER_TO_SLUG` (e.g.
  `technijian`). If they diverge mid-period, update the mapping.
- **Time bounds are UTC.** Months run from the 1st 00:00 UTC to the
  1st of the next month 00:00 UTC. Cross-timezone clients may see a
  patch deployed at 23:00 PT on Jan 31 land in February's report
  because the SQL `INSTALLED_TIME` is recorded UTC.
- **Failed-installs table is capped at 50 rows.** Months with more than
  50 failures truncate with a note pointing at the full SQL view.
- **Table widths are enforced.** All tables sized to fit within 6.5"
  (US Letter, 1" margins). Proofread check #4 (`check_table_widths`)
  fails any report exceeding this.
- **Vendor names** come from EC's `Vendor.NAME` table. Patches with no
  vendor lookup show as "Unknown".

## Related skills

- `me-ec-pull` — daily SQL snapshots that feed both the per-customer
  data folders and these reports
- `proofread-report` — auto-invoked at the end of the builder; fails
  the build on missing sections, placeholders, table overflow, or
  mojibake
- `meraki-monthly-report`, `sophos-pull`, `veeam-vbr` — sister monthly
  builders following the same pattern

## Ticket management

If this skill ever needs to open a CP ticket for a detected issue
(e.g. a customer with zero APD tasks but high missing-patch count,
persistent install failures, or a SUSPENDED task with no RUNNING
replacement), use the tracked wrapper from `cp-ticket-management`
(`cp_tickets.create_ticket_for_code_tracked(...)`) so deduplication
and 24h reminders work. Don't call `create_ticket(...)` directly.
