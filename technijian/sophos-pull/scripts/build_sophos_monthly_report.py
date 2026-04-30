"""Build branded Sophos Central monthly activity report per client.

Reads all clients/<code>/sophos/<YYYY-MM-*>/alerts.json + firewalls.json
for the target month, aggregates the data, and produces a branded DOCX.

Output: clients/<code>/sophos/reports/<CODE> - Sophos Monthly Activity - YYYY-MM.docx

Usage:
    python build_sophos_monthly_report.py                       # prior month, all clients
    python build_sophos_monthly_report.py --month 2026-04
    python build_sophos_monthly_report.py --only BWH,KSS
    python build_sophos_monthly_report.py --dry-run             # list targets, no write
"""
from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPELINE_ROOT = HERE.parent
REPO = PIPELINE_ROOT.parent.parent
CLIENTS_ROOT = REPO / "clients"
SHARED = REPO / "technijian" / "shared" / "scripts"
PROOFREADER = SHARED / "proofread_docx.py"

sys.path.insert(0, str(SHARED))
import _brand as brand  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _html_decode(s: str) -> str:
    return html.unescape(s or "")


def prior_month(ref: datetime | None = None) -> str:
    ref = ref or datetime.now(timezone.utc)
    if ref.month == 1:
        return f"{ref.year - 1}-12"
    return f"{ref.year}-{ref.month - 1:02d}"


