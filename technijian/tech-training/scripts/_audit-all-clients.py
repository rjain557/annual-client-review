"""All-clients, all-techs 2026 time-entry audit.

Scans every client folder under clients/, loads its time-entries CSV (either
clients/<code>/data/time_entries.csv or clients/<code>/<YEAR>/03_Accounting/
time-entries.csv), filters to the target YEAR, flags outliers using the same
rules as _flag-outliers.py, and writes:

  technijian/tech-training/<YEAR>/
    SUMMARY.md                        — cross-client rollup
    all-flagged-entries.csv           — master CSV (every flagged entry)
    by-client/<client>/
      tech-outliers-summary.md
      tech-outliers-by-tech.csv
      tech-outliers-detail.csv
    by-tech/<tech-slug>/
      training.md
      flagged-entries.csv

Usage: python _audit-all-clients.py [YEAR]  (default 2026)
"""
import csv
import importlib.util
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

csv.field_size_limit(10_000_000)

SCRIPTS = Path(__file__).resolve().parent

# Coaching templates
_coach_spec = importlib.util.spec_from_file_location("coaching", SCRIPTS / "_coaching.py")
_coach_mod = importlib.util.module_from_spec(_coach_spec)
_coach_spec.loader.exec_module(_coach_mod)
build_coaching = _coach_mod.build_coaching
REPO = SCRIPTS.parent.parent.parent
YEAR = sys.argv[1] if len(sys.argv) > 1 else "2026"
OUT_ROOT = REPO / "technijian" / "tech-training" / YEAR
OUT_BYCLIENT = OUT_ROOT / "by-client"
OUT_BYTECH = OUT_ROOT / "by-tech"
OUT_BYCLIENT.mkdir(parents=True, exist_ok=True)
OUT_BYTECH.mkdir(parents=True, exist_ok=True)

