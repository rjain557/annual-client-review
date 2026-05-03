---
name: meraki-monthly-report
description: "Use when the user asks to build, generate, or refresh monthly Cisco Meraki activity reports — branded Word docs summarizing IDS/IPS, firewall activity, configuration posture, WAN configuration, and daily trend per client per month. Reads daily files produced by the meraki-pull pipeline, runs the proofread-report gate before delivery. Examples: \"generate meraki monthly report for VAF March 2026\", \"build Q1 2026 meraki reports for all clients\", \"refresh meraki monthly reports\", \"meraki activity report for BWH last month\"."
---

# Meraki Monthly Activity Report

Builds branded Word reports summarizing each client org's Meraki activity for
a calendar month: IDS/IPS event volume, firewall activity, current
configuration posture, WAN interface configuration, and a daily trend table.
One Word doc per (client, month). Wired with the proofreader at
`proofread-report` so a defective report fails the build instead of shipping.

## Prerequisites

1. **Daily Meraki data must be present** for the month being reported on.
   Run the `meraki-pull` skill first (`pull_all.py` or
   `pull_security_events.py --since X --until Y` + `pull_network_events.py
   --since X --until Y`). Without daily files, the aggregator writes an
   empty summary and the proofreader will flag missing sections.
2. **Configuration snapshot** must exist (`pull_configuration.py`). The
   "Network & Device Inventory", "Firewall Configuration", and "Security
   Posture" sections come from this — they're point-in-time, not historical,
   so the most recent run feeds every month's report. Must also include WAN
   uplink data (`uplink_statuses.json` + `devices/<serial>/uplink_settings.json`).
3. **`python-docx`** must be installed (`pip install python-docx`).

## Generate

```bash
cd scripts/meraki

# Step 1: Aggregate daily files -> per-month JSON summary
python aggregate_monthly.py --month 2026-03                  # one month, all orgs
python aggregate_monthly.py --from 2026-01 --to 2026-03      # range
python aggregate_monthly.py --only vaf,bwh                   # subset

# Step 2: Render the Word docs (auto-runs proofread_docx.py at the end)
python generate_monthly_docx.py --month 2026-03
python generate_monthly_docx.py --from 2026-01 --to 2026-03 --only vaf,bwh
```

`generate_monthly_docx.py` invokes the proofreader on every doc it produces
and exits non-zero if any report fails. **Do not bypass with `--no-proofread`**
— that flag intentionally does not exist.

## Output

```
clients/<code>/meraki/
  monthly/<YYYY-MM>.json            # aggregated summary (input to docx)
  reports/<Org Name> - Meraki Monthly Activity - <YYYY-MM>.docx

clients/_meraki_logs/
  monthly_index.json                # cross-client roll-up of generated files
```

The JSON summary is the source of truth for everything in the doc — if a
table looks wrong, fix the aggregator (or the underlying daily file), not
the Word generator.

## Sections in the report

1. **Executive Summary** — KPI strip: networks, devices, IDS/IPS events,
   activity events, config changes count.
2. **Network & Device Inventory** — Devices by model, devices by product type,
   per-network rule counts, and a per-device inventory table (name, network,
   model, serial, firmware, LAN IP, type) pulled from the config snapshot.
3. **Firewall Configuration** — Full per-network firewall posture and WAN setup:
   - **WAN Interface Configuration**: device, network, interface (WAN1/WAN2),
     mode (Static/DHCP), IP/subnet, gateway, DNS — including warm-spare
     secondary appliances annotated with live status (active / not connected /
     failed). Deduplicates WAN2 if same IP/gateway as WAN1; suppresses phantom
     WAN3 cellular entries when no SIM installed.
   - **L3 outbound firewall rules**: protocol, policy, source CIDR, dest CIDR,
     comment (non-default rules only)
   - **Inbound firewall rules**: non-default rules only
   - **Port forwarding rules**: name, protocol, public port, LAN IP, allowed IPs
   - **VLANs**: VLAN ID, name, subnet, appliance IP, DHCP handling
   - **SSIDs**: number, SSID name, auth mode (wireless networks only)
   - **S2S VPN**: hub mode and remote subnet list (if configured)
   - **Content filtering**: blocked category list (if configured)
