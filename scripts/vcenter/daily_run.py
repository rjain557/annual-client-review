"""Daily vCenter pull + aggregate + per-client fan-out.

Triggered by Windows scheduled task `Technijian-DailyVCenterPull` (see workstation.md).

Sequence:
  1. Pull current snapshots (vms, datastores, luns, alerts) into .work/vcenter-<DATE>/
  2. Pull 5-min interval VM + storage perf for the past 25h (1h overlap safety margin)
  3. Run per_client_split to refresh clients/<code>/vcenter/<YEAR>/ snapshot files
  4. Aggregate the 5-min raw perf into daily peak/avg/p95 summaries and append
     to per-client accumulator files: vm_perf_daily.json + storage_perf_daily.json

After 365 daily runs we have full-year per-instance trend without ever asking
vCenter to retain it long-term. Required vCenter setting: 5-min interval at
collection level 3 (the daily/weekly/monthly intervals can stay at level 1).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL = Path(os.path.expanduser("~")) / ".claude" / "skills" / "vcenter-rest" / "scripts"

DEFAULT_OVERRIDES = REPO / "scripts" / "vcenter" / "client_overrides.json"


def run(*args: str, env: dict | None = None) -> None:
    print(f"[daily] $ {' '.join(args)}")
    e = os.environ.copy()
    e["PYTHONIOENCODING"] = "utf-8"
    if env:
        e.update(env)
    r = subprocess.run(args, env=e)
    if r.returncode != 0:
        raise SystemExit(f"[daily] command failed: rc={r.returncode}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default=str(dt.date.today().year))
    ap.add_argument("--keep-master", action="store_true",
                    help="Keep .work/vcenter-<DATE>/ after run (default: delete to save disk).")
    ap.add_argument("--skip-perf", action="store_true",
                    help="Skip 5-min perf pull (inventory + alerts only).")
    ap.add_argument("--skip-luns", action="store_true",
                    help="Skip per-LUN pyVmomi walk (much faster).")
    args = ap.parse_args()

    today = dt.date.today().isoformat()
    work = REPO / ".work" / f"vcenter-{today}"
    work.mkdir(parents=True, exist_ok=True)
    py = sys.executable

    # 1. Inventory + datastores + LUNs + alerts (master pull)
    dump_args = [
        py, str(SKILL / "dump_all.py"),
        "--out", str(work),
    ]
    if not args.skip_luns:
        dump_args.append("--with-luns")
    run(*dump_args)

    # 2. 5-min perf pull (1-day window with 1h safety overlap)
    if not args.skip_perf:
        run(py, str(SKILL / "get_vm_perf.py"),
            "--out", str(work / "vm_perf.json"),
            "--hours", "25", "--interval", "300")
        run(py, str(SKILL / "get_storage_perf.py"),
            "--out", str(work / "storage_perf.json"),
            "--hours", "25", "--interval", "300")

    # 3. Per-client split — refreshes snapshot files
    overrides = DEFAULT_OVERRIDES if DEFAULT_OVERRIDES.exists() else None
    split_args = [
        py, str(SKILL / "per_client_split.py"),
        "--src", str(work),
        "--out", str(REPO / "clients"),
        "--year", args.year,
    ]
    if overrides:
        split_args += ["--overrides", str(overrides)]
    run(*split_args)

    # 4. Aggregate 5-min perf -> daily summaries, append per-client
    if not args.skip_perf:
        clients_root = REPO / "clients"
        # Each client's vcenter folder gets its own daily-summary accumulator.
        # The split already wrote vm_perf.json and storage_perf.json per client at 5-min granularity.
        # We aggregate from those filtered files so each accumulator reflects only that client.
        for client_dir in sorted(clients_root.iterdir()):
            if not client_dir.is_dir():
                continue
            yr_dir = client_dir / "vcenter" / args.year
            vp = yr_dir / "vm_perf.json"
            sp = yr_dir / "storage_perf.json"
            if not vp.exists() and not sp.exists():
                continue  # no vcenter data for this client
            cmd = [py, str(SKILL / "aggregate_perf.py")]
            if vp.exists():
                cmd += ["--vm-perf", str(vp), "--vm-perf-out", str(yr_dir / "vm_perf_daily.json")]
            if sp.exists():
                cmd += ["--storage-perf", str(sp), "--storage-perf-out", str(yr_dir / "storage_perf_daily.json")]
            run(*cmd)

    # 5. Cleanup master dump (keeps disk usage flat across daily runs)
    if not args.keep_master:
        shutil.rmtree(work, ignore_errors=True)
        print(f"[daily] removed {work}")

    print(f"[daily] OK ({today})")


if __name__ == "__main__":
    main()
