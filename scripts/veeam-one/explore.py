"""
Veeam ONE REST API endpoint discovery probe.

The Reporter REST API in v13 has a small, sparse surface — many obvious
endpoint names 404. This script lets you brute-probe candidate paths quickly
and shape-check the responses. Use it to expand the client (`veeam_one_api.py`)
when Veeam ships new endpoints in a service-pack update.

Examples:
  python explore.py                          # run the curated discovery list
  python explore.py vbr/jobs vbr/sessions   # probe specific paths
  python explore.py --shape vbr/repositories # GET + dump truncated response
"""
from __future__ import annotations

import argparse
import json
import sys

import veeam_one_api as v

# Canonical probe set — paths the API may expose. Update when Veeam adds
# endpoints. Confirmed-working ones live in veeam_one_api.py as typed helpers.
DEFAULT_PROBES = [
    # confirmed working (sanity check)
    "license", "about", "agents",
    "alarms/templates", "businessView/categories", "businessView/groups",
    "vbr/backupServers", "vbr/repositories", "vbr/scaleOutRepositories",
    # commonly attempted, confirmed 404 in 13.0.1.6168 — re-probe periodically
    "vms", "inventory/vms", "inventory/hosts", "inventory/datastores",
    "alarms", "alarms/triggered", "alarms/active",
    "events", "users", "users/me", "rolesAndUsers",
    "vbr/jobs", "vbr/sessions", "vbr/proxies", "vbr/protectedVMs",
    "license/usage", "license/instances",
    "remedies", "loganalyzer",
    "topology/vms", "monitoring/vms", "monitoring/datastores",
    "telemetry/usage",
    "deployment", "deployment/widgets",
]


def probe(paths: list[str]) -> None:
    rows = []
    for p in paths:
        try:
            res = v.get(p, params={"Limit": 1}, allow_404=True, allow_403=True)
            if res is None:
                rows.append((404, p, "—"))
                continue
            if isinstance(res, dict) and "items" in res:
                tc = res.get("totalCount")
                rows.append((200, p, f"items={len(res['items'])} totalCount={tc}"))
            elif isinstance(res, dict):
                rows.append((200, p, f"keys={','.join(list(res.keys())[:6])}"))
            elif isinstance(res, list):
                rows.append((200, p, f"len={len(res)}"))
            else:
                rows.append((200, p, str(type(res).__name__)))
        except Exception as e:
            rows.append((500, p, str(e)[:120]))
    rows.sort()
    for code, p, info in rows:
        marker = "OK " if code == 200 else "404" if code == 404 else "ERR"
        print(f"{marker}  {p:<40s}  {info}")


def shape(path: str) -> None:
    res = v.get(path, params={"Limit": 2}, allow_404=True)
    print(json.dumps(res, indent=2, default=str)[:4000])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="paths to probe (default: curated list)")
    ap.add_argument("--shape", default=None, help="GET this single path + dump body")
    args = ap.parse_args()
    if args.shape:
        shape(args.shape)
        return 0
    probe(args.paths or DEFAULT_PROBES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
