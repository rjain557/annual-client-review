"""Backfill historical Huntress activity per client, per month.

The daily pull captures the last 24h. This script reaches back further using
the Huntress endpoints that DO support historical filtering:

    GET /v1/incident_reports         -> filtered post-fetch by updated_at
    GET /v1/signals?investigated_at_min=&investigated_at_max=
    GET /v1/reports?period_min=&period_max=

The agents endpoint has NO historical filter and is therefore NOT backfilled
(it would just return today's inventory in every month folder). The current
agent inventory lives under clients/<code>/huntress/<today>/ via the daily
pull.

Output (under clients/<code>/huntress/monthly/YYYY-MM/):
    incident_reports.json        incidents updated within the month
    signals.json                  signals investigated within the month
    reports.json                  reports with period overlapping the month
    pull_summary.json             counts, errors, window

Account-level outputs land at technijian/huntress-pull/backfill/<YYYY-MM>/:
    organizations.json            (snapshot at backfill time)
    mapping.json                  resolved huntress_org_id -> LocationCode
    unmapped.json
    run_log.json                  per-month rollup

Usage:
    # Backfill every month from 2026-01 through the current month, all clients
    python backfill_huntress.py --year 2026

    # Specific month range
    python backfill_huntress.py --from 2026-01 --to 2026-03

    # Just one client across the year
    python backfill_huntress.py --year 2026 --only BWH

    # Dry run / mapping check
    python backfill_huntress.py --year 2026 --dry-run
    python backfill_huntress.py --map-only
"""
from __future__ import annotations

import argparse
import calendar
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
import huntress_api as hapi  # noqa: E402
import cp_api  # noqa: E402
import pull_huntress_daily as pull  # noqa: E402  (reuse mapping resolver)


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
# Per-org per-month backfill
# ---------------------------------------------------------------------------

