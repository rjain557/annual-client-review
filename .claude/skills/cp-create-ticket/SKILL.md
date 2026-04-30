---
name: cp-create-ticket
description: "Use when the user asks to create, open, or file a ticket in the Technijian Client Portal — manually for one-off issues or programmatically from another pipeline (Sophos alert router, Meraki anomaly, Huntress incident, etc.). Wraps stp_xml_Tkt_API_CreateV3 with required-field defaults and active-contract auto-resolution. Examples: \"open a CP ticket for AAVA\", \"create a client portal ticket from this alert\", \"file a ticket in CP for the firewall outage\", \"wire ticket creation into the sophos router\"."
---

# Client Portal — Create Ticket (`stp_xml_Tkt_API_CreateV3`)

Creates a ticket in the Technijian Client Portal via the
`stp_xml_Tkt_API_CreateV3` stored procedure. Backs every automation that
opens billable tickets on a client's contract — Sophos alert router,
Meraki anomaly tickets, Huntress incident tickets, etc. Also usable
on demand from the command line for one-off support tickets.

## What it does

Builds a `<Root><Ticket>...</Ticket></Root>` XML envelope with the required
+ optional fields and POSTs it to:

```
POST /api/modules/dbo/stored-procedures/client-portal/dbo/stp_xml_Tkt_API_CreateV3/execute
Body: {"Parameters": {"XML_IN": "<Root><Ticket>...</Ticket></Root>"}}
```

Returns the new `TicketID` (best-effort extraction from the SP response —
falls back to the raw response dict if the identity column is exposed
under a different key in this CP build).

## Required SP fields

Every call MUST supply these (per the user-supplied SP contract):

| Field | Source / typical value |
|---|---|
| `Requestor_DirID` | Client contact's DirID, or the client's own DirID for automation-opened tickets |
| `AssignTo_DirID` | Pod/user DirID — default `205` = `CHD : TS1` (India tech support) |
| `ContractID` | Currently-active signed contract — resolve via `cp_api.find_active_signed_contract()` |
| `ClientID` | Client's DirID (same as `Requestor_DirID` for automation tickets) |
| `Title` | Short subject line |
| `Description` | Full body — multi-line OK; XML-escaped automatically |
| `Priority` | Numeric id from `vw_LookupV_Ticket_Priority` (1253-2611) — default `1257` "When Convenient" |
| `Status` | Numeric id from `vw_LookupV_Tkt_Status_NotComplete` (1259+) — default `1259` "New" |
| `RequestType` | String — default `"ClientPortal"` |
| `RoleType` | Numeric id from `vw_LookupV_Cal_RoleType_Get` (1231+) — default `1232` "Tech Support" |
| `WorkType` | Numeric enum — default `14` (lookup view not yet captured) |

## Lookup tables (source: SQL views supplied by Tharunaa Babu, 2026-04-30)

Numeric ids and human-readable names. Both `cp_tickets.create_ticket()` and
the CLI accept either form (case-insensitive on names).

### `vw_LookupV_Cal_RoleType_Get` — RoleType

| ID | Name |
|---:|---|
| 1231 | Development |
| 1232 | **Tech Support** ← default |
| 1233 | CTO |
| 1234 | Audit Manager |
| 1235 | Systems Architect |
| 1236 | Off-Shore Tech Support ← Sophos shim |
| 1237 | Off-Shore Development |
| 2593 | Wiring |
| 2598 | Telco |
| 2603 | Electrical |
| 2745 | Accounting |
| 2752 | Inbound Sales |
| 2753 | Outbound Sales |
| 2754 | Internal |
| 2825 | Onsite-Tech Support |
| 2826 | Onsite-Development |

### `vw_LookupV_Ticket_Priority` — Priority

| ID | Name |
|---:|---|
| 1253 | Critical |
| 1254 | Immediate |
| 1255 | Same Day |
| 1256 | Next Day |
| 1257 | **When Convenient** ← default |
| 1258 | Undetermined |
| 2611 | Watch |

### `vw_LookupV_Tkt_Status_NotComplete` — Status (open tickets)

| ID | Name |
|---:|---|
| 1259 | **New** ← default |
| 1260 | Opportunity Pending |
| 1261 | Dispatched |
| 1262 | In Progress |
| 1263 | Escalated |
| 1264 | Scheduled |
| 1265 | Waiting Materials |
| 1267 | Waiting Customer |
| 1269 | Waiting Vendor |
| 1270 | Follow Up Needed |
| 1275 | Closed |
| 2549 | Check with Client |
| 2550 | Call the Client |
| 2551 | Client Approval |
| 2562 | Notify the Client |
| 2563 | Client Notified |
| 2609 | Client Approved |
| 2610 | Client Rejected |

## Optional SP fields (defaulted)

