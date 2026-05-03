"""
Pull tenant summary from Veeam Backup for Microsoft 365.

For every organization the VB365 server protects, collects:
  - tenant name + officeName + Microsoft tenant id (msid)
  - userCount        : paginated count of /Organizations/{id}/users
                       (when jobBackupType is EntireOrganization, this == users backed up)
  - usedSpaceBytes   : sum of usedSpaceBytes from /Organizations/{id}/usedRepositories
  - localCacheBytes / objectStorageBytes : same source, separate buckets
  - repositories     : per-repo entry with repo name + bytes
  - jobs             : per-job summary (backupType, lastRun, lastStatus)

Outputs:
  clients/_veeam_365/tenant_summary.json     # full structured dump
  clients/_veeam_365/tenant_summary.csv      # one row per tenant for quick view
  console                                    # human table

Usage:
  python pull_tenant_summary.py
  python pull_tenant_summary.py --only JDH,BWH
  python pull_tenant_summary.py --skip-users      # skip the per-org user pagination (much faster)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from veeam_client import VeeamClient

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "clients" / "_veeam_365"
USER_PAGE_LIMIT = 500


def humanize_bytes(n: int | None) -> str:
    if n is None:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.2f} {u}"
        f /= 1024
    return f"{n} B"


def count_users(c: VeeamClient, org_id: str) -> int:
    """Walk /Organizations/{id}/users until exhausted, returning total count."""
    n = 0
    for _ in c.get_paginated(f"/Organizations/{org_id}/users", limit=USER_PAGE_LIMIT):
        n += 1
    return n


def used_repositories(c: VeeamClient, org_id: str) -> list[dict]:
    """Per-org per-repository used-space entries."""
    return list(c.get_paginated(f"/Organizations/{org_id}/usedRepositories"))


def jobs_for_org(c: VeeamClient, org_id: str, all_jobs: list[dict]) -> list[dict]:
    """Filter the global jobs list down to one tenant."""
    return [
        {
            "id": j["id"],
            "name": j.get("name"),
            "backupType": j.get("backupType"),
            "lastRun": j.get("lastRun"),
            "nextRun": j.get("nextRun"),
            "lastStatus": j.get("lastStatus"),
            "isEnabled": j.get("isEnabled"),
            "repositoryId": j.get("repositoryId"),
        }
        for j in all_jobs
        if j.get("organizationId") == org_id
    ]


def build_summary(only: set[str] | None, skip_users: bool) -> list[dict]:
    c = VeeamClient()
    print(f"Logging in to {c.base} ...", file=sys.stderr)
    c._login()
    print(f"  ok, api_version={c.api_version}", file=sys.stderr)

    print("Listing organizations ...", file=sys.stderr)
    orgs = c.list_organizations()
    print(f"  {len(orgs)} organizations", file=sys.stderr)

    print("Listing repositories ...", file=sys.stderr)
    repos = c.list_backup_repositories()
    repo_by_id = {r["id"]: r for r in repos}
    print(f"  {len(repos)} backup repositories", file=sys.stderr)

    print("Listing jobs ...", file=sys.stderr)
    jobs = c.list_jobs()
    print(f"  {len(jobs)} backup jobs", file=sys.stderr)

    rows: list[dict] = []
    for o in orgs:
        name = o.get("name") or o.get("officeName") or o["id"]
        if only and name.upper() not in only:
            continue
        print(f"  • {name}", file=sys.stderr)

        used = used_repositories(c, o["id"])
        repo_entries = []
        total_used = 0
        total_local_cache = 0
        total_object = 0
        for u in used:
            repo_link = ((u.get("_links") or {}).get("backupRepository") or {}).get("href", "")
            repo_id = repo_link.rsplit("/", 1)[-1] if repo_link else None
            repo = repo_by_id.get(repo_id) if repo_id else None
            entry = {
                "repositoryId": repo_id,
                "repositoryName": (repo or {}).get("name"),
                "repositoryPath": (repo or {}).get("path"),
                "usedSpaceBytes": u.get("usedSpaceBytes", 0),
                "localCacheUsedSpaceBytes": u.get("localCacheUsedSpaceBytes", 0),
                "objectStorageUsedSpaceBytes": u.get("objectStorageUsedSpaceBytes", 0),
                "isAvailable": u.get("isAvailable"),
                "capacityBytes": (repo or {}).get("capacityBytes"),
                "freeSpaceBytes": (repo or {}).get("freeSpaceBytes"),
            }
            repo_entries.append(entry)
            total_used += entry["usedSpaceBytes"] or 0
            total_local_cache += entry["localCacheUsedSpaceBytes"] or 0
            total_object += entry["objectStorageUsedSpaceBytes"] or 0

        org_jobs = jobs_for_org(c, o["id"], jobs)
        backup_types = sorted({j["backupType"] for j in org_jobs if j.get("backupType")})

        if skip_users:
            user_count: int | None = None
        else:
            try:
                user_count = count_users(c, o["id"])
            except Exception as e:
                print(f"    !! count_users failed: {e}", file=sys.stderr)
                user_count = None

        rows.append({
            "id": o["id"],
            "name": name,
            "officeName": o.get("officeName"),
            "msid": o.get("msid"),
            "type": o.get("type"),
            "region": o.get("region"),
            "isExchangeOnline": o.get("isExchangeOnline"),
            "isSharePointOnline": o.get("isSharePointOnline"),
            "isTeamsOnline": o.get("isTeamsOnline"),
            "userCount": user_count,
            "usedSpaceBytes": total_used,
            "localCacheUsedSpaceBytes": total_local_cache,
            "objectStorageUsedSpaceBytes": total_object,
            "repositories": repo_entries,
            "jobs": org_jobs,
            "jobBackupTypes": backup_types,
        })
    return rows


def write_outputs(rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "pulledAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tenantCount": len(rows),
        "totals": {
            "userCount": sum((r["userCount"] or 0) for r in rows),
            "usedSpaceBytes": sum(r["usedSpaceBytes"] for r in rows),
        },
        "tenants": rows,
    }
    (OUT_DIR / "tenant_summary.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )

    csv_path = OUT_DIR / "tenant_summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "name", "officeName", "userCount",
            "usedSpaceBytes", "usedSpaceHuman",
            "objectStorageUsedSpaceBytes", "jobBackupTypes",
            "repositoryCount",
        ])
        for r in rows:
            w.writerow([
                r["name"],
                r["officeName"],
                r["userCount"] if r["userCount"] is not None else "",
                r["usedSpaceBytes"],
                humanize_bytes(r["usedSpaceBytes"]),
                r["objectStorageUsedSpaceBytes"],
                "|".join(r["jobBackupTypes"]),
                len(r["repositories"]),
            ])

    print(f"\nWrote {OUT_DIR / 'tenant_summary.json'}")
    print(f"Wrote {csv_path}")


def print_table(rows: list[dict]) -> None:
    rows_sorted = sorted(rows, key=lambda r: -r["usedSpaceBytes"])
    name_w = max(8, max((len(str(r["name"])) for r in rows_sorted), default=8))
    office_w = max(12, max((len(str(r.get("officeName") or "")) for r in rows_sorted), default=12))

    fmt = f"  {{:<{name_w}}}  {{:<{office_w}}}  {{:>8}}  {{:>14}}  {{:>4}}  {{}}"
    print()
    print(fmt.format("Tenant", "M365 tenant", "Users", "Backup size", "Jobs", "Backup types"))
    print(fmt.format("-" * name_w, "-" * office_w, "--------", "--------------", "----", "------------"))
    total_users = 0
    total_used = 0
    for r in rows_sorted:
        users = r["userCount"]
        users_str = "?" if users is None else str(users)
        total_users += users or 0
        total_used += r["usedSpaceBytes"]
        print(fmt.format(
            r["name"][:name_w],
            (r.get("officeName") or "")[:office_w],
            users_str,
            humanize_bytes(r["usedSpaceBytes"]),
            len(r["jobs"]),
            ",".join(r["jobBackupTypes"]) or "-",
        ))
    print(fmt.format(
        f"TOTAL ({len(rows_sorted)})", "", str(total_users), humanize_bytes(total_used), "", ""
    ))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated tenant names (case-insensitive)")
    ap.add_argument("--skip-users", action="store_true", help="skip user-count pagination (much faster)")
    args = ap.parse_args()
    only = {x.strip().upper() for x in args.only.split(",")} if args.only else None
    rows = build_summary(only=only, skip_users=args.skip_users)
    write_outputs(rows)
    print_table(rows)


if __name__ == "__main__":
    main()
