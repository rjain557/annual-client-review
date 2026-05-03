"""
Generate branded monthly Sophos XGS firewall activity reports per client.

Reads daily pull data from:
  clients/<code>/sophos/<YYYY-MM-DD>/pull_summary.json   (events/alerts aggregates)
  clients/<code>/sophos/<YYYY-MM-DD>/alerts.json          (alert detail list)
  clients/<code>/sophos/<YYYY-MM-DD>/firewalls.json       (device inventory)
  clients/<code>/sophos/<YYYY-MM-DD>/config_extended_*.json (on-box config snapshot)

Writes:
  clients/<code>/sophos/reports/<Name> - Sophos Monthly Activity - <YYYY-MM>.docx

Uses canonical Technijian brand helpers from technijian/shared/scripts/_brand.py.
Runs the proofread gate after every generated batch.

Usage:
  python generate_monthly_docx.py
  python generate_monthly_docx.py --month 2026-04
  python generate_monthly_docx.py --only ani,bwh,vaf
  python generate_monthly_docx.py --from 2026-01 --to 2026-04
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED    = REPO_ROOT / "technijian" / "shared" / "scripts"
sys.path.insert(0, str(SHARED))
import _brand as brand  # noqa: E402
import vendor_news  # noqa: E402
import compliance_section  # noqa: E402

PROOFREADER  = SHARED / "proofread_docx.py"
CLIENTS_ROOT = REPO_ROOT / "clients"

EXPECTED_SECTIONS = [
    "Executive Summary",
    "Firewall Inventory",
    "Firewall Configuration",
    "Security Posture",
    "Connectivity Alerts",
    "Firewall Events",
    "Daily Trend",
    "What Technijian Did For You",
    "Recommendations",
    "About This Report",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n) if n is not None else "0"


def _trunc(v, n=80) -> str:
    s = str(v) if v is not None else "-"
    return s if len(s) <= n else s[:n - 1] + "..."


def _top_n(d: dict, n: int = 10) -> list[tuple]:
    return sorted(d.items(), key=lambda x: -x[1])[:n]


# ---------------------------------------------------------------------------
# Data aggregation — reads all daily files for a given client/month
# ---------------------------------------------------------------------------

def aggregate_month(client_dir: Path, month: str) -> dict | None:
    """
    Aggregate all daily pull_summary + alerts files for one client/month.
    Returns a payload dict or None if no data found.
    """
    sophos_dir = client_dir / "sophos"
    if not sophos_dir.exists():
        return None

    # Collect all day folders for this month
    day_dirs = sorted(
        d for d in sophos_dir.iterdir()
        if d.is_dir() and d.name.startswith(month + "-")
    )
    if not day_dirs:
        return None

    # Accumulators
    events_total = 0
    events_by_group: dict[str, int] = defaultdict(int)
    events_by_type:  dict[str, int] = defaultdict(int)
    events_by_severity: dict[str, int] = defaultdict(int)
    alerts_total = 0
    alerts_open  = 0
    alerts_by_severity: dict[str, int] = defaultdict(int)
    alerts_by_product:  dict[str, int] = defaultdict(int)
    daily_events: dict[str, int] = {}
    daily_alerts: dict[str, int] = {}
    fw_connected  = 0
    fw_total      = 0
    location_name = ""
    location_code = client_dir.name.upper()
    tenant_name   = ""
    firmware_versions: dict[str, int] = defaultdict(int)

    # All alert detail (for category breakdowns)
    all_alerts: list[dict] = []

    last_summary = None

    for day_dir in day_dirs:
        date_tag = day_dir.name  # YYYY-MM-DD

        # pull_summary.json
        ps_file = day_dir / "pull_summary.json"
        if ps_file.exists():
            try:
                ps = json.loads(ps_file.read_text(encoding="utf-8"))
                last_summary = ps
                if not location_name:
                    location_name = ps.get("Location_Name") or ps.get("sophos_tenant_name") or ""
                if not tenant_name:
                    tenant_name = ps.get("sophos_tenant_name") or ""
                if not location_code or location_code == client_dir.name.upper():
                    location_code = ps.get("LocationCode") or location_code

                day_ev = ps.get("events_total", 0) or 0
                day_al = ps.get("alerts_total", 0) or 0
                events_total += day_ev
                alerts_total += day_al
                daily_events[date_tag] = day_ev
                daily_alerts[date_tag] = day_al

                for k, v in (ps.get("events_by_group") or {}).items():
                    events_by_group[k] += v
                for k, v in (ps.get("events_by_type") or {}).items():
                    events_by_type[k] += v
                for k, v in (ps.get("events_by_severity") or {}).items():
                    events_by_severity[k] += v
                for k, v in (ps.get("alerts_by_severity") or {}).items():
                    alerts_by_severity[k] += v
                for k, v in (ps.get("alerts_by_product") or {}).items():
                    alerts_by_product[k] += v
                for fw_ver, cnt in (ps.get("firewalls_by_firmware_major") or {}).items():
                    firmware_versions[fw_ver] += cnt

                # Use latest day's connected count
                fw_total     = ps.get("firewalls_total", 0) or fw_total
                fw_connected = ps.get("firewalls_connected", 0) or fw_connected
                alerts_open  = ps.get("alerts_open", 0) if ps.get("alerts_open") is not None else alerts_open
            except Exception:
                pass

        # alerts.json (daily detail list)
        al_file = day_dir / "alerts.json"
        if al_file.exists():
            try:
                alerts_data = json.loads(al_file.read_text(encoding="utf-8"))
                items = alerts_data if isinstance(alerts_data, list) else alerts_data.get("items", [])
                all_alerts.extend(items or [])
            except Exception:
                pass

    if not last_summary and not daily_events:
        return None

    # Deduplicate alerts by id
    seen_ids: set[str] = set()
    unique_alerts: list[dict] = []
    for a in all_alerts:
        aid = a.get("id") or ""
        if aid and aid not in seen_ids:
            seen_ids.add(aid)
            unique_alerts.append(a)

    # Category breakdown from alert detail
    alerts_by_category: dict[str, int] = defaultdict(int)
    for a in unique_alerts:
        alerts_by_category[a.get("category") or "unknown"] += 1

    # Top alert descriptions
    alert_desc_counts: dict[str, int] = defaultdict(int)
    for a in all_alerts:
        desc = a.get("description") or "—"
        alert_desc_counts[desc] += 1

    # Firewall inventory from latest available day
    firewalls: list[dict] = []
    for day_dir in reversed(day_dirs):
        fw_file = day_dir / "firewalls.json"
        if fw_file.exists():
            try:
                fw_data = json.loads(fw_file.read_text(encoding="utf-8"))
                firewalls = fw_data if isinstance(fw_data, list) else fw_data.get("items", [])
                break
            except Exception:
                pass

    # Config extended — find most recent snapshot across ALL sophos dates (not just this month)
    config_ext: dict = {}
    config_snap_date = ""
    all_sophos_dirs = sorted(
        (d for d in sophos_dir.iterdir() if d.is_dir() and d.name.startswith("20")),
        reverse=True,
    )
    for day_dir in all_sophos_dirs:
        ext_files = list(day_dir.glob("config_extended_*.json"))
        if ext_files:
            try:
                config_ext = json.loads(ext_files[0].read_text(encoding="utf-8"))
                config_snap_date = day_dir.name
                break
            except Exception:
                pass

    # Days with connectivity alerts (category = connectivity)
    conn_days = sum(1 for d in day_dirs
                    if (d / "alerts.json").exists()
                    and any(a.get("category") == "connectivity"
                            for a in _load_alerts(d / "alerts.json")))

    return {
        "month":          month,
        "client_code":    location_code,
        "location_name":  location_name or location_code,
        "tenant_name":    tenant_name or location_code,
        "config_snap_date": config_snap_date,
        "firewalls":      firewalls,
        "fw_total":       fw_total,
        "fw_connected":   fw_connected,
        "firmware_versions": dict(firmware_versions),
        "events": {
            "total":      events_total,
            "by_group":   dict(events_by_group),
            "by_type":    dict(events_by_type),
            "by_severity": dict(events_by_severity),
            "daily":      daily_events,
        },
        "alerts": {
            "total":         alerts_total,
            "open":          alerts_open,
            "by_severity":   dict(alerts_by_severity),
            "by_product":    dict(alerts_by_product),
            "by_category":   dict(alerts_by_category),
            "top_desc":      _top_n(alert_desc_counts, 15),
            "unique_count":  len(unique_alerts),
            "conn_days":     conn_days,
        },
        "daily_alerts":   daily_alerts,
        "daily_events":   daily_events,
        "config_ext":     config_ext,
    }


def _load_alerts(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("items", [])
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def render_cover(doc, location_name: str, month: str) -> None:
    month_dt = datetime.strptime(month, "%Y-%m")
    month_label = month_dt.strftime("%B %Y")
    brand.render_cover(
        doc,
        title="Sophos Firewall Monthly Activity",
        subtitle=f"{location_name} — {month_label}",
        date_text=f"Reporting period: {month_label}",
        footer_note="Confidential — for internal Technijian and named-client use only.",
    )
    brand.add_page_break(doc)


def section_executive_summary(doc, payload: dict) -> None:
    brand.add_section_header(doc, "Executive Summary")

    ev   = payload["events"]
    al   = payload["alerts"]
    fwc  = payload["fw_connected"]
    fwt  = payload["fw_total"]
    aop  = al.get("open", 0) or 0

    brand.add_metric_card_row(doc, [
        (fmt_int(fwt),             "Firewalls",      brand.CORE_BLUE),
        (fmt_int(fwc),             "Online",         brand.GREEN if fwt and fwc == fwt else brand.CORE_ORANGE),
        (fmt_int(al["total"]),     "Alerts (month)", brand.CORE_ORANGE if al["total"] else brand.GREEN),
        (fmt_int(aop),             "Alerts open",    brand.RED if aop else brand.GREEN),
        (fmt_int(ev["total"]),     "Events",         brand.TEAL),
    ])

    # Status callout
    offline = fwt - fwc
    if offline and fwt:
        brand.add_callout_box(
            doc,
            f"Connectivity gap — {offline} of {fwt} firewall(s) reported offline during "
            f"this period. See the Connectivity Alerts section for dates and duration.",
        )
    elif al["total"] == 0:
        brand.add_callout_box(
            doc,
            "All clear — all firewalls remained connected and no alerts were recorded "
            "during the reporting period.",
            accent_hex=brand.GREEN_HEX, bg_hex="EAF7EE",
        )
    else:
        brand.add_callout_box(
            doc,
            f"{fmt_int(al['total'])} alert(s) were generated across the reporting period; "
            f"{fmt_int(aop)} remain open. Review the Connectivity Alerts section for detail.",
            accent_hex=brand.CORE_BLUE_HEX, bg_hex="EAF3FA",
        )

    brand.add_body(
        doc,
        f"This report summarizes Sophos XGS firewall connectivity, security posture, "
        f"and operational activity for {payload['location_name']} during "
        f"{datetime.strptime(payload['month'], '%Y-%m').strftime('%B %Y')}. "
        f"Alert and event counts are aggregated from daily Sophos Central Partner API "
        f"pulls; firewall configuration reflects the most recent on-box API snapshot "
        f"({payload.get('config_snap_date') or 'not available'}).",
    )


def section_fw_inventory(doc, payload: dict) -> None:
    brand.add_section_header(doc, "Firewall Inventory")

    firewalls = payload.get("firewalls") or []
    fw_versions = payload.get("firmware_versions") or {}

    if not firewalls:
        brand.add_body(doc, "No firewall inventory data available for this period.")
        return

    rows = []
    for fw in firewalls:
        status = fw.get("status") or {}
        connected = status.get("connected", None)
        suspended = status.get("suspended", False)
        if suspended:
            conn_label = "Suspended"
        elif connected is True:
            conn_label = "Online"
        elif connected is False:
            conn_label = "Offline"
        else:
            conn_label = (fw.get("status") or {}).get("reportingStatus") or "-"
        wan_ips = ", ".join(fw.get("externalIpv4Addresses") or []) or "-"
        rows.append([
            fw.get("hostname") or fw.get("name") or "-",
            fw.get("model") or "-",
            fw.get("firmwareVersion") or "-",
            fw.get("serialNumber") or "-",
            wan_ips,
            conn_label,
        ])
    brand.styled_table(
        doc,
        ["Hostname", "Model", "Firmware", "Serial", "WAN IP", "Status"],
        rows,
        col_widths=[1.2, 1.1, 1.1, 1.2, 1.1, 0.7],
        status_col=5,
    )

    if fw_versions:
        brand.add_body(doc, "Firmware version distribution (across reporting month):", bold=True)
        rows2 = [[ver, fmt_int(cnt)] for ver, cnt in sorted(fw_versions.items())]
        brand.styled_table(doc, ["Firmware major version", "Days seen"], rows2,
                           col_widths=[4.0, 2.0])


def section_fw_config(doc, payload: dict) -> None:
    brand.add_section_header(doc, "Firewall Configuration")

    cfg = payload.get("config_ext") or {}
    snap_date = payload.get("config_snap_date") or "unknown"
    sections = cfg.get("sections") or {}

    if not sections:
        brand.add_body(
            doc,
            "No on-box configuration snapshot is available for this client. "
            "This section will populate once the extended config pull has "
            "been run and the firewall API has been whitelisted."
        )
        return

    brand.add_body(
        doc,
        f"Configuration snapshot captured {snap_date} via the Sophos XGS on-box API. "
        "Reflects the current state of interfaces, zones, routing, DHCP, NAT, and "
        "firewall rules.",
    )

    # Interfaces
    ifaces = (sections.get("interfaces") or {}).get("Interface", [])
    if ifaces:
        if isinstance(ifaces, dict):
            ifaces = [ifaces]
        brand.add_body(doc, "Network Interfaces:", bold=True)
        rows = []
        for iface in ifaces:
            if not isinstance(iface, dict):
                continue
            rows.append([
                iface.get("Name") or iface.get("name") or "-",
                iface.get("IPAddress") or iface.get("IPv4Address") or "-",
                iface.get("Netmask") or iface.get("SubnetMask") or "-",
                iface.get("Zone") or "-",
                iface.get("Status") or iface.get("Enable") or "-",
            ])
        if rows:
            brand.styled_table(doc, ["Interface", "IP Address", "Netmask", "Zone", "Status"],
                               rows, col_widths=[1.3, 1.5, 1.3, 1.2, 1.2])

    # Zones
    zones = (sections.get("zones") or {}).get("Zone", [])
    if zones:
        if isinstance(zones, dict):
            zones = [zones]
        brand.add_body(doc, "Zones:", bold=True)
        rows = []
        for z in zones:
            if not isinstance(z, dict):
                continue
            rows.append([
                z.get("Name") or z.get("name") or "-",
                z.get("Type") or z.get("ZoneType") or "-",
                z.get("Description") or "-",
            ])
        if rows:
            brand.styled_table(doc, ["Zone", "Type", "Description"],
                               rows, col_widths=[2.0, 1.5, 3.0])

    # Firewall Rules
    fw_rules = (sections.get("firewall_rules") or {}).get("FirewallRule", [])
    if fw_rules:
        if isinstance(fw_rules, dict):
            fw_rules = [fw_rules]
        brand.add_body(doc, f"Firewall Rules ({len(fw_rules)} total):", bold=True)
        rows = []
        for r in fw_rules:
            if not isinstance(r, dict):
                continue
            action = r.get("Action") or r.get("action") or "-"
            rows.append([
                r.get("Name") or r.get("name") or "-",
                action.title() if action != "-" else "-",
                r.get("SourceZones") or r.get("src_zone") or "-",
                r.get("DestinationZones") or r.get("dst_zone") or "-",
                "Yes" if str(r.get("Status", "1")) == "1" or r.get("Status") == "Enable" else "No",
            ])
        if rows:
            brand.styled_table(
                doc,
                ["Rule Name", "Action", "Source Zone", "Dest Zone", "Enabled"],
                rows,
                col_widths=[2.0, 0.9, 1.2, 1.2, 0.7],
                status_col=1,
            )

    # NAT Rules
    nat_rules = (sections.get("nat_rules") or {}).get("NATRule", [])
    if nat_rules:
        if isinstance(nat_rules, dict):
            nat_rules = [nat_rules]
        brand.add_body(doc, f"NAT Rules ({len(nat_rules)} total):", bold=True)
        rows = []
        for r in nat_rules:
            if not isinstance(r, dict):
                continue
            rows.append([
                r.get("Name") or r.get("name") or "-",
                r.get("Type") or r.get("NATType") or "-",
                r.get("OriginalSourceIP") or r.get("src") or "-",
                r.get("TranslatedSourceIP") or r.get("dst") or "-",
            ])
        if rows:
            brand.styled_table(doc, ["Rule Name", "Type", "Original IP", "Translated IP"],
                               rows, col_widths=[2.5, 1.0, 1.5, 1.5])

    # DHCP Scopes
    dhcp = (sections.get("dhcp_server") or {}).get("DHCPServer", [])
    if dhcp:
        if isinstance(dhcp, dict):
            dhcp = [dhcp]
        brand.add_body(doc, "DHCP Scopes:", bold=True)
        rows = []
        for scope in dhcp:
            if not isinstance(scope, dict):
                continue
            rows.append([
                scope.get("Name") or scope.get("name") or "-",
                scope.get("Interface") or scope.get("interface") or "-",
                scope.get("StartIP") or scope.get("start_ip") or "-",
                scope.get("EndIP") or scope.get("end_ip") or "-",
                scope.get("Lease") or scope.get("lease_time") or "-",
            ])
        if rows:
            brand.styled_table(doc, ["Scope Name", "Interface", "Start IP", "End IP", "Lease"],
                               rows, col_widths=[1.5, 1.2, 1.2, 1.2, 1.4])

    # Static Routes
    routes = (sections.get("static_routes") or {}).get("UnicastRoute", [])
    if routes:
        if isinstance(routes, dict):
            routes = [routes]
        real_routes = [r for r in routes if isinstance(r, dict)]
        if real_routes:
            brand.add_body(doc, f"Static Routes ({len(real_routes)}):", bold=True)
            rows = []
            for r in real_routes:
                rows.append([
                    r.get("Network") or r.get("Destination") or "-",
                    r.get("Mask") or r.get("SubnetMask") or "-",
                    r.get("Gateway") or r.get("NextHop") or "-",
                    r.get("Interface") or "-",
                    r.get("Distance") or "-",
                ])
            brand.styled_table(doc, ["Destination", "Mask", "Gateway", "Interface", "Metric"],
                               rows, col_widths=[1.5, 1.2, 1.5, 1.2, 0.7])


def section_security_posture(doc, payload: dict) -> None:
    brand.add_section_header(doc, "Security Posture")

    cfg = payload.get("config_ext") or {}
    sections = cfg.get("sections") or {}

    brand.add_body(
        doc,
        "Current intrusion-prevention, web-filtering, SSL/TLS inspection, and "
        "network-object configuration from the most recent on-box snapshot. "
        "This section captures the security controls in place on the Sophos XGS "
        "firewall at time of last pull.",
    )

    # IPS Policies
    ips_list = (sections.get("ips_policy") or {}).get("IPSPolicy", [])
    if ips_list:
        if isinstance(ips_list, dict):
            ips_list = [ips_list]
        brand.add_body(doc, f"IPS / Intrusion Prevention Policies ({len(ips_list)}):", bold=True)
        rows = []
        for p in ips_list:
            if not isinstance(p, dict):
                continue
            rows.append([
                p.get("Name") or p.get("name") or "-",
                p.get("Description") or "-",
            ])
        if rows:
            brand.styled_table(doc, ["Policy Name", "Description"],
                               rows, col_widths=[2.5, 4.0])

    # Web Filter Policies
    wf_list = (sections.get("web_filter") or {}).get("WebFilterPolicy", [])
    if wf_list:
        if isinstance(wf_list, dict):
            wf_list = [wf_list]
        brand.add_body(doc, f"Web Filter Policies ({len(wf_list)}):", bold=True)
        rows = []
        for p in wf_list:
            if not isinstance(p, dict):
                continue
            rows.append([
                p.get("Name") or p.get("name") or "-",
                p.get("Description") or "-",
            ])
        if rows:
            brand.styled_table(doc, ["Policy Name", "Description"],
                               rows[:15], col_widths=[2.5, 4.0])

    # SSL/TLS Inspection
    ssl_sec = sections.get("ssl_tls_inspection") or {}
    ssl_rules = ssl_sec.get("SSLTLSInspectionRule", [])
    if ssl_rules:
        if isinstance(ssl_rules, dict):
            ssl_rules = [ssl_rules]
        real = [r for r in ssl_rules if isinstance(r, dict)]
        if real:
            brand.add_body(doc, f"SSL/TLS Inspection Rules ({len(real)}):", bold=True)
            rows = []
            for r in real:
                rows.append([
                    r.get("Name") or r.get("name") or "-",
                    r.get("Action") or r.get("action") or "-",
                    r.get("Status") or "-",
                ])
            brand.styled_table(doc, ["Rule Name", "Action", "Status"],
                               rows[:10], col_widths=[3.0, 1.5, 1.0])

    # Network objects summary
    hosts = (sections.get("network_objects") or {}).get("IPHost", [])
    host_groups = (sections.get("host_groups") or {}).get("IPHostGroup", [])
    services = (sections.get("service_objects") or {}).get("Services", [])
    if isinstance(hosts, dict): hosts = [hosts]
    if isinstance(host_groups, dict): host_groups = [host_groups]
    if isinstance(services, dict): services = [services]

    brand.add_metric_card_row(doc, [
        (fmt_int(len(hosts) if isinstance(hosts, list) else 0),        "IP Host Objects", brand.CORE_BLUE),
        (fmt_int(len(host_groups) if isinstance(host_groups, list) else 0), "Host Groups", brand.CORE_BLUE),
        (fmt_int(len(services) if isinstance(services, list) else 0),  "Service Objects", brand.CORE_BLUE),
    ])

    if not (ips_list or wf_list or ssl_rules):
        brand.add_body(
            doc,
            "Configuration snapshot not yet available for this client. "
            "Firewall API access must be whitelisted before security posture "
            "details can be captured.",
        )


def section_connectivity_alerts(doc, payload: dict) -> None:
    brand.add_section_header(doc, "Connectivity Alerts")

    al   = payload["alerts"]
    total = al.get("total", 0)

    month_label = datetime.strptime(payload["month"], "%Y-%m").strftime("%B %Y")
    brand.add_body(
        doc,
        f"Total alerts generated by Sophos Central during {month_label}: "
        f"{fmt_int(total)}. Sophos Central alerts include connectivity events "
        f"(gateway up/down), license notifications, and policy violations.",
    )

    if total == 0:
        brand.add_callout_box(
            doc,
            "No alerts were recorded via Sophos Central during this period. "
            "All firewalls maintained connectivity and no platform-level "
            "events were generated.",
            accent_hex=brand.GREEN_HEX, bg_hex="EAF7EE",
        )
        return

    brand.add_metric_card_row(doc, [
        (fmt_int(total),              "Total alerts",   brand.CORE_ORANGE if total else brand.GREEN),
        (fmt_int(al.get("open", 0)),  "Open alerts",    brand.RED if al.get("open", 0) else brand.GREEN),
        (fmt_int(al.get("conn_days", 0)), "Days with connectivity alerts", brand.CORE_ORANGE if al.get("conn_days", 0) else brand.GREEN),
    ])

    # By category
    if al.get("by_category"):
        brand.add_body(doc, "Alerts by category:", bold=True)
        rows = sorted(al["by_category"].items(), key=lambda x: -x[1])
        brand.styled_table(doc, ["Category", "Count"],
                           [[k.replace("_", " ").title(), fmt_int(v)] for k, v in rows],
                           col_widths=[4.0, 2.0])

    # By severity
    if al.get("by_severity"):
        brand.add_body(doc, "Alerts by severity:", bold=True)
        rows = sorted(al["by_severity"].items(), key=lambda x: x[0])
        brand.styled_table(doc, ["Severity", "Count"],
                           [[k.title(), fmt_int(v)] for k, v in rows],
                           col_widths=[4.0, 2.0])

    # By product
    if al.get("by_product"):
        brand.add_body(doc, "Alerts by product:", bold=True)
        rows = sorted(al["by_product"].items(), key=lambda x: -x[1])
        brand.styled_table(doc, ["Product", "Count"],
                           [[k.title(), fmt_int(v)] for k, v in rows],
                           col_widths=[4.0, 2.0])

    # Top alert descriptions
    if al.get("top_desc"):
        brand.add_body(doc, "Top alert descriptions:", bold=True)
        rows = [[_trunc(desc, 80), fmt_int(cnt)]
                for desc, cnt in al["top_desc"]]
        brand.styled_table(doc, ["Alert Description", "Count"],
                           rows, col_widths=[5.0, 1.0])


def section_fw_events(doc, payload: dict) -> None:
    brand.add_section_header(doc, "Firewall Events")

    ev    = payload["events"]
    total = ev.get("total", 0)

    brand.add_body(
        doc,
        f"Sophos Central event log entries for the reporting period: "
        f"{fmt_int(total)} total. Events include policy matches, threat detections, "
        f"and system activity recorded by the firewall and reported to Sophos Central.",
    )

    if total == 0:
        brand.add_body(
            doc,
            "No firewall events were recorded in Sophos Central during this period. "
            "This is typical for firewalls where only connectivity-level alerts are "
            "forwarded to Sophos Central. Detailed threat events require syslog "
            "forwarding to be configured to the Technijian DC syslog receiver.",
        )
        return

    if ev.get("by_group"):
        brand.add_body(doc, "Events by group:", bold=True)
        rows = sorted(ev["by_group"].items(), key=lambda x: -x[1])
        brand.styled_table(doc, ["Event Group", "Count"],
                           [[k, fmt_int(v)] for k, v in rows],
                           col_widths=[4.5, 1.5])

    if ev.get("by_type"):
        brand.add_body(doc, "Top event types:", bold=True)
        top = sorted(ev["by_type"].items(), key=lambda x: -x[1])[:15]
        brand.styled_table(doc, ["Event Type", "Count"],
                           [[k, fmt_int(v)] for k, v in top],
                           col_widths=[4.5, 1.5])

    if ev.get("by_severity"):
        brand.add_body(doc, "Events by severity:", bold=True)
        rows = sorted(ev["by_severity"].items(), key=lambda x: x[0])
        brand.styled_table(doc, ["Severity", "Count"],
                           [[k.title(), fmt_int(v)] for k, v in rows],
                           col_widths=[4.0, 2.0])


def section_daily_trend(doc, payload: dict) -> None:
    brand.add_section_header(doc, "Daily Trend")

    brand.add_body(
        doc,
        "Day-by-day count of Sophos Central alerts and firewall events throughout "
        "the reporting month. Connectivity spikes typically indicate WAN instability "
        "or ISP outages. Persistent open alerts warrant investigation.",
    )

    daily_al = payload.get("daily_alerts") or {}
    daily_ev = payload.get("daily_events") or {}
    days = sorted(set(daily_al) | set(daily_ev))
    if not days:
        brand.add_body(doc, "No daily data available for this period.")
        return

    rows = [
        [d, fmt_int(daily_al.get(d, 0)), fmt_int(daily_ev.get(d, 0))]
        for d in days
    ]
    brand.styled_table(
        doc,
        ["Date", "Alerts", "Events"],
        rows,
        col_widths=[2.5, 1.75, 1.75],
    )


def section_what_technijian_did(doc, payload: dict) -> None:
    brand.add_section_header(doc, "What Technijian Did For You")

    brand.add_body(
        doc,
        "Throughout the reporting period the Technijian security operations team "
        "performed the following ongoing services for your Sophos firewall environment:",
    )
    bullets = [
        ("24x7 monitoring: ",
         "continuous health checks against every Sophos XGS firewall via the "
         "Sophos Central Partner API; alerts are reviewed within on-call SLA."),
        ("Connectivity tracking: ",
         "daily firewall connection status is recorded; gaps beyond 15 minutes "
         "trigger an investigation and ticket in the Technijian Client Portal."),
        ("Configuration baseline: ",
         "on-box API snapshots capture firewall rules, NAT, IPS policies, web "
         "filter, zones, interfaces, and network objects; deviations from the "
         "documented baseline are reviewed on each pull."),
        ("Firmware awareness: ",
         "firmware version is tracked daily; Sophos XGS advisories are reviewed "
         "and upgrade windows are coordinated with you when critical patches are "
         "available."),
        ("Monthly reporting: ",
         "this document is generated from the Sophos Central API and on-box "
         "configuration data, verified through a structural proofreader, and "
         "delivered as part of your Managed Security service."),
    ]
    for prefix, text in bullets:
        brand.add_bullet(doc, text, bold_prefix=prefix)


def section_recommendations(doc, payload: dict) -> None:
    brand.add_section_header(doc, "Recommendations")

    al   = payload["alerts"]
    ev   = payload["events"]
    cfg  = (payload.get("config_ext") or {}).get("sections") or {}
    recs: list[tuple[str, str]] = []

    # Connectivity alert recommendation
    conn_days = al.get("conn_days", 0) or 0
    if conn_days:
        recs.append((
            "Investigate connectivity gaps: ",
            f"the firewall lost contact with Sophos Central on {fmt_int(conn_days)} "
            f"day(s) this period. Sustained outages may indicate WAN instability or "
            f"ISP issues. Review ISP SLA and consider a secondary WAN link.",
        ))

    # Open alerts
    open_al = al.get("open", 0) or 0
    if open_al:
        recs.append((
            "Resolve open alerts: ",
            f"{fmt_int(open_al)} alert(s) remain open in Sophos Central. Log into "
            f"the Central dashboard and acknowledge or dismiss any stale alerts to "
            f"keep the alert queue clean.",
        ))

    # Missing config snapshot
    if not cfg:
        recs.append((
            "Enable on-box API access: ",
            "firewall configuration details are not yet available. To unlock the "
            "Firewall Configuration and Security Posture sections, add the "
            "Technijian scanner IP (64.58.160.218) to the WAN zone allowed-API-IPs "
            "list under Administration > Device Access.",
        ))

    # IPS check
    ips = cfg.get("ips_policy", {}).get("IPSPolicy", [])
    if cfg and not ips:
        recs.append((
            "Review IPS policy assignment: ",
            "no IPS policies were found in the on-box snapshot. Confirm that an "
            "intrusion-prevention policy is assigned to all active firewall rules "
            "handling internet-bound traffic.",
        ))

    # Web filter check
    wf = cfg.get("web_filter", {}).get("WebFilterPolicy", [])
    if cfg and not wf:
        recs.append((
            "Configure web filtering: ",
            "no web filter policies were detected. Enabling web category filtering "
            "blocks malicious and high-risk categories (C2, malware, adult content) "
            "without additional licensing on Sophos XGS.",
        ))

    # Zero events — confirm syslog
    if ev["total"] == 0 and cfg:
        recs.append((
            "Configure syslog forwarding: ",
            "Sophos Central reports zero firewall events. IPS and threat events are "
            "only surfaced in Central if syslog forwarding is enabled. Configure "
            "Log Settings to forward to the Technijian DC syslog receiver for full "
            "threat-event visibility in future reports.",
        ))

    if not recs:
        recs.append((
            "Stay the course: ",
            "the firewall remained connected, all policies are in place, and alert "
            "volumes are within expected ranges. No configuration changes are "
            "recommended for this period.",
        ))

    for prefix, text in recs:
        brand.add_bullet(doc, text, bold_prefix=prefix)


def section_about(doc, payload: dict) -> None:
    brand.add_section_header(doc, "About This Report")

    brand.add_body(
        doc,
        "This report is generated automatically from the Sophos Central Partner API "
        "and the Sophos XGS on-box configuration API by Technijian's annual-client-"
        "review pipeline. Alert and event counts are aggregated from daily API pulls; "
        "configuration data reflects the most recent on-box snapshot.",
    )
    brand.add_body(
        doc,
        f"Report generated {datetime.now().strftime('%Y-%m-%d %H:%M').strip()} "
        f"for client '{payload['client_code']}'. Configuration snapshot: "
        f"{payload.get('config_snap_date') or 'not available'}.",
    )
    brand.add_body(
        doc,
        "For questions about this report or to request a different reporting cadence, "
        "email support@technijian.com.",
    )


# ---------------------------------------------------------------------------
# Build orchestration
# ---------------------------------------------------------------------------

def build_report(payload: dict, out_path: Path) -> None:
    doc = brand.new_branded_document()
    render_cover(doc, payload["location_name"], payload["month"])

    section_executive_summary(doc, payload)
    section_fw_inventory(doc, payload)
    section_fw_config(doc, payload)
    section_security_posture(doc, payload)
    section_connectivity_alerts(doc, payload)
    section_fw_events(doc, payload)
    section_daily_trend(doc, payload)
    section_what_technijian_did(doc, payload)
    try:
        ym = payload["month"]
        year_int, month_int = (int(x) for x in ym.split("-"))
        vendor_news.render_section(doc, "sophos", year_int, month_int, brand)
    except Exception:
        pass
    try:
        compliance_section.render_section(doc, payload["client_code"].lower(), brand)
    except Exception:
        pass
    section_recommendations(doc, payload)
    section_about(doc, payload)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))


def run_proofreader(generated: list[Path]) -> int:
    if not generated:
        return 0
    if not PROOFREADER.exists():
        print(f"\n[proofread] WARNING: proofreader missing — skipping.")
        return 0
    sections_csv = ",".join(EXPECTED_SECTIONS)
    cmd = [sys.executable, str(PROOFREADER), "--sections", sections_csv]
    cmd += [str(p) for p in generated if p.exists()]
    print("\n=== Proofreading reports ===")
    sys.stdout.flush()
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        print(f"\n[proofread] FAILED — one or more reports did not pass the gate (rc={rc}).")
    else:
        print(f"[proofread] OK — {len(generated)} report(s) passed all checks.")
    return rc


def discover_months(client_dir: Path, from_month: str | None, to_month: str | None) -> list[str]:
    """Return sorted list of YYYY-MM strings that have at least one day folder."""
    sophos_dir = client_dir / "sophos"
    if not sophos_dir.exists():
        return []
    months: set[str] = set()
    for d in sophos_dir.iterdir():
        if d.is_dir() and len(d.name) == 10 and d.name[4] == "-" and d.name[7] == "-":
            m = d.name[:7]  # YYYY-MM
            if from_month and m < from_month:
                continue
            if to_month and m > to_month:
                continue
            if (d / "pull_summary.json").exists() or (d / "alerts.json").exists():
                months.add(m)
    return sorted(months)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--month",  help="Single month YYYY-MM (default: all available)")
    p.add_argument("--from",   dest="from_month", help="Start month YYYY-MM")
    p.add_argument("--to",     dest="to_month",   help="End month YYYY-MM")
    p.add_argument("--only",   help="Comma-separated client codes")
    p.add_argument("--skip",   help="Comma-separated codes to skip")
    p.add_argument("--root",   default=str(CLIENTS_ROOT))
    p.add_argument("--no-proof", action="store_true", help="Skip proofreader gate")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root     = Path(args.root)
    only     = {s.strip().lower() for s in (args.only or "").split(",") if s.strip()}
    skip     = {s.strip().lower() for s in (args.skip or "").split(",") if s.strip()}
    from_m   = args.from_month or (args.month if args.month else None)
    to_m     = args.to_month   or (args.month if args.month else None)

    generated: list[Path] = []

    for client_dir in sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith("_")):
        if only and client_dir.name.lower() not in only:
            continue
        if client_dir.name.lower() in skip:
            continue
        if not (client_dir / "sophos").exists():
            continue

        months = discover_months(client_dir, from_m, to_m)
        if not months:
            continue

        for month in months:
            payload = aggregate_month(client_dir, month)
            if not payload:
                continue

            safe_name = "".join(c if c.isalnum() or c in " -_" else "_"
                                for c in payload["location_name"])
            out = (client_dir / "sophos" / "reports" /
                   f"{safe_name} - Sophos Monthly Activity - {month}.docx")

            build_report(payload, out)
            generated.append(out)
            try:
                rel = out.relative_to(root)
            except ValueError:
                rel = out
            print(f"  [{client_dir.name}] {month} -> {rel}")

    print(f"\nGenerated {len(generated)} Word report(s)")
    if args.no_proof:
        return 0
    return run_proofreader(generated)


if __name__ == "__main__":
    sys.exit(main())
