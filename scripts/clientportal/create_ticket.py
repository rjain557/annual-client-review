"""CLI wrapper around cp_tickets.create_ticket.

Examples:

    # Dry run — build the XML payload, print it, do not call the API
    python create_ticket.py --client-id 12345 --requestor 12345 \
        --contract 789 --title "Test" --description "Hello" --dry-run

    # Auto-resolve contract from the active signed contract
    python create_ticket.py --client-code AAVA --auto-contract \
        --title "Sophos alert: WAN1 down" \
        --description "Auto-routed from Sophos Central"

    # Read description from a file (or stdin with -)
    python create_ticket.py --client-id 123 --requestor 123 --contract 789 \
        --title "Long body" --description-file body.txt

    # Override the assignee (default = INDIA_SUPPORT_POD_DIRID = 205)
    python create_ticket.py ... --assign-to 206

    # Override numeric enums
    python create_ticket.py ... --priority 2 --status 1259 \
        --role-type 1 --work-type 14

The script writes a JSON receipt to stdout (or --out PATH). Exit code is 0
on success (ticket_id != None), 2 on dry-run-only, 1 on any error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import cp_api          # noqa: E402
import cp_tickets      # noqa: E402


def _resolve_client_dir_id(args: argparse.Namespace) -> int:
    if args.client_id is not None:
        return int(args.client_id)
    if args.client_code:
        # Cache-first: read clients/<code>/_meta.json
        meta = cp_tickets.load_client_meta(args.client_code)
        if meta and meta.get("DirID"):
            return int(meta["DirID"])
        # Fallback to live lookup (also handles Technijian which is not in /active)
        clients = cp_api.get_active_clients()
        code = args.client_code.upper()
        for c in clients:
            if (c.get("LocationCode") or "").upper() == code:
                return int(c["DirID"])
        raise SystemExit(
            f"client code {args.client_code!r} not in clients/{args.client_code.lower()}/_meta.json "
            "or /api/clients/active. Run: python scripts/clientportal/build_client_meta.py "
            f"--only {args.client_code.upper()}"
        )
    raise SystemExit("must specify --client-id or --client-code")


def _read_description(args: argparse.Namespace) -> str:
    if args.description is not None:
        return args.description
    if args.description_file:
        if args.description_file == "-":
            return sys.stdin.read()
        return Path(args.description_file).read_text(encoding="utf-8")
    raise SystemExit("must specify --description or --description-file")


def main() -> int:
    p = argparse.ArgumentParser(description="Create a Technijian Client Portal ticket")

    # Client + contract resolution
    g = p.add_argument_group("Client & contract")
    g.add_argument("--client-id", type=int,
                   help="Client DirID (= ClientID for the SP). Use this OR --client-code.")
    g.add_argument("--client-code",
                   help="Client LocationCode (e.g. AAVA). Resolved via /api/clients/active.")
    g.add_argument("--requestor", type=int,
                   help="Requestor_DirID. Defaults to --client-id when omitted.")
    g.add_argument("--contract", type=int,
                   help="ContractID. Use --auto-contract to resolve from the active signed contract.")
    g.add_argument("--auto-contract", action="store_true",
                   help="Look up the client's currently-active signed contract via GetAllContracts.")

    # Ticket fields
    t = p.add_argument_group("Ticket fields")
    t.add_argument("--title", required=True)
    t.add_argument("--description", help="Inline description text.")
    t.add_argument("--description-file",
                   help='Path to a file (or "-" for stdin) containing the description.')

    t.add_argument("--assign-to", type=int, default=cp_tickets.INDIA_SUPPORT_POD_DIRID,
                   help=f"AssignTo_DirID (default {cp_tickets.INDIA_SUPPORT_POD_DIRID} = {cp_tickets.INDIA_SUPPORT_POD_NAME})")
    t.add_argument("--priority", default=str(cp_tickets.DEFAULT_PRIORITY),
                   help=("Priority — id (1253-2611) OR name. "
                         "Names: " + ", ".join(cp_tickets.PRIORITIES.values()) + ". "
                         f"Default {cp_tickets.DEFAULT_PRIORITY} = {cp_tickets.PRIORITIES[cp_tickets.DEFAULT_PRIORITY]!r}"))
    t.add_argument("--status", default=str(cp_tickets.DEFAULT_STATUS),
                   help=("Status — id (1259+) OR name. "
                         "Names: " + ", ".join(cp_tickets.STATUSES.values()) + ". "
                         f"Default {cp_tickets.DEFAULT_STATUS} = {cp_tickets.STATUSES[cp_tickets.DEFAULT_STATUS]!r}"))
    t.add_argument("--request-type", default=cp_tickets.DEFAULT_REQUEST_TYPE,
                   help=f"RequestType (default {cp_tickets.DEFAULT_REQUEST_TYPE!r})")
    t.add_argument("--role-type", default=str(cp_tickets.DEFAULT_ROLE_TYPE),
                   help=("RoleType — id (1231+) OR name. "
                         "Names: " + ", ".join(cp_tickets.ROLE_TYPES.values()) + ". "
                         f"Default {cp_tickets.DEFAULT_ROLE_TYPE} = {cp_tickets.ROLE_TYPES[cp_tickets.DEFAULT_ROLE_TYPE]!r}"))
    t.add_argument("--work-type", type=int, default=cp_tickets.DEFAULT_WORK_TYPE,
                   help=f"WorkType enum (default {cp_tickets.DEFAULT_WORK_TYPE})")

    t.add_argument("--asset-id", type=int, default=0)
    t.add_argument("--location-top-filter", default="")
    t.add_argument("--asset-txt", default="")
    t.add_argument("--status-txt", default="")
    t.add_argument("--priority-txt", default="")
    t.add_argument("--parent-id", type=int, default=0)
    t.add_argument("--created-by", default=cp_tickets.DEFAULT_CREATED_BY)
    t.add_argument("--category", default=cp_tickets.DEFAULT_CATEGORY)

    # Run mode
    r = p.add_argument_group("Run mode")
    r.add_argument("--dry-run", action="store_true",
                   help="Build the XML payload but DO NOT call the API. Exit code 2.")
    r.add_argument("--out",
                   help="Path to write the JSON receipt. Default: stdout.")
    r.add_argument("--include-raw", action="store_true",
                   help="Include the full SP response in the receipt (default: omit on success).")

    args = p.parse_args()

    client_dir_id = _resolve_client_dir_id(args)
    requestor = args.requestor if args.requestor is not None else client_dir_id

    if args.contract is not None:
        contract_id = int(args.contract)
    elif args.auto_contract:
        # Cache-first via location_code, falls back to live GetAllContracts
        contract_id = cp_tickets.lookup_active_contract_id(
            client_dir_id, location_code=args.client_code)
        if contract_id is None:
            print(f"[error] no Active signed contract found for ClientID={client_dir_id}. "
                  f"Refresh: python scripts/clientportal/build_client_meta.py",
                  file=sys.stderr)
            return 1
    else:
        print("[error] must specify --contract <id> or --auto-contract", file=sys.stderr)
        return 1

    description = _read_description(args)

    try:
        result = cp_tickets.create_ticket(
            requestor_dir_id=requestor,
            client_id=client_dir_id,
            contract_id=contract_id,
            title=args.title,
            description=description,
            assign_to_dir_id=args.assign_to,
            priority=args.priority,
            status=args.status,
            request_type=args.request_type,
            role_type=args.role_type,
            work_type=args.work_type,
            asset_id=args.asset_id,
            location_top_filter=args.location_top_filter,
            asset_txt=args.asset_txt,
            status_txt=args.status_txt,
            priority_txt=args.priority_txt,
            parent_id=args.parent_id,
            created_by=args.created_by,
            category=args.category,
            dry_run=args.dry_run,
        )
    except Exception as e:
        receipt = {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "client_id": client_dir_id,
            "contract_id": contract_id,
            "requestor_dir_id": requestor,
        }
        out = json.dumps(receipt, indent=2)
        if args.out:
            Path(args.out).write_text(out, encoding="utf-8")
        print(out)
        return 1

    receipt = {
        "ok": result["ticket_id"] is not None or result["dry_run"],
        "dry_run": result["dry_run"],
        "ticket_id": result["ticket_id"],
        "client_id": client_dir_id,
        "contract_id": contract_id,
        "requestor_dir_id": requestor,
        "assign_to_dir_id": args.assign_to,
        "title": args.title,
        "xml_in": result["xml_in"],
    }
    if args.include_raw or result["ticket_id"] is None and not result["dry_run"]:
        receipt["raw"] = result["raw"]

    out = json.dumps(receipt, indent=2)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
    print(out)

    if result["dry_run"]:
        return 2
    return 0 if result["ticket_id"] is not None else 1


if __name__ == "__main__":
    sys.exit(main())
