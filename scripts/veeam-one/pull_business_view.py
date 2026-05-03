"""
Pull Business View categories + groups from Veeam ONE.

Business View is how Veeam ONE buckets infrastructure objects (VMs, hosts,
datastores) into logical groupings — typically used to map per-client SLA
tiers (Mission Critical / Standard / Archive) or storage classes. This is
the foundation for any per-client breakdown of VM/storage data.

Output:
  clients/_veeam_one/<YYYY-MM-DD>/
    business_view_categories.json
    business_view_groups.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import veeam_one_api as v

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    print(f"  wrote {p.relative_to(REPO_ROOT)}  ({p.stat().st_size} bytes)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else \
              REPO_ROOT / "clients" / "_veeam_one" / args.date
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[veeam-one bv] target: {out_dir}")

    print("[veeam-one] GET businessView/categories …")
    cats = v.list_business_view_categories()
    _write(out_dir / "business_view_categories.json", cats)

    print("[veeam-one] GET businessView/groups …")
    groups = v.list_business_view_groups()
    _write(out_dir / "business_view_groups.json", groups)

    print(f"\n[veeam-one bv] {len(cats)} categories, {len(groups)} groups")
    return 0


if __name__ == "__main__":
    sys.exit(main())
