"""Create draft emails in rjain@technijian.com's Outlook Drafts folder via
Microsoft Graph (app-only / client credentials).

For each tech with a flagged-entries.csv + Training.docx in
2026/by-tech/<slug>/, builds the same body the .eml drafter uses and POSTs it
as a draft message with both files attached.

NOTE: Drafts are created — NOT sent. They appear in the Outlook Drafts folder
of rjain@technijian.com for manual review and send.

Usage: python _create-outlook-drafts.py [YEAR]
"""
import base64
import csv
import json
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent.parent.parent
YEAR = sys.argv[1] if len(sys.argv) > 1 else "2026"
ROOT = REPO / "technijian" / "tech-training" / YEAR
BY_TECH = ROOT / "by-tech"

# --- Credentials (from C:\Users\rjain\OneDrive - Technijian, Inc\Documents\VSCODE\keys\m365-graph.md) ---
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from _secrets import get_m365_credentials
TENANT_ID, CLIENT_ID, CLIENT_SECRET, MAILBOX = get_m365_credentials()
GRAPH = "https://graph.microsoft.com/v1.0"
DOMAIN = "technijian.com"

# Override addresses if known (slug -> email)
EMAIL_OVERRIDES: dict[str, str] = {
    # "S-Kumar-Sharma": "skumarsharma@technijian.com",
}


# Load the user's actual signature (extracted from Sent Items)
SIG_HTML = (SCRIPTS / "signature.html").read_text(encoding="utf-8") if (SCRIPTS / "signature.html").exists() else ""
SIG_TXT = (SCRIPTS / "signature.txt").read_text(encoding="utf-8") if (SCRIPTS / "signature.txt").exists() else ""


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


def graph_delete(token: str, path: str) -> bool:
    url = f"{GRAPH}{path}"
    req = Request(url, method="DELETE", headers={"Authorization": f"Bearer {token}"})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.status in (200, 204)
    except HTTPError as e:
        if e.code in (404, 410):
            return True
        raise RuntimeError(f"Graph DELETE {path} failed {e.code}: {e.read()[:200]}") from None


def delete_existing_drafts(token: str) -> int:
    """Read outlook-drafts-created.csv (if present) and delete prior draft IDs."""
    manifest = BY_TECH / "outlook-drafts-created.csv"
    if not manifest.exists():
        return 0
    deleted = 0
    with manifest.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            did = row.get("draft_id") or ""
            if not did or row.get("error"):
                continue
            try:
                if graph_delete(token, f"/users/{MAILBOX}/messages/{did}"):
                    deleted += 1
            except RuntimeError as e:
                print(f"  delete-fail {did[:24]}…: {e}")
    return deleted


def graph_post(token: str, path: str, body: dict) -> dict:
    url = f"{GRAPH}{path}"
    data = json.dumps(body).encode()
    req = Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Graph POST {path} failed {e.code}: {err_body}") from None


# ---- email body / address derivation (same logic as _draft-tech-emails.py) ----

def slug_to_display(slug: str) -> str:
    m = re.match(r"([A-Z])-(.+)", slug)
    if m:
        return f"{m.group(1)}. {m.group(2).replace('-', ' ')}"
    return slug.replace("-", " ")


_TECH_CACHE_PATH = SCRIPTS / "tech-emails.json"
_TECH_CACHE: dict = {}
if _TECH_CACHE_PATH.exists():
    import json as _json
    _TECH_CACHE = _json.loads(_TECH_CACHE_PATH.read_text(encoding="utf-8"))


def slug_to_email(slug: str) -> str:
    # 1. explicit override (legacy, still supported)
    if slug in EMAIL_OVERRIDES:
        return EMAIL_OVERRIDES[slug]
    # 2. directory cache populated by _resolve-tech-emails.py
    cached = _TECH_CACHE.get(slug)
    if cached and cached.get("resolved") and cached.get("address"):
        return cached["address"]
    # 3. fall back to slug pattern (and warn — should not happen post-resolve)
    parts = slug.split("-")
    if len(parts) == 2:
        return f"{parts[0].lower()}{parts[1].lower()}@{DOMAIN}"
    return f"{slug.lower().replace('-', '.')}@{DOMAIN}"


