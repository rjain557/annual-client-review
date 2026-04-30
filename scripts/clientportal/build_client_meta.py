"""Write per-client _meta.json under clients/<code>/.

Each client folder gets a small metadata file so any pipeline (Sophos
ticket router, Meraki anomaly tickets, Huntress monthly report, etc.)
can resolve DirID, LocationCode, ContractID, recipient email — without
re-hitting the CP API on every call.

Source of truth:
  CP active clients          /api/clients/active
  Contracts (with signers)   GetAllContracts
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
      "ActiveContract": {
        "ContractID": 4567,
        "Contract_Name": "...",
        "ContractType": "...",
        "ContractStatusTxt": "Active",
        "DateSigned": "2024-05-30T...",
        "Signed_DirID": 9876
      },
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


# Technijian's own client identity in the CP directory. DirectoryType=Client,
# IsActive=True. Does NOT appear in /api/clients/active (which lists external
# clients only), so we have to surface it explicitly so internal-Technijian
# tickets can be opened against the right ClientID + ContractID.
TECHNIJIAN_DIRID = 139
TECHNIJIAN_INTERNAL_CONTRACT_ID = 3977   # "Internal Contract", ACTIVE, signed 2016-10-23


def write_technijian_meta(contracts: list[dict], dir_map: dict[int, str],
                         now_iso: str, dry_run: bool) -> bool:
    """Write clients/technijian/_meta.json — internal Technijian identity for
    automations that open INTERNAL tickets (Technijian-house infrastructure
    work, not client-billable). Looks up the live Internal Contract row.
    """
    folder = CLIENTS_ROOT / "technijian"
    if not folder.exists():
        print(f"  WARN: clients/technijian/ does not exist — skipping internal _meta.json")
        return False

    internal = next((c for c in contracts
                     if c.get("Contract_ID") == TECHNIJIAN_INTERNAL_CONTRACT_ID), None)
    contract_block = None
    if internal:
        contract_block = {
            "ContractID": int(internal["Contract_ID"]),
            "Contract_Name": internal.get("Contract_Name"),
            "ContractType": internal.get("ContractType"),
            "ContractStatusTxt": internal.get("ContractStatusTxt"),
            "DateSigned": internal.get("DateSigned"),
        }

    meta = {
        "LocationCode": "Technijian",
        "DirID": TECHNIJIAN_DIRID,
        "Location_Name": "TECHNIJIAN, INC",
        "Active": True,
        "Internal": True,
        "LocationTopFilter": dir_map.get(TECHNIJIAN_DIRID, ""),
        "Note": ("Service-provider identity — does NOT appear in "
                 "/api/clients/active. Use this DirID + ContractID for "
                 "tickets that bill against Technijian's internal cost "
                 "center (house infrastructure, automation, R&D), NOT "
                 "for client work."),
        "ActiveContract": contract_block,
        "updated_at": now_iso,
        "_source": {
            "dir": "stp_Get_All_Dir (DirID=139, DirectoryType=Client)",
            "contracts": "GetAllContracts (Contract_ID=3977, 'Internal Contract')",
        },
    }
    out_path = folder / "_meta.json"
    cid = contract_block["ContractID"] if contract_block else "—"
    if dry_run:
        print(f"  DRY  TECHNIJIAN dir_id={TECHNIJIAN_DIRID} internal_contract={cid}")
        return False
    out_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"  wrote TECHNIJIAN dir_id={TECHNIJIAN_DIRID} internal_contract={cid}")
    return True


def main() -> int:
    args = parse_args()
    only = None
    if args.only:
        only = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    print(f"[{datetime.now():%H:%M:%S}] fetching CP active clients...")
    cp_clients = cp_api.get_active_clients()
    print(f"  got {len(cp_clients)} active clients")

    print(f"[{datetime.now():%H:%M:%S}] fetching CP contracts...")
    contracts = cp_api.get_all_contracts()
    print(f"  got {len(contracts)} contract rows")

    print(f"[{datetime.now():%H:%M:%S}] fetching CP directory (LocationTopFilter)...")
    all_dir = cp_api.get_all_dir()
    dir_map: dict[int, str] = {}
    for d in all_dir:
        try:
            did = int(d.get("DirID") or -1)
        except (TypeError, ValueError):
            continue
        dir_map[did] = d.get("LocationTopFilter", "") or ""
    print(f"  got {len(dir_map)} directory entries")

    recipients = load_recipients()
    print(f"  loaded recipients for {len(recipients)} clients from {RECIPIENTS_CSV.name}")

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = 0
    skipped = 0
    folder_missing = 0
    no_contract = []  # codes with no Active signed contract resolved

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

        active_contract = cp_api.find_active_signed_contract(contracts, int(dir_id))
        contract_block = None
        if not active_contract:
            no_contract.append(code)
        if active_contract:
            cid_raw = active_contract.get("Contract_ID")
            try:
                cid = int(cid_raw) if cid_raw not in (None, "") else None
            except (TypeError, ValueError):
                cid = None
            signed_did_raw = active_contract.get("Signed_DirID")
            try:
                signed_did = int(signed_did_raw) if signed_did_raw not in (None, "") else None
            except (TypeError, ValueError):
                signed_did = None
            contract_block = {
                "ContractID": cid,
                "Contract_Name": active_contract.get("Contract_Name"),
                "ContractType": active_contract.get("ContractType"),
                "ContractStatusTxt": active_contract.get("ContractStatusTxt"),
                "DateSigned": active_contract.get("DateSigned"),
                "Signed_DirID": signed_did,
            }

        meta = {
            "LocationCode": code,
            "DirID": int(dir_id),
            "Location_Name": c.get("Location_Name"),
            "Active": True,
            "LocationTopFilter": dir_map.get(int(dir_id), ""),
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
            "ActiveContract": contract_block,
            "updated_at": now_iso,
            "_source": {
                "cp": "/api/clients/active",
                "contracts": "GetAllContracts",
                "recipients_csv": str(RECIPIENTS_CSV.relative_to(REPO)).replace("\\", "/"),
            },
        }

        out_path = client_dir / "_meta.json"
        contract_id_str = (str(contract_block["ContractID"]) if contract_block and contract_block.get("ContractID") else "—")
        if args.dry_run:
            print(f"  DRY  {code:<8s} dir_id={dir_id:<6} contract={contract_id_str:<6} send_ready={meta['Send_Ready']} recipients={len(meta['Recipient_Emails'])}")
            skipped += 1
            continue

        out_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        written += 1
        if written <= 5 or written % 10 == 0:
            print(f"  wrote {code:<8s} dir_id={dir_id:<6} contract={contract_id_str:<6} recipients={len(meta['Recipient_Emails'])}")

    print()
    print(f"[{datetime.now():%H:%M:%S}] writing Technijian internal _meta.json...")
    if not only or "TECHNIJIAN" in only:
        write_technijian_meta(contracts, dir_map, now_iso, args.dry_run)

    print()
    print(f"[{datetime.now():%H:%M:%S}] DONE")
    print(f"  written:        {written}")
    print(f"  dry-run only:   {skipped}")
    print(f"  folder missing: {folder_missing}")
    if no_contract:
        print(f"  no Active signed contract: {len(no_contract)} clients -> "
              f"ticket creation will be blocked for these. Codes: {', '.join(no_contract)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
