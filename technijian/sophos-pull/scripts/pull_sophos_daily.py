"""Pull last 24h Sophos Central Partner API activity per active client.

Designed to run HOURLY via Windows Scheduled Task. Window is
[run_time - 24h, run_time). With hourly cadence + 24h window, every alert
shows up in 24 consecutive runs — dedup is enforced downstream by
`route_alerts.py` against `state/alert-tickets.json`, so tickets are NOT
created multiple times for the same alert.

Per-client output (under clients/<code>/sophos/YYYY-MM-DD/):
    firewalls.json + firewalls.csv  per-tenant firewall inventory snapshot
                                    (serial, hostname, model, firmware, WAN IPs,
                                    HA, connected, suspended, capabilities)
    events.json                     SIEM events in window (CONNECTIVITY group:
                                    gateway up/down, lost-connection, reconnected)
    alerts.json                     /common/v1/alerts open alerts (5..N items)
    pull_summary.json               counts, errors, mapping_source, window

Account-level output (under technijian/sophos-pull/<YYYY-MM-DD>/):
    whoami.json                     partner identity
    tenants.json                    full tenant list (id, name, region, apiHost)
    mapping.json                    sophos_tenant_id -> LocationCode
    unmapped.json                   tenants with no LocationCode match
    firewalls_all.json              cross-tenant firewall inventory (for the
                                    syslog tenant-map seeder)
    run_log.json                    run summary (also under state/<date>.json)

Read-only by design. The Partner API does NOT surface IPS/IDS event detail at
the partner tier - only firewall management telemetry (gateway up/down,
disconnects). Real IPS/IDS event capture comes from the syslog receiver in
the Technijian DC; see docs/sophos-firewall-pipeline.md and
technijian/sophos-pull/state/sophos-tenant-ipmap.txt for the rsyslog
allowlist that this script's seeder produces.

Usage:
    python pull_sophos_daily.py                       # last 24h
    python pull_sophos_daily.py --hours 48
    python pull_sophos_daily.py --date 2026-04-29
    python pull_sophos_daily.py --only AAVA,BWH
    python pull_sophos_daily.py --skip ORX
    python pull_sophos_daily.py --dry-run
    python pull_sophos_daily.py --map-only            # mapping resolution only
"""
from __future__ import annotations

import argparse
import csv
import json
import re
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
MAPPING_FILE = STATE_DIR / "sophos-tenant-mapping.json"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(CLIENTPORTAL_SCRIPTS))
import sophos_api as sapi  # noqa: E402
import cp_api  # noqa: E402


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------

def compute_window(run_at: datetime, hours: int) -> tuple[str, str]:
    end = run_at.astimezone(timezone.utc).replace(microsecond=0)
    start = end - timedelta(hours=hours)
    return _isoz(start), _isoz(end)


def _isoz(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(dt: datetime) -> int:
    return int(dt.astimezone(timezone.utc).timestamp())


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tenant -> LocationCode mapping
# ---------------------------------------------------------------------------

_NAME_NOISE = re.compile(r"\b(inc|llc|llp|ltd|co|corp|corporation|company|the|of|and|&|holdings|group|services)\b",
                         flags=re.IGNORECASE)
_NAME_PUNCT = re.compile(r"[^a-z0-9]+")


def normalize_name(s: str) -> str:
    if not s:
        return ""
    out = s.lower()
    out = _NAME_NOISE.sub(" ", out)
    out = _NAME_PUNCT.sub("", out)
    return out.strip()


def load_manual_mapping() -> dict[str, Any]:
    if not MAPPING_FILE.exists():
        return {"manual": {}, "ignore": []}
    try:
        return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  WARN: could not parse {MAPPING_FILE.name}: {e}")
        return {"manual": {}, "ignore": []}


def resolve_mapping(tenants: list[dict], cp_clients: list[dict],
                    manual: dict[str, str],
                    ignore: set[str] | None = None) -> tuple[dict[str, dict], list[dict]]:
    """Match Sophos tenants to LocationCode. Returns (mapping, unmapped)."""
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

    for t in tenants:
        tid = str(t.get("id") or "")
        tname = t.get("name") or ""
        if not tid or tid in ignore:
            continue

        # 1) manual override
        target_code = (manual.get(tid) or "").upper()
        if target_code and target_code in cp_by_code:
            c = cp_by_code[target_code]
            mapping[tid] = _map_entry(t, target_code, c, "manual")
            continue
        if target_code:
            unmapped.append({"sophos_tenant_id": tid, "sophos_tenant_name": tname,
                             "reason": f"manual override -> {target_code} not in active client list"})
            continue

        # 2) exact normalized-name match
        n = normalize_name(tname)
        c = cp_by_norm.get(n) if n else None
        if c:
            mapping[tid] = _map_entry(t, (c.get("LocationCode") or "").upper(), c, "name_exact")
            continue

        # 3) bare-code (tenant name IS a LocationCode like "B2I")
        bare = tname.strip().upper()
        if bare in cp_by_code:
            c = cp_by_code[bare]
            mapping[tid] = _map_entry(t, bare, c, "bare_code")
            continue

        unmapped.append({
            "sophos_tenant_id": tid,
            "sophos_tenant_name": tname,
            "reason": "no name match - add to sophos-tenant-mapping.json manual block",
        })

    return mapping, unmapped


def _map_entry(t: dict, code: str, c: dict, source: str) -> dict:
    return {
        "sophos_tenant_id": t["id"],
        "sophos_tenant_name": t.get("name"),
        "dataRegion": t.get("dataRegion"),
        "apiHost": t.get("apiHost"),
        "LocationCode": code,
        "Location_Name": c.get("Location_Name"),
        "DirID": c.get("DirID"),
        "match_source": source,
    }


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

FIREWALL_PREFERRED_COLS = [
    "serialNumber", "hostname", "name", "model", "firmwareVersion",
    "externalIpv4Address", "externalIpv4Addresses",
    "connected", "suspended", "managingStatus", "reportingStatus",
    "id", "tenantId", "stateChangedAt", "createdAt", "updatedAt",
]


def write_csv(path: Path, rows: list[dict], preferred_cols: list[str] | None = None) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    cols: list[str] = []
    seen: set[str] = set()
    for k in (preferred_cols or []):
        if k not in seen:
            seen.add(k); cols.append(k)
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k); cols.append(k)
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


