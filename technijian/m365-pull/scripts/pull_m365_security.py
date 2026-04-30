"""Daily M365 sign-in security pull — per GDAP-approved client tenant.

Pulls the last 24h of Azure AD sign-in logs, detects threats, and writes
per-client snapshots. Designed to run nightly at 06:00 PT (after CrowdStrike
at 03:00).

Per-client output (clients/<code>/m365/YYYY-MM-DD/):
    signin_logs.json        all sign-in events in window
    failed_signins.json     status.errorCode != 0 only
    risky_signins.json      riskLevelAggregated = medium/high (P2 only)
    risky_users.json        currently flagged risky users (P2 only)
    threat_summary.json     brute-force, spray, foreign-login flags
    pull_summary.json       counts, errors, window, tenant_id

Usage:
    python pull_m365_security.py                    # last 24h, all GDAP tenants
    python pull_m365_security.py --hours 168        # last 7 days
    python pull_m365_security.py --date 2026-04-29
    python pull_m365_security.py --only BWH,ORX
    python pull_m365_security.py --skip JDH
    python pull_m365_security.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
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


def compute_window(run_at: datetime, hours: int) -> tuple[str, str]:
    end = run_at.astimezone(timezone.utc).replace(microsecond=0)
    start = end - timedelta(hours=hours)
    return _isoz(start), _isoz(end)


def load_gdap_clients(only: set[str] | None, skip: set[str]) -> list[dict]:
    """Return approved GDAP clients from state/gdap_status.csv."""
    if not GDAP_CSV.exists():
        print(f"[warn] {GDAP_CSV} not found — no tenants to pull", file=sys.stderr)
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
# Threat detection
# ---------------------------------------------------------------------------

def analyze_threats(signins: list[dict]) -> dict:
    """Flag brute-force, password spray, foreign logins, legacy auth."""
    fail_by_user: dict[str, int] = defaultdict(int)
    fail_by_ip: dict[str, set] = defaultdict(set)
    foreign: list[dict] = []
    legacy: list[dict] = []
    mfa_failures = 0

    for s in signins:
        status = s.get("status", {})
        error = status.get("errorCode", 0)
        is_fail = error != 0
        country = (s.get("location") or {}).get("countryOrRegion", "")
        client_app = s.get("clientAppUsed", "")
        upn = s.get("userPrincipalName", "")
        ip = s.get("ipAddress", "")

        if is_fail:
            fail_by_user[upn] += 1
            fail_by_ip[ip].add(upn)
            if "MFA" in str(status.get("failureReason", "")):
                mfa_failures += 1

        if country and country not in ("US", "United States", ""):
            foreign.append({
                "user": upn, "country": country, "ip": ip,
                "success": not is_fail,
                "time": s.get("createdDateTime", "")
            })

        legacy_apps = ("Exchange ActiveSync", "IMAP", "POP3", "SMTP", "MAPI over HTTP",
                       "Other clients", "Authenticated SMTP")
        if any(a in client_app for a in legacy_apps):
            legacy.append({"user": upn, "app": client_app, "time": s.get("createdDateTime", "")})

    brute_force = [{"user": u, "failures": c} for u, c in fail_by_user.items() if c >= 10]
    spray_ips = [{"ip": ip, "users_targeted": list(users)}
                 for ip, users in fail_by_ip.items() if len(users) >= 5]

    return {
        "brute_force_users": sorted(brute_force, key=lambda x: -x["failures"]),
        "password_spray_ips": sorted(spray_ips, key=lambda x: -len(x["users_targeted"])),
        "foreign_logins": foreign[:100],
        "legacy_auth_logins": legacy[:50],
        "mfa_failures": mfa_failures,
        "flags": {
            "has_brute_force": bool(brute_force),
            "has_password_spray": bool(spray_ips),
            "has_foreign_success": any(f["success"] for f in foreign),
            "has_legacy_auth": bool(legacy),
            "high_mfa_failures": mfa_failures >= 5,
        }
    }


# ---------------------------------------------------------------------------
# Per-client pull
# ---------------------------------------------------------------------------

def pull_client(client: dict, win_start: str, win_end: str, dry_run: bool,
                chunk_hours: int = 24) -> dict:
    code = client["code"]
    tenant_id = client["tenant_id"]
    out_dir = CLIENTS_ROOT / code.lower() / "m365" / win_start[:10]

    summary: dict[str, Any] = {
        "client_code": code,
        "tenant_id": tenant_id,
        "window_start": win_start,
        "window_end": win_end,
        "counts": {},
        "errors": [],
        "flags": {},
    }

    if dry_run:
        _safe_print(f"  [dry-run] {code} tenant={tenant_id}")
        return summary

    out_dir.mkdir(parents=True, exist_ok=True)

    # Sign-in logs (chunked to avoid per-call timeouts on big tenants)
    try:
        chunk_errors: list[str] = []

        def _on_chunk(c_start, c_end, count, err):
            if err:
                chunk_errors.append(f"[{c_start[:10]}..{c_end[:10]}] {err[:200]}")

        signins = mapi.get_signin_logs_chunked(
            tenant_id, win_start, win_end,
            chunk_hours=chunk_hours,
            on_chunk=_on_chunk,
        )
        (out_dir / "signin_logs.json").write_text(
            json.dumps(signins, indent=2), encoding="utf-8")
        failed = [s for s in signins if (s.get("status") or {}).get("errorCode", 0) != 0]
        (out_dir / "failed_signins.json").write_text(
            json.dumps(failed, indent=2), encoding="utf-8")
        summary["counts"]["total_signins"] = len(signins)
        summary["counts"]["failed_signins"] = len(failed)
        threats = analyze_threats(signins)
        (out_dir / "threat_summary.json").write_text(
            json.dumps(threats, indent=2), encoding="utf-8")
        summary["flags"] = threats["flags"]
        if chunk_errors:
            summary["errors"].append({
                "source": "signin_logs_chunks",
                "error": f"{len(chunk_errors)} chunk(s) failed",
                "details": chunk_errors[:5],
            })
    except Exception as exc:
        summary["errors"].append({"source": "signin_logs", "error": str(exc)})

    # Risky sign-ins (P2)
    try:
        risky = mapi.get_risky_signins(tenant_id, win_start)
        (out_dir / "risky_signins.json").write_text(
            json.dumps(risky, indent=2), encoding="utf-8")
        summary["counts"]["risky_signins"] = len(risky)
    except Exception as exc:
        summary["errors"].append({"source": "risky_signins", "error": str(exc)})

    # Risky users (P2)
    try:
        risky_users = mapi.get_risky_users(tenant_id)
        (out_dir / "risky_users.json").write_text(
            json.dumps(risky_users, indent=2), encoding="utf-8")
        summary["counts"]["risky_users"] = len(risky_users)
    except Exception as exc:
        summary["errors"].append({"source": "risky_users", "error": str(exc)})

    (out_dir / "pull_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _process_one(client: dict, win_start: str, win_end: str, dry_run: bool,
                 chunk_hours: int) -> tuple[dict, str]:
    """Run pull for a single tenant. Returns (summary, status_line)."""
    code = client["code"]
    tenant_id = client["tenant_id"]
    try:
        s = pull_client(client, win_start, win_end, dry_run, chunk_hours)
        flags = s.get("flags", {})
        alerts = [k for k, v in flags.items() if v]
        if alerts:
            status = f"  {code} ({tenant_id[:8]}...)  OK  alerts={alerts}"
        elif s.get("errors"):
            status = f"  {code} ({tenant_id[:8]}...)  PARTIAL  errors={len(s['errors'])}"
        else:
            status = f"  {code} ({tenant_id[:8]}...)  OK  clean"
        return s, status
    except Exception as exc:
        return ({"client_code": code, "tenant_id": tenant_id,
                 "errors": [{"source": "tenant", "error": str(exc)}]},
                f"  {code} ({tenant_id[:8]}...)  ERROR: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Daily M365 sign-in security pull")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--date", help="Pull window ending at midnight of this date (YYYY-MM-DD)")
    ap.add_argument("--only", help="Comma-separated client codes")
    ap.add_argument("--skip", help="Comma-separated client codes to skip")
    ap.add_argument("--workers", type=int, default=6,
                    help="Parallel tenant workers (default 6). Each tenant has its own"
                         " Graph rate limit so this scales with tenant count.")
    ap.add_argument("--chunk-hours", type=int, default=24,
                    help="Sign-in query chunk size in hours (default 24). Smaller chunks"
                         " avoid per-call timeouts on tenants with very high sign-in volume.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    run_at = datetime.now(timezone.utc)
    if args.date:
        run_at = datetime.fromisoformat(args.date + "T00:00:00+00:00") + timedelta(days=1)

    win_start, win_end = compute_window(run_at, args.hours)
    only = {c.strip().upper() for c in args.only.split(",")} if args.only else None
    skip = {c.strip().upper() for c in args.skip.split(",")} if args.skip else set()

    clients = load_gdap_clients(only, skip)
    if not clients:
        print("No GDAP-approved tenants found. Add entries to state/gdap_status.csv.")
        return

    workers = max(1, min(args.workers, len(clients)))
    print(f"M365 Security Pull | window: {win_start} -> {win_end} | "
          f"tenants: {len(clients)} | workers: {workers} | chunk: {args.chunk_hours}h")
    if args.dry_run:
        print("[dry-run] No API calls will be made.")

    summaries = []
    ok = err = partial = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_process_one, c, win_start, win_end, args.dry_run, args.chunk_hours): c
            for c in clients
        }
        for fut in as_completed(futures):
            s, status_line = fut.result()
            _safe_print(status_line)
            summaries.append(s)
            if "ERROR" in status_line:
                err += 1
            elif "PARTIAL" in status_line:
                partial += 1
            else:
                ok += 1

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    run_log = {
        "run_at": _isoz(run_at),
        "window_start": win_start,
        "window_end": win_end,
        "workers": workers,
        "chunk_hours": args.chunk_hours,
        "tenants_ok": ok,
        "tenants_partial": partial,
        "tenants_error": err,
        "summaries": summaries,
    }
    log_path = STATE_DIR / f"security-{win_start[:10]}.json"
    log_path.write_text(json.dumps(run_log, indent=2), encoding="utf-8")
    print(f"\nDone. {ok} OK, {partial} partial, {err} errors. Log: {log_path}")


if __name__ == "__main__":
    main()