# Category classifier — use broad routine/project pattern library (client-agnostic)
CATEGORIES = [
    ("Project: ERP / app upgrade",
     re.compile(r"\b(newstar|sage|quickbooks|procore|autocad|bluebeam|erp|application)\s*(upgrade|migrat|install|deploy|rollout|update)\b", re.I)),
    ("Project: Server / VM / ESXi upgrade or rebuild",
     re.compile(r"\b(esxi|vmware|vsphere|vcenter|hyper-?v|host)\b.*\b(upgrade|install|build|rebuild|migrat|refresh|decom)\b"
                r"|\bwindows\s*server\s*(2016|2019|2022)\b"
                r"|\bvirtual\s*disk\s*consolidation\b|\bsnapshot\s*consolidation\b"
                r"|\bserver\s*refresh", re.I)),
    ("Project: Firewall / VPN / Network buildout",
     re.compile(r"\bnew\s*firewall\b|\bfirewall\s*(install|replac|upgrade|deploy)\b"
                r"|\b(install|replac|upgrade|deploy|setup)\b.*\b(firewall|sonicwall|fortigate|meraki|cisco\s*asa|switch|access\s*point)\b", re.I)),
    ("Project: Backup / Veeam / Replication",
     re.compile(r"\b(veeam|vbr|backup|replication)\b.*\b(install|setup|implement|deploy|migrat|rebuild|replace|upgrade)\b"
                r"|\bqnap\s*(firmware|upgrade|setup|deploy)\b", re.I)),
    ("Project: M365 / Exchange / Intune / Entra",
     re.compile(r"\b(m365|o365|office\s*365|microsoft\s*365|exchange\s*online|tenant|intune|azure\s*ad|entra)\b.*\b(migrat|setup|deploy|implement|config|onboard|rollout)\b"
                r"|\bmailbox\s*(migrat|move)\b", re.I)),
    ("Project: OneDrive / SharePoint data migration",
     re.compile(r"\b(folder|file\s*share|shares?)\b.*\b(migrat|move)\b.*\bone\s*drive\b"
                r"|\bone\s*drive\b.*\b(migrat|rollout)\b"
                r"|\bsharepoint\b.*\b(migrat|setup|rollout)\b", re.I)),
    ("Project: Windows refresh / PC deploy",
     re.compile(r"\bwindows\s*11\s*(upgrade|rollout|deploy|refresh)\b"
                r"|\b(pc|laptop|workstation|hardware)\s*refresh\b"
                r"|\bpreconfigure\s*new\b"
                r"|\bnew\s*pc\s*config", re.I)),
    ("Project: RMM / tooling install",
     re.compile(r"\btools?\s*install(ation|ed)?\b|\btechnijian\s*tools\b|\bpasspor?tal\b|\bsnmp\s*(setup|config)\b", re.I)),
    ("Project: File server / data migration",
     re.compile(r"\bfile\s*server\s*(migrat|move|upgrade|rebuild)\b|\bdata\s*migration\b|\bserver\s*migration\b", re.I)),
    ("Project: Security / EDR / SSL rollout",
     re.compile(r"\bssl\s*cert(ificate)?\s*(update|renew|install)\b"
                r"|\b(crowdstrike|sentinelone|defender|huntress|umbrella)\b.*\b(deploy|rollout|setup|implement|onboard)\b", re.I)),

    ("Routine: Weekly Maintenance Window",
     re.compile(r"\bweekly\s*maintenance\s*window\b|\bmaintenance\s*window\b", re.I)),
    ("Routine: Patch management / Windows Update",
     re.compile(r"\bpatch(ed|es|ing)?\b|\bwindows\s*update\b|\bmissing\s*update\b|\bnon-?compliant\b|\bfailed\s*(patch|installation)\b|\bapd\b|\bautomate\s*patch\b", re.I)),
    ("Routine: CrowdStrike / EDR agent updates",
     re.compile(r"\bcrowdstrike\b|\bsentinelone\b|\bdefender\b|\bhuntress\b", re.I)),
    ("Routine: MyRMM / ManageEngine agent updates",
     re.compile(r"\b(myrmm|manage\s*engine|manageengine|n-?able|n-?central|rmm\s*agent|agent\s*(update|upgrade|version|not\s*sync|not\s*responding))\b", re.I)),
    ("Routine: ScreenConnect / MyRemote updates",
     re.compile(r"\b(screenconnect|myremote|my\s*remote)\b", re.I)),
    ("Routine: Antivirus / Malware scan",
     re.compile(r"\b(malwarebytes|antivirus|\bav\b|virus\s*scan|malware\s*scan|threat\s*detected|quarantin)\b", re.I)),
    ("Routine: Monitoring alert — device down / offline",
     re.compile(r"\bdevice\s*(not\s*responding|down)\b|\bnot\s*contact(ed)?\s*agent\b|\bprobably\s*down\b|\bno\s*response\s*from\s*device\b|\boffline\b", re.I)),
    ("Routine: Monitoring alert — CPU / memory / disk",
     re.compile(r"\b(cpu|memory|disk|bandwidth|drive\s*space)\s*utilization\b|\bthreshold\b|\bhigh\s*(cpu|memory|disk)\b", re.I)),
    ("Routine: Monitoring alert — generic critical / MonitorField",
     re.compile(r"\bmonitorfield\b|\bcritical\s*-\b|\battention\s*-\b|\btrouble\s*-\b|\bdesktop\s*alert\b|\bserver\s*alert\b", re.I)),
    ("Routine: Backup job / Veeam alert",
     re.compile(r"\bbackup\s*(fail|error|alert|monitor|job|issue|pending|not\s*running)\b|\bveeam\s*(alert|fail|error|issue)\b|\bweekly\s*firewall\s*backup\b", re.I)),
    ("Routine: User login / password / account lockout",
     re.compile(r"\b(password|lockout|locked\s*out|cannot\s*log\s*in|can't\s*log\s*in|unable\s*to\s*log\s*?in|reset\s*password|account\s*(disabled|locked)|login\s*(issue|problem))\b", re.I)),
    ("Routine: Email / Outlook / spam",
     re.compile(r"\b(outlook|email|spam|phish|junk|mailbox|mimecast|quarantine)\b", re.I)),
    ("Routine: File access / Shared drive / permissions",
     re.compile(r"\b(permission|access\s*(denied|to\s*(the|shared)|issue)|file\s*share|shared?\s*(drive|folder)|mapped\s*drive|network\s*drive|one\s*drive\s*(sync|file|issue)|file\s*missing|mydisk)\b", re.I)),
    ("Routine: Printer / Scanner",
     re.compile(r"\b(printer|scanner|toner|print\s*queue|jam|copier|mfp)\b", re.I)),
    ("Routine: Phone / Voice / Teams",
     re.compile(r"\b(phone|voice|voip|teams\s*call|ring\s*central|ringcentral|3cx|extension|zoom|conference)\b", re.I)),
    ("Routine: Hardware troubleshoot",
     re.compile(r"\b(screen|monitor|battery|slow|freez|crash|blue\s*screen|bsod|won't\s*boot|hardware|dock|keyboard|mouse|usb|bluetooth)\b", re.I)),
    ("Routine: VPN troubleshoot",
     re.compile(r"\bvpn\s*(issue|problem|not\s*working|update|client\s*issue)\b", re.I)),
    ("Routine: Network / Internet / Wi-Fi",
     re.compile(r"\b(network\s*(issue|down|problem)|internet\s*(down|out|slow)|isp|wi-?fi\s*(issue|down|slow)|no\s*internet|dns\s*issue|dhcp)\b", re.I)),
    ("Routine: Onboarding / Offboarding",
     re.compile(r"\bonboard(ing)?\b|\boffboard(ing)?\b|\bterminat|\bnew\s*hire\b", re.I)),
    ("Routine: Server/DC issue",
     re.compile(r"\b(server\s*(down|issue|problem)|dc\s*(issue|down)|domain\s*controller\s*issue)\b", re.I)),
    ("Routine: Individual user / PC / laptop (named)",
     re.compile(r"\b[A-Z][a-z]+(?:'s)?\s+(laptop|pc|computer|machine|docking|setup|upgrade)\b", re.I)),
    ("Routine: Admin / meetings / approvals",
     re.compile(r"\b(action\s*required|via-?sign|docusign|approval\s*needed|meeting|standup|status\s*update)\b", re.I)),
    ("Routine: Generic help / support",
     re.compile(r"\b(help|support|troubleshoot|question|assistance|fix|resolve|repair)\b", re.I)),
]

