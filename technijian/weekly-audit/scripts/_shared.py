"""Shared helpers for the weekly time-entry audit skill.

All weekly-audit scripts import from this module. Keeps classification rules,
flag-outlier logic, fingerprinting, and path conventions in one place.

The classification rules and category caps are intentionally identical to
technijian/tech-training/scripts/_audit-all-clients.py so the weekly skill
flags the same things the annual review flags.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

csv.field_size_limit(10_000_000)

SCRIPTS = Path(__file__).resolve().parent
WEEKLY_AUDIT = SCRIPTS.parent
REPO = WEEKLY_AUDIT.parent.parent
STATE_DIR = WEEKLY_AUDIT / "state"
RAW_ROOT = WEEKLY_AUDIT
BY_TECH_HISTORY = WEEKLY_AUDIT / "by-tech"

# Make the existing tech-training scripts importable for coaching + secrets.
TECH_TRAINING_SCRIPTS = REPO / "technijian" / "tech-training" / "scripts"
CLIENTPORTAL_SCRIPTS = REPO / "scripts" / "clientportal"
sys.path.insert(0, str(TECH_TRAINING_SCRIPTS))
sys.path.insert(0, str(CLIENTPORTAL_SCRIPTS))

PACIFIC = ZoneInfo("America/Los_Angeles")


# ---------------------------------------------------------------------------
# Classification (mirrors _audit-all-clients.py)
# ---------------------------------------------------------------------------

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
    ("Routine: Monitoring alert - device down / offline",
     re.compile(r"\bdevice\s*(not\s*responding|down)\b|\bnot\s*contact(ed)?\s*agent\b|\bprobably\s*down\b|\bno\s*response\s*from\s*device\b|\boffline\b", re.I)),
    ("Routine: Monitoring alert - CPU / memory / disk",
     re.compile(r"\b(cpu|memory|disk|bandwidth|drive\s*space)\s*utilization\b|\bthreshold\b|\bhigh\s*(cpu|memory|disk)\b", re.I)),
    ("Routine: Monitoring alert - generic critical / MonitorField",
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
    "Routine: Monitoring alert - CPU / memory / disk": 0.75,
    "Routine: Monitoring alert - device down / offline": 0.75,
    "Routine: Monitoring alert - generic critical / MonitorField": 0.75,
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
    return re.sub(r"[^A-Za-z0-9]+", "-", (name or "").strip()).strip("-") or "unknown"


# ---------------------------------------------------------------------------
# Fingerprinting (used for diff between Wed pull and Fri re-pull)
# ---------------------------------------------------------------------------

def fingerprint(entry: dict) -> str:
    """Stable ID for a time entry. Prefers InvDetID when present, otherwise hash
    of (Resource, StartDateTime, Title) which is unique enough in practice.
    """
    inv_id = (entry.get("InvDetID") or "").strip()
    if inv_id:
        return f"invid:{inv_id}"
    parts = "|".join([
        (entry.get("Resource") or entry.get("AssignedName") or "").strip().lower(),
        (entry.get("StartDateTime") or entry.get("TimeEntryDate") or "").strip(),
        (entry.get("Title") or "").strip().lower(),
    ])
    return "h:" + hashlib.sha1(parts.encode("utf-8")).hexdigest()[:16]


def parse_hours(row: dict) -> float:
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


# ---------------------------------------------------------------------------
# Flagging
# ---------------------------------------------------------------------------

def flag_entries(entries: list[dict]) -> list[dict]:
    """Return list of flagged entries with FlagCodes/Reasons/Cap/DailyTotal added.
    Entries should be normalized rows (dicts with Tech, Date, Title, Hours).
    """
    daily_totals: dict = defaultdict(float)
    title_day_groups: dict = defaultdict(list)
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


# ---------------------------------------------------------------------------
# Week / cycle helpers
# ---------------------------------------------------------------------------

def now_pacific() -> datetime:
    return datetime.now(tz=PACIFIC)


def cycle_id_for(d: datetime | None = None) -> str:
    """ISO-week cycle ID, e.g. 2026-W18.  Wednesday of the week the audit runs."""
    d = d or now_pacific()
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def cycle_dir(cycle: str | None = None) -> Path:
    p = WEEKLY_AUDIT / (cycle or cycle_id_for())
    p.mkdir(parents=True, exist_ok=True)
    return p


def week_window(d: datetime | None = None) -> tuple[str, str]:
    """Return (start_iso, end_iso) covering the prior 7 days (inclusive).
    end = today (Pacific), start = end - 7 days.
    """
    end = (d or now_pacific()).date()
    start = end - timedelta(days=7)
    return start.isoformat(), end.isoformat()


def state_path(name: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / name


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_csv(path: Path, rows: list[dict], cols: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    if cols is None:
        seen, cols = set(), []
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    cols.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: (", ".join(r[c]) if isinstance(r.get(c), list) else r.get(c, "")) for c in cols})


# ---------------------------------------------------------------------------
# Normalize a raw time-entry row into the audit shape
# ---------------------------------------------------------------------------

def normalize_entry(row: dict, client_code: str) -> dict | None:
    """Convert a raw client-portal time-entry row (XML-derived dict OR CSV row)
    into the canonical audit shape. Returns None for zero-hour rows.
    """
    date_iso = (row.get("TimeEntryDate") or row.get("Date") or "")[:10]
    if not date_iso:
        return None
    hrs = parse_hours(row)
    if hrs <= 0:
        return None
    tech = (row.get("AssignedName") or row.get("Resource") or "").strip() or "(unassigned)"
    return {
        "Fingerprint": fingerprint(row),
        "InvDetID": (row.get("InvDetID") or "").strip(),
        "Client": client_code,
        "Date": date_iso,
        "Title": (row.get("Title") or "").strip(),
        "Tech": tech,
        "POD": row.get("Office-POD") or row.get("PODDet") or "",
        "Shift": row.get("HourType") or "",
        "Hours": hrs,
        "Requestor": (row.get("Requestor") or "").strip(),
        "StartDateTime": row.get("StartDateTime") or "",
        "EndDateTime": row.get("EndDateTime") or "",
        "Notes": (row.get("Notes") or row.get("InvDescription") or "").strip(),
    }


# ---------------------------------------------------------------------------
# Entry-changed detection (used by 5_enforce_48h.py)
# ---------------------------------------------------------------------------

def entry_changed(original: dict, current: dict | None) -> tuple[bool, str]:
    """Decide whether the tech adjusted the entry (title or hours).
    Returns (was_changed, reason).
    """
    if current is None:
        return True, "deleted by tech"
    # hours: any reduction or change of >0.05 counts
    try:
        oh = float(original.get("Hours") or 0)
        ch = float(current.get("Hours") or 0)
        if abs(oh - ch) > 0.05:
            return True, f"hours adjusted {oh:.2f} -> {ch:.2f}"
    except (TypeError, ValueError):
        pass
    # title: case-insensitive normalized compare; consider changed if Levenshtein-ish ratio < 0.85
    ot = (original.get("Title") or "").strip().lower()
    nt = (current.get("Title") or "").strip().lower()
    if ot != nt:
        # crude similarity: if one side is a strict substring of the other AND length differs by > 10 chars,
        # treat as a meaningful rewrite. Otherwise small typo-level changes are fine.
        if len(nt) - len(ot) > 10 or len(ot) - len(nt) > 10:
            return True, "title rewritten"
        # word-level overlap: < 60% overlap means rewritten
        ow = set(re.findall(r"\w+", ot))
        nw = set(re.findall(r"\w+", nt))
        if not ow or not nw:
            return True, "title rewritten"
        overlap = len(ow & nw) / max(len(ow | nw), 1)
        if overlap < 0.6:
            return True, "title rewritten"
    return False, "unchanged"
