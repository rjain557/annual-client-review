"""Per-instance and per-store storage report.

Prints a table sized like the SPE management console "Statistics" view:
  - one row per instance with totalSize / messages / users / store count
  - one indented row per archive store (path, requestedState, size, recovery flags)

Exit non-zero if any store has searchIndexesNeedRebuild, needsUpgrade, or error.

Usage:
  python list_storage.py
  python list_storage.py --json
"""
from __future__ import annotations

import argparse
import json
import sys

from spe_client import Client, SPEError, fmt_bytes, fmt_mb


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    c = Client()
    out = []
    bad = False
    instances = c.list_instances("*")

    for inst in sorted(instances, key=lambda i: i["instanceID"]):
        iid = inst["instanceID"]
        rec = {
            "instanceID": iid,
            "status": inst.get("status"),
            "host": inst.get("instanceHost"),
            "stats": {},
            "user_count": 0,
            "stores": [],
        }
        if inst.get("status") == "running":
            try:
                rec["stats"] = c.instance_statistics(iid)
                rec["user_count"] = len(c.users(iid))
                rec["stores"] = c.stores(iid, include_size=True)
            except SPEError as e:
                rec["error"] = str(e)
        out.append(rec)
        for s in rec["stores"]:
            if s.get("error") or s.get("searchIndexesNeedRebuild") or s.get("needsUpgrade"):
                bad = True

    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"{'instance':22s} {'status':10s} {'totalSize':>12s} {'messages':>12s} {'users':>6s} {'stores':>6s}")
        print(f"{'-'*22} {'-'*10} {'-'*12} {'-'*12} {'-'*6} {'-'*6}")
        for rec in out:
            stats = rec.get("stats") or {}
            print(f"{rec['instanceID'][:22]:22s} {(rec.get('status') or ''):10s} "
                  f"{fmt_mb(stats.get('totalSizeMB')):>12s} "
                  f"{(stats.get('numberOfMessages') or 0):>12d} "
                  f"{rec.get('user_count'):>6d} {len(rec['stores']):>6d}")
            for s in rec["stores"]:
                flags = []
                if s.get("error"): flags.append("ERROR")
                if s.get("searchIndexesNeedRebuild"): flags.append("INDEX-REBUILD")
                if s.get("needsUpgrade"): flags.append("NEEDS-UPGRADE")
                flag_str = " ".join(flags) if flags else "ok"
                print(f"   store {s.get('id'):>3} {s.get('name','?')[:18]:18s} "
                      f"{(s.get('requestedState') or '')[:10]:10s} "
                      f"{fmt_bytes(s.get('statisticsSize')):>12s} "
                      f"msgs={s.get('statisticsCount') or 0:>10d}  "
                      f"path={s.get('databasePath','?')}  [{flag_str}]")

    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