CATEGORY_CAP = {
    "Routine: Patch management / Windows Update": 1.5,
    "Routine: Monitoring alert — CPU / memory / disk": 0.75,
    "Routine: Monitoring alert — device down / offline": 0.75,
    "Routine: Monitoring alert — generic critical / MonitorField": 0.75,
    "Routine: Backup job / Veeam alert": 1.5,
    "Routine: ScreenConnect / MyRemote updates": 1.0,
    "Routine: CrowdStrike / EDR agent updates": 1.5,
    "Routine: MyRMM / ManageEngine agent updates": 1.5,
    "Routine: Antivirus / Malware scan": 1.5,
    "Routine: Weekly Maintenance Window": 2.0,
    "Routine: User login / password / account lockout": 1.0,
    "Routine: Email / Outlook / spam": 1.5,
    "Routine: File access / Shared drive / permissions": 1.5,
    "Routine: Printer / Scanner": 1.5,
    "Routine: Phone / Voice / Teams": 1.5,
    "Routine: Hardware troubleshoot": 2.5,
    "Routine: Onboarding / Offboarding": 3.0,
    "Routine: Network / Internet / Wi-Fi": 2.0,
    "Routine: Admin / meetings / approvals": 1.0,
    "Routine: Server/DC issue": 3.0,
    "Routine: VPN troubleshoot": 1.5,
    "Routine: Individual user / PC / laptop (named)": 3.0,
    "Routine: Generic help / support": 1.5,
    "Project: ERP / app upgrade": 4.0,
    "Project: RMM / tooling install": 3.0,
    "Project: Server / VM / ESXi upgrade or rebuild": 4.0,
    "Project: Windows refresh / PC deploy": 4.0,
    "Project: OneDrive / SharePoint data migration": 4.0,
    "Project: Backup / Veeam / Replication": 4.0,
    "Project: Firewall / VPN / Network buildout": 4.0,
    "Project: File server / data migration": 4.0,
    "Project: Security / EDR / SSL rollout": 3.0,
    "Project: M365 / Exchange / Intune / Entra": 4.0,
    "Uncategorized": 2.5,
}
DEFAULT_CAP = 2.5

GENERIC_TITLE_RE = re.compile(
    r"^\s*(help|test\d*|testing|support|fix|issue|problem|question|note|follow[- ]up|call|"
    r"update|updates|tbd|misc|other|review|meeting|check(ing)?)\s*\.?\s*$", re.I)
ABSURD_SINGLE_ENTRY = 8.0
ABSURD_DAILY_TOTAL = 12.0
DUPE_DAY_CAP_MULTIPLIER = 2.0


def classify(title: str) -> str:
    if not title:
        return "Uncategorized"
    for name, pat in CATEGORIES:
        if pat.search(title):
            return name
    return "Uncategorized"


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name.strip()).strip("-") or "unknown"
    return s


