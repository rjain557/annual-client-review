"""
Pull Meraki IDS/IPS + AMP security events for all accessible orgs.

Daily window by default. Output:

  clients/<code>/meraki/security_events/<YYYY-MM-DD>.json

Each daily file contains the raw events list returned from
`GET /organizations/{orgId}/appliance/security/events`. Re-running on the
same day overwrites that day's file (idempotent).

Usage:
  python pull_security_events.py                    # last 24h, all orgs
  python pull_security_events.py --days 7           # last 7 days, one file per day
  python pull_security_events.py --only VAF,BWH     # restrict by org name slug
  python pull_security_events.py --since 2026-04-22 --until 2026-04-29
  python pull_security_events.py --output-root c:/some/path
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import meraki_api as m
from _org_mapping import client_folder


# Repo-relative: this file is at <repo>/scripts/meraki/pull_security_events.py
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "clients"


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def day_bounds(day: datetime) -> tuple[str, str, str]:
    """For a UTC date, return (t0, t1, label) covering 00:00 to 23:59:59."""
    start = day.replace(hour=0, minute=0, second=0, microsecond=0,
                        tzinfo=timezone.utc)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return iso_utc(start), iso_utc(end), start.strftime("%Y-%m-%d")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=1,
                   help="Number of days back from today (UTC). Default 1.")
    p.add_argument("--since", help="ISO date (UTC). Overrides --days when paired with --until.")
    p.add_argument("--until", help="ISO date (UTC). Inclusive end.")
    p.add_argument("--only", help="Comma-separated org slugs to include")
    p.add_argument("--skip", help="Comma-separated org slugs to skip")
    p.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT),
                   help="Root output dir (defaults to repo's clients/)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true",
                   help="Re-fetch days even when an output file already exists.")
    return p.parse_args()


def daterange(args: argparse.Namespace) -> list[datetime]:
    if args.since and args.until:
        s = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        e = datetime.strptime(args.until, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days = []
        cur = s
        while cur <= e:
            days.append(cur)
            cur += timedelta(days=1)
        return days
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return [today - timedelta(days=i) for i in range(args.days, 0, -1)] or [today]


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

    days = daterange(args)
    print(f"Window: {len(days)} day(s), {days[0].date()} to {days[-1].date()}")
    if args.dry_run:
        print("(dry run — no writes)")
        return 0

    summary = []
    for org in orgs:
        slug = m.slugify(org["name"])
        if only and slug not in only:
            continue
        if slug in skip:
            continue
        org_dir = output_root / client_folder(slug) / "meraki" / "security_events"
        org_dir.mkdir(parents=True, exist_ok=True)
        org_total = 0
        for day in days:
            t0, t1, label = day_bounds(day)
            out = org_dir / f"{label}.json"
            if out.exists() and not args.force:
                continue
            try:
                events = m.get_security_events_org(org["id"], t0=t0, t1=t1)
            except m.MerakiError as e:
                print(f"  [{slug}] {label}: ERR {e.status} — skipping")
                summary.append({"org": org["name"], "slug": slug, "day": label,
                                "error": f"HTTP {e.status}"})
                continue
            payload = {
                "org": {"id": org["id"], "name": org["name"]},
                "window": {"t0": t0, "t1": t1},
                "fetched_at": iso_utc(datetime.now(timezone.utc)),
                "count": len(events),
                "events": events,
            }
            out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            org_total += len(events)
            try:
                rel = out.relative_to(output_root)
            except ValueError:
                rel = out
            print(f"  [{slug}] {label}: {len(events)} events -> {rel}")
            summary.append({"org": org["name"], "slug": slug, "day": label,
                            "count": len(events)})
        print(f"  [{slug}] TOTAL: {org_total} events across {len(days)} day(s)")

    log = output_root / "_meraki_logs" / "security_events_pull_log.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({
        "fetched_at": iso_utc(datetime.now(timezone.utc)),
        "days": [d.strftime("%Y-%m-%d") for d in days],
        "results": summary,
    }, indent=2), encoding="utf-8")
    print(f"\nLog: {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
