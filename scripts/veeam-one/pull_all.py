"""
Veeam ONE one-shot pull orchestrator.

Runs every confirmed REST endpoint pull (vbr config + storage state, alarm
catalog, business view) in sequence and writes everything under
clients/_veeam_one/<YYYY-MM-DD>/.

Usage:
  python pull_all.py
  python pull_all.py --date 2026-05-02
  python pull_all.py --skip-alarms
  python pull_all.py --skip-bv
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--skip-vbr",    action="store_true")
    ap.add_argument("--skip-alarms", action="store_true")
    ap.add_argument("--skip-bv",     action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).parent))
    rc = 0

    if not args.skip_vbr:
        print("\n=== vbr / storage ===")
        import pull_vbr
        rc |= pull_vbr.main_args(args.date) if hasattr(pull_vbr, "main_args") \
              else _invoke(pull_vbr.main, ["--date", args.date])

    if not args.skip_alarms:
        print("\n=== alarms ===")
        import pull_alarms
        rc |= _invoke(pull_alarms.main, ["--date", args.date])

    if not args.skip_bv:
        print("\n=== business view ===")
        import pull_business_view as pull_bv
        rc |= _invoke(pull_bv.main, ["--date", args.date])

    print(f"\n=== veeam-one pull_all done — output: clients/_veeam_one/{args.date}/ ===")
    return rc


def _invoke(fn, argv: list[str]) -> int:
    saved = sys.argv
    sys.argv = ["veeam-one"] + argv
    try:
        return int(fn() or 0)
    finally:
        sys.argv = saved


if __name__ == "__main__":
    sys.exit(main())
