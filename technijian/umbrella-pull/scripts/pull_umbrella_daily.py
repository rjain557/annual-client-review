"""Pull the last 24h of Cisco Umbrella data per active client.

Designed to run nightly via Windows Scheduled Task on the production
workstation. The window is [run_time - 24h, run_time) so consecutive runs do
not double-count.

Different from the Huntress pull: Cisco Umbrella for Technijian is a SINGLE-
TENANT deployment (one org id, no MSSP child organizations). Per-client
attribution comes from the **hostname / identity-label prefix** of the
roaming-computer agents. The mapping resolves prefixes against active Client
Portal LocationCodes; unmatched agents land in unmapped.json.

For every prefix that maps to a Client Portal LocationCode the script writes:

    clients/<code>/umbrella/YYYY-MM-DD/
        roaming_computers.json + csv      agents whose name starts with the
                                          mapped prefix - drives "which
                                          computers have Umbrella installed"
                                          reporting
        internal_networks.json            internal-network records with a
                                          matching name prefix (often empty)
        sites.json                        site records with a matching name
                                          prefix (often empty)
        activity_summary.json             24h DNS activity rolled up by
                                          verdict + threat for this client's
                                          identities (sampled, see note)
        top_destinations.json             top destinations by this client's
                                          identities in the 24h window
        blocked_threats.json              blocked DNS queries with threats[]
                                          in the 24h window
        pull_summary.json                 counts, errors, mapping_source,
                                          window, run timestamp

Account-level outputs land at technijian/umbrella-pull/<YYYY-MM-DD>/:
    account.json                          parent org id + active users
    sites.json                            site list
    networks.json                         egress networks (often empty)
    internal_networks.json                internal subnets
    roaming_computers.json                full agent inventory
    network_devices.json                  network appliance integrations
    destination_lists.json                DNS allow/block lists
    activity_24h_sample.json              full 24h activity window sample
                                          (capped at 5000 records)
    mapping.json                          prefix -> LocationCode resolution
    unmapped.json                         hostname prefixes with no match
    run_log.json                          run summary

Note on activity sampling:
    /reports/v2/activity is paged but very heavy. The pull caps the 24h
    sample at 5000 records to keep the script fast and avoid offset overflow.
    For a true full-month aggregation, write a downstream consumer that walks
    activity in 1-hour chunks instead of relying on the daily snapshot.

Usage:
    python pull_umbrella_daily.py                       # last 24h, all clients
    python pull_umbrella_daily.py --hours 48            # custom lookback
    python pull_umbrella_daily.py --date 2026-04-29     # explicit run date
    python pull_umbrella_daily.py --only VAF,BWH        # subset of LocationCodes
    python pull_umbrella_daily.py --skip ORX
    python pull_umbrella_daily.py --dry-run             # plan only, no API calls
    python pull_umbrella_daily.py --map-only            # print prefix mapping and exit
    python pull_umbrella_daily.py --no-activity         # skip activity pull (faster)
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
MAPPING_FILE = STATE_DIR / "umbrella-prefix-mapping.json"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(CLIENTPORTAL_SCRIPTS))
import umbrella_api as uapi  # noqa: E402
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


# ---------------------------------------------------------------------------
# Hostname-prefix -> LocationCode mapping
# ---------------------------------------------------------------------------

# Common splitters between client prefix and the rest of the hostname.
_HOST_SPLITTERS = re.compile(r"[-_.]")


def derive_prefix(hostname: str) -> str:
    """Pull the leading client prefix off a hostname.

    Examples:
        "VAF-DC-FS-02"        -> "VAF"
        "BWH_FRONTDESK-01"   -> "BWH"
        "AAVA01"              -> "AAVA01"  (no separator -> whole token)
        "DESKTOP-AB12CD"      -> "DESKTOP"
    """
    if not hostname:
        return ""
    h = hostname.strip()
    # Split on first -, _, or .
    parts = _HOST_SPLITTERS.split(h, maxsplit=1)
    return (parts[0] or "").upper()


def load_manual_mapping() -> dict[str, Any]:
    """umbrella-prefix-mapping.json shape:
        {
          "manual": {"<HOSTNAME_PREFIX>": "<LocationCode>"},
          "ignore": ["<HOSTNAME_PREFIX>"]   # prefixes to never produce per-client output for
        }
    """
    if not MAPPING_FILE.exists():
        return {"manual": {}, "ignore": []}
    try:
        return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  WARN: could not parse {MAPPING_FILE.name}: {e}")
        return {"manual": {}, "ignore": []}


def resolve_prefix_mapping(roaming: list[dict],
                           cp_clients: list[dict],
                           manual: dict[str, str]
                           ) -> tuple[dict[str, dict], list[dict]]:
    """Group roaming-computer hostname prefixes -> LocationCode.

    Returns (mapping, unmapped) where mapping is keyed by prefix (upper-case).
    """
    cp_codes = {(c.get("LocationCode") or "").upper(): c
                for c in cp_clients
                if c.get("LocationCode")}

    # Bucket roaming computers by hostname prefix
    by_prefix: dict[str, list[dict]] = {}
    for r in roaming:
        p = derive_prefix(r.get("name") or "")
        if not p:
            continue
        by_prefix.setdefault(p, []).append(r)

    mapping: dict[str, dict] = {}
    unmapped: list[dict] = []

    for prefix, agents in sorted(by_prefix.items()):
        # 1) explicit override wins
        target_code = (manual.get(prefix) or "").upper()
        if target_code and target_code in cp_codes:
            cp = cp_codes[target_code]
            mapping[prefix] = {
                "prefix": prefix,
                "LocationCode": target_code,
                "Location_Name": cp.get("Location_Name"),
                "DirID": cp.get("DirID"),
                "agent_count": len(agents),
                "match_source": "manual",
            }
            continue
        if target_code:
            unmapped.append({
                "prefix": prefix,
                "agent_count": len(agents),
                "reason": f"manual override -> {target_code} not in active client list",
            })
            continue

        # 2) prefix == LocationCode itself
        if prefix in cp_codes:
            cp = cp_codes[prefix]
            mapping[prefix] = {
                "prefix": prefix,
                "LocationCode": prefix,
                "Location_Name": cp.get("Location_Name"),
                "DirID": cp.get("DirID"),
                "agent_count": len(agents),
                "match_source": "prefix_eq_code",
            }
            continue

        unmapped.append({
            "prefix": prefix,
            "agent_count": len(agents),
            "sample_hostnames": [a.get("name") for a in agents[:3]],
            "reason": "no LocationCode match - add to umbrella-prefix-mapping.json manual block",
        })

    return mapping, unmapped


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

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


ROAMING_PREFERRED_COLS = [
    "originId", "deviceId", "name", "type", "status", "lastSyncStatus",
    "lastSync", "version", "osVersion", "osVersionName", "appliedBundle",
    "hasIpBlocking", "swgStatus", "anyconnectDeviceId",
]


# ---------------------------------------------------------------------------
# Per-client write
# ---------------------------------------------------------------------------

def _identity_in_window(rec: dict, start_ms: int, end_ms: int) -> bool:
    ts = rec.get("timestamp")
    if not isinstance(ts, (int, float)):
        return False
    return start_ms <= int(ts) < end_ms


def write_client_dir(prefix: str,
                     entry: dict,
                     all_roaming: list[dict],
                     all_internal_networks: list[dict],
                     all_sites: list[dict],
                     activity: list[dict],
                     window_start_ms: int,
                     window_end_ms: int,
                     out_root: Path,
                     mode: str = "daily",
                     inventory_snapshot_at: str | None = None) -> dict:
    """Write per-client snapshot. mode='daily' for nightly run; mode='backfill'
    when called from backfill_umbrella.py - the snapshot fields (roaming, sites,
    networks, destination_lists) reflect the *current* state of the Umbrella
    org, not the historical state on the per-day folder's date. The
    `inventory_snapshot_at` field timestamps when the inventory was captured."""
    code = entry["LocationCode"]
    out_dir = out_root / code.lower() / "umbrella" / datetime.fromtimestamp(
        window_end_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Per-client roaming-computer subset
    agents = [r for r in all_roaming
              if (r.get("name") or "").upper().split("-", 1)[0].split("_", 1)[0].split(".", 1)[0]
              == prefix]
    (out_dir / "roaming_computers.json").write_text(
        json.dumps(agents, indent=2, default=str), encoding="utf-8")
    write_csv(out_dir / "roaming_computers.csv", agents, ROAMING_PREFERRED_COLS)

    # 2) Internal networks / sites whose name starts with the prefix
    nets = [n for n in all_internal_networks
            if (n.get("name") or "").upper().startswith(prefix)]
    sites = [s for s in all_sites
             if (s.get("name") or "").upper().startswith(prefix)]
    (out_dir / "internal_networks.json").write_text(
        json.dumps(nets, indent=2, default=str), encoding="utf-8")
    (out_dir / "sites.json").write_text(
        json.dumps(sites, indent=2, default=str), encoding="utf-8")

    # 3) Activity rollup for this client's identities
    agent_ids = {str(a.get("originId")) for a in agents if a.get("originId") is not None}
    agent_names = {(a.get("name") or "") for a in agents}

    in_window: list[dict] = []
    for r in activity:
        if not _identity_in_window(r, window_start_ms, window_end_ms):
            continue
        idents = r.get("identities") or []
        if any(str(i.get("id")) in agent_ids for i in idents):
            in_window.append(r)
            continue
        if any(i.get("label") in agent_names for i in idents):
            in_window.append(r)

    verdicts: dict[str, int] = {}
    types: dict[str, int] = {}
    domains: dict[str, int] = {}
    blocked_threats: list[dict] = []
    for r in in_window:
        v = r.get("verdict") or "unknown"
        verdicts[v] = verdicts.get(v, 0) + 1
        t = r.get("type") or "unknown"
        types[t] = types.get(t, 0) + 1
        d = r.get("domain")
        if d:
            domains[d] = domains.get(d, 0) + 1
        if v == "blocked":
            tlist = r.get("threats") or []
            if tlist:
                blocked_threats.append({
                    "domain": d,
                    "threats": tlist,
                    "timestamp": r.get("timestamp"),
                    "identity_labels": [i.get("label") for i in (r.get("identities") or [])],
                })

    top_destinations = sorted(domains.items(), key=lambda kv: kv[1], reverse=True)[:50]

    activity_summary = {
        "events_in_window": len(in_window),
        "verdicts": verdicts,
        "types": types,
    }
    (out_dir / "activity_summary.json").write_text(
        json.dumps(activity_summary, indent=2, default=str), encoding="utf-8")
    (out_dir / "top_destinations.json").write_text(
        json.dumps([{"domain": d, "count": c} for d, c in top_destinations],
                   indent=2, default=str), encoding="utf-8")
    (out_dir / "blocked_threats.json").write_text(
        json.dumps(blocked_threats, indent=2, default=str), encoding="utf-8")

    # Status counters for the agent inventory
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
        "mode": mode,
        "inventory_snapshot_at": inventory_snapshot_at,
        "window_start_iso": datetime.fromtimestamp(window_start_ms / 1000,
                                                    tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_end_iso": datetime.fromtimestamp(window_end_ms / 1000,
                                                  tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agents_total": len(agents),
        "agents_status": status_counts,
        "internal_networks": len(nets),
        "sites": len(sites),
        "activity_events_in_window": len(in_window),
        "blocked_threats_in_window": len(blocked_threats),
        "errors": [],
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out_dir / "pull_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Pull last 24h Cisco Umbrella data per client.")
    ap.add_argument("--hours", type=int, default=24,
                    help="Lookback window in hours (default 24)")
    ap.add_argument("--date", help="Override end-of-window date (YYYY-MM-DD, anchored to ~01:00 PT)")
    ap.add_argument("--only", help="comma-separated LocationCodes")
    ap.add_argument("--skip", action="append", default=[],
                    help="LocationCode to skip (repeatable, case-insensitive)")
    ap.add_argument("--dry-run", action="store_true", help="Plan only - no API calls")
    ap.add_argument("--map-only", action="store_true",
                    help="Resolve and print prefix -> LocationCode mapping, then exit")
    ap.add_argument("--no-activity", action="store_true",
                    help="Skip the /reports/v2/activity pull (faster, but no activity_summary)")
    return ap.parse_args()


def _safe(step: str, fn, summary_errors: list[dict]):
    try:
        return fn()
    except Exception as e:
        summary_errors.append({"step": step, "err": str(e),
                                "tb": traceback.format_exc()})
        return None


def main() -> int:
    args = parse_args()
    run_at = datetime.now(timezone.utc)
    if args.date:
        # Anchor window-end to 09:00 UTC of the given date (~01:00 PT)
        d = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=9)
        run_at = d
    window_start_iso, window_end_iso = compute_window(run_at, args.hours)
    window_start_dt = datetime.fromisoformat(window_start_iso.replace("Z", "+00:00"))
    window_end_dt = datetime.fromisoformat(window_end_iso.replace("Z", "+00:00"))
    window_start_ms = int(window_start_dt.timestamp() * 1000)
    window_end_ms = int(window_end_dt.timestamp() * 1000)
    run_date = window_end_iso[:10]

    skip_codes: set[str] = set()
    for s in args.skip:
        for x in s.split(","):
            x = x.strip().upper()
            if x:
                skip_codes.add(x)
    only_codes = None
    if args.only:
        only_codes = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    print(f"[{datetime.now():%H:%M:%S}] Cisco Umbrella daily pull")
    print(f"  window: {window_start_iso} -> {window_end_iso} ({args.hours}h)")
    print(f"  run_date dir tag: {run_date}")

    # 1) CP active clients (for mapping)
    print(f"[{datetime.now():%H:%M:%S}] fetching active CP clients...")
    cp_clients = cp_api.get_active_clients()
    print(f"  got {len(cp_clients)} active CP clients")

    # 2) Umbrella deployment inventory (cheap)
    print(f"[{datetime.now():%H:%M:%S}] fetching Umbrella deployment inventory...")
    org_errors: list[dict] = []
    sites = _safe("sites", uapi.list_sites, org_errors) or []
    networks = _safe("networks", uapi.list_networks, org_errors) or []
    internal_networks = _safe("internal_networks", uapi.list_internal_networks, org_errors) or []
    roaming = _safe("roaming_computers", uapi.list_roaming_computers, org_errors) or []
    network_devices = _safe("network_devices", uapi.list_network_devices, org_errors) or []
    print(f"  sites={len(sites)} networks={len(networks)} internal_networks={len(internal_networks)}"
          f" roaming={len(roaming)} network_devices={len(network_devices)}")

    # 3) Resolve mapping
    manual = load_manual_mapping()
    mapping, unmapped = resolve_prefix_mapping(roaming, cp_clients,
                                                manual.get("manual") or {})
    ignore = {str(x).upper() for x in (manual.get("ignore") or [])}

    # Drop ignored prefixes from mapping AND unmapped
    mapping = {p: e for p, e in mapping.items() if p not in ignore}
    unmapped = [u for u in unmapped if (u.get("prefix") or "").upper() not in ignore]

    print(f"  mapped prefixes: {len(mapping)}    unmapped: {len(unmapped)}    ignored: {len(ignore)}")

    if args.map_only:
        print()
        for p, info in sorted(mapping.items(), key=lambda kv: kv[1]["LocationCode"]):
            print(f"  MAP   {info['LocationCode']:<8s} <- {p:<10s}  agents={info['agent_count']:>3d} ({info['match_source']})")
        for u in unmapped:
            sample = ", ".join(u.get("sample_hostnames") or [])
            print(f"  ----  {u['prefix']:<10s} agents={u['agent_count']:>3d}  {u['reason']}    e.g. {sample}")
        return 0

    if args.dry_run:
        print("  --dry-run set, skipping API pulls per client")
        return 0

    # 4) Account-level outputs
    pipeline_run_dir = PIPELINE_ROOT / run_date
    pipeline_run_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{datetime.now():%H:%M:%S}] fetching account info + policy lists...")
    users = _safe("users", uapi.list_users, org_errors) or []
    destination_lists = _safe("destination_lists", uapi.list_destination_lists, org_errors) or []

    account = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "users_count": len(users),
        "users": users,
    }
    (pipeline_run_dir / "account.json").write_text(
        json.dumps(account, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "sites.json").write_text(
        json.dumps(sites, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "networks.json").write_text(
        json.dumps(networks, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "internal_networks.json").write_text(
        json.dumps(internal_networks, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "roaming_computers.json").write_text(
        json.dumps(roaming, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "network_devices.json").write_text(
        json.dumps(network_devices, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "destination_lists.json").write_text(
        json.dumps(destination_lists, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "mapping.json").write_text(
        json.dumps(mapping, indent=2, default=str), encoding="utf-8")
    (pipeline_run_dir / "unmapped.json").write_text(
        json.dumps(unmapped, indent=2, default=str), encoding="utf-8")

    # 5) Activity (heavy) - one shot for the whole org, then filter per client
    activity: list[dict] = []
    if args.no_activity:
        print(f"[{datetime.now():%H:%M:%S}] activity pull skipped (--no-activity)")
    else:
        print(f"[{datetime.now():%H:%M:%S}] sampling 24h activity (max 5000 records)...")
        try:
            activity = uapi.list_activity(window_start_iso, window_end_iso,
                                           page_limit=200, max_records=5000)
        except Exception as e:
            org_errors.append({"step": "activity", "err": str(e),
                                "tb": traceback.format_exc()})
            print(f"  activity sample failed: {e}")
        print(f"  pulled {len(activity)} activity records (sample)")
    (pipeline_run_dir / "activity_24h_sample.json").write_text(
        json.dumps(activity, indent=2, default=str), encoding="utf-8")

    # 6) Per-client pulls
    overall: list[dict] = []
    items = list(mapping.items())
    for i, (prefix, info) in enumerate(items, 1):
        code = info["LocationCode"]
        if code in skip_codes:
            print(f"  [{i}/{len(items)}] skip {code}")
            continue
        if only_codes is not None and code not in only_codes:
            continue
        s = write_client_dir(prefix, info, roaming, internal_networks, sites,
                              activity, window_start_ms, window_end_ms,
                              CLIENTS_ROOT)
        flag = "  ERR" if s["errors"] else ""
        print(f"  [{i}/{len(items)}] {code:<8s} prefix={prefix:<10s} agents={s['agents_total']:>3d}"
              f" act24h={s['activity_events_in_window']:>4d}"
              f" blk={s['blocked_threats_in_window']:>3d}{flag}")
        overall.append(s)

    # 7) Run log
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_date": run_date,
        "window_start": window_start_iso,
        "window_end": window_end_iso,
        "lookback_hours": args.hours,
        "umbrella_orgs_total": 1,        # single tenant
        "deployment_counts": {
            "sites": len(sites),
            "networks": len(networks),
            "internal_networks": len(internal_networks),
            "roaming_computers": len(roaming),
            "network_devices": len(network_devices),
            "destination_lists": len(destination_lists),
            "users": len(users),
        },
        "prefixes_mapped": len(mapping),
        "prefixes_unmapped": len(unmapped),
        "prefixes_ignored": len(ignore),
        "clients_pulled": len(overall),
        "skipped_codes": sorted(skip_codes),
        "activity_sample_size": len(activity),
        "totals": {
            "agents": sum(r["agents_total"] for r in overall),
            "activity_events_in_window": sum(r["activity_events_in_window"] for r in overall),
            "blocked_threats_in_window": sum(r["blocked_threats_in_window"] for r in overall),
        },
        "org_errors": org_errors,
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
    print(f"  mapped prefixes:  {len(mapping)}")
    print(f"  pulled clients:   {len(overall)}")
    print(f"  unmapped prefixes:{len(unmapped)} (see {pipeline_run_dir / 'unmapped.json'})")
    print(f"  total agents:     {log['totals']['agents']:,}")
    print(f"  activity 24h:     {log['totals']['activity_events_in_window']:,}")
    print(f"  blocked threats:  {log['totals']['blocked_threats_in_window']:,}")
    print(f"  log:              {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
