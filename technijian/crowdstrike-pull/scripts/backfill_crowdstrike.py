"""Backfill historical CrowdStrike Falcon activity per client, per month.

The daily pull captures the last 24h. This script reaches back further using
the Falcon endpoints that DO support historical filtering via FQL:

    GET /alerts/queries/alerts/v2?filter=created_timestamp:>'<start>'+
                                         created_timestamp:<'<end>'
    GET /incidents/queries/incidents/v1?filter=modified_timestamp:>'<start>'+
                                                modified_timestamp:<'<end>'
    GET /incidents/queries/behaviors/v1?filter=timestamp:>'<start>'+
                                                timestamp:<'<end>'   (optional)

Hosts (`/devices/queries/devices/v1`) have NO historical filter and are
therefore NOT backfilled (the call would just return today's inventory in every
month folder). The current host inventory lives under
clients/<code>/crowdstrike/<today>/ via the daily pull.

Legacy detects (`/detects/queries/detects/v1`) returns 404 on US-2 - the
unified Alerts API replaces it. Skipped.

Output (under clients/<code>/crowdstrike/monthly/YYYY-MM/):
    alerts.json                   alerts created within the month
    incidents.json                incidents modified within the month
    behaviors.json                behaviors with timestamp in the month (when granted)
    pull_summary.json             counts, errors, window

Account-level outputs land at technijian/crowdstrike-pull/backfill/<YYYY-MM>/:
    children.json                 (snapshot at backfill time)
    mapping.json                  resolved member_cid -> LocationCode
    unmapped.json
    run_log.json                  per-month rollup

Usage:
    # Backfill every month from 2026-01 through the current month, all clients
    python backfill_crowdstrike.py --year 2026

    # Specific month range
    python backfill_crowdstrike.py --from 2026-01 --to 2026-03

    # Just one client across the year
    python backfill_crowdstrike.py --year 2026 --only BWH

    # Dry run / mapping check
    python backfill_crowdstrike.py --year 2026 --dry-run
    python backfill_crowdstrike.py --map-only
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PIPELINE_ROOT = HERE.parent
REPO = PIPELINE_ROOT.parent.parent
CLIENTPORTAL_SCRIPTS = REPO / "scripts" / "clientportal"
CLIENTS_ROOT = REPO / "clients"
BACKFILL_ROOT = PIPELINE_ROOT / "backfill"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(CLIENTPORTAL_SCRIPTS))
import cs_api  # noqa: E402
import cp_api  # noqa: E402
import pull_crowdstrike_daily as pull  # noqa: E402  (reuse mapping resolver)


# ---------------------------------------------------------------------------
# Month iteration helpers
# ---------------------------------------------------------------------------

def month_iter(start_yyyy_mm: str, end_yyyy_mm: str) -> list[str]:
    sy, sm = (int(x) for x in start_yyyy_mm.split("-"))
    ey, em = (int(x) for x in end_yyyy_mm.split("-"))
    out: list[str] = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def month_window(yyyy_mm: str) -> tuple[str, str]:
    """[start_iso (UTC, inclusive), end_iso (UTC, exclusive)] for the calendar
    month."""
    y, m = (int(x) for x in yyyy_mm.split("-"))
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        nxt_y, nxt_m = y + 1, 1
    else:
        nxt_y, nxt_m = y, m + 1
    end_excl = datetime(nxt_y, nxt_m, 1, tzinfo=timezone.utc)
    return pull._isoz(start), pull._isoz(end_excl)


def current_month() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


# ---------------------------------------------------------------------------
# Per-child-CID per-month backfill
# ---------------------------------------------------------------------------

def _alerts_filter(start_iso: str, end_iso: str) -> str:
    return f"created_timestamp:>='{start_iso}'+created_timestamp:<'{end_iso}'"


def _incidents_filter(start_iso: str, end_iso: str) -> str:
    return f"modified_timestamp:>='{start_iso}'+modified_timestamp:<'{end_iso}'"


def _behaviors_filter(start_iso: str, end_iso: str) -> str:
    return f"timestamp:>='{start_iso}'+timestamp:<'{end_iso}'"


def _cid_of(rec: dict) -> str:
    """Return the lowercase 32-char child CID embedded in a Falcon alert /
    incident / behavior record. Tries `cid`, then `device.cid`, then the first
    segment of `composite_id` / `aggregate_id`."""
    cid = (rec.get("cid")
           or (rec.get("device") or {}).get("cid")
           or (rec.get("composite_id") or "").split(":")[0]
           or (rec.get("aggregate_id") or "").split(":")[0])
    return (cid or "").lower()


def fetch_month_parent_level(yyyy_mm: str, win_start_iso: str, win_end_iso: str,
                              capture_behaviors: bool = False,
                              ) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Pull alerts / incidents / behaviors ONCE at the parent CID level for the
    month. Returns (alerts, incidents, behaviors, errors).

    Falcon's `/alerts/queries/alerts/v2` ignores `member_cid` for Flight Control
    parents (verified empirically 2026-04-29), so we pull once and bucket by
    the `cid` field on each record. Cuts API calls from ~29x to 1x per month.
    """
    errors: list[dict] = []

    # Alerts
    try:
        alert_ids = cs_api.list_all_ids(
            "/alerts/queries/alerts/v2",
            params={"filter": _alerts_filter(win_start_iso, win_end_iso)},
        )
        alerts = cs_api.get_alerts(alert_ids) if alert_ids else []
    except Exception as e:
        errors.append({"step": "alerts", "err": str(e),
                       "tb": traceback.format_exc()})
        alerts = []

    # Incidents - the queries endpoint returns 500 on US-2 without Incidents:Read
    # scope. Wrap and continue.
    try:
        incident_ids = cs_api.list_all_ids(
            "/incidents/queries/incidents/v1",
            params={
                "filter": _incidents_filter(win_start_iso, win_end_iso),
                "sort": "modified_timestamp.desc",
            },
        )
        incidents = cs_api.get_incidents(incident_ids) if incident_ids else []
    except Exception as e:
        errors.append({"step": "incidents", "err": str(e),
                       "tb": traceback.format_exc()})
        incidents = []

    # Behaviors (optional, high-cardinality)
    behaviors: list[dict] = []
    if capture_behaviors:
        try:
            beh_ids = cs_api.list_all_ids(
                "/incidents/queries/behaviors/v1",
                params={"filter": _behaviors_filter(win_start_iso, win_end_iso)},
            )
            behaviors = cs_api.get_behaviors(beh_ids) if beh_ids else []
        except Exception as e:
            errors.append({"step": "behaviors", "err": str(e),
                           "tb": traceback.format_exc()})
            behaviors = []

    return alerts, incidents, behaviors, errors


