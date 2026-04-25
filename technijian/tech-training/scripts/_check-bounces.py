"""Check inbox for recent NDR / undeliverable bounce messages from the
training emails."""
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote
from urllib.error import HTTPError

from _secrets import get_m365_credentials
TENANT, CID, SEC, MBOX = get_m365_credentials()
GRAPH = "https://graph.microsoft.com/v1.0"


def tok():
    r = Request(f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
        data=urlencode({"client_id": CID, "client_secret": SEC,
                        "scope": "https://graph.microsoft.com/.default",
                        "grant_type": "client_credentials"}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    return json.loads(urlopen(r).read())["access_token"]


def gget(token, path):
    req = Request(f"{GRAPH}{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        return {"error": e.code, "body": e.read().decode("utf-8", errors="replace")[:300]}


t = tok()
# Get inbox messages received in the last 1 hour, filter for NDR senders
since = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds").replace("+00:00", "Z")
qs = (f"$top=20&$orderby=" + quote("receivedDateTime desc")
      + "&$select=" + quote("id,subject,from,receivedDateTime,bodyPreview")
      + "&$filter=" + quote(f"receivedDateTime ge {since}"))
data = gget(t, f"/users/{MBOX}/messages?{qs}")
if "error" in data:
    print(f"ERR: {data}")
else:
    print(f"Last 2h inbox ({len(data.get('value', []))} messages):\n")
    for m in data["value"]:
        sender = (m.get("from") or {}).get("emailAddress", {})
        addr = sender.get("address", "?")
        subj = m.get("subject") or ""
        is_ndr = bool(re.search(r"undeliver|delivery failed|delivery has failed|returned mail|not\s*delivered|postmaster", subj + " " + addr, re.I))
        marker = " [NDR]" if is_ndr else ""
        print(f"  {m['receivedDateTime']}  FROM {addr:<40} | {subj[:80]}{marker}")
        if is_ndr:
            preview = (m.get("bodyPreview") or "")[:400].replace("\n", " ")
            print(f"      preview: {preview}")
