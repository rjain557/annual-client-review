"""
Pull a full configuration snapshot for every accessible Meraki org/network.

Output (overwritten on each run — this is a "current state" snapshot):

  clients/<code>/meraki/
    org_meta.json
    networks.json
    devices.json
    config_snapshot_at.json     # timestamp + endpoint coverage report
    networks/<network_slug>/
      meta.json
      <one file per config endpoint>.json

Endpoint set is defined in meraki_api.py:
  - APPLIANCE_CONFIG_ENDPOINTS  (firewall L3/L7/inbound/cellular, NAT, port
    forwards, IDS/IPS, AMP, content filtering, traffic shaping, VLANs, S2S
    VPN, static routes, ports, settings)
  - WIRELESS_CONFIG_ENDPOINTS   (SSIDs, settings, RF profiles)
  - SWITCH_CONFIG_ENDPOINTS     (access policies, QoS, port schedules, settings)
  - NETWORK_WIDE_CONFIG_ENDPOINTS  (syslog, SNMP, alerts, group policies, webhooks)

403 / 404 responses (feature not enabled, org dormant) are recorded in the
coverage report and skipped silently — they're expected per network shape.

Usage:
  python pull_configuration.py
  python pull_configuration.py --only VAF,BWH
  python pull_configuration.py --skip technijian
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import meraki_api as m
from _org_mapping import client_folder


DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "clients"


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", help="Comma-separated org slugs to include")
    p.add_argument("--skip", help="Comma-separated org slugs to skip")
    p.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def pull_endpoint(template: str, network_id: str) -> tuple[str, object]:
    """Returns (status, body). status is 'ok', a tolerated HTTP code as
    string, or 'err:<code>' for unexpected errors.

    Tolerated:
      400 — "feature not enabled on this network" (VLANs disabled, IDS
            not licensed, etc.)
      403 — license-gated org
      404 — endpoint not applicable to this product type
    """
    path = template.format(nid=network_id)
    try:
        body = m.get(path, allow_403=False, allow_404=False)
        return ("ok", body)
    except m.MerakiError as e:
        if e.status in (400, 403, 404):
            return (str(e.status), None)
        return (f"err:{e.status}", None)


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root)
    only = {s.strip().lower() for s in (args.only or "").split(",") if s.strip()}
    skip = {s.strip().lower() for s in (args.skip or "").split(",") if s.strip()}

    print("Auth check ...", flush=True)
    me = m.whoami()
    print(f"  {me.get('name')} ({me.get('email')})")

    orgs = m.list_organizations()
    print(f"Discovered {len(orgs)} accessible orgs")

    if args.dry_run:
        for org in orgs:
            slug = m.slugify(org["name"])
            if only and slug not in only:
                continue
            if slug in skip:
                continue
            print(f"  [dry] would snapshot: {slug} ({org['id']})")
        return 0

    pulled_orgs = 0
    pulled_nets = 0
    coverage_summary = []
    for org in orgs:
        slug = m.slugify(org["name"])
        if only and slug not in only:
            continue
        if slug in skip:
            continue
        org_dir = output_root / client_folder(slug) / "meraki"
        write_json(org_dir / "org_meta.json", org)

        try:
            networks = m.list_networks(org["id"])
            devices = m.list_devices(org["id"])
        except m.MerakiError as e:
            print(f"  [{slug}] org-level fetch failed: HTTP {e.status} — skipping")
            write_json(org_dir / "config_snapshot_at.json", {
                "snapshot_at": iso_utc(datetime.now(timezone.utc)),
                "error": f"HTTP {e.status} on org-level enumeration",
            })
            continue
        write_json(org_dir / "networks.json", networks)
        write_json(org_dir / "devices.json", devices)
        pulled_orgs += 1
        print(f"  [{slug}] {len(networks)} networks, {len(devices)} devices")

        org_coverage = []
        for net in networks:
            net_slug = m.slugify(net["name"])
            net_dir = org_dir / "networks" / net_slug
            write_json(net_dir / "meta.json", net)

            endpoint_set: list[tuple[str, str]] = []
            endpoint_set += list(m.NETWORK_WIDE_CONFIG_ENDPOINTS)
            if m.network_has_product(net, "appliance"):
                endpoint_set += list(m.APPLIANCE_CONFIG_ENDPOINTS)
            if m.network_has_product(net, "wireless"):
                endpoint_set += list(m.WIRELESS_CONFIG_ENDPOINTS)
            if m.network_has_product(net, "switch"):
                endpoint_set += list(m.SWITCH_CONFIG_ENDPOINTS)

            net_coverage = {"network": net["name"], "id": net["id"],
                            "productTypes": net.get("productTypes"),
                            "endpoints": {}}
            for tmpl, fname in endpoint_set:
                status, body = pull_endpoint(tmpl, net["id"])
                net_coverage["endpoints"][fname] = status
                if status == "ok":
                    write_json(net_dir / fname, body)
            ok = sum(1 for v in net_coverage["endpoints"].values() if v == "ok")
            total = len(net_coverage["endpoints"])
            print(f"    {net_slug}: {ok}/{total} endpoints captured")
            org_coverage.append(net_coverage)
            pulled_nets += 1

        write_json(org_dir / "config_snapshot_at.json", {
            "snapshot_at": iso_utc(datetime.now(timezone.utc)),
            "org": {"id": org["id"], "name": org["name"]},
            "network_count": len(networks),
            "device_count": len(devices),
            "coverage": org_coverage,
        })
        coverage_summary.append({"org": org["name"], "slug": slug,
                                 "networks": len(networks),
                                 "devices": len(devices)})

    log = output_root / "_meraki_logs" / "configuration_pull_log.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({
        "snapshot_at": iso_utc(datetime.now(timezone.utc)),
        "orgs_snapshotted": pulled_orgs,
        "networks_snapshotted": pulled_nets,
        "by_org": coverage_summary,
    }, indent=2), encoding="utf-8")
    print(f"\nSnapshot complete: {pulled_orgs} orgs, {pulled_nets} networks")
    print(f"Log: {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
