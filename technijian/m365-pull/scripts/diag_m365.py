"""Diagnostic test — full error messages, no truncation."""
from __future__ import annotations
import sys, json, traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import m365_api as mapi

TECHNIJIAN_TENANT = "cab8077a-3f42-4277-b7bd-5c9023e826d8"

now = datetime.now(timezone.utc)
since_1h = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
since_7d  = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

tid = TECHNIJIAN_TENANT
passed = []
failed = []

def check(label: str, fn, *args):
    try:
        result = fn(*args)
        n = len(result) if isinstance(result, list) else (1 if result else 0)
        print(f"  PASS  {label}  [{n} items]")
        passed.append(label)
    except Exception as exc:
        print(f"  FAIL  {label}")
        print(f"        {exc}")
        failed.append((label, str(exc)))

print(f"\n=== M365 Graph Diagnostic  tenant={tid} ===\n")

# Auth
try:
    tok = mapi._get_token(tid)
    print(f"  PASS  Token acquired [{len(tok)} chars]\n")
except Exception as exc:
    print(f"  FAIL  Token: {exc}")
    sys.exit(1)

print("--- AuditLog ---")
check("Sign-in logs (1h)", mapi.get_signin_logs, tid, since_1h, now.strftime("%Y-%m-%dT%H:%M:%SZ"))

print("\n--- Reports ---")
check("Mailbox usage (D7)",    mapi.get_mailbox_usage,    tid, "D7")
check("OneDrive usage (D7)",   mapi.get_onedrive_usage,   tid, "D7")
check("SharePoint usage (D7)", mapi.get_sharepoint_usage, tid, "D7")
check("Storage org totals",    mapi.get_storage_org_totals, tid, "D7")

print("\n--- Auth methods ---")
check("MFA registration", mapi.get_mfa_registration, tid)

print("\n--- Security ---")
check("Security alerts",   mapi.get_security_alerts,   tid, since_7d)
check("Security incidents", mapi.get_security_incidents, tid, since_7d)

print("\n--- Compliance ---")
check("Conditional access", mapi.get_conditional_access_policies, tid)
check("Secure score",       mapi.get_secure_score,                tid)
check("Admin roles",        mapi.get_admin_roles,                 tid)
check("Subscribed SKUs",    mapi.get_subscribed_skus,             tid)
check("Guest users",        mapi.get_guest_users,                 tid)

print(f"\n=== {len(passed)} passed  {len(failed)} failed ===\n")
if failed:
    print("FAILURES:")
    for lbl, msg in failed:
        print(f"  {lbl}: {msg}")
sys.exit(len(failed))
