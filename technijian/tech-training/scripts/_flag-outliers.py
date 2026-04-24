"""Tech-training outlier analysis.

For each time entry, decide whether the hours claimed are outside a reasonable
range given the work described, then flag and group by tech. Produces:

  03_Accounting/tech-outliers-detail.csv   — every flagged entry
  03_Accounting/tech-outliers-by-tech.csv  — totals per tech, sorted worst-first
  03_Accounting/tech-outliers-summary.md   — human-readable training summary

Categories of outliers:
  H1  Trivial-work-high-hours : routine/low-complexity title with hours exceeding category cap
  H2  Generic/vague-title-high-hours : title is essentially meaningless ("Help", "Test") with >0.5h
  H3  Single-entry-too-long : one time-block > 8 hours (suggests a day-long dump into one entry)
  H4  Tech-day-too-long : total hours by one tech on one date > 12 hours
  H5  Duplicate-day-entries : same tech + same title + same day + multiple entries totalling > cap
"""
import csv
import importlib.util
import re
import sys
from collections import defaultdict
from pathlib import Path

# Usage: python _flag-outliers.py <client_code> <year>
# e.g.: python _flag-outliers.py bwh 2026
SCRIPTS = Path(__file__).resolve().parent                              # technijian/tech-training/scripts/
REPO = SCRIPTS.parent.parent.parent                                    # repo root
CLIENT = (sys.argv[1] if len(sys.argv) > 1 else "bwh").lower()
YEAR = sys.argv[2] if len(sys.argv) > 2 else "2026"

CLIENT_DATA = REPO / "clients" / CLIENT / YEAR / "03_Accounting"
CLIENT_SCRIPTS = REPO / "clients" / CLIENT / YEAR / "06_Scripts"
OUT = REPO / "technijian" / "tech-training" / CLIENT / YEAR
OUT.mkdir(parents=True, exist_ok=True)
SRC = CLIENT_DATA / "time-entries.csv"

# Load the classifier from the client's scripts folder
spec = importlib.util.spec_from_file_location("catmod", CLIENT_SCRIPTS / "_categorize-work.py")
catmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catmod)
classify = catmod.classify

# Per-category "reasonable" hours cap for a single logged entry on one ticket in one day.
# If an entry exceeds this, we flag it as H1.
CATEGORY_CAP = {
    # routine alerts/noise should rarely exceed 0.5-1h
    "Routine: Patch management / Windows Update / missing patches": 1.5,
    "Routine: Monitoring alert — CPU / memory / disk utilization": 0.75,
    "Routine: Monitoring alert — device down / not responding / agent offline": 0.75,
    "Routine: Monitoring alert — generic critical / MonitorField": 0.75,
    "Routine: Backup job / Veeam alert / failure": 1.5,
    "Routine: ScreenConnect / MyRemote agent updates": 1.0,
    "Routine: CrowdStrike / EDR agent version updates": 1.5,
    "Routine: MyRMM / ManageEngine / N-able / RMM agent version updates": 1.5,
    "Routine: Antivirus / Malware scan": 1.5,
    "Routine: Weekly Maintenance Window": 2.0,
    "Routine: User login / password / account lockout": 1.0,
    "Routine: Email / Outlook / spam / phishing": 1.5,
    "Routine: File access / Shared drive / OneDrive sync / Permissions": 1.5,
    "Routine: Printer / Scanner / Peripheral": 1.5,
    "Routine: Phone / Voice / Teams / Conferencing": 1.5,
    "Routine: Hardware troubleshoot (slow, freeze, bsod, boot)": 2.5,
    "Routine: Onboarding / Offboarding user": 3.0,
    "Routine: Network / Internet / ISP / Wi-Fi issue": 2.0,
    "Routine: Weekly firewall / config backup": 1.0,
    "Routine: Admin / Approvals / Signatures / Meetings": 1.0,
    "Routine: Server/DC issue (generic)": 3.0,
    "Routine: VPN troubleshoot": 1.5,
    "Routine: Individual user / PC / laptop issue (named)": 3.0,
    "Routine: Web / app 404 / site down": 2.0,
    "Routine: Generic help / troubleshoot / support": 1.5,
    # project work can legitimately take longer per entry
    "Project: NewStar ERP upgrade / updates / support": 4.0,
    "Project: RMM / tooling install on new machines": 3.0,
    "Project: Server / VM / ESXi / VMware upgrade or rebuild": 4.0,
    "Project: Windows 11 / PC refresh / laptop deploy": 4.0,
    "Project: OneDrive / SharePoint data migration": 4.0,
    "Project: Backup / Veeam / Replication setup or rebuild": 4.0,
    "Project: Firewall / VPN / Network buildout": 4.0,
    "Project: File server / data migration": 4.0,
    "Project: Security / EDR / CrowdStrike / Umbrella / SSL / MFA rollout": 3.0,
    "Uncategorized": 2.5,  # fallback
}
DEFAULT_CAP = 2.5