def load_month_data(code: str, month: str) -> dict:
    """Aggregate all daily sophos snapshots for the given month."""
    client_dir = CLIENTS_ROOT / code.lower()
    sophos_dir = client_dir / "sophos"
    if not sophos_dir.exists():
        return {}

    prefix = month  # "2026-04"
    date_dirs = sorted(
        p for p in sophos_dir.iterdir()
        if p.is_dir() and p.name.startswith(prefix)
    )
    if not date_dirs:
        return {}

    all_alerts: list[dict] = []
    all_events: list[dict] = []
    fw_snapshot: list[dict] = []
    seen_alert_ids: set[str] = set()

    for d in date_dirs:
        a_path = d / "alerts.json"
        if a_path.exists():
            try:
                for a in json.loads(a_path.read_text(encoding="utf-8")):
                    if a.get("id") and a["id"] not in seen_alert_ids:
                        seen_alert_ids.add(a["id"])
                        all_alerts.append(a)
            except Exception:
                pass
        e_path = d / "events.json"
        if e_path.exists():
            try:
                all_events.extend(json.loads(e_path.read_text(encoding="utf-8")))
            except Exception:
                pass

    # Use most recent firewall snapshot
    if date_dirs:
        fw_path = date_dirs[-1] / "firewalls.json"
        if fw_path.exists():
            try:
                fw_snapshot = json.loads(fw_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    return {
        "alerts": all_alerts,
        "events": all_events,
        "firewalls": fw_snapshot,
        "date_range": (date_dirs[0].name, date_dirs[-1].name) if date_dirs else ("—", "—"),
        "days_with_data": len(date_dirs),
    }


def load_meta(code: str) -> dict:
    p = CLIENTS_ROOT / code.lower() / "_meta.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"LocationCode": code, "Location_Name": code}


# ---------------------------------------------------------------------------
# Alert analysis helpers
# ---------------------------------------------------------------------------

def alert_type_short(atype: str) -> str:
    for prefix in ("Event::Firewall::", "Event::Other::", "Event::Endpoint::"):
        if atype.startswith(prefix):
            return atype[len(prefix):]
    return atype


ALERT_TYPE_FRIENDLY: dict[str, str] = {
    "LostConnectionToSophosCentral": "Lost Connection to Sophos Central",
    "Reconnected": "Reconnected to Sophos Central",
    "FirewallGatewayUp": "WAN Gateway Restored",
    "FirewallGatewayDown": "WAN Gateway Down",
    "FirewallFirmwareUpdateSuccessfullyFinished": "Firmware Update Completed",
    "FirewallFirmwareUpgradeFailed": "Firmware Upgrade Failed",
    "NotProtected": "Endpoint Not Protected",
    "UpdateFailed": "Endpoint Update Failed",
}


def friendly_type(atype: str) -> str:
    short = alert_type_short(atype)
    return ALERT_TYPE_FRIENDLY.get(short, short)


def count_by(items: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for item in items:
        out[item.get(key, "unknown")] += 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def connectivity_summary(alerts: list[dict]) -> str:
    lost = sum(1 for a in alerts if "LostConnection" in (a.get("type") or ""))
    reconnected = sum(1 for a in alerts if "Reconnected" in (a.get("type") or ""))
    gw_down = sum(1 for a in alerts if "GatewayDown" in (a.get("type") or ""))
    gw_up = sum(1 for a in alerts if "GatewayUp" in (a.get("type") or ""))

    parts = []
    if lost:
        parts.append(f"{lost} disconnect event(s)")
    if reconnected:
        parts.append(f"{reconnected} reconnect event(s)")
    if gw_down:
        parts.append(f"{gw_down} gateway-down event(s)")
    if gw_up:
        parts.append(f"{gw_up} gateway-restored event(s)")
    if not parts:
        return "No connectivity events recorded this month."
    paired = min(lost, reconnected)
    unresolved = lost - reconnected
    summary = ", ".join(parts) + "."
    if unresolved > 0:
        summary += f" ({unresolved} disconnect(s) may still be open.)"
    elif paired == lost and lost > 0:
        summary += " All disconnects self-resolved (reconnected)."
    return summary


# ---------------------------------------------------------------------------
# Firmware helpers
# ---------------------------------------------------------------------------

def fw_firmware_status(firewalls: list[dict]) -> list[dict]:
    rows = []
    for fw in firewalls:
        status = fw.get("status") or {}
        ips = fw.get("externalIpv4Addresses") or []
        rows.append({
            "hostname": fw.get("hostname") or fw.get("name") or "—",
            "model": (fw.get("model") or "").split("_SFOS")[0],
            "firmware": (fw.get("firmwareVersion") or "").split("_")[-1],
            "wan_ip": ips[0] if ips else "—",
            "connected": "Connected" if (status.get("connected") if isinstance(status, dict) else fw.get("connected")) else "Offline",
            "serial": fw.get("serialNumber") or "—",
        })
    return rows


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

STATUS_COLOR = {
    "Connected": brand.GREEN,
    "Offline": brand.RED,
    "high": brand.RED,
    "low": brand.TEAL,
    "medium": brand.CORE_ORANGE,
}


def build_report(code: str, month: str, data: dict, dry_run: bool) -> Path | None:
    meta = load_meta(code)
    location_name = meta.get("Location_Name") or code
    month_dt = datetime.strptime(month, "%Y-%m")
    month_label = month_dt.strftime("%B %Y")

    alerts = data.get("alerts", [])
    events = data.get("events", [])
    firewalls = data.get("firewalls", [])
    days_with_data = data.get("days_with_data", 0)
    date_range = data.get("date_range", ("—", "—"))

    high_alerts = [a for a in alerts if a.get("severity") == "high"]
    low_alerts = [a for a in alerts if a.get("severity") != "high"]
    connectivity_events = [a for a in alerts
                           if (a.get("type") or "").startswith("Event::Firewall::")]
    fw_rows = fw_firmware_status(firewalls)

    out_dir = CLIENTS_ROOT / code.lower() / "sophos" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{code} - Sophos Monthly Activity - {month}.docx"

    if dry_run:
        print(f"  DRY  {code:<8s} alerts={len(alerts)} fws={len(firewalls)} -> {out_path.name}")
        return None

    doc = brand.new_branded_document()
    brand.render_cover(
        doc,
        title=f"{location_name}",
        subtitle=f"Sophos Central — Monthly Activity Report\n{month_label}",
        footer_note="Confidential — prepared by Technijian, Inc.",
        date_text=month_label,
    )

    # Executive Summary
    brand.add_section_header(doc, "Executive Summary")
    conn_note = connectivity_summary(alerts)
    fw_count = len(firewalls)
    fw_online = sum(1 for fw in firewalls
                    if (fw.get("status") or {}).get("connected") or fw.get("connected"))
    fw_updates = sum(1 for a in alerts
                     if "FirmwareUpdate" in (a.get("type") or ""))

    exec_text = (
        f"During {month_label}, Technijian monitored {fw_count} Sophos XGS firewall(s) "
        f"for {location_name} via Sophos Central. "
        f"{fw_online} of {fw_count} firewall(s) were connected at month end. "
        f"A total of {len(alerts)} alerts were recorded: "
        f"{len(high_alerts)} high-severity and {len(low_alerts)} low-severity. "
        f"Data was captured across {days_with_data} pull(s) between "
        f"{date_range[0]} and {date_range[1]}. "
    )
    if fw_updates:
        exec_text += f"{fw_updates} firmware update(s) completed successfully during this period. "
    exec_text += conn_note

    brand.add_body(doc, exec_text)

    # Metric cards
    brand.add_metric_card_row(doc, [
        (str(fw_count), "Firewalls Managed", brand.CORE_BLUE),
        (str(len(high_alerts)), "High Alerts", brand.RED if high_alerts else brand.GREEN),
        (str(len(low_alerts)), "Low Alerts", brand.CORE_ORANGE),
        (str(fw_updates), "FW Updates", brand.GREEN),
    ])

    # Firewall Inventory
    brand.add_section_header(doc, "Firewall Inventory")
    if fw_rows:
        fw_headers = ["Hostname", "Model", "Firmware", "WAN IP", "Serial", "Status"]
        fw_table_rows = [
            [r["hostname"], r["model"], r["firmware"], r["wan_ip"], r["serial"], r["connected"]]
            for r in fw_rows
        ]
        brand.styled_table(
            doc, fw_headers, fw_table_rows,
            col_widths=[1.2, 1.2, 1.0, 1.2, 1.2, 0.7],
            status_col=5,
        )
        for r in fw_rows:
            if r["connected"] == "Offline":
                brand.add_callout_box(
                    doc,
                    f"WARNING: {r['hostname']} (serial {r['serial']}) shows as Offline in "
                    f"Sophos Central. Please verify connectivity and check the open CP ticket."
                )
    else:
        brand.add_body(doc, "No firewall inventory data available for this month.")

    # Alert Summary
    brand.add_section_header(doc, "Alert Summary")
    if alerts:
        by_type = count_by(alerts, "type")
        alert_headers = ["Alert Type", "Severity", "Count"]
        alert_rows = []
        for atype, cnt in sorted(by_type.items(), key=lambda kv: -kv[1]):
            sev_list = [a.get("severity", "low") for a in alerts if a.get("type") == atype]
            top_sev = "high" if "high" in sev_list else "low"
            alert_rows.append([friendly_type(atype), top_sev.capitalize(), str(cnt)])
        brand.styled_table(
            doc, alert_headers, alert_rows,
            col_widths=[4.0, 1.5, 1.0],
            status_col=1,
        )
    else:
        brand.add_callout_box(doc, "No alerts recorded in Sophos Central this month.")

    # Connectivity Events
    brand.add_section_header(doc, "Connectivity Events")
    lost_events = [a for a in alerts if "LostConnection" in (a.get("type") or "")]
    reconn_events = [a for a in alerts if "Reconnected" in (a.get("type") or "")]
    gw_events = [a for a in alerts if "Gateway" in (a.get("type") or "")]

    if lost_events or gw_events:
        brand.add_body(
            doc,
            f"The firewall experienced {len(lost_events)} Sophos Central disconnect event(s) "
            f"and {len(gw_events)} gateway event(s) this month. "
        )
        brand.add_body(doc, conn_note)

        if lost_events:
            conn_headers = ["Event", "Severity", "Raised At", "Device"]
            conn_rows = []
            for a in sorted(lost_events + reconn_events, key=lambda x: x.get("raisedAt") or ""):
                raised = (a.get("raisedAt") or "")[:16].replace("T", " ")
                device = (a.get("managedAgent") or {}).get("name") or "—"
                conn_rows.append([
                    friendly_type(a.get("type") or ""),
                    (a.get("severity") or "low").capitalize(),
                    raised,
                    device,
                ])
            if len(conn_rows) <= 20:
                brand.styled_table(
                    doc, conn_headers, conn_rows,
                    col_widths=[2.5, 0.9, 1.55, 1.55],
                    status_col=1,
                )
            else:
                brand.add_body(
                    doc,
                    f"({len(conn_rows)} connectivity events recorded — see Sophos Central "
                    f"Log Viewer for the full list.)"
                )
    else:
        brand.add_callout_box(doc, "No connectivity disruptions recorded this month.")

    # Firmware Updates
    fw_update_alerts = [a for a in alerts if "Firmware" in (a.get("type") or "")]
    if fw_update_alerts:
        brand.add_section_header(doc, "Firmware Updates")
        fu_headers = ["Device", "Event", "Raised At"]
        fu_rows = []
        for a in sorted(fw_update_alerts, key=lambda x: x.get("raisedAt") or ""):
            raised = (a.get("raisedAt") or "")[:16].replace("T", " ")
            device = (a.get("managedAgent") or {}).get("name") or "—"
            fu_rows.append([device, friendly_type(a.get("type") or ""), raised])
        brand.styled_table(doc, fu_headers, fu_rows, col_widths=[1.8, 2.9, 1.8])

    # Recommendations
    brand.add_section_header(doc, "Recommendations")
    recs: list[str] = []
    offline_fws = [r for r in fw_rows if r["connected"] == "Offline"]
    if offline_fws:
        names = ", ".join(r["hostname"] for r in offline_fws)
        recs.append(f"Investigate offline firewall(s): {names}. Verify ISP connectivity and re-register with Sophos Central if needed.")
    if len(lost_events) >= 3:
        recs.append(f"{len(lost_events)} Sophos Central disconnect events recorded. Review ISP line quality and consider opening a trouble ticket with the ISP if the pattern continues.")
    if len(lost_events) >= 1 and len(lost_events) == len(reconn_events):
        recs.append("All disconnect events self-resolved (firewall reconnected automatically). Monitor for recurrence next month.")
    old_fw = [r for r in fw_rows if r["firmware"] and "20.0" in r["firmware"]]
    if old_fw:
        names = ", ".join(r["hostname"] for r in old_fw)
        recs.append(f"Firewall(s) running SFOS 20.x ({names}) are on an older firmware branch. Plan upgrade to SFOS 21.5 or 22.0 during a maintenance window.")
    if not recs:
        recs.append("No critical issues identified this month. Continue regular monitoring via Sophos Central.")

    for rec in recs:
        brand.add_bullet(doc, rec)

    # About This Report
    brand.add_section_header(doc, "About This Report")
    brand.add_body(
        doc,
        f"This report was automatically generated by Technijian's Sophos Central monitoring "
        f"pipeline on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}. Data is sourced from "
        f"the Sophos Central Partner API. Firewall IPS/IDS signature-level events require "
        f"syslog forwarding to the Technijian DC collector and are not included in this report. "
        f"For questions, contact Technijian support at support@technijian.com."
    )

    doc.save(str(out_path))
    print(f"  wrote {code:<8s} alerts={len(alerts)} fws={len(firewalls)} -> {out_path.name}")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build Sophos monthly branded DOCX per client.")
    ap.add_argument("--month", help="YYYY-MM (default: prior calendar month)")
    ap.add_argument("--only", help="comma-separated LocationCodes")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    month = args.month or prior_month()
    only = None
    if args.only:
        only = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    print(f"[{datetime.now():%H:%M:%S}] Sophos monthly report builder  month={month}")

    # Find all clients with sophos data for this month
    targets: list[str] = []
    for client_dir in sorted(CLIENTS_ROOT.iterdir()):
        if not client_dir.is_dir():
            continue
        code = client_dir.name.upper()
        if only and code not in only:
            continue
        sophos_dir = client_dir / "sophos"
        if not sophos_dir.exists():
            continue
        has_data = any(
            p.is_dir() and p.name.startswith(month)
            for p in sophos_dir.iterdir()
        )
        if has_data:
            targets.append(client_dir.name.upper())

    print(f"  clients with {month} data: {len(targets)}")
    if not targets:
        print("  Nothing to build. Run pull_sophos_daily.py first.")
        return 0

    generated: list[Path] = []
    for code in targets:
        data = load_month_data(code, month)
        if not data:
            print(f"  SKIP {code:<8s} (no data loaded)")
            continue
        p = build_report(code, month, data, args.dry_run)
        if p:
            generated.append(p)

    if generated and not args.dry_run and PROOFREADER.exists():
        print(f"\n[{datetime.now():%H:%M:%S}] proofreading {len(generated)} reports...")
        expected = "Executive Summary,Firewall Inventory,Alert Summary,Connectivity Events,Recommendations,About This Report"
        rc = subprocess.run(
            [sys.executable, str(PROOFREADER),
             "--sections", expected, "--quiet"]
            + [str(p) for p in generated if p.exists()]
        ).returncode
        if rc != 0:
            print("[proofread] FAILED — one or more reports did not pass the gate.")
            return rc
        print("[proofread] all reports passed.")

    print(f"\n[{datetime.now():%H:%M:%S}] DONE — {len(generated)} report(s) written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
