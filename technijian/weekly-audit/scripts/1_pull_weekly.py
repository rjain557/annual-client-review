"""Pull the last 7 days of time entries from the Client Portal for every active
client. Writes per-client raw + parsed data under
technijian/weekly-audit/<cycle>/raw/<client-code>/.

Cycle ID is derived from the current Pacific date (ISO week, e.g. 2026-W18).

Usage:
    python 1_pull_weekly.py
    python 1_pull_weekly.py --only AAVA,BWH
    python 1_pull_weekly.py --skip ORX
    python 1_pull_weekly.py --cycle 2026-W18 --start 2026-04-25 --end 2026-05-02
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _shared import (
    CLIENTPORTAL_SCRIPTS,
    cycle_dir,
    cycle_id_for,
    week_window,
    write_csv,
    write_json,
)

sys.path.insert(0, str(CLIENTPORTAL_SCRIPTS))
import cp_api  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated LocationCodes")
    ap.add_argument("--skip", action="append", default=[], help="LocationCode to skip (repeatable)")
    ap.add_argument("--cycle", help="cycle ID override (default = current ISO week)")
    ap.add_argument("--start", help="ISO start date override (default = today-7d)")
    ap.add_argument("--end", help="ISO end date override (default = today)")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    cycle = args.cycle or cycle_id_for()
    default_start, default_end = week_window()
    start = args.start or default_start
    end = args.end or default_end

    out_root = cycle_dir(cycle)
    raw_dir = out_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    skip = {s.upper() for s in args.skip for s in s.split(",") if s.strip()}
    only = None
    if args.only:
        only = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    print(f"[{datetime.now():%H:%M:%S}] cycle={cycle} window={start} -> {end}")
    print(f"  output: {out_root}")

    if args.dry_run:
        print("  --dry-run set, no API calls")
        return 0

    print(f"[{datetime.now():%H:%M:%S}] fetching active clients...")
    clients = cp_api.get_active_clients()
    print(f"  got {len(clients)} active clients")

    results = []
    for i, c in enumerate(clients, 1):
        code = (c.get("LocationCode") or "").upper()
        did = c.get("DirID")
        name = c.get("Location_Name") or ""
        if not code or did is None:
            print(f"  [{i}/{len(clients)}] SKIP (missing code/DirID): {c}")
            continue
        if code in skip:
            print(f"  [{i}/{len(clients)}] skip {code}")
            continue
        if only is not None and code not in only:
            continue

        client_dir = raw_dir / code.lower()
        client_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "LocationCode": code,
            "DirID": did,
            "Location_Name": name,
            "start": start,
            "end": end,
            "time_entry_count": 0,
            "errors": [],
        }
        try:
            xml = cp_api.get_time_entries_xml(did, start, end)
            (client_dir / "time_entries.xml").write_text(xml or "", encoding="utf-8")
            tes = cp_api.parse_flat_xml(xml, "TimeEntry")
            summary["time_entry_count"] = len(tes)
            (client_dir / "time_entries.json").write_text(
                json.dumps(tes, indent=2), encoding="utf-8")
            write_csv(client_dir / "time_entries.csv", tes)
        except Exception as e:
            summary["errors"].append({"step": "time_entries",
                                       "err": str(e),
                                       "tb": traceback.format_exc()})

        (client_dir / "pull_summary.json").write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8")
        results.append(summary)
        print(f"  [{i}/{len(clients)}] {code:<8s} DirID={did:<6d} entries={summary['time_entry_count']}"
              f"{'  ERR' if summary['errors'] else ''}")

    log = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "cycle": cycle,
        "start": start,
        "end": end,
        "clients_attempted": len(results),
        "total_entries": sum(r["time_entry_count"] for r in results),
        "results": results,
    }
    write_json(out_root / "pull_log.json", log)
    print(f"\n[{datetime.now():%H:%M:%S}] DONE")
    print(f"  clients pulled: {len(results)}")
    print(f"  total entries:  {log['total_entries']:,}")
    print(f"  log:            {out_root / 'pull_log.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