# Generic/vague titles that should not carry many hours
GENERIC_TITLE_RE = re.compile(
    r"^\s*(help|test\d*|testing|support|fix|issue|problem|question|note|follow[- ]up|call|"
    r"update|updates|tbd|misc|other|review|meeting|check(ing)?)\s*\.?\s*$", re.I)

ABSURD_SINGLE_ENTRY = 8.0    # >8h in one block
ABSURD_DAILY_TOTAL = 12.0    # one tech > 12h in a day
DUPE_DAY_CAP_MULTIPLIER = 2.0  # same tech+title+day, total > cap * 2

# --- load & analyze ---
entries = []
with SRC.open("r", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        try:
            hrs = abs(float(row.get("Hours") or 0))
        except ValueError:
            hrs = 0.0
        if hrs <= 0:
            continue
        entries.append({
            "Date": row.get("TimeEntryDate", "")[:10],
            "Month": row.get("TimeEntryDate", "")[:7],
            "Title": (row.get("Title") or "").strip(),
            "Tech": (row.get("AssignedName") or "").strip() or "(unassigned)",
            "POD": row.get("Office-POD", ""),
            "Shift": row.get("HourType", ""),
            "Hours": hrs,
            "Requestor": row.get("Requestor", ""),
            "InvDescription": (row.get("InvDescription") or "").strip(),
        })

# Group for H4 (daily totals per tech) and H5 (dupes)
daily_totals = defaultdict(float)              # (tech, date) -> hours
title_day_totals = defaultdict(list)           # (tech, date, title) -> [(hours, entry_ref)]
for e in entries:
    daily_totals[(e["Tech"], e["Date"])] += e["Hours"]
    title_day_totals[(e["Tech"], e["Date"], e["Title"])].append(e)

# Flag entries
flagged = []
for e in entries:
    flags = []
    cat = classify(e["Title"])
    cap = CATEGORY_CAP.get(cat, DEFAULT_CAP)

    # H1: Trivial-work-high-hours
    if cat.startswith("Routine:") and e["Hours"] > cap:
        flags.append(("H1", f"routine work > {cap}h cap (cat: {cat[9:]})"))

    # H2: Generic/vague-title-high-hours
    if GENERIC_TITLE_RE.match(e["Title"]) and e["Hours"] > 0.5:
        flags.append(("H2", f"vague title '{e['Title']}' with {e['Hours']:.2f}h"))

    # H3: Single-entry-too-long
    if e["Hours"] > ABSURD_SINGLE_ENTRY:
        flags.append(("H3", f"single entry {e['Hours']:.2f}h > {ABSURD_SINGLE_ENTRY}h"))

    # H4: Tech-day-too-long (flag the entry if its day total crosses threshold)
    day_tot = daily_totals[(e["Tech"], e["Date"])]
    if day_tot > ABSURD_DAILY_TOTAL:
        flags.append(("H4", f"tech daily total {day_tot:.2f}h > {ABSURD_DAILY_TOTAL}h"))

    # H5: Duplicate-day-entries (same tech+title+day sum > cap*2)
    group = title_day_totals[(e["Tech"], e["Date"], e["Title"])]
    if len(group) >= 2:
        group_sum = sum(g["Hours"] for g in group)
        if group_sum > cap * DUPE_DAY_CAP_MULTIPLIER:
            flags.append(("H5", f"{len(group)} entries on same ticket/day totalling {group_sum:.2f}h"))

    if flags:
        e["Category"] = cat
        e["Cap"] = cap
        e["DailyTotal"] = round(day_tot, 2)
        e["FlagCodes"] = ";".join(f[0] for f in flags)
        e["FlagReasons"] = " | ".join(f[1] for f in flags)
        flagged.append(e)

# --- outputs ---

# detail.csv — every flagged entry
out_detail = OUT / "tech-outliers-detail.csv"
with out_detail.open("w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Date", "Tech", "POD", "Shift", "Title", "Category", "Hours", "CategoryCap", "DailyTotal", "Flags", "Reasons", "Requestor"])
    for e in sorted(flagged, key=lambda x: (-x["Hours"], x["Date"])):
        w.writerow([e["Date"], e["Tech"], e["POD"], e["Shift"], e["Title"], e["Category"],
                    round(e["Hours"], 2), e["Cap"], e["DailyTotal"],
                    e["FlagCodes"], e["FlagReasons"], e["Requestor"]])

# by-tech.csv — aggregate per tech
tech_agg = defaultdict(lambda: {"count": 0, "hours": 0.0, "flags": defaultdict(int)})
for e in flagged:
    t = tech_agg[e["Tech"]]
    t["count"] += 1
    t["hours"] += e["Hours"]
    for code in e["FlagCodes"].split(";"):
        t["flags"][code] += 1

# total entries and hours per tech (all time, not just flagged)
tech_totals = defaultdict(lambda: {"entries": 0, "hours": 0.0})
for e in entries:
    tt = tech_totals[e["Tech"]]
    tt["entries"] += 1
    tt["hours"] += e["Hours"]

