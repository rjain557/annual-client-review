"""Round 2 probe: drill into restore-point sub-resources for per-module sizes."""
from __future__ import annotations
import json, sys, requests
from veeam_client import VeeamClient

c = VeeamClient()
c._login()

# Pick a recent restore point with all four service flags set true
rps = list(c.get_paginated("/RestorePoints", limit=50))
print(f"# {len(rps)} restore points fetched", file=sys.stderr)
rich = next((r for r in rps if r.get("isExchange") and r.get("isOneDrive") and r.get("isSharePoint") and r.get("isTeams")), None)
if not rich:
    rich = rps[0]
rpid = rich["id"]
oid = rich["organizationId"]
print(f"# Drilling into RP {rpid} (org {oid})", file=sys.stderr)

PATHS = [
    f"/RestorePoints/{rpid}/Mailboxes",
    f"/RestorePoints/{rpid}/OneDrives",
    f"/RestorePoints/{rpid}/Sites",
    f"/RestorePoints/{rpid}/Teams",
    f"/RestorePoints/{rpid}/Statistics",
    f"/RestorePoints/{rpid}/Items",
    f"/RestorePoints/{rpid}/EntityData",
    # global per-entity collections
    "/Mailboxes?limit=1",
    "/OneDrives?limit=1",
    "/Sites?limit=1",
    "/Teams?limit=1",
    "/Backups?limit=1",
    "/Reports?limit=1",
    "/RestorePortal/Reports",
    "/Reports/Storage",
    "/Reports/Backup",
    # from /Organizations/{oid} drill via _links
    f"/Organizations/{oid}/Backups",
    f"/Organizations/{oid}/restorepoints",
    f"/organizations/{oid}/protectionStatus",
    # The "Backup" entity — possibly /Backups/{repoId+orgId}
    f"/Backups/{rich.get('repositoryId')}",
]

out = {}
for p in PATHS:
    if not p:
        continue
    try:
        url = c._full_url(p)
        r = c.session.get(
            url,
            headers={"Authorization": f"Bearer {c._access_token}", "Accept": "application/json"},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"ERR  {p}: {e}", file=sys.stderr)
        continue
    status = r.status_code
    body = None
    try:
        body = r.json()
    except ValueError:
        body = (r.text[:200] if r.text else None)
    sample_keys = []
    if isinstance(body, dict):
        if isinstance(body.get("results"), list) and body["results"]:
            sample = body["results"][0]
            sample_keys = sorted(sample.keys()) if isinstance(sample, dict) else []
        else:
            sample_keys = sorted(body.keys())
    out[p] = {"status": status, "keys": sample_keys, "body_excerpt": str(body)[:400]}
    flag = "OK " if status == 200 else f"{status}"
    print(f"{flag}  {p}  keys={sample_keys[:8]}", file=sys.stderr)

print(json.dumps(out, indent=2, default=str))
