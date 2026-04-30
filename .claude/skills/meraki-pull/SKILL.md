---
name: meraki-pull
description: "Use when the user asks to pull Cisco Meraki data — IDS/IPS events, firewall activity logs, security events, configuration snapshots (firewall rules, VLANs, content filtering, traffic shaping, VPN, SSIDs, switch settings) — across all client organizations in the Technijian MSP Meraki dashboard. Handles auth from the OneDrive key vault, multi-org enumeration, license-gated 403 tolerance, and per-client folder output. Examples: \"pull meraki ids/ips for all clients\", \"daily meraki activity log refresh\", \"snapshot meraki firewall configuration\", \"refresh meraki data for VAF/BWH\"."
---

# Cisco Meraki Multi-Org Pull

The Cisco Meraki Dashboard API is a REST API at `https://api.meraki.com/api/v1`,
authenticated with `Authorization: Bearer <api-key>`. The current personal MSP
key (`rjain@technijian.com`) has admin access to **9 organizations** (7
licensed/active, 2 dormant) covering 11 networks and 30 devices.

Credentials live in the key vault at:

```
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\meraki.md
```

Reusable Python module: `scripts/meraki/meraki_api.py`
Pipeline scripts: `scripts/meraki/pull_*.py`
(repo root: `c:/VSCode/annual-client-review/annual-client-review-1`)

## Auth flow

```python
import meraki_api as m
me = m.whoami()                 # GET /administered/identities/me — health check
orgs = m.list_organizations()   # 9 orgs the key has admin on
```

The module reads the key from `MERAKI_API_KEY` env var if set, otherwise from
the keys/meraki.md vault file (regex grabs the first 40-hex token under
`**API Key:**`). Bearer header is added automatically. **Do not use the legacy
`X-Cisco-Meraki-API-Key` header — newer keys reject it.**

## Daily one-shot

```bash
cd c:/VSCode/annual-client-review/annual-client-review-1/scripts/meraki
python pull_all.py                        # last 24h events + full config snapshot
python pull_all.py --days 7               # 7-day backfill for events
python pull_all.py --only VAF,BWH         # restrict by org slug
python pull_all.py --skip-config          # events only
python pull_all.py --skip-events          # snapshot only
```

Per-component scripts can be run on their own:

```bash
python pull_security_events.py --days 7   # IDS/IPS + AMP, per-day files
python pull_network_events.py             # firewall/VPN/DHCP activity log per network
python pull_network_events.py --product-type wireless    # MR event log
python pull_configuration.py              # full config snapshot, all orgs
```

## Output structure

Output uses the standard per-client layout: `clients/<code>/meraki/...`. The
Meraki-org-slug → CP-LocationCode mapping is in `scripts/meraki/_org_mapping.py`.
Cross-org logs (run summaries) land in `clients/_meraki_logs/`.

```
clients/<code>/meraki/
  org_meta.json
  networks.json
  devices.json
  config_snapshot_at.json
  security_events/
    2026-04-29.json                # daily IDS/IPS + AMP file
  network_events/
    <network-slug>/
      2026-04-29.json              # firewall/VPN/DHCP activity log
  networks/
    <network-slug>/
      meta.json
      firewall_l3.json firewall_l7.json firewall_inbound.json
      firewall_cellular.json firewall_port_forwarding.json
      firewall_1to1_nat.json firewall_1tomany_nat.json
      security_intrusion.json      # IDS/IPS mode + ruleset
      security_malware.json        # AMP config
      content_filtering.json
      traffic_shaping.json traffic_shaping_rules.json traffic_shaping_uplink_bw.json
      vlans.json vpn_s2s.json static_routes.json
      appliance_ports.json appliance_settings.json
      wireless_ssids.json wireless_settings.json wireless_rf_profiles.json   # MR
      switch_access_policies.json switch_qos_rules.json
      switch_port_schedules.json switch_settings.json                         # MS
      syslog_servers.json snmp.json alerts_settings.json
      group_policies.json webhooks_http_servers.json
  monthly/<YYYY-MM>.json            # aggregated summary (input to docx)
  reports/<Org Name> - Meraki Monthly Activity - <YYYY-MM>.docx

clients/_meraki_logs/
  security_events_pull_log.json
  network_events_pull_log.json
  configuration_pull_log.json
  monthly_index.json
```

