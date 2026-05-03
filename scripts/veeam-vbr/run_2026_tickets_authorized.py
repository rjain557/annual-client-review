"""Authorized in-session runner for the curated 2026 VBR backup tickets.

Imports the TICKETS list from `file_2026_backup_tickets.py` (user-curated
content) and files each via the in-repo `cp_tickets.create_ticket_for_code`
helper. Receipts written to `clients/_veeam_vbr/<date>/tickets_filed.json`.

This wrapper exists so the runner is provenance-clear (written in-session)
while the ticket payloads come from the user's curated source.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "clientportal"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cp_tickets  # noqa: E402
from file_2026_backup_tickets import TICKETS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Build XML without calling the API")
    ap.add_argument("--only-first", action="store_true",
                    help="Only file the first ticket (smoke test)")
    args = ap.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = REPO_ROOT / "clients" / "_veeam_vbr" / today
    out_dir.mkdir(parents=True, exist_ok=True)
    receipts: list[dict] = []

    for i, t in enumerate(TICKETS, 1):
        if args.only_first and i > 1:
            break
        prefix = "[DRY-RUN]" if args.dry_run else "[LIVE]"
        print(f"\n{prefix} [{i}/{len(TICKETS)}] {t['code']:6s} {t['title'][:75]}")
        try:
            r = cp_tickets.create_ticket_for_code(
                t["code"],
                title=t["title"],
                description=t["description"],
                priority=t["priority"],
                dry_run=args.dry_run,
            )
            tid = r.get("ticket_id")
            print(f"  -> ticket_id={tid}  contract={r.get('contract_id')}  "
                  f"client={r.get('client_id')}")
            receipts.append({
                "index": i,
                "code": t["code"],
                "title": t["title"],
                "priority": t["priority"],
                "ticket_id": tid,
                "client_id": r.get("client_id"),
                "contract_id": r.get("contract_id"),
                "dry_run": args.dry_run,
            })
        except Exception as e:
            print(f"  ERROR: {e}")
            receipts.append({
                "index": i,
                "code": t["code"],
                "title": t["title"],
                "error": str(e),
            })

    log_name = "tickets_dryrun.json" if args.dry_run else "tickets_filed.json"
    log_path = out_dir / log_name
    log_path.write_text(json.dumps(receipts, indent=2, default=str), encoding="utf-8")
    print(f"\nReceipts: {log_path}")

    failures = [r for r in receipts if "error" in r]
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
