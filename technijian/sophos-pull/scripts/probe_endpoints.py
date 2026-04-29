"""Sweep every candidate Partner / Tenant endpoint and report status + shape.

Output: a table of {scope, path, status, item_count or summary, top-level keys}.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")
import sophos_api as s  # noqa: E402

PARTNER_PATHS = [
    ("/partner/v1/tenants",          {"pageTotal": "true", "pageSize": "100"}),
    ("/partner/v1/admins",           {"pageTotal": "true"}),
    ("/partner/v1/billing/usage",    None),
    ("/partner/v1/roles",            None),
    ("/partner/v1/users",            None),
]

TENANT_PATHS = [
    ("/accounts/v1/accounts",                    None),
    ("/endpoint/v1/endpoints",                   {"pageSize": "5"}),
    ("/endpoint/v1/endpoint-groups",             None),
    ("/endpoint/v1/policies",                    None),
    ("/endpoint/v1/migrations",                  None),
    ("/endpoint/v1/settings/exclusions/scanning", None),
    ("/endpoint/v1/settings/allowed-items",      None),
    ("/endpoint/v1/settings/blocked-items",      None),
    ("/firewall/v1/firewalls",                   None),
    ("/firewall/v1/firewalls/groups",            None),
    ("/common/v1/alerts",                        {"pageSize": "5"}),
    ("/common/v1/directory/users",               {"pageSize": "5"}),
    ("/common/v1/directory/user-groups",         {"pageSize": "5"}),
    ("/common/v1/admins",                        None),
    ("/common/v1/health-check",                  None),
    ("/xdr-datalake/v1/queries",                 None),
]


def _summarise(body):
    if isinstance(body, dict):
        keys = list(body.keys())[:8]
        items = body.get("items")
        if isinstance(items, list):
            return f"items={len(items)} keys={keys}"
        return f"keys={keys}"
    if isinstance(body, list):
        return f"list len={len(body)}"
    if isinstance(body, str):
        return f"str: {body[:120]}"
    return str(type(body).__name__)


def main() -> int:
    me = s.whoami()
    print(f"[partner] id={me['id']}  idType={me['idType']}\n")

    print("=" * 90)
    print("PARTNER-SCOPED PROBES")
    print("=" * 90)
    for path, q in PARTNER_PATHS:
        r = s.partner_get(path, q)
        st = r["status"]
        summary = _summarise(r["body"]) if st == 200 else str(r["body"])[:160]
        print(f"  {st!s:>5} GET {path:50s}  {summary}")

    tenants = s.list_tenants()
    target = next((t for t in tenants if t.get("name") == "Technijian"), tenants[0])
    print(f"\n[probe-tenant] {target['name']}  id={target['id']}  apiHost={target['apiHost']}\n")

    print("=" * 90)
    print("TENANT-SCOPED PROBES (against Technijian tenant)")
    print("=" * 90)
    for path, q in TENANT_PATHS:
        r = s.tenant_get(target, path, q)
        st = r["status"]
        summary = _summarise(r["body"]) if st == 200 else str(r["body"])[:160]
        print(f"  {st!s:>5} GET {path:50s}  {summary}")

    # SIEM endpoints take a `from_date` window (ISO seconds). 24h max.
    now = datetime.now(timezone.utc)
    from_date = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    print(f"\n[siem-window] from_date={from_date}\n")
    for path in ("/siem/v1/events", "/siem/v1/alerts"):
        r = s.tenant_get(target, path, {"from_date": from_date, "limit": "10"})
        st = r["status"]
        summary = _summarise(r["body"]) if st == 200 else str(r["body"])[:160]
        print(f"  {st!s:>5} GET {path:50s}  {summary}")

    # Per-firewall detail
    fws = s.list_firewalls(target)
    if fws:
        fw = fws[0]
        print(f"\n[firewall-detail] {fw.get('name')}  id={fw.get('id')}\n")
        for sub in ("", "/health"):
            path = f"/firewall/v1/firewalls/{fw['id']}{sub}"
            r = s.tenant_get(target, path)
            st = r["status"]
            summary = _summarise(r["body"]) if st == 200 else str(r["body"])[:160]
            print(f"  {st!s:>5} GET {path:60s}  {summary}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