def find_time_entries_csv(client_dir: Path, year: str) -> Path | None:
    # Order of preference
    candidates = [
        client_dir / year / "03_Accounting" / "time-entries.csv",
        client_dir / year / "03_Accounting" / "time_entries.csv",
        client_dir / "data" / "time_entries.csv",
        client_dir / "data" / "time-entries.csv",
    ]
    for c in candidates:
        if c.exists() and c.stat().st_size > 100:
            return c
    return None


def parse_hours(row: dict) -> float:
    """Try multiple fields — Qty, AH+NH hours, or parse TimeDiff."""
    for fld in ("Qty", "Hours"):
        v = row.get(fld)
        if v:
            try:
                return abs(float(v))
            except ValueError:
                pass
    ah = row.get("AH_HoursWorked") or ""
    nh = row.get("NH_HoursWorked") or ""
    try:
        total = 0.0
        if ah:
            total += abs(float(ah))
        if nh:
            total += abs(float(nh))
        if total > 0:
            return total
    except ValueError:
        pass
    td = row.get("TimeDiff") or ""
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*hrs", td)
    if m:
        return abs(float(m.group(1)))
    return 0.0


def load_client_entries(client_code: str, csv_path: Path, year: str):
    entries = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = (row.get("TimeEntryDate") or row.get("Date") or "")[:10]
            if not date.startswith(year):
                continue
            hrs = parse_hours(row)
            if hrs <= 0:
                continue
            entries.append({
                "Client": client_code,
                "Date": date,
                "Month": date[:7],
                "Title": (row.get("Title") or "").strip(),
                "Tech": (row.get("AssignedName") or row.get("Resource") or "").strip() or "(unassigned)",
                "POD": row.get("Office-POD", ""),
                "Shift": row.get("HourType", ""),
                "Hours": hrs,
                "Requestor": (row.get("Requestor") or "").strip(),
            })
    return entries


def flag_entries(entries):
    daily_totals = defaultdict(float)
    title_day_groups = defaultdict(list)
    for e in entries:
        daily_totals[(e["Tech"], e["Date"])] += e["Hours"]
        title_day_groups[(e["Tech"], e["Date"], e["Title"])].append(e)

    flagged = []
    for e in entries:
        flags = []
        cat = classify(e["Title"])
        cap = CATEGORY_CAP.get(cat, DEFAULT_CAP)

        if cat.startswith("Routine:") and e["Hours"] > cap:
            flags.append(("H1", f"routine > {cap}h cap ({cat[9:]})"))
        if GENERIC_TITLE_RE.match(e["Title"]) and e["Hours"] > 0.5:
            flags.append(("H2", f"vague title '{e['Title']}' with {e['Hours']:.2f}h"))
        if e["Hours"] > ABSURD_SINGLE_ENTRY:
            flags.append(("H3", f"single entry {e['Hours']:.2f}h > {ABSURD_SINGLE_ENTRY}h"))
        day_tot = daily_totals[(e["Tech"], e["Date"])]
        if day_tot > ABSURD_DAILY_TOTAL:
            flags.append(("H4", f"tech daily total {day_tot:.2f}h > {ABSURD_DAILY_TOTAL}h"))
        grp = title_day_groups[(e["Tech"], e["Date"], e["Title"])]
        if len(grp) >= 2:
            grp_sum = sum(g["Hours"] for g in grp)
            if grp_sum > cap * DUPE_DAY_CAP_MULTIPLIER:
                flags.append(("H5", f"{len(grp)} entries same ticket/day totalling {grp_sum:.2f}h"))

        if flags:
            e2 = dict(e)
            e2["Category"] = cat
            e2["Cap"] = cap
            e2["DailyTotal"] = round(day_tot, 2)
            e2["FlagCodes"] = ";".join(f[0] for f in flags)
            e2["FlagReasons"] = " | ".join(f[1] for f in flags)
            flagged.append(e2)
    return flagged


