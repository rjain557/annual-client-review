---
name: me-ec-pull
description: "Use when the user asks to pull data from ManageEngine Endpoint Central MSP 11 — applicable patches, missing/installed patches, per-system patch matrix, hardware/OS inventory, installed software per machine, EC server event log, hardware/software audit history, or per-customer patch posture. Two pull paths: REST API at https://myrmm.technijian.com:8041 (catalog + system report) and SQL backend at TE-DC-MYRMM-SQL/10.100.13.11 (everything else, including per-machine inventory + installed software + events + comprehensive patch tables). Handles bare-token REST auth from keys vault, NTLM SQL auth via pymssql for non-domain workstations, customer-name vs customer-id scoping, and pagination. Examples: \"pull patch status for all clients\", \"how many missing patches per customer\", \"refresh ME EC inventory + installed software\", \"per-machine patch summary\", \"customer event log from endpoint central\", \"is endpoint insight collecting performance data\"."
---

# ManageEngine Endpoint Central MSP 11 — Pull Pipeline

Pulls patch posture data from the on-prem EC MSP server.

- **Web UI:** https://myrmm.technijian.com:8041 (login: admin)
- **API root:** https://myrmm.technijian.com:8041
- **Host:** TE-DC-MYRMM (paired with TE-DC-MYRMM-SQL backend)

## Quick reference

```bash
cd c:/VSCode/annual-client-review/annual-client-review-1/scripts/me_ec

python me_ec_api.py whoami                       # auth probe
python me_ec_api.py customers                    # 32 MSP customers
python me_ec_api.py patches          --customer AAVA
python me_ec_api.py patches-missing  --customer AAVA
python me_ec_api.py systems-report   --customer AAVA

python pull_all.py                               # all customers
python pull_all.py --only AAVA,BWH               # restrict
python pull_all.py --include-installed           # also pull installed patches (large)
```

Output: `clients/_me_ec/<YYYY-MM-DD>/<CUSTOMER_SLUG>/`:

| File                        | Source                                                |
|-----------------------------|-------------------------------------------------------|
| `_customer.json`            | one row from `/api/1.4/desktop/customers`             |
| `patches.json`              | `/dcapi/threats/patches?customername=<NAME>` (catalog)|
| `patches_missing.json`      | same + `patch_status=Missing`                         |
| `patches_installed.json`    | same + `patch_status=Installed` (only if `--include-installed`) |
| `systems_report.json`       | `/dcapi/threats/systemreport/patches?customername=<NAME>` |

Plus `_customers.json` at the day root with the full 32-row customer list.

## Auth — important quirks

The API key (UUID) is generated at **Admin → API Settings → API Key Management → Generate Key**. The current key is stored at:

```
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\manageengine-ec.md
```

The key must be sent as a **bare** ``Authorization`` header — **NO scheme prefix**. EC IAM rejects every prefix (Bearer / Zoho-authtoken / Zoho-oauthtoken / X-AUTHTOKEN / etc.) with ``error_code 10002 "Invalid or expired token"`` even when the token is valid. The right form is:

```http
Authorization: 683C7C42-AA62-495A-8D3B-4AEED016BBCA
```

When generating a new key in the UI, the **(1) Permissions** tab must have at least *Customer*, *PatchMgmt*, *Inventory*, *Common*, *Report* with R rights granted. A key with empty permissions still shows ``Active`` but every endpoint returns 10002.

`MEECClient` reads the key from ``ME_EC_API_KEY`` if set, otherwise from the keys vault file (regex grabs the first hex/UUID under ``**API Key:**``). The key is added to the ``Authorization`` header automatically.

**TLS:** the cert is self-signed; ``verify=False`` is the default.

## Two API namespaces — don't mix them

EC MSP 11 exposes two different namespaces with different conventions:

| Namespace      | Auth         | Pagination param  | Customer scope            | Envelope                          |
|----------------|--------------|-------------------|---------------------------|-----------------------------------|
| `/api/1.4/...` | bare token   | `page` + `pagelimit`  | `customerId` (rejects most paths) | `{message_response: {...}}`       |
| `/dcapi/...`   | bare token   | `page` + `pageLimit`  | `customername=<string>`   | `{metadata: {totalPages,...}, message_response: {...}}` |

The MSP's actual API surface as documented in the on-prem **API Explorer** (``/APIExplorerServlet?action=showAPIExplorerPage``) is:

