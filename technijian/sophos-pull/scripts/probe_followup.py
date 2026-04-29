"""Follow-up probes: full SIEM error, alternative time formats, sample shapes."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")
import sophos_api as s  # noqa: E402


def show(label, r):
    print(f"\n--- {label} ---")
    print(f"  status: {r['status']}")
    body = r["body"]
    if isinstance(body, dict):
        print("  body:", json.dumps(body, indent=2)[:1200])
    else:
        print("  body:", str(body)[:1200])


def main() -> int:
    tenants = s.list_tenants()

    # Pick tenants likely to have endpoints/data
    technijian = next(t for t in tenants if t["name"] == "Technijian")
    kss = next(t for t in tenants if t["name"] == "KSS")
    bwh = next(t for t in tenants if t["name"] == "Brandywine Homes")

    # 1) Full SIEM error message
    print("=" * 80)
    print("SIEM error detail")
    print("=" * 80)
    now = datetime.now(timezone.utc)
    iso_24h = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    epoch_24h = int((now - timedelta(hours=24)).timestamp())

    show("SIEM events ISO from_date", s.tenant_get(technijian, "/siem/v1/events", {"from_date": iso_24h, "limit": "200"}))
    show("SIEM events epoch from_date", s.tenant_get(technijian, "/siem/v1/events", {"from_date": str(epoch_24h), "limit": "200"}))
    show("SIEM events no from_date", s.tenant_get(technijian, "/siem/v1/events", {"limit": "200"}))
    show("SIEM events cursor='' ", s.tenant_get(technijian, "/siem/v1/events", {"cursor": "", "limit": "200"}))
    # Try the alerts endpoint with both
    show("SIEM alerts no params", s.tenant_get(technijian, "/siem/v1/alerts", {"limit": "200"}))

    # 2) Try a tenant with Intercept-X enrolled (KSS, BWH)
    print("\n" + "=" * 80)
    print("Endpoint inventory across tenants")
    print("=" * 80)
    for t in tenants:
        r = s.tenant_get(t, "/endpoint/v1/endpoints", {"pageSize": "1"})
        if r["status"] == 200 and isinstance(r["body"], dict):
            total = r["body"].get("pages", {}).get("items") or r["body"].get("pages", {}).get("total") or len(r["body"].get("items", []))
            print(f"  {t['name']:40s}  endpoints~{total}")

    # 3) Sample one endpoint record + one alert record from a tenant that has them
    print("\n" + "=" * 80)
    print("Sample shapes — alerts + endpoints + firewall")
    print("=" * 80)
    # KSS has firewalls; alerts may or may not be present
    for t in (kss, bwh, technijian):
        ra = s.tenant_get(t, "/common/v1/alerts", {"pageSize": "3"})
        if ra["status"] == 200 and ra["body"].get("items"):
            print(f"\n  Sample alert from {t['name']}:")
            print(json.dumps(ra["body"]["items"][0], indent=2)[:1200])
            break

    # Sample firewall detail
    fws = s.list_firewalls(technijian)
    if fws:
        print(f"\n  Sample firewall record (Technijian tenant, fw 0):")
        print(json.dumps(fws[0], indent=2)[:1200])

    # Sample endpoint policy record
    rp = s.tenant_get(technijian, "/endpoint/v1/policies", {"pageSize": "1"})
    if rp["status"] == 200 and rp["body"].get("items"):
        print(f"\n  Sample endpoint policy (Technijian tenant):")
        print(json.dumps(rp["body"]["items"][0], indent=2)[:800])

    # Sample partner admin record
    ra = s.partner_get("/partner/v1/admins", {"pageSize": "1"})
    if ra["status"] == 200 and ra["body"].get("items"):
        print(f"\n  Sample partner admin record:")
        print(json.dumps(ra["body"]["items"][0], indent=2)[:600])

    # 4) Try a different SIEM time-window format Sophos uses: epoch ms in the past 24h
    print("\n" + "=" * 80)
    print("Try /siem/v1/events with various known param shapes")
    print("=" * 80)
    show("from_date as epoch-ms", s.tenant_get(technijian, "/siem/v1/events", {"from_date": str(int(time.time() * 1000) - 24 * 3600 * 1000), "limit": "200"}))
    # Sophos docs for /siem/v1/events list params: 'cursor' OR 'from_date' (epoch seconds OR ISO 8601), 'limit'
    # Try with seconds without ms
    show("from_date as seconds-only", s.tenant_get(technijian, "/siem/v1/events", {"from_date": str(epoch_24h), "limit": "200"}))

    return 0


if __name__ == "__main__":
    sys.exit(main())
