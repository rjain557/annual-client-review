#!/usr/bin/env python3
"""
create_customer_api_keys.py

Logs into Cisco Umbrella and creates a per-customer OAuth2 API key named
"ClaudeCode" for each of the 29 MSP customer orgs.

Uses the top-right org switcher dropdown visible in the dashboard and/or direct
URL navigation (verified working 2026-04-29).

USAGE
    python create_customer_api_keys.py                 # all 29 orgs
    python create_customer_api_keys.py --only VAF,BWH  # subset
    python create_customer_api_keys.py --skip VAF      # skip already-done
    python create_customer_api_keys.py --resume        # skip already in state
    python create_customer_api_keys.py --dry-run       # plan only, no browser
    python create_customer_api_keys.py --verify-only   # test captured keys

PREREQUISITES
    pip install playwright
    playwright install msedge
"""

import argparse, base64, json, os, re, sys, tempfile, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Customer org roster  (code -> Umbrella org_id)
# ---------------------------------------------------------------------------
CUSTOMERS = [
    ("B2I",    8182603),
    ("ANI",    8182605),
    ("TECH",   8182611),
    ("TDC",    8182613),
    ("ISI",    8182639),
    ("NOR",    8182646),
    ("ORX",    8182647),
    ("RSPMD",  8182655),
    ("SAS",    8182656),
    ("VAF",    8182659),
    ("AAVA",   8212809),
    ("KSS",    8213557),
    ("AOC",    8219569),
    ("BWH",    8219571),
    ("CCC",    8219573),
    ("MAX",    8219576),
    ("ACU",    8228246),
    ("JDH",    8256091),
    ("HHOC",   8262496),
    ("TALY",   8270949),
    ("CBI",    8298405),
    ("RMG",    8315328),
    ("SGC",    8316182),
    ("ALG",    8316664),
    ("KES",    8323805),
    ("JSD",    8324833),
    ("DTS",    8347026),
    ("EBRMD",  8347471),
    ("AFFG",   8390093),
]

# Customer org name -> code mapping for dropdown matching
ORG_NAMES = {
    8182603: "B2I",   8182605: "ANI",   8182611: "TECH",  8182613: "TDC",
    8182639: "ISI",   8182646: "NOR",   8182647: "ORX",   8182655: "RSPMD",
    8182656: "SAS",   8182659: "VAF",   8212809: "AAVA",  8213557: "KSS",
    8219569: "AOC",   8219571: "BWH",   8219573: "CCC",   8219576: "MAX",
    8228246: "ACU",   8256091: "JDH",   8262496: "HHOC",  8270949: "TALY",
    8298405: "CBI",   8315328: "RMG",   8316182: "SGC",   8316664: "ALG",
    8323805: "KES",   8324833: "JSD",   8347026: "DTS",   8347471: "EBRMD",
    8390093: "AFFG",
}

HERE    = Path(__file__).parent
REPO    = HERE.parent.parent.parent
STATE   = REPO / "technijian" / "umbrella-pull" / "state" / "customer-api-keys.json"
SHOTS   = REPO / "technijian" / "umbrella-pull" / "debug-screenshots"
KEYFILE = (
    Path(os.environ["USERPROFILE"])
    / "OneDrive - Technijian, Inc"
    / "Documents" / "VSCODE" / "keys" / "cisco-umbrella.md"
)

KEY_NAME    = "ClaudeCode"
MSP_ORG_ID  = 8163754
LOGIN_URL   = ("https://login.umbrella.com/?expired=true"
               "&return_to=https%3A%2F%2Fdashboard.umbrella.com%2Fo%2F8182659%2F")
TIMEOUT_MS  = 20_000
SLOW_MO_MS  = 120

SHOTS.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# State + keyfile helpers
# ---------------------------------------------------------------------------
def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}

def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))

SECTION_HEADER = "## Per-Customer OAuth2 Keys (MSP-Playwright)"