def write_client_artifacts(client: str, entries, flagged):
    out = OUT_BYCLIENT / client
    out.mkdir(parents=True, exist_ok=True)

    # by-tech csv
    tech_totals = defaultdict(lambda: {"entries": 0, "hours": 0.0})
    for e in entries:
        t = tech_totals[e["Tech"]]
        t["entries"] += 1
        t["hours"] += e["Hours"]
    tech_agg = defaultdict(lambda: {"count": 0, "hours": 0.0, "flags": defaultdict(int)})
    for e in flagged:
        a = tech_agg[e["Tech"]]
        a["count"] += 1
        a["hours"] += e["Hours"]
        for code in e["FlagCodes"].split(";"):
            a["flags"][code] += 1
    rows = []
    for tech, agg in tech_agg.items():
        tot = tech_totals[tech]
        pct = (agg["hours"] / tot["hours"] * 100) if tot["hours"] else 0
        rows.append([tech, tot["entries"], round(tot["hours"], 2),
                     agg["count"], round(agg["hours"], 2), f"{pct:.1f}%",
                     agg["flags"].get("H1", 0), agg["flags"].get("H2", 0),
                     agg["flags"].get("H3", 0), agg["flags"].get("H4", 0),
                     agg["flags"].get("H5", 0)])
    rows.sort(key=lambda r: -r[4])
    with (out / "tech-outliers-by-tech.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Tech", "TotalEntries", "TotalHours", "FlaggedEntries",
                    "FlaggedHours", "FlaggedPctOfHours",
                    "H1_trivial_high", "H2_vague_title", "H3_entry>8h",
                    "H4_day>12h", "H5_dupe_day"])
        w.writerows(rows)

    # detail csv
    with (out / "tech-outliers-detail.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Tech", "POD", "Shift", "Title", "Category",
                    "Hours", "CategoryCap", "DailyTotal", "Flags", "Reasons", "Requestor"])
        for e in sorted(flagged, key=lambda x: (-x["Hours"], x["Date"])):
            w.writerow([e["Date"], e["Tech"], e["POD"], e["Shift"], e["Title"],
                        e["Category"], round(e["Hours"], 2), e["Cap"], e["DailyTotal"],
                        e["FlagCodes"], e["FlagReasons"], e["Requestor"]])

    # summary md
    total_h = sum(e["Hours"] for e in entries)
    flag_h = sum(e["Hours"] for e in flagged)
    with (out / "tech-outliers-summary.md").open("w", encoding="utf-8") as f:
        f.write(f"# {client.upper()} {YEAR} — Tech Time-Entry Outlier Review\n\n")
        f.write(f"**Entries scanned:** {len(entries):,}  \n")
        f.write(f"**Hours:** {total_h:,.2f}  \n")
        f.write(f"**Flagged entries:** {len(flagged):,} ({len(flagged)/max(len(entries),1)*100:.1f}%)  \n")
        f.write(f"**Flagged hours:** {flag_h:,.2f} ({flag_h/max(total_h,0.01)*100:.1f}%)  \n\n")
        if rows:
            f.write("## Techs ranked by flagged hours\n\n")
            f.write("| Tech | Total hrs | Flagged hrs | % | H1 | H2 | H3 | H4 | H5 |\n")
            f.write("|---|---:|---:|---:|---:|---:|---:|---:|---:|\n")
            for r in rows:
                f.write(f"| {r[0]} | {r[2]:,.1f} | {r[4]:,.1f} | {r[5]} | {r[6]} | {r[7]} | {r[8]} | {r[9]} | {r[10]} |\n")

    return len(entries), total_h, len(flagged), flag_h


