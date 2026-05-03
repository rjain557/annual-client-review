"""
Full daily/monthly Veeam Backup for Microsoft 365 pull — feeds the monthly
report. For every protected tenant collects:

    tenant: {id, name, officeName, msid, services}
    repos:  per-repo capacity / free / used
    jobs:   per-tenant job summaries (lastRun, lastStatus, backupType)
    users:  per-user coverage flags
              {displayName, email, hasMailbox, hasOneDrive, hasArchive(?)}
            Mailbox coverage = covered by an EntireOrganization job (this is
            true for every protected tenant on this server today).
            OneDrive coverage = /users/{uid}/onedrives returns ≥1 entry.
            Archive coverage cannot be derived from REST → omitted (caveat
            documented in the report).
    modules:per-module estimated bytes for the *current* repo total —
            attribution from the share of restore points (last 30 days)
            that include each service flag, weighted by industry-default
            ratios when no signal exists.
    history:list of {date, totalBytes, perModuleBytes} rebuilt by reading
            existing snapshots in clients/_veeam_365/snapshots/.

Outputs (per run):
    clients/_veeam_365/snapshots/<YYYY-MM-DD>.json          # daily snapshot
    clients/_veeam_365/tenant_summary.json                  # latest summary
    clients/<slug>/veeam-365/<YYYY-MM-DD>/data.json         # per-tenant feed
                                                              for the report

Usage:
    python pull_full.py
    python pull_full.py --only JDH,BWH
    python pull_full.py --skip-user-onedrives    # 10x faster; no OneDrive coverage
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from veeam_client import VeeamClient
from _tenant_mapping import slug_for, display_for

REPO_ROOT = Path(__file__).resolve().parents[2]
GLOBAL_OUT = REPO_ROOT / "clients" / "_veeam_365"
SNAP_DIR = GLOBAL_OUT / "snapshots"

# Industry-default per-module ratios used when a tenant has *all* services on.
# These are rough seed weights only — real bytes are reweighted per tenant
# using restore-point service-flag frequencies.
DEFAULT_MODULE_WEIGHT = {
    "Exchange":   0.55,   # mailbox content typically dominates
    "OneDrive":   0.25,
    "SharePoint": 0.15,
    "Teams":      0.05,
}
RP_HISTORY_DAYS = 90


def humanize_bytes(n: int | float | None) -> str:
    if n is None:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.2f} {u}"
        f /= 1024
    return f"{n} B"


def collect_tenant(c: VeeamClient, o: dict, all_repos: dict, all_jobs: list[dict],
                   recent_rps: list[dict], pull_user_onedrives: bool) -> dict:
    org_id = o["id"]
    name = o.get("name") or o.get("officeName") or org_id

    # repositories used by this tenant
    used = list(c.get_paginated(f"/Organizations/{org_id}/usedRepositories"))
    repos = []
    total_used = 0
    total_local_cache = 0
    total_object = 0
    for u in used:
        link = ((u.get("_links") or {}).get("backupRepository") or {}).get("href", "")
        rid = link.rsplit("/", 1)[-1] if link else None
        repo = all_repos.get(rid) if rid else None
        entry = {
            "repositoryId": rid,
            "repositoryName": (repo or {}).get("name"),
            "repositoryPath": (repo or {}).get("path"),
            "usedSpaceBytes": u.get("usedSpaceBytes", 0) or 0,
            "localCacheUsedSpaceBytes": u.get("localCacheUsedSpaceBytes", 0) or 0,
            "objectStorageUsedSpaceBytes": u.get("objectStorageUsedSpaceBytes", 0) or 0,
            "capacityBytes": (repo or {}).get("capacityBytes"),
            "freeSpaceBytes": (repo or {}).get("freeSpaceBytes"),
        }
        repos.append(entry)
        total_used += entry["usedSpaceBytes"]
        total_local_cache += entry["localCacheUsedSpaceBytes"]
        total_object += entry["objectStorageUsedSpaceBytes"]

    # jobs scoped to this tenant
    jobs = [
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

    # per-module attribution from RP service flags over last 30 days
    org_rps = [r for r in recent_rps if r.get("organizationId") == org_id]
    flag_counts = {
        "Exchange":   sum(1 for r in org_rps if r.get("isExchange")),
        "OneDrive":   sum(1 for r in org_rps if r.get("isOneDrive")),
        "SharePoint": sum(1 for r in org_rps if r.get("isSharePoint")),
        "Teams":      sum(1 for r in org_rps if r.get("isTeams")),
    }
    if any(flag_counts.values()):
        # weight = raw flag share × default weight, then normalize so total = 1
        raw = {k: flag_counts[k] * DEFAULT_MODULE_WEIGHT[k] for k in flag_counts}
        s = sum(raw.values())
        weights = {k: (raw[k] / s) if s else 0.0 for k in raw}
    else:
        weights = {k: 0.0 for k in flag_counts}

    modules = {
        k: {
            "estimatedBytes": int(total_used * weights[k]),
            "estimatedShare": round(weights[k], 4),
            "rpFlagCount": flag_counts[k],
            "rpTotalCount": len(org_rps),
        }
        for k in DEFAULT_MODULE_WEIGHT
    }

    # users + per-user coverage
    users_raw = list(c.get_paginated(f"/Organizations/{org_id}/users", limit=500))
    has_entire_org_job = any(j.get("backupType") == "EntireOrganization" for j in jobs)
    users = []
    onedrive_covered = 0
    for u in users_raw:
        uid = u["id"]
        has_onedrive = None
        if pull_user_onedrives:
            try:
                od = c.get(f"/Organizations/{org_id}/users/{uid}/onedrives", allow_404=True)
                if isinstance(od, dict):
                    od_list = od.get("results") or []
                else:
                    od_list = od or []
                has_onedrive = bool(od_list)
            except Exception:
                has_onedrive = None
            if has_onedrive:
                onedrive_covered += 1
        users.append({
            "id": uid,
            "displayName": u.get("displayName"),
            "email": u.get("name"),     # /users returns email in 'name'
            "userType": u.get("type"),
            "locationType": u.get("locationType"),
            "hasMailbox": True if has_entire_org_job else None,
            "hasOneDrive": has_onedrive,
        })

    return {
        "id": org_id,
        "name": name,
        "displayName": display_for(name),
        "clientSlug": slug_for(name),
        "officeName": o.get("officeName"),
        "msid": o.get("msid"),
        "type": o.get("type"),
        "region": o.get("region"),
        "services": {
            "exchange":   o.get("isExchangeOnline", False),
            "sharepoint": o.get("isSharePointOnline", False),
            "teams":      o.get("isTeamsOnline", False),
            "teamsChats": o.get("isTeamsChatsOnline", False),
        },
        "userCount": len(users),
        "onedriveCoveredUserCount": onedrive_covered if pull_user_onedrives else None,
        "totals": {
            "usedSpaceBytes": total_used,
            "localCacheUsedSpaceBytes": total_local_cache,
            "objectStorageUsedSpaceBytes": total_object,
        },
        "repositories": repos,
        "jobs": jobs,
        "jobBackupTypes": sorted({j["backupType"] for j in jobs if j.get("backupType")}),
        "modules": modules,
        "users": users,
    }


def fetch_recent_rps(c: VeeamClient, days: int) -> list[dict]:
    """
    Server-side filter via ?backupTimeFrom=YYYY-MM-DDTHH:MM:SSZ — verified
    2026-05-02 against /v8/RestorePoints. Returns RPs newer than `days` ago.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    return list(c.get_paginated("/RestorePoints", params={"backupTimeFrom": cutoff_iso}, limit=500))