4. **Security Posture** — IDS/IPS mode per network, AMP mode, content
   filtering categories, S2S VPN mode, syslog destinations.
5. **Configuration Changes** — Who changed what this month: total changes,
   by-admin table, by-network table, by-configuration-area table, and a full
   before/after detail table of the 25 most-recent changes for compliance review.
   Green callout when no changes recorded ("baseline is intact").
6. **IDS/IPS & AMP Events** — Top signatures, top sources/destinations,
   blocked vs alerted breakdown, priority distribution.
7. **Firewall / Network Activity** — Top event types, by category, per-network
   rollup with most-frequent event types.
8. **Daily Trend** — Day-by-day count of security events vs activity events.

## Proofreader expected sections (EXPECTED_SECTIONS)

The proofread gate checks for these 8 section headers (case-insensitive, searched
across all text including table cells):

```
Executive Summary
Network & Device Inventory
Firewall Configuration
Security Posture
Configuration Changes
IDS/IPS & AMP Events
Firewall / Network Activity
Daily Trend
```

28/28 reports (Jan–Apr 2026, 7 active orgs) pass 8/8 proofread checks as of
2026-04-30.

## Brand styling

Matches `generate_aava_docx.py` / `generate_bwh_docx.py` conventions:
- Dark blue `#1F4E79` for h1 + table headers
- Medium blue `#2E75B6` for h2
- Alternating row fill `#F2F7FB`
- Pt 9 cell text, Pt 10 body, Pt 16 h1, Pt 12 h2

## Org slugs

Same as the `meraki-pull` skill — `technijian_inc`, `vaf`, `aoc`, `bwh`,
`orx`, `vg`, `aranda_tooling` are the licensed orgs. `technijian` and `gsc`
have no active licenses and produce empty reports if forced.

## Gotchas

- **Empty months are real.** A small client (VAF, AOC) may genuinely have
  zero IDS/IPS events for the month. The report shows "0 events" rather
  than omitting the section. The proofreader doesn't fail on legitimate
  zeros — only on missing sections / placeholders.
- **"No data pulled" vs "data pulled = 0".** If the daily files don't exist
  for the month, the aggregator emits an empty summary. Run the pull first.
  The aggregator does NOT distinguish these in v1; treat empty months with
  suspicion until the corresponding daily files are present.
- **Configuration is the most-recent snapshot.** All months show the latest
  pulled config. Versioned daily snapshots are now stored under
  `config_history/<YYYY-MM-DD>/` — use those to compare any two dates.
  Admin-initiated changes are tracked in the **Configuration Changes** section
  via the `configurationChanges` API with full before/after values.
- **Org name vs slug.** Word doc titles use the human org name from
  `org_meta.json`; file paths use the slug. If they diverge (mid-period
  rename), regenerate the affected month after the next config pull.
- **Network event counts can be large.** Technijian DC alone produces
  60-80k firewall events per month; the activity table only shows top types,
  not every event.
- **WAN table must be pulled before generating.** Run `pull_configuration.py`
  (which now also calls the uplink endpoints) before running
  `aggregate_monthly.py`. If `uplink_statuses.json` is absent, the Firewall
  Configuration section will show no WAN data but will still pass the
  proofreader (it only checks section headers, not content).
- **Dormant org (technijian / id=699778) shares folder with active org
  (technijian_inc / id=80731).** The pull pipeline guards against the dormant
  org overwriting the active org's metadata — but always pull with
  `--only technijian_inc` to be safe when refreshing Technijian data.
- **Table widths are enforced.** All tables are sized to fit within 6.5"
  (US Letter with 1" margins). The proofread gate check #4 (`check_table_widths`)
  will fail any report where a table exceeds this width.

## Related skills

- `meraki-pull` — produces the daily files and config snapshots this skill
  consumes; also pulls WAN uplink data
- `proofread-report` — auto-invoked at the end of `generate_monthly_docx.py`;
  fails the build if any report has missing sections, placeholders, table
  overflow, or mojibake

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
