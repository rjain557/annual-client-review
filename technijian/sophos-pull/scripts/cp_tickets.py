"""Client Portal ticket creation — STUB awaiting SP signature.

Discovered via the public OpenAPI spec (https://api-clientportal.technijian.com/swagger/v1/swagger.json):

  POST /api/modules/dbo/stored-procedures/client-portal/dbo/stp_xml_Tkt_API_Create/execute
  POST /api/modules/dbo/stored-procedures/client-portal/dbo/stp_xml_Tkt_API_CreateV2/execute
  POST /api/modules/dbo/stored-procedures/client-portal/dbo/stp_xml_Tkt_API_CreateV3/execute  <- presumed latest

  Assignment:
  POST /api/modules/dbo/stored-procedures/client-portal/dbo/stp_Tkt_Assigned_Save/execute

  Lookups (read-only, safe to probe):
  POST /api/modules/lookups/stored-procedures/client-portal/dbo/stp_xml_Lookup_Priority_DSB_Ticket_Filter/execute
  POST /api/modules/lookups/stored-procedures/client-portal/dbo/stp_xml_Lookup_Status_DSB_Ticket_Filter/execute
  POST /api/modules/pod/stored-procedures/client-portal/dbo/stp_xml_TechTktShift_List_Get/execute

The OpenAPI spec models every SP body as a generic
`{"Parameters": <object>}` — the actual required parameters for the
ticket-create SPs are NOT in the spec. Live probing of the write SPs is
explicitly NOT done from this code without prior user approval.

To wire this up, the user needs to provide one of:
    (a) The exact `Parameters` object the front-end sends when creating a
        ticket via the Client Portal UI (a network capture of one ticket
        create from the portal will give us this in 30 seconds).
    (b) A direct read-out of the SP signature from CP source: the parameter
        names + types for stp_xml_Tkt_API_CreateV3 and stp_Tkt_Assigned_Save.
    (c) Explicit approval to probe stp_xml_Tkt_API_CreateV3 with empty
        Parameters (SQL Server typically returns "Procedure expects parameter
        @X" which reveals the required signature one parameter at a time).

Until the SP is wired, `create_ticket()` raises NotImplementedError so the
router can never silently no-op while pretending to have created a ticket.

Companion items still to be supplied once the SP is known:
    - INDIA_SUPPORT_POD value (group/user/queue id; from
      stp_xml_TechTktShift_List_Get or directly from the CP admin).
    - AUTOMATION_OPENER_ID for audit attribution.
"""
from __future__ import annotations

# Resolved 2026-04-29 via stp_GetTechnijianUser_PodList:
#   DirID=205  CHD : TS1  (Chandigarh Tech Support) — India tech support pod
#   DirID=206  CHD : PR1  (Chandigarh Programming) — dev work, NOT this pipeline
# Sophos firewall alerts are tech-support work (break-fix / connectivity),
# so they go to CHD : TS1, not the programming pod.
INDIA_SUPPORT_POD = 205
INDIA_SUPPORT_POD_NAME = "CHD : TS1"

# Default ticket priority for Sophos firewall alerts. Adjust as needed.
DEFAULT_PRIORITY = "Normal"

# Tickets opened on behalf of automation should record a known operator id
# (so the audit log shows the source). Replace once the CP SP is wired.
AUTOMATION_OPENER_ID = "TODO_AUTOMATION_USER_ID"

# Client-alert tickets are CLIENT BILLABLE (against the managed-IT contract
# or T&M), NOT Technijian-internal. The SP parameter name for this flag is
# yet to be confirmed — likely `IsBillable`, `Billable`, `TicketType`, or
# `IsInternal=False` (presence of stp_xml_InternalTicket_Setting_List_Get
# in the OpenAPI strongly implies internal-vs-billable is a distinct flag).
# When wiring the SP, ensure this maps to the BILLABLE branch so the work
# is on the client's contract / hits their invoice, not Technijian's
# internal cost center.
CLIENT_BILLABLE = True
INTERNAL_TICKET = False


def create_ticket(*,
                  client_dir_id: int,
                  subject: str,
                  description: str,
                  assigned_to: str = INDIA_SUPPORT_POD,
                  priority: str = DEFAULT_PRIORITY,
                  source: str = "Sophos Central (auto)",
                  opener_id: str = AUTOMATION_OPENER_ID,
                  billable: bool = CLIENT_BILLABLE) -> dict:
    """Create a CP ticket. Currently UNWIRED — raises NotImplementedError.

    Args:
        client_dir_id: CP DirID of the client this ticket is FOR (their
            contract is what gets billed, NOT Technijian's house tenant).
        subject / description: human-readable text.
        assigned_to: target queue/pod/user (default INDIA_SUPPORT_POD).
        priority: CP priority enum value.
        source: free-form attribution string for the audit log.
        opener_id: CP user id under whom the ticket is opened (audit).
        billable: True = client-billable (default for client alerts);
            False = Technijian internal. For Sophos client alerts ALWAYS
            pass billable=True. Internal infrastructure issues (e.g. the
            Technijian house tenant firewall) would pass False.

    Returns: {"ticket_id": <id>, "ticket_url": <url>, "raw": <SP response>}
    Raises:  NotImplementedError until the SP signature is supplied.
    """
    raise NotImplementedError(
        "CP ticket-create SP not yet wired. See module docstring for the "
        "checklist of what to fill in. Until then, route_alerts.py runs in "
        "REPORT mode (no --apply) and logs what would be created. The "
        "wired implementation MUST honour the `billable` flag so client "
        "alerts hit the client contract, not Technijian internal."
    )
