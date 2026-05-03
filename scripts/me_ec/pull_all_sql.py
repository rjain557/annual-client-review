"""Full-SQL pull from ManageEngine Endpoint Central MSP 11 backend.

Companion to pull_all.py (REST). Pulls everything the REST API doesn't
expose, scoped per customer:

    inventory_computers.json    — hardware/OS/warranty per endpoint
    installed_software.json     — software catalog per endpoint
    patches_missing.json        — missing patches per endpoint
    patches_installed.json      — installed patches per endpoint (with deploy time + error code)
    patches_superceded.json     — historical installed-then-superseded
    patch_scan_status.json      — last-scan time per endpoint
    per_machine_patch_summary.json — aggregate counts per endpoint
    customer_event_log.json     — EC server events for the customer (last 90 days)
    hardware_audit.json         — hardware add/remove audit
    software_audit.json         — software install/uninstall audit

Plus at the day root:
    _customers.json             — all 32 customers
    _performance_status.json    — diagnostic showing whether EI is enabled

Usage:
    python pull_all_sql.py                      # all customers
    python pull_all_sql.py --only AAVA,BWH      # restrict
    python pull_all_sql.py --skip-events        # skip events (faster)
    python pull_all_sql.py --skip-software      # skip software (largest table)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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
    s = "".join(keep).strip("_")
    return s or "UNKNOWN"


def _write(path: Path, data) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    n = len(data) if hasattr(data, "__len__") else 1
    print(f"  -> {path.relative_to(REPO_ROOT)} ({n} rows)")
    return n


def _safe(label: str, fn, *a, **kw):
    t0 = time.monotonic()
    try:
        out = fn(*a, **kw)
        print(f"  [{time.monotonic()-t0:5.1f}s] {label}: {len(out) if hasattr(out, '__len__') else 1}")
        return out
    except Exception as exc:
        print(f"  [{time.monotonic()-t0:5.1f}s] {label}: ERROR {type(exc).__name__}: {str(exc)[:200]}")
        return None


def pull_customer(conn, customer: dict, day_dir: Path, *, skip_software: bool, skip_events: bool, since_ms: int | None) -> None:
    cust_name = customer["CUSTOMER_NAME"]
    cust_id = int(customer["CUSTOMER_ID"])
    slug = _slugify(cust_name)
    out_dir = day_dir / slug
    print(f"\n[{slug}] customer_id={cust_id} name={cust_name!r}")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "_customer_sql.json").write_text(
        json.dumps(customer, indent=2, default=str), encoding="utf-8"
    )

    computers = _safe("inventory_computers", sql.list_computers, conn, cust_id)
    if computers is not None:
        _write(out_dir / "inventory_computers.json", computers)

    if not skip_software:
        sw = _safe("installed_software", sql.installed_software, conn, cust_id)
        if sw is not None:
            _write(out_dir / "installed_software.json", sw)

    summary = _safe("per_machine_patch_summary", sql.per_machine_patch_summary, conn, cust_id)
    if summary is not None:
        _write(out_dir / "per_machine_patch_summary.json", summary)

    miss = _safe("patches_missing", sql.missing_patches, conn, cust_id)
    if miss is not None:
        _write(out_dir / "patches_missing_sql.json", miss)

    inst = _safe("patches_installed", sql.installed_patches, conn, cust_id)
    if inst is not None:
        _write(out_dir / "patches_installed_sql.json", inst)

    sup = _safe("patches_superceded", sql.superceded_installed, conn, cust_id)
    if sup is not None:
        _write(out_dir / "patches_superceded.json", sup)

    scan = _safe("patch_scan_status", sql.patch_scan_status, conn, cust_id)
    if scan is not None:
        _write(out_dir / "patch_scan_status.json", scan)

    if not skip_events:
        events = _safe("customer_event_log", sql.customer_event_log, conn, cust_id, since_ms, 5000)
        if events is not None:
            _write(out_dir / "customer_event_log.json", events)

    hw_audit = _safe("hardware_audit", sql.hardware_audit_history, conn, cust_id, 10000)
    if hw_audit is not None:
        _write(out_dir / "hardware_audit.json", hw_audit)

    sw_audit = _safe("software_audit", sql.software_audit_history, conn, cust_id, 10000)
    if sw_audit is not None:
        _write(out_dir / "software_audit.json", sw_audit)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="Comma-separated customer names")
    ap.add_argument("--skip-software", action="store_true", help="Skip per-machine installed software (largest table)")
    ap.add_argument("--skip-events", action="store_true", help="Skip customer event log")
    ap.add_argument("--event-window-days", type=int, default=90, help="Event log window (default 90)")
    ap.add_argument("--out-root", default=str(OUT_ROOT))
    args = ap.parse_args(argv)

    out_root = Path(args.out_root)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir = out_root / day
    day_dir.mkdir(parents=True, exist_ok=True)

    since_ms = int((datetime.now(timezone.utc).timestamp() - args.event_window_days * 86400) * 1000)

    print(f"== ME EC SQL pull -> {day_dir} (event window: {args.event_window_days}d) ==")

    with sql.connect() as conn:
        customers = sql.list_customers(conn)
        (day_dir / "_customers_sql.json").write_text(
            json.dumps(customers, indent=2, default=str), encoding="utf-8"
        )
        print(f"  {len(customers)} customers in CustomerInfo")

        perf = sql.performance_status(conn)
        (day_dir / "_performance_status.json").write_text(
            json.dumps(perf, indent=2, default=str), encoding="utf-8"
        )
        ei = perf["endpoint_insight"]
        print(
            f"  Endpoint Insight: any_enabled={ei['any_enabled']} "
            f"any_data={ei['any_data_collected']} "
            f"row_counts={perf['perf_table_rowcounts']}"
        )

        only = None
        if args.only:
            only = {s.strip().upper() for s in args.only.split(",")}

        for customer in customers:
            cust_name = customer["CUSTOMER_NAME"]
            slug = _slugify(cust_name)
            if only and slug not in only and cust_name.upper() not in only:
                continue
            try:
                pull_customer(
                    conn,
                    customer,
                    day_dir,
                    skip_software=args.skip_software,
                    skip_events=args.skip_events,
                    since_ms=since_ms,
                )
            except Exception as exc:
                print(f"  ERROR pulling customer {slug}: {exc}", file=sys.stderr)

    print(f"\nDONE. Output: {day_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
