"""Pull backup-storage configuration + capacity from VBR.

Returns repositories (regular + scale-out) joined with their states for
capacity / used / free bytes. Optionally includes proxies for transport
context. No IOPS — VBR REST does not expose storage performance counters;
session throughput is the proxy you'd use for that (see get_vm_backups.py).

    {
      "repositories": [
        {"id": "...", "name": "...", "type": "...", "path": "...",
         "capacityGB": ..., "freeGB": ..., "usedGB": ...,
         "isOutOfDate": false, "status": "Available"},
        ...
      ],
      "scaleOutRepositories": [...],
      "proxies": [...]   # only when --include-proxies
    }

Usage:
    python get_storage.py
    python get_storage.py --out storage.json
    python get_storage.py --include-proxies
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from veeam_client import VeeamApiError, VeeamClient


def _gb(b):
    return None if b is None else round(b / (1024**3), 2)


def _index(items, key="id"):
    return {x[key]: x for x in items if isinstance(x, dict) and key in x}


def _maybe_states(c: VeeamClient, path: str) -> dict:
    """Some VBR builds expose `/states` collections; others don't (the server
    treats `states` as an `id` and 400s). Return {} on those builds."""
    try:
        return _index(c.get_paged(path))
    except VeeamApiError as e:
        if e.status in (400, 404):
            return {}
        raise


def _repo_path(r: dict) -> str | None:
    """Resolve a repo's display path across NFS / SMB / WinLocal variants."""
    return (
        r.get("path")
        or (r.get("share") or {}).get("sharePath")
        or (r.get("smbShare") or {}).get("sharePath")
        or (r.get("repository") or {}).get("path")
    )


def collect_repos(c: VeeamClient):
    repos = list(c.get_paged("/backupInfrastructure/repositories"))
    states = _maybe_states(c, "/backupInfrastructure/repositories/states")
    out = []
    for r in repos:
        s = states.get(r.get("id"), {})
        # /repositories/states returns GB fields directly, NOT bytes.
        cap_gb = s.get("capacityGB")
        free_gb = s.get("freeGB")
        used_gb = s.get("usedSpaceGB")
        if used_gb is None and cap_gb is not None and free_gb is not None:
            used_gb = round(cap_gb - free_gb, 2)
        out.append(
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "description": r.get("description"),
                "type": r.get("type"),
                "path": _repo_path(r) or s.get("path"),
                "host": (r.get("host") or {}).get("name") if isinstance(r.get("host"), dict) else (r.get("host") or s.get("hostName")),
                "useFastCloningOnXFSVolumes": r.get("useFastCloningOnXFSVolumes"),
                "makeRecentBackupsImmutable": r.get("makeRecentBackupsImmutable"),
                "immutabilityDays": r.get("immutabilityDays"),
                "capacityGB": cap_gb,
                "freeGB": free_gb,
                "usedGB": used_gb,
                "isOnline": s.get("isOnline"),
                "isOutOfDate": s.get("isOutOfDate"),
                "status": s.get("status") or ("Online" if s.get("isOnline") else None),
            }
        )
    return out


def collect_sobr(c: VeeamClient):
    sobr = list(c.get_paged("/backupInfrastructure/scaleOutRepositories"))
    states = _maybe_states(c, "/backupInfrastructure/scaleOutRepositories/states")
    out = []
    for r in sobr:
        s = states.get(r.get("id"), {})
        out.append(
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "description": r.get("description"),
                "performanceTier": r.get("performanceTier"),
                "capacityTier": r.get("capacityTier"),
                "archiveTier": r.get("archiveTier"),
                "placementPolicy": r.get("placementPolicy"),
                "capacityBytes": s.get("capacity"),
                "freeBytes": s.get("freeSpace"),
                "capacityGB": _gb(s.get("capacity")),
                "freeGB": _gb(s.get("freeSpace")),
                "status": s.get("status"),
            }
        )
    return out


def collect_proxies(c: VeeamClient):
    proxies = list(c.get_paged("/backupInfrastructure/proxies"))
    states = _maybe_states(c, "/backupInfrastructure/proxies/states")
    out = []
    for p in proxies:
        s = states.get(p.get("id"), {})
        out.append(
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "type": p.get("type"),
                "description": p.get("description"),
                "server": (p.get("server") or {}).get("name") if isinstance(p.get("server"), dict) else p.get("server"),
                "maxTaskCount": (p.get("options") or {}).get("maxTaskCount"),
                "transportMode": (p.get("options") or {}).get("transportMode"),
                "status": s.get("status"),
            }
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--include-proxies", action="store_true")
    ap.add_argument("--host")
    ap.add_argument("--keyfile")
    args = ap.parse_args()

    c = VeeamClient(host=args.host, keyfile=args.keyfile)
    c.login()

    out = {
        "repositories": collect_repos(c),
        "scaleOutRepositories": collect_sobr(c),
    }
    if args.include_proxies:
        out["proxies"] = collect_proxies(c)

    payload = json.dumps(out, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(
            f"wrote {len(out['repositories'])} repos, "
            f"{len(out['scaleOutRepositories'])} SOBRs to {args.out}"
        )
    else:
        print(payload)


if __name__ == "__main__":
    main()
