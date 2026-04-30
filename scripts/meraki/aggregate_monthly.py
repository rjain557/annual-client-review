"""
Aggregate daily Meraki pull files into per-org per-month summary JSON.

Reads (from clients/<code>/meraki/):
  security_events/<YYYY-MM-DD>.json
  network_events/<network_slug>/<YYYY-MM-DD>.json
  org_meta.json, networks.json, devices.json
  networks/<network_slug>/*.json

Writes:
  clients/<code>/meraki/monthly/<YYYY-MM>.json     (structured summary)
  clients/_meraki_logs/monthly_index.json          (cross-client index)

Usage:
  python aggregate_monthly.py                              # all clients, all months
  python aggregate_monthly.py --month 2026-03              # one month, all clients
  python aggregate_monthly.py --only vaf,bwh               # subset
  python aggregate_monthly.py --from 2026-01 --to 2026-03  # range
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CLIENTS_ROOT = Path(__file__).resolve().parents[2] / "clients"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--month", help="Single month YYYY-MM")
    p.add_argument("--from", dest="from_month", help="Start month YYYY-MM (inclusive)")
    p.add_argument("--to", dest="to_month", help="End month YYYY-MM (inclusive)")
    p.add_argument("--only", help="Comma-separated client codes (lowercase)")
    p.add_argument("--skip", help="Comma-separated client codes to skip")
    p.add_argument("--root", default=str(CLIENTS_ROOT), help="clients/ root")
    return p.parse_args()


def month_of(date_str: str) -> str:
    return date_str[:7]


def discover_meraki_clients(clients_root: Path) -> list[Path]:
    """Find every clients/<code>/meraki/ directory."""
    out: list[Path] = []
    if not clients_root.exists():
        return out
    for client_dir in sorted(clients_root.iterdir()):
        if not client_dir.is_dir() or client_dir.name.startswith("_"):
            continue
        meraki_dir = client_dir / "meraki"
        if meraki_dir.exists() and meraki_dir.is_dir():
            out.append(meraki_dir)
    return out


def discover_months(meraki_dir: Path) -> set[str]:
    months: set[str] = set()
    sec_dir = meraki_dir / "security_events"
    if sec_dir.exists():
        for f in sec_dir.glob("*.json"):
            months.add(month_of(f.stem))
    net_dir = meraki_dir / "network_events"
    if net_dir.exists():
        for n in net_dir.iterdir():
            if n.is_dir():
                for f in n.glob("*.json"):
                    months.add(month_of(f.stem))
    return months


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def filter_months(all_months: Iterable[str], target: str | None,
                  fr: str | None, to: str | None) -> list[str]:
    months = sorted(all_months)
    if target:
        return [m for m in months if m == target]
    if fr or to:
        out = []
        for m in months:
            if fr and m < fr:
                continue
            if to and m > to:
                continue
            out.append(m)
        return out
    return months


def aggregate_security(meraki_dir: Path, month: str) -> dict:
    sec_dir = meraki_dir / "security_events"
    empty = {"total": 0, "days_with_events": 0, "daily_counts": [],
             "by_signature_top": [], "by_priority": {}, "by_blocked": {},
             "top_sources": [], "top_destinations": [],
             "top_internal_clients": [], "sample_events": []}
    if not sec_dir.exists():
        return empty
    files = sorted([f for f in sec_dir.glob(f"{month}-*.json")])
    if not files:
        return empty

    daily_counts: list[dict] = []
    by_signature: Counter = Counter()
    by_priority: Counter = Counter()
    by_blocked: Counter = Counter()
    top_src: Counter = Counter()
    top_dst: Counter = Counter()
    top_clients: Counter = Counter()
    sample_events: list[dict] = []
    total = 0

    for f in files:
        d = load_json(f) or {}
        events = d.get("events") or []
        daily_counts.append({"date": f.stem, "count": len(events)})
        total += len(events)
        for ev in events:
            sig = ev.get("signature") or ev.get("ruleId") or "(unknown)"
            by_signature[sig] += 1
            pri = ev.get("priority") or ev.get("severity") or "(unknown)"
            by_priority[str(pri)] += 1
            blocked = ev.get("blocked")
            by_blocked["blocked" if blocked else "alerted"] += 1
            src = ev.get("srcIp") or ev.get("src") or ""
            dst = ev.get("destIp") or ev.get("dest") or ev.get("dst") or ""
            cli = ev.get("clientName") or ev.get("clientMac") or ""
            if src:
                top_src[src] += 1
            if dst:
                top_dst[dst] += 1
            if cli:
                top_clients[cli] += 1
            if len(sample_events) < 25:
                sample_events.append(ev)

    return {
        "total": total,
        "days_with_events": sum(1 for d in daily_counts if d["count"] > 0),
        "daily_counts": daily_counts,
        "by_signature_top": by_signature.most_common(15),
        "by_priority": dict(by_priority),
        "by_blocked": dict(by_blocked),
        "top_sources": top_src.most_common(15),
        "top_destinations": top_dst.most_common(15),
        "top_internal_clients": top_clients.most_common(15),
        "sample_events": sample_events,
    }


def aggregate_network(meraki_dir: Path, month: str) -> dict:
    net_dir = meraki_dir / "network_events"
    empty = {"total": 0, "networks_with_events": 0, "by_network": {},
             "by_type_top": [], "by_category": {}, "daily_counts": []}
    if not net_dir.exists():
        return empty

    by_network: dict[str, dict] = {}
    by_type: Counter = Counter()
    by_category: Counter = Counter()
    daily_counts: Counter = Counter()
    total = 0
    networks_seen: set[str] = set()

    for n in net_dir.iterdir():
        if not n.is_dir():
            continue
        files = sorted(n.glob(f"{month}-*.json"))
        if not files:
            continue
        net_total = 0
        net_types: Counter = Counter()
        net_daily: list[dict] = []
        net_name = None
        for f in files:
            d = load_json(f) or {}
            events = d.get("events") or []
            net_name = d.get("network", {}).get("name") or n.name
            net_total += len(events)
            net_daily.append({"date": f.stem, "count": len(events)})
            daily_counts[f.stem] += len(events)
            for ev in events:
                t = ev.get("type") or "(unknown)"
                by_type[t] += 1
                net_types[t] += 1
                cat = ev.get("category") or "(unknown)"
                by_category[cat] += 1
        if net_total:
            networks_seen.add(n.name)
            by_network[n.name] = {
                "name": net_name,
                "total": net_total,
                "by_type_top": net_types.most_common(10),
                "daily_counts": net_daily,
            }
            total += net_total

    return {
        "total": total,
        "networks_with_events": len(networks_seen),
        "by_network": by_network,
        "by_type_top": by_type.most_common(20),
        "by_category": dict(by_category),
        "daily_counts": [{"date": d, "count": c} for d, c in sorted(daily_counts.items())],
    }


def aggregate_configuration(meraki_dir: Path) -> dict:
    org_meta = load_json(meraki_dir / "org_meta.json") or {}
    networks = load_json(meraki_dir / "networks.json") or []
    devices = load_json(meraki_dir / "devices.json") or []
    snap = load_json(meraki_dir / "config_snapshot_at.json") or {}

    summary = {
        "org": org_meta.get("name"),
        "snapshot_at": snap.get("snapshot_at"),
        "network_count": len(networks),
        "device_count": len(devices),
        "device_models": dict(Counter(d.get("model") for d in devices)),
        "device_product_types": dict(Counter(d.get("productType") for d in devices)),
        "networks": [],
    }

    nets_dir = meraki_dir / "networks"
    if nets_dir.exists():
        for n in sorted(nets_dir.iterdir()):
            if not n.is_dir():
                continue
            net_meta = load_json(n / "meta.json") or {}
            net_summary = {
                "slug": n.name,
                "name": net_meta.get("name"),
                "productTypes": net_meta.get("productTypes"),
                "timeZone": net_meta.get("timeZone"),
            }
            for fname, key in [
                ("firewall_l3.json", "firewall_l3_rule_count"),
                ("firewall_l7.json", "firewall_l7_rule_count"),
                ("firewall_inbound.json", "firewall_inbound_rule_count"),
                ("firewall_port_forwarding.json", "port_forward_count"),
                ("firewall_1to1_nat.json", "one_to_one_nat_count"),
            ]:
                d = load_json(n / fname) or {}
                net_summary[key] = len(d.get("rules", []))
            ids = load_json(n / "security_intrusion.json")
            if ids:
                net_summary["intrusion"] = {
                    "mode": ids.get("mode"),
                    "rulesetGenerated": ids.get("idsRulesets") or ids.get("idsRulesEnabled"),
                    "protectedNetworks": ids.get("protectedNetworks"),
                }
            amp = load_json(n / "security_malware.json")
            if amp:
                net_summary["malware"] = {"mode": amp.get("mode")}
            cf = load_json(n / "content_filtering.json") or {}
            net_summary["content_filtering"] = {
                "blocked_categories_count": len(cf.get("blockedUrlCategories") or []),
                "blocked_url_patterns_count": len(cf.get("blockedUrlPatterns") or []),
                "allowed_url_patterns_count": len(cf.get("allowedUrlPatterns") or []),
            }
            vlans = load_json(n / "vlans.json")
            net_summary["vlan_count"] = len(vlans) if isinstance(vlans, list) else 0
            ssids = load_json(n / "wireless_ssids.json") or []
            if isinstance(ssids, list):
                net_summary["ssid_count"] = sum(1 for s in ssids if s.get("enabled"))
            vpn = load_json(n / "vpn_s2s.json") or {}
            net_summary["s2s_vpn_mode"] = vpn.get("mode")
            net_summary["s2s_vpn_peer_count"] = len(vpn.get("hubs") or [])
            sysl = load_json(n / "syslog_servers.json") or {}
            net_summary["syslog_destination_count"] = len(sysl.get("servers") or [])
            summary["networks"].append(net_summary)

    return summary


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    only = {s.strip().lower() for s in (args.only or "").split(",") if s.strip()}
    skip = {s.strip().lower() for s in (args.skip or "").split(",") if s.strip()}

    meraki_dirs = [d for d in discover_meraki_clients(root)
                   if (not only or d.parent.name in only) and d.parent.name not in skip]
    print(f"Aggregating {len(meraki_dirs)} client(s) from {root}")

    index: list[dict] = []
    total_files = 0
    for meraki_dir in meraki_dirs:
        client_code = meraki_dir.parent.name
        all_months = discover_months(meraki_dir)
        months = filter_months(all_months, args.month, args.from_month, args.to_month)
        if not months:
            print(f"  [{client_code}] no months found")
            continue
        config_summary = aggregate_configuration(meraki_dir)

        out_dir = meraki_dir / "monthly"
        out_dir.mkdir(parents=True, exist_ok=True)
        for m in months:
            sec = aggregate_security(meraki_dir, m)
            net = aggregate_network(meraki_dir, m)
            payload = {
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "client_code": client_code,
                "month": m,
                "configuration": config_summary,
                "security_events": sec,
                "network_events": net,
            }
            out = out_dir / f"{m}.json"
            out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            total_files += 1
            index.append({"client_code": client_code, "month": m,
                          "security_events_total": sec["total"],
                          "network_events_total": net["total"]})
            print(f"  [{client_code}] {m}: sec={sec['total']:>6}  net={net['total']:>6}")

    log_dir = root / "_meraki_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "monthly_index.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "monthly_files": index,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {total_files} monthly summaries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
