---
name: sophos-pull
description: "Use when the user asks about Sophos Central Partner data — pulling firewall inventory, connectivity events, or open alerts across Technijian MSP tenants; routing alerts to client-billable Client Portal tickets assigned to the India support pod; sending reminder emails to support@technijian.com; or seeding the rsyslog allowlist for the DC syslog receiver. Examples: \"pull sophos for all clients\", \"refresh sophos firewall inventory\", \"create CP tickets for open Sophos alerts\", \"set up the hourly sophos pipeline\", \"regenerate the rsyslog tenant map\"."
---

# Sophos Central Partner — Hourly Pull + Alert Router

The Sophos Central Partner API is at `https://api.central.sophos.com` with
per-tenant data hosts (e.g. `https://api-us01.central.sophos.com`). Auth is
OAuth2 client_credentials against `https://id.sophos.com/api/v2/oauth2/token`,
followed by `/whoami/v1` and `/partner/v1/tenants` to enumerate tenants.

Credentials live in the key vault at:

```
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\sophos.md
```

Reusable Python module: `technijian/sophos-pull/scripts/sophos_api.py`
Pipeline scripts: `technijian/sophos-pull/scripts/`
(repo root: `c:/VSCode/annual-client-review/annual-client-review`)

## Two-layer architecture

**Layer 1 — Partner API (this skill):** firewall inventory, connectivity
events (24h max lookback), open alerts, admin/role audit. Hourly cadence.
Read-only against Sophos; writes Client Portal tickets and sends reminder
emails.

**Layer 2 — syslog receiver (separate):** the Partner API does NOT expose
per-signature firewall IPS/IDS events. For real IPS/IDS detail, route
syslog from each XGS to the Technijian DC receiver. This skill auto-seeds
the receiver's tenant-map allowlist from the Partner API firewall WAN IPs.

## Auth flow

```python
import sys
sys.path.insert(0, r'technijian\sophos-pull\scripts')
import sophos_api as s
me = s.whoami()                  # → {idType: 'partner', id: '<partner-id>'}
tenants = s.list_tenants()       # → 11 tenants, each with apiHost + dataRegion
fws = s.list_firewalls(tenants[0])  # tenant-scoped firewall inventory
```

## Hourly one-shot

The wrapper runs three steps in sequence:

```cmd
technijian\sophos-pull\run-hourly-sophos.cmd
```

1. `pull_sophos_daily.py` — per-tenant snapshot to `clients/<code>/sophos/<date>/`
2. `seed_tenant_map.py` — regenerate `state/sophos-tenant-ipmap.{txt,json}`
3. `route_alerts.py` — REPORT mode by default; `set ROUTER_MODE=apply` to
   create CP tickets and send reminder emails.

Per-component scripts can be run on their own:

```bash
python pull_sophos_daily.py --map-only            # mapping resolution only
python pull_sophos_daily.py --only AAVA,BWH       # restrict
python pull_sophos_daily.py --hours 48            # widen window
python pull_sophos_daily.py --date 2026-04-29     # backfill anchor

python backfill_sophos.py                          # 2026 open-alert backlog by month
python backfill_sophos.py --only KSS              # one tenant

python seed_tenant_map.py                          # generate rsyslog allowlist
python seed_tenant_map.py --print                  # stdout only

python route_alerts.py                             # REPORT mode (no writes)
python route_alerts.py --apply                     # create tickets + send emails
python route_alerts.py --apply --no-tickets        # only emails
python route_alerts.py --reminder-hours 12         # tighter cadence
```

## Output structure

```
clients/<code>/sophos/
  <YYYY-MM-DD>/
    firewalls.json + firewalls.csv     per-tenant firewall inventory
    events.json                         24h SIEM events (CONNECTIVITY group)
    alerts.json                         /common/v1/alerts open alerts
    pull_summary.json                   counts, errors, mapping_source
  monthly/<YYYY-MM>/
    alerts.json + pull_summary.json    open-alert backlog bucketed by raisedAt
    firewalls.json + firewalls.csv     latest-snapshot copy

technijian/sophos-pull/<YYYY-MM-DD>/
  whoami.json + tenants.json + mapping.json + unmapped.json
  firewalls_all.json                   cross-tenant inventory (seeder reads this)
  routing-plan.json                    per-run NEW/AGING/QUIET/RESOLVED breakdown
  run_log.json                         run summary

technijian/sophos-pull/state/
  sophos-tenant-mapping.json           manual sophos_tenant_id -> LocationCode + ignore list
  sophos-tenant-ipmap.txt              human-readable rsyslog allowlist
  sophos-tenant-ipmap.json             rsyslog lookup_table format (drop on receiver)
  alert-tickets.json                   persistent state — sophos alert.id -> CP ticket
  <YYYY-MM-DD>.json                    per-day run log (mirrors run_log.json)
```

## Tenant -> LocationCode mapping

Resolution order: (1) manual override in `state/sophos-tenant-mapping.json`;
(2) exact normalized-name match against active CP clients; (3) bare-code
match (tenant name == LocationCode like "B2I"). Anything still unmatched
lands in `unmapped.json`. Internal Technijian tenant goes in `ignore`.

