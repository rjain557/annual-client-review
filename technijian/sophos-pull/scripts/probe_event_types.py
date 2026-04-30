"""Walk the SIEM events + alerts endpoints across all tenants and bucket by type/group."""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")
import sophos_api as s  # noqa: E402


def walk_paged(tenant, path, *, params=None, cap=2000):
    out = []
    cursor = None
    while True:
        q = dict(params or {})
        q["limit"] = "1000"
        if cursor:
            q["cursor"] = cursor
        r = s.tenant_get(tenant, path, q)
        if r["status"] != 200 or not isinstance(r["body"], dict):
            return out, r
        items = r["body"].get("items", [])
        out.extend(items)
        if len(out) >= cap:
            return out[:cap], r
        if not r["body"].get("has_more"):
            return out, r
        cursor = r["body"].get("next_cursor")
        if not cursor:
            return out, r


def main() -> int:
    tenants = s.list_tenants()

    epoch_24h = int(time.time()) - 24 * 3600

    print("=" * 100)
    print("SIEM /events — last 24h, all tenants")
    print("=" * 100)
    print(f"{'tenant':40s} {'events':>7s}  top types (group/type counts)")
    grand_types = Counter()
    grand_groups = Counter()
    all_events = {}
    for t in tenants:
        events, last = walk_paged(t, "/siem/v1/events", params={"from_date": str(epoch_24h)}, cap=2000)
        if last["status"] != 200:
            print(f"  {t['name']:40s} ERR {last['status']}")
            continue
        groups = Counter(e.get("group", "?") for e in events)
        types = Counter(e.get("type", "?") for e in events)
        grand_types.update(types)
        grand_groups.update(groups)
        all_events[t["name"]] = events
        top = ", ".join(f"{g}={n}" for g, n in groups.most_common(5))
        print(f"  {t['name']:40s} {len(events):>7d}  {top}")

    print(f"\n  GRAND TOTAL groups: {dict(grand_groups.most_common(20))}")
    print(f"  GRAND TOTAL types : {dict(grand_types.most_common(20))}")

    print("\n" + "=" * 100)
    print("SIEM /alerts — most-recent 1000 across all tenants (cursor-paged)")
    print("=" * 100)
    grand_alert_types = Counter()
    grand_alert_cats = Counter()
    grand_alert_sev = Counter()
    grand_alert_products = Counter()
    for t in tenants:
        alerts, last = walk_paged(t, "/siem/v1/alerts", cap=1000)
        if last["status"] != 200:
            print(f"  {t['name']:40s} ERR {last['status']}")
            continue
        cats = Counter(a.get("category") or a.get("group", "?") for a in alerts)
        types = Counter(a.get("type", "?") for a in alerts)
        sev = Counter(a.get("severity", "?") for a in alerts)
        prod = Counter(a.get("product", "?") for a in alerts)
        grand_alert_cats.update(cats)
        grand_alert_types.update(types)
        grand_alert_sev.update(sev)
        grand_alert_products.update(prod)
        top = ", ".join(f"{g}={n}" for g, n in cats.most_common(5))
        print(f"  {t['name']:40s} {len(alerts):>5d}  {top}")

    print(f"\n  ALERT categories: {dict(grand_alert_cats.most_common(20))}")
    print(f"  ALERT products  : {dict(grand_alert_products.most_common(20))}")
    print(f"  ALERT severity  : {dict(grand_alert_sev)}")
    print(f"  ALERT types (top 25): {json.dumps(dict(grand_alert_types.most_common(25)), indent=2)}")

    # Sample one IPS/IDS-flavored alert if any exist
    keywords = ("idp", "ips", "ids", "intrusion", "atp", "malware", "ransom", "scan", "exploit")
    print("\n" + "=" * 100)
    print("Search for IPS/IDS/ATP/malware events in the captures")
    print("=" * 100)
    for tname, events in all_events.items():
        hits = [e for e in events if any(k in (e.get("type", "") + e.get("name", "") + e.get("group", "")).lower() for k in keywords)]
        if hits:
            print(f"\n  {tname}: {len(hits)} matching events. Sample:")
            print(json.dumps(hits[0], indent=2)[:1200])

    # Also a few sample event records from each non-empty group
    print("\n" + "=" * 100)
    print("Sample event per group (across all tenants)")
    print("=" * 100)
    seen_groups = set()
    for events in all_events.values():
        for e in events:
            g = e.get("group", "?")
            if g not in seen_groups:
                seen_groups.add(g)
                print(f"\n  group={g}  type={e.get('type')}  severity={e.get('severity')}")
                print(json.dumps(e, indent=2)[:600])

    return 0


if __name__ == "__main__":
    sys.exit(main())