- ``POST /api/1.4/desktop/authentication`` (login — only needed for username/password→token, not when using a UI-issued API key)
- ``GET  /api/1.4/desktop/customers`` (server-wide customer enumeration)
- ``GET  /dcapi/threats/patches`` (all applicable patches)
- ``GET  /dcapi/threats/systemreport/patches`` (per-system patch matrix)

Other paths (``inventory/computers``, ``som/summary``, ``patch/missingpatches``, etc.) appear in ME's general docs but **return ``error_code 10022 "API Endpoint is not supported by current server"``** on the MSP build. Don't bother probing them — the surface is genuinely small.

## Customer scope

`/dcapi` endpoints take **`customername=<MSP customer name>`** (string, case-sensitive — exactly as it appears in `/api/1.4/desktop/customers` ``customer_name``). Numeric ``customer_id`` is **not** accepted and returns ``IAM0028 Unsupported parameter customerId``.

`/api/1.4/desktop/customers` is server-wide — no scope param needed.

## Pagination

`/dcapi` envelope::

```json
{
  "metadata": {
    "page": 1,
    "totalPages": 44,
    "totalRecords": "88",
    "links": {"next": "...", "prev": null},
    "pageLimit": 2
  },
  "message_response": {"patches": [...]},
  "message_type": "patches",
  "response_code": 200
}
```

Param names are ``page`` and ``pageLimit`` (camelCase L). ``MEECClient.paginated_dcapi()`` walks all pages automatically using ``totalPages``.

`/api/1.4/...` uses lowercase ``page`` + ``pagelimit`` and ``meta_data.total`` — different convention. The client handles both, but use the right helper for the right namespace.

## Per-customer patch report — what to expect

Each customer-name request returns:

- **`/dcapi/threats/patches`** — an applicable-patch catalog. One row per patch, with `severity`, `patchname`, `update_type`, `vendor_name`, `installed_system_count`, `missing_system_count`, `kb_number`, `cveids`, `patch_status` (Missing/Installed/Mixed), `patch_released_time` (ms), etc.
- **`/dcapi/threats/systemreport/patches`** — one row per system, each with a nested ``patches[]`` array. Use this for endpoint-by-endpoint patch posture (Missing vs Installed per host).

For aggregate counts (e.g. "missing-critical-patches per client"), the catalog view is faster. For per-host drilldown, use the system report.

## "Performance" data — Endpoint Insight is installed but not collecting

EC MSP 11 has an "Endpoint Insight" (EI) component that would collect CPU/RAM/disk/battery telemetry into ``EICpuUsage`` / ``EIMemoryUsage`` / ``EIDiskSpace`` / ``EIBatteryHealth``. **On this server those tables are all 0 rows** — verified via `me_ec_sql.performance_status()`. ``EIManagedResource`` shows 336 endpoints with ``STATUS=0, COMPONENT_STATUS=0, REMARKS='ei.agent.component_status.yet_to_enable'`` — EI is installed but never turned on.

Until someone enables it in **EC console → Endpoint Insight → Settings**, perf data stays empty. Alternatives:

- **OpManager / Applications Manager** — separate ME products with their own REST APIs
- The **patch posture** view (`per_machine_patch_summary` in `me_ec_sql`) is the closest thing to a fleet-health metric available today

## SQL backend (TE-DC-MYRMM-SQL) — companion path

For data the REST API doesn't expose, use the SQL backend directly. Module: `scripts/me_ec/me_ec_sql.py`. Orchestrator: `scripts/me_ec/pull_all_sql.py`. Credentials: `keys/myrmm-sql.md`.

```bash
python pull_all_sql.py                       # all 32 customers, all categories
python pull_all_sql.py --only AAVA,BWH       # restrict
python pull_all_sql.py --skip-software       # skip installed-software (largest)
python pull_all_sql.py --skip-events         # skip event log
python pull_all_sql.py --event-window-days 30
```

Per-customer SQL output (alongside REST output, same `clients/_me_ec/<DATE>/<SLUG>/` folder):

