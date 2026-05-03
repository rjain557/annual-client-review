---
name: cp-ticket-management
description: "Use when any pipeline needs to (1) create CP tickets idempotently — same issue must not file the same ticket twice, (2) track tickets across runs in a central state file (state/cp_tickets.json), (3) send 24-hour reminder emails to support@technijian.com when an open ticket has not been resolved, or (4) mark tickets resolved to stop reminders. Generic / cross-skill — every automated CP ticket creator (Veeam 365, Veeam VBR, MailStore, Sophos, Meraki anomaly, Huntress incident, M365 security) should switch to the tracked wrapper here. Examples: 'check open tickets', 'send 24h reminders for due tickets', 'mark ticket 1452721 resolved', 'list open client portal tickets', 'why didn't my caller create a duplicate ticket', 'wire ticket-state tracking into <pipeline>'."
---

# CP Ticket Management — state, idempotency, 24h reminders

A central layer over `cp-create-ticket` that adds:

1. **Idempotency** — every ticket carries an `issue_key`. Re-running a
   pipeline with an open ticket for the same issue_key returns the
   existing ticket id instead of filing a duplicate.
2. **Central state file** — `state/cp_tickets.json` records every
   pipeline-opened ticket: who, when, priority, source skill, full
   history (created → reminders → resolved).
3. **24-hour reminder emails** — `ticket_monitor.py check` scans state,
   finds open tickets older than the reminder window (default 24h
   since `created_at` or `last_reminder_at`), and emails
   support@technijian.com with a "please action this ticket" body.
4. **Manual resolution** — `ticket_monitor.py resolve <ticket_id>`
   stops further reminders.

> Built 2026-05-02. Initial caller: `scripts/veeam-365/file_capacity_tickets.py`.
> Ready for adoption by every other ticket-creating pipeline (see
> "Migration guide" below).

## Files

| Layer | Path |
| --- | --- |
| State file | `state/cp_tickets.json` (created on first write) |
| State CRUD | `scripts/clientportal/ticket_state.py` |
| Email send | `scripts/clientportal/ticket_email.py` (M365 Graph; reuses `_secrets.get_m365_credentials()`) |
| Monitor CLI | `scripts/clientportal/ticket_monitor.py` |
| Tracked wrapper | `cp_tickets.create_ticket_for_code_tracked()` in `scripts/clientportal/cp_tickets.py` |

## Issue-key convention

```
"<source-skill>:<issue-type>:<resource-id>"
```

Examples in use:

| Issue key | Meaning |
| --- | --- |
| `veeam-365:repo-capacity:AFFG-O365` | Veeam 365 repo `AFFG-O365` is filling up |
| `veeam-365:repo-capacity:TECH-O365` | Veeam 365 repo `TECH-O365` is filling up |
| `veeam-365:repo-capacity-and-warning:ALG-O365` | Veeam 365 repo + job-warning combo |
| `veeam-365:migration-cleanup:ORX` | Veeam 365 ORX migration cleanup |

If the same issue recurs after a previous one was resolved (e.g.
the AFFG repo gets extended, then fills up again 6 months later),
the entry is **overwritten** with the new ticket id — `history`
accumulates so the timeline is preserved.

## Daily one-shot (recommended cron / scheduled task)

```bash
cd c:/VSCode/annual-client-review/annual-client-review-1
python scripts/clientportal/ticket_monitor.py check
```

Run once a day on the production workstation (NOT the dev box per
[[no-dev-box-schedules]]). Each open ticket beyond the 24h window gets
one reminder per run; multiple runs on the same day are safe (the
"due" check uses `last_reminder_at` so the next reminder is 24h after
the last one).

## CLI

```bash
# list everything in state
python ticket_monitor.py list

# only open tickets
python ticket_monitor.py list --open

# JSON dump
python ticket_monitor.py list --json

# check + send reminders for due tickets (24h default)
python ticket_monitor.py check
python ticket_monitor.py check --dry-run        # don't actually email
python ticket_monitor.py check --hours 48       # custom window
python ticket_monitor.py check --to manager@technijian.com

# mark a ticket resolved (stops reminders); accepts ticket_id OR issue_key
python ticket_monitor.py resolve 1452721 --note "fixed by SK"
python ticket_monitor.py resolve veeam-365:repo-capacity:AFFG-O365 --note "extended to 5 TB"
```

## Programmatic — the tracked wrapper

For any new caller, prefer `create_ticket_for_code_tracked()` over the
raw `create_ticket_for_code()`:

```python
import sys
sys.path.insert(0, r"c:/VSCode/annual-client-review/annual-client-review-1/scripts/clientportal")
import cp_tickets

result = cp_tickets.create_ticket_for_code_tracked(
    "AFFG",
    issue_key="veeam-365:repo-capacity:AFFG-O365",
    source_skill="veeam-365-pull",
    title="Veeam 365 backup repo AFFG-O365 at 91.7% full",
    description="...",   # full step-by-step body
    priority=1255,        # Same Day
    assign_to_dir_id=205, # CHD : TS1
    role_type=1232,       # Tech Support
    metadata={"repo": "AFFG-O365", "used_pct": 91.7, "free_gb": 80},
)
# result -> {ticket_id, skipped, state_entry, raw}
if result["skipped"]:
    print(f"existing ticket #{result['ticket_id']} — no new ticket filed")
else:
    print(f"new ticket #{result['ticket_id']} recorded in state")
```

