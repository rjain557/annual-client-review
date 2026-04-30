---
name: meraki-monthly-report
description: "Use when the user asks to build, generate, or refresh monthly Cisco Meraki activity reports — branded Word docs summarizing IDS/IPS, firewall activity, configuration posture, and daily trend per client per month. Reads daily files produced by the meraki-pull pipeline, runs the proofread-report gate before delivery. Examples: \"generate meraki monthly report for VAF March 2026\", \"build Q1 2026 meraki reports for all clients\", \"refresh meraki monthly reports\", \"meraki activity report for BWH last month\"."
---

# Meraki Monthly Activity Report

Builds branded Word reports summarizing each client org's Meraki activity for
a calendar month: IDS/IPS event volume, firewall activity, current
configuration posture, and a daily trend table. One Word doc per (client,
month). Wired with the proofreader at `proofread-report` so a defective
report fails the build instead of shipping.

## Prerequisites

1. **Daily Meraki data must be present** for the month being reported on.
   Run the `meraki-pull` skill first (`pull_all.py` or
   `pull_security_events.py --since X --until Y` + `pull_network_events.py
   --since X --until Y`). Without daily files, the aggregator writes an
   empty summary and the proofreader will flag missing sections.
2. **Configuration snapshot** must exist (`pull_configuration.py`). The
   "Network & Device Inventory" and "Security Posture" sections come from
   this — they're point-in-time, not historical, so the most recent run
   feeds every month's report.
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
   per-network rule counts.
3. **Security Posture** — IDS/IPS mode per network, AMP mode, content
   filtering categories, S2S VPN mode, syslog destinations.
4. **Configuration Changes** — Who changed what this month: total changes,
   by-admin table, by-network table, by configuration-area table, and a full
   before/after detail table of the 25 most-recent changes for compliance review.
   Green callout when no changes recorded ("baseline is intact").
5. **IDS/IPS & AMP Events** — Top signatures, top sources/destinations,
   blocked vs alerted breakdown, priority distribution.
6. **Firewall / Network Activity** — Top event types, by category, per-network
   rollup with most-frequent event types.
7. **Daily Trend** — Day-by-day count of security events vs activity events.

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

## Related skills

- `meraki-pull` — produces the daily files this skill consumes
- `proofread-report` — auto-invoked at the end of `generate_monthly_docx.py`;
  fails the build if any report has missing sections, placeholders, or
  mojibake
