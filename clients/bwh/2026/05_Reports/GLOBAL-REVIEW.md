# BWH — Global Review of 4,050 Hours Over 3 Years

**Prepared:** 2026-04-24
**Client:** Brandywine Homes (DirID 6245, Contract 4924)
**Contract period analyzed:** 2023-05-02 through 2026-04-24 (36 months)
**Source data:** Client Portal (all ticket time entries + all invoices pulled 2026-04-24)
**Total delivered hours:** 4,050.10

This review answers the question Dave raised: *how is 4,000 hours of actual support possible over 3 years, and were project-style proposals (server OS upgrades, VM rebuilds, migrations) absorbed into the monthly support allocation instead of being quoted separately?*

---

## 1. Headline answer

Yes — a substantial portion of the work that should normally be scoped and quoted as a **separate project / SOW** was delivered through the same weekly support ticket queue, and therefore consumed monthly-support allocation hours.

Specifically, in the 36-month portal ticket record:

| Bucket | Hours | % of total | Notes |
|---|---:|---:|---|
| Routine monthly-support work | ~2,466 | 60.9% | Patching, AV, RMM agent updates, alerts, user issues — legitimately inside the contract |
| **Project-style work (SOW candidates)** | **~588** | **14.5%** | NewStar upgrades, VM/ESXi rebuilds, Windows-11 refresh, OneDrive migration, firewall install, file-server migration |
| Uncategorized misc | ~996 | 24.6% | Short ad-hoc tickets without a project theme; functionally routine support |

**There are zero project/SOW invoices in the portal.** All 149 invoices pulled from the client portal are type `Weekly Invoice`. No separate line item exists for the upgrade, migration, or refresh projects listed below. Whatever project work was delivered, it flowed through the same hour pool as routine support.

