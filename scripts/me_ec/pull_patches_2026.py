"""Pull 2026 patch installs (per machine, monthly rollup) + patch windows
per client from the EC SQL backend.

Companion data set for the monthly client patch-activity report. Output:

    clients/_me_ec/<YYYY-MM-DD>/<SLUG>/
        patches_installed_2026.json
        patches_installed_2026_monthly.json
        patch_window.json
    clients/_me_ec/<YYYY-MM-DD>/
        _patch_windows_summary.json   — all 32 customers in one table

Usage:
    python pull_patches_2026.py
    python pull_patches_2026.py --only AAVA,BWH
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import me_ec_sql as sql

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = REPO_ROOT / "clients" / "_me_ec"


def _slugify(name: str) -> str:
    keep = []
    for ch in (name or "").strip():
        if ch.isalnum():
            keep.append(ch.upper())
        elif ch in (" ", "-", "_"):
            keep.append("_")
    return "".join(keep).strip("_") or "UNKNOWN"


def _write(path: Path, data) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    n = len(data) if hasattr(data, "__len__") else 1
    print(f"  -> {path.relative_to(REPO_ROOT)} ({n} rows)")
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="Comma-separated customer names")
    args = ap.parse_args(argv)

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir = OUT_ROOT / day
    day_dir.mkdir(parents=True, exist_ok=True)

    only = None
    if args.only:
        only = {s.strip().upper() for s in args.only.split(",")}

    print(f"== ME EC 2026 patch + window pull -> {day_dir} ==")

    with sql.connect() as conn:
        # All-customers patch-window summary first
        windows = sql.patch_windows(conn)
        _write(day_dir / "_patch_windows_summary.json", windows)

        # Group windows by customer for per-folder writes
        windows_by_customer: dict[int, list[dict]] = {}
        for w in windows:
            windows_by_customer.setdefault(int(w["CUSTOMER_ID"]), []).append(w)

        customers = sql.list_customers(conn)
        for customer in customers:
            cust_name = customer["CUSTOMER_NAME"]
            cust_id = int(customer["CUSTOMER_ID"])
            slug = _slugify(cust_name)
            if only and slug not in only and cust_name.upper() not in only:
                continue
            out_dir = day_dir / slug
            out_dir.mkdir(parents=True, exist_ok=True)
            print(f"\n[{slug}] customer_id={cust_id}")

            # Patch window for this customer
            cust_windows = windows_by_customer.get(cust_id, [])
            _write(out_dir / "patch_window.json", cust_windows)
            for w in cust_windows:
                print(
                    f"  window: task={w['TASKNAME']!r} status={w['task_status']} "
                    f"-> {w['window_summary']}"
                )

            # Per-machine 2026 installs (full detail)
            installs = sql.installed_patches_2026(conn, cust_id)
            _write(out_dir / "patches_installed_2026.json", installs)

            # Monthly rollup per machine
            monthly = sql.installed_patches_2026_per_machine_monthly(conn, cust_id)
            _write(out_dir / "patches_installed_2026_monthly.json", monthly)

    print(f"\nDONE. Output: {day_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
