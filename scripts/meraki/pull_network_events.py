"""
Pull Meraki appliance/firewall activity events (the "event log") per network.

Daily window by default. Output:

  clients/<code>/meraki/network_events/<network_slug>/<YYYY-MM-DD>.json

These are the firewall / VPN / DHCP / connectivity events you'd see in
Dashboard → Network-wide → Monitor → Event log (filtered to productType=appliance
by default). For switch / wireless event logs, pass --product-type switch or wireless.

Usage:
  python pull_network_events.py
  python pull_network_events.py --days 7
  python pull_network_events.py --product-type wireless
  python pull_network_events.py --only VAF,BWH
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import meraki_api as m
from _org_mapping import client_folder


DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "clients"


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--since", help="ISO date YYYY-MM-DD (UTC). Overrides --days when paired with --until.")
    p.add_argument("--until", help="ISO date YYYY-MM-DD (UTC). Inclusive end.")
    p.add_argument("--product-type", default="appliance",
                   choices=["appliance", "switch", "wireless", "camera",
                            "cellularGateway", "systemsManager"],
                   help="Which product layer to pull events for. Default appliance (firewall).")
    p.add_argument("--only", help="Comma-separated org slugs to include")
    p.add_argument("--skip", help="Comma-separated org slugs to skip")
    p.add_argument("--max-pages", type=int, default=20,
                   help="Max pages per (network, day). Each page = up to 1000 events.")
    p.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true",
                   help="Re-fetch days even when an output file already exists.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root)
    only = {s.strip().lower() for s in (args.only or "").split(",") if s.strip()}
    skip = {s.strip().lower() for s in (args.skip or "").split(",") if s.strip()}

    print("Auth check ...", flush=True)
    me = m.whoami()
    print(f"  {me.get('name')} ({me.get('email')})")

    orgs = m.list_organizations()
    print(f"Discovered {len(orgs)} accessible orgs")

    if args.since and args.until:
        s = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        e = datetime.strptime(args.until, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days = []
        cur = s
        while cur <= e:
            days.append(cur)
            cur += timedelta(days=1)
    else:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        days = [today - timedelta(days=i) for i in range(args.days, 0, -1)] or [today]
    print(f"Window: {len(days)} day(s) ({days[0].date()} to {days[-1].date()}), product={args.product_type}")
    if args.dry_run:
        print("(dry run)")
        return 0

    summary = []
    for org in orgs:
        slug = m.slugify(org["name"])
        if only and slug not in only:
            continue
        if slug in skip:
            continue
        try:
            networks = m.list_networks(org["id"])
        except m.MerakiError as e:
            print(f"  [{slug}] networks: ERR {e.status}")
            continue
        if not networks:
            print(f"  [{slug}] no accessible networks (likely 403/dormant)")
            continue
        for net in networks:
            if not m.network_has_product(net, args.product_type):
                continue
            net_slug = m.slugify(net["name"])
            net_dir = output_root / client_folder(slug) / "meraki" / "network_events" / net_slug
            net_dir.mkdir(parents=True, exist_ok=True)
            for day in days:
                t0 = day.replace(hour=0, minute=0, second=0, microsecond=0)
                t1 = t0 + timedelta(days=1) - timedelta(seconds=1)
                label = t0.strftime("%Y-%m-%d")
                out = net_dir / f"{label}.json"
                if out.exists() and not args.force:
                    # Idempotent skip: already fetched in a prior run.
                    continue
                try:
                    events = m.get_network_events(
                        net["id"], product_type=args.product_type,
                        t0=iso_utc(t0), t1=iso_utc(t1),
                        max_pages=args.max_pages,
                    )
                except m.MerakiError as e:
                    print(f"  [{slug}/{net_slug}] {label}: ERR {e.status}")
                    summary.append({"org": org["name"], "network": net["name"],
                                    "day": label, "error": f"HTTP {e.status}"})
                    continue
                payload = {
                    "org": {"id": org["id"], "name": org["name"]},
                    "network": {"id": net["id"], "name": net["name"],
                                "productTypes": net.get("productTypes")},
                    "productType": args.product_type,
                    "window": {"t0": iso_utc(t0), "t1": iso_utc(t1)},
                    "fetched_at": iso_utc(datetime.now(timezone.utc)),
                    "count": len(events),
                    "events": events,
                }
                out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                print(f"  [{slug}/{net_slug}] {label}: {len(events)} events")
                summary.append({"org": org["name"], "network": net["name"],
                                "day": label, "count": len(events)})

    log = output_root / "_meraki_logs" / "network_events_pull_log.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({
        "fetched_at": iso_utc(datetime.now(timezone.utc)),
        "product_type": args.product_type,
        "days": [d.strftime("%Y-%m-%d") for d in days],
        "results": summary,
    }, indent=2), encoding="utf-8")
    print(f"\nLog: {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
