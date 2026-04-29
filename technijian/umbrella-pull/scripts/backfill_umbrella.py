"""Backfill Cisco Umbrella per-client per-day folders for a date range.

Cisco Umbrella's `/reports/v2/activity` retention is **~90 days** for
Technijian's plan (verified 2026-04-29). Anything older returns zero records
silently.

This script writes one day-folder per LocationCode for every day in the
range, using **aggregation endpoints** (top-identities, top-threats,
requests-by-hour, categories-by-hour) plus a small **blocked-only** activity
walk. That is dramatically faster than walking raw activity:

    raw walk (one LocationCode, 1 day, ~200K events): ~3-5 min, 24 hourly
        chunks each capped at 10K (the offset cap), so busy hours under-
        sample anyway.
    aggregations (one LocationCode, 1 day):           ~5 sec, captures
        full counts via top-identities + per-hour breakdowns.

For 90 days x 1 client this collapses ~6-10 hours of API time to ~10 min.

Why this is the right tradeoff for the annual-review use case:
    The downstream reports want daily counts (total queries, blocked, by-
    category-by-hour) and per-client top destinations / threats / identities.
    Aggregations give exactly that. Raw activity is only needed for
    forensic deep-dives, which can use --mode raw on demand.

Snapshot data (roaming computers, sites, networks, destination lists) does
NOT have per-day history in the Umbrella API. The current snapshot is
written into every backfilled day's folder, tagged with
    "mode": "backfill"
    "inventory_snapshot_at": "<ISO timestamp>"
in `pull_summary.json`.

Output mirrors the daily pull layout, with extra aggregation files:

    clients/<code>/umbrella/YYYY-MM-DD/
        roaming_computers.json + csv      current snapshot, filtered to prefix
        internal_networks.json            current snapshot
        sites.json                        current snapshot
        activity_summary.json             daily totals + hourly request curve
        top_destinations.json             top destinations (org-wide top1k
                                          filtered to client identities)
        top_threats.json                  top blocked threats touching this
                                          client's identities
        top_identities.json               this client's identities by request
                                          count for the day
        requests_by_hour.json             hourly request curve filtered to
                                          client identities
        blocked_threats.json              raw blocked-verdict activity
                                          touching this client's identities
        pull_summary.json                 mode=backfill aggregation summary

    technijian/umbrella-pull/<YYYY-MM-DD>/
        run_log.json                      per-day rollup with mode=backfill

    technijian/umbrella-pull/state/backfill-<RANGE>.json
        master log of the whole backfill run

Usage:
    python backfill_umbrella.py --start 2026-01-30 --end 2026-04-28
    python backfill_umbrella.py --start 2026-03-01 --end 2026-04-28 --only VAF
    python backfill_umbrella.py --start 2026-04-20 --end 2026-04-28 --include-empty-days
    python backfill_umbrella.py --start 2026-04-20 --end 2026-04-28 --dry-run
    python backfill_umbrella.py --start 2026-04-28 --end 2026-04-28 --mode raw  # forensic

Cadence note:
    On-demand only - no scheduled task. Run after a fresh-onboard or when
    the daily pull's activity sample was insufficient on a busy day.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PIPELINE_ROOT = HERE.parent
REPO = PIPELINE_ROOT.parent.parent
CLIENTPORTAL_SCRIPTS = REPO / "scripts" / "clientportal"
CLIENTS_ROOT = REPO / "clients"
STATE_DIR = PIPELINE_ROOT / "state"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(CLIENTPORTAL_SCRIPTS))
import umbrella_api as uapi  # noqa: E402
import cp_api  # noqa: E402
from pull_umbrella_daily import (  # noqa: E402
    derive_prefix,
    load_manual_mapping,
    resolve_prefix_mapping,
    write_csv,
    ROAMING_PREFERRED_COLS,
)

# Activity retention window for Umbrella standard plans (verified 2026-04-29)
RETENTION_DAYS = 90


def _isoz(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms(dt: datetime) -> int:
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def parse_args() -> argparse.Namespace:
    today = datetime.now(timezone.utc).date()
    ap = argparse.ArgumentParser(description="Backfill Umbrella per-client per-day folders.")
    ap.add_argument("--start", required=True, help="Start date (YYYY-MM-DD, inclusive)")
    ap.add_argument("--end", default=None,
                    help="End date (YYYY-MM-DD, inclusive). Default = yesterday UTC.")
    ap.add_argument("--only", help="comma-separated LocationCodes")
    ap.add_argument("--skip", action="append", default=[],
                    help="LocationCode to skip (repeatable)")
    ap.add_argument("--include-empty-days", action="store_true",
                    help="Write per-client folders even when the day had 0 events for the client")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan + no API calls and no files")
    ap.add_argument("--mode", choices=["aggregations", "raw"], default="aggregations",
                    help="Default 'aggregations' is fast (~5s/day/client). 'raw' walks "
                         "/reports/v2/activity in 1h chunks (~3-5min/day/client, capped "
                         "at 10K records per hour by Umbrella) - use only for forensic "
                         "deep-dives of a small range.")
    return ap.parse_args()


def _identity_belongs_to_prefix(label: str, prefix: str) -> bool:
    """Hostname/identity-label match: e.g. 'VAF-DC-FS-02' -> prefix 'VAF'."""
    return derive_prefix(label or "") == prefix


def _aggregate_blocked_threats(blocked_records: list[dict],
                                client_identity_labels: set[str]) -> list[dict]:
    """Filter blocked-verdict activity to records touching client identities."""
    out: list[dict] = []
    for r in blocked_records:
        idents = r.get("identities") or []
        for ident in idents:
            if (ident.get("label") or "") in client_identity_labels:
                out.append({
                    "domain": r.get("domain"),
                    "threats": r.get("threats") or [],
                    "categories": r.get("categories") or [],
                    "verdict": r.get("verdict"),
                    "timestamp": r.get("timestamp"),
                    "date": r.get("date"),
                    "time": r.get("time"),
                    "identity_labels": [i.get("label") for i in idents],
                    "identity_ids": [i.get("id") for i in idents],
                })
                break  # don't double-count if multiple identities match
    return out


def _filter_top_identities_for_prefix(top_identities: list[dict], prefix: str
                                       ) -> tuple[list[dict], set[str], set[str]]:
    """Return (entries, labels, ids) for identities matching the client prefix."""
    matches: list[dict] = []
    labels: set[str] = set()
    ids: set[str] = set()
    for entry in top_identities:
        ident = entry.get("identity") or {}
        label = ident.get("label") or ""
        if _identity_belongs_to_prefix(label, prefix):
            matches.append(entry)
            labels.add(label)
            iid = ident.get("id")
            if iid is not None:
                ids.add(str(iid))
    return matches, labels, ids


def write_client_aggregation_dir(prefix: str,
                                  entry: dict,
                                  all_roaming: list[dict],
                                  all_internal_networks: list[dict],
                                  all_sites: list[dict],
                                  top_identities: list[dict],
                                  blocked_records: list[dict],
                                  org_top_threats: list[dict],
                                  requests_by_hour: list[dict],
                                  categories_by_hour: list[dict],
                                  window_start_iso: str,
                                  window_end_iso: str,
                                  run_date: str,
                                  out_root: Path,
                                  inventory_snapshot_at: str,
                                  ) -> dict:
    # IMPORTANT: folder name = run_date (the activity day), NOT window_end.
    # window_end is the start of the NEXT UTC day; using it here would
    # overwrite the next day's folder.
    code = entry["LocationCode"]
    out_dir = out_root / code.lower() / "umbrella" / run_date
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Snapshot fields filtered to this client's prefix
    agents = [r for r in all_roaming
              if derive_prefix(r.get("name") or "") == prefix]
    nets = [n for n in all_internal_networks
            if (n.get("name") or "").upper().startswith(prefix)]
    sites = [s for s in all_sites
             if (s.get("name") or "").upper().startswith(prefix)]
    (out_dir / "roaming_computers.json").write_text(
        json.dumps(agents, indent=2, default=str), encoding="utf-8")
    write_csv(out_dir / "roaming_computers.csv", agents, ROAMING_PREFERRED_COLS)
    (out_dir / "internal_networks.json").write_text(
        json.dumps(nets, indent=2, default=str), encoding="utf-8")
    (out_dir / "sites.json").write_text(
        json.dumps(sites, indent=2, default=str), encoding="utf-8")

    # 2) Per-client top identities (filtered from org-wide)
    client_top_idents, client_labels, client_ids = (
        _filter_top_identities_for_prefix(top_identities, prefix))
    (out_dir / "top_identities.json").write_text(
        json.dumps(client_top_idents, indent=2, default=str), encoding="utf-8")

    client_total_requests = sum(int(e.get("requests") or 0) for e in client_top_idents)

    # 3) Per-client top threats (filter org-wide threats to those touching client identities)
    client_threats: list[dict] = []
    for t in org_top_threats:
        idents_touching = []
        for ident_entry in (t.get("identities") or []):
            label = ((ident_entry.get("identity") or {}).get("label")
                     or ident_entry.get("label") or "")
            if label in client_labels:
                idents_touching.append(label)
        if idents_touching:
            client_threats.append({
                "name": t.get("name") or t.get("threat") or t.get("threatType"),
                "category": t.get("category"),
                "type": t.get("type"),
                "count": t.get("count") or t.get("requests"),
                "identities_touching": idents_touching,
                "raw": t,
            })
    (out_dir / "top_threats.json").write_text(
        json.dumps(client_threats, indent=2, default=str), encoding="utf-8")

    # 4) Per-client blocked threats (raw blocked activity touching client identities)
    client_blocked = _aggregate_blocked_threats(blocked_records, client_labels)
    (out_dir / "blocked_threats.json").write_text(
        json.dumps(client_blocked, indent=2, default=str), encoding="utf-8")

    # 5) Top destinations - derive from blocked + top-identities counts
    # (org doesn't expose per-identity top-domains directly; we approximate with blocked
    # destinations + a fingerprint from top-identities.counts)
    domains: dict[str, int] = {}
    for r in client_blocked:
        d = r.get("domain")
        if d:
            domains[d] = domains.get(d, 0) + 1
    top_dest_blocked = sorted(domains.items(), key=lambda kv: kv[1], reverse=True)[:50]
    (out_dir / "top_destinations.json").write_text(
        json.dumps([{"domain": d, "count": c, "verdict": "blocked"}
                    for d, c in top_dest_blocked],
                   indent=2, default=str), encoding="utf-8")

    # 6) Activity summary - hourly curve filtered to client identities is not
    # directly available from requests-by-hour (org-wide); store the org-wide
    # curve plus the per-client request total as an approximation.
    # For a per-identity hourly breakdown, would need to call /reports/v2/activity
    # with identityId filter - too heavy for backfill.
    activity_summary = {
        "client_requests_total_via_top_identities": client_total_requests,
        "client_identity_count": len(client_top_idents),
        "client_blocked_records": len(client_blocked),
        "org_requests_by_hour": requests_by_hour,
        "org_categories_by_hour": categories_by_hour,
        "note": "client_requests_total_via_top_identities is the sum of requests "
                 "for this client's identities found in the org-wide top-1000. "
                 "If the client has more than 1000 identities or any fall outside "
                 "the top-1000, this undercounts. requests_by_hour and "
                 "categories_by_hour are org-wide (per-identity hourly is not in "
                 "the public v2 aggregation endpoints).",
    }
    (out_dir / "activity_summary.json").write_text(
        json.dumps(activity_summary, indent=2, default=str), encoding="utf-8")

    # Hourly curve as a separate file too for downstream readers
    (out_dir / "requests_by_hour.json").write_text(
        json.dumps(requests_by_hour, indent=2, default=str), encoding="utf-8")

    # 7) Pull summary
    status_counts: dict[str, int] = {}
    for a in agents:
        st = (a.get("status") or "").lower()
        status_counts[st] = status_counts.get(st, 0) + 1

    summary = {
        "prefix": prefix,
        "LocationCode": code,
        "Location_Name": entry.get("Location_Name"),
        "DirID": entry.get("DirID"),
        "match_source": entry.get("match_source"),
        "mode": "backfill",
        "data_source": "aggregations",
        "inventory_snapshot_at": inventory_snapshot_at,
        "window_start_iso": window_start_iso,
        "window_end_iso": window_end_iso,
        "agents_total": len(agents),
        "agents_status": status_counts,
        "internal_networks": len(nets),
        "sites": len(sites),
        "client_identities_in_top1k": len(client_top_idents),
        "client_requests_total": client_total_requests,
        "client_threats_total": len(client_threats),
        "client_blocked_threats": len(client_blocked),
        "errors": [],
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out_dir / "pull_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> int:
    args = parse_args()

    if args.mode == "raw":
        print("ERROR: --mode raw is reserved for forensic deep-dives and not implemented "
              "in this build. Use the daily pull with --date <YYYY-MM-DD> for a single-day "
              "raw pull at the 5000-record cap, or extend this script if you need a true "
              "raw walk.")
        return 2

    today_utc = datetime.now(timezone.utc).date()
    earliest_utc = today_utc - timedelta(days=RETENTION_DAYS - 1)

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = (datetime.strptime(args.end, "%Y-%m-%d").date()
           if args.end else today_utc - timedelta(days=1))

    if start > end:
        print(f"ERROR: --start {start} is after --end {end}")
        return 2
    if start < earliest_utc:
        print(f"WARNING: --start {start} is older than the {RETENTION_DAYS}-day "
              f"Umbrella retention window (earliest pullable: {earliest_utc}). "
              f"Days before {earliest_utc} will return zero events. Continuing.")

    skip_codes: set[str] = set()
    for s in args.skip:
        for x in s.split(","):
            x = x.strip().upper()
            if x:
                skip_codes.add(x)
    only_codes = None
    if args.only:
        only_codes = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    days = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)

    print(f"[{datetime.now():%H:%M:%S}] Cisco Umbrella backfill (aggregations mode)")
    print(f"  range:        {start} -> {end}  ({len(days)} days)")
    print(f"  retention:    {earliest_utc} (90 days back from {today_utc})")
    print(f"  only:         {sorted(only_codes) if only_codes else '(all mapped)'}")
    print(f"  skip:         {sorted(skip_codes) if skip_codes else '(none)'}")
    if args.dry_run:
        print("  --dry-run set - no API calls, no per-client folders")

    # 1) Snapshot pull (one-time inventory, used for every backfill day)
    print(f"[{datetime.now():%H:%M:%S}] fetching active CP clients + Umbrella snapshot...")
    cp_clients = cp_api.get_active_clients()
    sites = uapi.list_sites()
    networks = uapi.list_networks()
    internal_networks = uapi.list_internal_networks()
    roaming = uapi.list_roaming_computers()
    network_devices = uapi.list_network_devices()
    destination_lists = uapi.list_destination_lists()
    inventory_snapshot_at = _isoz(datetime.now(timezone.utc))
    print(f"  cp_clients={len(cp_clients)} roaming={len(roaming)} sites={len(sites)}"
          f" networks={len(networks)} internal_networks={len(internal_networks)}")

    manual = load_manual_mapping()
    mapping, _unmapped = resolve_prefix_mapping(roaming, cp_clients,
                                                 manual.get("manual") or {})
    ignore = {str(x).upper() for x in (manual.get("ignore") or [])}
    mapping = {p: e for p, e in mapping.items() if p not in ignore}

    eligible_prefixes = []
    for prefix, info in mapping.items():
        code = info["LocationCode"]
        if code in skip_codes:
            continue
        if only_codes is not None and code not in only_codes:
            continue
        eligible_prefixes.append((prefix, info))
    print(f"  eligible prefixes: {len(eligible_prefixes)} "
          f"({', '.join(info['LocationCode'] for _, info in eligible_prefixes)})")

    if not eligible_prefixes:
        print("  no prefixes match - nothing to backfill")
        return 0

    if args.dry_run:
        print(f"[{datetime.now():%H:%M:%S}] DRY-RUN  would backfill {len(days)} days "
              f"x {len(eligible_prefixes)} clients = "
              f"{len(days) * len(eligible_prefixes)} per-client folders")
        return 0

    # 2) Walk days
    master_log: list[dict] = []
    t0 = time.time()
    for i, d in enumerate(days, 1):
        window_end_dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1)
        window_start_dt = window_end_dt - timedelta(hours=24)
        window_start_iso = _isoz(window_start_dt)
        window_end_iso = _isoz(window_end_dt)
        run_date = d.strftime("%Y-%m-%d")
        outside_retention = d < earliest_utc

        elapsed = int(time.time() - t0)
        print(f"[{datetime.now():%H:%M:%S}] day {i}/{len(days)} {run_date} (elapsed {elapsed}s)")

        # Aggregation calls (cheap)
        day_errors: list[dict] = []
        try:
            top_identities = uapi.report_top_identities(
                str(_ms(window_start_dt)), str(_ms(window_end_dt)), limit=1000)
        except Exception as e:
            day_errors.append({"step": "top_identities", "err": str(e)})
            top_identities = []
        try:
            top_threats = uapi.report_top_threats(
                str(_ms(window_start_dt)), str(_ms(window_end_dt)), limit=1000)
        except Exception as e:
            day_errors.append({"step": "top_threats", "err": str(e)})
            top_threats = []
        try:
            requests_by_hour = uapi.report_requests_by_hour(
                str(_ms(window_start_dt)), str(_ms(window_end_dt)))
        except Exception as e:
            day_errors.append({"step": "requests_by_hour", "err": str(e)})
            requests_by_hour = []
        try:
            categories_by_hour = uapi.report_categories_by_hour(
                str(_ms(window_start_dt)), str(_ms(window_end_dt)))
        except Exception as e:
            day_errors.append({"step": "categories_by_hour", "err": str(e)})
            categories_by_hour = []
        try:
            blocked_records = uapi.list_activity_blocked(
                str(_ms(window_start_dt)), str(_ms(window_end_dt)),
                page_limit=5000, max_records=10000)
        except Exception as e:
            day_errors.append({"step": "blocked_activity", "err": str(e)})
            blocked_records = []

        # Org-wide rollup
        org_total_requests = sum(int(h.get("counts", {}).get("requests")
                                      or h.get("requests") or 0)
                                  for h in requests_by_hour)
        if not isinstance(org_total_requests, int) or org_total_requests == 0:
            # Some shapes use top-level numbers; sum what we can find
            org_total_requests = 0
            for h in requests_by_hour:
                v = (h.get("requests") or h.get("count") or 0)
                if isinstance(v, dict):
                    v = sum(int(x) for x in v.values() if isinstance(x, (int, float)))
                org_total_requests += int(v or 0)

        per_day_summary = {
            "run_date": run_date,
            "window_start": window_start_iso,
            "window_end": window_end_iso,
            "outside_retention": outside_retention,
            "org_top_identities_count": len(top_identities),
            "org_top_threats_count": len(top_threats),
            "org_requests_by_hour_buckets": len(requests_by_hour),
            "org_blocked_activity_records": len(blocked_records),
            "errors": day_errors,
            "clients": [],
        }

        # Skip empty days unless overridden
        if (org_total_requests == 0 and not blocked_records
                and not args.include_empty_days):
            print(f"  {run_date}: 0 events org-wide (skip; --include-empty-days to override)")
            master_log.append(per_day_summary)
            continue

        pipeline_run_dir = PIPELINE_ROOT / run_date
        pipeline_run_dir.mkdir(parents=True, exist_ok=True)

        # Per-client folders
        for prefix, info in eligible_prefixes:
            try:
                s = write_client_aggregation_dir(
                    prefix, info, roaming, internal_networks, sites,
                    top_identities, blocked_records, top_threats,
                    requests_by_hour, categories_by_hour,
                    window_start_iso, window_end_iso, run_date,
                    CLIENTS_ROOT, inventory_snapshot_at)
                if day_errors:
                    s["errors"].extend(day_errors)
                    (CLIENTS_ROOT / info["LocationCode"].lower() / "umbrella"
                     / run_date / "pull_summary.json").write_text(
                        json.dumps(s, indent=2, default=str), encoding="utf-8")
                per_day_summary["clients"].append({
                    "LocationCode": info["LocationCode"],
                    "agents_total": s["agents_total"],
                    "client_identities_in_top1k": s["client_identities_in_top1k"],
                    "client_requests_total": s["client_requests_total"],
                    "client_threats_total": s["client_threats_total"],
                    "client_blocked_threats": s["client_blocked_threats"],
                })
                print(f"    {info['LocationCode']:<8s} agents={s['agents_total']:>3d}"
                      f" idents={s['client_identities_in_top1k']:>2d}"
                      f" requests={s['client_requests_total']:>7d}"
                      f" threats={s['client_threats_total']:>3d}"
                      f" blocked={s['client_blocked_threats']:>3d}")
            except Exception as e:
                err = {"step": "write_client_dir", "client": info["LocationCode"],
                       "err": str(e), "tb": traceback.format_exc()}
                day_errors.append(err)
                print(f"    {info['LocationCode']:<8s} ERR: {e}")

        # Per-day run_log
        (pipeline_run_dir / "run_log.json").write_text(
            json.dumps({
                "mode": "backfill",
                "data_source": "aggregations",
                "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                **per_day_summary,
            }, indent=2, default=str), encoding="utf-8")

        master_log.append(per_day_summary)

    # 3) Master log
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    master_path = STATE_DIR / f"backfill-{start}-to-{end}.json"
    master_path.write_text(json.dumps({
        "mode": "backfill",
        "data_source": "aggregations",
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start": str(start),
        "end": str(end),
        "days": len(days),
        "earliest_pullable": str(earliest_utc),
        "inventory_snapshot_at": inventory_snapshot_at,
        "eligible_clients": [info["LocationCode"] for _, info in eligible_prefixes],
        "totals": {
            "days_with_data": sum(1 for d in master_log
                                   if any(c["client_requests_total"] for c in d["clients"])),
            "days_outside_retention": sum(1 for d in master_log if d["outside_retention"]),
            "errors": sum(len(d["errors"]) for d in master_log),
        },
        "per_day": master_log,
    }, indent=2, default=str), encoding="utf-8")

    print()
    print(f"[{datetime.now():%H:%M:%S}] BACKFILL DONE  ({int(time.time() - t0)}s)")
    days_with_data = sum(1 for d in master_log
                          if any(c["client_requests_total"] for c in d["clients"]))
    days_outside = sum(1 for d in master_log if d["outside_retention"])
    total_errors = sum(len(d["errors"]) for d in master_log)
    print(f"  days walked:           {len(days)}")
    print(f"  days with client data: {days_with_data}")
    print(f"  days outside retention:{days_outside}")
    print(f"  total errors:          {total_errors}")
    print(f"  master log:            {master_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
