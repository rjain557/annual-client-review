#!/usr/bin/env python3
"""
umbrella_screenshot_debug.py

Logs into Umbrella, navigates to a customer org's API Keys page, takes
screenshots at every step, saves them + page HTML so we can see the exact
selectors needed.

Usage:
    python umbrella_screenshot_debug.py
"""

import json, re, sys, time
from pathlib import Path

HERE   = Path(__file__).parent
REPO   = HERE.parent.parent.parent
SHOTS  = REPO / "technijian" / "umbrella-pull" / "debug-screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)

import os
KEYFILE = (
    Path(os.environ["USERPROFILE"])
    / "OneDrive - Technijian, Inc"
    / "Documents" / "VSCODE" / "keys" / "cisco-umbrella.md"
)

LOGIN_URL  = "https://login.umbrella.com/?expired=true&return_to=https%3A%2F%2Fdashboard.umbrella.com%2Fo%2F8182659%2F"
# Try VAF's admin/apikeys page
TARGET_URL = "https://dashboard.umbrella.com/o/8182659/#/admin/apikeys"
# MSP customer management page
MSP_CUST   = "https://dashboard.umbrella.com/o/8163754/#/customermanagement/customers"

def creds():
    txt = KEYFILE.read_text(encoding="utf-8")
    u = re.search(r"\*\*Username:\*\*\s*(\S+)", txt)
    p = re.search(r"\*\*Password:\*\*\s*(\S+)", txt)
    return u.group(1), p.group(1)

def snap(page, label):
    f = SHOTS / f"{label}.png"
    page.screenshot(path=str(f), full_page=False)
    html_f = SHOTS / f"{label}.html"
    html_f.write_text(page.content(), encoding="utf-8")
    print(f"  [snap] {f.name}  url={page.url[:80]}")

def dump_inputs(page):
    inputs = page.evaluate("""() => [...document.querySelectorAll('input,button,a[href]')]
        .filter(e => e.offsetParent !== null)
        .slice(0, 30)
        .map(e => ({
            tag: e.tagName, type: e.type||'', name: e.name||'', id: e.id||'',
            text: (e.textContent||'').trim().slice(0,40),
            ariaLabel: e.getAttribute('aria-label')||'',
            cls: e.className.slice(0,60)
        }))""")
    for i in inputs:
        print(f"    {i['tag']:8} type={i['type']:12} name={i['name']:20} id={i['id']:20} text={i['text']!r} aria={i['ariaLabel']!r}")

from playwright.sync_api import sync_playwright
import tempfile

with sync_playwright() as pw:
    tmp = tempfile.mkdtemp(prefix="umbrella_dbg_")
    ctx = pw.chromium.launch_persistent_context(
        tmp, channel="msedge", headless=False, slow_mo=200,
        args=["--no-first-run","--no-default-browser-check"]
    )
    page = ctx.new_page()
    page.set_default_timeout(30_000)

    # ---- Step 1: Login ----
    print("\n=== Step 1: Login page ===")
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=15_000)
    snap(page, "01-login-page")
    print("Visible interactive elements:")
    dump_inputs(page)

    username, password = creds()

    # Fill username
    for sel in ["input[name='username']","input[name='identifier']","input[type='email']"]:
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.fill(username)
            print(f"  filled username in {sel}")
            break

    # Fill password
    for sel in ["input[name='password']","input[name='credentials.passcode']","input[type='password']"]:
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.fill(password)
            print(f"  filled password in {sel}")
            break

    snap(page, "02-credentials-filled")

    # Submit
    with page.expect_navigation(wait_until="domcontentloaded", timeout=30_000):
        page.evaluate("""() => {
            const btns = [...document.querySelectorAll('input[type=submit],button[type=submit],button')];
            const btn = btns.find(b => b.offsetParent !== null && !b.disabled);
            if (btn) { console.log('clicking', btn.outerHTML.slice(0,100)); btn.click(); }
        }""")

    snap(page, "03-after-submit")
    print(f"\n=== After submit: {page.url} ===")

    # If 2FA needed - wait up to 3 min
    if "dashboard.umbrella.com/o/" not in page.url:
        print("\n>>> 2FA / SSO page detected. Please complete 2FA in the browser.")
        print(">>> Waiting up to 3 minutes...")
        page.wait_for_url("**/dashboard.umbrella.com/o/**", timeout=180_000,
                          wait_until="domcontentloaded")

    snap(page, "04-dashboard-home")
    print(f"\n=== Dashboard: {page.url} ===")
    dump_inputs(page)

    # ---- Step 2: MSP customer management page ----
    print(f"\n=== Step 2: MSP Customer Management ===")
    page.goto(MSP_CUST, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20_000)
    time.sleep(2)
    snap(page, "05-msp-customer-list")
    print(f"URL: {page.url}")
    dump_inputs(page)

    # ---- Step 3: Navigate directly to VAF API keys ----
    print(f"\n=== Step 3: VAF admin/apikeys direct URL ===")
    page.goto(TARGET_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=20_000)
    time.sleep(3)
    snap(page, "06-vaf-apikeys-direct")
    print(f"URL: {page.url}")
    dump_inputs(page)

    # Also dump all buttons
    btns = page.evaluate("""() => [...document.querySelectorAll('button,[role=button],[class*=btn]')]
        .filter(e => e.offsetParent !== null)
        .map(e => ({text:(e.textContent||'').trim().slice(0,50), cls:e.className.slice(0,80), aria:e.getAttribute('aria-label')||''}))""")
    print("  Buttons visible:")
    for b in btns:
        print(f"    text={b['text']!r:40} aria={b['aria']!r:30} cls={b['cls']!r}")

    print(f"\n\nAll screenshots saved to: {SHOTS}")
    print("Review them to find correct selectors, then update create_customer_api_keys.py")
    input("\nPress ENTER to close browser...")
    ctx.close()
