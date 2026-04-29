"""Pull the prior calendar month of tickets + time entries from the Client Portal
for every active client. Writes per-client snapshots under
    clients/<code>/monthly/YYYY-MM/

Designed to run on the 1st of every month at 7:00 AM PT via Windows Scheduled
Task. When run on May 1, it captures the full month of April. The window is
[start_of_prior_month, start_of_current_month), so it never double-counts the
boundary day.

Usage:
    python pull_monthly.py                      # auto = prior calendar month
    python pull_monthly.py --month 2026-04      # explicit month
    python pull_monthly.py --only AAVA,BWH      # subset
    python pull_monthly.py --skip ORX           # exclude
    python pull_monthly.py --dry-run            # plan only, no API calls

Per-client output (under clients/<code>/monthly/YYYY-MM/):
    time_entries.xml          raw XML from stp_xml_TktEntry_List_Get
    time_entries.json         parsed array of time-entry dicts
    time_entries.csv          flat CSV
    tickets.json              unique tickets derived from time entries
    pull_summary.json         month, client, counts, errors

Run-level output:
    technijian/monthly-pull/state/<YYYY-MM>.json   summary log for the run
"""
from __future__ import annotations

import argparse
import calendar
import csv
import json
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
CLIENTPORTAL_SCRIPTS = REPO / "scripts" / "clientportal"
CLIENTS_ROOT = REPO / "clients"
STATE_DIR = HERE.parent / "state"

sys.path.insert(0, str(CLIENTPORTAL_SCRIPTS))
import cp_api  # noqa: E402


# ---------------------------------------------------------------------------
# Month-window helpers
# ---------------------------------------------------------------------------

def prior_month(today: date | None = None) -> tuple[str, str, str]:
    """Return (yyyy_mm, start_iso_inclusive, end_iso_exclusive) for the
    calendar month BEFORE `today` (default: today's local date)."""
    today = today or date.today()
    y, m = today.year, today.month
    if m == 1:
        py, pm = y - 1, 12
    else:
        py, pm = y, m - 1
    last_day = calendar.monthrange(py, pm)[1]
    start = date(py, pm, 1).isoformat()
    # API treats EndDate as inclusive in some SPs; we pass the last day of the
    # month to stay consistent with how get_time_entries_xml is used elsewhere.
    end = date(py, pm, last_day).isoformat()
    return f"{py:04d}-{pm:02d}", start, end


def parse_month_arg(s: str) -> tuple[str, str, str]:
    """`s` is YYYY-MM. Return (yyyy_mm, start_iso, end_iso)."""
    y_str, m_str = s.split("-")
    y, m = int(y_str), int(m_str)
    last_day = calendar.monthrange(y, m)[1]
    return f"{y:04d}-{m:02d}", date(y, m, 1).isoformat(), date(y, m, last_day).isoformat()


# ---------------------------------------------------------------------------
# Ticket derivation (same shape as scripts/clientportal/pull_all_active.py)
# ---------------------------------------------------------------------------

def derive_tickets(time_entries: list[dict]) -> list[dict]:
    """Group time entries by Title+Requestor to produce a unique-ticket list.
    The API time-entry XML doesn't carry a stable TicketID, but Title is the ticket
    subject and Requestor is the requester."""
    by_key: dict[tuple[str, str], dict] = {}
    for te in time_entries:
        key = (te.get("Title", ""), te.get("Requestor", ""))
        agg = by_key.setdefault(key, {
            "Title": key[0],
            "Requestor": key[1],
            "EntryCount": 0,
            "FirstEntry": None,
            "LastEntry": None,
            "TotalHours_NH": 0.0,
            "TotalHours_AH": 0.0,
            "TotalQty": 0.0,
            "Categories": set(),
            "Resources": set(),
        })
        agg["EntryCount"] += 1
        dt = te.get("TimeEntryDate")
        if dt:
            if not agg["FirstEntry"] or dt < agg["FirstEntry"]:
                agg["FirstEntry"] = dt
            if not agg["LastEntry"] or dt > agg["LastEntry"]:
                agg["LastEntry"] = dt

        def _f(x: str) -> float:
            try:
                return float(x)
            except Exception:
                return 0.0
        agg["TotalHours_NH"] += _f(te.get("NH_HoursWorked", "0"))
        agg["TotalHours_AH"] += _f(te.get("AH_HoursWorked", "0"))
        agg["TotalQty"] += _f(te.get("Qty", "0"))
        if te.get("Category"):
            agg["Categories"].add(te["Category"])
        if te.get("AssignedName"):
            agg["Resources"].add(te["AssignedName"])
    out = []
    for v in by_key.values():
        v["Categories"] = sorted(v["Categories"])
        v["Resources"] = sorted(v["Resources"])
        out.append(v)
    out.sort(key=lambda r: r.get("LastEntry") or "", reverse=True)
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    cols: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                cols.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: (", ".join(r[c]) if isinstance(r.get(c), list) else r.get(c, "")) for c in cols})