def write_outputs(snapshot: dict, tenant_blocks: list[dict]) -> Path:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    GLOBAL_OUT.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).date().isoformat()

    # global daily snapshot (compact — totals + per-tenant per-module bytes only)
    snap_path = SNAP_DIR / f"{today}.json"
    snap_path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")

    # latest summary (always overwritten)
    (GLOBAL_OUT / "tenant_summary.json").write_text(
        json.dumps({
            "pulledAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tenants": tenant_blocks,
        }, indent=2, default=str),
        encoding="utf-8",
    )

    # per-tenant feed for the monthly report builder
    for t in tenant_blocks:
        slug = t["clientSlug"]
        if slug == "_internal":
            base = GLOBAL_OUT / "internal"
        else:
            base = REPO_ROOT / "clients" / slug / "veeam-365"
        out_dir = base / today
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "data.json").write_text(json.dumps(t, indent=2, default=str), encoding="utf-8")

    return snap_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated tenant names (case-insensitive)")
    ap.add_argument("--skip-user-onedrives", action="store_true",
                    help="don't probe per-user /onedrives (faster, but no OneDrive coverage)")
    args = ap.parse_args()
    only = {x.strip().upper() for x in args.only.split(",")} if args.only else None

    c = VeeamClient()
    print(f"Logging in to {c.base} ...", file=sys.stderr)
    c._login()

    print("Listing organizations ...", file=sys.stderr)
    orgs = c.list_organizations()
    print(f"  {len(orgs)} orgs", file=sys.stderr)

    print("Listing repositories ...", file=sys.stderr)
    repos = c.list_backup_repositories()
    repos_by_id = {r["id"]: r for r in repos}

    print("Listing jobs ...", file=sys.stderr)
    jobs = c.list_jobs()

    print(f"Fetching restore points for last {RP_HISTORY_DAYS} days ...", file=sys.stderr)
    recent_rps = fetch_recent_rps(c, RP_HISTORY_DAYS)
    print(f"  {len(recent_rps)} restore points", file=sys.stderr)

    tenant_blocks = []
    for o in orgs:
        nm = (o.get("name") or "").upper()
        if only and nm not in only:
            continue
        print(f"  • {nm}", file=sys.stderr)
        block = collect_tenant(
            c, o, repos_by_id, jobs, recent_rps,
            pull_user_onedrives=not args.skip_user_onedrives,
        )
        tenant_blocks.append(block)

    snapshot = {
        "snapshotDate": datetime.now(timezone.utc).date().isoformat(),
        "pulledAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tenantCount": len(tenant_blocks),
        "totals": {
            "userCount": sum(t["userCount"] for t in tenant_blocks),
            "usedSpaceBytes": sum(t["totals"]["usedSpaceBytes"] for t in tenant_blocks),
        },
        "tenants": [
            {
                "name": t["name"],
                "clientSlug": t["clientSlug"],
                "userCount": t["userCount"],
                "onedriveCoveredUserCount": t["onedriveCoveredUserCount"],
                "totals": t["totals"],
                "modules": {k: v["estimatedBytes"] for k, v in t["modules"].items()},
            }
            for t in tenant_blocks
        ],
    }
    snap_path = write_outputs(snapshot, tenant_blocks)
    print(f"\nWrote snapshot {snap_path}")

    # console table
    name_w = max(8, max(len(t["name"]) for t in tenant_blocks))
    fmt = f"  {{:<{name_w}}}  {{:>5}}  {{:>5}}  {{:>10}}  {{:>10}}  {{:>10}}  {{:>10}}  {{:>10}}"
    print()
    print(fmt.format("Tenant", "Users", "OD", "Total", "Mailbox", "OneDrive", "Sites", "Teams"))
    print(fmt.format("-" * name_w, "-----", "----", "----------", "--------", "--------", "--------", "--------"))
    for t in sorted(tenant_blocks, key=lambda x: -x["totals"]["usedSpaceBytes"]):
        print(fmt.format(
            t["name"][:name_w],
            t["userCount"],
            t["onedriveCoveredUserCount"] if t["onedriveCoveredUserCount"] is not None else "-",
            humanize_bytes(t["totals"]["usedSpaceBytes"]),
            humanize_bytes(t["modules"]["Exchange"]["estimatedBytes"]),
            humanize_bytes(t["modules"]["OneDrive"]["estimatedBytes"]),
            humanize_bytes(t["modules"]["SharePoint"]["estimatedBytes"]),
            humanize_bytes(t["modules"]["Teams"]["estimatedBytes"]),
        ))


if __name__ == "__main__":
    main()