The wrapper:
1. Looks up `issue_key` in state.
2. If found AND not resolved → returns existing without calling the SP.
3. If found AND resolved → falls through, creates new, records it
   (history accumulates).
4. If not found → creates new, records it.

## Reminder email shape

Plain HTML, Technijian colors, sent FROM the M365 mailbox configured
in `_secrets.get_m365_credentials()`. Subject:

```
[CP #1452721 reminder] AFFG — Veeam 365 backup repo AFFG-O365 at 91.7% full — only 80 GB free of 1 TB
```

Body includes ticket number, client, source skill, priority, assignee
(DirID 205 / CHD : TS1), age in hours/days, reminder count, the original
title, and a "please action this ticket" callout pointing the tech at
the CP description (which already has the full step-by-step
remediation, courtesy of the source pipeline).

## Migration guide — switching an existing caller

Every caller that opens CP tickets directly (Sophos
`route_alerts.py`, MailStore `route_alerts.py`, future Meraki / M365
ticket creators) should migrate. Steps:

1. Replace `cp_tickets.create_ticket(...)` or
   `cp_tickets.create_ticket_for_code(...)` with
   `cp_tickets.create_ticket_for_code_tracked(...)`.
2. Pick a stable `issue_key` for each unique issue. Use the convention
   `<source>:<type>:<resource>`. Same fingerprint must always map to
   the same conceptual issue.
3. Pass `source_skill="<your-skill-name>"`.
4. Optional but recommended: pass `metadata={...}` with the data points
   that justified opening the ticket (e.g. counts, percentages).
5. Backfill any tickets you've already filed with
   `ticket_state.backfill(...)` so the monitor can track them — see
   `scripts/veeam-365/_backfill_state.py` for a template.

## State schema (state/cp_tickets.json)

```jsonc
{
  "schemaVersion": 1,
  "tickets": {
    "veeam-365:repo-capacity:AFFG-O365": {
      "ticket_id": 1452721,
      "issue_key": "veeam-365:repo-capacity:AFFG-O365",
      "client_code": "AFFG",
      "source_skill": "veeam-365-pull",
      "title": "...",
      "priority_id": 1255,
      "assign_to_dir_id": 205,
      "created_at": "2026-05-02T20:01:00+00:00",
      "last_reminder_at": null,
      "reminder_count": 0,
      "resolved_at": null,
      "resolved_note": null,
      "metadata": {"repo": "AFFG-O365", "used_pct": 91.7, "free_gb": 80, "cap_tb": 1.0},
      "history": [
        {"ts": "2026-05-02T20:01:00+00:00", "event": "created", "ticket_id": 1452721}
      ]
    }
  }
}
```

## Currently tracked (verified 2026-05-02)

| Ticket | Client | Source | Issue key |
| --- | --- | --- | --- |
| #1452721 | AFFG | veeam-365-pull | `veeam-365:repo-capacity:AFFG-O365` |
| #1452722 | Technijian | veeam-365-pull | `veeam-365:repo-capacity:TECH-O365` |
| #1452723 | ALG | veeam-365-pull | `veeam-365:repo-capacity-and-warning:ALG-O365` |
| #1452724 | ORX | veeam-365-pull | `veeam-365:migration-cleanup:ORX` |

The 8 Veeam VBR tickets (#1452728-1452735, opened in a parallel
session) and the 3 MailStore tickets (#1452674-1452676) are NOT yet
in state — those callers still use the raw `create_ticket_for_code()`.
Backfill them with `ticket_state.backfill(...)` when migrating those
callers.

## Future enhancements (not built)

- **CP polling for status / time-entry activity** — today the monitor
  sends reminders based purely on age. Once the right CP read SP is
  identified (`stp_xml_Tkt_API_Read` candidates from
  [[reference_cp_user_role_sps]]), the monitor can detect whether the
  ticket has been touched (status change, time logged) and skip
  reminders for tickets actually being worked on.
- **Reminder escalation** — currently sends one email per 24h to the
  same address. Could escalate to a manager after N reminders.
- **Slack / Teams webhook** — alternative delivery channel for high-priority tickets.

## Gotchas

- **issue_key is the only dedup key.** Two callers using the same
  issue_key for different things will collide. Use the
  `<source>:<type>:<resource>` convention strictly.
- **Backfill is overwriting.** `ticket_state.backfill(...)` replaces
  the entry for an issue_key wholesale. Use it only for one-time
  registration of pre-existing tickets.
- **dry-run does not record state.** `file_capacity_tickets.py
  --dry-run` calls the raw `create_ticket_for_code` so the state file
  isn't touched.
- **Email sender mailbox** comes from
  `_secrets.get_m365_credentials()[3]` — the same mailbox the Sophos
  reminder pipeline already uses (`RJain@technijian.com` by default,
  override with `M365_MAILBOX` env var).
- **Schedule on the production workstation, not the dev box** per
  [[no-dev-box-schedules]].

## Related

- `cp-create-ticket` — underlying ticket-creation skill (`stp_xml_Tkt_API_CreateV3`)
- `client-portal-pull` — read side of CP (active clients, contracts)
- `scripts/clientportal/build_client_meta.py` — keeps `clients/<code>/_meta.json` fresh
