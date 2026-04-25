"""Resolve each tech's actual email address from RJain's mailbox history,
then cache to tech-emails.json.

Strategy (Mail.Read only — no User.Read.All available):
1. For each tech name (from by-tech/ slug), search RJain's mailbox using Graph
   $search across messages in Sent + Inbox folders for the tech's surname.
2. Walk From/ToRecipients/CcRecipients of matched messages, collect every
   @technijian.com address whose display name contains the tech's surname or
   first-initial+surname.
3. Score each candidate and pick the most likely match.
4. Cache to tech-emails.json. On re-runs, skip already-cached techs unless
   --refresh is passed.

Usage:
  python _resolve-tech-emails.py [YEAR]
  python _resolve-tech-emails.py [YEAR] --refresh
"""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote
from urllib.error import HTTPError

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent.parent.parent
YEAR = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "2026"
REFRESH = "--refresh" in sys.argv
BY_TECH = REPO / "technijian" / "tech-training" / YEAR / "by-tech"
CACHE = SCRIPTS / "tech-emails.json"

import sys as _sys
_sys.path.insert(0, str(SCRIPTS))
from _secrets import get_m365_credentials
TENANT, CID, SEC, MBOX = get_m365_credentials()
GRAPH = "https://graph.microsoft.com/v1.0"
DOMAIN = "technijian.com"


