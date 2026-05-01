"""
Backfill Sophos Central Partner API data for all dates in 2026
that don't already have firewalls.json.

Runs pull_sophos_daily.py --date YYYY-MM-DD sequentially for each
missing date, oldest-first.

Usage:
    python backfill_sophos_2026.py
    python backfill_sophos_2026.py --from 2026-01-01 --to 2026-04-28
    python backfill_sophos_2026.py --only ani,bwh,vaf
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
CLIENTS_ROOT = REPO / "clients"
DAILY_SCRIPT = HERE / "pull_sophos_daily.py"

# Codes present in the Central Partner API mapping
CENTRAL_CODES = ["affg", "ani", "b2i", "bwh", "jdh", "kss", "orx", "taly", "vaf"]


def dates_range(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def has_data(d: date) -> bool:
    """True if ALL central codes already have firewalls.json for this date."""
    tag = d.strftime("%Y-%m-%d")
    return all(
        (CLIENTS_ROOT / code / "sophos" / tag / "firewalls.json").exists()
        for code in CENTRAL_CODES
    )


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", default="2026-01-01",
                    help="Start date inclusive (default 2026-01-01)")
    ap.add_argument("--to",   dest="end",   default="2026-04-28",
                    help="End date inclusive (default 2026-04-28)")
    ap.add_argument("--only", help="Comma-separated codes (default: all central codes)")
    ap.add_argument("--force", action="store_true",
                    help="Re-pull even if data already exists")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    only  = args.only  # pass-through to daily script if set

    all_dates = list(dates_range(start, end))
    missing = [d for d in all_dates
               if args.force or not has_data(d)]

    print(f"Sophos 2026 backfill: {start} to {end}")
    print(f"Total dates: {len(all_dates)}  Missing: {len(missing)}")
    if not missing:
        print("Nothing to backfill.")
        return 0

    print()
    ok = 0
    fail = 0
    for i, d in enumerate(missing, 1):
        tag = d.strftime("%Y-%m-%d")
        cmd = [sys.executable, str(DAILY_SCRIPT), "--date", tag]
        if only:
            cmd += ["--only", only]
        print(f"[{i}/{len(missing)}] {tag} ...", flush=True)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            ok += 1
            # Print last line of output (summary)
            lines = result.stdout.strip().splitlines()
            if lines:
                print(f"  OK  {lines[-1]}")
        else:
            fail += 1
            err = (result.stderr or result.stdout or "").strip().splitlines()
            print(f"  FAIL  {err[-1] if err else 'unknown error'}")

    print(f"\nBackfill complete: {ok} OK, {fail} failed out of {len(missing)} dates.")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