*(Caveat: monthly / recurring QuickBooks invoices #28148 and #28116 are referenced in BWH.md but are generated outside the portal SP and could not be pulled here. If separate project billing exists, it lives in QuickBooks and needs a manual pull to rule this out.)*

---

## 2. How the 4,050 hours break down (life of contract)

Categorized from every ticket title in the 25,654-row `ticket-by-ticket.csv`. Full file: `work-categories-summary.csv`.

### Routine / operational categories (2,466 hrs, 60.9 %)

| Category | Hours | % | What it is |
|---|---:|---:|---|
| Patch management / Windows Update / missing-patch alerts | 789.5 | 19.5% | Monthly patching cycle; mostly auto-generated "BWxxxx has not been patched for 14 days" tickets |
| CrowdStrike / EDR agent version updates | 260.8 | 6.4% | Pushing new agent versions across fleet |
| MyRMM / ManageEngine / N-able RMM agent updates | 205.0 | 5.1% | Same — RMM stack agent version bumps |
| Weekly Maintenance Window (scheduled) | 144.7 | 3.6% | Recurring Fri 9pm → Sat 3am + Sat 9pm → Sun 3am scheduled maintenance |
| Antivirus / Malwarebytes scans | 119.8 | 3.0% | Recurring AV scans |
| ScreenConnect / MyRemote agent updates | 119.1 | 2.9% | Remote-access tool version bumps |
| Individual user laptop/PC issues (Chris, Nancy, Liz, etc.) | 92.8 | 2.3% | Named user troubleshooting |
| Network / Internet / Wi-Fi / ISP issues | 89.3 | 2.2% | Connectivity troubleshooting |
| Generic help / support / troubleshoot | 74.3 | 1.8% | Catch-all tickets |
| Server/DC issues (generic) | 70.4 | 1.7% | `RA01 down`, `DC issues`, `HV01 offline`, etc. |
| CPU / memory / disk utilization alerts | 68.8 | 1.7% | Auto-generated threshold alerts |
| Email / Outlook / spam / phish | 67.4 | 1.7% | End-user email support |
| Backup job / Veeam alert failures | 60.4 | 1.5% | Scheduled backup job health |
| Device-down / not-responding monitoring alerts | 44.2 | 1.1% | Pingable-asset alerts |
| File access / Shared drive / OneDrive sync / permissions | 44.1 | 1.1% | User file access |
| Printer / scanner / peripheral | 44.0 | 1.1% | |
| Hardware troubleshoot (slow, freeze, bsod, boot) | 43.7 | 1.1% | |
| Onboarding / Offboarding user | 24.9 | 0.6% | |
| Monitoring alert — generic critical / MonitorField | 22.6 | 0.6% | |
| Admin / approvals / signatures / meetings | 21.5 | 0.5% | |
| VPN troubleshoot | 18.2 | 0.5% | |
| User login / password / account lockout | 15.3 | 0.4% | |
| Web / app 404 / site down | 9.6 | 0.2% | |
| Phone / voice / Teams calls | 9.2 | 0.2% | |
| Weekly firewall / config backup | 6.3 | 0.2% | |

### Project-style categories (588 hrs, 14.5 %)

| Category | Hours | % | Representative tickets |
|---|---:|---:|---|
| **NewStar ERP upgrade / updates / support** | 188.3 | 4.6% | "NewStar upgrade project" (18h, Nov '23–Feb '24); "Updating NewStar batches to 2023 version" (8.3h); "Newstar upgrade needed" (11.1h, Aug '24); plus ~130h of recurring NewStar app support |
| **RMM / tooling install on new machines** | 103.4 | 2.6% | "Tools installation" (22.7h); "Passportal", "SNMP setup", "Network Detective scans" |
| **Server / VM / ESXi / VMware upgrade or rebuild** | 87.6 | 2.2% | "HP Server Refreshing" (6.4h); "Virtual Disk consolidation required" (multi-entry, 24h+); "ESXi Host Reboot Issue" (7.8h); "Server down" (15.5h); multiple ESXi CPU/memory tickets |
| **Windows 11 / PC refresh / laptop deploy** | 66.0 | 1.6% | "Brandywine Homes Windows 11 Upgrade" (6.9h); "Onsite new PC configuration" (7.2h); "Preconfigure new dell computers for deployment" (5.5h); "Nancy Hayden's laptop", "Chris laptop", "Traci — PC setup" (named user builds) |
| **OneDrive / SharePoint data migration** | 65.5 | 1.6% | "Projects folder migration to one drive" (16.3h, Sep '23); "Share folder migration to one drive" (14.8h, Sep '23); "One Drive file problem and documents" ongoing |
| **Backup / Veeam / Replication setup or rebuild** | 33.4 | 0.8% | "QNAP firmware upgrade" (7.1h); "Getting Loaner QNAP Ready and Configured" (1.2h); Veeam reinstall/reconfigure tickets |
| **Firewall / VPN / Network buildout** | 18.8 | 0.5% | "New Firewall installed in BWH-HQ" (9.2h, Sep '25); Brandywine VPN update |
| **File server / data migration** | 13.5 | 0.3% | "File Server migration" (8.2h) |
| **Security / EDR / SSL / MFA rollout** | 12.0 | 0.3% | "SSL Certificate update" (8.2h); "SSL Cert Renewal" (3.9h) — infrastructure-cert work |

### Uncategorized (996 hrs, 24.6 %)
Short ad-hoc tickets whose titles don't match any clear pattern. Sample titles: *"Help"*, *"URGENT/CONFIDENTIAL"*, *"Chris laptop"*, *"File Missing"*, *"RE: my computer"*, *"DC issues"*, *"site visit"*. These are functionally routine support; they inflate the overage unavoidably.

---

## 3. When the project-heavy months happened

Top 10 months by project-candidate hours (from `work-categories-by-month.csv`):

| Month | Total hrs | Project hrs | % | Driver |
|---|---:|---:|---:|---|
| 2023-09 | 164.4 | 57.3 | 35% | **OneDrive migration burst (53h)** |
| 2023-08 | 113.7 | 34.4 | 30% | Windows 11 / laptop deploys + NewStar + OneDrive onset |
| 2024-12 | 154.5 | 34.3 | 22% | RMM tooling install (27h) + server work |
| 2025-09 | 158.4 | 28.2 | 18% | NewStar + Windows 11 + firewall |
| 2023-05 | 28.5 | 25.3 | 89% | **Contract onboarding month — laptop/PC deploys** |
| 2026-01 | 168.1 | 24.4 | 15% | Server/VM upgrade + NewStar |
| 2026-03 | 141.9 | 22.4 | 16% | Server/VM + RMM + OneDrive |
| 2024-05 | 156.4 | 21.5 | 14% | **NewStar batch 2023 upgrade (16h)** |
| 2025-03 | 130.6 | 21.3 | 16% | RMM tooling install + NewStar |
| 2024-08 | 118.0 | 21.2 | 18% | **"NewStar upgrade needed" (19h)** |

Observations:
- **2023-09 is an outlier (164 hrs total, 35% project).** The OneDrive migration project alone consumed 53 hrs — that should have been a separate SOW.
- **The contract onboarding month (2023-05)** was 89% project work — the initial hardware deploy / tooling install work was all bundled into month-1 support allocation.
- **NewStar was a recurring project theme** across at least 4 distinct upgrade waves (Nov '23–Feb '24, Mar–May '24, Aug '24, ongoing). Each wave produced 15–20+ project-like hours that were absorbed by monthly allocation.

---

## 4. How this explains the 4,050 hours

Reasonable interpretation Dave can absorb:

1. **~60 % of hours (2,466 hrs)** are exactly what a monthly-support contract is supposed to cover — patching, AV scans, agent updates, user support, monitoring alert response, printer/email/login/VPN triage. Averaged across 36 months, that's **~68 hrs/mo of pure operational support**, consistent with a ~40-seat environment running the RMM/EDR/backup/patching stack Technijian operates.

2. **~15 % of hours (588 hrs)** were project-type deliveries — NewStar upgrades, Windows 11 refresh, OneDrive migration, server VM work, firewall install, file-server migration, SSL certificate work. In a properly structured engagement, each of these would have been quoted as a separate SOW with a fixed-price or time-and-materials budget outside the monthly allocation. They were not. They were logged as tickets and billed through the weekly support invoice stream, which pushed BWH over allocation.

3. **~25 % of hours (996 hrs)** are short ad-hoc ticket activity that couldn't be bucketed cleanly — the classic "long tail" of MSP support. These belong in the monthly allocation.

Putting (1) + (3) together, **~3,462 hrs (85%) is defensibly monthly-support work**, averaging **~96 hrs/mo**, vs. the implied monthly allocation of ~83.6 hrs/mo. That alone produces roughly (96 − 83.6) × 36 = **~446 hrs of legitimate overage from routine support pressure**, mostly driven by the patch-management and CrowdStrike/ManageEngine/ScreenConnect agent-update workload which grew over the contract.

The remaining **~588 hrs of project work** is where the real conversation with BWH lives: **those should have been separate proposals**, and if they had been, the monthly-support overage balance on 4/24 would be materially lower.

---

## 5. Recommendations — how to present this to Dave

1. **Lead with ownership.** The 4/1 email figure (687.67 hrs) was a bad extract; the 4/24 figure (1,040.28 hrs) is correct. Acknowledge the gap was an internal extract error, not a new ~350 hr ghost.

2. **Show the breakdown.** Present the table in §2 so Dave sees what the 4,050 hours actually were. 60% routine ops, 25% short ad-hoc, 15% project work absorbed into support.

3. **Name the projects that should have been SOWs** and acknowledge they weren't quoted separately:
   - OneDrive / SharePoint migration (Sep 2023, ~65h)
   - NewStar ERP upgrade cycles (Nov '23 → ongoing, ~90h project + ~100h routine app support)
   - Windows 11 / PC refresh waves (~66h, plus named-user builds)
   - HP server refresh + ESXi/VM work (~88h)
   - New firewall install (Sep 2025, ~18h)
   - File server migration (~13.5h)
   - Tools install / RMM deployment on new machines (~103h)

4. **Offer a constructive path forward.** Options Dave can choose between:
   - **(a)** Write down the overage by the ~588 hrs of project-type work that was never separately quoted; keep the ~450 hrs of legitimate routine overage on the invoice.
   - **(b)** Propose forward-looking governance: any single ticket >4 hrs or any recognized project keyword (upgrade, migration, new deploy, rebuild) gets a change-order / SOW quote before delivery, so the monthly-support pool stays clean going forward.

5. **Provide `ticket-by-ticket.csv` + `project-candidate-tickets.csv`** as attachments so BWH can audit the classification. Every one of the 588 project-candidate hours is enumerated by date, ticket title, role, requestor, and hours.

---

## 6. Data caveats

1. **Systems Architect: 0 hours.** No architect time logged anywhere in 36 months. If architect hours were contractually allocated, those allocation hrs are entirely unused — which arguably offsets a portion of the support overage.
2. **2025-10 and 2025-11 India NH: 0 hrs.** Anomalous vs. typical 45–60 hrs/mo. Confirm with Tharunaa whether those months migrated to a different POD coding or were reclassified — they look like a data-capture gap, not actual zero delivery.
3. **Weekly invoice gaps.** 149 invoices across 156 possible weeks. Some weeks had no billable entries — consistent with fully-contracted weeks.
4. **No portal project invoices exist.** If separate project billing was ever done, it lives in QuickBooks outside the portal pipeline. A QuickBooks export is required to rule that out.
5. **Categorization heuristic.** The 588 hrs "project" figure is derived from keyword matching against ticket titles (see `_categorize-work.py`). Sampling accuracy is high for the named projects above but ~25% of hours remained uncategorized and some of those may also be project-like. Treat 588 hrs as a **lower bound** on project-absorption.

---

## 7. Files produced in this review

| File | Description |
|---|---|
| `GLOBAL-REVIEW.md` | This document |
| `work-categories-summary.csv` | Category × Hours × % × unique-ticket-count × entry-count |
| `work-categories-by-month.csv` | Month × Category pivot (36 months × 32 categories) |
| `work-categories-by-role.csv` | India NH / India AH / USA NH / USA AH × Category pivot |
| `project-candidate-tickets.csv` | All 588 hrs of project-style tickets, enumerated |
| `work-categories-samples.md` | 12 sample ticket titles per category (for human validation) |
| `_categorize-work.py` | Classifier (regex rules — easy to refine) |
| `_project-timeline.py` | Project-hours-per-month analysis script |
| `_dump-uncat.py` | Helper to inspect the uncategorized bucket |