def write_tech_artifacts(tech: str, tech_entries: list, all_flagged_for_tech: list):
    slug = slugify(tech)
    out = OUT_BYTECH / slug
    out.mkdir(parents=True, exist_ok=True)

    # all flagged for this tech (across clients) — with coaching columns
    with (out / "flagged-entries.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Client", "Date", "Title", "Category", "Hours", "CategoryCap",
                    "DailyTotal", "Flags", "Reasons",
                    "Why_Flagged", "Title_Must_Include",
                    "Good_Title_At_Cap", "Good_Title_To_Justify_Your_Hours"])
        for e in sorted(all_flagged_for_tech, key=lambda x: (-x["Hours"], x["Date"])):
            coach = build_coaching(e["Title"], e["Category"], e["Hours"])
            w.writerow([e["Client"].upper(), e["Date"], e["Title"], e["Category"],
                        round(e["Hours"], 2), e["Cap"], e["DailyTotal"],
                        e["FlagCodes"], e["FlagReasons"],
                        coach["WhyFlagged"], coach["MustInclude"],
                        coach["GoodExample_AtCap"], coach["GoodExample_Justified"]])

    # aggregates
    total_h = sum(e["Hours"] for e in tech_entries)
    flag_h = sum(e["Hours"] for e in all_flagged_for_tech)
    flag_n = len(all_flagged_for_tech)
    tot_n = len(tech_entries)
    flag_code_counts = defaultdict(int)
    cat_counts = defaultdict(lambda: {"n": 0, "h": 0.0})
    client_counts = defaultdict(lambda: {"n": 0, "h": 0.0})
    for e in all_flagged_for_tech:
        for c in e["FlagCodes"].split(";"):
            flag_code_counts[c] += 1
        cat_counts[e["Category"]]["n"] += 1
        cat_counts[e["Category"]]["h"] += e["Hours"]
        client_counts[e["Client"]]["n"] += 1
        client_counts[e["Client"]]["h"] += e["Hours"]

    # training md
    with (out / "training.md").open("w", encoding="utf-8") as f:
        f.write(f"# Personalized Tech Training — {tech}\n\n")
        f.write(f"**Period:** {YEAR} (all clients)  \n")
        f.write(f"**Total entries logged:** {tot_n:,}  \n")
        f.write(f"**Total hours logged:** {total_h:,.2f}  \n")
        f.write(f"**Flagged entries:** {flag_n} ({flag_n/max(tot_n,1)*100:.1f}%)  \n")
        f.write(f"**Flagged hours:** {flag_h:,.2f} ({flag_h/max(total_h,0.01)*100:.1f}%)  \n\n")

        f.write("## Flags breakdown\n\n")
        f.write("| Code | Count | Meaning |\n|---|---:|---|\n")
        legend = {"H1": "Routine work with hours exceeding category cap",
                  "H2": "Vague title (\"Help\", \"Fix\", etc.) with > 0.5h",
                  "H3": "Single entry > 8 hours",
                  "H4": "Tech daily total > 12 hours",
                  "H5": "Duplicate same-ticket same-day stacks"}
        for code in ["H1", "H2", "H3", "H4", "H5"]:
            if flag_code_counts[code]:
                f.write(f"| {code} | {flag_code_counts[code]} | {legend[code]} |\n")

        if client_counts:
            f.write("\n## Flagged entries by client\n\n")
            f.write("| Client | # flagged | Flagged hours |\n|---|---:|---:|\n")
            for c, v in sorted(client_counts.items(), key=lambda kv: -kv[1]["h"]):
                f.write(f"| {c.upper()} | {v['n']} | {v['h']:,.2f} |\n")

        if cat_counts:
            f.write("\n## Most-flagged work categories\n\n")
            f.write("| Category | # flagged | Flagged hours |\n|---|---:|---:|\n")
            for c, v in sorted(cat_counts.items(), key=lambda kv: -kv[1]["h"])[:10]:
                f.write(f"| {c} | {v['n']} | {v['h']:,.2f} |\n")

        f.write("\n## Your 10 most-flagged individual entries\n\n")
        f.write("| Client | Date | Hours | Cap | Title | Reason |\n|---|---|---:|---:|---|---|\n")
        for e in sorted(all_flagged_for_tech, key=lambda x: -x["Hours"])[:10]:
            t = e["Title"].replace("|", "\\|")[:60]
            r = e["FlagReasons"].replace("|", "\\|")[:80]
            f.write(f"| {e['Client'].upper()} | {e['Date']} | {e['Hours']:.2f} | {e['Cap']} | {t} | {r} |\n")

        # Coaching: per-entry rewrite suggestions
        f.write("\n## Coaching — what your titles should look like\n\n")
        f.write("For each of your top flagged entries below, you'll see what you wrote, "
                "the expected normal time for that work, what the title should have included, "
                "and two model rewrites: one that fits within the cap and one that justifies "
                "the higher hours you actually logged.\n\n")
        for e in sorted(all_flagged_for_tech, key=lambda x: -x["Hours"])[:8]:
            coach = build_coaching(e["Title"], e["Category"], e["Hours"])
            f.write(f"### {e['Client'].upper()} {e['Date']} — {e['Hours']:.2f}h logged on \"{e['Title'][:80]}\"\n\n")
            f.write(f"- **Category:** {e['Category']}  \n")
            f.write(f"- **Expected time for this category:** ≤ {coach['ExpectedHours']:.1f} hours  \n")
            f.write(f"- **Why flagged:** {coach['WhyFlagged']}  \n")
            f.write(f"- **A good title must include:** {coach['MustInclude']}\n\n")
            f.write(f"**You wrote:** _{coach['BadExample']}_  \n\n")
            f.write(f"**Model title within {coach['ExpectedHours']:.1f}h:**  \n")
            f.write(f"> {coach['GoodExample_AtCap']}\n\n")
            f.write(f"**Model title to justify {e['Hours']:.2f}h:**  \n")
            f.write(f"> {coach['GoodExample_Justified']}\n\n")

        f.write("\n## Personalized training focus\n\n")
        # pick the TOP flag-type for this tech and write targeted advice
        top_flag = max(flag_code_counts.items(), key=lambda kv: kv[1])[0] if flag_code_counts else None
        advice = {
            "H1": "**Your most common issue is over-claiming time on routine work.** For patch-management alerts, "
                  "agent version updates (CrowdStrike, ScreenConnect, MyRMM), CPU/memory/disk threshold alerts, "
                  "and similar auto-generated monitoring tickets, the expected resolution time is 0.25–1.0 hours. "
                  "If an alert genuinely takes longer, your title must explain why (e.g. \"Critical CPU — "
                  "investigated runaway SQL process\" instead of just \"Critical - CPU Utilization\").",
            "H2": "**Your most common issue is vague ticket titles.** Titles like \"Help\", \"Fix\", \"Issue\", "
                  "\"Test\" are not acceptable on any entry > 0.5 hour. Every title must describe what you actually "
                  "did: the system/user affected + the action taken. Example — instead of \"Help\", use "
                  "\"Help — Sarah's OneDrive sync stuck, rebuilt local cache\".",
            "H3": "**Your most common issue is logging whole-day dumps into a single entry.** If you worked 8+ hours "
                  "across a day, break it into separate entries per activity with individual time blocks and "
                  "descriptive titles.",
            "H4": "**Your daily totals are exceeding 12 hours across tickets.** This can happen if overnight work "
                  "is double-counted or if hours are claimed against the wrong date. Review your day-end entries "
                  "before submitting the timesheet.",
            "H5": "**Your most common issue is creating multiple entries on the same ticket on the same day.** "
                  "If you spent 4 hours on \"Server Issue\" in three separate blocks, consolidate them into one "
                  "entry with a single clear note covering the full scope of work. Multiple entries on the same "
                  "ticket look like duplicate billing in a client review.",
        }
        if top_flag:
            f.write(advice[top_flag] + "\n\n")
        f.write("### General time-entry rules\n\n")
        f.write("1. **Descriptive titles required** — no standalone \"Help\", \"Test\", \"Fix\", \"Issue\".\n")
        f.write("2. **One entry per ticket per day** — consolidate all work on the same ticket into one entry.\n")
        f.write("3. **Cap routine alerts at 1 hour** — if it takes longer, the title must explain why.\n")
        f.write("4. **Weekly Maintenance Window time must be split** across the covered clients, not wholesale logged to one.\n")
        f.write("5. **Agent updates are ~0.25 hr/machine** — if your update ticket goes over, describe the problem.\n")
        f.write("6. **Spot-check your own week** before submitting. If a title would confuse a client, rewrite it.\n")

    return {"tech": tech, "slug": slug, "total_entries": tot_n, "total_hours": total_h,
            "flagged_entries": flag_n, "flagged_hours": flag_h}


