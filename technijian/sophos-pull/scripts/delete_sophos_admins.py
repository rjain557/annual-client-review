#!/usr/bin/env python3
"""
delete_sophos_admins.py

Playwright RPA pass to delete Sophos Central partner admin accounts that
the Partner API can't remove (Sophos exposes admin role-assignment CRUD but
NOT admin-account deletion — see reference_sophos_api_gaps.md).

Reads the cleanup queue from
  technijian/sophos-pull/state/sophos-admin-cleanup-candidates.json
which is populated by the API-tier neutralization scripts (route_alerts.py,
plus the in-session role-strip passes that move stripped admins into
`no_role_pending_ui_delete`).

Credentials: read from
  %USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/sophos-portal.md
This is a SEPARATE keyfile from sophos.md (which holds the API client
credentials). UI login uses Sophos ID username/password + 2FA.

USAGE
    python delete_sophos_admins.py                 # dry-run (default; no clicks)
    python delete_sophos_admins.py --apply         # actually delete
    python delete_sophos_admins.py --only x@y.com  # restrict to one user
    python delete_sophos_admins.py --skip x@y.com  # exclude one
    python delete_sophos_admins.py --resume        # skip those already logged successful

PREREQUISITES
    pip install playwright
    playwright install msedge

Per memory `feedback_playwright_background_runs.md` — when invoking from
Claude Code, run with run_in_background=True; the user has to do 2FA.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPELINE_ROOT = HERE.parent
REPO = PIPELINE_ROOT.parent.parent
STATE_DIR = PIPELINE_ROOT / "state"
CANDIDATES_FILE = STATE_DIR / "sophos-admin-cleanup-candidates.json"
SHOTS_DIR = PIPELINE_ROOT / "debug-screenshots"
KEYFILE = (
    Path(os.environ.get("USERPROFILE", str(Path.home())))
    / "OneDrive - Technijian, Inc"
    / "Documents" / "VSCODE" / "keys" / "sophos-portal.md"
)

# Sophos Central -> Partner -> System Settings -> Administrators
PARTNER_HOME_URL = "https://central.sophos.com/manage/partner"
ADMINS_URL_HINTS = [
    "https://central.sophos.com/manage/partner/system-settings/administrators",
    "https://central.sophos.com/manage/partner/admins",
]

TIMEOUT_MS = 30_000
SLOW_MO_MS = 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def read_creds() -> tuple[str, str]:
    if not KEYFILE.exists():
        raise RuntimeError(
            f"Keyfile not found: {KEYFILE}\n"
            "Create it with:\n"
            "    # Sophos Partner Portal UI Credentials\n"
            "    - **Username:** rjain@technijian.com\n"
            "    - **Password:** <password>\n"
            "These are different from the API client_id/secret in sophos.md."
        )
    text = KEYFILE.read_text(encoding="utf-8")
    u = re.search(r"\*\*Username:\*\*\s*(\S+)", text)
    p = re.search(r"\*\*Password:\*\*\s*(\S+)", text)
    if not u or not p:
        raise RuntimeError(f"Could not find Username/Password in {KEYFILE}")
    return u.group(1).strip(), p.group(1).strip()


def load_candidates() -> list[dict]:
    if not CANDIDATES_FILE.exists():
        raise RuntimeError(f"Candidates file not found: {CANDIDATES_FILE}")
    state = json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))
    out: list[dict] = []
    for k in ("no_role_pending_ui_delete", "roles_stripped_pending_ui_delete"):
        for entry in state.get(k, []):
            entry = dict(entry)
            entry.setdefault("source", k)
            out.append(entry)
    seen: set[str] = set()
    deduped: list[dict] = []
    for e in out:
        em = (e.get("username") or "").lower().strip()
        if not em or em in seen:
            continue
        seen.add(em)
        deduped.append(e)
    return deduped


def write_log(results: list[dict]) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    path = STATE_DIR / f"sophos-admin-deletion-log-{ts}.json"
    path.write_text(json.dumps({
        "run_at": ts,
        "results": results,
    }, indent=2, default=str), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Playwright pass
# ---------------------------------------------------------------------------
def login(page, username: str, password: str) -> None:
    print(f"  [login] navigating to {PARTNER_HOME_URL}")
    page.goto(PARTNER_HOME_URL, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
    time.sleep(2)
    page.screenshot(path=str(SHOTS_DIR / f"01-login-page-{int(time.time())}.png"))

    for sel in ("input[type='email']", "input[name='email']",
                "input[id='email']", "input[autocomplete='username']"):
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.fill(username)
            print(f"  [login] filled username via {sel}")
            break
    else:
        print("  [login] WARN: could not find email input — pausing 30s for manual fill")
        time.sleep(30)

    for sel in ("button[type='submit']", "button:has-text('Next')",
                "button:has-text('Continue')", "button:has-text('Sign in')"):
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.click()
            print(f"  [login] clicked next/submit via {sel}")
            break
    time.sleep(2)
    page.screenshot(path=str(SHOTS_DIR / f"02-after-username-{int(time.time())}.png"))

    for sel in ("input[type='password']", "input[name='password']",
                "input[autocomplete='current-password']"):
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.fill(password)
            print(f"  [login] filled password via {sel}")
            break

    for sel in ("button[type='submit']", "button:has-text('Sign in')",
                "button:has-text('Login')"):
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.click()
            print(f"  [login] clicked submit via {sel}")
            break

    print("  [login] waiting for 2FA / dashboard ... (up to 5 min)")
    deadline = time.time() + 300
    while time.time() < deadline:
        if "central.sophos.com/manage/partner" in page.url and "id.sophos.com" not in page.url:
            print(f"  [login] reached: {page.url[:100]}")
            time.sleep(3)
            return
        time.sleep(2)
    raise RuntimeError("Login timed out — 2FA not completed within 5 minutes")


def open_admins_page(page) -> bool:
    for url in ADMINS_URL_HINTS:
        print(f"  [nav] trying {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        time.sleep(4)
        body = (page.evaluate("() => document.body.innerText") or "").lower()
        if "administrator" in body or "admin" in body:
            page.screenshot(path=str(SHOTS_DIR / f"03-admins-page-{int(time.time())}.png"))
            print(f"  [nav] admins page reached: {page.url[:100]}")
            return True
    print("  [nav] FAIL — could not reach administrators page automatically")
    page.screenshot(path=str(SHOTS_DIR / f"03-nav-failed-{int(time.time())}.png"))
    return False


def delete_one(page, email: str, dry_run: bool) -> dict:
    """Locate the row by email, open the actions menu, click Remove, confirm."""
    result: dict = {"email": email, "actions": [], "ok": False, "error": None}
    print(f"\n--- {email}")
    page.screenshot(path=str(SHOTS_DIR / f"row-pre-{email.replace('@','_at_')}-{int(time.time())}.png"))

    rows = page.evaluate(f"""() => {{
        const rows = [...document.querySelectorAll('tr, li, [class*="row"], [class*="adminRow"]')]
            .filter(el => el.innerText && el.innerText.toLowerCase().includes('{email.lower()}') && el.offsetParent);
        return rows.length;
    }}""")
    if rows == 0:
        msg = "row not found (already deleted? or different page?)"
        result["error"] = msg
        result["actions"].append(msg)
        print(f"  [skip] {msg}")
        return result

    if dry_run:
        result["ok"] = True
        result["actions"].append("DRY-RUN — would click Remove")
        print(f"  [dry-run] would remove ({rows} matching row(s))")
        return result

    clicked_menu = page.evaluate(f"""() => {{
        const rows = [...document.querySelectorAll('tr, li, [class*="row"], [class*="adminRow"]')]
            .filter(el => el.innerText && el.innerText.toLowerCase().includes('{email.lower()}') && el.offsetParent);
        if (!rows.length) return null;
        const row = rows[0];
        const btns = [...row.querySelectorAll(
            'button[aria-label*="more" i], button[aria-label*="action" i], '
            + 'button[aria-haspopup], button[class*="more" i], button[class*="kebab" i], '
            + '[role="button"][class*="more" i]'
        )];
        if (btns.length) {{ btns[0].click(); return 'menu-button-clicked'; }}
        const all = [...row.querySelectorAll('button, [role="button"]')];
        if (all.length) {{ all[all.length - 1].click(); return 'last-button-clicked'; }}
        return null;
    }}""")
    result["actions"].append(f"open-menu: {clicked_menu}")
    if not clicked_menu:
        result["error"] = "could not open row actions menu"
        print(f"  [err] {result['error']}")
        page.screenshot(path=str(SHOTS_DIR / f"row-no-menu-{int(time.time())}.png"))
        return result
    time.sleep(1)
    page.screenshot(path=str(SHOTS_DIR / f"row-menu-{int(time.time())}.png"))

    remove_clicked = False
    for sel in (
        "[role='menuitem']:has-text('Remove')",
        "[role='menuitem']:has-text('Delete')",
        "button:has-text('Remove')",
        "button:has-text('Delete')",
        "li:has-text('Remove')",
        "li:has-text('Delete')",
        "a:has-text('Remove')",
    ):
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                remove_clicked = True
                result["actions"].append(f"click-remove: {sel}")
                print(f"  [click] Remove via {sel}")
                break
        except Exception as e:
            result["actions"].append(f"sel-fail {sel}: {e}")

    if not remove_clicked:
        result["error"] = "could not find Remove menu item"
        page.screenshot(path=str(SHOTS_DIR / f"no-remove-item-{int(time.time())}.png"))
        return result
    time.sleep(1.5)
    page.screenshot(path=str(SHOTS_DIR / f"confirm-dialog-{int(time.time())}.png"))

    confirmed = False
    for sel in (
        "button:has-text('Remove')",
        "button:has-text('Delete')",
        "button:has-text('Confirm')",
        "button:has-text('Yes')",
        "[role='dialog'] button:has-text('Remove')",
        "[role='dialog'] button:has-text('Delete')",
    ):
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                confirmed = True
                result["actions"].append(f"confirm: {sel}")
                print(f"  [confirm] via {sel}")
                break
        except Exception:
            pass
    if not confirmed:
        result["error"] = "no confirm dialog button found (check screenshot)"
        return result

    time.sleep(2)
    page.screenshot(path=str(SHOTS_DIR / f"after-delete-{email.replace('@','_at_')}-{int(time.time())}.png"))
    still_there = page.evaluate(f"""() => {{
        const rows = [...document.querySelectorAll('tr, li, [class*="row"], [class*="adminRow"]')]
            .filter(el => el.innerText && el.innerText.toLowerCase().includes('{email.lower()}') && el.offsetParent);
        return rows.length;
    }}""")
    if still_there:
        result["error"] = "row still present after confirm — deletion may have failed"
        return result
    result["ok"] = True
    print(f"  [ok] deleted")
    return result


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Delete Sophos partner admins via Playwright UI pass.")
    ap.add_argument("--apply", action="store_true", help="Actually click Remove. Default is dry-run.")
    ap.add_argument("--only", help="comma-separated emails to restrict to")
    ap.add_argument("--skip", action="append", default=[], help="email to skip (repeatable)")
    ap.add_argument("--resume", action="store_true",
                    help="skip emails already in a previous deletion log marked ok")
    return ap.parse_args()


def previously_deleted_emails() -> set[str]:
    out: set[str] = set()
    for f in STATE_DIR.glob("sophos-admin-deletion-log-*.json"):
        try:
            d = json.loads(f.read_text())
            for r in d.get("results", []):
                if r.get("ok"):
                    out.add((r.get("email") or "").lower())
        except Exception:
            continue
    return out


def main() -> int:
    args = parse_args()
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)

    candidates = load_candidates()
    only = {e.strip().lower() for e in (args.only or "").split(",") if e.strip()}
    skip = {e.strip().lower() for piece in args.skip for e in piece.split(",") if e.strip()}
    if args.resume:
        skip |= previously_deleted_emails()
    work = [c for c in candidates
            if (not only or (c.get("username") or "").lower() in only)
            and (c.get("username") or "").lower() not in skip]

    print(f"[{datetime.now():%H:%M:%S}] Sophos admin UI deletion pass  apply={args.apply}")
    print(f"  candidates loaded: {len(candidates)}")
    print(f"  to process:        {len(work)}  (after --only/--skip/--resume filters)")
    if not work:
        print("  nothing to do.")
        return 0

    if args.apply:
        username, password = read_creds()
    else:
        username = password = None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERR: playwright not installed. Run: pip install playwright && playwright install msedge")
        return 2

    results: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=False, slow_mo=SLOW_MO_MS)
        try:
            ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
            page = ctx.new_page()

            if args.apply:
                login(page, username, password)
            else:
                print("  [dry-run] launching browser; user may log in manually for visual confirmation")
                page.goto(PARTNER_HOME_URL, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
                print("  [dry-run] pausing 60s for you to log in (optional, only used to test selectors)")
                time.sleep(60)

            if not open_admins_page(page):
                print("ABORT: cannot find admins page. See screenshots.")
                return 3

            for c in work:
                em = c.get("username")
                if not em:
                    continue
                try:
                    r = delete_one(page, em, dry_run=not args.apply)
                except Exception as e:
                    r = {"email": em, "ok": False, "error": f"exception: {e}", "actions": []}
                r["name"] = c.get("name")
                r["sophos_id"] = c.get("sophos_id")
                results.append(r)
                time.sleep(0.5)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    log_path = write_log(results)
    ok = sum(1 for r in results if r.get("ok"))
    fail = len(results) - ok
    print()
    print(f"[{datetime.now():%H:%M:%S}] DONE   ok={ok}  fail={fail}   log={log_path}")
    if fail:
        print("  failed entries:")
        for r in results:
            if not r.get("ok"):
                print(f"    {r['email']:<36s}  {r.get('error')}")
    return 0 if fail == 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())