def flatten_firewall(fw: dict) -> dict:
    """Flatten a firewall record so the CSV has scalar columns."""
    flat = dict(fw)
    status = fw.get("status") or {}
    flat["connected"] = status.get("connected")
    flat["suspended"] = status.get("suspended")
    flat["managingStatus"] = status.get("managingStatus")
    flat["reportingStatus"] = status.get("reportingStatus")
    flat["tenantId"] = (fw.get("tenant") or {}).get("id")
    ips = fw.get("externalIpv4Addresses") or []
    flat["externalIpv4Address"] = ips[0] if ips else ""
    return flat


# ---------------------------------------------------------------------------
# Per-tenant pull
# ---------------------------------------------------------------------------

def pull_tenant(mapping_entry: dict,
                window_start_iso: str,
                window_end_iso: str,
                window_start_epoch: int,
                out_root: Path,
                dry_run: bool = False) -> dict:
    code = mapping_entry["LocationCode"]
    out_dir = out_root / code.lower() / "sophos" / window_end_iso[:10]
    tenant = {"id": mapping_entry["sophos_tenant_id"], "apiHost": mapping_entry["apiHost"]}

    summary: dict = {
        "sophos_tenant_id": mapping_entry["sophos_tenant_id"],
        "sophos_tenant_name": mapping_entry["sophos_tenant_name"],
        "LocationCode": code,
        "Location_Name": mapping_entry.get("Location_Name"),
        "DirID": mapping_entry.get("DirID"),
        "match_source": mapping_entry.get("match_source"),
        "dataRegion": mapping_entry.get("dataRegion"),
        "window_start": window_start_iso,
        "window_end": window_end_iso,
        "firewalls_total": 0,
        "firewalls_connected": 0,
        "firewalls_suspended": 0,
        "firewalls_by_firmware_major": {},
        "events_total": 0,
        "events_by_group": {},
        "events_by_type": {},
        "events_by_severity": {},
        "events_by_serial": {},
        "alerts_total": 0,
        "alerts_open": 0,
        "alerts_by_severity": {},
        "alerts_by_product": {},
        "errors": [],
        "dry_run": dry_run,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if dry_run:
        return summary

    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Firewall inventory
    try:
        firewalls = sapi.list_firewalls(tenant)
    except Exception as e:
        summary["errors"].append({"step": "firewalls", "err": str(e), "tb": traceback.format_exc()})
        firewalls = []
    flat = [flatten_firewall(fw) for fw in firewalls]
    (out_dir / "firewalls.json").write_text(
        json.dumps(firewalls, indent=2, default=str), encoding="utf-8")
    write_csv(out_dir / "firewalls.csv", flat, FIREWALL_PREFERRED_COLS)
    summary["firewalls_total"] = len(firewalls)
    for f in flat:
        if f.get("connected"):
            summary["firewalls_connected"] += 1
        if f.get("suspended"):
            summary["firewalls_suspended"] += 1
        major = (f.get("firmwareVersion") or "").split("_")[-1].split(".")
        major_key = ".".join(major[:2]) if len(major) >= 2 else "unknown"
        summary["firewalls_by_firmware_major"][major_key] = (
            summary["firewalls_by_firmware_major"].get(major_key, 0) + 1)

    # 2. SIEM events in window
    events: list[dict] = []
    try:
        cursor = None
        while True:
            params: dict[str, str] = {"from_date": str(window_start_epoch), "limit": "1000"}
            if cursor:
                params["cursor"] = cursor
            r = sapi.tenant_get(tenant, "/siem/v1/events", params)
            if r["status"] != 200 or not isinstance(r["body"], dict):
                summary["errors"].append({"step": "events", "status": r["status"], "body": str(r["body"])[:200]})
                break
            events.extend(r["body"].get("items", []))
            if not r["body"].get("has_more"):
                break
            cursor = r["body"].get("next_cursor")
            if not cursor:
                break
    except Exception as e:
        summary["errors"].append({"step": "events", "err": str(e), "tb": traceback.format_exc()})

    (out_dir / "events.json").write_text(
        json.dumps(events, indent=2, default=str), encoding="utf-8")
    summary["events_total"] = len(events)
    for e in events:
        g = e.get("group", "?")
        t = e.get("type", "?")
        sev = e.get("severity", "?")
        loc = e.get("location") or "?"
        summary["events_by_group"][g] = summary["events_by_group"].get(g, 0) + 1
        summary["events_by_type"][t] = summary["events_by_type"].get(t, 0) + 1
        summary["events_by_severity"][sev] = summary["events_by_severity"].get(sev, 0) + 1
        summary["events_by_serial"][loc] = summary["events_by_serial"].get(loc, 0) + 1

    # 3. Common alerts (open across history)
    alerts: list[dict] = []
    try:
        page = 1
        while True:
            r = sapi.tenant_get(tenant, "/common/v1/alerts", {"pageSize": "100", "page": str(page)})
            if r["status"] != 200 or not isinstance(r["body"], dict):
                summary["errors"].append({"step": "alerts", "status": r["status"], "body": str(r["body"])[:200]})
                break
            items = r["body"].get("items", [])
            alerts.extend(items)
            pages = r["body"].get("pages") or {}
            total_pages = int(pages.get("total") or pages.get("totalPages") or 1)
            if page >= total_pages or not items:
                break
            page += 1
    except Exception as e:
        summary["errors"].append({"step": "alerts", "err": str(e), "tb": traceback.format_exc()})

    (out_dir / "alerts.json").write_text(
        json.dumps(alerts, indent=2, default=str), encoding="utf-8")
    summary["alerts_total"] = len(alerts)
    summary["alerts_open"] = sum(1 for a in alerts if a.get("status") == "open")
    for a in alerts:
        sev = a.get("severity", "?")
        prod = a.get("product", "?")
        summary["alerts_by_severity"][sev] = summary["alerts_by_severity"].get(sev, 0) + 1
        summary["alerts_by_product"][prod] = summary["alerts_by_product"].get(prod, 0) + 1

    (out_dir / "pull_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Pull last 24h Sophos Central Partner API activity per client.")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--date", help="Override end-of-window date (YYYY-MM-DD, anchors window end at 13:00 UTC = 05:00 PT)")
    ap.add_argument("--only", help="comma-separated LocationCodes")
    ap.add_argument("--skip", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--map-only", action="store_true")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    run_at = datetime.now(timezone.utc)
    if args.date:
        d = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=13)
        run_at = d
    window_start_iso, window_end_iso = compute_window(run_at, args.hours)
    window_start_epoch = _epoch(_parse_dt(window_start_iso) or datetime.now(timezone.utc))
    run_date = window_end_iso[:10]

    skip_codes: set[str] = set()
    for s in args.skip:
        for piece in s.split(","):
            piece = piece.strip()
            if piece:
                skip_codes.add(piece.upper())
    only_codes = None
    if args.only:
        only_codes = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    print(f"[{datetime.now():%H:%M:%S}] Sophos Central Partner daily pull")
    print(f"  window: {window_start_iso} -> {window_end_iso} ({args.hours}h)")
    print(f"  run_date dir tag: {run_date}")

    print(f"[{datetime.now():%H:%M:%S}] fetching active CP clients...")
    cp_clients = cp_api.get_active_clients()
    print(f"  got {len(cp_clients)} active CP clients")

    print(f"[{datetime.now():%H:%M:%S}] fetching Sophos partner identity + tenants...")
    me = sapi.whoami()
    tenants = sapi.list_tenants()
    print(f"  partner_id={me['id']}  tenants={len(tenants)}")

    manual = load_manual_mapping()
    ignore = {str(x) for x in (manual.get("ignore") or [])}
    mapping, unmapped = resolve_mapping(tenants, cp_clients,
                                          manual.get("manual") or {}, ignore=ignore)

    print(f"  mapped: {len(mapping)}    unmapped: {len(unmapped)}    ignored: {len(ignore)}")
    if args.map_only:
        print()
        for tid, info in sorted(mapping.items(), key=lambda kv: kv[1]["LocationCode"]):
            print(f"  MAP  {info['LocationCode']:<8s} <- {info['sophos_tenant_name']:<45s} ({info['match_source']})")
        for u in unmapped:
            print(f"  ----  {u['sophos_tenant_id']:<40s} {u['sophos_tenant_name']:<45s} {u['reason']}")
        for tid in ignore:
            print(f"  IGN   {tid}")
        return 0

    if args.dry_run:
        print("  --dry-run set, skipping API pulls per tenant")
        return 0

    pipeline_run_dir = PIPELINE_ROOT / run_date
    pipeline_run_dir.mkdir(parents=True, exist_ok=True)

    (pipeline_run_dir / "whoami.json").write_text(
        json.dumps(me, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "tenants.json").write_text(
        json.dumps(tenants, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "mapping.json").write_text(
        json.dumps(mapping, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "unmapped.json").write_text(
        json.dumps(unmapped, indent=2, default=str), encoding="utf-8")

    overall: list[dict] = []
    cross_firewalls: list[dict] = []
    items = list(mapping.items())
    for i, (tid, info) in enumerate(items, 1):
        code = info["LocationCode"]
        if code in skip_codes:
            print(f"  [{i}/{len(items)}] skip {code}")
            continue
        if only_codes is not None and code not in only_codes:
            continue
        s = pull_tenant(info, window_start_iso, window_end_iso,
                        window_start_epoch, CLIENTS_ROOT, dry_run=False)
        flag = "  ERR" if s["errors"] else ""
        print(f"  [{i}/{len(items)}] {code:<8s} fws={s['firewalls_total']:>2d} "
              f"connected={s['firewalls_connected']:>2d} ev24h={s['events_total']:>4d} "
              f"alerts={s['alerts_total']:>3d}{flag}")
        overall.append(s)
        # Reload firewall records for the cross-tenant view
        try:
            tenant = {"id": info["sophos_tenant_id"], "apiHost": info["apiHost"]}
            for fw in sapi.list_firewalls(tenant):
                fw_view = flatten_firewall(fw)
                fw_view["LocationCode"] = code
                fw_view["sophos_tenant_id"] = info["sophos_tenant_id"]
                fw_view["sophos_tenant_name"] = info["sophos_tenant_name"]
                cross_firewalls.append(fw_view)
        except Exception:
            pass

    (pipeline_run_dir / "firewalls_all.json").write_text(
        json.dumps(cross_firewalls, indent=2, default=str), encoding="utf-8")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_date": run_date,
        "window_start": window_start_iso,
        "window_end": window_end_iso,
        "lookback_hours": args.hours,
        "partner_id": me["id"],
        "tenants_total": len(tenants),
        "tenants_mapped": len(mapping),
        "tenants_unmapped": len(unmapped),
        "tenants_ignored": len(ignore),
        "clients_pulled": len(overall),
        "skipped_codes": sorted(skip_codes),
        "totals": {
            "firewalls": sum(r["firewalls_total"] for r in overall),
            "firewalls_connected": sum(r["firewalls_connected"] for r in overall),
            "firewalls_suspended": sum(r["firewalls_suspended"] for r in overall),
            "events_in_window": sum(r["events_total"] for r in overall),
            "alerts_total": sum(r["alerts_total"] for r in overall),
            "alerts_open": sum(r["alerts_open"] for r in overall),
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
    print(f"  mapped clients:    {len(mapping)}")
    print(f"  pulled clients:    {len(overall)}")
    print(f"  unmapped tenants:  {len(unmapped)} (see {pipeline_run_dir / 'unmapped.json'})")
    print(f"  total firewalls:   {log['totals']['firewalls']}")
    print(f"    connected:       {log['totals']['firewalls_connected']}")
    print(f"    suspended:       {log['totals']['firewalls_suspended']}")
    print(f"  events 24h:        {log['totals']['events_in_window']}")
    print(f"  alerts open:       {log['totals']['alerts_open']}")
    print(f"  log:               {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
