"""Route open Sophos alerts -> CP ticket creation + reminder emails.

Runs after pull_sophos_daily.py each hour. Reads the latest pull's per-tenant
alerts.json, dedups against state/alert-tickets.json, and decides one of:

    NEW     - Sophos alert.id not in state              -> create CP ticket
                                                         (calls cp_tickets.create_ticket;
                                                          currently raises NotImplementedError
                                                          until SP signature is supplied)
    AGING   - alert still open, ticket already created,  -> send reminder email
              last_email_sent_at older than threshold       to support@technijian.com
              (default 24h)
    QUIET   - alert still open, ticket created, recent   -> no action
              email
    RESOLVED- alert.id was in state on a previous run    -> mark resolved_at,
              but is no longer in any tenant's alerts       no further action

Default mode is REPORT (dry-run) — writes a routing-plan.json showing what
would happen but does not call the CP API and does not send email. Pass
--apply to actually call cp_tickets.create_ticket and send_reminder.

Usage:
    python route_alerts.py                              # report mode (default)
    python route_alerts.py --apply                      # actually create+email
    python route_alerts.py --apply --no-tickets         # only send emails (skip CP)
    python route_alerts.py --reminder-hours 12          # change reminder cadence
    python route_alerts.py --to support@technijian.com  # override recipient
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
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


def latest_run_dir() -> Path | None:
    candidates = sorted(
        (p for p in PIPELINE_ROOT.iterdir() if p.is_dir() and len(p.name) == 10 and p.name[4] == "-"),
        reverse=True,
    )
    return candidates[0] if candidates else None


def load_state() -> dict:
    if not ALERT_STATE_FILE.exists():
        return {"alerts": {}}
    return json.loads(ALERT_STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    ALERT_STATE_FILE.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def collect_open_alerts() -> list[tuple[str, dict]]:
    """Walk every clients/<code>/sophos/<latest_date>/alerts.json and return
    a flat list of (LocationCode, alert) tuples for alerts currently open."""
    out: list[tuple[str, dict]] = []
    for client_dir in CLIENTS_ROOT.iterdir():
        if not client_dir.is_dir():
            continue
        sophos_dir = client_dir / "sophos"
        if not sophos_dir.exists():
            continue
        date_dirs = sorted(
            (p for p in sophos_dir.iterdir() if p.is_dir() and len(p.name) == 10 and p.name[4] == "-"),
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
            # only route OPEN alerts (defensive — pull already filters)
            if a.get("status") and a["status"] != "open":
                continue
            out.append((code, a))
    return out


def decide_action(state_entry: dict | None, reminder_threshold: timedelta) -> str:
    if not state_entry:
        return "NEW"
    # Retry ticket creation if it never succeeded (SP unwired or transient error)
    if not state_entry.get("ticket_id"):
        return "NEW"
    last = parse_iso(state_entry.get("last_email_sent_at")) or parse_iso(state_entry.get("first_seen_by_router_at"))
    if not last:
        return "AGING"
    if datetime.now(timezone.utc) - last >= reminder_threshold:
        return "AGING"
    return "QUIET"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Route open Sophos alerts to CP tickets + reminder emails.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually create tickets and send emails. Default: report only.")
    ap.add_argument("--no-tickets", action="store_true",
                    help="Skip CP ticket creation (still tracks state and sends emails).")
    ap.add_argument("--no-emails", action="store_true",
                    help="Skip reminder emails (still creates tickets).")
    ap.add_argument("--reminder-hours", type=float, default=24.0,
                    help="Hours to wait between reminder emails (default 24)")
    ap.add_argument("--to", default=email_support.DEFAULT_TO,
                    help="Reminder email recipient (default support@technijian.com)")
    ap.add_argument("--client-dirids", help="Path to JSON file mapping LocationCode -> DirID. "
                                            "Default: load via cp_api.get_active_clients()")
    return ap.parse_args()


def load_dirid_map(args) -> dict[str, int]:
    if args.client_dirids and Path(args.client_dirids).exists():
        return {k.upper(): int(v) for k, v in json.loads(Path(args.client_dirids).read_text()).items()}
    sys.path.insert(0, str(REPO / "scripts" / "clientportal"))
    import cp_api  # noqa: E402
    return {(c.get("LocationCode") or "").upper(): int(c["DirID"])
            for c in cp_api.get_active_clients()
            if c.get("LocationCode") and c.get("DirID")}


def main() -> int:
    args = parse_args()
    state = load_state()
    state.setdefault("alerts", {})
    threshold = timedelta(hours=args.reminder_hours)

    print(f"[{datetime.now():%H:%M:%S}] Sophos alert router  apply={args.apply} reminder_threshold={threshold}")

    open_alerts = collect_open_alerts()
    print(f"  open alerts found across all clients: {len(open_alerts)}")

    dirid_map: dict[str, int] = {}
    if args.apply and not args.no_tickets:
        try:
            dirid_map = load_dirid_map(args)
            print(f"  loaded DirID map for {len(dirid_map)} clients")
        except Exception as e:
            print(f"  WARN: could not load DirID map: {e}")

    plan = {"NEW": [], "AGING": [], "QUIET": [], "RESOLVED": []}
    seen_ids: set[str] = set()
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for code, alert in open_alerts:
        aid = alert["id"]
        seen_ids.add(aid)
        entry = state["alerts"].get(aid)
        action = decide_action(entry, threshold)

        if action == "NEW":
            new_state = {
                "LocationCode": code,
                "sophos_tenant_id": (alert.get("tenant") or {}).get("id"),
                "alert_category": alert.get("category"),
                "alert_severity": alert.get("severity"),
                "alert_type": alert.get("type"),
                "alert_description": alert.get("description") or alert.get("name"),
                "alert_raised_at": alert.get("raisedAt"),
                "first_seen_by_router_at": now_iso,
                "ticket_id": None,
                "ticket_created_at": None,
                "ticket_url": None,
                "ticket_assigned_to": cp_tickets.INDIA_SUPPORT_POD,
                "ticket_billable": cp_tickets.CLIENT_BILLABLE,
                "last_email_sent_at": None,
                "email_count": 0,
                "resolved_at": None,
            }

            if args.apply and not args.no_tickets:
                try:
                    dir_id = dirid_map.get(code)
                    if not dir_id:
                        raise RuntimeError(f"No DirID for LocationCode {code}")
                    desc = alert.get("description") or alert.get("name") or alert.get("type") or "Sophos alert"
                    fw = (alert.get("managedAgent") or {}).get("name") or "?"
                    body = (
                        f"Auto-routed from Sophos Central. Severity={alert.get('severity')}.\n"
                        f"Firewall: {fw}\n"
                        f"Category: {alert.get('category')}\n"
                        f"Type: {alert.get('type')}\n"
                        f"Raised: {alert.get('raisedAt')}\n"
                        f"Sophos alert id: {aid}\n\n"
                        f"Description:\n{desc}\n"
                    )
                    result = cp_tickets.create_ticket(
                        client_dir_id=dir_id,
                        subject=f"[Sophos {alert.get('severity','?').upper()}] {code} - {desc[:90]}",
                        description=body,
                        billable=cp_tickets.CLIENT_BILLABLE,  # client alerts = billable
                    )
                    new_state["ticket_id"] = result.get("ticket_id")
                    new_state["ticket_url"] = result.get("ticket_url")
                    new_state["ticket_created_at"] = now_iso
                except NotImplementedError as e:
                    new_state["_pending_reason"] = str(e)
                except Exception as e:
                    new_state["_creation_error"] = f"{type(e).__name__}: {e}"
                    new_state["_creation_traceback"] = traceback.format_exc()[-1000:]

            # Preserve any prior pending state when retrying a NEW that's
            # really a re-attempt at ticket creation
            if entry:
                new_state["first_seen_by_router_at"] = entry.get("first_seen_by_router_at") or now_iso
                new_state["email_count"] = entry.get("email_count", 0)
                new_state["last_email_sent_at"] = entry.get("last_email_sent_at")
            state["alerts"][aid] = new_state
            plan["NEW"].append({"id": aid, "code": code,
                                "severity": alert.get("severity"),
                                "category": alert.get("category"),
                                "type": alert.get("type"),
                                "description": (alert.get("description") or alert.get("name", ""))[:120],
                                "ticket_id": new_state.get("ticket_id"),
                                "_pending_reason": new_state.get("_pending_reason"),
                                "_creation_error": new_state.get("_creation_error")})

        elif action == "AGING":
            send_result: dict = {"sent": False, "status": "skipped"}
            if args.apply and not args.no_emails:
                try:
                    send_result = email_support.send_reminder(alert, entry, to_address=args.to)
                except Exception as e:
                    send_result = {"sent": False, "status": f"ERR {e}", "body": traceback.format_exc()[-600:]}
            if send_result.get("sent"):
                entry["last_email_sent_at"] = send_result["sent_at"] or now_iso
                entry["email_count"] = int(entry.get("email_count") or 0) + 1
            plan["AGING"].append({"id": aid, "code": code,
                                  "ticket_id": entry.get("ticket_id"),
                                  "email_count": entry.get("email_count", 0),
                                  "send_status": send_result.get("status")})

        else:  # QUIET
            plan["QUIET"].append({"id": aid, "code": code,
                                  "ticket_id": entry.get("ticket_id"),
                                  "last_email_sent_at": entry.get("last_email_sent_at")})

    # Anything in state that wasn't in this run = RESOLVED
    for aid, entry in list(state["alerts"].items()):
        if aid in seen_ids or entry.get("resolved_at"):
            continue
        entry["resolved_at"] = now_iso
        plan["RESOLVED"].append({"id": aid, "code": entry.get("LocationCode"),
                                 "ticket_id": entry.get("ticket_id")})

    if args.apply:
        save_state(state)
    else:
        print("  REPORT MODE - state file NOT updated (run with --apply to persist)")

    # Console summary
    print(f"  NEW:      {len(plan['NEW']):>3d}")
    print(f"  AGING:    {len(plan['AGING']):>3d}")
    print(f"  QUIET:    {len(plan['QUIET']):>3d}")
    print(f"  RESOLVED: {len(plan['RESOLVED']):>3d}")

    # Routing plan written next to today's run dir
    run_dir = latest_run_dir()
    if run_dir:
        plan_path = run_dir / "routing-plan.json"
    else:
        plan_path = STATE_DIR / f"routing-plan-{datetime.now(timezone.utc):%Y-%m-%dT%H%M%SZ}.json"
    plan_path.write_text(json.dumps({
        "run_at": now_iso,
        "apply": args.apply,
        "no_tickets": args.no_tickets,
        "no_emails": args.no_emails,
        "reminder_hours": args.reminder_hours,
        "recipient": args.to,
        "plan": plan,
    }, indent=2, default=str), encoding="utf-8")

    if not args.apply:
        print(f"  REPORT MODE - no tickets created, no emails sent.")
    if args.apply and any(p.get("_pending_reason") for p in plan["NEW"]):
        print()
        print("  *** {n} alert(s) need a CP ticket, but cp_tickets.create_ticket() is unwired ***".format(
            n=sum(1 for p in plan["NEW"] if p.get("_pending_reason"))))
        print("      See cp_tickets.py module docstring for what's needed to wire it up.")
    print(f"  routing plan: {plan_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
