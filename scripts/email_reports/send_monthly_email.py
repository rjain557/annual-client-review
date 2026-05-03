"""Compose and send the monthly client-report delivery email.

For each client with reports uploaded for a given month, this script:

  1. Reads the OneDrive/Teams upload manifest written by
     ``scripts/teams_upload/upload_monthly_reports.py`` at
     ``clients/<slug>/_monthly_report_uploads/<YYYY-MM>.json``.
  2. Reads the recipient list from ``clients/<slug>/_meta.json``
     (``Recipient_Emails`` field, populated by the active-client builder).
  3. Pulls a small set of headline KPIs from each report's underlying
     data so the email body has a real summary — not just file names.
  4. Renders a Technijian-branded HTML email with the summary plus a
     bulleted list of clickable OneDrive links to every report.
  5. (With ``--apply``) sends the email from ``clientportal@technijian.com``
     via Microsoft Graph ``/users/{mailbox}/sendMail``.

Defaults to ``--dry-run`` — writes the rendered HTML to
``clients/<slug>/_monthly_report_emails/<YYYY-MM>.html`` so you can
review before going live.

Usage:
    python send_monthly_email.py --month 2026-04                       # dry-run
    python send_monthly_email.py --month 2026-04 --only AAVA --apply   # send
    python send_monthly_email.py --month 2026-04 --to-only support@technijian.com  # internal review

Reads creds from
``%USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/m365-graph.md``
(Mail.Send Application — HiringPipeline-Automation app).
"""

from __future__ import annotations

import argparse
import calendar
import html
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENTS_ROOT = REPO_ROOT / "clients"
KEYFILE = (
    Path(os.environ.get("USERPROFILE", str(Path.home())))
    / "OneDrive - Technijian, Inc"
    / "Documents"
    / "VSCODE"
    / "keys"
    / "m365-graph.md"
)
SENDER_MAILBOX = "clientportal@technijian.com"
SIGNATURE_PATH = REPO_ROOT / "technijian" / "tech-training" / "scripts" / "signature.html"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_TOKEN_CACHE: dict = {"token": None, "expires_at": 0}


def _load_creds() -> tuple[str, str, str]:
    text = KEYFILE.read_text(encoding="utf-8", errors="replace")
    cid = re.search(r"App Client ID:\*\*\s*(\S+)", text).group(1)
    tid = re.search(r"Tenant ID:\*\*\s*(\S+)", text).group(1)
    sec = re.search(r"Client Secret:\*\*\s*(\S+)", text).group(1)
    return cid, tid, sec


def _token() -> str:
    if _TOKEN_CACHE["token"] and _TOKEN_CACHE["expires_at"] > time.time() + 60:
        return _TOKEN_CACHE["token"]
    cid, tid, sec = _load_creds()
    r = requests.post(
        f"https://login.microsoftonline.com/{tid}/oauth2/v2.0/token",
        data={
            "client_id": cid,
            "client_secret": sec,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    _TOKEN_CACHE["token"] = body["access_token"]
    _TOKEN_CACHE["expires_at"] = time.time() + int(body.get("expires_in", 3600))
    return _TOKEN_CACHE["token"]


def _send_via_graph(subject: str, html_body: str, to: list[str], cc: list[str] | None = None) -> dict:
    cc = cc or []
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html_body},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to],
            "ccRecipients": [{"emailAddress": {"address": a}} for a in cc],
        },
        "saveToSentItems": True,
    }
    r = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{SENDER_MAILBOX}/sendMail",
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    return {"status": r.status_code, "body": r.text[:500]}


# ---------------------------------------------------------------------------
# Headline KPI extraction (per data source)
# ---------------------------------------------------------------------------