def get_token() -> str:
    r = Request(
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
        data=urlencode({"client_id": CID, "client_secret": SEC,
                        "scope": "https://graph.microsoft.com/.default",
                        "grant_type": "client_credentials"}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return json.loads(urlopen(r).read())["access_token"]


def graph_get(token: str, path: str) -> dict:
    req = Request(f"{GRAPH}{path}", headers={
        "Authorization": f"Bearer {token}",
        "ConsistencyLevel": "eventual",   # required for $search
    })
    try:
        with urlopen(req, timeout=45) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode("utf-8", errors="replace")[:300]}


def slug_to_parts(slug: str) -> tuple[str, str]:
    """Return (first_initial, lastname-with-spaces) from slug like 'P-Biswal' or 'S-Kumar-Sharma'."""
    parts = slug.split("-")
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return "", slug


def slug_to_display(slug: str) -> str:
    fi, ln = slug_to_parts(slug)
    return f"{fi}. {ln}" if fi else ln


def candidates_from_recipients(recipients: list[dict], target_first: str, target_last: str) -> list[dict]:
    """Walk a recipient list, return technijian.com addresses where:
      - The displayName's first WORD starts with the target first initial (REQUIRED)
      - The displayName contains the lastname (or all surname words for compound names) (REQUIRED)
    Score by completeness so we prefer fully-named entries over bare email-as-name."""
    out = []
    surname_words = [w.lower() for w in target_last.split() if w]
    target_first_lower = target_first.lower() if target_first else ""
    for r in recipients or []:
        ea = r.get("emailAddress") or {}
        addr = (ea.get("address") or "").lower()
        name = (ea.get("name") or "").strip()
        if not addr.endswith(f"@{DOMAIN}"):
            continue
        # Skip distribution lists / shared mailboxes
        if any(s in addr for s in ("noreply", "no-reply", "postmaster", "@office365.")):
            continue

        name_lower = name.lower()
        name_words = [w.strip(".,") for w in name_lower.split() if w.strip(".,")]
        if not name_words:
            continue

        # REQUIRED 1: First letter of first word matches target first initial
        if target_first_lower and name_words[0][0] != target_first_lower:
            continue

        # REQUIRED 2: Every surname word must appear in displayName
        # (handles compound names like "S. Kumar Sharma")
        if surname_words and not all(any(sw in nw or nw in sw for nw in name_words[1:]) for sw in surname_words):
            continue

        # Scoring
        score = 100  # base for passing required filters
        # Bonus if displayName has at least 2 words (real name, not just an email-as-name)
        if len(name_words) >= 2:
            score += 30
        # Bonus if address starts with first-initial (typical Technijian convention)
        if target_first_lower and addr.startswith(target_first_lower):
            score += 20
        # Bonus if address contains lastname
        if surname_words and any(sw in addr for sw in surname_words):
            score += 20
        # Penalty if displayName equals address (shows it was never resolved against AAD)
        if name_lower == addr:
            score -= 50

        out.append({"address": addr, "name": name, "score": score})
    return out


def search_mailbox_for_name(token: str, last_name: str) -> list[dict]:
    """Use $search across messages in the mailbox for the tech's surname.
    Return ALL emailAddress entries from from/to/cc of matched messages."""
    # KQL: search the surname across body+headers+recipients+subject
    qs = (
        f"$top=50"
        f"&$select=" + quote("from,toRecipients,ccRecipients,subject,sentDateTime")
        + f"&$search=" + quote(f"\"{last_name}\"")
    )
    found = []
    for folder in ("sentitems", "inbox"):
        path = f"/users/{MBOX}/mailFolders/{folder}/messages?{qs}"
        data = graph_get(token, path)
        if "_error" in data:
            print(f"  [search err] {folder}/{last_name}: {data['_error']} {data['_body'][:120]}")
            continue
        for m in data.get("value", []):
            ea_from = (m.get("from") or {}).get("emailAddress")
            if ea_from:
                found.append({"emailAddress": ea_from})
            for r in m.get("toRecipients", []):
                if r.get("emailAddress"):
                    found.append(r)
            for r in m.get("ccRecipients", []):
                if r.get("emailAddress"):
                    found.append(r)
    return found


def resolve_one(token: str, slug: str) -> dict:
    fi, ln = slug_to_parts(slug)
    display = slug_to_display(slug)
    recipients = search_mailbox_for_name(token, ln.split()[0])  # search by primary surname
    candidates = candidates_from_recipients(recipients, fi, ln)
    if not candidates:
        return {"slug": slug, "display": display, "resolved": False,
                "reason": "no @technijian.com candidates found in recent mail"}
    # Aggregate by address, sum scores + frequency
    addr_score: dict[str, dict] = {}
    for c in candidates:
        a = c["address"]
        if a not in addr_score:
            addr_score[a] = {"address": a, "name": c["name"], "score": 0, "count": 0}
        addr_score[a]["score"] += c["score"]
        addr_score[a]["count"] += 1
    ranked = sorted(addr_score.values(), key=lambda x: (-x["score"], -x["count"]))
    top = ranked[0]
    return {
        "slug": slug, "display": display, "resolved": True,
        "address": top["address"], "graph_display_name": top["name"],
        "confidence_score": top["score"], "match_count": top["count"],
        "alternates": [{"address": r["address"], "name": r["name"], "score": r["score"], "count": r["count"]}
                       for r in ranked[1:4]],
    }


def main() -> None:
    if not BY_TECH.exists():
        print(f"No by-tech folder at {BY_TECH}")
        return

    cache = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding="utf-8"))

    print(f"Authenticating to Microsoft Graph...")
    token = get_token()
    print(f"  mailbox: {MBOX}")
    print(f"  cache: {CACHE} ({len(cache)} cached)")
    print(f"  refresh: {REFRESH}\n")

    slugs = sorted(d.name for d in BY_TECH.iterdir() if d.is_dir())
    new_resolved = 0
    for slug in slugs:
        if slug in cache and not REFRESH:
            entry = cache[slug]
            mark = "OK" if entry.get("resolved") else "??"
            addr = entry.get("address", "(unresolved)")
            print(f"  [{mark}] {slug:<20} -> {addr:<40}  (cached)")
            continue
        info = resolve_one(token, slug)
        cache[slug] = info
        new_resolved += 1
        if info["resolved"]:
            print(f"  [OK] {slug:<20} -> {info['address']:<40}  score={info['confidence_score']}  matched-as=\"{info['graph_display_name']}\"")
            for a in info.get("alternates", []):
                print(f"        alt: {a['address']:<35}  score={a['score']}  \"{a['name']}\"")
        else:
            print(f"  [??] {slug:<20} -> NOT RESOLVED  ({info.get('reason')})")

    CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    print(f"\nWrote: {CACHE}")
    resolved = sum(1 for v in cache.values() if v.get("resolved"))
    print(f"Resolved: {resolved}/{len(cache)}  (new lookups this run: {new_resolved})")


if __name__ == "__main__":
    main()
