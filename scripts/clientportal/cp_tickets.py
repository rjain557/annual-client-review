"""Canonical Client Portal ticket creation helper.

Wraps `cp_api.build_ticket_xml` + `cp_api.create_ticket_v3` so callers do not
have to know the SP signature or rebuild the XML envelope themselves.

Stored procedure: stp_xml_Tkt_API_CreateV3
Route: POST /api/modules/dbo/stored-procedures/client-portal/dbo/stp_xml_Tkt_API_CreateV3/execute

Required SP fields (per the CP API contract):
    Requestor_DirID, AssignTo_DirID, ContractID, Title, Priority, Status,
    Description, RequestType, RoleType, WorkType, ClientID

Optional SP fields with sensible defaults:
    AssetID=0, LocationTopFilter="", AssetTxt="", StatusTxt="",
    PriorityTxt="", ParentID=0, CreatedBy="clientportal@technijian.com",
    Category="API"

Usage from another module:

    from cp_tickets import create_ticket
    result = create_ticket(
        requestor_dir_id=12345,
        assign_to_dir_id=205,
        contract_id=789,
        client_id=12345,
        title="Sophos firewall alert: WAN1 down",
        description="Auto-routed from Sophos Central...",
        priority=1,
        status=1259,
        request_type="ClientPortal",
        role_type=1,
        work_type=14,
    )
    # result -> {"ticket_id": 98765, "raw": <SP response>, "xml_in": <payload>}

The wrapper never silently no-ops; on a failed create the response dict is
returned with `ticket_id=None` and the caller can inspect `raw` for the
error.

Constants here capture the operational defaults the user has approved for
automation-opened tickets — the Sophos router and any other automation
should import these rather than redefining them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

# scripts/clientportal lives next to cp_api; allow either direct invocation
# (python create_ticket.py) or import-as-module (sys.path.insert(...) by caller).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import cp_api  # noqa: E402

# Repo root for resolving clients/<code>/_meta.json
_REPO_ROOT = _HERE.parent.parent
_CLIENTS_ROOT = _REPO_ROOT / "clients"


# ---------------------------------------------------------------------------
# Operational defaults (importable constants)
# ---------------------------------------------------------------------------

# Resolved 2026-04-29 via stp_GetTechnijianUser_PodList:
#   DirID=205 = "CHD : TS1" (Chandigarh Tech Support) — India tech support pod
# Tech-support / break-fix automation should default here. Programming work
# would route to DirID=206 ("CHD : PR1") — set assign_to_dir_id explicitly
# in that case.
INDIA_SUPPORT_POD_DIRID = 205
INDIA_SUPPORT_POD_NAME = "CHD : TS1"

# Author/audit attribution for automation-opened tickets.
DEFAULT_CREATED_BY = "clientportal@technijian.com"
DEFAULT_CATEGORY = "API"
DEFAULT_REQUEST_TYPE = "ClientPortal"


# ---------------------------------------------------------------------------
# Lookup tables (source: SQL views supplied by Tharunaa Babu, 2026-04-30)
# ---------------------------------------------------------------------------

# vw_LookupV_Cal_RoleType_Get
ROLE_TYPES = {
    1231: "Development",
    1232: "Tech Support",
    1233: "CTO",
    1234: "Audit Manager",
    1235: "Systems Architect",
    1236: "Off-Shore Tech Support",
    1237: "Off-Shore Development",
    2593: "Wiring",
    2598: "Telco",
    2603: "Electrical",
    2825: "Onsite-Tech Support",
    2826: "Onsite-Development",
    2745: "Accounting",
    2753: "Outbound Sales",
    2752: "Inbound Sales",
    2754: "Internal",
}

# vw_LookupV_Ticket_Priority
PRIORITIES = {
    1253: "Critical",
    1254: "Immediate",
    1255: "Same Day",
    1256: "Next Day",
    1257: "When Convenient",
    1258: "Undetermined",
    2611: "Watch",
}

# vw_LookupV_Tkt_Status_NotComplete (only the "open" half — Closed=1275 is the
# only terminal status visible in the supplied screenshot; others not listed
# are presumably in vw_LookupV_Tkt_Status_Complete which we do not have yet).
STATUSES = {
    1259: "New",
    1260: "Opportunity Pending",
    1261: "Dispatched",
    1262: "In Progress",
    1263: "Escalated",
    1264: "Scheduled",
    1265: "Waiting Materials",
    1267: "Waiting Customer",
    1269: "Waiting Vendor",
    1270: "Follow Up Needed",
    1275: "Closed",
    2549: "Check with Client",
    2550: "Call the Client",
    2551: "Client Approval",
    2562: "Notify the Client",
    2563: "Client Notified",
    2609: "Client Approved",
    2610: "Client Rejected",
}

# Reverse maps for name->id lookup. Case-insensitive.
ROLE_TYPES_BY_NAME = {v.lower(): k for k, v in ROLE_TYPES.items()}
PRIORITIES_BY_NAME = {v.lower(): k for k, v in PRIORITIES.items()}
STATUSES_BY_NAME = {v.lower(): k for k, v in STATUSES.items()}


def _resolve_lookup(value, table_by_name: dict, table_by_id: dict, label: str) -> int:
    """Resolve a name or numeric id against a lookup table. Raises ValueError
    on unknown names; passes ints through untouched (callers may use a value
    not yet in our copy of the lookup view)."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        if value.isdigit():
            return int(value)
        key = value.strip().lower()
        if key in table_by_name:
            return table_by_name[key]
        valid = ", ".join(sorted(table_by_id.values()))
        raise ValueError(f"unknown {label} {value!r}. Valid: {valid}")
    raise TypeError(f"{label} must be int or str, got {type(value).__name__}")