| Field | Default | When to override |
|---|---|---|
| `AssetID` | `0` | Set when ticket is tied to a specific managed asset |
| `LocationTopFilter` | `""` | Multi-site clients with location filtering |
| `AssetTxt` | `""` | Free-text asset name fallback |
| `StatusTxt` / `PriorityTxt` | `""` | UI display overrides — usually leave blank |
| `ParentID` | `0` | Set for child tickets in a parent/sub-ticket relationship |
| `CreatedBy` | `"clientportal@technijian.com"` | Audit attribution |
| `Category` | `"API"` | Source category — keep as `"API"` for automation |

## Cache-first lookup (no API round-trips per ticket)

Each `clients/<code>/_meta.json` is pre-populated with `DirID`,
`ActiveContract.ContractID`, and `LocationTopFilter` by
`scripts/clientportal/build_client_meta.py`. The `LocationTopFilter` value
comes from `stp_Get_All_Dir` keyed on the client's DirID — it follows the
pattern `Tech.Clients.<CODE>` (e.g. `Tech.Clients.AAVA`). Callers should
read from the cache and only fall through to the API when the cache is stale
(new contract signed, new client onboarded).

`create_ticket_for_code()` automatically passes `LocationTopFilter` to the
SP — no extra kwarg needed. For callers that only have a DirID,
`lookup_location_top_filter_by_dir_id(dir_id)` scans `clients/*/_meta.json`
and returns the matching value.

```python
import sys
sys.path.insert(0, r"c:/vscode/annual-client-review/annual-client-review/scripts/clientportal")
import cp_tickets

# One-liner: looks up DirID + ContractID from clients/aava/_meta.json,
# builds the XML, calls the SP. No live GetAllContracts call.
result = cp_tickets.create_ticket_for_code(
    "AAVA",
    title="Sophos firewall WAN1 down",
    description="Auto-routed from Sophos Central. Severity=high.\n...",
)
# result -> {"ticket_id": 98765, "xml_in": "...", "raw": {...}, "dry_run": False}

# Internal Technijian ticket (DirID=139, ContractID=3977 = "Internal Contract")
internal = cp_tickets.create_ticket_for_code(
    "Technijian",
    title="House infrastructure: backup server reboot",
    description="...",
)
```

Refresh the cache when a new contract is signed:

```bash
python scripts/clientportal/build_client_meta.py            # all clients
python scripts/clientportal/build_client_meta.py --only AAVA   # one client
```

## Programmatic use (manual DirID + ContractID)

For callers that already have the IDs in hand (e.g. a Sophos alert payload),
or for ad-hoc tickets where the cache might be stale:

```python
import sys
sys.path.insert(0, r"c:/vscode/annual-client-review/annual-client-review/scripts/clientportal")
import cp_tickets

result = cp_tickets.create_ticket(
    requestor_dir_id=6989,
    client_id=6989,
    contract_id=5142,
    title="Sophos firewall WAN1 down",
    description="Auto-routed from Sophos Central. Severity=high.\n...",
)
```

Or look up the contract via the cache-aware helper (cache-first, falls
back to the live `GetAllContracts` query):

```python
contract_id = cp_tickets.lookup_active_contract_id(
    client_dir_id=6989, location_code="AAVA")
```

`create_ticket(..., dry_run=True)` and `create_ticket_for_code(..., dry_run=True)`
build the XML and skip the API call — use them to verify the payload locally
before going live with a new caller.

## CLI

```bash
cd c:/vscode/annual-client-review/annual-client-review/scripts/clientportal

# Dry-run: build the XML, print it, no API call. Exit code 2.
python create_ticket.py --client-code AAVA --auto-contract \
    --title "Test ticket" --description "Smoke test" --dry-run

# Live: create against an explicit contract
python create_ticket.py --client-id 12345 --contract 789 \
    --title "Sophos: WAN1 down" --description-file body.txt

# Live: auto-resolve contract from the client's active signed contract
python create_ticket.py --client-code AAVA --auto-contract \
    --title "Recurring printer issue" --description "Tray 2 jams hourly"

# Override the assignee (default 205 = CHD : TS1)
python create_ticket.py --client-code AAVA --auto-contract \
    --title "Dev work" --description "Custom report" --assign-to 206

# Read description from stdin
echo "Long body..." | python create_ticket.py --client-code AAVA \
    --auto-contract --title "Test" --description-file -
```

The CLI writes a JSON receipt to stdout (or `--out PATH`) with
`{ok, ticket_id, client_id, contract_id, requestor_dir_id, assign_to_dir_id,
title, xml_in}`. On failure, `raw` is included for diagnostics.

Exit codes: `0` = ticket created, `1` = error, `2` = dry-run.

## How a ticket is structured

User-supplied example (the SP accepts exactly this XML envelope as `XML_IN`):

