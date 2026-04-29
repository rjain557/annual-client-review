"""Create + send weekly tech training emails via Microsoft Graph.

For each tech slug under technijian/weekly-audit/<cycle>/by-tech/<slug>/ that
has both a `<slug>-Weekly-Training.docx` and `flagged-entries.csv`, this script
posts a draft to RJain's mailbox with both attached, then immediately sends it
(unless --drafts-only is passed).

Email recipient resolution reuses the directory cache from the annual pipeline
at technijian/tech-training/scripts/tech-emails.json.

Usage:
    python 4_email_weekly.py                  # create drafts + send
    python 4_email_weekly.py --drafts-only    # create drafts, do not send
    python 4_email_weekly.py --send-existing  # skip create, just send the manifest
    python 4_email_weekly.py --cycle 2026-W18 --only S-Kumar
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _shared import (
    TECH_TRAINING_SCRIPTS,
    cycle_dir,
    cycle_id_for,
    now_pacific,
)

# Reuse the existing M365 secrets resolver
sys.path.insert(0, str(TECH_TRAINING_SCRIPTS))
from _secrets import get_m365_credentials  # type: ignore  # noqa: E402

TENANT_ID, CLIENT_ID, CLIENT_SECRET, MAILBOX = get_m365_credentials()
GRAPH = "https://graph.microsoft.com/v1.0"
DOMAIN = "technijian.com"

# Reuse the directory cache built by _resolve-tech-emails.py
TECH_CACHE_PATH = TECH_TRAINING_SCRIPTS / "tech-emails.json"
SIG_HTML_PATH = TECH_TRAINING_SCRIPTS / "signature.html"

# CEO and any other slugs that should not receive these emails
EXCLUDE_SLUGS = {"R-Jain"}


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def get_token() -> str:
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = urlencode({
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode()
    req = Request(url, data=data, method="POST",
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if "access_token" not in body:
        raise RuntimeError(f"Token failure: {body}")
    return body["access_token"]


def graph_post(token: str, path: str, body: dict | None = None) -> tuple[int, dict | str]:
    url = f"{GRAPH}{path}"
    data = json.dumps(body).encode() if body is not None else b""
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    else:
        headers["Content-Length"] = "0"
    req = Request(url, data=data if body is not None else None,
                  method="POST", headers=headers)
    try:
        with urlopen(req, timeout=60) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return resp.status, raw.decode("utf-8", errors="replace")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def graph_delete(token: str, path: str) -> bool:
    req = Request(f"{GRAPH}{path}", method="DELETE",
                  headers={"Authorization": f"Bearer {token}"})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.status in (200, 204)
    except HTTPError as e:
        return e.code in (404, 410)


# ---------------------------------------------------------------------------
# Email body
# ---------------------------------------------------------------------------

def slug_to_display(slug: str) -> str:
    parts = slug.split("-")
    if len(parts) >= 2:
        return f"{parts[0]}. {' '.join(parts[1:])}"
    return slug


def load_tech_cache() -> dict:
    if TECH_CACHE_PATH.exists():
        return json.loads(TECH_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def slug_to_email(slug: str, cache: dict) -> str:
    entry = cache.get(slug) or {}
    if entry.get("resolved") and entry.get("address"):
        return entry["address"]
    parts = slug.split("-")
    if len(parts) == 2:
        return f"{parts[0].lower()}{parts[1].lower()}@{DOMAIN}"
    return f"{slug.lower().replace('-', '.')}@{DOMAIN}"


def load_signature() -> str:
    if SIG_HTML_PATH.exists():
        return SIG_HTML_PATH.read_text(encoding="utf-8")
    return ""


FLAG_DESCRIPTIONS = {
    "H1": "logging more time than expected on routine work (patches, agent updates, monitoring alerts)",
    "H2": "using vague titles like \"Help\", \"Fix\", or \"Issue\" on entries longer than 30 minutes",
    "H3": "logging a single time-block over 8 hours - break it into separate entries",
    "H4": "exceeding 12 hours total in one day across tickets - verify the dates",
    "H5": "creating multiple entries on the same ticket on the same day - consolidate them",
}


def summarize_csv(csv_path: Path) -> dict:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    flagged_entries = len(rows)
    flagged_hours = sum(float(r["Hours"]) for r in rows)
    flag_counts: dict = {}
    for r in rows:
        for c in (r.get("Flags") or "").split(";"):
            if c:
                flag_counts[c] = flag_counts.get(c, 0) + 1
    top_flag = max(flag_counts.items(), key=lambda kv: kv[1])[0] if flag_counts else None
    clients = sorted({r["Client"] for r in rows})
    return {
        "flagged_entries": flagged_entries,
        "flagged_hours": flagged_hours,
        "top_flag": top_flag,
        "clients": clients,
    }


def invoice_evening_label() -> str:
    """Returns 'tonight (Friday May 1) at end of day'."""
    today = now_pacific()
    return f"tonight ({today.strftime('%A %B %-d')}) at end of day" if sys.platform != "win32" \
        else f"tonight ({today.strftime('%A %B %#d')}) at end of day"


def build_html_body(slug: str, display: str, cycle: str,
                     summary: dict, signature_html: str) -> str:
    pct_focus = ""
    if summary["top_flag"] and summary["top_flag"] in FLAG_DESCRIPTIONS:
        pct_focus = (
            f'<p>Your most common pattern this week is '
            f'<b style="color:#F67D4B">{summary["top_flag"]}</b> - '
            f'{FLAG_DESCRIPTIONS[summary["top_flag"]]}. '
            f'The attached training document walks through your specific entries '
            f'and gives a model rewrite for each.</p>'
        )

    clients_str = ", ".join(c.upper() for c in summary["clients"])
    deadline = invoice_evening_label()

    return f"""<html><body style="font-family:'Open Sans',Arial,sans-serif;color:#1A1A2E;font-size:11pt;line-height:1.5;">