| File                              | Source tables                                                |
|-----------------------------------|--------------------------------------------------------------|
| `inventory_computers.json`        | `Resource + InvComputer + InvComputerOSRel + InvComputerExtn` (hw, os, warranty) |
| `installed_software.json`         | `InvComputerToManagedSWRel + InvSW`                          |
| `per_machine_patch_summary.json`  | counts joined per machine                                    |
| `patches_missing_sql.json`        | `AffectedPatchStatus + Patch + PatchDetails`                 |
| `patches_installed_sql.json`      | `InstallPatchStatus + Patch` (with deploy time + error code) |
| `patches_superceded.json`         | `SupercededInstallPatchStatus`                               |
| `patch_scan_status.json`          | `PatchClientScanStatus`                                      |
| `customer_event_log.json`         | `CustomerEventLog + EventLog + EventCode` (server events, last 90d) |
| `hardware_audit.json`             | `InvAuditToComputerRel + InvHWAuditHistory`                  |
| `software_audit.json`             | `InvAuditToComputerRel + InvSWAuditHistory`                  |

Plus at the day root:
- `_customers_sql.json` — `CustomerInfo` (32 customers, with email + timezone + account head)
- `_performance_status.json` — diagnostic showing whether EI is enabled

### SQL auth quirks (Windows 11 Home workstation)

This workstation isn't domain-joined, so `sqlcmd -E` (integrated auth) fails with `Cannot generate SSPI context`. The Windows `Administrator` account isn't a SQL-native login, so `sqlcmd -U Administrator -P ...` also fails (`Login failed`). The working path is **pymssql (FreeTDS) with NTLM via `host\user`**:

```python
pymssql.connect(server='10.100.13.11',
                user='TE-DC-MYRMM-SQL\\Administrator',
                password='...',
                database='desktopcentral')
```

`me_ec_sql.connect()` does this automatically.

### Customer scoping in SQL

`Resource.CUSTOMER_ID` is the join axis. `CustomerInfo.CUSTOMER_ID` matches the REST API's `customer_id` field exactly. So slugs derived from `CustomerInfo.CUSTOMER_NAME` line up with the slugs used by the REST orchestrator — REST and SQL writes go into the **same** per-customer folder.

### Schema gotchas

- `InvComputer.COMPUTER_ID == Resource.RESOURCE_ID` (no separate ID).
- `InvComputerToManagedSWRel.MANAGED_SW_ID` joins to **`InvSW.SOFTWARE_ID`** (NOT `SoftwareDetails.SOFTWARE_ID` — those are different namespaces. `SoftwareDetails` only has 38K rows; `InvSW` has 174K and is the actual per-customer detected software catalog).
- `Resource.RESOURCE_TYPE = 1` is the only type that represents a managed endpoint. Type 2 is a mixed bucket; types 5/101/121/150 are mobile/groups/probes.
- `Customer` table doesn't exist — use `CustomerInfo`.
- Events are server-side EC events (patch scan completed, config deployed, audit ran), not Windows event-log shipping. Per-machine Windows event log isn't being collected.

## Discovering more endpoints

The on-prem **API Explorer** at ``/APIExplorerServlet?action=showAPIExplorerPage`` documents only what this server actually serves. Use it (after admin login) to view the full filter/parameter surface for the two ``/dcapi`` endpoints. The "Execute" form there is the authoritative source for query-param names and customer-scope conventions.

`probe_endpoints.py` runs a curated list against the live server and prints ``OK / -- / XX`` per path — useful after EC upgrades or when ME ships new modules.

## Verification

```bash
python me_ec_api.py whoami
python me_ec_api.py customers          # expect 32 rows today
python pull_all.py --only AAVA         # one customer end-to-end (~5s)
```

If `whoami` returns ``error_code 10002``, the key is rejected — regenerate it in the EC admin UI (**Admin → API Settings → API Key Management → Generate Key**) and replace the value under ``**API Key:**`` in ``keys/manageengine-ec.md``. Make sure the **(1) Permissions** tab grants Customer / PatchMgmt / Inventory / Common / Report at minimum.

<!-- ticket-management-note: cp-ticket-management -->

## Ticket management

If this skill ever needs to open a CP ticket for an issue it detects
(capacity warning, threshold breach, persistent failure), use the
tracked wrapper from the **cp-ticket-management** skill —
`cp_tickets.create_ticket_for_code_tracked(...)` in
`scripts/clientportal/cp_tickets.py`. The central state file at
`state/cp_tickets.json` deduplicates on `issue_key`
(convention: `<source-skill>:<issue-type>:<resource-id>`) and
`scripts/clientportal/ticket_monitor.py check` (daily 06:00 PT on the
production workstation) sends 24h reminder emails to
support@technijian.com for any open ticket. **Don't call
`cp_tickets.create_ticket(...)` directly** — the raw call bypasses
state and reminders.