```xml
<Root>
  <Ticket>
    <Requestor_DirID>123</Requestor_DirID>
    <AssignTo_DirID>456</AssignTo_DirID>
    <ContractID>789</ContractID>
    <AssetID>0</AssetID>
    <Title>Test ticket title</Title>
    <Priority>1</Priority>
    <Status>1259</Status>
    <Description>Ticket description here</Description>
    <RequestType>ClientPortal</RequestType>
    <LocationTopFilter></LocationTopFilter>
    <RoleType>1</RoleType>
    <WorkType>14</WorkType>
    <ClientID>123</ClientID>
    <AssetTxt></AssetTxt>
    <StatusTxt></StatusTxt>
    <PriorityTxt></PriorityTxt>
    <ParentID>0</ParentID>
    <CreatedBy>clientportal@technijian.com</CreatedBy>
    <Category>API</Category>
  </Ticket>
</Root>
```

`build_ticket_xml()` in `cp_api.py` produces this envelope with all values
XML-escaped (`&`, `<`, `>`, `"`, `'`). Title and Description containing
special characters are safe.

## Tech support pod DirIDs (resolved 2026-04-29)

| DirID | Pod | Use for |
|---|---|---|
| `205` | `CHD : TS1` (Chandigarh Tech Support) | Tech support / break-fix / client alerts (default) |
| `206` | `CHD : PR1` (Chandigarh Programming) | Custom dev work — set `assign_to_dir_id=206` explicitly |

Source: `stp_GetTechnijianUser_PodList`. Confirm before adding a new
default — pod ids change as Technijian's org evolves.

## Auth & credentials

Inherits from `scripts/clientportal/cp_api.py`:

1. `CP_USERNAME` / `CP_PASSWORD` env vars (preferred for headless / scheduled).
2. Fallback: `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\client-portal.md`.

Bearer token cached for ~1h via `cp_api.login()`.

## Files

| Layer | Path |
|---|---|
| Skill | `.claude/skills/cp-create-ticket/SKILL.md` (this file) |
| Low-level helpers | `scripts/clientportal/cp_api.py` — `build_ticket_xml`, `create_ticket_v3`, `extract_ticket_id` |
| High-level wrapper | `scripts/clientportal/cp_tickets.py` — `create_ticket(...)`, `create_ticket_for_code(...)`, `lookup_client_id_and_contract(...)`, `lookup_active_contract_id(...)`, defaults |
| CLI | `scripts/clientportal/create_ticket.py` |
| Per-client cache | `clients/<code>/_meta.json` — `DirID`, `ActiveContract.ContractID`, recipients, signals |
| Cache builder | `scripts/clientportal/build_client_meta.py` — refreshes all `_meta.json` from `/api/clients/active` + `GetAllContracts` |
| Technijian internal cache | `clients/technijian/_meta.json` — `DirID=139`, `ContractID=3977` ("Internal Contract"). Use for HOUSE-INTERNAL tickets only. |

## Callers

- **Sophos alert router** (`technijian/sophos-pull/scripts/route_alerts.py`)
  re-exports `create_ticket` from this canonical module — runs in REPORT
  mode by default and only writes tickets when invoked with `--apply`.
- **Future:** Meraki anomaly tickets (per-org IDS spike, WAN dropouts),
  Huntress P1 incident handoff, CrowdStrike critical detection escalation.
  Each caller imports `cp_tickets.create_ticket` rather than re-implementing
  the XML envelope.

## Gotchas

- **The SP returns the new TicketID via either `outputParameters` or the
  first row of `resultSets[0]`** depending on the CP build. `extract_ticket_id`
  tries both. If a future call returns `ticket_id=None` but `raw` shows the
  insert succeeded, add the new key name to `extract_ticket_id` rather
  than working around it in the caller.
- **`Priority` and `Status` are numeric ids, not strings.** The user-supplied
  example uses `Priority=1` and `Status=1259`. To populate the `*_Txt`
  fields, look up the matching strings via
  `stp_xml_Lookup_Priority_DSB_Ticket_Filter` /
  `stp_xml_Lookup_Status_DSB_Ticket_Filter`. Usually safe to leave blank —
  the portal renders the text from the id at display time.
- **`Requestor_DirID` for automation tickets:** when the alert source is a
  system (Sophos, Meraki, Huntress) rather than a person, set
  `requestor_dir_id = client_dir_id`. The portal will display the client
  org as the requestor, which is the correct billing entity.
- **`ContractID` is required and must reference an Active contract.** A
  ticket without a contract cannot be billed. `lookup_active_contract_id()`
  returns `None` for clients with no Active signed contract — the caller
  must skip ticket creation and surface the gap (e.g. add to a
  `needs_contract_set.csv` follow-up file).
- **The harness blocks unrelated write SP probes.** This skill is wired
  for `stp_xml_Tkt_API_CreateV3` specifically. Adding a new write SP
  (e.g. ticket update) requires a fresh capture of the front-end network
  call to confirm the parameter contract.

## Related

- `client-portal-pull` — read side (active clients, contracts, time entries, invoices)
- `sophos-pull` — primary caller for client-billable alert tickets
- `monthly-client-pull` — adjacent skill, snapshot only (does not create tickets)
