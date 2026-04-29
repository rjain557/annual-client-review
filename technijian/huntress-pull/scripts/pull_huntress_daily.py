"""Pull the last 24h of Huntress AV/EDR + incident activity per active client.

Designed to run nightly at 1:00 AM PT via Windows Scheduled Task. The window is
[run_time - 24h, run_time) so consecutive runs do not double-count.

Scope (v1.1 - broadened 2026-04-29 to include historically-queryable activity):
    For every Huntress organization mapped to a Technijian Client Portal
    LocationCode, capture:

      1. Agent inventory snapshot (point-in-time; the API does not expose
         historical agent state). Drives "which computers have it installed",
         daily delta of healthy/offline agents, license-seat counts.

      2. Incident reports updated within the 24h window. Filterable by
         status/severity for SOC dashboards.

      3. Signals investigated within the 24h window. Server-side filtered.

      4. Summary / executive reports with period overlapping the 24h window.

    Helpers for external_ports, identities, and reseller line items remain in
    huntress_api.py but are not wired here. Add them only on explicit ask.

Per-client output (under clients/<code>/huntress/YYYY-MM-DD/):
    agents.json + agents.csv      full agent inventory with snapshot fields
    incident_reports.json         { window: [...24h...], all_recent: [...] }
    signals.json                  signals investigated_at within window
    reports.json                  summary/executive reports overlapping window
    pull_summary.json             counts, errors, mapping_source, window

Account-level output (under technijian/huntress-pull/<YYYY-MM-DD>/):
    account.json                  account info
    organizations.json            full Huntress org list
    mapping.json                  huntress_org_id -> LocationCode
    unmapped.json                 orgs with no LocationCode match
    run_log.json                  run summary (also under state/<date>.json)

Usage:
    python pull_huntress_daily.py                       # last 24h
    python pull_huntress_daily.py --hours 48
    python pull_huntress_daily.py --date 2026-04-29
    python pull_huntress_daily.py --only AAVA,BWH
    python pull_huntress_daily.py --skip ORX
    python pull_huntress_daily.py --dry-run
    python pull_huntress_daily.py --map-only            # mapping resolution only

A note on Security Awareness Training (SAT):
    Huntress Managed SAT is not exposed in the v1 REST API as of 2026-04. SAT
    is out of scope here. When SAT endpoints ship, add helpers to
    huntress_api.py and a per-client SAT pull next to agents.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
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
MAPPING_FILE = STATE_DIR / "huntress-org-mapping.json"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(CLIENTPORTAL_SCRIPTS))
import huntress_api as hapi  # noqa: E402
import cp_api  # noqa: E402


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------

def compute_window(run_at: datetime, hours: int) -> tuple[str, str]:
    """Return (window_start_iso, window_end_iso) in UTC, exclusive on the right."""
    end = run_at.astimezone(timezone.utc).replace(microsecond=0)
    start = end - timedelta(hours=hours)
    return _isoz(start), _isoz(end)


def _isoz(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _in_window(ts: str | None, win_start: datetime, win_end: datetime) -> bool:
    dt = _parse_dt(ts)
    return bool(dt and win_start <= dt < win_end)


# ---------------------------------------------------------------------------
# Org -> LocationCode mapping
# ---------------------------------------------------------------------------

_NAME_NOISE = re.compile(r"\b(inc|llc|llp|ltd|co|corp|corporation|company|the|of|and|&|holdings|group|services)\b",
                         flags=re.IGNORECASE)
_NAME_PUNCT = re.compile(r"[^a-z0-9]+")
# Huntress org name convention used by Technijian: "<CODE> - <Full Name>" or
# "<CODE>-<Full Name>" (no space). The prefix matches an active CP LocationCode.
_CODE_PREFIX = re.compile(r"^\s*([A-Z][A-Z0-9]{1,9})\s*-\s*\S")


def normalize_name(s: str) -> str:
    if not s:
        return ""
    out = s.lower()
    out = _NAME_NOISE.sub(" ", out)
    out = _NAME_PUNCT.sub("", out)
    return out.strip()


def extract_code_prefix(s: str) -> str | None:
    """Return the uppercase LocationCode prefix of a Huntress org name like
    'BWH - Brandywine Homes' or 'KES-KES Homes'. None if no clean match."""
    if not s:
        return None
    m = _CODE_PREFIX.match(s)
    return m.group(1).upper() if m else None


def load_manual_mapping() -> dict[str, Any]:
    """huntress-org-mapping.json shape:
        {
          "manual": {"<huntress_org_id>": "<LocationCode>"},
          "ignore": ["<huntress_org_id>"]
        }
    """
    if not MAPPING_FILE.exists():
        return {"manual": {}, "ignore": []}
    try:
        return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  WARN: could not parse {MAPPING_FILE.name}: {e}")
        return {"manual": {}, "ignore": []}


def resolve_mapping(orgs: list[dict], cp_clients: list[dict],
                    manual: dict[str, str],
                    ignore: set[str] | None = None) -> tuple[dict[str, dict], list[dict]]:
    """Match Huntress orgs to LocationCode. Returns (mapping, unmapped).
    Orgs whose id is in `ignore` are dropped silently (they don't appear in
    `unmapped` and don't get a per-client folder).
    """
    ignore = ignore or set()
    cp_by_norm: dict[str, dict] = {}
    cp_by_code: dict[str, dict] = {}
    for c in cp_clients:
        n = normalize_name(c.get("Location_Name") or "")
        if n:
            cp_by_norm.setdefault(n, c)
        code = (c.get("LocationCode") or "").upper()
        if code:
            cp_by_code[code] = c

    mapping: dict[str, dict] = {}
    unmapped: list[dict] = []

    for org in orgs:
        oid = str(org.get("id") or org.get("organization_id") or "")
        if not oid:
            continue
        if oid in ignore:
            continue
        oname = org.get("name") or ""

        # 1) manual override wins
        target_code = (manual.get(oid) or "").upper()
        if target_code and target_code in cp_by_code:
            c = cp_by_code[target_code]
            mapping[oid] = {
                "huntress_org_id": oid,
                "huntress_org_name": oname,
                "LocationCode": target_code,
                "Location_Name": c.get("Location_Name"),
                "DirID": c.get("DirID"),
                "match_source": "manual",
            }
            continue
        if target_code:
            unmapped.append({
                "huntress_org_id": oid,
                "huntress_org_name": oname,
                "reason": f"manual override -> {target_code} not in active client list",
            })
            continue

        # 2) exact normalized-name match
        n = normalize_name(oname)
        c = cp_by_norm.get(n) if n else None
        if c:
            mapping[oid] = {
                "huntress_org_id": oid,
                "huntress_org_name": oname,
                "LocationCode": (c.get("LocationCode") or "").upper(),
                "Location_Name": c.get("Location_Name"),
                "DirID": c.get("DirID"),
                "match_source": "name_exact",
            }
            continue

        # 3) "<CODE> - <Full Name>" prefix pattern (Huntress convention at Technijian)
        prefix_code = extract_code_prefix(oname)
        if prefix_code and prefix_code in cp_by_code:
            c = cp_by_code[prefix_code]
            mapping[oid] = {
                "huntress_org_id": oid,
                "huntress_org_name": oname,
                "LocationCode": prefix_code,
                "Location_Name": c.get("Location_Name"),
                "DirID": c.get("DirID"),
                "match_source": "code_prefix",
            }
            continue

        # 4) bare-code org name (e.g. "B2I") matches a LocationCode directly
        bare = oname.strip().upper()
        if bare in cp_by_code:
            c = cp_by_code[bare]
            mapping[oid] = {
                "huntress_org_id": oid,
                "huntress_org_name": oname,
                "LocationCode": bare,
                "Location_Name": c.get("Location_Name"),
                "DirID": c.get("DirID"),
                "match_source": "bare_code",
            }
            continue

        reason = "no name match - add to huntress-org-mapping.json manual block"
        if prefix_code:
            reason = f"prefix code '{prefix_code}' not in active CP client list"
        unmapped.append({
            "huntress_org_id": oid,
            "huntress_org_name": oname,
            "reason": reason,
        })

    return mapping, unmapped


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

AGENT_PREFERRED_COLS = [
    "id", "hostname", "platform", "os", "version", "edr_version",
    "last_callback_at", "last_survey_at",
    "defender_status", "defender_policy_status", "firewall_status",
    "ipv4_address", "external_ip", "domain_name",
    "serial_number", "organization_id",
]


def classify_agent_age(last_seen: datetime | None, now: datetime) -> str:
    """Return one of 'fresh' (<= 24h), 'recent' (<= 7d), 'stale' (<= 30d),
    'inactive' (> 30d), 'never' (no callback)."""
    if not last_seen:
        return "never"
    delta = now - last_seen
    if delta <= timedelta(hours=24):
        return "fresh"
    if delta <= timedelta(days=7):
        return "recent"
    if delta <= timedelta(days=30):
        return "stale"
    return "inactive"


def write_csv(path: Path, rows: list[dict], preferred_cols: list[str] | None = None) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    cols: list[str] = []
    seen: set[str] = set()
    if preferred_cols:
        for k in preferred_cols:
            if k not in seen:
                seen.add(k)
                cols.append(k)
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                cols.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            row = {}
            for c in cols:
                v = r.get(c)
                if isinstance(v, (list, dict)):
                    row[c] = json.dumps(v, default=str)
                else:
                    row[c] = v if v is not None else ""
            w.writerow(row)


# ---------------------------------------------------------------------------
# Per-org pull (agents only)
# ---------------------------------------------------------------------------

def pull_org(mapping_entry: dict,
             org_id: int | str,
             window_start_iso: str,
             window_end_iso: str,
             out_root: Path,
             dry_run: bool = False) -> dict:
    code = mapping_entry["LocationCode"]
    out_dir = out_root / code.lower() / "huntress" / window_end_iso[:10]

    summary: dict = {
        "huntress_org_id": str(org_id),
        "huntress_org_name": mapping_entry["huntress_org_name"],
        "LocationCode": code,
        "Location_Name": mapping_entry.get("Location_Name"),
        "DirID": mapping_entry.get("DirID"),
        "match_source": mapping_entry.get("match_source"),
        "window_start": window_start_iso,
        "window_end": window_end_iso,
        "agents_total": 0,
        "agents_called_back_in_window": 0,
        "agents_by_age": {"fresh": 0, "recent": 0, "stale": 0, "inactive": 0, "never": 0},
        "agents_by_platform": {},
        "agents_defender_status": {},
        "agents_defender_policy": {},
        "agents_firewall": {},
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
    win_start = datetime.fromisoformat(window_start_iso.replace("Z", "+00:00"))
    win_end = datetime.fromisoformat(window_end_iso.replace("Z", "+00:00"))

    # 1. Agents - point-in-time inventory (the API has no historical filter)
    try:
        agents = hapi.list_agents(organization_id=org_id)
    except Exception as e:
        summary["errors"].append({"step": "agents", "err": str(e),
                                   "tb": traceback.format_exc()})
        agents = []

    (out_dir / "agents.json").write_text(
        json.dumps(agents, indent=2, default=str), encoding="utf-8")
    write_csv(out_dir / "agents.csv", agents, AGENT_PREFERRED_COLS)
    summary["agents_total"] = len(agents)
    now = datetime.now(timezone.utc)
    for a in agents:
        last = _parse_dt(a.get("last_callback_at") or a.get("last_survey_at"))
        bucket = classify_agent_age(last, now)
        summary["agents_by_age"][bucket] += 1
        if last and win_start <= last < win_end:
            summary["agents_called_back_in_window"] += 1
        plat = a.get("platform") or "unknown"
        summary["agents_by_platform"][plat] = summary["agents_by_platform"].get(plat, 0) + 1
        for k, dest in (("defender_status", "agents_defender_status"),
                         ("defender_policy_status", "agents_defender_policy"),
                         ("firewall_status", "agents_firewall")):
            v = a.get(k) or "unknown"
            summary[dest][v] = summary[dest].get(v, 0) + 1

    # 2. Incident reports - filter to the 24h window by updated_at / sent_at / created_at
    try:
        incidents_all = hapi.list_incident_reports(organization_id=org_id)
    except Exception as e:
        summary["errors"].append({"step": "incident_reports", "err": str(e),
                                   "tb": traceback.format_exc()})
        incidents_all = []
    incidents_window = [
        x for x in incidents_all
        if _in_window(x.get("updated_at") or x.get("sent_at") or x.get("created_at"),
                       win_start, win_end)
    ]
    (out_dir / "incident_reports.json").write_text(
        json.dumps({"window": incidents_window, "all_recent": incidents_all},
                    indent=2, default=str),
        encoding="utf-8")
    summary["incidents_total_pulled"] = len(incidents_all)
    summary["incidents_in_window"] = len(incidents_window)

    # 3. Signals - server-side filtered by investigated_at
    try:
        signals = hapi.list_signals(organization_id=org_id,
                                     investigated_at_min=window_start_iso,
                                     investigated_at_max=window_end_iso)
    except Exception as e:
        summary["errors"].append({"step": "signals", "err": str(e),
                                   "tb": traceback.format_exc()})
        signals = []
    (out_dir / "signals.json").write_text(
        json.dumps(signals, indent=2, default=str), encoding="utf-8")
    summary["signals_in_window"] = len(signals)

    # 4. Reports - server-side filtered by period_min / period_max
    try:
        reports = hapi.list_reports(organization_id=org_id,
                                     period_min=window_start_iso,
                                     period_max=window_end_iso)
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
    ap = argparse.ArgumentParser(description="Pull last 24h Huntress AV/EDR agent activity per client.")
    ap.add_argument("--hours", type=int, default=24,
                    help="Lookback window in hours (default 24)")
    ap.add_argument("--date", help="Override end-of-window date (YYYY-MM-DD, anchors window end at 09:00 UTC)")
    ap.add_argument("--only", help="comma-separated LocationCodes")
    ap.add_argument("--skip", action="append", default=[],
                    help="LocationCode to skip (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="Plan only")
    ap.add_argument("--map-only", action="store_true",
                    help="Resolve and print Huntress org -> LocationCode mapping, then exit")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    run_at = datetime.now(timezone.utc)
    if args.date:
        d = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=9)
        run_at = d
    window_start_iso, window_end_iso = compute_window(run_at, args.hours)
    run_date = window_end_iso[:10]

    skip_codes = {s.upper() for s in args.skip for s in s.split(",") if s.strip()}
    only_codes = None
    if args.only:
        only_codes = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    print(f"[{datetime.now():%H:%M:%S}] Huntress daily AV pull")
    print(f"  window: {window_start_iso} -> {window_end_iso} ({args.hours}h)")
    print(f"  run_date dir tag: {run_date}")

    print(f"[{datetime.now():%H:%M:%S}] fetching active CP clients...")
    cp_clients = cp_api.get_active_clients()
    print(f"  got {len(cp_clients)} active CP clients")
    print(f"[{datetime.now():%H:%M:%S}] fetching Huntress organizations...")
    orgs = hapi.list_organizations()
    print(f"  got {len(orgs)} Huntress organizations")

    manual = load_manual_mapping()
    ignore = {str(x) for x in (manual.get("ignore") or [])}
    mapping, unmapped = resolve_mapping(orgs, cp_clients,
                                          manual.get("manual") or {}, ignore=ignore)

    print(f"  mapped: {len(mapping)}    unmapped: {len(unmapped)}    ignored: {len(ignore)}")
    if args.map_only:
        print()
        for oid, info in sorted(mapping.items(), key=lambda kv: kv[1]["LocationCode"]):
            print(f"  MAP  {info['LocationCode']:<8s} <- {info['huntress_org_name']:<40s} ({info['match_source']})")
        for u in unmapped:
            print(f"  ----  {u['huntress_org_id']:<10s} {u['huntress_org_name']:<40s} {u['reason']}")
        return 0

    if args.dry_run:
        print("  --dry-run set, skipping API pulls per org")
        return 0

    pipeline_run_dir = PIPELINE_ROOT / run_date
    pipeline_run_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{datetime.now():%H:%M:%S}] fetching account info...")
    try:
        account = hapi.get_account()
    except Exception as e:
        print(f"  account fetch failed: {e}")
        account = {"error": str(e)}
    (pipeline_run_dir / "account.json").write_text(
        json.dumps(account, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "organizations.json").write_text(
        json.dumps(orgs, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "mapping.json").write_text(
        json.dumps(mapping, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "unmapped.json").write_text(
        json.dumps(unmapped, indent=2, default=str), encoding="utf-8")

    overall: list[dict] = []
    items = list(mapping.items())
    for i, (oid, info) in enumerate(items, 1):
        if oid in ignore:
            continue
        code = info["LocationCode"]
        if code in skip_codes:
            print(f"  [{i}/{len(items)}] skip {code}")
            continue
        if only_codes is not None and code not in only_codes:
            continue
        s = pull_org(info, oid, window_start_iso, window_end_iso,
                     CLIENTS_ROOT, dry_run=False)
        flag = "  ERR" if s["errors"] else ""
        ab = s["agents_by_age"]
        print(f"  [{i}/{len(items)}] {code:<8s} oid={oid:<8s} agents={s['agents_total']:>3d}"
              f" fresh={ab['fresh']:>3d} stale={ab['stale']:>2d} inactive={ab['inactive']:>3d}"
              f" inc24h={s['incidents_in_window']:>2d} sig24h={s['signals_in_window']:>3d}{flag}")
        overall.append(s)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_date": run_date,
        "window_start": window_start_iso,
        "window_end": window_end_iso,
        "lookback_hours": args.hours,
        "huntress_orgs_total": len(orgs),
        "huntress_orgs_mapped": len(mapping),
        "huntress_orgs_unmapped": len(unmapped),
        "huntress_orgs_ignored": len(ignore),
        "clients_pulled": len(overall),
        "skipped_codes": sorted(skip_codes),
        "totals": {
            "agents": sum(r["agents_total"] for r in overall),
            "agents_called_back_in_window": sum(r["agents_called_back_in_window"] for r in overall),
            "agents_fresh": sum(r["agents_by_age"]["fresh"] for r in overall),
            "agents_recent": sum(r["agents_by_age"]["recent"] for r in overall),
            "agents_stale": sum(r["agents_by_age"]["stale"] for r in overall),
            "agents_inactive": sum(r["agents_by_age"]["inactive"] for r in overall),
            "agents_never": sum(r["agents_by_age"]["never"] for r in overall),
            "incidents_in_window": sum(r["incidents_in_window"] for r in overall),
            "signals_in_window": sum(r["signals_in_window"] for r in overall),
            "reports_overlapping_window": sum(r["reports_overlapping_window"] for r in overall),
        },
        "errors": [{"client": r["LocationCode"], "errors": r["errors"]}
                    for r in overall if r["errors"]],
        "results": overall,
    }
    log_path = STATE_DIR / f"{run_date}.json"
    log_path.write_text(json.dumps(log, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "run_log.json").write_text(
        json.dumps(log, indent=2, default=str), encoding="utf-8")

    print()
    print(f"[{datetime.now():%H:%M:%S}] DONE")
    print(f"  mapped clients:  {len(mapping)}")
    print(f"  pulled clients:  {len(overall)}")
    print(f"  unmapped orgs:   {len(unmapped)} (see {pipeline_run_dir / 'unmapped.json'})")
    print(f"  total agents:    {log['totals']['agents']:,}")
    print(f"    fresh (<=24h): {log['totals']['agents_fresh']:,}")
    print(f"    recent (<=7d): {log['totals']['agents_recent']:,}")
    print(f"    stale (<=30d): {log['totals']['agents_stale']:,}")
    print(f"    inactive (>30d): {log['totals']['agents_inactive']:,}")
    print(f"    never seen:    {log['totals']['agents_never']:,}")
    print(f"    called back 24h: {log['totals']['agents_called_back_in_window']:,}")
    print(f"  incidents 24h:   {log['totals']['incidents_in_window']:,}")
    print(f"  signals 24h:     {log['totals']['signals_in_window']:,}")
    print(f"  reports overlap: {log['totals']['reports_overlapping_window']:,}")
    print(f"  log:             {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