def update_keyfile(state: dict) -> None:
    if not KEYFILE.exists():
        print(f"[WARN] keyfile not found: {KEYFILE}")
        return
    text = KEYFILE.read_text(encoding="utf-8")
    lines = [SECTION_HEADER, "",
             "Created by Playwright automation. Each key was generated from the customer's own dashboard.",
             f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}", "",
             "| Code | Org ID | API Key | API Secret | Created |",
             "|---|---|---|---|---|"]
    for code, org_id in CUSTOMERS:
        entry = state.get(code, {})
        if entry.get("api_key"):
            lines.append(f"| {code} | {org_id} | {entry['api_key']} | {entry['api_secret']} | {entry.get('created_at','')[:10]} |")
        else:
            lines.append(f"| {code} | {org_id} | (not yet created) | | |")
    lines.append("")
    new_section = "\n".join(lines)
    if SECTION_HEADER in text:
        text = re.sub(rf"{re.escape(SECTION_HEADER)}.*?(?=\n## |\Z)", new_section, text, flags=re.DOTALL)
    else:
        text = text.rstrip() + "\n\n" + new_section + "\n"
    KEYFILE.write_text(text, encoding="utf-8")
    print(f"[keyfile] updated: {KEYFILE}")


# ---------------------------------------------------------------------------
# Credential reader
# ---------------------------------------------------------------------------
def read_creds() -> tuple[str, str]:
    text = KEYFILE.read_text(encoding="utf-8")
    u = re.search(r"\*\*Username:\*\*\s*(\S+)", text)
    p = re.search(r"\*\*Password:\*\*\s*(\S+)", text)
    if not u or not p:
        raise RuntimeError("Username/Password not found in keyfile.")
    return u.group(1).strip(), p.group(1).strip()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
def auto_login(page, username: str, password: str) -> None:
    """Fill login form, submit, wait for 2FA (user completes manually), then dashboard."""
    print(f"  [login] {page.url[:80]}")
    page.wait_for_load_state("domcontentloaded", timeout=15_000)
    time.sleep(1)

    # Fill username + password (single-page form verified 2026-04-29)
    page.fill("input[name='username']", username)
    page.fill("input[name='password']", password)
    print("  [login] credentials filled")

    # Submit
    with page.expect_navigation(wait_until="domcontentloaded", timeout=30_000):
        page.click("button#sign-in")
    print(f"  [login] submitted -> {page.url[:80]}")

    # If not yet on dashboard, wait for user to complete 2FA/SSO (up to 3 min)
    if "dashboard.umbrella.com/o/" not in page.url:
        print("  [login] 2FA detected — please complete it in the browser window ...")
        page.wait_for_url("**/dashboard.umbrella.com/o/**", timeout=180_000,
                          wait_until="domcontentloaded")
    print(f"  [login] dashboard reached: {page.url[:80]}")
    time.sleep(2)