def _safe_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _highlight_me_ec(client_dir: Path, year: int, month: int) -> str | None:
    """Pulls from the most recent _me_ec snapshot under clients/_me_ec."""
    me_ec_root = REPO_ROOT / "clients" / "_me_ec"
    if not me_ec_root.exists():
        return None
    # Most recent dated folder
    days = sorted([p for p in me_ec_root.iterdir() if p.is_dir()])
    if not days:
        return None
    slug_upper = client_dir.name.upper()
    # Try the slug folder under the latest day
    cust_dir = None
    for d in reversed(days):
        if (d / slug_upper).is_dir():
            cust_dir = d / slug_upper
            break
    if cust_dir is None:
        return None
    summary = _safe_load_json(cust_dir / "per_machine_patch_summary.json") or []
    if not summary:
        return None
    machines = len(summary)
    # Sum of installed_count is YTD; this is just an indicator
    inst = sum(int(m.get("installed_count") or 0) for m in summary)
    if inst == 0:
        return f"Patch posture monitored across {machines} endpoint(s)."
    return f"{inst:,} cumulative patches installed across {machines} endpoint(s)."


def _highlight_huntress(client_dir: Path, year: int, month: int) -> str | None:
    ym = f"{year:04d}-{month:02d}"
    code = client_dir.name.upper()
    base = client_dir / "huntress" / "monthly" / ym
    inc = _safe_load_json(base / "incident_reports.json") or {}
    if isinstance(inc, dict):
        incidents = inc.get("window") or []
    else:
        incidents = inc
    signals = _safe_load_json(base / "signals.json") or []
    reports = _safe_load_json(base / "reports.json") or []
    parts = []
    if incidents:
        parts.append(f"{len(incidents)} incident report(s)")
    if signals:
        parts.append(f"{len(signals)} signal(s)")
    if reports:
        parts.append(f"{len(reports)} platform report(s)")
    if not parts:
        return "Endpoints monitored 24x7 by the Huntress SOC — no incident reports raised this month."
    return ", ".join(parts) + " reviewed by the Huntress 24x7 SOC."


def _highlight_crowdstrike(client_dir: Path, year: int, month: int) -> str | None:
    ym = f"{year:04d}-{month:02d}"
    base = client_dir / "crowdstrike" / "monthly" / ym
    alerts = _safe_load_json(base / "alerts.json") or []
    if isinstance(alerts, dict):
        alerts = alerts.get("alerts") or alerts.get("data") or []
    crit_high = 0
    for a in alerts:
        sev = (a.get("severity") or a.get("Severity") or "").lower()
        if sev in ("critical", "high"):
            crit_high += 1
    if not alerts:
        return "Falcon Overwatch monitored endpoints 24x7 — no alerts fired this month."
    return f"{len(alerts)} Falcon alert(s) reviewed by Overwatch ({crit_high} Critical/High)."


def _highlight_veeam_vbr(client_dir: Path, year: int, month: int) -> str | None:
    base = client_dir / "veeam-vbr" / str(year)
    if not base.exists():
        return None
    summary = _safe_load_json(base / "summary.json") or {}
    by_result = summary.get("by_result") or {}
    succ = int(by_result.get("Success", 0)) + int(by_result.get("Warning", 0))
    total = int(summary.get("session_count") or sum(by_result.values()) or 0)
    if not total:
        return None
    rate = (succ / total * 100) if total else 0
    return f"{succ:,}/{total:,} backup sessions completed across the year ({rate:.0f}%)."


def _highlight_vcenter(client_dir: Path, year: int, month: int) -> str | None:
    base = client_dir / "vcenter" / str(year)
    if not base.exists():
        return None
    summary = _safe_load_json(base / "summary.json") or {}
    vms = summary.get("vm_count") or 0
    on = summary.get("vm_powered_on") or 0
    if not vms:
        return None
    return f"{vms} virtual machine(s) under management, {on} powered on."


def build_highlights(client_dir: Path, year: int, month: int) -> list[str]:
    out = []
    for fn in (
        _highlight_huntress,
        _highlight_crowdstrike,
        _highlight_me_ec,
        _highlight_veeam_vbr,
        _highlight_vcenter,
    ):
        try:
            text = fn(client_dir, year, month)
        except Exception:
            text = None
        if text:
            out.append(text)
    return out


# ---------------------------------------------------------------------------
# HTML email composition
# ---------------------------------------------------------------------------

def load_signature_html() -> str:
    if not SIGNATURE_PATH.exists():
        return ""
    return SIGNATURE_PATH.read_text(encoding="utf-8", errors="replace")