Current state (2026-04-29): 9 of 11 tenants mapped (JDH, BWH, TALY, AFFG,
KSS, ANI, VAF, ORX, B2I); 1 unmapped (Yebo Group — not in active CP list);
1 ignored (Technijian house tenant). 14 firewalls across the mapped tenants.

## Alert routing

Each open alert in `clients/<code>/sophos/<latest>/alerts.json` is classified:

- **NEW** — alert.id not yet in `state/alert-tickets.json` OR ticket creation
  previously failed (`ticket_id == null`). Action: call
  `cp_tickets.create_ticket(client_dir_id, subject, description, billable=True)`.
- **AGING** — alert still open, ticket exists, `last_email_sent_at` older
  than `--reminder-hours` (default 24). Action: send reminder email to
  support@technijian.com via M365 Graph (RJain@technijian.com sender).
- **QUIET** — alert still open, ticket exists, recent reminder. No action.
- **RESOLVED** — alert.id in state but absent from this run's data. Action:
  set `resolved_at` timestamp; reminders stop.

**Client alerts always create CLIENT-BILLABLE tickets** (against the client
contract, not Technijian internal). Internal Technijian-tenant alerts would
use `billable=False`, but the Technijian tenant is in the ignore list anyway.

## Blockers (must be resolved before APPLY mode is meaningful)

1. **CP ticket-create SP signature.** `cp_tickets.create_ticket()` raises
   NotImplementedError. The OpenAPI spec at
   `https://api-clientportal.technijian.com/swagger/v1/swagger.json`
   identifies three candidates:
   `stp_xml_Tkt_API_Create`, `stp_xml_Tkt_API_CreateV2`,
   `stp_xml_Tkt_API_CreateV3` (presumed latest). The OpenAPI spec wraps
   them all as `{"Parameters": {<opaque>}}`. Required to wire:
   exact parameter names + types, the assignment value for the India
   support pod, the billable flag's parameter name. See module docstring
   in `cp_tickets.py` for the checklist.

2. **Live CP write probe is permission-gated.** The harness blocks calls
   to write SPs without explicit user approval — that's correct. The
   user needs to either (a) capture the ticket-create network call from
   the CP front-end and share the JSON body, (b) read out the SP signature
   from the CP source, or (c) explicitly approve a probe with empty
   parameters to learn the signature one error at a time.

## Brand colors (for any branded reports later)

| Color | Hex | Usage |
|---|---|---|
| Technijian Blue | `#006DB6` | primary brand, headings |
| Orange | `#F67D4B` | high-severity callouts |
| Teal | `#1EAAC8` | accent |
| Dark Charcoal | `#1A1A2E` | body text |
| Brand Grey | `#59595B` | muted body text |

## Shared infra reused

- `scripts/clientportal/cp_api.py` — CP auth + active-clients lookup (DirIDs)
- `technijian/tech-training/scripts/_secrets.py` — M365 Graph credentials
- `technijian/huntress-pull/scripts/_brand.py` — DOCX brand helpers (when
  monthly branded reports are added later)

## Cadence

| Action | Cadence | Reason |
|---|---|---|
| Pull + seed + route | hourly :15 | 24h SIEM ceiling; hourly catches alerts within the hour |
| Backfill open-alert backlog | on demand | run once after ticket SP wires up; idempotent |
| rsyslog tenant-map deploy | hourly (auto) + manual scp to receiver | follow firewall WAN-IP changes |

## Troubleshooting

- `RuntimeError: Sophos keyfile not found` → OneDrive isn't synced yet
- `HTTP 401` from Sophos → keyfile credentials stale; regenerate in Central Partner
- `NotImplementedError` from cp_tickets → expected until SP is wired (see Blockers)
- Alerts piling up in `routing-plan.json` NEW bucket → ticket creation failing
  silently. Check `state/alert-tickets.json` entries for `_creation_error`.
- Reminder emails not arriving → check `_secrets.py` resolves M365 creds and
  the app registration still has `Mail.Send` application permission.

<!-- ticket-management-note: cp-ticket-management -->

## Ticket management — migration to cp-ticket-management

This skill currently opens CP tickets directly. State today:
`technijian/sophos-pull/state/alert-tickets.json`.

`route_alerts.py` runs hourly and opens client-billable tickets to CHD : TS1. **Pending migration** to the central tracked wrapper. After migration its existing 24h reminder loop in `email_support.py` can retire (the central monitor covers reminders).

**Migration steps** (see ../cp-ticket-management/SKILL.md):

1. Replace `cp_tickets.create_ticket(...)` /
   `cp_tickets.create_ticket_for_code(...)` with
   `cp_tickets.create_ticket_for_code_tracked(...)`.
2. Pick a stable `issue_key` per unique issue
   (convention: `sophos-pull:<issue-type>:<resource-id>`).
3. Pass `source_skill="sophos-pull"`.
4. Pass `metadata={...}` with the data points that justified the
   ticket (counts, percentages, server names).
5. Backfill any existing open tickets via
   `ticket_state.backfill(...)` — template at
   `scripts/veeam-365/_backfill_state.py`.

After migration: the central monitor at
`scripts/clientportal/ticket_monitor.py check` handles 24h reminders to
support@technijian.com automatically. Retire this skill's local
reminder loop / state file.