CP-code mapping: `technijian_inc → technijian`, `aranda_tooling → arnd`,
`aoc/bwh/orx/vaf/vg → same`. Event files are idempotent on day boundaries
(re-running on the same day overwrites that day's file). The puller skips
already-fetched days unless `--force` is passed. Configuration snapshots
overwrite each run.

## Org slugs (current)

| Slug | Org Name | Org ID | Status |
|---|---|---|---|
| `technijian_inc` | Technijian Inc | 80731 | ✅ |
| `technijian` | Technijian | 699778 | ❌ 403 — dormant |
| `vaf` | VAF | 1297510 | ✅ |
| `aranda_tooling` | Aranda Tooling | 1549341 | ✅ |
| `aoc` | AOC | 1567983 | ✅ |
| `bwh` | BWH | 572520102629475782 | ✅ |
| `gsc` | GSC | 573083052582896176 | ❌ 403 — dormant |
| `orx` | ORX | 573083052582896177 | ✅ |
| `vg` | VG | 3710403142999867518 | ✅ |

The two 403 orgs return `"Meraki API services are available for licensed
Meraki devices only"` — the key has admin rights, but those orgs have no
active device licenses. Skip silently; don't treat as auth failure.

## Endpoint map

### Time-bounded (events)
| Endpoint | Purpose | Time params |
|---|---|---|
| `/organizations/{id}/appliance/security/events` | **IDS/IPS + AMP** events org-wide | `t0`, `t1` ISO **or** `timespan` seconds (max 31d) |
| `/networks/{id}/events?productType=appliance` | Firewall / VPN / DHCP activity log | same |

Pagination: org `security/events` uses Link `rel=next` headers; network
`events` uses `pageEndAt` cursor (handled by `meraki_api.get_network_events`).

### Configuration (point-in-time)
The endpoint sets are constants in `meraki_api.py`:
- `APPLIANCE_CONFIG_ENDPOINTS` — 17 endpoints (firewall L3/L7/inbound/cellular,
  NAT 1:1 + 1:many, port forwards, IDS/IPS, AMP, content filtering, traffic
  shaping, VLANs, S2S VPN, static routes, ports, settings)
- `WIRELESS_CONFIG_ENDPOINTS` — 3 (SSIDs, settings, RF profiles)
- `SWITCH_CONFIG_ENDPOINTS` — 4 (access policies, QoS, port schedules, settings)
- `NETWORK_WIDE_CONFIG_ENDPOINTS` — 6 (syslog, SNMP, alerts, group policies,
  floor plans, webhook HTTP servers)

The configuration puller filters endpoints by `network.productTypes` so
appliance-only networks don't probe wireless/switch endpoints (which would
404 noisily).

## Programmatic use

```python
import sys
sys.path.insert(0, r"c:/VSCode/annual-client-review/annual-client-review-1/scripts/meraki")
import meraki_api as m

orgs = m.list_organizations()
vaf = next(o for o in orgs if o["name"] == "VAF")
nets = m.list_networks(vaf["id"])
events = m.get_security_events_org(vaf["id"], timespan=86400)   # last 24h
fw_l3 = m.get(f"/networks/{nets[0]['id']}/appliance/firewall/l3FirewallRules")
```

`m.get(path, allow_403=True, allow_404=True)` returns `None` instead of
raising on 403/404 by default — that's the right behavior for license-dormant
orgs and feature-disabled networks.

## Rate limits & retry

- **10 req/sec per org**, 5 concurrent connections per IP recommended.
- `meraki_api._request()` honors `Retry-After` on 429 and exponentially
  backs off on 5xx, up to 4 retries.
- For multi-org pulls the orchestrator runs orgs sequentially. Don't
  parallelize across orgs without a token-bucket limiter.

## Gotchas

- **Bearer auth only.** `X-Cisco-Meraki-API-Key` is rejected for keys created
  in 2026+. Always `Authorization: Bearer <key>`.
- **403 ≠ invalid key.** Org-level license gate uses the same 403 status as
  unauthorized. Check for the `"licensed Meraki devices only"` body string.
- **Org IDs vary by length.** Older orgs are 5-7 digit ints (`80731`); newer
  ones are 18-digit snowflakes (`572520102629475782`). Treat as opaque strings.
- **`/networks/{id}/events` paginates differently** — uses `pageEndAt` cursor,
  not Link headers. The wrapper handles it.
- **Time windows max 31 days** for `/appliance/security/events`. For longer
  backfills, loop day-by-day (`pull_security_events.py --since/--until`).
- **`productType` matters** for `/networks/{id}/events`: pass `appliance` for
  firewall events, `wireless` for AP events, `switch` for switch events.
- **Bandwidth.** Org-wide security events for active days can exceed 10 MB.
  Per-day files keep this manageable.
- The user's personal key was exposed in chat on 2026-04-29; the vault file
  notes this and recommends rotating to a service-account key
  (`meraki-api@technijian.com`) for production.

## Related: key vault

```
%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\meraki.md
```

Contains the API key, all 9 org IDs, license/status table, endpoint coverage,
and rotation history. The `meraki_api.get_api_key()` helper reads it.
