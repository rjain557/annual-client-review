#!/usr/bin/env python3
"""Build final BWH hour-accounting reconciliation from pulled data.

Produces:
  hours-by-month.csv              -- one row per (Month x POD x RoleType x HourType)
  hours-pivot.csv                 -- wide format: months as rows, POD/Role/Shift as columns
  reconciliation-summary.md       -- human-readable narrative
  ticket-by-ticket.csv            -- ticket-grain summary (hours grouped by TicketTitle+Date)
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_time_entries():
    rows = []
    with open(HERE / "time-entries.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                r["HoursAbs"] = abs(float(r.get("Hours") or 0))
            except ValueError:
                r["HoursAbs"] = 0.0
            rows.append(r)
    return rows


def month_of(date_str):
    return (date_str or "")[:7]


def categorize_role(te):
    """Collapse to 4 categories matching the 4/1 and 4/24 emails."""
    pod = te.get("Office-POD", "")
    hour_type = (te.get("HourType") or "").upper()
    role = te.get("RoleType", "")

    if "AD1" in pod or role == "CTO" or "Architect" in te.get("AssignedName", ""):
        return "Systems Architect"
    if "CHD" in pod:
        return "India Tech After Hours" if hour_type == "AH" else "India Tech Normal"
    if "IRV" in pod:
        return "USA Tech"
    return f"Other ({pod})"


def write_hours_by_month(rows):
    agg = defaultdict(float)
    for r in rows:
        ym = month_of(r.get("TimeEntryDate"))
        if not ym or not ym.startswith("2"):
            continue
        cat = categorize_role(r)
        agg[(ym, cat)] += r["HoursAbs"]

    months = sorted({ym for ym, _ in agg})
    cats = ["India Tech Normal", "India Tech After Hours", "USA Tech", "Systems Architect"]
    other_cats = sorted({c for _, c in agg if c not in cats})
    all_cats = cats + other_cats

    out = HERE / "hours-by-month.csv"
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Month"] + all_cats + ["Monthly Total"])
        running = defaultdict(float)
        cumulative_rows = []
        for ym in months:
            total = 0.0
            row = [ym]
            for c in all_cats:
                v = round(agg.get((ym, c), 0.0), 2)
                row.append(v)
                total += v
                running[c] += v
            row.append(round(total, 2))
            w.writerow(row)
            cumulative_rows.append([ym] + [round(running[c], 2) for c in all_cats] + [round(sum(running.values()), 2)])

    # cumulative sheet
    cum_path = HERE / "hours-cumulative.csv"
    with open(cum_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Month"] + all_cats + ["Cumulative Total"])
        for r in cumulative_rows:
            w.writerow(r)

    return agg, months, all_cats


def write_ticket_by_ticket(rows):
    agg = defaultdict(float)
    meta = {}
    for r in rows:
        key = (
            r.get("TimeEntryDate", ""),
            r.get("Title", ""),
            r.get("Requestor", ""),
            r.get("Office-POD", ""),
            r.get("RoleType", ""),
            r.get("HourType", ""),
            r.get("AssignedName", ""),
        )
        agg[key] += r["HoursAbs"]
        meta[key] = {
            "Date": r.get("TimeEntryDate", ""),
            "Ticket": r.get("Title", ""),
            "Requestor": r.get("Requestor", ""),
            "POD": r.get("Office-POD", ""),
            "Role": r.get("RoleType", ""),
            "Shift": r.get("HourType", ""),
            "Assignee": r.get("AssignedName", ""),
            "InvDescription": r.get("InvDescription", "").replace("\r\n", " / "),
        }

    out = HERE / "ticket-by-ticket.csv"
    fieldnames = ["Date", "Ticket", "Requestor", "POD", "Role", "Shift", "Assignee", "InvDescription", "Hours"]
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for key, hrs in sorted(agg.items()):
            m = dict(meta[key])
            m["Hours"] = round(hrs, 2)
            w.writerow(m)
    print(f"  wrote {out} ({len(agg)} ticket-grain rows)")


def build_summary_md(agg, months, cats):
    lines = []
    lines.append("# BWH Hour Accounting — Life of Contract")
    lines.append("")
    lines.append("**Contract ID:** 4924 (IT Services Proposal, Monthly Service)")
    lines.append("**Contract Start:** 2023-05-02")
    lines.append("**Client DirID:** 6245")
    lines.append("**Data source:** Client Portal stored procedures (pulled 2026-04-24)")
    lines.append("  - Time entries: `stp_xml_TktEntry_List_Get` (ClientID=6245)")
    lines.append("  - Invoices: `stp_xml_InvWeekly_Org_Loc_Inv_Weekly_List_Get` (DirID=6245)")
    lines.append("")
    lines.append("## Hours Delivered by Month — by Role")
    lines.append("")
    header = ["Month"] + cats + ["Total"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    grand = {c: 0.0 for c in cats}
    grand_total = 0.0
    for ym in months:
        row_vals = []
        mt = 0.0
        for c in cats:
            v = agg.get((ym, c), 0.0)
            row_vals.append(f"{v:.2f}")
            grand[c] += v
            mt += v
        row_vals.append(f"{mt:.2f}")
        grand_total += mt
        lines.append("| " + ym + " | " + " | ".join(row_vals) + " |")
    lines.append("| **TOTAL** | " + " | ".join(f"**{grand[c]:.2f}**" for c in cats) + f" | **{grand_total:.2f}** |")
    lines.append("")
    lines.append("## How this compares to the two figures Dave is asking about")
    lines.append("")
    lines.append("### 4/1 email footer (what Tharunaa reported to Dave on 2026-04-01)")
    lines.append("```")
    lines.append("LocationCode=BWH, MonthStartDate=3/1/2026")
    lines.append("  India OFFSHORESUPPORT NH : 413.61")
    lines.append("  India OFFSHORESUPPORT AH : 168.55")
    lines.append("  Systems Architect US NH  :   0.00")
    lines.append("  USA Tech Support NH      : 105.51")
    lines.append("  TOTAL                    : 687.67")
    lines.append("```")
    lines.append("")
    lines.append("### 4/24 email (figure now cited by Technijian after April billing)")
    lines.append("```")
    lines.append("  India Tech Normal        : 600.22")
    lines.append("  India Tech After Hours   : 310.63")
    lines.append("  USA Tech Normal          : 129.43")
    lines.append("  Systems Architect        :   0.00")
    lines.append("  TOTAL                    : 1,040.28")
    lines.append("```")
    lines.append("")
    lines.append("### Ravi's interim explanation to Dave (4/24 18:44)")
    lines.append("> \"Before April 1st total hours were 1011.69, then we billed for April 1st, 116.21 new hours, plus partial April delivery → ~1,040\"")
    lines.append("")
    lines.append("## Reconciliation notes")
    lines.append("")
    lines.append("1. **The 687.67 figure (4/1 email) is NOT life-of-contract delivered hours.** Our portal data shows far more than 687.67 hours were delivered in any single calendar month, let alone all months combined. This number represents some other snapshot — most likely a month-specific unpaid-overage figure or a subset that did not aggregate the full history.")
    lines.append("")
    lines.append("2. **The 1,040.28 figure (4/24 email) tracks closer to a cumulative overage above contracted allocation**, but the delta from 687.67 (+352.61 in 23 days) is not explained by new delivery alone. Actual delivered hours in April 2026 through 4/24:")
    agg_apr = {c: agg.get(("2026-04", c), 0.0) for c in cats}
    lines.append("```")
    for c in cats:
        lines.append(f"  {c:<25s}: {agg_apr[c]:>7.2f}")
    lines.append(f"  {'TOTAL':<25s}: {sum(agg_apr.values()):>7.2f}")
    lines.append("```")
    lines.append("")
    lines.append("3. **Dave's specific ask** — ticket-by-ticket accounting with date, role, ticket, hours, allocation treatment — is satisfied by `ticket-by-ticket.csv` in this folder. Every time entry with full provenance is in `time-entries.csv`.")
    lines.append("")
    lines.append("4. **What to send Dave next:**")
    lines.append("   - `ticket-by-ticket.csv` (or filtered 12-month slice)")
    lines.append("   - A signed-off figure for the cumulative unpaid-overage balance, with the method used to compute it (delivered - contracted allocation per role per month, running total)")
    lines.append("   - The OLD contract's monthly allocation per role — needed to compute \"contracted vs delivered\" per month. The portal's `stp_xml_MC_Org_Loc_Con_Sup_POD_LocHours_Get` returns empty for BWH, so allocation must be sourced from the original signed agreement or Tharunaa's working worksheet.")
    lines.append("")
    lines.append("## Invoice history (life of contract)")
    lines.append("")
    lines.append("Total Weekly Invoices Sent: 149 (2023-05-05 → 2026-04-17). All 149 marked **Paid** in portal.")
    lines.append("")
    lines.append("Monthly / Recurring invoices (#28148 Monthly, #28116 Recurring per BWH.md) were not returned by the weekly-list SP; they are generated by a different billing workflow and not accessible via the Client Portal generic SP set under the current permissions. Those should be pulled directly from QuickBooks if required.")
    lines.append("")
    lines.append("## Data artifacts in this folder")
    lines.append("")
    lines.append("| File | Description |")
    lines.append("|------|-------------|")
    lines.append("| `time-entries.csv` | All 6,694 time entries (every row = one logged hour block) |")
    lines.append("| `ticket-by-ticket.csv` | Aggregated by (Date × Ticket × Role × POD × Shift) |")
    lines.append("| `monthly-summary.csv` | Aggregated by (Month × POD × Role × Shift × InvDescription) |")
    lines.append("| `hours-by-month.csv` | Wide format: months as rows, 4 role categories as columns |")
    lines.append("| `hours-cumulative.csv` | Same but with running totals |")
    lines.append("| `invoices.csv` | 149 weekly invoices (ID, number, date, status) |")
    lines.append("| `time-entries-raw/*.xml` | Raw monthly XML from portal |")
    lines.append("| `invoice-details-raw/*.xml` | Per-invoice detail XML |")
    lines.append("")

    out = HERE / "ACCOUNTING.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote {out}")


if __name__ == "__main__":
    rows = load_time_entries()
    print(f"loaded {len(rows)} time entries")
    agg, months, cats = write_hours_by_month(rows)
    print(f"  wrote hours-by-month.csv and hours-cumulative.csv ({len(months)} months)")
    write_ticket_by_ticket(rows)
    build_summary_md(agg, months, ["India Tech Normal", "India Tech After Hours", "USA Tech", "Systems Architect"])
