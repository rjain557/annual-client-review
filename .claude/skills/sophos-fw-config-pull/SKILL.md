# Skill: sophos-fw-config-pull

Pull on-box configuration from Sophos XGS firewalls via the admin REST API (port 4444).
Used for change management, firewall rule auditing, and config snapshot diffing.

## When to invoke

Invoke this skill when the user asks to:
- Pull Sophos firewall config / rules / settings for a client
- Check what changed on a Sophos firewall
- Compare firewall configs between dates
- Set up or test the Sophos on-box API for a client
- Run the Sophos config scan

Trigger phrases: "pull sophos config", "sophos firewall rules", "sophos change management",
"scan sophos firewalls", "sophos fw api", "sophos on-box api"

## Prerequisites

### Per-client whitelist (user must do this first)
Each client's XGS firewall must allow the Technijian scanner IP on port 4444:

1. Log in to the XGS admin console: `https://<wan-ip>:4444`
2. Go to **Administration > Device Access**
3. WAN zone row: check **HTTPS** and **API**
4. Add to Allowed IP addresses:
   - `64.58.160.218` (current scanner IP — verify with `--update-ip` flag)
   - (add Technijian DC IP if running from DC, not office)
5. Click Apply

### Per-client credentials (you create after whitelist is in place)
Create `%USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/sophos-fw-<CODE>.md`:

```markdown
# Sophos Firewall API -- <ClientName>

## Firewall 1
- **Hostname:** client-fw-01
- **WAN IP:** 203.0.113.45
- **API Port:** 4444
- **Username:** technijian-api
- **Password:** <password>
- **Serial:** F211ABCDEFGH
```

On the firewall, create `technijian-api` user:
- **Authentication > Users > Add**
- User Type: Administrator
- Profile: Technijian-ReadOnly (create profile with all-Read permissions)

## State files

- `technijian/sophos-pull/state/firewall-api-inventory.json` — scan results, one entry per firewall WAN IP
  - `api_status` values: `not_whitelisted` | `reachable` | `configured` | `auth_failed`
- `clients/<code>/sophos/<date>/config.json` — pulled config snapshot (interfaces, rules, NAT, VPN)

## Script

`technijian/sophos-pull/scripts/scan_sophos_fw_api.py`

## Commands

```bash
# Check which firewalls are reachable (no credentials needed)
python technijian/sophos-pull/scripts/scan_sophos_fw_api.py

# Refresh scanner IP + check reachability
python technijian/sophos-pull/scripts/scan_sophos_fw_api.py --update-ip

# Pull config where credentials exist in keyvault
python technijian/sophos-pull/scripts/scan_sophos_fw_api.py --pull

# Specific clients only
python technijian/sophos-pull/scripts/scan_sophos_fw_api.py --pull --only BWH,ORX

# Longer timeout for slow WAN links
python technijian/sophos-pull/scripts/scan_sophos_fw_api.py --timeout 15 --pull
```

## What config.json contains (sections pulled per firewall)

| Section | config_key | Description |
|---|---|---|
| InterfaceList | interfaces | All interfaces (LAN/WAN/DMZ/VLAN) |
| LANInterface | lan_interfaces | LAN zone interface detail |
| WANInterface | wan_interfaces | WAN zone interface detail |
| FirewallRule | firewall_rules | All firewall policy rules |
| NATRule | nat_rules | DNAT/SNAT/masquerade rules |
| IPSecConnection | ipsec_vpn | Site-to-site IPSec VPN tunnels |
| SSLVPNClientPolicy | sslvpn | SSL VPN client access policies |
| DHCPServer | dhcp_server | DHCP scopes and leases |
| DNSConfig | dns | DNS server settings |
| StaticRoute | static_routes | Static routing table |

## Current firewall inventory (as of 2026-04-30)

All 10 firewalls need whitelist. Scanner IP: `64.58.160.218`

| Code | Hostname | WAN IP | Admin URL | Status |
|---|---|---|---|---|
| ANI | ANI-FIREWALL-01 | 97.93.171.50 | https://97.93.171.50:4444 | NOT_WHITELISTED |
| B2I | B2I-HQ-FW-01 | 98.154.36.202 | https://98.154.36.202:4444 | NOT_WHITELISTED |
| BWH | BWH-HQ-FW-01 | 64.58.142.218 | https://64.58.142.218:4444 | NOT_WHITELISTED |
| BWH | BWH-HQ-FW-01 | 98.174.153.35 | https://98.174.153.35:4444 | NOT_WHITELISTED |
| JDH | JDH-HQ-FW-01 | 12.231.12.100 | https://12.231.12.100:4444 | NOT_WHITELISTED |
| KSS | KSS-HQ-FW-01 | 50.247.89.142 | https://50.247.89.142:4444 | NOT_WHITELISTED |
| ORX | ORX-HQ-FW-01 | 12.79.8.230 | https://12.79.8.230:4444 | NOT_WHITELISTED |
| ORX | JRMED-HQ-FW-01 | 12.189.90.138 | https://12.189.90.138:4444 | NOT_WHITELISTED |
| TALY | TALY-HQ-FW-01 | 162.228.135.162 | https://162.228.135.162:4444 | NOT_WHITELISTED |
| VAF | VAF-HQ-FW-01 | 64.58.151.18 | https://64.58.151.18:4444 | NOT_WHITELISTED |

## Workflow once whitelist is in place

1. Create `technijian-api` read-only user on the firewall
2. Add credentials to `keys/sophos-fw-<CODE>.md`
3. Run `scan_sophos_fw_api.py --pull --only <CODE>` to verify
4. Status flips to `configured` in inventory; config saved to `clients/<code>/sophos/<date>/config.json`
5. Add `--pull` to the daily Sophos CMD wrapper (`run-hourly-sophos.cmd`) once all clients are configured

## Notes

- Self-signed TLS cert on all XGS appliances — scanner uses `ssl.CERT_NONE` (expected)
- The XGS API endpoint is `POST /webconsole/APIController` with XML body (not REST/JSON)
- Auth is per-request (username + password in each XML envelope) — no session token
- Config pull pulls ~10 sections per firewall; takes 5-15s per device depending on WAN latency
- SFOS 18.5+ confirmed compatible; all 14 of Technijian's XGS devices are on SFOS 19.5-22.0