def build_email_html(client: dict, manifest: dict, highlights: list[str], year: int, month: int) -> str:
    month_label = f"{calendar.month_name[month]} {year}"
    location_name = client.get("Location_Name") or client["LocationCode"]
    code = client["LocationCode"]

    # Highlight bullets
    if highlights:
        hl_html = "<ul>" + "".join(f"<li>{html.escape(h)}</li>" for h in highlights) + "</ul>"
    else:
        hl_html = "<p>This package contains every monitoring report Technijian generated for your environment this month.</p>"

    # Report list with clickable links
    rows = ""
    for u in manifest.get("uploads") or []:
        label = html.escape(u.get("label") or "Report")
        fname = html.escape(u.get("filename") or "")
        web = html.escape(u.get("web_url") or "#")
        rows += (
            f'<tr><td style="padding:6px 12px 6px 0;border-bottom:1px solid #E9ECEF;'
            f'font-family:Open Sans,Arial,sans-serif;color:#1A1A2E;width:170px;">'
            f'<strong>{label}</strong></td>'
            f'<td style="padding:6px 0;border-bottom:1px solid #E9ECEF;'
            f'font-family:Open Sans,Arial,sans-serif;">'
            f'<a href="{web}" style="color:#006DB6;text-decoration:none;">{fname}</a></td></tr>'
        )

    folder_url = manifest.get("month_folder_web_url") or "#"

    body = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#F8F9FA;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#F8F9FA;">
  <tr><td align="center" style="padding:24px 12px;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="640" style="background:#ffffff;border-radius:6px;border:1px solid #E9ECEF;">
      <tr><td style="background:#006DB6;padding:18px 28px;border-radius:6px 6px 0 0;">
        <div style="font-family:Open Sans,Arial,sans-serif;color:#ffffff;font-size:18px;font-weight:bold;">Technijian Monthly Reports</div>
        <div style="font-family:Open Sans,Arial,sans-serif;color:#FEEAD7;font-size:13px;margin-top:4px;">{html.escape(location_name)} — {html.escape(month_label)}</div>
      </td></tr>
      <tr><td style="padding:24px 28px;font-family:Open Sans,Arial,sans-serif;color:#1A1A2E;font-size:14px;line-height:1.5;">
        <p>Hello,</p>
        <p>Your {html.escape(month_label)} monitoring reports are now available. Below is a quick summary of what Technijian observed and delivered for {html.escape(code)} this month, followed by direct links to each report on your team's SharePoint.</p>
        <h3 style="color:#006DB6;font-size:15px;margin:18px 0 8px;">Highlights</h3>
        {hl_html}
        <h3 style="color:#006DB6;font-size:15px;margin:18px 0 8px;">Reports for {html.escape(month_label)}</h3>
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;">{rows}</table>
        <p style="margin-top:18px;">
          <a href="{html.escape(folder_url)}" style="display:inline-block;background:#F67D4B;color:#ffffff;text-decoration:none;padding:10px 20px;border-radius:4px;font-weight:600;">Open Reports Folder</a>
        </p>
        <p style="margin-top:18px;color:#59595B;font-size:13px;">For questions about any item in this package, or to request a different reporting cadence, just reply to this email or write to <a href="mailto:support@technijian.com" style="color:#006DB6;">support@technijian.com</a>. Our team is happy to walk through any detail.</p>
        <p>Thank you for being a Technijian client.</p>
      </td></tr>
      <tr><td style="background:#F8F9FA;padding:14px 28px;border-radius:0 0 6px 6px;border-top:1px solid #E9ECEF;font-family:Open Sans,Arial,sans-serif;color:#59595B;font-size:11px;text-align:center;">
        Technijian | 18 Technology Dr., Ste 141, Irvine, CA 92618 | 949.379.8500 | technijian.com
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>
"""
    return body


def build_subject(client: dict, year: int, month: int) -> str:
    code = client["LocationCode"]
    return f"Technijian Monthly Reports — {code} — {calendar.month_name[month]} {year}"


# ---------------------------------------------------------------------------
# Per-client send
# ---------------------------------------------------------------------------

def process_client(client_dir: Path, year: int, month: int, *, dry_run: bool, to_override: list[str] | None) -> dict:
    slug = client_dir.name
    meta = _safe_load_json(client_dir / "_meta.json")
    if not meta:
        return {"slug": slug, "skipped": "no _meta.json"}
    if not meta.get("Active"):
        return {"slug": slug, "skipped": "client not Active"}
    if not meta.get("Send_Ready"):
        return {"slug": slug, "skipped": "Send_Ready=False"}

    manifest_path = client_dir / "_monthly_report_uploads" / f"{year:04d}-{month:02d}.json"
    manifest = _safe_load_json(manifest_path)
    if not manifest or not manifest.get("uploads"):
        return {"slug": slug, "skipped": f"no upload manifest at {manifest_path.relative_to(REPO_ROOT)}"}

    recipients = list(to_override) if to_override else (meta.get("Recipient_Emails") or [])
    if not recipients:
        return {"slug": slug, "skipped": "no recipients in _meta.json"}

    highlights = build_highlights(client_dir, year, month)
    html_body = build_email_html(meta, manifest, highlights, year, month)
    subject = build_subject(meta, year, month)

    # Always write a preview file so the user can review
    preview_dir = client_dir / "_monthly_report_emails"
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_path = preview_dir / f"{year:04d}-{month:02d}.html"
    preview_path.write_text(html_body, encoding="utf-8")

    if dry_run:
        return {
            "slug": slug,
            "subject": subject,
            "to": recipients,
            "preview": str(preview_path.relative_to(REPO_ROOT)),
            "report_count": len(manifest.get("uploads") or []),
            "highlight_count": len(highlights),
            "dry_run": True,
        }

    result = _send_via_graph(subject, html_body, recipients, cc=["support@technijian.com"])
    return {
        "slug": slug,
        "subject": subject,
        "to": recipients,
        "report_count": len(manifest.get("uploads") or []),
        "send_status": result["status"],
        "send_response": result["body"][:200],
        "sent_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "preview": str(preview_path.relative_to(REPO_ROOT)),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--month", required=True, help="YYYY-MM")
    ap.add_argument("--only", help="Comma-separated client slugs to include")
    ap.add_argument("--skip", help="Comma-separated client slugs to skip")
    ap.add_argument("--to-only", help="Override recipients with this comma-separated list (for review). e.g. support@technijian.com")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--dry-run", action="store_true", default=True)
    grp.add_argument("--apply", action="store_true",
                     help="Actually send the emails. Default is dry-run.")
    args = ap.parse_args(argv)

    dry_run = not args.apply
    year, month = (int(x) for x in args.month.split("-"))
    only = {s.strip().lower() for s in (args.only or "").split(",") if s.strip()}
    skip = {s.strip().lower() for s in (args.skip or "").split(",") if s.strip()}
    to_override = [s.strip() for s in (args.to_only or "").split(",") if s.strip()] or None

    print(f"== Monthly report email {'DRY-RUN' if dry_run else 'APPLY'}: {args.month} ==")
    if to_override:
        print(f"   recipient override: {to_override}")
    print()

    summary: list[dict] = []
    for client_dir in sorted([d for d in CLIENTS_ROOT.iterdir() if d.is_dir() and not d.name.startswith("_")]):
        slug = client_dir.name
        if only and slug not in only:
            continue
        if slug in skip:
            continue
        try:
            r = process_client(client_dir, year, month, dry_run=dry_run, to_override=to_override)
        except Exception as exc:
            r = {"slug": slug, "skipped": f"error: {exc}"}
        summary.append(r)
        print(f"  [{slug}] " + json.dumps({k: v for k, v in r.items() if k != "slug"}, default=str))

    sent = sum(1 for r in summary if r.get("send_status") and 200 <= int(r["send_status"]) < 300)
    skipped = [r for r in summary if r.get("skipped")]
    print(f"\n== Summary ({len(summary)} clients) ==")
    if dry_run:
        print(f"  DRY-RUN — {len(summary) - len(skipped)} email(s) would be sent.")
        print(f"  Previews written to clients/<slug>/_monthly_report_emails/<YYYY-MM>.html")
    else:
        print(f"  sent:    {sent}")
    if skipped:
        print(f"  skipped: {len(skipped)}")
        for r in skipped:
            print(f"    - {r['slug']}: {r.get('skipped')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