<div style="height:6px;background:#006DB6;margin-bottom:20px;"></div>

<p>Hi {display},</p>

<p>This is the weekly time-entry review for cycle <b>{cycle}</b>. The audit ran
this morning and flagged <b>{summary['flagged_entries']} of your entries</b>
totalling <b>{summary['flagged_hours']:.2f} hours</b> across these clients:
{clients_str}.</p>

{pct_focus}

<p style="background:#F8F9FA;border-left:4px solid #F67D4B;padding:12px 16px;margin:16px 0;">
<b>Action requested before {deadline}:</b><br>
Weekly in-contract invoices go out this evening. For each flagged entry, please
either rewrite the title (so the hours make sense to a client reading the
invoice) or reduce the hours to the suggested cap. The attached CSV lists the
specific entries plus a model rewrite and suggested hours for each.
</p>

<p><b>Two attachments:</b></p>
<ul>
  <li><b>{slug}-Weekly-Training.docx</b> - branded weekly review with your
      stats, flag breakdown, per-entry suggested rewrites, and the six rules
      that prevent flags going forward.</li>
  <li><b>flagged-entries.csv</b> - every flagged entry with InvDetID,
      suggested adjusted hours, suggested title rewrite, and the reason it was
      flagged. Open in Excel and use the InvDetID to find the entry in the
      Client Portal.</li>
</ul>

<p><b>What happens if I do not adjust:</b> the entry will appear on tonight's
client invoice exactly as you logged it. There is no automatic deletion - but
patterns that repeat from week to week will be reviewed with your team lead.</p>

<p>If a flag looks wrong (a one-off that genuinely required the time, or work
mis-classified by the audit), reply with the date and ticket and I will tune
the rules so it stops flagging.</p>

{signature_html}

