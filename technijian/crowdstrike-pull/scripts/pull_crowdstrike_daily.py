"""Pull the last 24h of CrowdStrike Falcon EDR activity per active client.

Designed to run nightly at 3:00 AM PT via Windows Scheduled Task on the
production workstation. The window is [run_time - 24h, run_time) so consecutive
runs do not double-count the boundary minute.

Tenancy detection:
    The script first calls /mssp/queries/children/v1 to detect whether
    Technijian's CrowdStrike tenant is a Falcon Flight Control parent. If yes,
    each child CID is mapped to a Client Portal LocationCode (same convention
    as Huntress). If no, the tenant is treated as a single CID and per-client
    mapping falls back to host hostname/tag prefix (same as Cisco Umbrella).

Per-client output (under clients/<code>/crowdstrike/YYYY-MM-DD/):
    hosts.json + hosts.csv         full host inventory snapshot
    detects.json                   detections last_behavior in window
    alerts.json                    unified alerts created in window
    incidents.json                 incidents created/modified in window
    pull_summary.json              counts, errors, mapping_source, window

Account-level output (under technijian/crowdstrike-pull/<YYYY-MM-DD>/):
    ccid.json                      parent CCID (the entire Technijian tenant id)
    children.json                  Flight Control child CIDs (or empty)
    mapping.json                   member_cid -> LocationCode mapping
    unmapped.json                  child CIDs (or hostname prefixes) with no LocationCode match
    run_log.json                   run summary (also under state/<date>.json)

Usage:
    python pull_crowdstrike_daily.py                       # last 24h
    python pull_crowdstrike_daily.py --hours 48
    python pull_crowdstrike_daily.py --date 2026-04-29
    python pull_crowdstrike_daily.py --only AAVA,BWH
    python pull_crowdstrike_daily.py --skip ORX
    python pull_crowdstrike_daily.py --dry-run
    python pull_crowdstrike_daily.py --map-only            # mapping resolution only

This pull is read-only and uses ONLY the helpers in cs_api.py that target the
read scopes listed in keys/crowdstrike.md. It does not call any RTR-execute,
isolation, detection-acknowledgement, IOC-write, or policy-mutation endpoint.
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
MAPPING_FILE = STATE_DIR / "crowdstrike-cid-mapping.json"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(CLIENTPORTAL_SCRIPTS))
import cs_api  # noqa: E402
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


# ---------------------------------------------------------------------------
# CID -> LocationCode mapping (Flight Control multi-tenant case)
# ---------------------------------------------------------------------------

_NAME_NOISE = re.compile(
    r"\b(inc|llc|llp|ltd|co|corp|corporation|company|the|of|and|&|holdings|group|services)\b",
    flags=re.IGNORECASE)
_NAME_PUNCT = re.compile(r"[^a-z0-9]+")
_CODE_PREFIX = re.compile(r"^\s*([A-Z][A-Z0-9]{1,9})\s*-\s*\S")


def normalize_name(s: str) -> str:
    if not s:
        return ""
    out = s.lower()
    out = _NAME_NOISE.sub(" ", out)
    out = _NAME_PUNCT.sub("", out)
    return out.strip()


def extract_code_prefix(s: str) -> str | None:
    if not s:
        return None
    m = _CODE_PREFIX.match(s)
    return m.group(1).upper() if m else None


def load_manual_mapping() -> dict[str, Any]:
    """crowdstrike-cid-mapping.json shape:
        {
          "manual": {"<member_cid>": "<LocationCode>"},
          "ignore": ["<member_cid>"],
          "hostname_prefix": {"BWH": ["BWH-", "brandywine-"]}  # single-CID fallback
        }
    """
    if not MAPPING_FILE.exists():
        return {"manual": {}, "ignore": [], "hostname_prefix": {}}
    try:
        return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  WARN: could not parse {MAPPING_FILE.name}: {e}")
        return {"manual": {}, "ignore": [], "hostname_prefix": {}}


def resolve_child_mapping(children: list[dict], cp_clients: list[dict],
                          manual: dict[str, str],
                          ignore: set[str] | None = None) -> tuple[dict[str, dict], list[dict]]:
    """Match CrowdStrike child CIDs to LocationCode. Returns (mapping, unmapped)."""
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

    for child in children:
        cid = (child.get("child_cid") or child.get("cid") or "").strip()
        if not cid:
            continue
        if cid in ignore:
            continue
        cname = child.get("name") or child.get("description") or ""

        # 1) manual override
        target = (manual.get(cid) or "").upper()
        if target and target in cp_by_code:
            c = cp_by_code[target]
            mapping[cid] = {
                "member_cid": cid,
                "child_name": cname,
                "LocationCode": target,
                "Location_Name": c.get("Location_Name"),
                "DirID": c.get("DirID"),
                "match_source": "manual",
            }
            continue
        if target:
            unmapped.append({
                "member_cid": cid,
                "child_name": cname,
                "reason": f"manual override -> {target} not in active CP client list",
            })
            continue

        # 2) exact normalized-name match
        n = normalize_name(cname)
        c = cp_by_norm.get(n) if n else None
        if c:
            mapping[cid] = {
                "member_cid": cid,
                "child_name": cname,
                "LocationCode": (c.get("LocationCode") or "").upper(),
                "Location_Name": c.get("Location_Name"),
                "DirID": c.get("DirID"),
                "match_source": "name_exact",
            }
            continue

        # 3) "<CODE> - <Full Name>" prefix
        prefix = extract_code_prefix(cname)
        if prefix and prefix in cp_by_code:
            c = cp_by_code[prefix]
            mapping[cid] = {
                "member_cid": cid,
                "child_name": cname,
                "LocationCode": prefix,
                "Location_Name": c.get("Location_Name"),
                "DirID": c.get("DirID"),
                "match_source": "code_prefix",
            }
            continue

        # 4) bare uppercase code
        bare = cname.strip().upper()
        if bare in cp_by_code:
            c = cp_by_code[bare]
            mapping[cid] = {
                "member_cid": cid,
                "child_name": cname,
                "LocationCode": bare,
                "Location_Name": c.get("Location_Name"),
                "DirID": c.get("DirID"),
                "match_source": "bare_code",
            }
            continue

        reason = "no name match - add to crowdstrike-cid-mapping.json manual block"
        if prefix:
            reason = f"prefix code '{prefix}' not in active CP client list"
        unmapped.append({
            "member_cid": cid,
            "child_name": cname,
            "reason": reason,
        })

    return mapping, unmapped


# ---------------------------------------------------------------------------
# Single-CID fallback: per-client mapping by hostname prefix
# ---------------------------------------------------------------------------

def bucket_hosts_by_prefix(hosts: list[dict],
                           prefix_map: dict[str, list[str]]) -> tuple[dict[str, list[dict]], list[dict]]:
    """When the tenant is single-CID, group hosts into clients by hostname/tag
    prefix. prefix_map: {"BWH": ["BWH-", "brandywine-"]}.
    Returns (per_code_hosts, unmatched_hosts).
    """
    if not prefix_map:
        return {}, list(hosts)
    # Pre-lower for case-insensitive prefix match
    table = [(code.upper(), [p.lower() for p in prefixes])
             for code, prefixes in prefix_map.items()]
    out: dict[str, list[dict]] = {}
    unmatched: list[dict] = []
    for h in hosts:
        hostname = (h.get("hostname") or "").lower()
        tags = h.get("tags") or []
        tags_lc = [t.lower() if isinstance(t, str) else "" for t in tags]
        match_code: str | None = None
        for code, prefixes in table:
            if any(hostname.startswith(p) for p in prefixes):
                match_code = code
                break
            if any(any(t.startswith(p) for p in prefixes) for t in tags_lc):
                match_code = code
                break
        if match_code:
            out.setdefault(match_code, []).append(h)
        else:
            unmatched.append(h)
    return out, unmatched


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

HOST_PREFERRED_COLS = [
    "device_id", "hostname", "platform_name", "os_version", "os_build",
    "agent_version", "first_seen", "last_seen", "last_login_user",
    "external_ip", "local_ip", "mac_address",
    "system_manufacturer", "system_product_name", "serial_number",
    "status", "kernel_version", "site_name", "machine_domain",
    "tags", "device_policies", "groups", "cid",
]


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
            row: dict[str, Any] = {}
            for c in cols:
                v = r.get(c)
                if isinstance(v, (list, dict)):
                    row[c] = json.dumps(v, default=str)
                else:
                    row[c] = v if v is not None else ""
            w.writerow(row)


# ---------------------------------------------------------------------------
# Per-client pull
# ---------------------------------------------------------------------------

def pull_for_code(code: str, hosts: list[dict], detects: list[dict],
                  alerts: list[dict], incidents: list[dict],
                  match_info: dict, window_start_iso: str, window_end_iso: str,
                  out_root: Path, errors: list[dict]) -> dict:
    out_dir = out_root / code.lower() / "crowdstrike" / window_end_iso[:10]
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict = {
        "LocationCode": code,
        "match_source": match_info.get("match_source"),
        "member_cid": match_info.get("member_cid"),
        "Location_Name": match_info.get("Location_Name"),
        "DirID": match_info.get("DirID"),
        "window_start": window_start_iso,
        "window_end": window_end_iso,
        "hosts_total": len(hosts),
        "hosts_seen_in_window": 0,
        "hosts_by_platform": {},
        "hosts_by_status": {},
        "detects_in_window": len(detects),
        "alerts_in_window": len(alerts),
        "incidents_in_window": len(incidents),
        "errors": errors,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    win_start = datetime.fromisoformat(window_start_iso.replace("Z", "+00:00"))
    win_end = datetime.fromisoformat(window_end_iso.replace("Z", "+00:00"))
    for h in hosts:
        last = _parse_dt(h.get("last_seen"))
        if last and win_start <= last < win_end:
            summary["hosts_seen_in_window"] += 1
        plat = (h.get("platform_name") or "unknown").lower()
        summary["hosts_by_platform"][plat] = summary["hosts_by_platform"].get(plat, 0) + 1
        st = (h.get("status") or "unknown").lower()
        summary["hosts_by_status"][st] = summary["hosts_by_status"].get(st, 0) + 1

    (out_dir / "hosts.json").write_text(
        json.dumps(hosts, indent=2, default=str), encoding="utf-8")
    write_csv(out_dir / "hosts.csv", hosts, HOST_PREFERRED_COLS)
    (out_dir / "detects.json").write_text(
        json.dumps(detects, indent=2, default=str), encoding="utf-8")
    (out_dir / "alerts.json").write_text(
        json.dumps(alerts, indent=2, default=str), encoding="utf-8")
    (out_dir / "incidents.json").write_text(
        json.dumps(incidents, indent=2, default=str), encoding="utf-8")
    (out_dir / "pull_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------
# Pull pipelines
# ---------------------------------------------------------------------------

def _cid_of(rec: dict) -> str:
    """Return lowercase 32-char child CID from a Falcon alert/incident/detect."""
    cid = (rec.get("cid")
           or (rec.get("device") or {}).get("cid")
           or (rec.get("composite_id") or "").split(":")[0]
           or (rec.get("aggregate_id") or "").split(":")[0])
    return (cid or "").lower()


def pull_per_child_cid(mapping: dict[str, dict], window_start_iso: str,
                       window_end_iso: str, out_root: Path,
                       only_codes: set[str] | None,
                       skip_codes: set[str]) -> list[dict]:
    """Multi-tenant pull. Hosts are per-child (member_cid is honored).
    Alerts/incidents/detects are pulled ONCE at parent level and bucketed by
    the `cid` field on each record - Falcon's `/alerts/queries/alerts/v2`
    endpoint ignores `member_cid` for Flight Control parents (verified
    2026-04-29), so per-child queries return identical full-tenant sets.
    """
    overall: list[dict] = []

    # 1. One-shot parent-level fetch for alerts, detects, incidents
    shared_errors: list[dict] = []
    print("  fetching alerts at parent level...")
    try:
        alert_ids = cs_api.list_all_ids(
            "/alerts/queries/alerts/v2",
            params={"filter": f"created_timestamp:>'{window_start_iso}'"},
        )
        alerts_all = cs_api.get_alerts(alert_ids) if alert_ids else []
    except Exception as e:
        shared_errors.append({"step": "alerts", "err": str(e),
                               "tb": traceback.format_exc()})
        alerts_all = []
    print(f"    {len(alerts_all):,} alerts total")

    print("  fetching legacy detects at parent level...")
    try:
        detect_ids = cs_api.list_detect_ids(
            filter_str=f"last_behavior:>'{window_start_iso}'")
        detects_all = cs_api.get_detects(detect_ids) if detect_ids else []
    except Exception as e:
        shared_errors.append({"step": "detects", "err": str(e),
                               "tb": traceback.format_exc()})
        detects_all = []
    print(f"    {len(detects_all):,} detects total")

    print("  fetching incidents at parent level...")
    try:
        incident_ids = cs_api.list_incident_ids(
            filter_str=f"modified_timestamp:>'{window_start_iso}'")
        incidents_all = cs_api.get_incidents(incident_ids) if incident_ids else []
    except Exception as e:
        shared_errors.append({"step": "incidents", "err": str(e),
                               "tb": traceback.format_exc()})
        incidents_all = []
    print(f"    {len(incidents_all):,} incidents total")

    # 2. Bucket parent-level records by child CID
    cid_alerts: dict[str, list[dict]] = {}
    for a in alerts_all:
        cid_alerts.setdefault(_cid_of(a), []).append(a)
    cid_detects: dict[str, list[dict]] = {}
    for d in detects_all:
        cid_detects.setdefault(_cid_of(d), []).append(d)
    cid_incidents: dict[str, list[dict]] = {}
    for x in incidents_all:
        cid_incidents.setdefault(_cid_of(x), []).append(x)

    # 3. Per-child loop fetches only hosts (which DO honor member_cid)
    items = list(mapping.items())
    for i, (cid, info) in enumerate(items, 1):
        code = info["LocationCode"]
        if code in skip_codes:
            print(f"  [{i}/{len(items)}] skip {code}")
            continue
        if only_codes is not None and code not in only_codes:
            continue

        errors: list[dict] = list(shared_errors)
        try:
            host_ids = cs_api.list_host_ids(member_cid=cid)
            hosts = cs_api.get_hosts(host_ids, member_cid=cid) if host_ids else []
        except Exception as e:
            errors.append({"step": "hosts", "err": str(e),
                           "tb": traceback.format_exc()})
            hosts = []

        alerts = cid_alerts.get(cid, [])
        detects = cid_detects.get(cid, [])
        incidents = cid_incidents.get(cid, [])

        s = pull_for_code(code, hosts, detects, alerts, incidents, info,
                          window_start_iso, window_end_iso, out_root, errors)
        flag = "  ERR" if [e for e in errors if e not in shared_errors] else ""
        print(f"  [{i}/{len(items)}] {code:<8s} cid={cid[:8]}... hosts={s['hosts_total']:>3d}"
              f" seen={s['hosts_seen_in_window']:>3d} alt={s['alerts_in_window']:>2d}"
              f" det={s['detects_in_window']:>2d} inc={s['incidents_in_window']:>2d}{flag}")
        overall.append(s)
    return overall


def pull_single_cid(prefix_map: dict[str, list[str]], window_start_iso: str,
                    window_end_iso: str, out_root: Path,
                    only_codes: set[str] | None,
                    skip_codes: set[str]) -> tuple[list[dict], list[dict]]:
    """Single-CID: pull once, then bucket by hostname/tag prefix."""
    print("  fetching all hosts (single-CID)...")
    host_ids = cs_api.list_host_ids()
    hosts_all = cs_api.get_hosts(host_ids) if host_ids else []
    print(f"    {len(hosts_all):,} total hosts in tenant")

    print("  fetching alerts in window...")
    try:
        alert_ids = cs_api.list_alert_ids(
            filter_str=f"created_timestamp:>'{window_start_iso}'")
        alerts_all = cs_api.get_alerts(alert_ids) if alert_ids else []
    except Exception as e:
        print(f"    alert fetch failed: {e}")
        alerts_all = []

    print("  fetching detects in window...")
    try:
        detect_ids = cs_api.list_detect_ids(
            filter_str=f"last_behavior:>'{window_start_iso}'")
        detects_all = cs_api.get_detects(detect_ids) if detect_ids else []
    except Exception as e:
        print(f"    detect fetch failed: {e}")
        detects_all = []

    print("  fetching incidents in window...")
    try:
        incident_ids = cs_api.list_incident_ids(
            filter_str=f"modified_timestamp:>'{window_start_iso}'")
        incidents_all = cs_api.get_incidents(incident_ids) if incident_ids else []
    except Exception as e:
        print(f"    incident fetch failed: {e}")
        incidents_all = []

    per_code_hosts, unmatched_hosts = bucket_hosts_by_prefix(hosts_all, prefix_map)
    # alerts/detects/incidents are device-id-keyed; bucket by host membership
    host_to_code: dict[str, str] = {}
    for code, hs in per_code_hosts.items():
        for h in hs:
            did = h.get("device_id") or h.get("aid") or ""
            if did:
                host_to_code[did] = code

    def _device_id_of(rec: dict) -> str:
        return (rec.get("device_id") or rec.get("aid")
                or (rec.get("device") or {}).get("device_id") or "")

    per_code_alerts: dict[str, list[dict]] = {}
    per_code_detects: dict[str, list[dict]] = {}
    per_code_incidents: dict[str, list[dict]] = {}
    for src, dest in [(alerts_all, per_code_alerts),
                       (detects_all, per_code_detects),
                       (incidents_all, per_code_incidents)]:
        for r in src:
            did = _device_id_of(r)
            code = host_to_code.get(did)
            if code:
                dest.setdefault(code, []).append(r)

    overall: list[dict] = []
    items = sorted(per_code_hosts.keys())
    for i, code in enumerate(items, 1):
        if code in skip_codes:
            print(f"  [{i}/{len(items)}] skip {code}")
            continue
        if only_codes is not None and code not in only_codes:
            continue
        info = {"match_source": "hostname_prefix", "member_cid": "(single-CID)"}
        s = pull_for_code(code, per_code_hosts.get(code, []),
                           per_code_detects.get(code, []),
                           per_code_alerts.get(code, []),
                           per_code_incidents.get(code, []),
                           info, window_start_iso, window_end_iso,
                           out_root, errors=[])
        print(f"  [{i}/{len(items)}] {code:<8s} hosts={s['hosts_total']:>3d}"
              f" seen={s['hosts_seen_in_window']:>3d} alt={s['alerts_in_window']:>2d}"
              f" det={s['detects_in_window']:>2d} inc={s['incidents_in_window']:>2d}")
        overall.append(s)
    return overall, unmatched_hosts


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Pull last 24h CrowdStrike Falcon EDR activity per client.")
    ap.add_argument("--hours", type=int, default=24,
                    help="Lookback window in hours (default 24)")
    ap.add_argument("--date", help="Override end-of-window date (YYYY-MM-DD, anchors window end at 09:00 UTC)")
    ap.add_argument("--only", help="comma-separated LocationCodes")
    ap.add_argument("--skip", action="append", default=[],
                    help="LocationCode to skip (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="Plan only")
    ap.add_argument("--map-only", action="store_true",
                    help="Resolve and print mapping, then exit")
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

    print(f"[{datetime.now():%H:%M:%S}] CrowdStrike daily Falcon pull")
    print(f"  window: {window_start_iso} -> {window_end_iso} ({args.hours}h)")
    print(f"  run_date dir tag: {run_date}")

    print(f"[{datetime.now():%H:%M:%S}] fetching active CP clients...")
    cp_clients = cp_api.get_active_clients()
    print(f"  got {len(cp_clients)} active CP clients")

    print(f"[{datetime.now():%H:%M:%S}] checking Flight Control / MSSP children...")
    child_ids = cs_api.list_mssp_children()
    if child_ids:
        print(f"  multi-tenant: {len(child_ids)} child CID(s)")
        children = cs_api.get_mssp_children(child_ids)
    else:
        print("  single-tenant CID (MSSP children endpoint returned 0)")
        children = []

    manual_cfg = load_manual_mapping()
    ignore = {str(x) for x in (manual_cfg.get("ignore") or [])}
    mapping: dict[str, dict] = {}
    unmapped: list[dict] = []
    if children:
        mapping, unmapped = resolve_child_mapping(
            children, cp_clients,
            manual_cfg.get("manual") or {},
            ignore=ignore,
        )
        print(f"  mapped: {len(mapping)}    unmapped: {len(unmapped)}    ignored: {len(ignore)}")

    if args.map_only:
        print()
        if children:
            for cid, info in sorted(mapping.items(), key=lambda kv: kv[1]["LocationCode"]):
                print(f"  MAP   {info['LocationCode']:<8s} <- {info['child_name']:<40s} ({info['match_source']})")
            for u in unmapped:
                print(f"  ----  {u['member_cid']} {u['child_name']} {u['reason']}")
        else:
            print("  Single-CID tenant. Mapping is by hostname/tag prefix.")
            for code, prefixes in (manual_cfg.get("hostname_prefix") or {}).items():
                print(f"  PREFIX  {code:<8s} <- {prefixes}")
            print("  Define hostname_prefix in crowdstrike-cid-mapping.json to enable per-client buckets.")
        return 0

    if args.dry_run:
        print("  --dry-run set, skipping API pulls per client")
        return 0

    pipeline_run_dir = PIPELINE_ROOT / run_date
    pipeline_run_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{datetime.now():%H:%M:%S}] fetching parent CCID...")
    try:
        ccid = cs_api.get_ccid()
    except Exception as e:
        print(f"  ccid fetch failed: {e}")
        ccid = {"error": str(e)}
    (pipeline_run_dir / "ccid.json").write_text(
        json.dumps(ccid, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "children.json").write_text(
        json.dumps(children, indent=2, default=str), encoding="utf-8")
    if children:
        (pipeline_run_dir / "mapping.json").write_text(
            json.dumps(mapping, indent=2, default=str), encoding="utf-8")
        (pipeline_run_dir / "unmapped.json").write_text(
            json.dumps(unmapped, indent=2, default=str), encoding="utf-8")

    overall: list[dict] = []
    unmatched_hosts: list[dict] = []
    if children and mapping:
        overall = pull_per_child_cid(mapping, window_start_iso, window_end_iso,
                                       CLIENTS_ROOT, only_codes, skip_codes)
    else:
        prefix_map = manual_cfg.get("hostname_prefix") or {}
        if not prefix_map:
            print("  WARN: single-CID tenant and no hostname_prefix in"
                  f" {MAPPING_FILE.name}; per-client buckets are empty.")
        overall, unmatched_hosts = pull_single_cid(
            prefix_map, window_start_iso, window_end_iso,
            CLIENTS_ROOT, only_codes, skip_codes,
        )
        if unmatched_hosts:
            (pipeline_run_dir / "unmatched_hosts.json").write_text(
                json.dumps(unmatched_hosts, indent=2, default=str), encoding="utf-8")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_date": run_date,
        "window_start": window_start_iso,
        "window_end": window_end_iso,
        "lookback_hours": args.hours,
        "tenancy": "multi" if children else "single",
        "child_cids_total": len(children),
        "child_cids_mapped": len(mapping),
        "child_cids_unmapped": len(unmapped),
        "child_cids_ignored": len(ignore),
        "clients_pulled": len(overall),
        "skipped_codes": sorted(skip_codes),
        "totals": {
            "hosts": sum(r["hosts_total"] for r in overall),
            "hosts_seen_in_window": sum(r["hosts_seen_in_window"] for r in overall),
            "alerts_in_window": sum(r["alerts_in_window"] for r in overall),
            "detects_in_window": sum(r["detects_in_window"] for r in overall),
            "incidents_in_window": sum(r["incidents_in_window"] for r in overall),
            "unmatched_hosts_single_cid": len(unmatched_hosts),
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
    print(f"  tenancy:         {log['tenancy']}")
    print(f"  child CIDs:      {len(children)} (mapped {len(mapping)}, unmapped {len(unmapped)})")
    print(f"  clients pulled:  {len(overall)}")
    print(f"  total hosts:     {log['totals']['hosts']:,}")
    print(f"    seen in 24h:   {log['totals']['hosts_seen_in_window']:,}")
    print(f"  alerts 24h:      {log['totals']['alerts_in_window']:,}")
    print(f"  detects 24h:     {log['totals']['detects_in_window']:,}")
    print(f"  incidents 24h:   {log['totals']['incidents_in_window']:,}")
    if unmatched_hosts:
        print(f"  unmatched hosts: {len(unmatched_hosts)} (see"
              f" {pipeline_run_dir / 'unmatched_hosts.json'})")
    print(f"  log:             {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
