"""
Run the full Meraki daily pull: security events + network events + config snapshot.

This is the script you wire into the daily scheduler.

Usage:
  python pull_all.py                  # last 24h security & activity, full config snapshot
  python pull_all.py --days 7         # last 7 days for the event pulls
  python pull_all.py --skip-config    # skip the config snapshot (events only)
  python pull_all.py --skip-events    # snapshot only
  python pull_all.py --only VAF,BWH   # restrict to specific org slugs
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def run(script: str, extra: list[str]) -> int:
    cmd = [sys.executable, str(HERE / script)] + extra
    print(f"\n>>> {' '.join(cmd)}")
    proc = subprocess.run(cmd)
    return proc.returncode


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--only")
    p.add_argument("--skip")
    p.add_argument("--skip-config", action="store_true")
    p.add_argument("--skip-events", action="store_true")
    p.add_argument("--skip-network-events", action="store_true",
                   help="Skip per-network activity log (the slowest part)")
    p.add_argument("--output-root")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    common: list[str] = []
    if args.only:
        common += ["--only", args.only]
    if args.skip:
        common += ["--skip", args.skip]
    if args.output_root:
        common += ["--output-root", args.output_root]

    rc = 0
    if not args.skip_events:
        rc |= run("pull_security_events.py", common + ["--days", str(args.days)])
        if not args.skip_network_events:
            rc |= run("pull_network_events.py", common + ["--days", str(args.days)])

    if not args.skip_config:
        rc |= run("pull_configuration.py", common)

    print("\n=== Daily Meraki pull complete ===" if rc == 0
          else f"\n=== Daily Meraki pull finished with non-zero exit ({rc}) ===")
    return rc


if __name__ == "__main__":
    sys.exit(main())
