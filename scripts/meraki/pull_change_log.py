"""
Pull Cisco Meraki Dashboard configuration-change log for every accessible org.

The Meraki API exposes a structured audit trail of every admin action taken
via the Dashboard, API, or mobile app:

  GET /organizations/{orgId}/configurationChanges
  Fields per record: ts, adminName, adminEmail, networkId, networkName,
                     page, label, oldValue, newValue

Changes are merged idempotently into per-org per-month files so reruns and
overlapping windows don't create duplicates.

Output:
  clients/<code>/meraki/change_log/<YYYY-MM>.json   per-month audit file
  clients/_meraki_logs/change_log_pull_log.json      run summary

Usage:
  python pull_change_log.py                              # last 24h, all orgs
  python pull_change_log.py --days 7                     # last 7 days
  python pull_change_log.py --since 2026-04-01 --until 2026-04-30
  python pull_change_log.py --only VAF,BWH
  python pull_change_log.py --skip technijian
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import meraki_api as m
from _org_mapping import client_folder

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "clients"


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=1,
                   help="Pull the last N days of changes (default: 1)")
    p.add_argument("--since", help="Start date YYYY-MM-DD (inclusive)")
    p.add_argument("--until", help="End date YYYY-MM-DD (inclusive; defaults to today)")
    p.add_argument("--only", help="Comma-separated org slugs to include")
    p.add_argument("--skip", help="Comma-separated org slugs to skip")
    p.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def change_key(c: dict) -> str:
    """Stable fingerprint for deduplication across overlapping pulls."""
    return "|".join([
        c.get("ts") or "",
        c.get("adminEmail") or c.get("adminName") or "",
        c.get("networkId") or "",
        c.get("page") or "",
        c.get("label") or "",
        str(c.get("oldValue") or "")[:80],
    ])


def merge_changes(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Add incoming changes not already in existing; return sorted newest-first."""
    seen = {change_key(c) for c in existing}
    merged = list(existing)
    for c in incoming:
        k = change_key(c)
        if k not in seen:
            merged.append(c)
            seen.add(k)
    merged.sort(key=lambda c: c.get("ts") or "", reverse=True)
    return merged


def group_by_month(changes: list[dict]) -> dict[str, list[dict]]:
    by_month: dict[str, list[dict]] = {}
    for c in changes:
        m_key = (c.get("ts") or "")[:7]
        if not m_key:
            m_key = "unknown"
        by_month.setdefault(m_key, []).append(c)
    return by_month


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root)
    only = {s.strip().lower() for s in (args.only or "").split(",") if s.strip()}
    skip = {s.strip().lower() for s in (args.skip or "").split(",") if s.strip()}

    now = datetime.now(timezone.utc)
    if args.since:
        t0_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if args.until:
            t1_dt = datetime.strptime(args.until, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc)
        else:
            t1_dt = now
    else:
        t1_dt = now
        t0_dt = now - timedelta(days=args.days)

    t0 = iso_utc(t0_dt)
    t1 = iso_utc(t1_dt)
    print(f"Window: {t0} -> {t1}")

    if args.dry_run:
        print("[dry-run] would pull configurationChanges for all licensed orgs")
        return 0

    print("Auth check ...", flush=True)
    me = m.whoami()
    print(f"  {me.get('name')} ({me.get('email')})")

    orgs = m.list_organizations()
    print(f"Discovered {len(orgs)} accessible orgs")

    pull_log: list[dict] = []
    for org in orgs:
        slug = m.slugify(org["name"])
        if only and slug not in only:
            continue
        if slug in skip:
            continue

        try:
            new_changes = m.get_configuration_changes(org["id"], t0=t0, t1=t1)
        except m.MerakiError as e:
            print(f"  [{slug}] HTTP {e.status} — skipping")
            pull_log.append({"org": org["name"], "slug": slug,
                             "error": f"HTTP {e.status}"})
            continue

        if not new_changes:
            print(f"  [{slug}] 0 changes in window")
            pull_log.append({"org": org["name"], "slug": slug, "changes_added": 0,
                             "months_updated": []})
            continue

        print(f"  [{slug}] {len(new_changes)} change(s) in window")
        org_dir = output_root / client_folder(slug) / "meraki"
        change_log_dir = org_dir / "change_log"

        by_month = group_by_month(new_changes)
        total_added = 0
        months_updated: list[str] = []
        for month, month_changes in sorted(by_month.items()):
            if month == "unknown":
                continue
            out = change_log_dir / f"{month}.json"
            existing_data = load_json(out) or {}
            existing_changes = existing_data.get("changes") or []
            merged = merge_changes(existing_changes, month_changes)
            added = len(merged) - len(existing_changes)
            total_added += added
            write_json(out, {
                "month": month,
                "org": org["name"],
                "org_id": str(org["id"]),
                "change_count": len(merged),
                "pulled_at": iso_utc(now),
                "changes": merged,
            })
            months_updated.append(month)
            print(f"    {month}: +{added} new  ({len(merged)} total)")

        pull_log.append({
            "org": org["name"],
            "slug": slug,
            "changes_in_window": len(new_changes),
            "changes_added": total_added,
            "months_updated": months_updated,
        })

    log_path = output_root / "_meraki_logs" / "change_log_pull_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(log_path, {
        "pulled_at": iso_utc(now),
        "window": {"t0": t0, "t1": t1},
        "orgs": pull_log,
    })
    print(f"\nChange log pull complete. Log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
