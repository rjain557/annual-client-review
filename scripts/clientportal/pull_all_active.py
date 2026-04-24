"""Pull tickets + time entries + invoices for every active client since their
active contract was signed. Writes per-client folders under clients/<code>/data/.

Usage:
    python pull_all_active.py                 # run for all active clients
    python pull_all_active.py --skip BWH      # skip one or more codes (repeatable)
    python pull_all_active.py --only AAVA,VAF # only these codes
    python pull_all_active.py --dry-run       # list plan, don't fetch

Outputs (per client) under clients/<code>/data/:
    contract_summary.json         - active-contract metadata
    time_entries.xml              - raw XML from SP
    time_entries.json             - parsed array of time-entry dicts
    time_entries.csv              - flat CSV
    invoices.xml                  - raw XML from SP
    invoices.json                 - parsed array of invoice dicts
    invoices.csv                  - flat CSV
    tickets.json                  - derived set of unique tickets from time entries
    pull_log.json                 - summary of this run
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cp_api  # noqa: E402

PROJECT_ROOT = HERE.parent.parent
CLIENTS_ROOT = PROJECT_ROOT / "clients"


def derive_tickets(time_entries: list[dict]) -> list[dict]:
    """Group time entries by Title+Requestor to produce a unique-ticket list.
    The API time-entry XML doesn't carry a stable TicketID, but Title is the ticket
    subject and Requestor is the requester. We group by (Title, Requestor)."""
    by_key: dict[tuple[str, str], dict] = {}
    for te in time_entries:
        key = (te.get("Title", ""), te.get("Requestor", ""))
        agg = by_key.setdefault(key, {
            "Title": key[0],
            "Requestor": key[1],
            "EntryCount": 0,
            "FirstEntry": None,
            "LastEntry": None,
            "TotalHours_NH": 0.0,
            "TotalHours_AH": 0.0,
            "TotalQty": 0.0,
            "Categories": set(),
            "Resources": set(),
        })
        agg["EntryCount"] += 1
        dt = te.get("TimeEntryDate")
        if dt:
            if not agg["FirstEntry"] or dt < agg["FirstEntry"]:
                agg["FirstEntry"] = dt
            if not agg["LastEntry"] or dt > agg["LastEntry"]:
                agg["LastEntry"] = dt
        def _f(x: str) -> float:
            try: return float(x)
            except Exception: return 0.0
        agg["TotalHours_NH"] += _f(te.get("NH_HoursWorked", "0"))
        agg["TotalHours_AH"] += _f(te.get("AH_HoursWorked", "0"))
        agg["TotalQty"] += _f(te.get("Qty", "0"))
        if te.get("Category"): agg["Categories"].add(te["Category"])
        if te.get("AssignedName"): agg["Resources"].add(te["AssignedName"])
    out = []
    for v in by_key.values():
        v["Categories"] = sorted(v["Categories"])
        v["Resources"] = sorted(v["Resources"])
        out.append(v)
    out.sort(key=lambda r: r.get("LastEntry") or "", reverse=True)
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    cols: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k); cols.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: (", ".join(r[c]) if isinstance(r.get(c), list) else r.get(c, "")) for c in cols})


def pull_client(client: dict, active_contract: dict | None,
                dry_run: bool = False) -> dict:
    code = client["LocationCode"]
    did = client["DirID"]
    name = client["Location_Name"]
    out_dir = CLIENTS_ROOT / code.lower() / "data"
    summary: dict = {
        "LocationCode": code,
        "Location_Name": name,
        "DirID": did,
        "active_contract": None,
        "start_date": None,
        "end_date": date.today().isoformat(),
        "time_entry_count": 0,
        "invoice_count": 0,
        "ticket_count": 0,
        "errors": [],
        "dry_run": dry_run,
    }
    if active_contract:
        summary["active_contract"] = {
            "Contract_ID": active_contract["Contract_ID"],
            "Contract_Name": active_contract.get("Contract_Name"),
            "StartDate": active_contract.get("StartDate"),
            "EndDate": active_contract.get("EndDate"),
            "DateSigned": active_contract.get("DateSigned"),
            "ContractStatusTxt": active_contract.get("ContractStatusTxt"),
            "Under_Contract_Period": active_contract.get("Under_Contract_Period"),
            "Fixed_Rate_Cost": active_contract.get("Fixed_Rate_Cost"),
            "Over_Hours_Rate": active_contract.get("Over_Hours_Rate"),
        }
        ds = active_contract.get("DateSigned")
        if ds:
            summary["start_date"] = ds.split("T")[0]
    if not summary["start_date"]:
        sd = (active_contract or {}).get("StartDate")
        if sd:
            summary["start_date"] = sd.split("T")[0]
        else:
            summary["start_date"] = "2020-01-01"

    if dry_run:
        return summary

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "contract_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")

    # Time entries
    try:
        xml = cp_api.get_time_entries_xml(did, summary["start_date"], summary["end_date"])
        (out_dir / "time_entries.xml").write_text(xml or "", encoding="utf-8")
        tes = cp_api.parse_flat_xml(xml, "TimeEntry")
        summary["time_entry_count"] = len(tes)
        (out_dir / "time_entries.json").write_text(
            json.dumps(tes, indent=2), encoding="utf-8")
        write_csv(out_dir / "time_entries.csv", tes)
    except Exception as e:
        summary["errors"].append({"step": "time_entries", "err": str(e), "tb": traceback.format_exc()})
        tes = []

    # Derived tickets
    try:
        tks = derive_tickets(tes)
        summary["ticket_count"] = len(tks)
        (out_dir / "tickets.json").write_text(
            json.dumps(tks, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        summary["errors"].append({"step": "tickets", "err": str(e), "tb": traceback.format_exc()})

    # Invoices (all history for the client)
    try:
        inv_xml = cp_api.get_invoices_xml(did)
        (out_dir / "invoices.xml").write_text(inv_xml or "", encoding="utf-8")
        invs = cp_api.parse_flat_xml(inv_xml, "Invoice")
        summary["invoice_count"] = len(invs)
        (out_dir / "invoices.json").write_text(
            json.dumps(invs, indent=2), encoding="utf-8")
        write_csv(out_dir / "invoices.csv", invs)
    except Exception as e:
        summary["errors"].append({"step": "invoices", "err": str(e), "tb": traceback.format_exc()})

    (out_dir / "contract_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated LocationCodes to include")
    ap.add_argument("--skip", action="append", default=[],
                    help="LocationCode to skip (repeatable, case-insensitive)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    skip = {s.upper() for s in args.skip for s in s.split(",") if s.strip()}
    only = None
    if args.only:
        only = {s.strip().upper() for s in args.only.split(",") if s.strip()}

    print(f"[{datetime.now():%H:%M:%S}] fetching active clients...")
    clients = cp_api.get_active_clients()
    print(f"  got {len(clients)} active clients")
    print(f"[{datetime.now():%H:%M:%S}] fetching all contracts...")
    contracts = cp_api.get_all_contracts()
    print(f"  got {len(contracts)} contracts")

    overall: list[dict] = []
    for i, c in enumerate(clients, 1):
        code = c["LocationCode"].upper()
        if code in skip:
            print(f"  [{i}/{len(clients)}] skip {code}")
            continue
        if only is not None and code not in only:
            continue
        ac = cp_api.find_active_signed_contract(contracts, c["DirID"])
        if ac:
            eff = (ac.get("DateSigned") or ac.get("StartDate") or "")[:10] or "(none)"
            note = f"CID={ac['Contract_ID']} start={eff}"
        else:
            note = "no active contract"
        print(f"  [{i}/{len(clients)}] {code:<8s} DirID={c['DirID']:<6d} {note}")
        s = pull_client(c, ac, dry_run=args.dry_run)
        print(f"      -> time_entries={s['time_entry_count']} invoices={s['invoice_count']} "
              f"tickets={s['ticket_count']} errors={len(s['errors'])}")
        overall.append(s)

    log_path = CLIENTS_ROOT / "pull_log.json"
    log_path.write_text(json.dumps({
        "run_at": datetime.now().isoformat(),
        "clients_attempted": len(overall),
        "skipped": sorted(skip),
        "results": overall,
    }, indent=2, default=str), encoding="utf-8")
    print(f"[{datetime.now():%H:%M:%S}] wrote {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