# Numeric defaults — see cp-create-ticket SKILL.md for the rationale.
# Match the most common automation case: tech-support break-fix opened on a
# client's contract by an MSP automation, routed to the offshore pod.
DEFAULT_PRIORITY = 1257       # "When Convenient" — safe middle ground for automation
DEFAULT_STATUS = 1259         # "New"
DEFAULT_ROLE_TYPE = 1232      # "Tech Support" (override to 1236 "Off-Shore Tech Support" when assigning to CHD pods)
DEFAULT_WORK_TYPE = 14        # WorkType lookup not yet captured; preserved from user's example body


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_ticket(*,
                  requestor_dir_id: int,
                  client_id: int,
                  contract_id: int,
                  title: str,
                  description: str,
                  assign_to_dir_id: int = INDIA_SUPPORT_POD_DIRID,
                  priority=DEFAULT_PRIORITY,
                  status=DEFAULT_STATUS,
                  request_type: str = DEFAULT_REQUEST_TYPE,
                  role_type=DEFAULT_ROLE_TYPE,
                  work_type: int = DEFAULT_WORK_TYPE,
                  asset_id: int = 0,
                  location_top_filter: str = "",
                  asset_txt: str = "",
                  status_txt: str = "",
                  priority_txt: str = "",
                  parent_id: int = 0,
                  created_by: str = DEFAULT_CREATED_BY,
                  category: str = DEFAULT_CATEGORY,
                  dry_run: bool = False) -> dict:
    """Create a Client Portal ticket via stp_xml_Tkt_API_CreateV3.

    Required: requestor_dir_id, client_id, contract_id, title, description.
    Defaults cover the rest. Override priority/status/role/work-type when
    the caller knows the exact enum values.

    `priority`, `status`, `role_type` accept either a numeric id or the
    human-readable name from the lookup tables (e.g. "Same Day", "New",
    "Tech Support"). Names are case-insensitive.

    Set dry_run=True to build the XML payload without calling the API.
    Returns: {"ticket_id": int|None, "xml_in": str, "raw": dict, "dry_run": bool}
    """
    priority_id = _resolve_lookup(priority, PRIORITIES_BY_NAME, PRIORITIES, "priority")
    status_id = _resolve_lookup(status, STATUSES_BY_NAME, STATUSES, "status")
    role_type_id = _resolve_lookup(role_type, ROLE_TYPES_BY_NAME, ROLE_TYPES, "role_type")

    xml_in = cp_api.build_ticket_xml(
        requestor_dir_id=requestor_dir_id,
        assign_to_dir_id=assign_to_dir_id,
        contract_id=contract_id,
        title=title,
        priority=priority_id,
        status=status_id,
        description=description,
        request_type=request_type,
        role_type=role_type_id,
        work_type=work_type,
        client_id=client_id,
        asset_id=asset_id,
        location_top_filter=location_top_filter,
        asset_txt=asset_txt,
        status_txt=status_txt,
        priority_txt=priority_txt,
        parent_id=parent_id,
        created_by=created_by,
        category=category,
    )

    if dry_run:
        return {"ticket_id": None, "xml_in": xml_in, "raw": {}, "dry_run": True}

    raw = cp_api.create_ticket_v3(xml_in)
    ticket_id = cp_api.extract_ticket_id(raw)
    return {"ticket_id": ticket_id, "xml_in": xml_in, "raw": raw, "dry_run": False}


def load_client_meta(location_code: str) -> Optional[dict]:
    """Read clients/<code>/_meta.json. Case-insensitive on the folder name.

    Returns None if the file does not exist. Raises on parse error so the
    caller surfaces a corrupt cache rather than silently bypassing it.
    """
    code = (location_code or "").lower()
    path = _CLIENTS_ROOT / code / "_meta.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def lookup_client_id_and_contract(location_code: str) -> tuple[Optional[int], Optional[int]]:
    """Read DirID + ContractID from cached _meta.json.

    Returns (DirID, ContractID) — either may be None if missing in the
    cache. Use this when the caller wants the cached values without a
    round-trip to the API. To refresh stale data, run
    `python scripts/clientportal/build_client_meta.py [--only CODE]`.

    Special case: location_code in {"technijian", "TECHNIJIAN"} resolves to
    the internal Technijian identity (DirID=139, ContractID=3977 = "Internal
    Contract"). Use this for Technijian-house tickets that bill internally.
    """
    meta = load_client_meta(location_code)
    if not meta:
        return None, None
    dir_id = meta.get("DirID")
    contract_block = meta.get("ActiveContract") or {}
    contract_id = contract_block.get("ContractID")
    return (
        int(dir_id) if dir_id not in (None, "") else None,
        int(contract_id) if contract_id not in (None, "") else None,
    )


