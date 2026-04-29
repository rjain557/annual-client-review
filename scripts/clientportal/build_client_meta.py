"""Write per-client _meta.json under clients/<code>/.

Each client folder gets a small metadata file so any pipeline (Sophos
ticket router, Huntress monthly report, etc.) can resolve DirID +
LocationCode + recipient email without re-hitting the CP API.

Source of truth:
  CP active clients          /api/clients/active
  Recipient resolution       technijian/contacts/active_client_recipients.csv

Output (per active client):
  clients/<code>/_meta.json
    {
      "LocationCode": "BWH",
      "DirID": 12345,
      "Location_Name": "Brandywine Homes",
      "Active": true,
      "Data_Signals": ["huntress", "crowdstrike", "umbrella"],
      "Recipient_Emails": ["jane@brandywine.example"],
      "Recipient_Source": "portal-primary | contract-signer | none",
      "Send_Ready": true,
      "Has_Legal_File": true,
      "updated_at": "ISO 8601"
    }

Usage:
    python scripts/clientportal/build_client_meta.py            # all clients
    python scripts/clientportal/build_client_meta.py --only BWH,KSS
    python scripts/clientportal/build_client_meta.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CLIENTS_ROOT = REPO / "clients"
RECIPIENTS_CSV = REPO / "technijian" / "contacts" / "active_client_recipients.csv"

sys.path.insert(0, str(HERE))
import cp_api  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Write per-client _meta.json")
    ap.add_argument("--only", help="comma-separated LocationCodes")
    ap.add_argument("--dry-run", action="store_true", help="don't write")
    return ap.parse_args()


def load_recipients() -> dict[str, dict]:
    """Return {LocationCode: row} from active_client_recipients.csv."""
    out: dict[str, dict] = {}
    if not RECIPIENTS_CSV.exists():
        return out
    with RECIPIENTS_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = (row.get("LocationCode") or "").upper()
            if code:
                out[code] = row
    return out


def split_emails(s: str | None) -> list[str]:
    if not s:
        return []
    return [e.strip() for e in s.replace(";", ",").split(",") if e.strip()]


def main() -> int:
    args = parse_args()
    only = None
    if args.only:
        only = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    print(f"[{datetime.now():%H:%M:%S}] fetching CP active clients...")
    cp_clients = cp_api.get_active_clients()
    print(f"  got {len(cp_clients)} active clients")

    recipients = load_recipients()
    print(f"  loaded recipients for {len(recipients)} clients from {RECIPIENTS_CSV.name}")

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = 0
    skipped = 0
    folder_missing = 0

    for c in cp_clients:
        code = (c.get("LocationCode") or "").upper()
        dir_id = c.get("DirID")
        if not code or not dir_id:
            continue
        if only and code not in only:
            continue

        client_dir = CLIENTS_ROOT / code.lower()
        if not client_dir.exists():
            folder_missing += 1
            print(f"  WARN: {code:<8s} CP active but clients/{code.lower()}/ does not exist (skipping)")
            continue

        rec = recipients.get(code, {})
        meta = {
            "LocationCode": code,
            "DirID": int(dir_id),
            "Location_Name": c.get("Location_Name"),
            "Active": True,
            "Data_Signals": split_emails(rec.get("Data_Signals")) if rec.get("Data_Signals") else [],
            "Has_Legal_File": (rec.get("Has_Legal_File") or "").lower() == "true",
            "Has_Designated_Recipient": (rec.get("Has_Designated_Recipient") or "").lower() == "true",
            "Recipient_Emails": split_emails(rec.get("Recipient_Emails")),
            "Recipient_Source": rec.get("Recipient_Source") or "",
            "Contract_Signer": rec.get("Contract_Signer") or "",
            "Invoice_Recipient": rec.get("Invoice_Recipient") or "",
            "Primary_Contact": rec.get("Primary_Contact") or "",
            "Send_Ready": (rec.get("Send_Ready") or "").lower() == "true",
            "Time_Entries_This_Month": int(rec.get("Time_Entries_This_Month") or 0) if (rec.get("Time_Entries_This_Month") or "").isdigit() else 0,
            "Total_Active_Users": int(rec.get("Total_Active_Users") or 0) if (rec.get("Total_Active_Users") or "").isdigit() else 0,
            "CP_Only": (rec.get("CP_Only") or "").lower() == "true",
            "updated_at": now_iso,
            "_source": {
                "cp": "/api/clients/active",
                "recipients_csv": str(RECIPIENTS_CSV.relative_to(REPO)).replace("\\", "/"),
            },
        }

        out_path = client_dir / "_meta.json"
        if args.dry_run:
            print(f"  DRY  {code:<8s} dir_id={dir_id:<6} send_ready={meta['Send_Ready']} recipients={len(meta['Recipient_Emails'])}")
            skipped += 1
            continue

        out_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        written += 1
        if written <= 5 or written % 10 == 0:
            print(f"  wrote {code:<8s} dir_id={dir_id:<6} recipients={len(meta['Recipient_Emails'])}")

    print()
    print(f"[{datetime.now():%H:%M:%S}] DONE")
    print(f"  written:        {written}")
    print(f"  dry-run only:   {skipped}")
    print(f"  folder missing: {folder_missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
