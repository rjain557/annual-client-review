"""Send Sophos alert reminder emails to support@technijian.com via M365 Graph.

Reuses the M365 credential resolver at technijian/tech-training/scripts/_secrets.py
(same auth flow as the weekly-audit pipeline). Sends as RJain@technijian.com
unless overridden via M365_MAILBOX env var.

This module never creates tickets. It only sends an email. The router
invokes it ONLY for alerts that already have a tracked CP ticket but have
remained open beyond the reminder threshold (default 24h since last email).
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TECH_TRAINING_SCRIPTS = REPO / "technijian" / "tech-training" / "scripts"
sys.path.insert(0, str(TECH_TRAINING_SCRIPTS))
import _secrets  # noqa: E402

DEFAULT_TO = "support@technijian.com"
DEFAULT_CC: list[str] = []  # add any escalation addresses here when needed


def _get_token() -> str:
    tenant_id, client_id, client_secret, _mailbox = _secrets.get_m365_credentials()
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))["access_token"]


def _post_json(url: str, token: str, body: dict, mailbox: str | None = None) -> tuple[int, str]:
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


def build_html_body(alert: dict, ticket_state: dict) -> str:
    """Build the reminder email body. Uses Technijian brand colors. No
    attachments — this is a short escalation note pointing at the existing
    CP ticket.
    """
    sev = alert.get("severity", "?")
    cat = alert.get("category", "?")
    desc = alert.get("description") or alert.get("name") or "(no description)"
    raised = alert.get("raisedAt", "?")
    code = ticket_state.get("LocationCode", "?")
    tid = ticket_state.get("ticket_id") or "(not yet created)"
    turl = ticket_state.get("ticket_url") or "(not yet created)"
    last_seen = ticket_state.get("first_seen_by_router_at", "?")
    email_count = ticket_state.get("email_count", 0)
    fw = (alert.get("managedAgent") or {}).get("name") or "?"
    sophos_alert_id = alert.get("id", "?")
    return f"""<html><body style="font-family: 'Open Sans', sans-serif; color: #1A1A2E;">
<h3 style="color: #006DB6; margin-bottom: 4px;">Sophos alert still open after {email_count + 1} reminder(s)</h3>
<p style="color: #59595B; margin-top: 4px;">Routed by automated pipeline — please action before EOD.</p>

<table style="border-collapse: collapse; margin-top: 12px;">
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Client</td><td style="padding: 4px;"><b>{code}</b></td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Firewall</td><td style="padding: 4px;">{fw}</td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Severity</td><td style="padding: 4px;"><b style="color: {'#F67D4B' if sev == 'high' else '#1EAAC8'};">{sev}</b></td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Category</td><td style="padding: 4px;">{cat}</td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Raised</td><td style="padding: 4px;">{raised}</td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">First routed</td><td style="padding: 4px;">{last_seen}</td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">CP ticket</td><td style="padding: 4px;"><a href="{turl}">{tid}</a></td></tr>
  <tr><td style="padding: 4px 12px 4px 0; color: #59595B;">Sophos alert id</td><td style="padding: 4px; font-family: monospace; color: #59595B;">{sophos_alert_id}</td></tr>
</table>

<p style="margin-top: 16px;"><b>Description:</b><br/>{desc}</p>

<p style="margin-top: 24px; font-size: 0.85em; color: #59595B;">
This is an automated reminder. The alert was originally routed to the
India support pod via CP ticket above. Reminder cadence: 24 hours.
Once the underlying issue is resolved in Sophos Central, this alert will
disappear from the next pipeline run and reminders stop automatically.
</p>
</body></html>"""


def send_reminder(alert: dict, ticket_state: dict,
                  to_address: str = DEFAULT_TO,
                  cc: list[str] | None = None,
                  dry_run: bool = False) -> dict:
    """Send the reminder email. Returns dict with {sent, status, body, sent_at}."""
    cc = cc if cc is not None else DEFAULT_CC
    desc = alert.get("description") or alert.get("name") or "(no description)"
    code = ticket_state.get("LocationCode", "?")
    sev = alert.get("severity", "?")
    subject = f"[Sophos {sev.upper()}] {code} - {desc[:90]}"
    body_html = build_html_body(alert, ticket_state)

    if dry_run:
        return {"sent": False, "status": "dry-run", "body": "", "subject": subject,
                "to": to_address, "cc": cc,
                "sent_at": None}

    _tenant, _cid, _sec, mailbox = _secrets.get_m365_credentials()
    token = _get_token()
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": to_address}}],
            "ccRecipients": [{"emailAddress": {"address": a}} for a in cc],
        },
        "saveToSentItems": True,
    }
    url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/sendMail"
    status, body = _post_json(url, token, payload, mailbox=mailbox)
    return {
        "sent": 200 <= int(status) < 300,
        "status": status,
        "body": body[:300],
        "subject": subject,
        "to": to_address,
        "cc": cc,
        "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
