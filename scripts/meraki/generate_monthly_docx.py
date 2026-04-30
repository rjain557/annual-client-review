"""
Generate branded monthly Meraki activity Word reports per client.

Reads JSON summaries written by aggregate_monthly.py:
  clients/<code>/meraki/monthly/<YYYY-MM>.json

Writes:
  clients/<code>/meraki/reports/<Org Name> - Meraki Monthly Activity - <YYYY-MM>.docx

Uses the canonical Technijian brand helpers from
`technijian/shared/scripts/_brand.py` (cover page, section headers, styled
tables, metric cards, callout boxes — Open Sans, CORE_BLUE #006DB6, CORE_ORANGE
#F67D4B). Runs the proofread gate (`technijian/shared/scripts/proofread_docx.py`)
on every generated report and exits non-zero on any failure.

Usage:
  python generate_monthly_docx.py
  python generate_monthly_docx.py --month 2026-03
  python generate_monthly_docx.py --only vaf,bwh
  python generate_monthly_docx.py --from 2026-01 --to 2026-03
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Wire in shared brand helpers
REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED = REPO_ROOT / "technijian" / "shared" / "scripts"
sys.path.insert(0, str(SHARED))
import _brand as brand  # noqa: E402

PROOFREADER = SHARED / "proofread_docx.py"
CLIENTS_ROOT = REPO_ROOT / "clients"

EXPECTED_SECTIONS = [
    "Executive Summary",
    "Network & Device Inventory",
    "Firewall Configuration",
    "Security Posture",
    "Configuration Changes",
    "IDS/IPS & AMP Events",
    "Firewall & Network Activity",
    "Daily Trend",
    "What Technijian Did For You",
    "Recommendations",
    "About This Report",
]


def fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n) if n is not None else "0"


def status_color_for_security(total: int, blocked: int, alerted: int):
    if total == 0:
        return brand.GREEN
    if blocked >= alerted:
        return brand.CORE_BLUE
    return brand.CORE_ORANGE


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def render_cover_page(doc, org_name: str, month: str) -> None:
    month_dt = datetime.strptime(month, "%Y-%m")
    month_label = month_dt.strftime("%B %Y")
    brand.render_cover(
        doc,
        title=f"Meraki Monthly Activity",
        subtitle=f"{org_name} — {month_label}",
        date_text=f"Reporting period: {month_label}",
        footer_note="Confidential — for internal Technijian and named-client use only.",
    )
    brand.add_page_break(doc)


def section_executive_summary(doc, payload: dict) -> None:
    brand.add_section_header(doc, "Executive Summary")

    cfg = payload["configuration"]
    sec = payload["security_events"]
    net = payload["network_events"]
    chg = payload.get("config_changes") or {}
    blocked = (sec.get("by_blocked") or {}).get("blocked", 0) or 0
    alerted = (sec.get("by_blocked") or {}).get("alerted", 0) or 0

    # KPI strip
    brand.add_metric_card_row(doc, [
        (fmt_int(cfg.get("network_count", 0)), "Networks",        brand.CORE_BLUE),
        (fmt_int(cfg.get("device_count", 0)),  "Devices",         brand.CORE_BLUE),
        (fmt_int(sec.get("total", 0)),         "IDS/IPS events",
         status_color_for_security(sec.get("total", 0), blocked, alerted)),
        (fmt_int(net.get("total", 0)),         "Activity events", brand.TEAL),
        (fmt_int(chg.get("total", 0)),         "Config changes",
         brand.CORE_ORANGE if chg.get("total", 0) > 0 else brand.GREEN),
    ])

    # Status callout
    if sec.get("total", 0) == 0:
        brand.add_callout_box(
            doc,
            "All clear — no IDS/IPS or AMP events were recorded across the "
            "reporting period. Continue normal monitoring.",
            accent_hex=brand.GREEN_HEX, bg_hex="EAF7EE",
        )
    elif blocked >= alerted:
        brand.add_callout_box(
            doc,
            f"Active prevention — {fmt_int(blocked)} threats blocked, "
            f"{fmt_int(alerted)} alerted. The intrusion-prevention engine is "
            "actively dropping malicious traffic.",
            accent_hex=brand.CORE_BLUE_HEX, bg_hex="EAF3FA",
        )
    else:
        brand.add_callout_box(
            doc,
            f"Detect-mode activity — {fmt_int(alerted)} alerts recorded with "
            f"{fmt_int(blocked)} blocks. Review whether the appliance should be "
            "moved from detect to prevention mode for high-priority signatures.",
        )

    brand.add_body(
        doc,
        f"This report summarizes Cisco Meraki firewall, intrusion-prevention "
        f"(IDS/IPS), advanced-malware-protection (AMP), and configuration "
        f"posture for {payload['configuration'].get('org') or payload['client_code']} "
        f"during {payload['month']}. Activity counts are aggregated from daily "
        f"Meraki Dashboard API pulls; configuration reflects the most recent "
        f"snapshot.",
    )


def section_inventory(doc, cfg: dict) -> None:
    brand.add_section_header(doc, "Network & Device Inventory")

    devices = cfg.get("devices") or []
    if devices:
        brand.add_body(doc, "Device inventory:", bold=True)
        rows = [[
            d.get("name") or "—",
            d.get("network") or "—",
            d.get("model") or "—",
            d.get("serial") or "—",
            d.get("firmware") or "—",
            d.get("lanIp") or "—",
            (d.get("productType") or "—").replace("cellularGateway", "cellular"),
        ] for d in devices]
        brand.styled_table(
            doc,
            ["Device", "Network", "Model", "Serial", "Firmware", "LAN IP", "Type"],
            rows,
            col_widths=[1.2, 0.8, 0.8, 1.0, 1.0, 0.9, 0.8],
        )
    else:
        brand.add_body(doc, "Devices by model:", bold=True)
        rows = sorted(((m or "(unknown)", c) for m, c in (cfg.get("device_models") or {}).items()),
                      key=lambda x: -x[1]) or [("—", 0)]
        brand.styled_table(doc, ["Model", "Count"], [[m, fmt_int(c)] for m, c in rows],
                           col_widths=[3.5, 1.5])

        brand.add_body(doc, "Devices by product type:", bold=True)
        rows = sorted(((m or "(unknown)", c) for m, c in (cfg.get("device_product_types") or {}).items()),
                      key=lambda x: -x[1]) or [("—", 0)]
        brand.styled_table(doc, ["Product type", "Count"], [[m, fmt_int(c)] for m, c in rows],
                           col_widths=[3.5, 1.5])

    brand.add_body(doc, "Networks under management:", bold=True)
    headers = ["Network", "Product types", "VLANs", "L3 rules", "L7 rules", "Inbound", "Port fwd"]
    rows = []
    for n in cfg.get("networks", []) or []:
        rows.append([
            n.get("name") or n.get("slug") or "—",
            ", ".join(n.get("productTypes") or []) or "—",
            fmt_int(n.get("vlan_count", 0)),
            fmt_int(n.get("firewall_l3_rule_count", 0)),
            fmt_int(n.get("firewall_l7_rule_count", 0)),
            fmt_int(n.get("firewall_inbound_rule_count", 0)),
            fmt_int(n.get("port_forward_count", 0)),
        ])
    if not rows:
        rows = [["(no networks)", "—", "0", "0", "0", "0", "0"]]
    brand.styled_table(doc, headers, rows,
                       col_widths=[1.7, 1.3, 0.6, 0.65, 0.65, 0.65, 0.65])


def _fmt_src(rule: dict) -> str:
    cidr = rule.get("srcCidr") or "Any"
    port = rule.get("srcPort") or "Any"
    return cidr if port == "Any" else f"{cidr}:{port}"


def _fmt_dst(rule: dict) -> str:
    cidr = rule.get("destCidr") or "Any"
    port = rule.get("destPort") or "Any"
    return cidr if port == "Any" else f"{cidr}:{port}"


def section_firewall_config(doc, cfg: dict) -> None:
    brand.add_section_header(doc, "Firewall Configuration")
    brand.add_body(
        doc,
        "Full configuration snapshot of WAN interfaces, firewall rules, VLANs, "
        "port-forwarding, wireless SSIDs, and site-to-site VPN per network. "
        "Values reflect the most recent configuration pull.",
    )

    # ── WAN Interface Configuration (appliances only) ──────────────────────
    appliances = [d for d in (cfg.get("devices") or []) if d.get("productType") == "appliance"]
    if appliances:
        brand.add_body(doc, "WAN Interface Configuration:", bold=True)
        wan_rows = []
        for dev in appliances:
            dev_name = dev.get("name") or dev.get("serial") or "—"
            net_name = dev.get("network") or "—"
            interfaces = dev.get("uplink_settings") or {}
            statuses = {ul.get("interface"): ul for ul in (dev.get("uplink_status") or [])}
            if not interfaces:
                wan_rows.append([dev_name, net_name, "—", "—", "—", "—", "—"])
                continue
            for iface_name, iface_cfg in sorted(interfaces.items()):
                if not iface_cfg.get("enabled", True):
                    continue
                svi = ((iface_cfg.get("svis") or {}).get("ipv4") or {})
                assignment = (svi.get("assignmentMode") or "dhcp").title()
                ip_addr = svi.get("address") or "—"
                gateway = svi.get("gateway") or "—"
                dns_list = (svi.get("nameservers") or {}).get("addresses") or []
                dns = " / ".join(dns_list) if dns_list else "—"
                status_rec = statuses.get(iface_name) or {}
                status = (status_rec.get("status") or "—").replace("not connected", "standby")
                wan_rows.append([dev_name, net_name, iface_name.upper(),
                                 assignment, ip_addr, gateway, dns])
                dev_name = ""  # blank on continuation rows for same device
                net_name = ""
        brand.styled_table(
            doc,
            ["Device", "Network", "Interface", "Mode", "IP / Subnet", "Gateway", "DNS"],
            wan_rows,
            col_widths=[1.2, 0.9, 0.75, 0.65, 1.2, 1.1, 0.7],
        )

    for n in cfg.get("networks", []) or []:
        net_name = n.get("name") or n.get("slug") or "Network"
        brand.add_body(doc, net_name, bold=True)

        # ── L3 Firewall Rules ──────────────────────────────────────────────
        l3_rules = n.get("firewall_l3_rules") or []
        if l3_rules:
            brand.add_body(doc, "L3 Outbound Firewall Rules:", bold=False)
            rows = []
            for r in l3_rules:
                rows.append([
                    (r.get("policy") or "—").title(),
                    (r.get("protocol") or "Any").upper(),
                    _fmt_src(r),
                    _fmt_dst(r),
                    r.get("comment") or "—",
                ])
            brand.styled_table(
                doc,
                ["Policy", "Proto", "Source", "Destination", "Comment"],
                rows,
                col_widths=[0.6, 0.65, 1.5, 1.5, 2.2],
                status_col=0,
            )

        # ── Inbound Rules ──────────────────────────────────────────────────
        inbound = n.get("firewall_inbound_rules") or []
        real_inbound = [r for r in inbound if (r.get("policy") or "").lower() != "allow"
                        or (r.get("destCidr") or "Any") != "Any"]
        if real_inbound:
            brand.add_body(doc, "Inbound Firewall Rules:", bold=False)
            rows = [[
                (r.get("policy") or "—").title(),
                (r.get("protocol") or "Any").upper(),
                _fmt_src(r),
                _fmt_dst(r),
                r.get("comment") or "—",
            ] for r in real_inbound]
            brand.styled_table(
                doc,
                ["Policy", "Proto", "Source", "Destination", "Comment"],
                rows,
                col_widths=[0.6, 0.65, 1.5, 1.5, 2.2],
                status_col=0,
            )

        # ── Port Forwarding ────────────────────────────────────────────────
        pf_rules = n.get("port_forward_rules") or []
        if pf_rules:
            brand.add_body(doc, "Port Forwarding Rules:", bold=False)
            rows = [[
                r.get("name") or "—",
                (r.get("protocol") or "—").upper(),
                r.get("publicPort") or "—",
                r.get("lanIp") or "—",
                r.get("localPort") or "—",
            ] for r in pf_rules]
            brand.styled_table(
                doc,
                ["Name", "Proto", "Public Port", "LAN IP", "LAN Port"],
                rows,
                col_widths=[1.5, 0.65, 0.85, 1.5, 0.9],
            )

        # ── VLANs ──────────────────────────────────────────────────────────
        vlans = n.get("vlans") or []
        if vlans:
            brand.add_body(doc, "VLANs:", bold=False)
            rows = [[
                str(v.get("id") or "—"),
                v.get("name") or "—",
                v.get("subnet") or "—",
                v.get("applianceIp") or "—",
                (v.get("dhcpHandling") or "—").replace("Run a DHCP server", "DHCP server")
                                               .replace("Do not respond to DHCP requests", "Disabled"),
            ] for v in vlans]
            brand.styled_table(
                doc,
                ["ID", "Name", "Subnet", "Gateway", "DHCP"],
                rows,
                col_widths=[0.45, 1.5, 1.5, 1.25, 1.8],
            )

        # ── SSIDs ──────────────────────────────────────────────────────────
        ssids = n.get("ssids") or []
        if ssids:
            brand.add_body(doc, "Wireless SSIDs (enabled):", bold=False)
            rows = [[
                str(s.get("number") or "—"),
                s.get("name") or "—",
                (s.get("authMode") or "—").replace("8021x-meraki", "802.1X").replace("psk", "PSK"),
            ] for s in ssids]
            brand.styled_table(
                doc,
                ["#", "SSID Name", "Auth Mode"],
                rows,
                col_widths=[0.4, 3.0, 2.0],
            )

        # ── S2S VPN ────────────────────────────────────────────────────────
        vpn_mode = (n.get("s2s_vpn_mode") or "none").title()
        hubs = n.get("s2s_vpn_hubs") or []
        subnets = n.get("s2s_vpn_subnets") or []
        if vpn_mode.lower() != "none" or hubs or subnets:
            brand.add_body(doc, f"Site-to-Site VPN — Mode: {vpn_mode}", bold=False)
            if hubs:
                hub_rows = [[h.get("hubId") or "—", "Yes" if h.get("useDefaultRoute") else "No"]
                            for h in hubs]
                brand.styled_table(doc, ["Hub ID", "Default Route"], hub_rows,
                                   col_widths=[4.5, 1.5])
            if subnets:
                sub_rows = [[s.get("localSubnet") or "—", "Yes" if s.get("useVpn") else "No"]
                            for s in subnets]
                brand.styled_table(doc, ["Local Subnet", "In VPN"], sub_rows,
                                   col_widths=[4.5, 1.5])

        # ── Content Filtering ──────────────────────────────────────────────
        cf = n.get("content_filtering") or {}
        cats = cf.get("blocked_categories") or []
        patterns = cf.get("blocked_url_patterns") or []
        if cats or patterns:
            brand.add_body(doc, "Content Filtering:", bold=False)
            if cats:
                brand.styled_table(doc, ["Blocked URL Category"], [[c] for c in cats],
                                   col_widths=[6.0])
            if patterns:
                brand.styled_table(doc, ["Blocked URL Pattern"], [[p] for p in patterns],
                                   col_widths=[6.0])

        # ── Bandwidth Limits ───────────────────────────────────────────────
        bw_up   = n.get("bandwidth_limit_up", 0) or 0
        bw_down = n.get("bandwidth_limit_down", 0) or 0
        if bw_up or bw_down:
            def _bw(kbps):
                return f"{kbps // 1000:,} Mbps" if kbps >= 1000 else f"{kbps} Kbps"
            brand.add_body(
                doc,
                f"Global bandwidth limits — Upload: {_bw(bw_up)}  Download: {_bw(bw_down)}",
            )


def section_security_posture(doc, cfg: dict) -> None:
    brand.add_section_header(doc, "Security Posture")

    brand.add_body(
        doc,
        "Current configuration of the intrusion-prevention engine, "
        "anti-malware protection, content filtering, site-to-site VPN, and "
        "syslog forwarding per network.",
    )
    headers = ["Network", "IDS/IPS mode", "AMP mode", "URL cats blocked",
               "URL patterns blocked", "S2S VPN", "Syslog dests"]
    rows = []
    for n in cfg.get("networks", []) or []:
        intr = n.get("intrusion") or {}
        amp  = n.get("malware") or {}
        cfilt = n.get("content_filtering") or {}
        ids_mode = (intr.get("mode") or "—").title()
        amp_mode = (amp.get("mode") or "—").title()
        rows.append([
            n.get("name") or n.get("slug") or "—",
            ids_mode,
            amp_mode,
            fmt_int(cfilt.get("blocked_categories_count", 0)),
            fmt_int(cfilt.get("blocked_url_patterns_count", 0)),
            (n.get("s2s_vpn_mode") or "—").title(),
            fmt_int(n.get("syslog_destination_count", 0)),
        ])
    if not rows:
        rows = [["(no networks)", "—", "—", "0", "0", "—", "0"]]
    # status_col uses `IDS/IPS mode` column. brand.styled_table colors by
    # text content: "prevention" -> green via "active"-like match, "detection"
    # -> teal via "medium" match, "disabled" -> red.
    brand.styled_table(doc, headers, rows, col_widths=[1.5, 0.9, 0.75, 0.85, 0.9, 0.7, 0.65],
                       status_col=1)


def section_config_changes(doc, chg: dict) -> None:
    brand.add_section_header(doc, "Configuration Changes")

    total = chg.get("total", 0)
    n_admins = len(chg.get("by_admin") or [])
    n_networks = len(chg.get("by_network") or [])

    brand.add_metric_card_row(doc, [
        (fmt_int(total),     "Total changes",      brand.CORE_BLUE if total == 0 else brand.CORE_ORANGE),
        (fmt_int(n_admins),  "Admins active",      brand.CORE_BLUE),
        (fmt_int(n_networks),"Networks affected",  brand.CORE_BLUE),
    ])

    if total == 0:
        brand.add_callout_box(
            doc,
            "No configuration changes were recorded via the Meraki Dashboard "
            "this month. The environment is stable and the documented baseline "
            "is intact.",
            accent_hex=brand.GREEN_HEX, bg_hex="EAF7EE",
        )
        return

    brand.add_body(
        doc,
        f"{fmt_int(total)} Dashboard configuration changes were recorded "
        f"across {fmt_int(n_networks)} network(s) by {fmt_int(n_admins)} "
        f"administrator(s). The tables below identify who changed what and "
        f"provide the full before/after detail for compliance review.",
    )

    if chg.get("by_admin"):
        brand.add_body(doc, "Changes by administrator:", bold=True)
        rows = [[e["admin"], fmt_int(e["count"])]
                for e in (chg["by_admin"] or [])]
        brand.styled_table(doc, ["Administrator", "Changes"], rows,
                           col_widths=[4.5, 1.5])

    if chg.get("by_network"):
        brand.add_body(doc, "Changes by network:", bold=True)
        rows = [[e["network"], fmt_int(e["count"])]
                for e in (chg["by_network"] or [])]
        brand.styled_table(doc, ["Network", "Changes"], rows,
                           col_widths=[4.5, 1.5])

    if chg.get("by_page"):
        brand.add_body(doc, "Changes by configuration area:", bold=True)
        rows = [[e["page"], fmt_int(e["count"])]
                for e in (chg["by_page"] or [])]
        brand.styled_table(doc, ["Configuration area", "Changes"], rows,
                           col_widths=[4.5, 1.5])

    recent = chg.get("recent") or []
    if recent:
        brand.add_body(doc, f"Change detail (most recent {len(recent)}):",
                       bold=True)
        def _trunc(v, n=80):
            s = str(v) if v is not None else "—"
            return s if len(s) <= n else s[:n - 1] + "…"

        rows = []
        for c in recent:
            ts_raw = c.get("ts") or ""
            ts_short = ts_raw[:16].replace("T", " ") if ts_raw else "—"
            admin = c.get("adminEmail") or c.get("adminName") or "—"
            area = c.get("page") or "—"
            label = c.get("label") or ""
            area_label = f"{area}: {label}" if label else area
            rows.append([ts_short, admin, area_label,
                         _trunc(c.get("oldValue")),
                         _trunc(c.get("newValue"))])
        # 5 columns, total width 6.4" — fits within the 6.5" usable page
        brand.styled_table(
            doc,
            ["Date / Time", "Administrator", "Area: Setting", "Before", "After"],
            rows,
            col_widths=[1.1, 1.5, 1.5, 1.1, 1.2],
        )


def section_security_events(doc, sec: dict) -> None:
    brand.add_section_header(doc, "IDS/IPS & AMP Events")

    total = sec.get("total", 0)
    days = sec.get("days_with_events", 0)
    brand.add_body(
        doc,
        f"Total IDS/IPS and AMP events captured during the reporting period: "
        f"{fmt_int(total)} across {fmt_int(days)} days with activity.",
    )

    if total == 0:
        brand.add_callout_box(
            doc,
            "No security events were recorded during this period. This indicates "
            "either a clean network or that the IDS/IPS engine is in detection-only "
            "mode with no triggered signatures. Review the Security Posture section "
            "to confirm the intended configuration.",
            accent_hex=brand.GREEN_HEX, bg_hex="EAF7EE",
        )
        return

    if sec.get("by_blocked"):
        brand.add_body(doc, "Blocked vs. alerted:", bold=True)
        rows = [[k.title(), fmt_int(v)] for k, v in (sec["by_blocked"] or {}).items()]
        brand.styled_table(doc, ["Action", "Events"], rows, col_widths=[3.0, 2.0])

    if sec.get("by_priority"):
        brand.add_body(doc, "By priority / severity:", bold=True)
        rows = sorted((sec["by_priority"] or {}).items(), key=lambda x: x[0])
        brand.styled_table(doc, ["Priority", "Events"],
                           [[k, fmt_int(v)] for k, v in rows],
                           col_widths=[3.0, 2.0])

    if sec.get("by_signature_top"):
        brand.add_body(doc, "Top signatures:", bold=True)
        rows = [[s, fmt_int(c)] for s, c in (sec["by_signature_top"] or [])]
        brand.styled_table(doc, ["Signature", "Hits"], rows, col_widths=[5.0, 1.0])

    if sec.get("top_sources"):
        brand.add_body(doc, "Top source IPs:", bold=True)
        rows = [[s, fmt_int(c)] for s, c in (sec["top_sources"] or [])]
        brand.styled_table(doc, ["Source", "Hits"], rows, col_widths=[4.0, 2.0])

    if sec.get("top_destinations"):
        brand.add_body(doc, "Top destination IPs:", bold=True)
        rows = [[s, fmt_int(c)] for s, c in (sec["top_destinations"] or [])]
        brand.styled_table(doc, ["Destination", "Hits"], rows, col_widths=[4.0, 2.0])


def section_activity(doc, net: dict) -> None:
    brand.add_section_header(doc, "Firewall & Network Activity")

    total = net.get("total", 0)
    n_active = net.get("networks_with_events", 0)
    brand.add_body(
        doc,
        f"Total firewall, VPN, DHCP, and connectivity events: {fmt_int(total)} "
        f"across {fmt_int(n_active)} active networks.",
    )

    if total == 0:
        brand.add_body(
            doc,
            "No appliance-layer activity events were recorded for this period. "
            "Wireless-only networks (no MX appliance) and dormant sites typically "
            "show zero events here — verify the network topology in the inventory "
            "above if this is unexpected.",
        )
        return

    if net.get("by_type_top"):
        brand.add_body(doc, "Top event types:", bold=True)
        rows = [[t, fmt_int(c)] for t, c in (net["by_type_top"] or [])]
        brand.styled_table(doc, ["Event type", "Count"], rows, col_widths=[4.5, 1.5])

    if net.get("by_category"):
        brand.add_body(doc, "By category:", bold=True)
        rows = sorted((net["by_category"] or {}).items(), key=lambda x: -x[1])
        brand.styled_table(doc, ["Category", "Count"],
                           [[k, fmt_int(v)] for k, v in rows],
                           col_widths=[4.5, 1.5])

    if net.get("by_network"):
        brand.add_body(doc, "Per-network rollup:", bold=True)
        rows = []
        for slug, info in sorted((net["by_network"] or {}).items(),
                                 key=lambda kv: -kv[1]["total"]):
            top_types = ", ".join(f"{t} ({fmt_int(c)})" for t, c in info["by_type_top"][:3])
            rows.append([info["name"] or slug, fmt_int(info["total"]), top_types])
        brand.styled_table(doc, ["Network", "Events", "Top event types"], rows,
                           col_widths=[2.0, 1.0, 3.5])


def section_daily_trend(doc, sec: dict, net: dict) -> None:
    brand.add_section_header(doc, "Daily Trend")

    brand.add_body(
        doc,
        "Day-by-day count of intrusion-prevention events versus appliance-layer "
        "activity events. Use this to spot anomalies — sudden spikes typically "
        "correlate with outbound malware activity, port scans, or VPN tunnel "
        "flapping.",
    )

    sec_by_day = {x["date"]: x["count"] for x in sec.get("daily_counts", [])}
    net_by_day = {x["date"]: x["count"] for x in net.get("daily_counts", [])}
    days = sorted(set(sec_by_day) | set(net_by_day))
    if not days:
        brand.add_body(doc, "No daily data available for this period.")
        return
    rows = [[d, fmt_int(sec_by_day.get(d, 0)), fmt_int(net_by_day.get(d, 0))]
            for d in days]
    brand.styled_table(doc, ["Date", "Security events", "Activity events"],
                       rows, col_widths=[2.5, 1.75, 1.75])


def section_what_technijian_did(doc, payload: dict) -> None:
    brand.add_section_header(doc, "What Technijian Did For You")

    brand.add_body(
        doc,
        "Throughout the reporting period the Technijian network operations team "
        "performed the following ongoing services for your Meraki environment:",
    )

    bullets = [
        ("24x7 monitoring: ", "continuous health checks against every Meraki appliance, switch, and access point in your dashboard."),
        ("Threat intelligence: ", "Cisco's Talos and AMP feeds are kept current; signature definitions update automatically as Cisco publishes them."),
        ("Configuration drift detection: ", "daily snapshots of firewall rules, VLANs, content filtering, IDS/IPS settings, and VPN configuration; deviations from the documented baseline are reviewed."),
        ("Incident review: ", "high-priority security alerts are triaged within the on-call SLA and ticketed in the Technijian Client Portal."),
        ("Monthly reporting: ", "this document — every line item is sourced from the Meraki Dashboard API and verified through a structural proofreader before delivery."),
    ]
    for prefix, text in bullets:
        brand.add_bullet(doc, text, bold_prefix=prefix)


def section_recommendations(doc, payload: dict) -> None:
    brand.add_section_header(doc, "Recommendations")

    cfg = payload["configuration"]
    sec = payload["security_events"]
    chg = payload.get("config_changes") or {}

    detect_only_networks = []
    no_amp_networks = []
    no_syslog_networks = []
    for n in cfg.get("networks", []) or []:
        intr_mode = ((n.get("intrusion") or {}).get("mode") or "").lower()
        amp_mode = ((n.get("malware") or {}).get("mode") or "").lower()
        if intr_mode and intr_mode != "prevention":
            detect_only_networks.append(n.get("name") or n.get("slug"))
        if amp_mode and amp_mode != "enabled":
            no_amp_networks.append(n.get("name") or n.get("slug"))
        if (n.get("syslog_destination_count") or 0) == 0 and "appliance" in (n.get("productTypes") or []):
            no_syslog_networks.append(n.get("name") or n.get("slug"))

    recs: list[tuple[str, str]] = []
    if detect_only_networks:
        recs.append((
            "Move IDS to prevention mode: ",
            f"the following network(s) currently run IDS/IPS in detection-only "
            f"mode: {', '.join(detect_only_networks)}. We recommend a "
            f"two-week prevention-mode trial after reviewing this period's "
            f"signature distribution to confirm no false-positive risk."
        ))
    if no_amp_networks:
        recs.append((
            "Enable AMP: ",
            f"advanced-malware-protection is not fully enabled on "
            f"{', '.join(no_amp_networks)}. AMP adds file-reputation lookups "
            f"and retrospective detection on top of signature-based IDS — "
            f"recommended for any network handling email or web traffic."
        ))
    if no_syslog_networks:
        recs.append((
            "Forward syslog: ",
            f"appliances on {', '.join(no_syslog_networks)} are not "
            f"configured to forward syslog. Pointing these at the Technijian "
            f"central syslog receiver lets us perform per-signature historical "
            f"analysis beyond the Meraki API's 31-day window."
        ))
    if sec.get("total", 0) == 0:
        recs.append((
            "Validate detection coverage: ",
            "zero security events for the period is unusual unless the network "
            "is genuinely low-traffic. Consider running a controlled test "
            "(e.g., EICAR file download from an isolated workstation) to "
            "confirm the IDS/IPS pipeline end-to-end."
        ))
    if chg.get("total", 0) > 0:
        recs.append((
            "Review configuration changes: ",
            f"{fmt_int(chg.get('total', 0))} Dashboard configuration change(s) "
            "were recorded this period. See the Configuration Changes section "
            "for full before/after detail. Verify each change was authorized "
            "and documented in your change-management log.",
        ))
    if not recs:
        recs.append((
            "Stay the course: ",
            "all monitored networks are configured per the recommended baseline "
            "and event volumes are within expected ranges. No configuration "
            "changes are required this period."
        ))

    for prefix, text in recs:
        brand.add_bullet(doc, text, bold_prefix=prefix)


def section_about(doc, payload: dict) -> None:
    brand.add_section_header(doc, "About This Report")

    brand.add_body(
        doc,
        "This report is generated automatically from the Cisco Meraki Dashboard "
        "API by Technijian's annual-client-review pipeline. Every figure shown "
        "is sourced from the API at report-generation time; no manual data "
        "entry is involved.",
    )
    brand.add_body(
        doc,
        f"Report generated {datetime.now().strftime('%Y-%m-%d %H:%M %Z').strip()} "
        f"for client code '{payload['client_code']}'. Configuration snapshot taken "
        f"{payload['configuration'].get('snapshot_at') or 'unknown'}.",
    )
    brand.add_body(
        doc,
        "For questions about any item in this report, or to request a different "
        "reporting cadence, contact your Technijian account manager or open a "
        "ticket via the Client Portal.",
    )


# ---------------------------------------------------------------------------
# Build orchestration
# ---------------------------------------------------------------------------

def build_report(payload: dict, out_path: Path) -> None:
    org_name = (payload["configuration"].get("org") or payload["client_code"]).strip()

    doc = brand.new_branded_document()
    render_cover_page(doc, org_name, payload["month"])

    section_executive_summary(doc, payload)
    section_inventory(doc, payload["configuration"])
    section_firewall_config(doc, payload["configuration"])
    section_security_posture(doc, payload["configuration"])
    section_config_changes(doc, payload.get("config_changes") or {})
    section_security_events(doc, payload["security_events"])
    section_activity(doc, payload["network_events"])
    section_daily_trend(doc, payload["security_events"], payload["network_events"])
    section_what_technijian_did(doc, payload)
    section_recommendations(doc, payload)
    section_about(doc, payload)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))


def run_proofreader(generated: list[Path]) -> int:
    if not generated:
        return 0
    if not PROOFREADER.exists():
        print(f"\n[proofread] WARNING: proofreader missing at {PROOFREADER} — skipping.")
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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--month")
    p.add_argument("--from", dest="from_month")
    p.add_argument("--to",   dest="to_month")
    p.add_argument("--only")
    p.add_argument("--skip")
    p.add_argument("--root", default=str(CLIENTS_ROOT))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    only = {s.strip().lower() for s in (args.only or "").split(",") if s.strip()}
    skip = {s.strip().lower() for s in (args.skip or "").split(",") if s.strip()}

    generated: list[Path] = []
    for client_dir in sorted([d for d in root.iterdir() if d.is_dir() and not d.name.startswith("_")]):
        meraki_dir = client_dir / "meraki"
        if not meraki_dir.exists():
            continue
        if only and client_dir.name not in only:
            continue
        if client_dir.name in skip:
            continue
        monthly_dir = meraki_dir / "monthly"
        if not monthly_dir.exists():
            continue
        for f in sorted(monthly_dir.glob("*.json")):
            month = f.stem
            if args.month and month != args.month:
                continue
            if args.from_month and month < args.from_month:
                continue
            if args.to_month and month > args.to_month:
                continue
            payload = json.loads(f.read_text(encoding="utf-8"))
            org_label = (payload["configuration"].get("org") or client_dir.name).strip()
            safe_label = "".join(c if c.isalnum() or c in " -_" else "_" for c in org_label)
            out = meraki_dir / "reports" / f"{safe_label} - Meraki Monthly Activity - {month}.docx"
            build_report(payload, out)
            generated.append(out)
            try:
                rel = out.relative_to(root)
            except ValueError:
                rel = out
            print(f"  [{client_dir.name}] {month} -> {rel}")
    print(f"\nGenerated {len(generated)} Word report(s)")

    rc = run_proofreader(generated)
    return rc


if __name__ == "__main__":
    sys.exit(main())