# =================== MAIN ===================
def main():
    clients_root = REPO / "clients"
    client_dirs = sorted(p for p in clients_root.iterdir() if p.is_dir())

    all_entries = []
    all_flagged = []
    client_results = []
    client_rollup = []
    per_tech_entries = defaultdict(list)
    per_tech_flagged = defaultdict(list)

    skipped = []
    for cd in client_dirs:
        code = cd.name.lower()
        if code == "archive":
            continue
        csv_path = find_time_entries_csv(cd, YEAR)
        if not csv_path:
            skipped.append((code, "no time-entries CSV"))
            continue
        try:
            entries = load_client_entries(code, csv_path, YEAR)
        except Exception as ex:
            skipped.append((code, f"load err: {ex}"))
            continue
        if not entries:
            skipped.append((code, f"no {YEAR} entries"))
            continue
        flagged = flag_entries(entries)
        scan_n, scan_h, flag_n, flag_h = write_client_artifacts(code, entries, flagged)
        client_rollup.append({
            "client": code, "entries": scan_n, "hours": scan_h,
            "flagged_entries": flag_n, "flagged_hours": flag_h,
            "pct": (flag_h / scan_h * 100) if scan_h else 0,
        })
        for e in entries:
            per_tech_entries[e["Tech"]].append(e)
        for e in flagged:
            per_tech_flagged[e["Tech"]].append(e)
        all_entries.extend(entries)
        all_flagged.extend(flagged)
        client_results.append(code)
        print(f"  {code}: {scan_n:4d} entries, {scan_h:7.1f}h — flagged {flag_n:3d} ({flag_h:6.1f}h, {flag_h/max(scan_h,0.01)*100:.1f}%)")

    # per tech — include all techs who logged time this year (even if no flags)
    tech_summaries = []
    for tech, tech_ents in per_tech_entries.items():
        flagged_for_tech = per_tech_flagged.get(tech, [])
        if not flagged_for_tech:
            continue  # skip techs with zero flags — no training needed
        summary = write_tech_artifacts(tech, tech_ents, flagged_for_tech)
        tech_summaries.append(summary)

    # All-flagged master CSV
    with (OUT_ROOT / "all-flagged-entries.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Client", "Date", "Tech", "Title", "Category", "Hours", "CategoryCap",
                    "DailyTotal", "Flags", "Reasons"])
        for e in sorted(all_flagged, key=lambda x: (x["Client"], -x["Hours"])):
            w.writerow([e["Client"].upper(), e["Date"], e["Tech"], e["Title"], e["Category"],
                        round(e["Hours"], 2), e["Cap"], e["DailyTotal"],
                        e["FlagCodes"], e["FlagReasons"]])

    # Top SUMMARY.md
    total_entries = sum(c["entries"] for c in client_rollup)
    total_hours = sum(c["hours"] for c in client_rollup)
    total_flagged = sum(c["flagged_entries"] for c in client_rollup)
    total_flag_hours = sum(c["flagged_hours"] for c in client_rollup)

    with (OUT_ROOT / "SUMMARY.md").open("w", encoding="utf-8") as f:
        f.write(f"# Technijian Tech Time-Entry Audit — {YEAR} (All Clients)\n\n")
        f.write(f"**Generated:** {datetime.now().isoformat(timespec='seconds')}\n\n")
        f.write(f"## Scope\n\n")
        f.write(f"- Clients analyzed: {len(client_rollup)}\n")
        f.write(f"- Entries scanned: {total_entries:,}\n")
        f.write(f"- Hours scanned: {total_hours:,.2f}\n")
        f.write(f"- Flagged entries: {total_flagged} ({total_flagged/max(total_entries,1)*100:.1f}%)\n")
        f.write(f"- Flagged hours: {total_flag_hours:,.2f} ({total_flag_hours/max(total_hours,0.01)*100:.1f}%)\n\n")

        f.write(f"## Per-client rollup ({len(client_rollup)} clients)\n\n")
        f.write("| Client | Entries | Hours | Flagged Entries | Flagged Hours | % Flagged |\n")
        f.write("|---|---:|---:|---:|---:|---:|\n")
        for c in sorted(client_rollup, key=lambda x: -x["flagged_hours"]):
            f.write(f"| {c['client'].upper()} | {c['entries']:,} | {c['hours']:,.1f} | {c['flagged_entries']} | {c['flagged_hours']:,.1f} | {c['pct']:.1f}% |\n")

        if skipped:
            f.write(f"\n## Skipped clients ({len(skipped)})\n\n")
            for code, reason in skipped:
                f.write(f"- **{code.upper()}** — {reason}\n")

        if tech_summaries:
            f.write(f"\n## Per-tech training folders\n\n")
            f.write(f"Individualized training documents in `by-tech/<tech>/training.md`. "
                    f"{len(tech_summaries)} techs have at least one flagged entry and a folder was created for each.\n\n")
            f.write("| Tech | Total hrs | Flagged hrs | Flagged entries | Folder |\n")
            f.write("|---|---:|---:|---:|---|\n")
            for s in sorted(tech_summaries, key=lambda x: -x["flagged_hours"]):
                f.write(f"| {s['tech']} | {s['total_hours']:,.1f} | {s['flagged_hours']:,.1f} | {s['flagged_entries']} | `by-tech/{s['slug']}/` |\n")

    print(f"\n==== DONE ====")
    print(f"Clients with data: {len(client_rollup)}  skipped: {len(skipped)}")
    print(f"Total flagged: {total_flagged} entries / {total_flag_hours:.1f}h across {len(tech_summaries)} techs")
    print(f"Outputs under: {OUT_ROOT}")


if __name__ == "__main__":
    main()