def read_summary(slug: str) -> dict:
    md = (BY_TECH / slug / "training.md").read_text(encoding="utf-8")
    def grab(pattern, cast=str, default=0):
        m = re.search(pattern, md)
        if not m:
            return default
        try:
            return cast(m.group(1).replace(",", ""))
        except ValueError:
            return default
    return {
        "total_entries": grab(r"Total entries logged:\*\*\s*([\d,]+)", int),
        "total_hours": grab(r"Total hours logged:\*\*\s*([\d,\.]+)", float, 0.0),
        "flagged_entries": grab(r"Flagged entries:\*\*\s*(\d+)", int),
        "flagged_hours": grab(r"Flagged hours:\*\*\s*([\d,\.]+)", float, 0.0),
    }


def top_flag_code(slug: str) -> str | None:
    counts: dict[str, int] = {}
    with (BY_TECH / slug / "flagged-entries.csv").open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            for c in (row.get("Flags") or "").split(";"):
                if c:
                    counts[c] = counts.get(c, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


FLAG_DESCRIPTIONS = {
    "H1": "logging more time than expected on routine work (patch, agent updates, monitoring alerts)",
    "H2": "using vague titles like \"Help\", \"Fix\", or \"Issue\" on entries longer than 30 minutes",
    "H3": "logging a single time-block over 8 hours — break into separate entries",
    "H4": "exceeding 12 hours total in one day across tickets — verify dates",
    "H5": "creating multiple entries on the same ticket on the same day — consolidate them",
}


def build_html_body(slug: str, display: str, summary: dict, top_flag: str | None) -> str:
    pct_e = summary["flagged_entries"] / max(summary["total_entries"], 1) * 100
    pct_h = summary["flagged_hours"] / max(summary["total_hours"], 0.01) * 100
    focus = ""
    if top_flag and top_flag in FLAG_DESCRIPTIONS:
        focus = (
            f'<p><b>Your most common flag is <span style="color:#F67D4B">{top_flag}</span></b> — '
            f'{FLAG_DESCRIPTIONS[top_flag]}. The attached training document walks through your '
            f'specific entries and what to change going forward.</p>'
        )
    return f"""<html><body style="font-family:'Open Sans',Arial,sans-serif;color:#1A1A2E;font-size:11pt;line-height:1.5;">
<div style="height:6px;background:#006DB6;margin-bottom:20px;"></div>

<p>Hi {display},</p>

<p>As part of an internal effort to clean up how Technijian time entries appear on client invoices,
I ran a review of every time entry logged across all clients during {YEAR}. The goal is not to
audit anyone — it is to give each tech a personal view of where the entries they log might look
unreasonable to a client reading their weekly in-contract invoice, so we can correct things
<em>before</em> the invoice is committed.</p>

<p><b>Your {YEAR} numbers:</b></p>
<ul>
  <li>You logged <b>{summary['total_entries']:,} time entries</b> totalling <b>{summary['total_hours']:,.2f} hours</b>
      across all clients.</li>
  <li>The audit flagged <b>{summary['flagged_entries']} entries ({summary['flagged_hours']:,.2f} hours)</b> —
      <b>{pct_e:.1f}%</b> of your entries by count, <b>{pct_h:.1f}%</b> by hours.</li>
</ul>

{focus}

<p><b>Two attachments to review:</b></p>
<ul>
  <li><b>{slug}-Training.docx</b> — your personalized branded training document. Cover page, your
      stats, breakdown by client and category, your 12 most-flagged entries, and concrete advice
      on what to write differently next time.</li>
  <li><b>flagged-entries.csv</b> — every flagged entry of yours (client, date, title, hours, cap,
      flag codes, reasons). Filterable in Excel.</li>
</ul>

<p style="background:#F8F9FA;border-left:4px solid #F67D4B;padding:12px 16px;margin:16px 0;">
<b>New weekly cadence — starting this week:</b><br>
Every <b>Thursday</b> we will run this scan against the week's logged entries and email each tech
their personalized flagged-entries list <b>before</b> Friday's weekly in-contract invoice is
committed. That gives you a window to revise titles, consolidate duplicate entries, or reassign
hours so your time appears the way it should on the invoice the client receives.
</p>

<p><b>What you can do today:</b></p>
<ol>
  <li>Open the attached training document and read the personalized advice.</li>
  <li>Skim the CSV to see your specific flagged entries.</li>
  <li>Going forward, follow the six general rules at the bottom of the training doc — most
      flags disappear when titles are descriptive and same-ticket entries are consolidated.</li>
</ol>

<p>If anything in the analysis looks wrong (mis-classified work, a one-off P1 incident that
genuinely needed the time), reply with the date and ticket and I will adjust the rules so it
does not flag next time.</p>

{SIG_HTML}

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


def create_draft(token: str, slug: str) -> dict | None:
    folder = BY_TECH / slug
    docx_path = folder / f"{slug}-Training.docx"
    csv_path = folder / "flagged-entries.csv"
    if not docx_path.exists() or not csv_path.exists():
        return {"slug": slug, "error": "missing artifacts"}

    display = slug_to_display(slug)
    to_addr = slug_to_email(slug)
    summary = read_summary(slug)
    top_flag = top_flag_code(slug)

    msg = {
        "subject": f"[Action] Your {YEAR} time-entry training review — adjustments before Friday invoices",
        "body": {
            "contentType": "HTML",
            "content": build_html_body(slug, display, summary, top_flag),
        },
        "toRecipients": [{"emailAddress": {"address": to_addr}}],
        "attachments": [
            attachment(docx_path,
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            attachment(csv_path, "text/csv"),
        ],
    }

    try:
        result = graph_post(token, f"/users/{MAILBOX}/messages", msg)
        return {
            "slug": slug,
            "display": display,
            "to": to_addr,
            "draft_id": result.get("id"),
            "web_link": result.get("webLink"),
            "is_draft": result.get("isDraft"),
            "flagged": summary["flagged_entries"],
            "flagged_hours": round(summary["flagged_hours"], 2),
            "top_flag": top_flag or "",
        }
    except RuntimeError as e:
        return {"slug": slug, "error": str(e)[:300]}


def main() -> None:
    if not BY_TECH.exists():
        print(f"No by-tech folder at {BY_TECH}. Run _audit-all-clients.py first.")
        return

    print("Authenticating to Microsoft Graph...")
    token = get_token()
    print(f"  token acquired (length {len(token)})")
    print(f"  mailbox: {MAILBOX}")
    print(f"  signature loaded: html={len(SIG_HTML)} chars, txt={len(SIG_TXT)} chars")
    print()

    # Delete any prior drafts from a previous run (avoid duplicates)
    n = delete_existing_drafts(token)
    if n:
        print(f"  Deleted {n} prior draft(s) from previous run.\n")

    # Skip the CEO and any other excluded slugs
    EXCLUDE = {"R-Jain"}

    results = []
    for d in sorted(BY_TECH.iterdir()):
        if not d.is_dir():
            continue
        if d.name in EXCLUDE:
            print(f"  SKIP {d.name} (excluded — CEO)")
            continue
        info = create_draft(token, d.name)
        if not info:
            continue
        results.append(info)
        if "error" in info:
            print(f"  ERR  {d.name}: {info['error'][:120]}")
        else:
            print(f"  OK   {info['display']:<22} -> {info['to']:<40}  draft id: {info['draft_id'][:24]}…")

    # write results manifest
    manifest = BY_TECH / "outlook-drafts-created.csv"
    with manifest.open("w", encoding="utf-8", newline="") as f:
        flds = ["slug", "display", "to", "flagged", "flagged_hours", "top_flag",
                "is_draft", "draft_id", "web_link", "error"]
        w = csv.DictWriter(f, fieldnames=flds, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(r)
    ok = [r for r in results if not r.get("error")]
    err = [r for r in results if r.get("error")]
    print()
    print(f"Created drafts: {len(ok)}")
    print(f"Errors:         {len(err)}")
    print(f"Manifest:       {manifest}")
    print()
    print(f"Open Outlook on {MAILBOX} -> Drafts folder to review and send.")


if __name__ == "__main__":
    main()
