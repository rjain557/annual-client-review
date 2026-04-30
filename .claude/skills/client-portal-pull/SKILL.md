---
name: client-portal-pull
description: "Use when the user asks to pull tickets, time entries, invoices, contracts, or active client data from the Technijian Client Portal API (api-clientportal.technijian.com). Handles auth, SP discovery, and per-client folder output. Examples: \"pull tickets/time entries/invoices for all active clients\", \"refresh client data from client portal\", \"fetch <CODE> data since contract signed date\"."
---

# Technijian Client Portal API Pull

The Client Portal API exposes a stored-procedure catalog at
`https://api-clientportal.technijian.com`. Auth is Microsoft Entra-backed;
credentials live in the key vault at:

```
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\client-portal.md
```

Reusable Python module: `scripts/clientportal/cp_api.py`
(repo: `c:/VSCode/annual-client-review/annual-client-review-1`).

The bulk-pull script is `scripts/clientportal/pull_all_active.py`.

## Auth flow

```
POST /api/auth/token
body: {"userName": "<email>", "password": "<pw>"}
-> {"tokenType":"Bearer","expiresIn":<seconds>,"accessToken":"<jwt>"}
```

Tokens last ~1–2 hours. Reuse; only re-auth when expired. All SP calls need
`Authorization: Bearer <accessToken>`. `cp_api.login()` caches the session.

## Endpoint map (the ones that actually work)

| Purpose | Route | Params | Response shape |
|---|---|---|---|
| Active clients | `GET /api/clients/active` | — | `ResultSets[0].Rows`: `{DirID, LocationCode, Location_Name, CreateDateTime, Net_Terms}` |
| All contracts | `POST /api/modules/contract/stored-procedures/client-portal/dbo/GetAllContracts/execute` | — | `resultSets[0].rows` — match `Client_LocationsID` to `DirID`; filter `ContractStatusTxt` in {`Active`,`ACTIVE`}; prefer most recent `DateSigned` |
| Time entries (per client, date range) | `POST /api/modules/timeentry/stored-procedures/client-portal/Reporting/stp_xml_TktEntry_List_Get/execute` | `ClientID` (=DirID), `UserID`=0, `StartDate`, `EndDate` (YYYY-MM-DD) | `outputParameters.XML_OUT` = `<Root><TimeEntry>…</TimeEntry>…</Root>` |
| Invoices (all history per client) | `POST /api/modules/invoices/stored-procedures/client-portal/dbo/stp_xml_Inv_Org_Loc_Inv_List_Get/execute` | `DirID` | `outputParameters.XML_OUT` = `<Root><Invoice>…</Invoice>…</Root>` |
| Ticket history (per ticket) | `POST /api/modules/tickets/stored-procedures/client-portal/dbo/stp_xml_Tkt_Cal_Tkt_CltHistory_List_Get/execute` | `TicketID` | `outputParameters.XML_OUT` |
| Invoice time-entry detail (per invoice) | `POST /api/modules/invoices/stored-procedures/client-portal/dbo/stp_Invoice_TimeEntryList/execute` | `InvoiceID` | `resultSets[0].rows` |
| SP metadata / param discovery | `GET /api/catalog/guide/client-portal/{schema}/{spName}` | — | `requestTemplate`, `requiredParameterNames`, `optionalParameterNames` — use this before calling any unfamiliar SP |

**Field keys are camelCase in SP execute responses (`resultSets`, `outputParameters`) but PascalCase on some direct endpoints (`ResultSets`).** `cp_api.sp_rows()` / `sp_xml_out()` handle both.

**TimeEntry XML fields:** `ConName, TimeEntryDate, Title, TimeDiff, Notes, Resource, Requestor, HourType, BillRate, PODDet, InvDescription, InvDetID, StartDateTime, EndDateTime, Office-POD, RoleType, WorkType, AssignedName, AH_Rate, NH_Rate, AH_HoursWorked, NH_HoursWorked, Qty, Category`

**Invoice XML fields:** `InvoiceID, InvoiceNo, DueDate, InvoiceDate, Paid, Total, InvoiceType, Status, Title`

**Ticket-level data is NOT a separate SP** (the obvious `stp_Get_POD_Tickets_V2`, `stp_xml_Ticket_Get_Ticket_Filter` etc. return empty unless a saved `FilterID` is supplied). Instead, `derive_tickets()` in `pull_all_active.py` groups time entries by `(Title, Requestor)` to produce a unique-ticket summary per client.

## One-shot command: pull everything for all active clients

```bash
cd c:/VSCode/annual-client-review/annual-client-review-1/scripts/clientportal
python pull_all_active.py                    # everyone
python pull_all_active.py --skip BWH         # skip one or more codes
python pull_all_active.py --only AAVA,VAF    # restrict
python pull_all_active.py --dry-run          # plan only, no writes
```

Output per client: `clients/<lowercase-code>/data/` containing
`contract_summary.json`, `time_entries.{xml,json,csv}`,
`tickets.json` (derived), `invoices.{xml,json,csv}`. A run-wide summary is
written to `clients/pull_log.json`.

Start date defaults to the active contract's `DateSigned`, falling back to
`StartDate`, then `2020-01-01`. End date is today.

## Programmatic use from another script

```python
import sys
sys.path.insert(0, r"c:/VSCode/annual-client-review/annual-client-review-1/scripts/clientportal")
import cp_api

clients   = cp_api.get_active_clients()
contracts = cp_api.get_all_contracts()
aava      = next(c for c in clients if c["LocationCode"] == "AAVA")
active    = cp_api.find_active_signed_contract(contracts, aava["DirID"])
xml       = cp_api.get_time_entries_xml(aava["DirID"], "2024-05-30", "2026-04-24")
entries   = cp_api.parse_flat_xml(xml, "TimeEntry")
invoices  = cp_api.parse_flat_xml(cp_api.get_invoices_xml(aava["DirID"]), "Invoice")
```

## Calling an unfamiliar SP

The catalog guide endpoint describes every SP's parameters:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "https://api-clientportal.technijian.com/api/catalog/guide/client-portal/dbo/<SPNAME>"
```

Response fields of note: `route`, `requiredParameterNames`,
`optionalParameterNames`, `requestTemplate`, `whenToUse`. Use
`cp_api.execute_sp(module, schema, name, parameters)` once you know the route.

## Gotchas

- `stp_Active_Clients` is NOT in the catalog under its own name — use the convenience route `GET /api/clients/active`.
- Many contracts have no `DateSigned` (older ones); fall back to `StartDate`.
- Clients appear multiple times across the contracts list; always filter by `Client_LocationsID == DirID` and `ContractStatusTxt` (not `Client_ID`, which is often `None`).
- Time-entry SP caps at whatever the date range covers; for very active clients (KSS, VAF, ORX, BST, ISI, B2I) the XML output exceeds 1 MB — keep date ranges bounded.
- `outputParameters` key casing drifts (`XML_OUT` vs `xml_out`); the parser in `cp_api.sp_xml_out()` is case-insensitive.
- POST SPs expect body `{"Parameters": {…}}` even when empty.
- There is a public Swagger JSON at `/swagger/v1/swagger.json` (~1.3 MB, 1002 paths). Do NOT re-download it every run — cache locally.

## Related: key vault

Credentials (and other Technijian service creds) live at
`%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\`. The
`client-portal.md` file there contains the username/password used by
`cp_api.get_credentials()`.
