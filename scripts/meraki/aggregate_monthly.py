"""
Aggregate daily Meraki pull files into per-org per-month summary JSON.

Reads:
  clients/_meraki/<org_slug>/security_events/<YYYY-MM-DD>.json
  clients/_meraki/<org_slug>/network_events/<network_slug>/<YYYY-MM-DD>.json
  clients/_meraki/<org_slug>/{org_meta,networks,devices}.json
  clients/_meraki/<org_slug>/networks/<network_slug>/*.json

Writes:
  clients/_meraki/<org_slug>/monthly/<YYYY-MM>.json     (structured summary)
  clients/_meraki/_monthly_index.json                    (cross-org index)

Usage:
  python aggregate_monthly.py                              # all orgs, all months found
  python aggregate_monthly.py --month 2026-03              # single month, all orgs
  python aggregate_monthly.py --only vaf,bwh               # subset of orgs
  python aggregate_monthly.py --from 2026-01 --to 2026-03  # range
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_ROOT = Path(
    r"c:/VSCode/annual-client-review/annual-client-review-1/clients/_meraki"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--month", help="Single month YYYY-MM")
    p.add_argument("--from", dest="from_month", help="Start month YYYY-MM (inclusive)")
    p.add_argument("--to", dest="to_month", help="End month YYYY-MM (inclusive)")
    p.add_argument("--only", help="Comma-separated org slugs")
    p.add_argument("--skip", help="Comma-separated org slugs to skip")
    p.add_argument("--root", default=str(DEFAULT_ROOT), help="Output root")
    return p.parse_args()


def month_of(date_str: str) -> str:
    return date_str[:7]  # YYYY-MM


def discover_org_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted([d for d in root.iterdir() if d.is_dir() and not d.name.startswith("_")])


def discover_months_for_org(org_dir: Path) -> set[str]:
    months: set[str] = set()
    sec_dir = org_dir / "security_events"
    if sec_dir.exists():
        for f in sec_dir.glob("*.json"):
            months.add(month_of(f.stem))
    net_dir = org_dir / "network_events"
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


def aggregate_security(org_dir: Path, month: str) -> dict:
    sec_dir = org_dir / "security_events"
    if not sec_dir.exists():
        return _empty_security()
    files = sorted([f for f in sec_dir.glob(f"{month}-*.json")])
    if not files:
        return _empty_security()

    daily_counts: list[dict] = []
    by_signature: Counter = Counter()
    by_priority: Counter = Counter()
    by_blocked: Counter = Counter()
    by_disposition: Counter = Counter()
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
            disp = ev.get("disposition") or ev.get("dstName") or ""
            if disp:
                by_disposition[disp] += 1
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
        "by_disposition_top": by_disposition.most_common(10),
        "top_sources": top_src.most_common(15),
        "top_destinations": top_dst.most_common(15),
        "top_internal_clients": top_clients.most_common(15),
        "sample_events": sample_events,
    }


def _empty_security() -> dict:
    return {"total": 0, "days_with_events": 0, "daily_counts": [],
            "by_signature_top": [], "by_priority": {}, "by_blocked": {},
            "by_disposition_top": [], "top_sources": [], "top_destinations": [],
            "top_internal_clients": [], "sample_events": []}


def aggregate_network(org_dir: Path, month: str) -> dict:
    net_dir = org_dir / "network_events"
    if not net_dir.exists():
        return _empty_network()

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


def _empty_network() -> dict:
    return {"total": 0, "networks_with_events": 0, "by_network": {},
            "by_type_top": [], "by_category": {}, "daily_counts": []}


def aggregate_configuration(org_dir: Path) -> dict:
    """Snapshot summary from the latest config pull (point-in-time, not historical).
    Counts firewall rules, IDS mode, AMP mode, content filtering categories,
    VLANs, SSIDs, etc. across all networks."""
    org_meta = load_json(org_dir / "org_meta.json") or {}
    networks = load_json(org_dir / "networks.json") or []
    devices = load_json(org_dir / "devices.json") or []
    snap = load_json(org_dir / "config_snapshot_at.json") or {}

    summary = {
        "org": org_meta.get("name"),
        "snapshot_at": snap.get("snapshot_at"),
        "network_count": len(networks),
        "device_count": len(devices),
        "device_models": dict(Counter(d.get("model") for d in devices)),
        "device_product_types": dict(Counter(d.get("productType") for d in devices)),
        "networks": [],
    }

    nets_dir = org_dir / "networks"
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
            l3 = load_json(n / "firewall_l3.json") or {}
            net_summary["firewall_l3_rule_count"] = len(l3.get("rules", []))
            l7 = load_json(n / "firewall_l7.json") or {}
            net_summary["firewall_l7_rule_count"] = len(l7.get("rules", []))
            inb = load_json(n / "firewall_inbound.json") or {}
            net_summary["firewall_inbound_rule_count"] = len(inb.get("rules", []))
            pf = load_json(n / "firewall_port_forwarding.json") or {}
            net_summary["port_forward_count"] = len(pf.get("rules", []))
            nat1 = load_json(n / "firewall_1to1_nat.json") or {}
            net_summary["one_to_one_nat_count"] = len(nat1.get("rules", []))
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

    orgs = [d for d in discover_org_dirs(root)
            if (not only or d.name in only) and d.name not in skip]
    print(f"Aggregating {len(orgs)} org(s) from {root}")

    index: list[dict] = []
    total_files = 0
    for org_dir in orgs:
        all_months = discover_months_for_org(org_dir)
        months = filter_months(all_months, args.month, args.from_month, args.to_month)
        if not months:
            print(f"  [{org_dir.name}] no months found")
            continue
        config_summary = aggregate_configuration(org_dir)

        out_dir = org_dir / "monthly"
        out_dir.mkdir(parents=True, exist_ok=True)
        for m in months:
            sec = aggregate_security(org_dir, m)
            net = aggregate_network(org_dir, m)
            payload = {
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "org_slug": org_dir.name,
                "month": m,
                "configuration": config_summary,
                "security_events": sec,
                "network_events": net,
            }
            out = out_dir / f"{m}.json"
            out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            total_files += 1
            index.append({"org_slug": org_dir.name, "month": m,
                          "security_events_total": sec["total"],
                          "network_events_total": net["total"],
                          "path": str(out.relative_to(root))})
            print(f"  [{org_dir.name}] {m}: sec={sec['total']:>5}  net={net['total']:>6}")

    idx_path = root / "_monthly_index.json"
    idx_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "monthly_files": index,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {total_files} monthly summaries")
    print(f"Index: {idx_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