def write_child_month(mapping_entry: dict, member_cid: str, yyyy_mm: str,
                      win_start_iso: str, win_end_iso: str,
                      alerts: list[dict], incidents: list[dict],
                      behaviors: list[dict],
                      shared_errors: list[dict],
                      out_root: Path,
                      capture_behaviors: bool = False) -> dict:
    """Write the per-child-month folder using already-bucketed records."""
    code = mapping_entry["LocationCode"]
    out_dir = out_root / code.lower() / "crowdstrike" / "monthly" / yyyy_mm
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "member_cid": member_cid,
        "child_name": mapping_entry.get("child_name"),
        "LocationCode": code,
        "Location_Name": mapping_entry.get("Location_Name"),
        "DirID": mapping_entry.get("DirID"),
        "match_source": mapping_entry.get("match_source"),
        "month": yyyy_mm,
        "window_start": win_start_iso,
        "window_end": win_end_iso,
        "alerts_in_window": len(alerts),
        "incidents_in_window": len(incidents),
        "behaviors_in_window": len(behaviors),
        "errors": list(shared_errors),
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    (out_dir / "alerts.json").write_text(
        json.dumps(alerts, indent=2, default=str), encoding="utf-8")
    (out_dir / "incidents.json").write_text(
        json.dumps(incidents, indent=2, default=str), encoding="utf-8")
    if capture_behaviors:
        (out_dir / "behaviors.json").write_text(
            json.dumps(behaviors, indent=2, default=str), encoding="utf-8")

    (out_dir / "pull_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Backfill historical CrowdStrike Falcon activity per client per month.")
    ap.add_argument("--year", help="YYYY - backfill Jan through current month of that year")
    ap.add_argument("--from", dest="frm", help="YYYY-MM start month (inclusive)")
    ap.add_argument("--to", help="YYYY-MM end month (inclusive). Default: current month.")
    ap.add_argument("--only", help="comma-separated LocationCodes to include")
    ap.add_argument("--skip", action="append", default=[],
                    help="LocationCode to skip (repeatable)")
    ap.add_argument("--with-behaviors", action="store_true",
                    help="Also pull /incidents/queries/behaviors/v1 per month (high cardinality, off by default)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--map-only", action="store_true")
    return ap.parse_args()