# ---------------------------------------------------------------------------
# Per-client pull
# ---------------------------------------------------------------------------

def pull_client(client: dict, yyyy_mm: str, start: str, end: str,
                dry_run: bool = False) -> dict:
    code = (client.get("LocationCode") or "").upper()
    did = client.get("DirID")
    name = client.get("Location_Name") or ""
    out_dir = CLIENTS_ROOT / code.lower() / "monthly" / yyyy_mm
    summary: dict = {
        "month": yyyy_mm,
        "LocationCode": code,
        "Location_Name": name,
        "DirID": did,
        "start": start,
        "end": end,
        "time_entry_count": 0,
        "ticket_count": 0,
        "errors": [],
        "dry_run": dry_run,
        "run_at": datetime.now().isoformat(timespec="seconds"),
    }
    if dry_run:
        return summary

    out_dir.mkdir(parents=True, exist_ok=True)

    # Time entries
    tes: list[dict] = []
    try:
        xml = cp_api.get_time_entries_xml(did, start, end)
        (out_dir / "time_entries.xml").write_text(xml or "", encoding="utf-8")
        tes = cp_api.parse_flat_xml(xml, "TimeEntry")
        summary["time_entry_count"] = len(tes)
        (out_dir / "time_entries.json").write_text(
            json.dumps(tes, indent=2), encoding="utf-8")
        write_csv(out_dir / "time_entries.csv", tes)
    except Exception as e:
        summary["errors"].append({"step": "time_entries", "err": str(e),
                                   "tb": traceback.format_exc()})

    # Derived tickets
    try:
        tks = derive_tickets(tes)
        summary["ticket_count"] = len(tks)
        (out_dir / "tickets.json").write_text(
            json.dumps(tks, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        summary["errors"].append({"step": "tickets", "err": str(e),
                                   "tb": traceback.format_exc()})

    (out_dir / "pull_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Pull last calendar month per active client.")
    ap.add_argument("--month", help="YYYY-MM target month (default: prior calendar month)")
    ap.add_argument("--only", help="comma-separated LocationCodes to include")
    ap.add_argument("--skip", action="append", default=[],
                    help="LocationCode to skip (repeatable, case-insensitive)")
    ap.add_argument("--dry-run", action="store_true",
                    help="List clients and window only; no API calls")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if args.month:
        yyyy_mm, start, end = parse_month_arg(args.month)
    else:
        yyyy_mm, start, end = prior_month()

    skip = {s.upper() for s in args.skip for s in s.split(",") if s.strip()}
    only = None
    if args.only:
        only = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    print(f"[{datetime.now():%H:%M:%S}] month={yyyy_mm} window={start} -> {end}")

    if args.dry_run:
        print("  --dry-run set, no API calls")
        return 0

    print(f"[{datetime.now():%H:%M:%S}] fetching active clients...")
    clients = cp_api.get_active_clients()
    print(f"  got {len(clients)} active clients")

    overall: list[dict] = []
    for i, c in enumerate(clients, 1):
        code = (c.get("LocationCode") or "").upper()
        did = c.get("DirID")
        if not code or did is None:
            print(f"  [{i}/{len(clients)}] SKIP (missing code/DirID): {c}")
            continue
        if code in skip:
            print(f"  [{i}/{len(clients)}] skip {code}")
            continue
        if only is not None and code not in only:
            continue
        s = pull_client(c, yyyy_mm, start, end, dry_run=args.dry_run)
        print(f"  [{i}/{len(clients)}] {code:<8s} DirID={did:<6d} entries={s['time_entry_count']:>4d}"
              f" tickets={s['ticket_count']:>4d}{'  ERR' if s['errors'] else ''}")
        overall.append(s)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "month": yyyy_mm,
        "start": start,
        "end": end,
        "clients_attempted": len(overall),
        "skipped": sorted(skip),
        "total_entries": sum(r["time_entry_count"] for r in overall),
        "total_tickets": sum(r["ticket_count"] for r in overall),
        "errors": [{"client": r["LocationCode"], "errors": r["errors"]} for r in overall if r["errors"]],
        "results": overall,
    }
    log_path = STATE_DIR / f"{yyyy_mm}.json"
    log_path.write_text(json.dumps(log, indent=2, default=str), encoding="utf-8")

    print(f"\n[{datetime.now():%H:%M:%S}] DONE")
    print(f"  clients pulled: {len(overall)}")
    print(f"  total entries:  {log['total_entries']:,}")
    print(f"  total tickets:  {log['total_tickets']:,}")
    print(f"  log:            {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
