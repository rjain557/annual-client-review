"""Dump the most recent sent message's full HTML body so we can read the
signature directly."""
import json
from urllib.request import Request, urlopen
from urllib.parse import quote, urlencode
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
import sys as _sys
_sys.path.insert(0, str(SCRIPTS))
from _secrets import get_m365_credentials
TENANT, CID, SEC, MBOX = get_m365_credentials()


def tok():
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


t = tok()
qs = "$top=10&$select=subject,sentDateTime,body,toRecipients&$orderby=" + quote("sentDateTime desc")
r = Request(
    f"https://graph.microsoft.com/v1.0/users/{MBOX}/mailFolders/sentitems/messages?{qs}",
    headers={"Authorization": f"Bearer {t}"},
)
data = json.loads(urlopen(r).read())
out = SCRIPTS / "_sent-samples-raw.html"
buf = []
for i, m in enumerate(data["value"]):
    buf.append(f"<!-- ===== {i}: {m['sentDateTime']} | {m['subject']} ===== -->\n")
    buf.append(m["body"]["content"])
    buf.append("\n\n")
out.write_text("".join(buf), encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size:,} bytes, {len(data['value'])} messages)")