def determine_months(args) -> list[str]:
    if args.year:
        cm = current_month()
        cur_y = int(cm.split("-")[0])
        target_y = int(args.year)
        if target_y < cur_y:
            return month_iter(f"{target_y:04d}-01", f"{target_y:04d}-12")
        if target_y == cur_y:
            return month_iter(f"{target_y:04d}-01", cm)
        raise SystemExit(f"--year {target_y} is in the future; refusing to run")
    if args.frm:
        end = args.to or current_month()
        return month_iter(args.frm, end)
    raise SystemExit("Specify --year YYYY or --from YYYY-MM (--to YYYY-MM optional)")


def main() -> int:
    args = parse_args()
    months = determine_months(args)

    skip_codes = {s.upper() for s in args.skip for s in s.split(",") if s.strip()}
    only_codes = None
    if args.only:
        only_codes = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    print(f"[{datetime.now():%H:%M:%S}] CrowdStrike backfill")
    print(f"  months: {months[0]} -> {months[-1]} ({len(months)} months)")
    if args.with_behaviors:
        print("  including /incidents/queries/behaviors/v1 per month")

    print(f"[{datetime.now():%H:%M:%S}] fetching active CP clients...")
    cp_clients = cp_api.get_active_clients()
    print(f"  got {len(cp_clients)} active CP clients")

    print(f"[{datetime.now():%H:%M:%S}] fetching Flight Control children...")
    child_ids = cs_api.list_mssp_children()
    if not child_ids:
        raise SystemExit(
            "No Flight Control child CIDs returned. The backfill script "
            "currently supports the multi-tenant case only. For a single-CID "
            "tenant, extend the script to use hostname_prefix bucketing.")
    children = cs_api.get_mssp_children(child_ids)
    print(f"  got {len(children)} child CIDs")

    manual_cfg = pull.load_manual_mapping()
    ignore = {str(x) for x in (manual_cfg.get("ignore") or [])}
    mapping, unmapped = pull.resolve_child_mapping(
        children, cp_clients,
        manual_cfg.get("manual") or {},
        ignore=ignore)
    print(f"  mapped: {len(mapping)}    unmapped: {len(unmapped)}    ignored: {len(ignore)}")

    if args.map_only:
        for cid, info in sorted(mapping.items(), key=lambda kv: kv[1]["LocationCode"]):
            print(f"  MAP  {info['LocationCode']:<8s} <- {info['child_name']:<40s} ({info['match_source']})")
        for u in unmapped:
            print(f"  ----  {u['member_cid']} {u['child_name']} {u['reason']}")
        return 0

    if args.dry_run:
        print("  --dry-run set, skipping per-child work")
        return 0

    BACKFILL_ROOT.mkdir(parents=True, exist_ok=True)
    overall_log: dict = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "months": months,
        "cs_children_total": len(children),
        "cs_children_mapped": len(mapping),
        "cs_children_unmapped": len(unmapped),
        "cs_children_ignored": len(ignore),
        "results_by_month": {},
    }

    for yyyy_mm in months:
        win_start_iso, win_end_iso = month_window(yyyy_mm)
        run_dir = BACKFILL_ROOT / yyyy_mm
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "children.json").write_text(
            json.dumps(children, indent=2, default=str), encoding="utf-8")
        (run_dir / "mapping.json").write_text(
            json.dumps(mapping, indent=2, default=str), encoding="utf-8")
        (run_dir / "unmapped.json").write_text(
            json.dumps(unmapped, indent=2, default=str), encoding="utf-8")

        # Pull alerts/incidents/behaviors ONCE at parent level for this month
        print(f"  {yyyy_mm}  fetching parent-level alerts/incidents/behaviors...")
        alerts, incidents, behaviors, shared_errors = fetch_month_parent_level(
            yyyy_mm, win_start_iso, win_end_iso,
            capture_behaviors=args.with_behaviors,
        )
        print(f"    parent totals: alt={len(alerts)} inc={len(incidents)}"
              + (f" beh={len(behaviors)}" if args.with_behaviors else ""))

        # Bucket records by child CID using the `cid` field on each record.
        cid_alerts: dict[str, list[dict]] = {}
        for a in alerts:
            cid_alerts.setdefault(_cid_of(a), []).append(a)
        cid_incidents: dict[str, list[dict]] = {}
        for x in incidents:
            cid_incidents.setdefault(_cid_of(x), []).append(x)
        cid_behaviors: dict[str, list[dict]] = {}
        for b in behaviors:
            cid_behaviors.setdefault(_cid_of(b), []).append(b)

        per_month: list[dict] = []
        items = list(mapping.items())
        for i, (cid, info) in enumerate(items, 1):
            code = info["LocationCode"]
            if code in skip_codes:
                continue
            if only_codes is not None and code not in only_codes:
                continue
            s = write_child_month(
                info, cid, yyyy_mm, win_start_iso, win_end_iso,
                alerts=cid_alerts.get(cid, []),
                incidents=cid_incidents.get(cid, []),
                behaviors=cid_behaviors.get(cid, []),
                shared_errors=shared_errors,
                out_root=CLIENTS_ROOT,
                capture_behaviors=args.with_behaviors,
            )
            flag = "  ERR" if s["errors"] else ""
            beh = f" beh={s['behaviors_in_window']:>4d}" if args.with_behaviors else ""
            per_month.append(s)
            print(f"  {yyyy_mm}  [{i:>2d}/{len(items)}] {code:<6s} cid={cid[:8]}..."
                  f" alt={s['alerts_in_window']:>4d}"
                  f" inc={s['incidents_in_window']:>3d}{beh}{flag}")

        month_log = {
            "month": yyyy_mm,
            "window_start": win_start_iso,
            "window_end": win_end_iso,
            "clients_pulled": len(per_month),
            "totals": {
                "alerts_in_window": sum(r["alerts_in_window"] for r in per_month),
                "incidents_in_window": sum(r["incidents_in_window"] for r in per_month),
                "behaviors_in_window": sum(r["behaviors_in_window"] for r in per_month),
            },
            "errors": [{"client": r["LocationCode"], "errors": r["errors"]}
                        for r in per_month if r["errors"]],
            "results": per_month,
        }
        (run_dir / "run_log.json").write_text(
            json.dumps(month_log, indent=2, default=str), encoding="utf-8")
        overall_log["results_by_month"][yyyy_mm] = {
            "clients_pulled": month_log["clients_pulled"],
            "totals": month_log["totals"],
        }

    overall_path = BACKFILL_ROOT / f"backfill-log-{datetime.now():%Y%m%d-%H%M%S}.json"
    overall_path.write_text(json.dumps(overall_log, indent=2, default=str),
                             encoding="utf-8")

    print()
    print(f"[{datetime.now():%H:%M:%S}] DONE")
    print(f"  months processed: {len(months)}")
    for yyyy_mm in months:
        t = overall_log["results_by_month"][yyyy_mm]["totals"]
        beh = f" beh={t['behaviors_in_window']:>5d}" if args.with_behaviors else ""
        print(f"    {yyyy_mm}: alt={t['alerts_in_window']:>5d}"
              f" inc={t['incidents_in_window']:>4d}{beh}")
    print(f"  log: {overall_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
