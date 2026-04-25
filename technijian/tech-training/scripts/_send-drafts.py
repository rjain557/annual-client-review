"""Send the previously-created drafts via Microsoft Graph.

Reads `2026/by-tech/outlook-drafts-created.csv` (or the year passed on CLI),
then POSTs `/users/{mailbox}/messages/{id}/send` for each draft.

Usage: python _send-drafts.py [YEAR]
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent.parent.parent
YEAR = sys.argv[1] if len(sys.argv) > 1 else "2026"
MANIFEST = REPO / "technijian" / "tech-training" / YEAR / "by-tech" / "outlook-drafts-created.csv"
SENT_LOG = REPO / "technijian" / "tech-training" / YEAR / "by-tech" / "outlook-drafts-sent.csv"

import sys as _sys
_sys.path.insert(0, str(SCRIPTS))
from _secrets import get_m365_credentials
TENANT, CID, SEC, MBOX = get_m365_credentials()
GRAPH = "https://graph.microsoft.com/v1.0"


def get_token() -> str:
    r = Request(
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
        data=urlencode({
            "client_id": CID, "client_secret": SEC,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return json.loads(urlopen(r).read())["access_token"]


def graph_post(token: str, path: str) -> tuple[int, str]:
    req = Request(f"{GRAPH}{path}", method="POST",
                  headers={"Authorization": f"Bearer {token}", "Content-Length": "0"})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.status, ""
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return e.code, body


def main() -> None:
    if not MANIFEST.exists():
        print(f"No manifest at {MANIFEST}. Run _create-outlook-drafts.py first.")
        return

    print(f"Authenticating to Microsoft Graph...")
    token = get_token()
    print(f"  mailbox: {MBOX}")
    print(f"  manifest: {MANIFEST}")
    print()

    with MANIFEST.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    drafts = [r for r in rows if r.get("draft_id") and not r.get("error")]
    print(f"Sending {len(drafts)} drafts...")
    print()

    sent = []
    failed = []
    for r in drafts:
        did = r["draft_id"]
        to = r["to"]
        display = r["display"]
        status, body = graph_post(token, f"/users/{MBOX}/messages/{did}/send")
        if status in (200, 202, 204):
            print(f"  SENT  {display:<22} -> {to}")
            sent.append({**r, "sent_at": datetime.utcnow().isoformat() + "Z", "status": status})
        else:
            print(f"  FAIL  {display:<22} -> {to}   [{status}] {body[:120]}")
            failed.append({**r, "sent_at": datetime.utcnow().isoformat() + "Z",
                           "status": status, "error_body": body})

    # write sent log
    fields = ["sent_at", "display", "to", "draft_id", "status", "flagged",
              "flagged_hours", "top_flag", "error_body"]
    with SENT_LOG.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for s in sent + failed:
            w.writerow(s)

    print()
    print(f"Sent:   {len(sent)}")
    print(f"Failed: {len(failed)}")
    print(f"Log:    {SENT_LOG}")


if __name__ == "__main__":
    main()
