"""Sophos Central Partner backfill — pull all 2026 activity we can.

What this captures (and what it does NOT):

YES (Partner API exposes this):
  - All currently OPEN alerts via /common/v1/alerts. These persist with
    `raisedAt` going back to whenever the alert first opened, so this is
    effectively "every still-open alert from 2026". Bucketed by raisedAt
    month into clients/<code>/sophos/monthly/<YYYY-MM>/alerts.json.
  - Current firewall inventory snapshot (point-in-time only).

NO (Partner API does not expose this):
  - SIEM /events older than 24h — the API returns HTTP 400 for any
    from_date older than ~24h. No way to backfill historical firewall
    connectivity events through the Partner API.
  - Resolved / acknowledged / closed alerts — /common/v1/alerts only
    returns status=open. status=resolved returns 0 items.
  - Per-signature firewall IPS/IDS event detail. That requires syslog
    forwarding from each XGS to the Technijian DC syslog receiver.

Usage:
    python backfill_sophos.py                       # all mapped tenants, full backlog
    python backfill_sophos.py --only AAVA,BWH
    python backfill_sophos.py --year 2026
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPELINE_ROOT = HERE.parent
REPO = PIPELINE_ROOT.parent.parent
CLIENTS_ROOT = REPO / "clients"
STATE_DIR = PIPELINE_ROOT / "state"
MAPPING_FILE = STATE_DIR / "sophos-tenant-mapping.json"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "scripts" / "clientportal"))
import sophos_api as sapi  # noqa: E402
import cp_api  # noqa: E402

from pull_sophos_daily import (  # noqa: E402
    load_manual_mapping,
    resolve_mapping,
    flatten_firewall,
    write_csv,
    FIREWALL_PREFERRED_COLS,
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Backfill all retrievable Sophos history per client.")
    ap.add_argument("--only", help="comma-separated LocationCodes")
    ap.add_argument("--year", type=int, default=2026, help="filter alerts to this year (default 2026)")
    return ap.parse_args()


def fetch_all_alerts(tenant: dict) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        r = sapi.tenant_get(tenant, "/common/v1/alerts", {"pageSize": "100", "page": str(page)})
        if r["status"] != 200 or not isinstance(r["body"], dict):
            break
        items = r["body"].get("items", [])
        out.extend(items)
        pages = r["body"].get("pages") or {}
        total_pages = int(pages.get("total") or pages.get("totalPages") or 1)
        if page >= total_pages or not items:
            break
        page += 1
    return out


def main() -> int:
    args = parse_args()
    only_codes = None
    if args.only:
        only_codes = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    print(f"[{datetime.now():%H:%M:%S}] Sophos Central Partner backfill (year={args.year})")
    print(f"[{datetime.now():%H:%M:%S}] fetching active CP clients + Sophos tenants...")
    cp_clients = cp_api.get_active_clients()
    me = sapi.whoami()
    tenants = sapi.list_tenants()
    print(f"  cp_clients={len(cp_clients)}  partner_id={me['id']}  tenants={len(tenants)}")

    manual = load_manual_mapping()
    ignore = {str(x) for x in (manual.get("ignore") or [])}
    mapping, _ = resolve_mapping(tenants, cp_clients, manual.get("manual") or {}, ignore=ignore)
    print(f"  mapped tenants: {len(mapping)}")

    grand_alerts_by_month: dict[str, int] = defaultdict(int)
    grand_total = 0

    for tid, info in sorted(mapping.items(), key=lambda kv: kv[1]["LocationCode"]):
        code = info["LocationCode"]
        if only_codes and code not in only_codes:
            continue
        tenant = {"id": tid, "apiHost": info["apiHost"]}

        # 1) Pull every open alert
        alerts = fetch_all_alerts(tenant)

        # 2) Pull firewall inventory snapshot (current)
        try:
            firewalls = sapi.list_firewalls(tenant)
        except Exception:
            firewalls = []

        # 3) Bucket alerts by raisedAt month
        by_month: dict[str, list[dict]] = defaultdict(list)
        for a in alerts:
            raised = a.get("raisedAt") or a.get("updatedAt") or ""
            try:
                dt = datetime.fromisoformat(raised.replace("Z", "+00:00")) if raised else None
            except Exception:
                dt = None
            if not dt or dt.year != args.year:
                continue
            ym = f"{dt.year:04d}-{dt.month:02d}"
            by_month[ym].append(a)

        # 4) Write per-month folders
        client_dir = CLIENTS_ROOT / code.lower() / "sophos" / "monthly"
        client_dir.mkdir(parents=True, exist_ok=True)

        per_month_counts = []
        for ym, items in sorted(by_month.items()):
            md = client_dir / ym
            md.mkdir(parents=True, exist_ok=True)
            (md / "alerts.json").write_text(
                json.dumps(items, indent=2, default=str), encoding="utf-8")
            sev = {"high": 0, "medium": 0, "low": 0, "informational": 0}
            cat: dict[str, int] = {}
            prod: dict[str, int] = {}
            for a in items:
                s = a.get("severity") or "?"
                sev[s] = sev.get(s, 0) + 1
                c = a.get("category") or "?"
                cat[c] = cat.get(c, 0) + 1
                p = a.get("product") or "?"
                prod[p] = prod.get(p, 0) + 1
            (md / "pull_summary.json").write_text(json.dumps({
                "LocationCode": code,
                "sophos_tenant_id": tid,
                "sophos_tenant_name": info["sophos_tenant_name"],
                "year_month": ym,
                "alerts_total": len(items),
                "alerts_by_severity": sev,
                "alerts_by_category": cat,
                "alerts_by_product": prod,
                "data_caveats": {
                    "scope": "Open alerts only — Sophos /common/v1/alerts does not return resolved/closed alerts.",
                    "siem_events": "Not backfilled — Partner SIEM /events has 24h max lookback.",
                    "ips_ids": "Not in this dataset — captured via syslog receiver, not Partner API.",
                },
                "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }, indent=2), encoding="utf-8")
            per_month_counts.append((ym, len(items)))
            grand_alerts_by_month[ym] += len(items)
            grand_total += len(items)

        # 5) Write current firewall snapshot under monthly/<latest_month>/firewalls.* alongside
        if firewalls and per_month_counts:
            latest_ym = sorted(per_month_counts)[-1][0]
            md = client_dir / latest_ym
            md.mkdir(parents=True, exist_ok=True)
            flat = [flatten_firewall(fw) for fw in firewalls]
            (md / "firewalls.json").write_text(
                json.dumps(firewalls, indent=2, default=str), encoding="utf-8")
            write_csv(md / "firewalls.csv", flat, FIREWALL_PREFERRED_COLS)

        # Console summary line
        months_summary = " ".join(f"{ym}={n}" for ym, n in sorted(per_month_counts)) or "(no alerts in window)"
        print(f"  {code:<8s} alerts_total={len(alerts):>3d} fws={len(firewalls)} | {months_summary}")

    print()
    print(f"[{datetime.now():%H:%M:%S}] DONE")
    print(f"  grand total alerts bucketed: {grand_total}")
    print(f"  by month: " + " ".join(f"{ym}={grand_alerts_by_month[ym]}" for ym in sorted(grand_alerts_by_month)))
    print(f"  output: clients/<code>/sophos/monthly/YYYY-MM/")
    print()
    print("  IMPORTANT: this is the OPEN alert backlog only. Resolved/closed alerts and")
    print("  historical SIEM events are not retrievable through the Partner API. For full")
    print("  IPS/IDS detail, route firewall syslog to the Technijian DC receiver.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
