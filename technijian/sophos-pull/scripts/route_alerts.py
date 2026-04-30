"""Route open Sophos alerts -> CP ticket creation + reminder emails.

Runs after pull_sophos_daily.py each hour. Reads the latest pull's per-tenant
alerts.json, groups all alerts per client into ONE consolidated ticket
(instead of one ticket per alert), dedups against state/alert-tickets.json,
and decides one of:

    NEW     - Client not in state, or no open ticket yet
              -> create ONE CP ticket per client summarising ALL alerts
              -> ticket body includes full actionable resolution steps per type
    AGING   - Open ticket already exists, last reminder > threshold
              -> send reminder email to support@technijian.com
    QUIET   - Open ticket exists, reminder recent
              -> no action
    RESOLVED- All alerts for a client gone from the feed
              -> mark resolved_at, no further action

Default mode is REPORT (dry-run) — writes routing-plan.json without calling
the CP API or sending email. Pass --apply to actually create tickets.

Usage:
    python route_alerts.py                              # report mode
    python route_alerts.py --apply                      # create tickets + email
    python route_alerts.py --apply --no-tickets         # emails only
    python route_alerts.py --reminder-hours 12
    python route_alerts.py --to support@technijian.com
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPELINE_ROOT = HERE.parent
REPO = PIPELINE_ROOT.parent.parent
CLIENTS_ROOT = REPO / "clients"
STATE_DIR = PIPELINE_ROOT / "state"
ALERT_STATE_FILE = STATE_DIR / "alert-tickets.json"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "scripts" / "clientportal"))
import cp_tickets  # noqa: E402
import email_support  # noqa: E402


# ---------------------------------------------------------------------------
# Actionable resolution steps per Sophos alert type
# ---------------------------------------------------------------------------

RESOLUTION_STEPS: dict[str, str] = {
    "Event::Firewall::LostConnectionToSophosCentral": """\
WHAT HAPPENED
The Sophos XGS firewall lost its management connection to Sophos Central,
meaning the firewall could not sync policies, receive updates, or send telemetry
during the outage window.

RESOLUTION STEPS
1. Log in to Sophos Central (central.sophos.com) and check the current firewall status.