out_bytech = OUT / "tech-outliers-by-tech.csv"
with out_bytech.open("w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Tech", "TotalEntries", "TotalHours",
                "FlaggedEntries", "FlaggedHours", "FlaggedPctOfHours",
                "H1_trivial_high", "H2_vague_title", "H3_entry>8h", "H4_day>12h", "H5_dupe_day"])
    rows = []
    for tech, agg in tech_agg.items():
        tot = tech_totals[tech]
        flagged_pct = (agg["hours"] / tot["hours"] * 100) if tot["hours"] else 0
        rows.append([
            tech,
            tot["entries"],
            round(tot["hours"], 2),
            agg["count"],
            round(agg["hours"], 2),
            f"{flagged_pct:.1f}%",
            agg["flags"].get("H1", 0),
            agg["flags"].get("H2", 0),
            agg["flags"].get("H3", 0),
            agg["flags"].get("H4", 0),
            agg["flags"].get("H5", 0),
        ])
    rows.sort(key=lambda r: -r[4])  # by flagged hours desc
    w.writerows(rows)

# summary.md
out_md = OUT / "tech-outliers-summary.md"
total_hours = sum(e["Hours"] for e in entries)
flagged_hours = sum(e["Hours"] for e in flagged)
with out_md.open("w", encoding="utf-8") as f:
    f.write("# BWH Time-Entry Outlier Review — Tech Training\n\n")
    f.write(f"**Source:** `time-entries.csv` (all BWH time entries, life of contract)\n")
    f.write(f"**Total entries analyzed:** {len(entries):,}\n")
    f.write(f"**Total hours:** {total_hours:,.2f}\n")
    f.write(f"**Flagged entries:** {len(flagged):,} ({len(flagged)/len(entries)*100:.1f}%)\n")
    f.write(f"**Flagged hours:** {flagged_hours:,.2f} ({flagged_hours/total_hours*100:.1f}%)\n\n")

    f.write("## Flag codes\n\n")
    f.write("| Code | Meaning |\n|---|---|\n")
    f.write("| H1 | Routine/low-complexity work with hours exceeding the reasonable category cap |\n")
    f.write("| H2 | Generic/vague title (\"Help\", \"Test\", \"Fix\", etc.) with >0.5h claimed |\n")
    f.write(f"| H3 | Single time-entry > {ABSURD_SINGLE_ENTRY}h (suggests a whole-day dump into one entry) |\n")
    f.write(f"| H4 | Tech's total hours on one date > {ABSURD_DAILY_TOTAL}h (cross-ticket over-claim) |\n")
    f.write("| H5 | Same tech + same ticket + same day with multiple entries totalling > 2× cap |\n\n")

    f.write("## Techs ranked by flagged hours\n\n")
    f.write("| Tech | Total hrs | Flagged hrs | % flagged | Entries flagged | H1 | H2 | H3 | H4 | H5 |\n")
    f.write("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    for r in rows:
        tech, tot_e, tot_h, fe, fh, fp, h1, h2, h3, h4, h5 = r
        f.write(f"| {tech} | {tot_h:,.1f} | {fh:,.1f} | {fp} | {fe} | {h1} | {h2} | {h3} | {h4} | {h5} |\n")

    # Show worst 25 individual entries
    f.write("\n## Top 25 worst individual flagged entries (by hours)\n\n")
    f.write("| Date | Tech | Hours | Cap | Title | Flags |\n|---|---|---:|---:|---|---|\n")
    for e in sorted(flagged, key=lambda x: -x["Hours"])[:25]:
        title = e["Title"].replace("|", "\\|")[:80]
        f.write(f"| {e['Date']} | {e['Tech']} | {e['Hours']:.2f} | {e['Cap']} | {title} | {e['FlagCodes']} |\n")

    # Per-flag top samples
    for code, label in [
        ("H1", "Trivial work with excessive hours"),
        ("H2", "Vague title with too many hours"),
        ("H3", f"Single entries over {ABSURD_SINGLE_ENTRY}h"),
        ("H4", f"Tech days over {ABSURD_DAILY_TOTAL}h total"),
        ("H5", "Duplicate-day title stacks"),
    ]:
        sample = [e for e in flagged if code in e["FlagCodes"].split(";")]
        if not sample:
            continue
        f.write(f"\n## Flag {code} — {label} ({len(sample)} entries)\n\n")
        f.write("Top 15:\n\n")
        f.write("| Date | Tech | Hours | Title | Reason |\n|---|---|---:|---|---|\n")
        for e in sorted(sample, key=lambda x: -x["Hours"])[:15]:
            title = e["Title"].replace("|", "\\|")[:70]
            reason = e["FlagReasons"].replace("|", "\\|")[:90]
            f.write(f"| {e['Date']} | {e['Tech']} | {e['Hours']:.2f} | {title} | {reason} |\n")

print(f"Entries analyzed: {len(entries):,}")
print(f"Flagged entries:  {len(flagged):,} ({len(flagged)/len(entries)*100:.1f}%)")
print(f"Flagged hours:    {flagged_hours:,.2f} of {total_hours:,.2f} ({flagged_hours/total_hours*100:.1f}%)")
print(f"\nWrote:")
print(f"  {out_detail}")
print(f"  {out_bytech}")
print(f"  {out_md}")
