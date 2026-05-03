"""
Generic Graph mail send for ticket reminders. Same auth flow as the
Sophos pipeline — reuses `_secrets.get_m365_credentials()` and posts to
the M365 Graph `/users/{mailbox}/sendMail` endpoint.

Used by ticket_monitor.py to remind support@technijian.com about open
CP tickets that have not been worked on within the reminder window.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TECH_TRAINING_SCRIPTS = REPO_ROOT / "technijian" / "tech-training" / "scripts"
sys.path.insert(0, str(TECH_TRAINING_SCRIPTS))
import _secrets  # type: ignore  # noqa: E402

DEFAULT_TO = "support@technijian.com"


def _get_token() -> str:
    tenant_id, client_id, client_secret, _ = _secrets.get_m365_credentials()
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))["access_token"]


def _post_json(url: str, token: str, body: dict) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _human_age(created_iso: str) -> str:
    try:
        created = datetime.fromisoformat(created_iso.replace("Z", "+00:00"))
    except Exception:
        return "?"
    delta = datetime.now(timezone.utc) - created
    hours = int(delta.total_seconds() // 3600)
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    rem = hours % 24
    return f"{days}d {rem}h"


def build_reminder_html(ticket: dict) -> str:
    """Build the HTML body for a 'please action this ticket' email."""
    age = _human_age(ticket.get("created_at", ""))
    rem = int(ticket.get("reminder_count") or 0)
    nth = "1st" if rem == 0 else "2nd" if rem == 1 else "3rd" if rem == 2 else f"{rem + 1}th"
    sev_color = "#CC0000" if ticket.get("priority_id") in (1253, 1254, 1255) else "#F67D4B"
    return f"""<html><body style="font-family: 'Open Sans', sans-serif; color: #1A1A2E;">
<h3 style="color: #006DB6; margin-bottom: 4px;">CP ticket #{ticket.get("ticket_id")} — please action ({nth} reminder)</h3>
<p style="color: #59595B; margin-top: 4px;">Automated reminder from the ticket-monitor pipeline. The ticket has been open for <b>{age}</b> with no resolution recorded in our state file.</p>

<table style="border-collapse: collapse; margin-top: 12px;">
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Ticket #</td><td style="padding: 4px;"><b>{ticket.get("ticket_id")}</b></td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Client</td><td style="padding: 4px;"><b>{ticket.get("client_code")}</b></td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Source</td><td style="padding: 4px;">{ticket.get("source_skill")}</td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Priority</td><td style="padding: 4px;"><b style="color: {sev_color};">{ticket.get("priority_id")}</b></td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Assigned to</td><td style="padding: 4px;">DirID {ticket.get("assign_to_dir_id")} (CHD : TS1)</td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Created</td><td style="padding: 4px;">{ticket.get("created_at")} (UTC)</td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Open for</td><td style="padding: 4px;"><b>{age}</b></td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Reminders sent</td><td style="padding: 4px;">{rem}</td></tr>
</table>

<p style="margin-top: 16px;"><b>Title:</b><br/>{ticket.get("title")}</p>

<p style="margin-top: 16px; padding: 12px; background: #FEF3EE; border-left: 4px solid #F67D4B;">
<b>Action required:</b> open ticket #{ticket.get("ticket_id")} in the Client Portal,
read the description (full step-by-step remediation is included), and start work.
Once resolved, run on the dev box:<br/>
<code>python scripts/clientportal/ticket_monitor.py resolve {ticket.get("ticket_id")} --note "fixed by &lt;name&gt;"</code><br/>
to stop further reminders.
</p>

<p style="margin-top: 24px; font-size: 0.85em; color: #59595B;">
Reminder cadence: every 24 hours until resolved. State file:
<code>state/cp_tickets.json</code> on the dev workstation.
</p>
</body></html>"""


def send_reminder(ticket: dict, *, to_address: str = DEFAULT_TO,
                  cc: list[str] | None = None,
                  dry_run: bool = False) -> dict:
    """Send a reminder email about one open ticket. Returns
    {sent, status, body, sent_at}."""
    cc = cc or []
    subject = (
        f"[CP #{ticket.get('ticket_id')} reminder] "
        f"{ticket.get('client_code')} — {(ticket.get('title') or '')[:80]}"
    )
    html = build_reminder_html(ticket)

    if dry_run:
        return {"sent": False, "status": "dry-run", "body": "", "subject": subject,
                "to": to_address, "cc": cc, "sent_at": None}

    _t, _c, _s, mailbox = _secrets.get_m365_credentials()
    token = _get_token()
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [{"emailAddress": {"address": to_address}}],
            "ccRecipients": [{"emailAddress": {"address": a}} for a in cc],
        },
        "saveToSentItems": True,
    }
    url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/sendMail"
    status, body = _post_json(url, token, payload)
    return {
        "sent": 200 <= int(status) < 300,
        "status": status,
        "body": body[:300],
        "subject": subject,
        "to": to_address,
        "cc": cc,
        "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
