"""Fetch the most recent sent items from rjain@technijian.com via Microsoft
Graph and extract the email signature pattern used. Writes:

  scripts/signature.html  — HTML signature snippet (for HTML body)
  scripts/signature.txt   — plain-text fallback
  scripts/signature-source.md — provenance + raw samples
"""
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

SCRIPTS = Path(__file__).resolve().parent
import sys as _sys
_sys.path.insert(0, str(SCRIPTS))
from _secrets import get_m365_credentials
TENANT_ID, CLIENT_ID, CLIENT_SECRET, MAILBOX = get_m365_credentials()
GRAPH = "https://graph.microsoft.com/v1.0"


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
        return json.loads(resp.read())["access_token"]


def graph_get(token: str, path: str) -> dict:
    req = Request(f"{GRAPH}{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        raise RuntimeError(f"GET {path} {e.code}: {e.read()[:300]}")


def html_to_text(html: str) -> str:
    txt = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.S | re.I)
    txt = re.sub(r"<script[^>]*>.*?</script>", "", txt, flags=re.S | re.I)
    txt = re.sub(r"<br\s*/?>", "\n", txt, flags=re.I)
    txt = re.sub(r"</(p|div|tr)>", "\n", txt, flags=re.I)
    txt = re.sub(r"</t[dh]>", " | ", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
    txt = re.sub(r"\n[ \t]+", "\n", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    return txt.strip()


def find_signature_block(text: str) -> str | None:
    """Heuristic: signature usually starts with the sender's name on its own line
    followed by a title line, contact info, and a tagline/address. Look for a
    block at the bottom that contains 'Technijian' and what appears to be a phone
    pattern."""
    # Drop quoted reply chain
    cleaned = re.split(r"\n(?:On .{5,80} wrote:|From: .+@)", text, maxsplit=1)[0]
    # Heuristic: take the last 30 non-empty lines
    lines = [ln.rstrip() for ln in cleaned.splitlines() if ln.strip()]
    if not lines:
        return None
    # Walk backwards finding 'Ravi' or 'Jain' or 'Technijian' and grab the surrounding 8-15 lines
    for i in range(len(lines) - 1, max(len(lines) - 30, 0), -1):
        if re.search(r"\b(Technijian|technijian\.com|949\.?379)\b", lines[i], re.I):
            # Extend window upward to find the start of the sig
            start = i
            for j in range(i, max(i - 12, -1), -1):
                if re.match(r"^\s*(thanks|thank you|regards|best|cheers|sincerely)[, ]*\s*$", lines[j], re.I):
                    start = j
                    break
                # If we hit a paragraph break (long sentence), stop
                if len(lines[j]) > 90:
                    start = j + 1
                    break
            end = min(i + 6, len(lines))
            return "\n".join(lines[start:end])
    return None


def main() -> None:
    token = get_token()
    print(f"Authenticated. Pulling last 10 sent items from {MAILBOX}...")
    # Sent Items is the well-known folder "sentitems"
    from urllib.parse import quote
    qs = (
        "$top=10"
        "&$select=id,subject,from,toRecipients,sentDateTime,body,bodyPreview"
        "&$orderby=" + quote("sentDateTime desc")
    )
    data = graph_get(token, f"/users/{MAILBOX}/mailFolders/sentitems/messages?{qs}")
    msgs = data.get("value", [])
    print(f"Found {len(msgs)} sent messages.")

    samples_md = ["# Email Signature — provenance\n",
                  f"Source: {MAILBOX} Sent Items, last {len(msgs)} messages.\n"]
    sig_text = None
    sig_html = None
    for m in msgs:
        ctype = m["body"]["contentType"]
        body = m["body"]["content"]
        if ctype.lower() == "html":
            txt = html_to_text(body)
        else:
            txt = body
        sig = find_signature_block(txt)
        samples_md.append(f"\n## {m['sentDateTime']} — {m['subject'][:80]}\n")
        if sig:
            samples_md.append("```\n" + sig[:1200] + "\n```\n")
        else:
            samples_md.append("_(no signature block detected)_\n")
        if sig and not sig_text:
            sig_text = sig
            # Try to find the HTML version of just the signature
            # Heuristic: look for the rendered text fragment in the HTML
            if ctype.lower() == "html":
                # Use the lines of sig_text to slice the HTML
                last_line = sig.splitlines()[-1].strip()
                first_line = sig.splitlines()[0].strip()
                # Find the index in the html where the first signature line appears
                # then take everything from there to end (approx)
                # We strip everything after </body> too
                idx = body.lower().find(first_line.lower()[:30])
                if idx >= 0:
                    end_idx = body.lower().find("</body>", idx)
                    if end_idx < 0:
                        end_idx = len(body)
                    sig_html_raw = body[idx:end_idx]
                    # cut at next obvious quoted-reply marker
                    cut = re.split(r"<div[^>]*>?\s*From:\s*", sig_html_raw, maxsplit=1, flags=re.I)
                    sig_html = cut[0]

    # Write outputs
    if sig_text:
        (SCRIPTS / "signature.txt").write_text(sig_text + "\n", encoding="utf-8")
        print(f"Wrote signature.txt ({len(sig_text)} chars)")
        if sig_html:
            (SCRIPTS / "signature.html").write_text(sig_html.strip() + "\n", encoding="utf-8")
            print(f"Wrote signature.html ({len(sig_html)} chars)")
    else:
        print("WARNING: No signature could be extracted from sent items.")

    (SCRIPTS / "signature-source.md").write_text("\n".join(samples_md), encoding="utf-8")
    print(f"Wrote signature-source.md")


if __name__ == "__main__":
    main()