# ---------------------------------------------------------------------------
# Navigate to a customer org's Admin > API Keys page
# ---------------------------------------------------------------------------
def go_to_apikeys(page, org_id: int) -> bool:
    """
    Navigate to org's admin/apikeys page.
    Returns True if successfully on the right org's page.

    Verified approach (2026-04-29):
    - Direct URL navigation to /o/{org_id}/#/admin/apikeys works when logged
      in via MSP account.
    - The SPA never fires 'networkidle' so we use 'domcontentloaded' + sleep.
    """
    target = f"https://dashboard.umbrella.com/o/{org_id}/#/admin/apikeys"
    page.goto(target, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
    time.sleep(4)   # React needs a moment to render

    current = page.url
    if str(org_id) not in current:
        # We may have been redirected to MSP parent — try via customer dropdown
        print(f"  [nav] URL {current[:60]} doesn't contain {org_id}, trying dropdown")
        return _switch_via_dropdown(page, org_id)

    # Make sure we're on the apikeys hash — may need to navigate hash manually
    if "admin/apikeys" not in current:
        page.evaluate("() => { location.hash = '/admin/apikeys'; }")
        time.sleep(3)

    return True


def _switch_via_dropdown(page, org_id: int) -> bool:
    """
    Use the top-right 'Current Customer' dropdown to switch org, then
    navigate to admin/apikeys.
    """
    code = ORG_NAMES.get(org_id, str(org_id))

    # The dropdown is the search input in the top-right nav bar
    # Screenshot (2026-04-29) shows: magnifier icon + "Current Customer: VAF" + chevron
    dropdown_selectors = [
        "input[placeholder*='Current Customer']",
        "input[placeholder*='customer']",
        "[class*='customer-search'] input",
        "[class*='org-select'] input",
        "[class*='orgSelector'] input",
        "input[class*='customer']",
        # Try clicking the text area that shows the current org name
        "[class*='currentOrg'] input",
        "[class*='orgName']",
    ]
    clicked = False
    for sel in dropdown_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(0.5)
                el.fill("")
                el.fill(code)
                clicked = True
                print(f"  [dropdown] typed '{code}' in {sel}")
                break
        except Exception:
            pass

    if not clicked:
        print(f"  [dropdown] could not find customer dropdown")
        return False

    # Wait for the dropdown list to appear and click the matching item
    time.sleep(1.5)
    items = page.query_selector_all("[class*='dropdown'] li, [role='option'], [role='listitem'], [class*='result']")
    for item in items:
        text = (item.text_content() or "").strip()
        if code.lower() in text.lower() or str(org_id) in text:
            item.click()
            print(f"  [dropdown] selected: {text!r}")
            time.sleep(3)
            break
    else:
        # Fallback: press Enter to select first result
        page.keyboard.press("Enter")
        time.sleep(3)

    # Now navigate to admin/apikeys
    page.evaluate("() => { location.hash = '/admin/apikeys'; }")
    time.sleep(3)

    return str(org_id) in page.url


# ---------------------------------------------------------------------------
# Delete an existing API key by name (for --force-recreate)
# ---------------------------------------------------------------------------
def delete_existing_key(page, key_name: str = KEY_NAME) -> bool:
    """
    Find a key named key_name in the current API keys list and delete it.
    Returns True if deleted, False if not found.
    """
    page.screenshot(path=str(SHOTS / f"pre-delete-{int(time.time())}.png"))
    page_text = page.evaluate("() => document.body.innerText")
    if key_name not in page_text:
        return False  # nothing to delete

    # Each key row has a chevron/expand button on the far right.
    # Try to find a button associated with the key_name row.
    deleted = page.evaluate(f"""() => {{
        // Find the row that contains the key name
        const rows = [...document.querySelectorAll('tr, li, [class*="row"], [class*="item"]')]
            .filter(el => el.innerText && el.innerText.includes('{key_name}') && el.offsetParent);
        for (const row of rows) {{
            // Look for a button or icon inside the row (delete, expand, options)
            const btns = [...row.querySelectorAll('button, [role="button"], [class*="delete"], [class*="remove"]')];
            if (btns.length > 0) {{
                btns[btns.length - 1].click();  // click last button (usually options/delete)
                return 'clicked-row-button';
            }}
        }}
        return null;
    }}""")
    print(f"  [delete] row action: {deleted}")
    time.sleep(1)
    page.screenshot(path=str(SHOTS / f"delete-menu-{int(time.time())}.png"))

    # Look for a "Delete" option in a dropdown/menu
    for sel in [
        "button >> text=Delete",
        "a >> text=Delete",
        "[role='menuitem'] >> text=Delete",
        "button >> text='Delete Key'",
        "li >> text=Delete",
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                print(f"  [delete] clicked delete menu item ({sel})")
                time.sleep(1)
                break
        except Exception:
            pass

    # Confirm deletion dialog if it appears
    page.screenshot(path=str(SHOTS / f"delete-confirm-{int(time.time())}.png"))
    for sel in [
        "button >> text=Delete",
        "button >> text=Confirm",
        "button >> text=Yes",
        "button >> text='Delete Key'",
        "button >> text='Yes, Delete'",
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                print(f"  [delete] confirmed ({sel})")
                time.sleep(2)
                break
        except Exception:
            pass

    # Verify it's gone
    time.sleep(1)
    page_text = page.evaluate("() => document.body.innerText")
    deleted_ok = key_name not in page_text
    print(f"  [delete] key removed: {deleted_ok}")
    return deleted_ok


# ---------------------------------------------------------------------------
# Find the Add/Create API Key button
# ---------------------------------------------------------------------------
def find_and_click_add_button(page) -> str:
    """Click the Add API Key button. Returns the selector that worked."""
    page.screenshot(path=str(SHOTS / f"apikeys-page-{int(time.time())}.png"))

    # Log all visible buttons for debugging
    btns = page.evaluate("""() => [...document.querySelectorAll('button,[role=button]')]
        .filter(e => e.offsetParent !== null)
        .map(e => ({text:(e.textContent||'').trim().slice(0,50),
                    aria:e.getAttribute('aria-label')||'',
                    cls:e.className.slice(0,80),
                    id:e.id||''}))""")
    print("  [buttons]", btns[:10])

    # Try in priority order
    for sel in [
        "button[aria-label='Create API Key']",
        "button[aria-label='Add API Key']",
        "button[aria-label='Add']",
        "[data-testid='create-api-key']",
        "[data-testid='add-api-key']",
        "button >> text=Create API Key",
        "button >> text='Add API Key'",
        "button >> text=Add",
        "button >> text=Create",
        "button >> text='+ Add'",
        "button.btn-primary",
        "button.add-key",
        "button.create-key",
        # Umbrella uses a floating action button (+) pattern
        "button[class*='fab']",
        "button[class*='add']:not([disabled])",
        "button[class*='create']:not([disabled])",
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible() and not el.get_attribute("disabled"):
                el.click()
                return sel
        except Exception:
            pass

    # Last resort: find any button that looks like an "add" action
    for btn in btns:
        text = btn["text"].lower()
        aria = btn["aria"].lower()
        if any(kw in text or kw in aria for kw in ["add", "create", "new", "+"]):
            try:
                page.click(f"button >> text={btn['text']!r}")
                return f"button(text={btn['text']!r})"
            except Exception:
                pass

    raise RuntimeError(f"No Add/Create button found. Buttons visible: {[b['text'] for b in btns[:8]]}")


# ---------------------------------------------------------------------------
# Fill the create-key form
# ---------------------------------------------------------------------------
def fill_create_form(page) -> None:
    time.sleep(1.5)
    page.evaluate("() => window.scrollTo(0, 0)")
    time.sleep(0.5)
    page.screenshot(path=str(SHOTS / f"create-form-{int(time.time())}.png"))

    # ---- API Key Name field ----
    # IMPORTANT: input[type='text'] matches the top-right customer search bar first.
    # Target by default value "New API Key" which uniquely identifies the name field.
    name_filled = False
    for sel in [
        "input[value='New API Key']",
        "input[name='keyName']",
        "input[placeholder*='key name' i]",
        "input[aria-label*='key name' i]",
        "input[aria-label*='api key name' i]",
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.triple_click()
                el.fill(KEY_NAME)
                print(f"  [form] name filled in {sel}")
                name_filled = True
                break
        except Exception:
            pass

    if not name_filled:
        # JS fallback: find the input whose current value is 'New API Key'
        filled = page.evaluate(f"""() => {{
            const inputs = [...document.querySelectorAll('input[type=text],input:not([type])')];
            const target = inputs.find(i => i.value === 'New API Key');
            if (target) {{
                target.focus();
                target.select();
                document.execCommand('insertText', false, '{KEY_NAME}');
                target.dispatchEvent(new Event('input', {{bubbles: true}}));
                target.dispatchEvent(new Event('change', {{bubbles: true}}));
                return true;
            }}
            return false;
        }}""")
        print(f"  [form] name filled via JS: {filled}")
    time.sleep(0.5)

    # ---- Select all scope checkboxes ----
    # Try a "Select All" toggle first, then click each unchecked box individually.
    select_all_clicked = False
    for sel in [
        "input[type='checkbox'][aria-label*='all' i]",
        "label >> text='Select All'",
        "label >> text='All'",
        ".select-all input[type='checkbox']",
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                if not el.is_checked():
                    el.click()
                print(f"  [form] select-all clicked ({sel})")
                select_all_clicked = True
                time.sleep(0.3)
                break
        except Exception:
            pass

    if not select_all_clicked:
        # Scope checkboxes are hidden <input type="checkbox"> behind CSS-styled spans.
        # Use check(force=True) to bypass visibility and fire the React change event.
        checkboxes = page.query_selector_all("input[type='checkbox']")
        checked_count = 0
        for cb in checkboxes:
            try:
                cb.check(force=True)
                checked_count += 1
                time.sleep(0.1)
            except Exception:
                pass
        print(f"  [form] force-checked {checked_count} scope checkboxes")
        time.sleep(0.5)
        page.screenshot(path=str(SHOTS / f"scopes-after-check-{int(time.time())}.png"))

    page.screenshot(path=str(SHOTS / f"create-form-filled-{int(time.time())}.png"))


# ---------------------------------------------------------------------------
# Capture key+secret from the post-creation success page
# ---------------------------------------------------------------------------
def _looks_like_key(v: str) -> bool:
    """Return True if v looks like a real API key/secret (not plain English)."""
    if not v or len(v) < 16:
        return False
    if " " in v.strip():          # plain English has spaces
        return False
    # Must be mostly alphanumeric/dash/underscore
    alnum = sum(1 for c in v if c.isalnum() or c in "-_")
    return alnum / len(v) >= 0.85

def capture_credentials(page) -> tuple[str, str]:
    # Wait for the success state to render (form submission takes a moment)
    time.sleep(3)
    page.screenshot(path=str(SHOTS / f"key-modal-{int(time.time())}.png"))

    # Save page HTML for debugging failed captures
    html_path = SHOTS / f"key-modal-{int(time.time())}.html"
    html_path.write_text(page.content(), encoding="utf-8")

    # Strategy 1: readonly inputs anywhere on the page
    all_inputs = page.query_selector_all("input[readonly], input[type='text']")
    candidates = []
    for inp in all_inputs:
        try:
            v = (inp.get_attribute("value") or inp.input_value() or "").strip()
            if _looks_like_key(v):
                candidates.append(v)
        except Exception:
            pass
    if len(candidates) >= 2:
        return candidates[0], candidates[1]

    # Strategy 2: code/pre/span elements (Umbrella might show key in a code block)
    creds = page.evaluate("""() => {
        const els = [...document.querySelectorAll(
            'code, pre, [class*="key"], [class*="secret"], [class*="token"], [class*="credential"]'
        )];
        return els
            .map(e => (e.textContent || '').trim())
            .filter(v => v.length >= 16 && !/\\s/.test(v) && /[a-zA-Z0-9]/.test(v));
    }""")
    if len(creds) >= 2:
        k, s = creds[0], creds[1]
        if _looks_like_key(k) and _looks_like_key(s):
            return k, s

    # Strategy 3: regex on full page innerText — 32-char hex OR UUID patterns
    text = page.evaluate("() => document.body.innerText")
    tokens = re.findall(r"[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text.lower())
    tokens = [t for t in tokens if _looks_like_key(t)]
    if len(tokens) >= 2:
        return tokens[0], tokens[1]

    # Check if we're still on the Add form (means 0 scopes — form didn't submit)
    if "Add New API Key" in text and "0 selected" in text:
        raise RuntimeError(
            "Form still open after submit — scopes were not selected. "
            "Check create-form-filled screenshot."
        )

    raise RuntimeError(
        "Could not extract key/secret from success page. "
        f"HTML saved to {html_path.name}. Add manually to state file."
    )


# ---------------------------------------------------------------------------
# Submit the create form
# ---------------------------------------------------------------------------
def submit_create_form(page) -> None:
    # The submit button is below the fold — scroll to it first.
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(0.5)
    page.screenshot(path=str(SHOTS / f"create-form-scrolled-{int(time.time())}.png"))

    # Form is full-page (not inside a dialog), so no dialog-scoped selectors.
    # The actual submit button text is "CREATE KEY" (all-caps teal button, bottom right).
    # Do NOT use "button >> text=Add" — that hits the IP-Restrictions "ADD" button.
    for sel in [
        "button >> text='CREATE KEY'",
        "button >> text='Create Key'",
        "button >> text='Create key'",
        "button >> text=CREATE",
        "button[type='submit']",
        "button >> text='Create API Key'",
        "[data-testid='submit']",
        "button.btn-primary",
        "button.primary",
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.scroll_into_view_if_needed()
                el.click()
                print(f"  [form] submitted ({sel})")
                return
        except Exception:
            pass
    # Last resort: press Enter in the form
    page.keyboard.press("Enter")
    print("  [form] submitted via Enter")


# ---------------------------------------------------------------------------
# Dismiss the modal after capturing credentials
# ---------------------------------------------------------------------------
def dismiss_modal(page) -> None:
    for sel in ["button >> text=Done", "button >> text=Close", "button >> text=OK",
                "button >> text=Finish", "dialog button", "[role='dialog'] button"]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                time.sleep(0.5)
                return
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Verify a key works
# ---------------------------------------------------------------------------
def verify_key(code: str, entry: dict) -> bool:
    try:
        credentials = base64.b64encode(f"{entry['api_key']}:{entry['api_secret']}".encode()).decode()
        req = urllib.request.Request(
            "https://api.umbrella.com/auth/v2/token",
            data=b"grant_type=client_credentials",
            headers={"Authorization": f"Basic {credentials}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read())
            ok = "access_token" in body
            print(f"  [{code}] verify: {'OK' if ok else 'FAIL'} (token_len={len(body.get('access_token',''))})")
            return ok
    except Exception as exc:
        print(f"  [{code}] verify FAILED: {exc}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only",           help="Comma-separated codes")
    parser.add_argument("--skip",           help="Comma-separated codes to skip")
    parser.add_argument("--resume",         action="store_true", help="Skip already in state")
    parser.add_argument("--force-recreate", action="store_true", help="Delete existing ClaudeCode key and recreate")
    parser.add_argument("--dry-run",        action="store_true")
    parser.add_argument("--verify-only",    action="store_true")
    args = parser.parse_args()

    only_set = {c.strip().upper() for c in args.only.split(",")} if args.only else None
    skip_set = {c.strip().upper() for c in args.skip.split(",")} if args.skip else set()
    targets = [(c, o) for c, o in CUSTOMERS
               if (only_set is None or c in only_set) and c not in skip_set]

    state = load_state()
    if args.resume:
        targets = [(c, o) for c, o in targets if not state.get(c, {}).get("api_key")]

    print(f"Targets ({len(targets)}): {[c for c,_ in targets]}")
    print(f"State:   {STATE}")

    if args.dry_run:
        print("[dry-run] no browser launched")
        for c, o in targets:
            print(f"  {c} (org {o})")
        return

    if args.verify_only:
        for c, o in targets:
            e = state.get(c, {})
            if e.get("api_key"):
                e["verified"] = verify_key(c, e)
                state[c] = e
        save_state(state)
        update_keyfile(state)
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("pip install playwright && playwright install msedge")

    username, password = read_creds()
    tmp = tempfile.mkdtemp(prefix="umbrella_pw_")
    errors = {}

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            tmp, channel="msedge", headless=False, slow_mo=SLOW_MO_MS,
            args=["--no-first-run", "--no-default-browser-check"],
        )
        page = ctx.new_page()
        page.set_default_timeout(TIMEOUT_MS)

        # Login
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        time.sleep(1.5)
        auto_login(page, username, password)

        print(f"\nLogged in. Processing {len(targets)} orgs...\n")

        for code, org_id in targets:
            print(f"\n{'='*55}")
            print(f"  {code}  (org_id={org_id})")
            print(f"{'='*55}")
            try:
                # Navigate to this org's API keys page
                ok = go_to_apikeys(page, org_id)
                if not ok:
                    raise RuntimeError(f"Could not navigate to org {org_id}")

                # Check if key already exists
                page_text = page.evaluate("() => document.body.innerText")
                if KEY_NAME in page_text:
                    if args.force_recreate:
                        print(f"  [{code}] deleting existing '{KEY_NAME}' key...")
                        deleted = delete_existing_key(page)
                        if not deleted:
                            raise RuntimeError(f"Could not delete existing '{KEY_NAME}' key")
                        print(f"  [{code}] deleted — recreating...")
                        # Refresh API keys page after deletion
                        go_to_apikeys(page, org_id)
                    else:
                        raise RuntimeError(
                            f"Key '{KEY_NAME}' already exists — delete it first or use --skip {code}")

                # Click Add / Create
                add_sel = find_and_click_add_button(page)
                print(f"  [add] clicked ({add_sel})")
                time.sleep(1)

                # Fill form
                fill_create_form(page)

                # Submit
                submit_create_form(page)

                # Capture credentials
                api_key, api_secret = capture_credentials(page)
                dismiss_modal(page)

                entry = {
                    "code": code, "org_id": org_id,
                    "api_key": api_key, "api_secret": api_secret,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                entry["verified"] = verify_key(code, entry)
                state[code] = entry
                save_state(state)
                print(f"  [{code}] SAVED  key={api_key[:8]}...  verified={entry['verified']}")

            except Exception as exc:
                print(f"  [{code}] ERROR: {exc}")
                errors[code] = str(exc)
                page.screenshot(path=str(SHOTS / f"error-{code}-{int(time.time())}.png"))
                time.sleep(2)

        # Auto-retry "already exists" errors within the same browser session
        retry_codes = [
            c for c, m in errors.items()
            if "already exists" in m
        ]
        if retry_codes and not args.force_recreate:
            print(f"\n{'='*55}")
            print(f"Auto-retry {len(retry_codes)} orgs with --force-recreate: {retry_codes}")
            print(f"{'='*55}")
            retry_errors = {}
            for code in retry_codes:
                org_id = next(o for c, o in CUSTOMERS if c == code)
                print(f"\n--- {code} (force-recreate) ---")
                try:
                    ok = go_to_apikeys(page, org_id)
                    if not ok:
                        raise RuntimeError(f"Could not navigate to org {org_id}")

                    page_text = page.evaluate("() => document.body.innerText")
                    if KEY_NAME in page_text:
                        print(f"  [{code}] deleting existing '{KEY_NAME}' key...")
                        deleted = delete_existing_key(page)
                        if not deleted:
                            raise RuntimeError(f"Could not delete existing '{KEY_NAME}' key")
                        go_to_apikeys(page, org_id)

                    add_sel = find_and_click_add_button(page)
                    print(f"  [add] clicked ({add_sel})")
                    time.sleep(1)
                    fill_create_form(page)
                    submit_create_form(page)
                    api_key, api_secret = capture_credentials(page)
                    dismiss_modal(page)

                    entry = {
                        "code": code, "org_id": org_id,
                        "api_key": api_key, "api_secret": api_secret,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    entry["verified"] = verify_key(code, entry)
                    state[code] = entry
                    save_state(state)
                    # Remove from errors if succeeded
                    errors.pop(code, None)
                    print(f"  [{code}] SAVED  key={api_key[:8]}...  verified={entry['verified']}")

                except Exception as exc:
                    print(f"  [{code}] RETRY ERROR: {exc}")
                    retry_errors[code] = str(exc)
                    page.screenshot(path=str(SHOTS / f"retry-error-{code}-{int(time.time())}.png"))
                    time.sleep(2)

            errors.update(retry_errors)

        # Final summary
        print(f"\n{'='*55}")
        succeeded = [c for c, _ in CUSTOMERS if state.get(c, {}).get("verified")]
        failed    = list(errors.keys())
        print(f"Verified: {len(succeeded)}/{len(CUSTOMERS)}  {succeeded}")
        print(f"Failed:   {len(failed)}  {failed}")
        if errors:
            for c, m in errors.items():
                print(f"  {c}: {m}")

        update_keyfile(state)
        print(f"\nState:   {STATE}")
        print(f"Shots:   {SHOTS}")
        print(f"Keyfile: {KEYFILE}")

        print("\nAll orgs processed. Browser will stay open 60 s then close.")
        time.sleep(60)
        ctx.close()


if __name__ == "__main__":
    main()
