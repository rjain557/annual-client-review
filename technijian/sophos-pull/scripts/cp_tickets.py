"""Sophos alert router compatibility shim.

The canonical Client Portal ticket-create helper now lives at
`scripts/clientportal/cp_tickets.py` next to `cp_api.py`. This shim:

  - Re-exports the high-level `create_ticket(...)` from the canonical module
    with a Sophos-friendly call signature (subject/description, opener_id,
    billable kwarg) so `route_alerts.py` does not need a refactor.
  - Re-exports the operational defaults (`INDIA_SUPPORT_POD`,
    `CLIENT_BILLABLE`) the router prints in routing-plan.json.

Sophos client alerts are CLIENT-BILLABLE — they hit the client's contract
via `ContractID`, not Technijian's internal cost center. The router's
`billable=True` convention is preserved here. There is currently no
SP-level billable flag in `stp_xml_Tkt_API_CreateV3`; ContractID itself
encodes the billing entity.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# The canonical module lives at scripts/clientportal/cp_tickets.py — same
# filename as this shim, so a plain `import cp_tickets` collides via
# sys.modules. Load by file path under a different module name.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CP_SCRIPTS = _REPO_ROOT / "scripts" / "clientportal"
if str(_CP_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CP_SCRIPTS))  # so cp_api.py is importable from the canonical module

_canonical_path = _CP_SCRIPTS / "cp_tickets.py"
_spec = importlib.util.spec_from_file_location("cp_tickets_canonical", _canonical_path)
_canonical = importlib.util.module_from_spec(_spec)
sys.modules["cp_tickets_canonical"] = _canonical
_spec.loader.exec_module(_canonical)

# ---- Re-exported defaults the router reads ---------------------------------

# Resolved 2026-04-29 via stp_GetTechnijianUser_PodList:
#   DirID=205  CHD : TS1  (Chandigarh Tech Support) — India tech support pod
INDIA_SUPPORT_POD = _canonical.INDIA_SUPPORT_POD_DIRID
INDIA_SUPPORT_POD_NAME = _canonical.INDIA_SUPPORT_POD_NAME

# Sophos alerts are client-billable by default (against the managed-IT
# contract, NOT Technijian internal). ContractID resolution at call time
# enforces this — there is no separate SP flag.
CLIENT_BILLABLE = True
INTERNAL_TICKET = False

# Default priority/category for Sophos alert tickets. Maps free-text severity
# strings to the CP Priority lookup ids.
#   Critical -> 1253 "Critical"        (Sophos critical alerts)
#   High     -> 1255 "Same Day"        (Sophos high alerts)
#   Medium   -> 1256 "Next Day"        (Sophos medium alerts)
#   Low      -> 1257 "When Convenient" (Sophos low / informational)
#   Normal   -> 1257 "When Convenient" (legacy default)
PRIORITY_BY_SEVERITY = {
    "critical": 1253,
    "high": 1255,
    "medium": 1256,
    "low": 1257,
    "normal": 1257,
    "info": 2611,        # 2611 = "Watch"
    "informational": 2611,
}
DEFAULT_PRIORITY = "Normal"  # legacy free-text — translated below
AUTOMATION_OPENER_ID = _canonical.DEFAULT_CREATED_BY


def create_ticket(*,
                  client_dir_id: int,
                  subject: str,
                  description: str,
                  assigned_to: int = INDIA_SUPPORT_POD,
                  priority=DEFAULT_PRIORITY,
                  source: str = "Sophos Central (auto)",
                  opener_id: str = AUTOMATION_OPENER_ID,
                  billable: bool = CLIENT_BILLABLE) -> dict:
    """Create a CP ticket for a Sophos alert.

    Args:
        client_dir_id: CP DirID of the client this ticket is FOR (their
            contract is what gets billed).
        subject / description: human-readable text -> Title / Description.
        assigned_to: AssignTo_DirID; defaults to the India support pod.
        priority: legacy free-text priority; ignored when not numeric.
            Translated to Priority=1 (Normal) unless overridden upstream.
        source: free-form attribution string prepended to the description.
        opener_id: CreatedBy attribution string for the audit log.
        billable: True = client-billable. Currently advisory — ContractID
            resolution determines the billing entity.

    Returns: {"ticket_id": <id|None>, "ticket_url": <url|None>, "raw": <SP response>}
    Raises: RuntimeError if no Active signed contract exists for the client.
    """
    contract_id = _canonical.lookup_active_contract_id(client_dir_id)
    if contract_id is None:
        raise RuntimeError(
            f"No Active signed contract for ClientID={client_dir_id}; "
            "cannot create a billable ticket. Resolve via the contracts pipeline."
        )

    body = description if not source else f"[{source}]\n{description}"

    # Map free-text severity to a CP Priority lookup id.
    if isinstance(priority, int):
        priority_int = priority
    else:
        key = (priority or "").strip().lower()
        priority_int = PRIORITY_BY_SEVERITY.get(key, _canonical.DEFAULT_PRIORITY)

    # Sophos client alerts route to the offshore tech-support pod, so the
    # right RoleType is "Off-Shore Tech Support" (1236), not the canonical
    # default of 1232 "Tech Support".
    location_top_filter = _canonical.lookup_location_top_filter_by_dir_id(client_dir_id)
    result = _canonical.create_ticket(
        requestor_dir_id=client_dir_id,
        client_id=client_dir_id,
        contract_id=contract_id,
        title=subject,
        description=body,
        assign_to_dir_id=assigned_to,
        priority=priority_int,
        role_type=1236,  # Off-Shore Tech Support
        location_top_filter=location_top_filter,
        created_by=opener_id,
    )
    return {
        "ticket_id": result["ticket_id"],
        "ticket_url": None,  # CP does not expose a stable per-ticket URL via this SP
        "raw": result["raw"],
    }


__all__ = [
    "INDIA_SUPPORT_POD",
    "INDIA_SUPPORT_POD_NAME",
    "CLIENT_BILLABLE",
    "INTERNAL_TICKET",
    "DEFAULT_PRIORITY",
    "AUTOMATION_OPENER_ID",
    "create_ticket",
]
