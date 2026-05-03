"""Pull patch data from ManageEngine Endpoint Central MSP 11.

EC MSP 11's REST surface for managed customers is patch-focused. The two
exposed endpoints are:

    /dcapi/threats/patches              — all applicable patches (catalog)
    /dcapi/threats/systemreport/patches — per-system patch matrix

Both are scoped by ``customername=<MSP customer name>``. Customers are
enumerated via ``/api/1.4/desktop/customers``.

For each customer we write the catalog (patches.json), the missing-only
slice (patches_missing.json), the installed slice (patches_installed.json),
and the per-system report (systems_report.json).

Usage:
    python pull_all.py                          # all customers
    python pull_all.py --only AAVA,BWH          # restrict by customer name
    python pull_all.py --include-installed      # include installed patches
                                                  (skipped by default — large)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import me_ec_api as ec

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


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    n = len(data) if hasattr(data, "__len__") else 1
    print(f"  -> {path.relative_to(REPO_ROOT)} ({n} rows)")


def _safe(fn, *a, **kw):
    try:
        return fn(*a, **kw), None
    except requests.HTTPError as exc:
        return None, f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def pull_customer(client: ec.MEECClient, customer: dict, day_dir: Path, include_installed: bool) -> None:
    cust_name = customer.get("customer_name") or customer.get("company_name") or ""
    cust_id = customer.get("customer_id")
    slug = _slugify(cust_name)
    out_dir = day_dir / slug
    print(f"\n[{slug}] customer_id={cust_id} name={cust_name!r}")
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "_customer.json").write_text(
        json.dumps(customer, indent=2, default=str), encoding="utf-8"
    )

    patches, err = _safe(ec.applicable_patches, cust_name, client)
    if err:
        print(f"  patches: {err}")
    else:
        _write(out_dir / "patches.json", patches)

    missing, err = _safe(ec.missing_patches, cust_name, client)
    if err:
        print(f"  patches-missing: {err}")
    else:
        _write(out_dir / "patches_missing.json", missing)

    if include_installed:
        installed, err = _safe(ec.installed_patches, cust_name, client)
        if err:
            print(f"  patches-installed: {err}")
        else:
            _write(out_dir / "patches_installed.json", installed)

    sysrep, err = _safe(ec.system_patch_report, cust_name, client)
    if err:
        print(f"  systems-report: {err}")
    else:
        _write(out_dir / "systems_report.json", sysrep)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="Comma-separated customer names to include")
    ap.add_argument(
        "--include-installed",
        action="store_true",
        help="Also pull installed patches (large; skipped by default)",
    )
    ap.add_argument("--out-root", default=str(OUT_ROOT), help="Override output root")
    args = ap.parse_args(argv)

    out_root = Path(args.out_root)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir = out_root / day
    day_dir.mkdir(parents=True, exist_ok=True)

    client = ec.MEECClient()

    print(f"== ME EC MSP pull -> {day_dir} ==")

    customers, err = _safe(ec.list_customers, client)
    if err or not customers:
        print(f"FATAL: could not list customers -> {err or 'empty'}", file=sys.stderr)
        return 1
    (day_dir / "_customers.json").write_text(
        json.dumps(customers, indent=2, default=str), encoding="utf-8"
    )
    print(f"  {len(customers)} customers")

    only = None
    if args.only:
        only = {s.strip().upper() for s in args.only.split(",")}

    for customer in customers:
        cust_name = customer.get("customer_name") or customer.get("company_name") or ""
        slug = _slugify(cust_name)
        if only and slug not in only and cust_name.upper() not in only:
            continue
        try:
            pull_customer(client, customer, day_dir, args.include_installed)
        except Exception as exc:
            print(f"  ERROR pulling customer {slug}: {exc}", file=sys.stderr)

    print(f"\nDONE. Output: {day_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