def backfill_org_month(mapping_entry: dict, org_id: int | str,
                        yyyy_mm: str, win_start_iso: str, win_end_iso: str,
                        out_root: Path, dry_run: bool = False) -> dict:
    code = mapping_entry["LocationCode"]
    out_dir = out_root / code.lower() / "huntress" / "monthly" / yyyy_mm

    summary: dict[str, Any] = {
        "huntress_org_id": str(org_id),
        "huntress_org_name": mapping_entry["huntress_org_name"],
        "LocationCode": code,
        "Location_Name": mapping_entry.get("Location_Name"),
        "DirID": mapping_entry.get("DirID"),
        "match_source": mapping_entry.get("match_source"),
        "month": yyyy_mm,
        "window_start": win_start_iso,
        "window_end": win_end_iso,
        "incidents_total_pulled": 0,
        "incidents_in_window": 0,
        "signals_in_window": 0,
        "reports_overlapping_window": 0,
        "errors": [],
        "dry_run": dry_run,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if dry_run:
        return summary

    out_dir.mkdir(parents=True, exist_ok=True)
    win_start = datetime.fromisoformat(win_start_iso.replace("Z", "+00:00"))
    win_end = datetime.fromisoformat(win_end_iso.replace("Z", "+00:00"))

    # 1. Incident reports - the API does not expose a date filter on this
    #    endpoint, so we pull all and filter by updated_at locally. Note this
    #    means the backfill is bounded by Huntress's retention of incident
    #    records (no documented hard limit; backfill far enough back may
    #    silently miss closed incidents the platform pruned).
    try:
        all_inc = hapi.list_incident_reports(organization_id=org_id)
    except Exception as e:
        summary["errors"].append({"step": "incident_reports", "err": str(e),
                                   "tb": traceback.format_exc()})
        all_inc = []
    summary["incidents_total_pulled"] = len(all_inc)
    inc_window = [
        x for x in all_inc
        if pull._in_window(x.get("updated_at") or x.get("sent_at") or x.get("created_at"),
                            win_start, win_end)
    ]
    (out_dir / "incident_reports.json").write_text(
        json.dumps({"window": inc_window}, indent=2, default=str),
        encoding="utf-8")
    summary["incidents_in_window"] = len(inc_window)

    # 2. Signals - server-side filtered by investigated_at_min/max
    try:
        signals = hapi.list_signals(organization_id=org_id,
                                     investigated_at_min=win_start_iso,
                                     investigated_at_max=win_end_iso)
    except Exception as e:
        summary["errors"].append({"step": "signals", "err": str(e),
                                   "tb": traceback.format_exc()})
        signals = []
    (out_dir / "signals.json").write_text(
        json.dumps(signals, indent=2, default=str), encoding="utf-8")
    summary["signals_in_window"] = len(signals)

    # 3. Reports - server-side filtered by period_min/period_max
    try:
        reports = hapi.list_reports(organization_id=org_id,
                                     period_min=win_start_iso,
                                     period_max=win_end_iso)
    except Exception as e:
        summary["errors"].append({"step": "reports", "err": str(e),
                                   "tb": traceback.format_exc()})
        reports = []
    (out_dir / "reports.json").write_text(
        json.dumps(reports, indent=2, default=str), encoding="utf-8")
    summary["reports_overlapping_window"] = len(reports)

    (out_dir / "pull_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Backfill historical Huntress activity per client per month.")
    ap.add_argument("--year", help="YYYY - backfill Jan through current month of that year")
    ap.add_argument("--from", dest="frm", help="YYYY-MM start month (inclusive)")
    ap.add_argument("--to", help="YYYY-MM end month (inclusive). Default: current month.")
    ap.add_argument("--only", help="comma-separated LocationCodes to include")
    ap.add_argument("--skip", action="append", default=[],
                    help="LocationCode to skip (repeatable)")
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

    print(f"[{datetime.now():%H:%M:%S}] Huntress backfill")
    print(f"  months: {months[0]} -> {months[-1]} ({len(months)} months)")

    print(f"[{datetime.now():%H:%M:%S}] fetching active CP clients...")
    cp_clients = cp_api.get_active_clients()
    print(f"  got {len(cp_clients)} active CP clients")
    print(f"[{datetime.now():%H:%M:%S}] fetching Huntress organizations...")
    orgs = hapi.list_organizations()
    print(f"  got {len(orgs)} Huntress organizations")

    manual = pull.load_manual_mapping()
    ignore = {str(x) for x in (manual.get("ignore") or [])}
    mapping, unmapped = pull.resolve_mapping(orgs, cp_clients,
                                              manual.get("manual") or {},
                                              ignore=ignore)
    print(f"  mapped: {len(mapping)}    unmapped: {len(unmapped)}    ignored: {len(ignore)}")

    if args.map_only:
        for oid, info in sorted(mapping.items(), key=lambda kv: kv[1]["LocationCode"]):
            print(f"  MAP  {info['LocationCode']:<8s} <- {info['huntress_org_name']:<40s} ({info['match_source']})")
        for u in unmapped:
            print(f"  ----  {u['huntress_org_id']:<10s} {u['huntress_org_name']:<40s} {u['reason']}")
        return 0

    if args.dry_run:
        print("  --dry-run set, skipping per-org work")
        return 0

    BACKFILL_ROOT.mkdir(parents=True, exist_ok=True)
    overall_log: dict = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "months": months,
        "huntress_orgs_total": len(orgs),
        "huntress_orgs_mapped": len(mapping),
        "huntress_orgs_unmapped": len(unmapped),
        "huntress_orgs_ignored": len(ignore),
        "results_by_month": {},
    }

    for yyyy_mm in months:
        win_start_iso, win_end_iso = month_window(yyyy_mm)
        run_dir = BACKFILL_ROOT / yyyy_mm
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "organizations.json").write_text(
            json.dumps(orgs, indent=2, default=str), encoding="utf-8")
        (run_dir / "mapping.json").write_text(
            json.dumps(mapping, indent=2, default=str), encoding="utf-8")
        (run_dir / "unmapped.json").write_text(
            json.dumps(unmapped, indent=2, default=str), encoding="utf-8")

        per_month: list[dict] = []
        items = list(mapping.items())
        for i, (oid, info) in enumerate(items, 1):
            code = info["LocationCode"]
            if code in skip_codes:
                continue
            if only_codes is not None and code not in only_codes:
                continue
            s = backfill_org_month(info, oid, yyyy_mm,
                                    win_start_iso, win_end_iso,
                                    CLIENTS_ROOT, dry_run=False)
            flag = "  ERR" if s["errors"] else ""
            per_month.append(s)
            print(f"  {yyyy_mm}  [{i:>2d}/{len(items)}] {code:<6s} oid={oid:<7s}"
                  f" inc={s['incidents_in_window']:>3d} sig={s['signals_in_window']:>4d}"
                  f" rep={s['reports_overlapping_window']:>2d}{flag}")

        month_log = {
            "month": yyyy_mm,
            "window_start": win_start_iso,
            "window_end": win_end_iso,
            "clients_pulled": len(per_month),
            "totals": {
                "incidents_in_window": sum(r["incidents_in_window"] for r in per_month),
                "signals_in_window": sum(r["signals_in_window"] for r in per_month),
                "reports_overlapping_window": sum(r["reports_overlapping_window"] for r in per_month),
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
        print(f"    {yyyy_mm}: inc={t['incidents_in_window']:>4d}"
              f" sig={t['signals_in_window']:>5d}"
              f" rep={t['reports_overlapping_window']:>3d}")
    print(f"  log: {overall_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
