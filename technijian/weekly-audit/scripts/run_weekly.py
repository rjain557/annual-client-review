"""End-to-end weekly orchestrator.

Runs the full pipeline in order:
  1) pull last 7 days of time entries from Client Portal
  2) flag outliers + build per-tech artifacts
  3) build branded Word docs per tech
  4) create + send Outlook drafts via M365 Graph

This is what the Friday 7am PST scheduled task on the workstation invokes.

Usage:
    python run_weekly.py
    python run_weekly.py --drafts-only          # stop after creating drafts
    python run_weekly.py --skip-email           # stop after building docs
    python run_weekly.py --cycle 2026-W18       # re-run a specific cycle
    python run_weekly.py --resume-from email    # skip earlier steps
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _shared import cycle_dir, cycle_id_for, write_json

PYTHON = sys.executable
STEPS = [
    ("pull",  HERE / "1_pull_weekly.py"),
    ("audit", HERE / "2_audit_weekly.py"),
    ("docs",  HERE / "3_build_weekly_docs.py"),
    ("email", HERE / "4_email_weekly.py"),
]


def run_step(name: str, script: Path, cycle: str, extra: list[str]) -> int:
    cmd = [PYTHON, str(script), "--cycle", cycle] + extra
    print(f"\n{'='*72}\n>>> step: {name}\n>>> {' '.join(cmd)}\n{'='*72}", flush=True)
    proc = subprocess.run(cmd)
    return proc.returncode


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycle", help="cycle ID (default = current ISO week)")
    ap.add_argument("--drafts-only", action="store_true",
                     help="email step creates drafts but does not send")
    ap.add_argument("--skip-email", action="store_true",
                     help="stop after building docs (steps 1-3 only)")
    ap.add_argument("--resume-from",
                     choices=[s[0] for s in STEPS],
                     help="skip steps before this one")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    cycle = args.cycle or cycle_id_for()
    out = cycle_dir(cycle)

    started = time.time()
    print(f"weekly-audit pipeline start  cycle={cycle}")
    print(f"output: {out}")

    skip_until = args.resume_from
    failures = []

    for name, script in STEPS:
        if skip_until and name != skip_until:
            print(f"--- skipping {name}")
            continue
        skip_until = None
        if name == "email" and args.skip_email:
            print("--- skip-email set; stopping before email step.")
            break
        extra = []
        if name == "email" and args.drafts_only:
            extra = ["--drafts-only"]
        rc = run_step(name, script, cycle, extra)
        if rc != 0:
            failures.append({"step": name, "returncode": rc})
            print(f"!! step {name} failed with rc={rc}; aborting pipeline.")
            break

    elapsed = round(time.time() - started, 1)
    log = {
        "cycle": cycle,
        "started_at_unix": started,
        "elapsed_seconds": elapsed,
        "drafts_only": args.drafts_only,
        "skip_email": args.skip_email,
        "resume_from": args.resume_from,
        "failures": failures,
        "ok": not failures,
    }
    write_json(out / "run_log.json", log)
    print(f"\n{'='*72}\nweekly-audit pipeline {'OK' if not failures else 'FAILED'}  ({elapsed}s)")
    print(f"run log: {out / 'run_log.json'}")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