2. If the firewall is CURRENTLY OFFLINE (red dot in Central):
   a. Try pinging the firewall WAN IP from outside the network (use a mobile hotspot
      or ask the client to confirm local internet is up).
   b. If unreachable: check physical connections — WAN port → ISP modem/router → ONT/demarcation.
   c. If reachable: log into the firewall admin console via LAN (https://<LAN-IP>:4444).
      Go to Admin > Sophos Central and click "Re-register" or "Reconnect."
   d. Go to System > Diagnostics > Connectivity > run the Connection Test.
   e. Check System > Logs > Firewall Log for WAN interface errors.

3. If the firewall is CURRENTLY ONLINE (issue resolved itself — intermittent):
   a. Review the frequency: if this is the Nth disconnect in the last 30 days,
      escalate to an ISP trouble ticket with the outage timestamps from this ticket.
   b. In Sophos Central > Log Viewer > System, filter for "Central" to see all
      disconnect/reconnect events with exact timestamps.
   c. Check whether the disconnect coincides with a failover event (SD-WAN gateway
      health check failure) — if so, investigate the primary WAN circuit quality.
   d. Ask the client if they notice internet drops at the same times.

4. Close this ticket once the firewall has been online in Central for 48 hours
   with no further disconnects.""",

    "Event::Firewall::FirewallGatewayUp": """\
WHAT HAPPENED
A WAN gateway on the firewall came back online after being down (gateway health
check failed, then recovered). This may indicate an ISP blip or a WAN failover/failback.

RESOLUTION STEPS
1. Log in to Sophos Central and confirm all gateways are currently UP (green).
2. In the firewall admin console (System > SD-WAN > Gateway) review which gateway
   went down and for how long.
3. If this was a PRIMARY → SECONDARY failover:
   a. Confirm primary WAN is now restored and traffic is back on the primary circuit.
   b. Verify the SD-WAN failover/failback policy is configured with the correct
      health-check intervals and thresholds (Admin > SD-WAN > Profiles).
   c. Contact the ISP for the affected primary circuit if the cause is unknown.
4. If recurring (>2 gateway-down events per week): open an ISP trouble ticket
   citing the timestamps from Sophos Central logs.
5. No further action required if this is a single, isolated, self-resolved event.""",

    "Event::Firewall::Reconnected": """\
INFORMATIONAL — Firewall connection to Sophos Central restored.
Verify in Sophos Central that the firewall shows as Connected and no additional
alerts are pending. Pair this with any LostConnection alerts in this ticket to
understand the total outage window.""",

    "Event::Firewall::FirewallGatewayDown": """\
WHAT HAPPENED
A WAN gateway on the firewall has gone DOWN. Traffic may have failed over to a
secondary circuit, or internet access may be disrupted if no failover is configured.

RESOLUTION STEPS
1. Immediately check whether the client has internet access (call the client if needed).
2. Log in to Sophos Central and confirm whether the gateway is still down.
3. If still down:
   a. Check physical WAN connections (modem, cable, ONT).
   b. Call the ISP and open a trouble ticket with the circuit ID.
   c. Verify SD-WAN failover activated (check Admin > SD-WAN > Routes in the firewall).
4. If recovered on its own: document the outage window and follow up with the ISP
   for a root-cause explanation if the outage was >15 minutes.""",

    "Event::Other::FirewallFirmwareUpdateSuccessfullyFinished": """\
INFORMATIONAL — SFOS firmware update completed successfully.
1. Verify in Sophos Central that the reported firmware version matches the
   expected release (Admin > System > Firmware).
2. Confirm all firewall services are running normally post-update
   (no additional alerts in Sophos Central within 2 hours of the update).
3. Log the firmware update version and timestamp in the client's change record.
4. No further action required unless services are degraded.""",

    "Event::Firewall::FirewallFirmwareUpgradeFailed": """\
WHAT HAPPENED
An SFOS firmware upgrade attempt failed on the firewall.

RESOLUTION STEPS
1. Log in to Sophos Central and check the current firmware version — the firewall
   may have rolled back to the previous version automatically.
2. In the firewall admin console: Admin > Firmware > review the upgrade log.
3. Retry the upgrade from Sophos Central > Firewall > Firmware tab.
   If it fails again: download the firmware .sfos file from Sophos and upload
   it manually via Admin > Firmware > Manual Upload.
4. If the firewall is unresponsive post-failed-upgrade:
   a. Physical console access may be required to restore firmware.
   b. Contact Sophos Support with the firewall serial number and error log.""",

    "Event::Endpoint::NotProtected": """\
WHAT HAPPENED
One or more endpoints (computers/servers) under this client's Sophos Central
tenant are not protected — the Sophos Intercept X agent is missing, disabled,
or expired.

RESOLUTION STEPS
1. In Sophos Central > Endpoints, filter by Protection Status = "Not Protected."
2. For each unprotected endpoint:
   a. If the agent is missing: download the installer from Central and deploy it.
   b. If the agent is disabled: re-enable via the policy or locally on the machine.
   c. If the license is expired: renew via the client's Sophos license dashboard.
3. Confirm all endpoints show "Protected" in Central within 24 hours.
4. If the endpoint is decommissioned, remove it from the Central inventory to
   avoid false alerts.""",

    "Event::Endpoint::UpdateFailed": """\
WHAT HAPPENED
A Sophos Intercept X agent failed to update to the latest threat definition
or software version.

RESOLUTION STEPS
1. In Sophos Central > Endpoints, find the affected device.
2. Check if the endpoint is online (reachable). If offline, the update will
   retry automatically when the device comes back online.
3. If the device is online but not updating:
   a. Right-click the endpoint in Central and click "Update Now."
   b. If update still fails, check the endpoint's system clock — skewed time
      can cause update authentication failures.
   c. Verify the device has outbound internet access to Sophos update servers
      (update.sophosxl.net, update1.sophoslabs.com on TCP 443).
4. If the issue persists: re-install the Intercept X agent from Central.""",

    "_default": """\
WHAT HAPPENED
Sophos Central raised an alert on this client's account. Details are in the
alert data below.

RESOLUTION STEPS
1. Log in to Sophos Central (central.sophos.com) and review the alert.
2. Click the alert to see the full details and any recommended actions from Sophos.
3. Follow Sophos's in-product guidance to remediate.
4. If the alert is unclear, search the Sophos Community (community.sophos.com)
   for the exact alert type listed in this ticket.
5. Close this ticket once the alert is resolved or acknowledged in Central.""",
}


def _resolution(alert_type: str) -> str:
    return RESOLUTION_STEPS.get(alert_type) or RESOLUTION_STEPS["_default"]


def _html_decode(s: str) -> str:
    return html.unescape(s) if s else ""


# ---------------------------------------------------------------------------
# Alert collection
# ---------------------------------------------------------------------------

def collect_open_alerts_by_client() -> dict[str, list[dict]]:
    """Walk every clients/<code>/sophos/<latest_date>/alerts.json.
    Returns {LocationCode: [alert, ...]} for alerts with status==open."""
    out: dict[str, list[dict]] = defaultdict(list)
    for client_dir in CLIENTS_ROOT.iterdir():
        if not client_dir.is_dir():
            continue
        sophos_dir = client_dir / "sophos"
        if not sophos_dir.exists():
            continue
        date_dirs = sorted(
            (p for p in sophos_dir.iterdir()
             if p.is_dir() and len(p.name) == 10 and p.name[4] == "-"),
            reverse=True,
        )
        if not date_dirs:
            continue
        alerts_path = date_dirs[0] / "alerts.json"
        if not alerts_path.exists():
            continue
        try:
            alerts = json.loads(alerts_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        code = client_dir.name.upper()
        for a in alerts:
            if not a.get("id"):
                continue
            if a.get("status") and a["status"] != "open":
                continue
            out[code].append(a)
    return dict(out)


# ---------------------------------------------------------------------------
# Consolidated ticket body builder
# ---------------------------------------------------------------------------

def _classify_connectivity(alerts: list[dict]) -> str:
    """Determine connectivity pattern: 'current_outage', 'intermittent', or 'resolved'."""
    lost = [a for a in alerts if a.get("type") == "Event::Firewall::LostConnectionToSophosCentral"]
    reconnected = [a for a in alerts if a.get("type") == "Event::Firewall::Reconnected"]
    if len(lost) > len(reconnected):
        return "current_outage"
    if len(lost) > 0:
        return "intermittent"
    return "resolved"


def build_client_ticket_title(code: str, alerts: list[dict]) -> str:
    high = [a for a in alerts if a.get("severity") == "high"]
    types = {a.get("type", "") for a in alerts}

    has_lost = any("LostConnection" in t for t in types)
    has_gw_down = any("GatewayDown" in t for t in types)
    has_unprotected = any("NotProtected" in t for t in types)
    has_update_fail = any("UpdateFailed" in t or "UpgradeFailed" in t for t in types)

    if has_unprotected:
        return f"[Sophos] {code} - Endpoints not protected - action required"
    if has_gw_down:
        return f"[Sophos HIGH] {code} - WAN gateway down on firewall"
    if has_lost:
        pattern = _classify_connectivity(alerts)
        if pattern == "current_outage":
            return f"[Sophos HIGH] {code} - Firewall offline - not reporting to Central"
        count = sum(1 for a in alerts if "LostConnection" in (a.get("type") or ""))
        return f"[Sophos] {code} - Intermittent firewall connectivity ({count}x disconnect)"
    if has_update_fail:
        return f"[Sophos] {code} - Firmware update failed on firewall"
    if high:
        sample = _html_decode(high[0].get("description") or high[0].get("type") or "alert")[:60]
        return f"[Sophos HIGH] {code} - {sample}"
    sample = _html_decode(alerts[0].get("description") or alerts[0].get("type") or "alert")[:70]
    return f"[Sophos] {code} - {sample}"


def build_client_ticket_body(code: str, location_name: str, alerts: list[dict],
                              firewalls: list[dict] | None = None) -> str:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Group alerts by type for summary
    by_type: dict[str, list[dict]] = defaultdict(list)
    for a in alerts:
        by_type[a.get("type") or "_unknown"].append(a)

    high_count = sum(1 for a in alerts if a.get("severity") == "high")
    low_count = sum(1 for a in alerts if a.get("severity") == "low")

    # Firewall inventory summary
    fw_lines = []
    if firewalls:
        for fw in firewalls:
            status_str = "CONNECTED" if fw.get("connected") else "OFFLINE"
            fw_lines.append(
                f"  - {fw.get('hostname') or fw.get('name') or 'unknown'}"
                f"  |  {fw.get('model', '').split('_SFOS')[0]}"
                f"  |  WAN: {fw.get('externalIpv4Address', 'N/A')}"
                f"  |  Firmware: {fw.get('firmwareVersion', 'N/A').split('_')[-1]}"
                f"  |  Status: {status_str}"
            )
    fw_block = "\n".join(fw_lines) if fw_lines else "  (inventory not available for this run)"

    # Build alert type breakdown
    alert_breakdown_lines = []
    for atype, agroup in sorted(by_type.items()):
        sevs = [a.get("severity", "?") for a in agroup]
        high_n = sevs.count("high")
        low_n = sevs.count("low")
        raised = sorted(
            [a.get("raisedAt") or "" for a in agroup if a.get("raisedAt")],
        )
        earliest = raised[0][:16].replace("T", " ") if raised else "—"
        latest = raised[-1][:16].replace("T", " ") if raised else "—"
        type_short = atype.replace("Event::Firewall::", "").replace("Event::Other::", "").replace("Event::Endpoint::", "")
        sev_str = f"high={high_n} low={low_n}" if high_n else f"low={low_n}"
        time_range = f"{earliest}" if earliest == latest else f"{earliest} → {latest}"
        alert_breakdown_lines.append(
            f"  [{len(agroup)}x {sev_str}]  {type_short}\n"
            f"             First: {time_range}"
        )

    alert_breakdown = "\n".join(alert_breakdown_lines)

    # Build resolution section — deduplicate by type, prioritise actionable types
    resolution_types_seen: set[str] = set()
    resolution_blocks: list[str] = []

    # Order: highest-priority types first
    priority_order = [
        "Event::Firewall::LostConnectionToSophosCentral",
        "Event::Firewall::FirewallGatewayDown",
        "Event::Firewall::FirewallFirmwareUpgradeFailed",
        "Event::Endpoint::NotProtected",
        "Event::Endpoint::UpdateFailed",
        "Event::Firewall::FirewallGatewayUp",
        "Event::Firewall::Reconnected",
        "Event::Other::FirewallFirmwareUpdateSuccessfullyFinished",
    ]
    ordered_types = [t for t in priority_order if t in by_type]
    ordered_types += [t for t in by_type if t not in ordered_types]

    for atype in ordered_types:
        if atype in resolution_types_seen:
            continue
        resolution_types_seen.add(atype)
        step_text = _resolution(atype)
        type_short = atype.replace("Event::Firewall::", "").replace("Event::Other::", "").replace("Event::Endpoint::", "")
        resolution_blocks.append(
            f"--- {type_short} ---\n{step_text.strip()}"
        )

    resolution_section = "\n\n".join(resolution_blocks)

    # Alert IDs for reference
    alert_ids = "\n".join(f"  {a['id']}  [{a.get('severity','?')}]  {a.get('raisedAt','')[:16]}  {(a.get('type') or '').split('::')[-1]}"
                          for a in sorted(alerts, key=lambda x: x.get("raisedAt") or ""))

    connectivity_pattern = _classify_connectivity(alerts)
    pattern_note = {
        "current_outage": "*** CURRENT OUTAGE — firewall may still be offline ***",
        "intermittent": "Pattern: intermittent disconnects — firewall is currently reconnected.",
        "resolved": "Pattern: all events appear resolved.",
    }.get(connectivity_pattern, "")

    return f"""\
Auto-generated by Technijian Sophos Central alert router on {now_str}.
Client: {location_name} ({code})
{pattern_note}

ALERT SUMMARY
Total open alerts: {len(alerts)}  |  High: {high_count}  |  Low: {low_count}

{alert_breakdown}

FIREWALL INVENTORY (at time of pull)
{fw_block}

===========================================================
RESOLUTION STEPS — PLEASE READ BEFORE CLOSING
===========================================================

{resolution_section}

===========================================================
ALERT REFERENCE IDs (Sophos Central)
===========================================================
{alert_ids}

To view these alerts in Sophos Central:
  1. Log in to central.sophos.com
  2. Go to My Customers > {location_name} > Alerts
  3. Resolve or acknowledge each alert once actioned
"""


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if not ALERT_STATE_FILE.exists():
        return {"clients": {}, "alerts": {}}
    s = json.loads(ALERT_STATE_FILE.read_text(encoding="utf-8"))
    s.setdefault("clients", {})
    s.setdefault("alerts", {})
    return s


def save_state(state: dict) -> None:
    ALERT_STATE_FILE.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def decide_client_action(client_state: dict | None, reminder_threshold: timedelta) -> str:
    if not client_state:
        return "NEW"
    if not client_state.get("ticket_id"):
        return "NEW"
    last = parse_iso(client_state.get("last_email_sent_at")) or \
           parse_iso(client_state.get("first_seen_at"))
    if not last:
        return "AGING"
    if datetime.now(timezone.utc) - last >= reminder_threshold:
        return "AGING"
    return "QUIET"


# ---------------------------------------------------------------------------
# Firewall inventory loader
# ---------------------------------------------------------------------------

def load_latest_firewalls(code: str) -> list[dict]:
    client_dir = CLIENTS_ROOT / code.lower()
    sophos_dir = client_dir / "sophos"
    if not sophos_dir.exists():
        return []
    date_dirs = sorted(
        (p for p in sophos_dir.iterdir()
         if p.is_dir() and len(p.name) == 10 and p.name[4] == "-"),
        reverse=True,
    )
    if not date_dirs:
        return []
    fw_path = date_dirs[0] / "firewalls.json"
    if not fw_path.exists():
        return []
    try:
        raw = json.loads(fw_path.read_text(encoding="utf-8"))
        # Flatten for display
        result = []
        for fw in raw:
            status = fw.get("status") or {}
            ips = fw.get("externalIpv4Addresses") or []
            result.append({
                "hostname": fw.get("hostname") or fw.get("name"),
                "model": fw.get("model", ""),
                "firmwareVersion": fw.get("firmwareVersion", ""),
                "externalIpv4Address": ips[0] if ips else "",
                "connected": status.get("connected"),
                "suspended": status.get("suspended"),
            })
        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
# DirID + location name lookup
# ---------------------------------------------------------------------------

def load_client_info(code: str) -> tuple[int | None, str]:
    """Return (DirID, Location_Name) from _meta.json."""
    meta_path = CLIENTS_ROOT / code.lower() / "_meta.json"
    if not meta_path.exists():
        return None, code
    try:
        m = json.loads(meta_path.read_text(encoding="utf-8"))
        return m.get("DirID"), m.get("Location_Name") or code
    except Exception:
        return None, code


# ---------------------------------------------------------------------------
# CLI + main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Route open Sophos alerts to CP tickets (one per client) + reminder emails.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually create tickets and send emails. Default: report only.")
    ap.add_argument("--no-tickets", action="store_true",
                    help="Skip CP ticket creation (still tracks state, sends emails).")
    ap.add_argument("--no-emails", action="store_true",
                    help="Skip reminder emails (still creates tickets).")
    ap.add_argument("--reminder-hours", type=float, default=24.0,
                    help="Hours between reminder emails (default 24)")
    ap.add_argument("--to", default=email_support.DEFAULT_TO,
                    help="Reminder email recipient (default support@technijian.com)")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    state = load_state()
    threshold = timedelta(hours=args.reminder_hours)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(f"[{datetime.now():%H:%M:%S}] Sophos alert router  "
          f"apply={args.apply}  reminder={threshold}")

    alerts_by_client = collect_open_alerts_by_client()
    total_alerts = sum(len(v) for v in alerts_by_client.values())
    print(f"  clients with open alerts: {len(alerts_by_client)}  "
          f"total alerts: {total_alerts}")

    plan: dict[str, list] = {"NEW": [], "AGING": [], "QUIET": [], "RESOLVED": []}
    seen_codes: set[str] = set()

    for code, alerts in sorted(alerts_by_client.items()):
        seen_codes.add(code)
        client_state = state["clients"].get(code)
        action = decide_client_action(client_state, threshold)

        dir_id, location_name = load_client_info(code)
        firewalls = load_latest_firewalls(code)

        high_count = sum(1 for a in alerts if a.get("severity") == "high")
        alert_ids = [a["id"] for a in alerts]

        if action == "NEW":
            new_state: dict = {
                "LocationCode": code,
                "location_name": location_name,
                "first_seen_at": now_iso,
                "alert_ids": alert_ids,
                "alert_count": len(alerts),
                "high_count": high_count,
                "ticket_id": None,
                "ticket_created_at": None,
                "last_email_sent_at": None,
                "email_count": 0,
                "resolved_at": None,
            }
            if client_state:
                new_state["first_seen_at"] = client_state.get("first_seen_at") or now_iso
                new_state["email_count"] = client_state.get("email_count", 0)
                new_state["last_email_sent_at"] = client_state.get("last_email_sent_at")

            if args.apply and not args.no_tickets:
                try:
                    if not dir_id:
                        raise RuntimeError(f"No DirID for {code} — run build_client_meta.py")
                    title = build_client_ticket_title(code, alerts)
                    body = build_client_ticket_body(code, location_name, alerts, firewalls)

                    # Priority: HIGH if any high-severity, else When Convenient
                    priority = 1255 if high_count > 0 else 1257  # Same Day vs When Convenient
                    result = cp_tickets.create_ticket(
                        requestor_dir_id=dir_id,
                        client_id=dir_id,
                        contract_id=cp_tickets.lookup_active_contract_id(dir_id, code),
                        title=title,
                        description=body,
                        priority=priority,
                        role_type=1236,  # Off-Shore Tech Support
                        location_top_filter=cp_tickets.lookup_location_top_filter_by_dir_id(dir_id),
                        created_by="clientportal@technijian.com",
                    )
                    new_state["ticket_id"] = result.get("ticket_id")
                    new_state["ticket_created_at"] = now_iso
                except Exception as e:
                    new_state["_creation_error"] = f"{type(e).__name__}: {e}"
                    new_state["_creation_traceback"] = traceback.format_exc()[-1000:]

            state["clients"][code] = new_state
            # Also mark individual alert IDs as seen so old per-alert state is not confused
            for aid in alert_ids:
                state["alerts"].setdefault(aid, {
                    "LocationCode": code,
                    "grouped_into_client_ticket": True,
                    "first_seen_at": now_iso,
                })

            plan["NEW"].append({
                "code": code,
                "location_name": location_name,
                "alert_count": len(alerts),
                "high_count": high_count,
                "ticket_id": new_state.get("ticket_id"),
                "_creation_error": new_state.get("_creation_error"),
            })

        elif action == "AGING":
            # Update alert list in state
            client_state["alert_ids"] = alert_ids
            client_state["alert_count"] = len(alerts)
            client_state["high_count"] = high_count

            send_result: dict = {"sent": False, "status": "skipped"}
            if args.apply and not args.no_emails:
                try:
                    # Build a short reminder body
                    summary_alert = sorted(alerts, key=lambda a: a.get("severity") == "high", reverse=True)[0]
                    send_result = email_support.send_reminder(summary_alert, client_state,
                                                               to_address=args.to)
                except Exception as e:
                    send_result = {"sent": False, "status": f"ERR {e}"}
            if send_result.get("sent"):
                client_state["last_email_sent_at"] = send_result.get("sent_at") or now_iso
                client_state["email_count"] = int(client_state.get("email_count") or 0) + 1

            plan["AGING"].append({
                "code": code,
                "alert_count": len(alerts),
                "ticket_id": client_state.get("ticket_id"),
                "email_count": client_state.get("email_count", 0),
                "send_status": send_result.get("status"),
            })

        else:  # QUIET
            plan["QUIET"].append({
                "code": code,
                "alert_count": len(alerts),
                "ticket_id": client_state.get("ticket_id"),
                "last_email_sent_at": client_state.get("last_email_sent_at"),
            })

    # Clients in state that are no longer in the alert feed = RESOLVED
    for code, cs in list(state["clients"].items()):
        if code in seen_codes or cs.get("resolved_at"):
            continue
        cs["resolved_at"] = now_iso
        plan["RESOLVED"].append({
            "code": code,
            "ticket_id": cs.get("ticket_id"),
        })

    if args.apply:
        save_state(state)
    else:
        print("  REPORT MODE — state NOT updated (pass --apply to persist)")

    print(f"  NEW:      {len(plan['NEW']):>3d}  (one ticket per client with all alerts)")
    print(f"  AGING:    {len(plan['AGING']):>3d}")
    print(f"  QUIET:    {len(plan['QUIET']):>3d}")
    print(f"  RESOLVED: {len(plan['RESOLVED']):>3d}")

    for p in plan["NEW"]:
        status = f"ticket={p['ticket_id']}" if p.get("ticket_id") else \
                 f"ERROR: {p.get('_creation_error', 'pending --apply')}"
        print(f"    {p['code']:<8s} alerts={p['alert_count']}  high={p['high_count']}  {status}")

    # Write routing plan
    run_dirs = sorted(
        (d for d in PIPELINE_ROOT.iterdir()
         if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"),
        reverse=True,
    )
    plan_dir = run_dirs[0] if run_dirs else STATE_DIR
    plan_path = plan_dir / "routing-plan.json"
    plan_path.write_text(json.dumps({
        "run_at": now_iso,
        "apply": args.apply,
        "grouping": "per_client",
        "reminder_hours": args.reminder_hours,
        "plan": plan,
    }, indent=2, default=str), encoding="utf-8")

    print(f"  routing plan: {plan_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
