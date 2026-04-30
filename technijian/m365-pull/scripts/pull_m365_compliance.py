"""Monthly M365 compliance posture pull — per GDAP-approved client tenant.

Captures security configuration and compliance posture for each client:
  - Secure Score (overall + per-control breakdown)
  - Conditional Access policies (configured? gaps?)
  - MFA registration % (critical metric)
  - Admin role inventory (who has Global Admin?)
  - Security defaults enabled/disabled
  - Guest user count
  - Subscribed license SKUs

Per-client output (clients/<code>/m365/compliance/YYYY-MM/):
    secure_score.json
    conditional_access.json
    mfa_registration.json
    admin_roles.json
    security_defaults.json
    guest_users.json
    subscribed_skus.json
    compliance_summary.json     overall posture with pass/warn/fail per check

Usage:
    python pull_m365_compliance.py                  # current month, all tenants
    python pull_m365_compliance.py --month 2026-04
    python pull_m365_compliance.py --only BWH,ORX
    python pull_m365_compliance.py --skip JDH
    python pull_m365_compliance.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_print_lock = threading.Lock()


def _safe_print(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)

HERE = Path(__file__).resolve().parent
PIPELINE_ROOT = HERE.parent
REPO = PIPELINE_ROOT.parent.parent
CLIENTS_ROOT = REPO / "clients"
STATE_DIR = PIPELINE_ROOT / "state"
GDAP_CSV = STATE_DIR / "gdap_status.csv"

sys.path.insert(0, str(HERE))
import m365_api as mapi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _isoz(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_gdap_clients(only: set[str] | None, skip: set[str]) -> list[dict]:
    if not GDAP_CSV.exists():
        print(f"[warn] {GDAP_CSV} not found", file=sys.stderr)
        return []
    clients = []
    with open(GDAP_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = row.get("client_code", "").strip().upper()
            if row.get("status", "").strip().lower() != "approved":
                continue
            if not row.get("tenant_id", "").strip():
                continue
            if only and code not in only:
                continue
            if code in skip:
                continue
            clients.append({
                "code": code,
                "name": row.get("client_name", code),
                "tenant_id": row["tenant_id"].strip(),
            })
    return clients


# ---------------------------------------------------------------------------
# Compliance scoring
# ---------------------------------------------------------------------------

def score_compliance(data: dict) -> dict:
    """Produce a pass/warn/fail checklist from pulled data."""
    checks = []

    # MFA
    mfa_users = data.get("mfa_registration", [])
    if mfa_users:
        registered = sum(1 for u in mfa_users if u.get("isMfaRegistered"))
        pct = round(registered / len(mfa_users) * 100, 1) if mfa_users else 0
        checks.append({
            "check": "MFA Registration",
            "status": "pass" if pct >= 90 else ("warn" if pct >= 70 else "fail"),
            "value": f"{pct}% ({registered}/{len(mfa_users)} users)",
            "detail": "Target: 100% of users registered for MFA"
        })

    # Conditional Access
    ca_policies = data.get("conditional_access", [])
    enabled_ca = [p for p in ca_policies if p.get("state") == "enabled"]
    checks.append({
        "check": "Conditional Access Policies",
        "status": "pass" if len(enabled_ca) >= 2 else ("warn" if len(enabled_ca) >= 1 else "fail"),
        "value": f"{len(enabled_ca)} enabled policies",
        "detail": "Minimum: block legacy auth + require MFA for admins"
    })

    # Legacy auth block (CA policy check)
    legacy_blocked = any(
        "block" in str(p.get("grantControls", {})).lower() and
        any("legacyAuthenticationProtocols" in str(c)
            for c in (p.get("conditions") or {}).get("clientAppTypes", []) or [str(p.get("conditions", {}))])
        for p in enabled_ca
    )
    security_defaults = data.get("security_defaults", {})
    sec_defaults_on = security_defaults.get("isEnabled", False)
    checks.append({
        "check": "Legacy Authentication Blocked",
        "status": "pass" if (legacy_blocked or sec_defaults_on) else "fail",
        "value": "Security defaults enabled" if sec_defaults_on else ("CA policy" if legacy_blocked else "Not blocked"),
        "detail": "Legacy auth bypasses MFA — must be blocked"
    })

    # Admin roles
    admin_roles = data.get("admin_roles", [])
    global_admins = next((r for r in admin_roles if r.get("displayName") == "Global Administrator"), None)
    if global_admins:
        ga_count = global_admins.get("memberCount", 0)
        checks.append({
            "check": "Global Administrator Count",
            "status": "pass" if ga_count <= 3 else ("warn" if ga_count <= 5 else "fail"),
            "value": f"{ga_count} Global Admins",
            "detail": "Best practice: 2-3 Global Admins maximum"
        })

    # Secure Score
    score_data = data.get("secure_score", {})
    if score_data:
        current = score_data.get("currentScore", 0)
        max_score = score_data.get("maxScore", 1)
        pct = round(current / max_score * 100, 1) if max_score else 0
        checks.append({
            "check": "Microsoft Secure Score",
            "status": "pass" if pct >= 60 else ("warn" if pct >= 40 else "fail"),
            "value": f"{current}/{max_score} ({pct}%)",
            "detail": "Target: >60% of available score"
        })

    # Guest users
    guests = data.get("guest_users", [])
    checks.append({
        "check": "Guest User Count",
        "status": "pass" if len(guests) == 0 else ("warn" if len(guests) <= 10 else "fail"),
        "value": f"{len(guests)} guest accounts",
        "detail": "Review external guest access regularly"
    })

    fail_count = sum(1 for c in checks if c["status"] == "fail")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    overall = "fail" if fail_count > 0 else ("warn" if warn_count > 0 else "pass")

    return {
        "overall": overall,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "checks": checks
    }


# ---------------------------------------------------------------------------
# Per-client pull
# ---------------------------------------------------------------------------

def pull_client(client: dict, month_str: str, dry_run: bool) -> dict:
    code = client["code"]
    tenant_id = client["tenant_id"]
    out_dir = CLIENTS_ROOT / code.lower() / "m365" / "compliance" / month_str

    summary: dict[str, Any] = {
        "client_code": code,
        "tenant_id": tenant_id,
        "month": month_str,
        "errors": [],
        "posture": {},
    }

    if dry_run:
        _safe_print(f"  [dry-run] {code} tenant={tenant_id}")
        return summary

    out_dir.mkdir(parents=True, exist_ok=True)
    pulled: dict[str, Any] = {}

    def _pull(key: str, fn, *args):
        try:
            data = fn(*args)
            (out_dir / f"{key}.json").write_text(
                json.dumps(data, indent=2), encoding="utf-8")
            pulled[key] = data
            return data
        except Exception as exc:
            summary["errors"].append({"source": key, "error": str(exc)})
            return None

    _pull("secure_score",        mapi.get_secure_score,              tenant_id)
    _pull("conditional_access",  mapi.get_conditional_access_policies, tenant_id)
    _pull("security_defaults",   mapi.get_security_defaults,          tenant_id)
    _pull("mfa_registration",    mapi.get_mfa_registration,           tenant_id)
    _pull("admin_roles",         mapi.get_admin_roles,                tenant_id)
    _pull("guest_users",         mapi.get_guest_users,                tenant_id)
    _pull("subscribed_skus",     mapi.get_subscribed_skus,            tenant_id)
    _pull("user_licenses",       mapi.get_user_licenses,              tenant_id)

    posture = score_compliance(pulled)
    summary["posture"] = posture
    (out_dir / "compliance_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _process_one(client: dict, month_str: str, dry_run: bool) -> tuple[dict, str]:
    code = client["code"]
    tenant_id = client["tenant_id"]
    try:
        s = pull_client(client, month_str, dry_run)
        posture = s.get("posture", {})
        overall = posture.get("overall", "?")
        fails = posture.get("fail_count", 0)
        warns = posture.get("warn_count", 0)
        return s, f"  {code} ({tenant_id[:8]}...)  OK  posture={overall}  fails={fails}  warns={warns}"
    except Exception as exc:
        return ({"client_code": code, "tenant_id": tenant_id,
                 "errors": [{"source": "tenant", "error": str(exc)}]},
                f"  {code} ({tenant_id[:8]}...)  ERROR: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Monthly M365 compliance posture pull")
    ap.add_argument("--month", help="YYYY-MM (default: current month)")
    ap.add_argument("--only", help="Comma-separated client codes")
    ap.add_argument("--skip", help="Comma-separated client codes to skip")
    ap.add_argument("--workers", type=int, default=6,
                    help="Parallel tenant workers (default 6).")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    month_str = args.month if args.month else now.strftime("%Y-%m")
    only = {c.strip().upper() for c in args.only.split(",")} if args.only else None
    skip = {c.strip().upper() for c in args.skip.split(",")} if args.skip else set()

    clients = load_gdap_clients(only, skip)
    if not clients:
        print("No GDAP-approved tenants found. Add entries to state/gdap_status.csv.")
        return

    workers = max(1, min(args.workers, len(clients)))
    print(f"M365 Compliance Pull | month: {month_str} | tenants: {len(clients)} | workers: {workers}")
    if args.dry_run:
        print("[dry-run] No API calls will be made.")

    summaries = []
    ok = err = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_process_one, c, month_str, args.dry_run): c
            for c in clients
        }
        for fut in as_completed(futures):
            s, status_line = fut.result()
            _safe_print(status_line)
            summaries.append(s)
            if "ERROR" in status_line:
                err += 1
            else:
                ok += 1

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    run_log = {
        "run_at": _isoz(now),
        "month": month_str,
        "workers": workers,
        "tenants_ok": ok,
        "tenants_error": err,
        "summaries": summaries,
    }
    log_path = STATE_DIR / f"compliance-{month_str}.json"
    log_path.write_text(json.dumps(run_log, indent=2), encoding="utf-8")
    print(f"\nDone. {ok} OK, {err} errors. Log: {log_path}")


if __name__ == "__main__":
    main()