</body></html>"""


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def attachment(path: Path, mime: str) -> dict:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": path.name,
        "contentType": mime,
        "contentBytes": b64(path),
    }


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def manifest_path(cycle_root: Path) -> Path:
    return cycle_root / "by-tech" / "outlook-drafts-created.csv"


def sent_log_path(cycle_root: Path) -> Path:
    return cycle_root / "by-tech" / "outlook-drafts-sent.csv"


def delete_existing_drafts(token: str, mp: Path) -> int:
    if not mp.exists():
        return 0
    deleted = 0
    with mp.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            did = row.get("draft_id") or ""
            if not did or row.get("error"):
                continue
            if graph_delete(token, f"/users/{MAILBOX}/messages/{did}"):
                deleted += 1
    return deleted


# ---------------------------------------------------------------------------
# Create + send
# ---------------------------------------------------------------------------

def create_draft_for(token: str, cycle: str, cycle_root: Path,
                      slug: str, cache: dict, sig_html: str) -> dict:
    folder = cycle_root / "by-tech" / slug
    docx_path = folder / f"{slug}-Weekly-Training.docx"
    csv_path = folder / "flagged-entries.csv"
    if not docx_path.exists() or not csv_path.exists():
        return {"slug": slug, "error": "missing docx or csv"}

    summary = summarize_csv(csv_path)
    if summary["flagged_entries"] == 0:
        return {"slug": slug, "skipped": "no flagged entries"}

    display = slug_to_display(slug)
    to_addr = slug_to_email(slug, cache)
    subject = (f"[Action] Weekly time-entry review {cycle} - "
               f"{summary['flagged_entries']} entries to adjust before tonight's invoice")

    msg = {
        "subject": subject,
        "body": {
            "contentType": "HTML",
            "content": build_html_body(slug, display, cycle, summary, sig_html),
        },
        "toRecipients": [{"emailAddress": {"address": to_addr}}],
        "attachments": [
            attachment(docx_path,
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            attachment(csv_path, "text/csv"),
        ],
    }
    status, body = graph_post(token, f"/users/{MAILBOX}/messages", msg)
    if status >= 400:
        snippet = body if isinstance(body, str) else json.dumps(body)[:300]
        return {"slug": slug, "to": to_addr, "error": f"{status}: {snippet[:280]}"}

    info = {
        "slug": slug,
        "display": display,
        "to": to_addr,
        "draft_id": body.get("id") if isinstance(body, dict) else None,
        "web_link": body.get("webLink") if isinstance(body, dict) else None,
        "flagged_entries": summary["flagged_entries"],
        "flagged_hours": round(summary["flagged_hours"], 2),
        "top_flag": summary["top_flag"] or "",
    }
    return info


def send_draft(token: str, draft_id: str) -> tuple[int, str]:
    status, body = graph_post(token, f"/users/{MAILBOX}/messages/{draft_id}/send")
    return status, (body if isinstance(body, str) else json.dumps(body))[:300]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycle", help="cycle ID (default = current ISO week)")
    ap.add_argument("--only", help="comma-separated tech slugs")
    ap.add_argument("--drafts-only", action="store_true",
                     help="create drafts but do not send")
    ap.add_argument("--send-existing", action="store_true",
                     help="skip create; send drafts listed in the manifest")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    cycle = args.cycle or cycle_id_for()
    cycle_root = cycle_dir(cycle)
    by_tech = cycle_root / "by-tech"
    if not by_tech.exists():
        print(f"  no by-tech folder at {by_tech}; run 2_audit_weekly.py + 3_build_weekly_docs.py first.")
        return 1

    only = None
    if args.only:
        only = {s.strip() for s in args.only.split(",") if s.strip()}

    print(f"[{datetime.now():%H:%M:%S}] cycle={cycle} mailbox={MAILBOX}")
    print(f"  workspace: {cycle_root}")

    print("Authenticating to Microsoft Graph...")
    token = get_token()
    sig_html = load_signature()
    cache = load_tech_cache()
    mp = manifest_path(cycle_root)

    if args.send_existing:
        if not mp.exists():
            print(f"  manifest not found at {mp}; nothing to send.")
            return 1
        with mp.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        drafts = [r for r in rows if r.get("draft_id") and not r.get("error")]
        print(f"Sending {len(drafts)} drafts from manifest...")
        sent, failed = [], []
        for r in drafts:
            status, body = send_draft(token, r["draft_id"])
            ts = datetime.utcnow().isoformat() + "Z"
            if status in (200, 202, 204):
                print(f"  SENT  {r.get('display','?'):<22} -> {r.get('to','?')}")
                sent.append({**r, "sent_at": ts, "status": status})
            else:
                print(f"  FAIL  {r.get('display','?'):<22} -> {r.get('to','?')}  [{status}] {body[:120]}")
                failed.append({**r, "sent_at": ts, "status": status, "error_body": body})
        log = sent + failed
        with sent_log_path(cycle_root).open("w", encoding="utf-8", newline="") as f:
            fields = ["sent_at", "display", "to", "draft_id", "status",
                      "flagged_entries", "flagged_hours", "top_flag", "error_body"]
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in log:
                w.writerow(r)
        print(f"\nSent: {len(sent)}  Failed: {len(failed)}")
        return 0 if not failed else 2

    # create drafts
    if mp.exists():
        n = delete_existing_drafts(token, mp)
        if n:
            print(f"  deleted {n} prior draft(s) from previous run")

    results = []
    for d in sorted(by_tech.iterdir()):
        if not d.is_dir():
            continue
        slug = d.name
        if slug in EXCLUDE_SLUGS:
            print(f"  SKIP {slug} (excluded)")
            continue
        if only is not None and slug not in only:
            continue
        info = create_draft_for(token, cycle, cycle_root, slug, cache, sig_html)
        results.append(info)
        if "error" in info:
            print(f"  ERR  {slug:<22} -> {info.get('to','?'):<40}  {info['error'][:140]}")
        elif "skipped" in info:
            print(f"  --   {slug:<22}  ({info['skipped']})")
        else:
            print(f"  OK   {info['display']:<22} -> {info['to']:<40}  draft id: {(info['draft_id'] or '')[:24]}...")

    # write manifest
    with mp.open("w", encoding="utf-8", newline="") as f:
        fields = ["slug", "display", "to", "flagged_entries", "flagged_hours",
                  "top_flag", "draft_id", "web_link", "error"]
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(r)

    ok_drafts = [r for r in results if r.get("draft_id") and not r.get("error")]
    print(f"\nCreated drafts: {len(ok_drafts)}")
    print(f"Manifest:       {mp}")

    if args.drafts_only:
        print(f"\n--drafts-only set; skipping send. "
              f"Run with --send-existing when ready.")
        return 0

    # send all newly-created drafts
    print(f"\nSending {len(ok_drafts)} drafts...")
    sent, failed = [], []
    for r in ok_drafts:
        status, body = send_draft(token, r["draft_id"])
        ts = datetime.utcnow().isoformat() + "Z"
        if status in (200, 202, 204):
            print(f"  SENT  {r['display']:<22} -> {r['to']}")
            sent.append({**r, "sent_at": ts, "status": status})
        else:
            print(f"  FAIL  {r['display']:<22} -> {r['to']}  [{status}] {body[:120]}")
            failed.append({**r, "sent_at": ts, "status": status, "error_body": body})

    with sent_log_path(cycle_root).open("w", encoding="utf-8", newline="") as f:
        fields = ["sent_at", "display", "to", "draft_id", "status",
                  "flagged_entries", "flagged_hours", "top_flag", "error_body"]
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in sent + failed:
            w.writerow(r)

    print(f"\nSent: {len(sent)}  Failed: {len(failed)}")
    print(f"Sent log: {sent_log_path(cycle_root)}")
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
