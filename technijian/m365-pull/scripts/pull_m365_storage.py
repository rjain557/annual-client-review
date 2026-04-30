"""Weekly M365 storage usage pull — Mailbox, OneDrive, SharePoint, Teams.

Teams channel files live in SharePoint team sites.
Teams chat attachments and recordings live in each user's OneDrive.
Both are captured here — no separate Teams quota exists.

Per-client output (clients/<code>/m365/storage/YYYY-WW/):
    mailbox_usage.json      per-mailbox: used, quota, pct
    onedrive_usage.json     per-user OneDrive: used, quota, pct
    sharepoint_usage.json   per-site: used, quota, pct, isTeamsSite flag
    org_totals.json         org-level totals for each service
    storage_summary.json    warnings (≥75%) and critical alerts (≥90%)

Thresholds:
    ≥75% used  →  warn
    ≥90% used  →  critical  (flag for CP ticket creation)

Usage:
    python pull_m365_storage.py                     # current week, all tenants
    python pull_m365_storage.py --period D30        # 30-day window
    python pull_m365_storage.py --only BWH,ORX
    python pull_m365_storage.py --dry-run
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

WARN_PCT = 75.0
CRIT_PCT = 90.0

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


def _storage_alerts(service: str, rows: list[dict], id_key: str) -> list[dict]:
    """Return rows over WARN_PCT threshold with severity tagging."""
    alerts = []
    for r in rows:
        pct = r.get("pctUsed")
        if pct is None or pct < WARN_PCT:
            continue
        alerts.append({
            "service": service,
            "identifier": r.get(id_key, ""),
            "displayName": r.get("displayName") or r.get("ownerDisplayName") or r.get("siteUrl", ""),
            "storageUsedGB": r.get("storageUsedGB"),
            "quotaGB": r.get("quotaGB"),
            "pctUsed": pct,
            "severity": "critical" if pct >= CRIT_PCT else "warn",
        })
    return alerts


# ---------------------------------------------------------------------------
# Per-client pull
# ---------------------------------------------------------------------------

def pull_client(client: dict, period: str, week_label: str, dry_run: bool) -> dict:
    code = client["code"]
    tenant_id = client["tenant_id"]
    out_dir = CLIENTS_ROOT / code.lower() / "m365" / "storage" / week_label

    summary: dict[str, Any] = {
        "client_code": code,
        "tenant_id": tenant_id,
        "week": week_label,
        "period": period,
        "errors": [],
        "alerts": [],
        "totals": {},
    }

    if dry_run:
        print(f"  [dry-run] {code}")
        return summary

    out_dir.mkdir(parents=True, exist_ok=True)
    all_alerts: list[dict] = []

    def _pull(key: str, fn, *args) -> list | dict | None:
        try:
            data = fn(*args)
            (out_dir / f"{key}.json").write_text(
                json.dumps(data, indent=2), encoding="utf-8")
            return data
        except Exception as exc:
            summary["errors"].append({"source": key, "error": str(exc)})
            traceback.print_exc()
            return None

    # Mailbox
    mailbox = _pull("mailbox_usage", mapi.get_mailbox_usage, tenant_id, period)
    if mailbox:
        all_alerts += _storage_alerts("mailbox", mailbox, "userPrincipalName")

    # OneDrive
    onedrive = _pull("onedrive_usage", mapi.get_onedrive_usage, tenant_id, period)
    if onedrive:
        all_alerts += _storage_alerts("onedrive", onedrive, "userPrincipalName")

    # SharePoint + Teams
    sharepoint = _pull("sharepoint_usage", mapi.get_sharepoint_usage, tenant_id, period)
    if sharepoint:
        teams_sites = [s for s in sharepoint if s.get("isTeamsSite")]
        sp_sites = [s for s in sharepoint if not s.get("isTeamsSite")]
        all_alerts += _storage_alerts("sharepoint", sp_sites, "siteUrl")
        all_alerts += _storage_alerts("teams_sharepoint", teams_sites, "siteUrl")

    # Org totals
    totals = _pull("org_totals", mapi.get_storage_org_totals, tenant_id, period)
    if totals:
        summary["totals"] = totals

    summary["alerts"] = sorted(all_alerts, key=lambda a: -(a.get("pctUsed") or 0))
    summary["alert_counts"] = {
        "critical": sum(1 for a in all_alerts if a["severity"] == "critical"),
        "warn": sum(1 for a in all_alerts if a["severity"] == "warn"),
    }
    (out_dir / "storage_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _process_one(client: dict, period: str, week_label: str, dry_run: bool) -> tuple[dict, str]:
    code = client["code"]
    try:
        s = pull_client(client, period, week_label, dry_run)
        counts = s.get("alert_counts", {})
        crit = counts.get("critical", 0)
        warn = counts.get("warn", 0)
        return s, f"  {code}  OK  critical={crit}  warn={warn}"
    except Exception as exc:
        return ({"client_code": code, "errors": [{"source": "tenant", "error": str(exc)}]},
                f"  {code}  ERROR: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Weekly M365 storage usage pull")
    ap.add_argument("--period", default="D7",
                    choices=["D7", "D30", "D90", "D180"],
                    help="Graph report period (default D7)")
    ap.add_argument("--only", help="Comma-separated client codes")
    ap.add_argument("--skip", help="Comma-separated client codes to skip")
    ap.add_argument("--workers", type=int, default=6,
                    help="Parallel tenant workers (default 6).")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    iso_cal = now.isocalendar()
    week_label = f"{iso_cal.year}-W{iso_cal.week:02d}"

    only = {c.strip().upper() for c in args.only.split(",")} if args.only else None
    skip = {c.strip().upper() for c in args.skip.split(",")} if args.skip else set()

    clients = load_gdap_clients(only, skip)
    if not clients:
        print("No GDAP-approved tenants. Add entries to state/gdap_status.csv.")
        return

    workers = max(1, min(args.workers, len(clients)))
    print(f"M365 Storage Pull | week: {week_label} | period: {args.period} | "
          f"tenants: {len(clients)} | workers: {workers}")
    if args.dry_run:
        print("[dry-run] No API calls.")

    summaries = []
    ok = err = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_process_one, c, args.period, week_label, args.dry_run): c
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
        "week": week_label,
        "period": args.period,
        "workers": workers,
        "tenants_ok": ok,
        "tenants_error": err,
        "summaries": summaries,
    }
    log_path = STATE_DIR / f"storage-{week_label}.json"
    log_path.write_text(json.dumps(run_log, indent=2), encoding="utf-8")
    print(f"\nDone. {ok} OK, {err} errors. Log: {log_path}")


if __name__ == "__main__":
    main()