def lookup_active_contract_id(client_dir_id: int,
                              location_code: Optional[str] = None) -> Optional[int]:
    """Resolve a client's currently-active signed contract id.

    Cache-first: if `location_code` is supplied AND clients/<code>/_meta.json
    has a cached ContractID, returns that. Otherwise falls back to a live
    GetAllContracts query.

    Refresh the cache via `build_client_meta.py` whenever a new contract is
    signed (typically annually for managed-IT clients).
    """
    if location_code:
        meta = load_client_meta(location_code)
        if meta:
            cb = meta.get("ActiveContract") or {}
            cached = cb.get("ContractID")
            if cached not in (None, ""):
                try:
                    return int(cached)
                except (TypeError, ValueError):
                    pass  # fall through to live lookup

    contracts = cp_api.get_all_contracts()
    active = cp_api.find_active_signed_contract(contracts, client_dir_id)
    if not active:
        return None
    cid = active.get("Contract_ID")
    try:
        return int(cid) if cid not in (None, "") else None
    except (TypeError, ValueError):
        return None


def lookup_location_top_filter_by_dir_id(dir_id: int) -> str:
    """Scan clients/*/_meta.json to find the LocationTopFilter for a DirID.

    Used by callers that only have a DirID and no LocationCode. Returns ""
    if no matching _meta.json is found (e.g. a contact-only directory entry
    without a client folder).
    """
    for meta_path in _CLIENTS_ROOT.glob("*/_meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if int(meta.get("DirID", -1)) == dir_id:
                return meta.get("LocationTopFilter", "") or ""
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    return ""


def create_ticket_for_code(location_code: str, *,
                           title: str,
                           description: str,
                           **kwargs) -> dict:
    """Convenience wrapper: resolve DirID, ContractID, and LocationTopFilter
    from the cached _meta.json for the given LocationCode, then call
    create_ticket().

    Use this for any caller that has a LocationCode handy and wants the
    cache-first behavior. Raises RuntimeError if the cache is missing or
    incomplete — the caller should refresh via build_client_meta.py.

    LocationCode "Technijian" (or "technijian") routes to the internal
    Technijian identity for house-internal tickets.
    """
    meta = load_client_meta(location_code)
    if not meta:
        raise RuntimeError(
            f"clients/{location_code.lower()}/_meta.json not found or missing DirID. "
            "Run: python scripts/clientportal/build_client_meta.py "
            f"--only {location_code.upper()}"
        )
    dir_id = meta.get("DirID")
    if dir_id is None:
        raise RuntimeError(
            f"clients/{location_code.lower()}/_meta.json missing DirID. "
            "Run: python scripts/clientportal/build_client_meta.py "
            f"--only {location_code.upper()}"
        )
    contract_block = meta.get("ActiveContract") or {}
    contract_id = contract_block.get("ContractID")
    if contract_id is None:
        raise RuntimeError(
            f"clients/{location_code.lower()}/_meta.json has no ActiveContract.ContractID. "
            "This client has no Active signed contract — billable tickets cannot be created."
        )
    # Populate LocationTopFilter from cache unless the caller already supplied it.
    if "location_top_filter" not in kwargs:
        kwargs["location_top_filter"] = meta.get("LocationTopFilter", "") or ""
    return create_ticket(
        requestor_dir_id=int(dir_id),
        client_id=int(dir_id),
        contract_id=int(contract_id),
        title=title,
        description=description,
        **kwargs,
    )


__all__ = [
    "INDIA_SUPPORT_POD_DIRID",
    "INDIA_SUPPORT_POD_NAME",
    "DEFAULT_CREATED_BY",
    "DEFAULT_CATEGORY",
    "DEFAULT_REQUEST_TYPE",
    "DEFAULT_PRIORITY",
    "DEFAULT_STATUS",
    "DEFAULT_ROLE_TYPE",
    "DEFAULT_WORK_TYPE",
    "ROLE_TYPES",
    "PRIORITIES",
    "STATUSES",
    "ROLE_TYPES_BY_NAME",
    "PRIORITIES_BY_NAME",
    "STATUSES_BY_NAME",
    "create_ticket",
    "create_ticket_for_code",
    "lookup_active_contract_id",
    "lookup_client_id_and_contract",
    "lookup_location_top_filter_by_dir_id",
    "load_client_meta",
]
