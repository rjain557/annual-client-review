"""Diagnose per-org RP counts and module flag distribution."""
from veeam_client import VeeamClient
from collections import defaultdict

c = VeeamClient(); c._login()
orgs = {o["id"]: o.get("name") for o in c.list_organizations()}
counts = defaultdict(lambda: {"n": 0, "ex": 0, "od": 0, "sp": 0, "tm": 0, "oldest": None, "newest": None})
n = 0
for rp in c.get_paginated("/RestorePoints", limit=500):
    n += 1
    if n > 20000:
        break
    oid = rp.get("organizationId")
    name = orgs.get(oid, oid)
    c2 = counts[name]
    c2["n"] += 1
    if rp.get("isExchange"): c2["ex"] += 1
    if rp.get("isOneDrive"): c2["od"] += 1
    if rp.get("isSharePoint"): c2["sp"] += 1
    if rp.get("isTeams"): c2["tm"] += 1
    bt = rp.get("backupTime")
    if bt:
        if c2["oldest"] is None or bt < c2["oldest"]:
            c2["oldest"] = bt
        if c2["newest"] is None or bt > c2["newest"]:
            c2["newest"] = bt
print(f"Scanned {n} RPs")
for name, c2 in sorted(counts.items(), key=lambda kv: -kv[1]["n"]):
    print(f"  {str(name):>12}  n={c2['n']:5}  Ex={c2['ex']:5}  OD={c2['od']:5}  SP={c2['sp']:5}  Tm={c2['tm']:5}  oldest={c2['oldest']}  newest={c2['newest']}")
