# Sophos Central Monthly Reporting Service
## Full Specification & Pricing — Brochure / One-Pager Source

---

## Service Name Options (choose one for branding)

- **Sophos Insight Reports** — mirrors M365 Insight branding, portfolio-consistent
- **ClearDesk Sophos** — friendly, MSP-facing
- **Firewall Monthly Health Report** — utilitarian, descriptive
- **Sophos Central Monthly Monitor** — product-name forward, recognizable

---

## Elevator Pitch (use on cover of brochure)

> Every hour, your Sophos firewalls generate thousands of signals about
> intrusion attempts, malware callbacks, web policy violations, and network
> anomalies. Most MSPs see a fraction of it — only when alerts fire in
> the Central dashboard. We pull every IPS signature hit, ATP callback, web
> filter violation, and VPN event directly from your firewall, classify
> it, route billable tickets automatically, and deliver a plain-English
> monthly report on the 1st. You stop firefighting. You start billing.

---

## Who It's For

### Primary buyer: MSPs managing Sophos XG / XGS / UTM firewalls
MSPs who are Sophos Central Partner account holders managing firewalls
on behalf of 3–50 client organizations who want proactive managed firewall
billing without investing in a full SIEM.

**Ideal profile:**
- Sophos Central Partner account (MSP Partner portal, not per-tenant)
- 5–50 managed Sophos tenants
- XG/XGS firewalls accessible via HTTPS from Technijian infrastructure
  (site-to-site VPN or direct internet-facing management port)
- Currently checking alerts reactively or not at all

### Secondary buyer: In-house IT / network operations
Internal IT teams managing a single organization's XGS deployment who want
a monthly executive summary with full threat detail for their compliance
officer or board.

---

## The Problem We Solve

| Pain Point | Without This Service | With This Service |
|---|---|---|
| IPS/IDS events invisible | Buried in firewall log viewer — no one looks | Pulled hourly, top signatures in every report |
| Open alerts going unnoticed | Sit in Central for days/weeks | CP ticket created within 1 hour of detection |
| Malware callbacks unreported | ATP fires, nobody investigates | ATP events listed by host + destination + action |
| Web filter violations unmeasured | Client asks "is policy working?" — no answer | Top blocked categories + policy exception hits monthly |
| No proactive firewall billing | Break-fix only — client calls, you respond | Monthly managed firewall report = recurring revenue |
| QBR prep time | 1–2 hrs/client pulling from Central portal | 0 hrs — report ready on the 1st |
| Traffic anomalies missed | Discovered when bandwidth spikes or client complains | Top talkers + top destinations + bandwidth trends flagged |

---

## Service Tiers

Two tiers based on API access depth. Both use the Sophos Central Partner API;
**Advanced and Enterprise additionally use the XGS device-side REST API**
(runs on-box at `https://<firewall-ip>:4444/`) which unlocks the full
firewall log engine — IPS signatures, web filter detail, ATP events,
application control, per-user traffic, and traffic analytics.

| | **Essentials** | **Advanced** | **Enterprise** |
|---|---|---|---|
| API source | Central Partner API | Central + XGS REST | Central + XGS REST |
| Firewalls per tenant | 1–5 | 1–5 | 6+ |
| Alert detection + auto CP ticket | ✅ | ✅ | ✅ |
| Firewall inventory + firmware | ✅ | ✅ | ✅ |
| WAN / VPN connectivity events | ✅ | ✅ | ✅ |
| IPS / IDS per-signature events | — | ✅ | ✅ |
| ATP / malware callback detection | — | ✅ | ✅ |
| Web filter category reporting | — | ✅ | ✅ |
| Application control events | — | ✅ | ✅ |
| Per-user threat + traffic activity | — | ✅ | ✅ |
| Network traffic analytics | — | ✅ | ✅ |
| Firewall rule hit counts | — | ✅ | ✅ |
| SSL/TLS inspection events | — | ✅ | ✅ |
| Multi-site topology map | — | — | ✅ |
| HA pair failover log | — | ✅ | ✅ |
| On-demand report generation | — | ✅ | ✅ |
| API export (JSON) | — | — | ✅ |
| Custom alert routing rules | — | — | ✅ |
| SLA: report delivery by 1st 9 AM | — | — | ✅ |
| Dedicated customer success | — | — | ✅ |

---

## What Every Report Includes

Reports are delivered as **branded Microsoft Word documents (.docx)**
with your company logo, colors, and cover page. Each report covers
one Sophos tenant for one calendar month.

Sections marked **[Advanced+]** require the XGS device-side REST API
(Advanced or Enterprise tier). Sections are automatically omitted — not
shown as blank — when the required data source is not configured.

### Section 1 — Executive Summary
- KPI strip: total firewalls, open alerts, IPS blocks, ATP hits, web
  violations, VPN tunnels active, firmware compliance %
- Month-over-month change indicators (up/down/stable per metric)
- Plain-English status narrative: "Firewall environment is healthy /
  requires attention in 3 areas"
- Top-priority callout: most urgent open item or confirmation of clean status
- Threat severity breakdown: Critical / High / Medium counts at a glance

### Section 2 — Firewall Inventory & Health
- All Sophos firewalls in the tenant: model, serial, firmware version,
  WAN IPs, status (online / offline / degraded), uptime this month
- Firmware compliance: current version vs latest available — firewalls
  running outdated firmware flagged as P2 action item
- HA (High Availability) pair status: both nodes healthy, failover events
  this month, failback confirmed
- Firewall rule count: total active rules, unused rules (0 hits this month)
  flagged as cleanup candidates **[Advanced+]**

### Section 3 — Alert Activity
- Total alerts raised, grouped by severity (Critical / High / Medium /
  Low / Informational)
- Alert category breakdown: gateway, web filtering, email, IPS, authentication,
  system health, VPN
- New vs aging vs resolved: opened, still open at month-end, closed this month
- Top 10 alerts by severity + age: description, first seen, last seen,
  current status, linked CP ticket number
- Alert aging: any alert open > 7 days flagged as escalation risk

### Section 4 — IPS / IDS Threat Intelligence **[Advanced+]**
- Total IPS block and detect events for the month
- Top 10 attack signatures by hit count: CVE reference (where available),
  attack category (SQL injection, buffer overflow, RCE, etc.), action taken
- Top attacker source IPs: repeat offenders, country of origin, total hit count
- Top targeted internal hosts: which servers/workstations are most targeted
- Inbound vs outbound: inbound attacks (external → internal) vs outbound
  attempts (infected host → external C2) — outbound is the higher-severity signal
- MITRE ATT&CK mapping for top signatures where available
- Week-over-week trend: is attack volume increasing, decreasing, or stable?

### Section 5 — ATP & Advanced Threat Protection **[Advanced+]**
- Total ATP events: malware callbacks blocked, C2 destinations hit,
  malicious file detections
- Per-event detail: internal host, destination IP/domain, threat name,
  action (blocked / detected / allowed), timestamp
- Unresolved ATP hits: any host with an active ATP detection that has not
  been investigated — flagged as P1 finding
- Threat categories: ransomware C2, botnet, exploit kit, credential theft,
  cryptomining — breakdown by category count
- Repeat offenders: internal hosts generating multiple ATP hits (likely
  compromised — highest priority for investigation)

### Section 6 — Web Filtering & Application Control **[Advanced+]**
- Total web requests processed, blocked, allowed
- Top 10 blocked categories: Malware, Phishing, P2P, Streaming, Social
  Media, Gambling, etc. — by request count + unique users
- Top 10 users by blocked request volume (anonymizable per client preference)
- Policy exceptions: sites explicitly allowed via rule override — review for
  policy creep
- Application control top blocked applications: count by application name
  and category (Shadow IT signal — unsanctioned cloud storage, VPNs, etc.)
- SSL/TLS inspection coverage: % of HTTPS traffic inspected vs bypassed;
  certificates that failed validation

### Section 7 — Network Traffic Analytics **[Advanced+]**
- Total inbound/outbound bandwidth for the month
- Top 10 internal hosts by outbound bandwidth (data exfiltration signal if
  abnormal)
- Top 10 external destinations by connection count and bandwidth
- Bandwidth trend: daily bandwidth graph — spikes or anomalous patterns called out
- Protocol mix: % breakdown by TCP/UDP/ICMP and by application protocol
- Internal traffic anomalies: hosts communicating on unusual ports or
  to unusual internal subnets (lateral movement signal)

### Section 8 — User Security Activity **[Advanced+]**
- Per-user threat summary: users who triggered IPS events, ATP detections,
  or web filter blocks this month — count per user, highest severity event
- Authentication events: successful and failed admin logins to the firewall
  console — who, when, source IP, method
- Remote access VPN users: active users, session count, bytes transferred,
  any authentication failures or unusual source countries
- Privileged action audit: firewall configuration changes made via admin
  console or API — what changed, who changed it, when

### Section 9 — VPN & Remote Access
- Site-to-site VPN tunnels: tunnel name, remote peer, status, uptime %,
  bytes transferred, downtime events this month
- Remote access VPN: total sessions, unique users, peak concurrent, auth
  failures, sessions from unusual countries
- SD-WAN / WAN load balancing: primary vs backup interface utilization,
  failover events, automatic failback confirmed **[Advanced+]**
- Certificate expiry: VPN certificates expiring in the next 90 days flagged

### Section 10 — What Technijian Did For You This Month
- CP tickets opened from this tenant's alerts: ticket number, title,
  severity, date opened, current status
- Alerts acknowledged and resolved by Technijian team
- Firmware updates applied (if any)
- Configuration changes visible in the admin audit log
- Technician hours logged against firewall-related tickets (if PSA integrated)

### Section 11 — Findings & Recommendations
- Prioritized action list (P1/P2/P3):
  - **P1:** unresolved ATP hit on an internal host; Critical alert open > 48h;
    offline firewall; active WAN failover at month-end; outbound C2 callback
    detected; firewall admin auth brute force
  - **P2:** firmware out of date; IPS attack volume trending up >25% month-over-month;
    VPN tunnel instability (>3 disruptions/week); aging High alert; SSL
    inspection bypassing > 30% of HTTPS traffic; unused firewall rules > 20%
  - **P3:** Low/Info alerts pending cleanup; web filter policy exceptions accumulating;
    application control gaps (Shadow IT); firewall rule count > 200 (complexity risk);
    VPN certificates expiring in 60 days
- Each finding includes estimated remediation effort (hours) and risk if
  left unaddressed

### Section 12 — About This Report
- Data sources and cadence explanation
- API access method for this tenant (Central Partner API / XGS REST API)
- Scope clarification (firewall layer only — endpoint covered separately
  under Huntress Endpoint Monitoring)
- Tenant ID + firewall serial numbers for traceability

---

## Pricing

### Model: Flat Per-Org / Per-Month, Tiered by Access Depth

| Tier | API Source | Firewalls | Monthly | Annual (save 17%) | Per-Day |
|---|---|---|---|---|---|
| **Essentials** | Central Partner API only | 1–5 | **$99** | $990/yr | $3.30/day |
| **Advanced** | Central + XGS REST API | 1–5 | **$199** | $1,990/yr | $6.63/day |
| **Enterprise** | Central + XGS REST API | 6+ | **$299** | $2,990/yr | $9.97/day |

**Why the Essentials → Advanced jump ($99 → $199):**
The XGS REST API unlocks the full on-box log engine — IPS signatures, ATP events,
web filter analytics, user activity, traffic trends. This is SIEM-quality data
for a fraction of SIEM cost. Typical SIEM/MSSP services charge $300–$800/month
per site for equivalent visibility. Advanced at $199 prices the gap competitively
while reflecting the setup complexity of direct firewall API access.

**Firewall count definition:** active XG/XGS/UTM appliances reporting to
the Central tenant within the billing month. HA pairs count as 1 (shared
license and management identity).

**Volume discount (MSPs with 10+ tenants):**
Contact us. Typical break: 10% off for 10–24 tenants, 20% off for 25+.

---

## Bundle Pricing

### With Meraki Monitoring (10% off)

| Sophos Tier | Sophos Only | + Meraki ($150/org) | 10% Bundle | Annual Bundle |
|---|---|---|---|---|
| Essentials $99 | $99 | $249 | **$224/mo** | $2,688/yr |
| Advanced $199 | $199 | $349 | **$314/mo** | $3,768/yr |
| Enterprise $299 | $299 | $449 | **$404/mo** | $4,848/yr |

### With M365 Reporting (10% off)

| M365 Band | M365 Only | + Sophos Advanced | 10% Bundle | Annual Bundle |
|---|---|---|---|---|
| XS ($15) | $15 | $214 | **$193/mo** | $2,316/yr |
| S ($29) | $29 | $228 | **$205/mo** | $2,460/yr |
| M ($49) | $49 | $248 | **$223/mo** | $2,676/yr |
| L ($79) | $79 | $278 | **$250/mo** | $3,000/yr |
| XL ($129) | $129 | $328 | **$295/mo** | $3,540/yr |

### Full Stack Bundle — M365 + Meraki + Sophos Advanced (15% off)

| Example client | Individual total | 15% bundle | Annual |
|---|---|---|---|
| 30 users, 2 FW, 1 Meraki org | $49 + $199 + $150 = $398 | **$338/mo** | $4,056/yr |
| 75 users, 5 FW, 1 Meraki org | $79 + $199 + $150 = $428 | **$364/mo** | $4,368/yr |
| 100 users, 3 FW, 1 Meraki org | $79 + $199 + $150 = $428 | **$364/mo** | $4,368/yr |

---

## ROI & Value Calculator

### Time savings

| MSP profile | Manual Sophos time/mo | At $75/hr | Service cost | Monthly savings |
|---|---|---|---|---|
| 10 Essentials tenants | 10 × 1.5h = 15h | $1,125 | $990 | **$135** |
| 10 Advanced tenants | 10 × 2.5h = 25h | $1,875 | $1,990 | **($115) — break-even month 2** |
| 20 Advanced tenants | 20 × 2.5h = 50h | $3,750 | $3,180 | **$570** |

Note: Advanced tenants take 2.5h/month to manually review because the IPS, ATP,
and traffic data requires individual log viewer sessions — time the service
eliminates.

### Missed-billing recovery (Essentials)

| Tenants | Missed incidents/mo | At $75 each | Service cost | Net |
|---|---|---|---|---|
| 10 tenants | 10 × 2 = 20 | $1,500 | $990 | **+$510** |
| 20 tenants | 20 × 2 = 40 | $3,000 | $1,980 | **+$1,020** |

### SIEM displacement (Advanced)

Equivalent SIEM/MSSP visibility (Perch, Arctic Wolf lite, ConnectWise SIEM)
runs $300–$800/site/month. Advanced at $199 is **38–75% less** for
equivalent per-firewall threat visibility — compelling cost justification for
clients who've been told they "need a SIEM."

---

## Technical Requirements

### Essentials tier (Central Partner API only)

1. **Sophos Central Partner credentials** — OAuth2 client ID + secret.
   Read-only Partner API scope. 5 minutes to generate in Central Partner.
2. **Your branding assets** — logo (PNG, min 600px wide) + hex color codes.

### Advanced / Enterprise tier (+ XGS device-side REST API)

3. **XGS REST API enabled** — on each firewall: Administration → Device
   Access → Local Service ACL → enable HTTPS API on the WAN/management
   interface. Enable REST API under System → Administration.
4. **API user account** — create a dedicated read-only admin account on each
   XGS for Technijian API access (separate from the main admin account).
   Technijian provides the public IP(s) to restrict access to.
5. **Network access** — Technijian infrastructure must be able to reach
   `https://<firewall-ip>:4444/`. Two options:
   - **S2S VPN** (recommended): permanent IPsec or SSL VPN tunnel from
     Technijian DC to client site — already configured for most managed clients
   - **Management port exposed**: restrict HTTPS management to Technijian
     IP range only (`/32` block) — acceptable for clients without S2S VPN
6. **Per-firewall credentials stored** in Technijian OneDrive key vault at
   `keys/sophos-xgs-<client_code>.md` — never committed to the repo.

### Microsoft Graph API permissions (alert routing emails)

Inherits from the existing pipeline — `Mail.Send` application permission
on the HiringPipeline-Automation app. Already configured.

### Supported product lines

| Product | Essentials | Advanced |
|---|---|---|
| Sophos XGS series | ✅ | ✅ |
| Sophos XG series | ✅ | ✅ (firmware v18+) |
| Sophos SG/UTM (Central-managed) | ✅ | ⚠️ Limited REST API |
| Sophos Firewall on AWS/Azure | ✅ | ✅ (if reachable) |

Sections requiring XGS REST API are automatically omitted for SG/UTM
tenants where the REST API is not available.

---

## API Endpoint Reference (XGS REST)

The device-side REST API runs at `https://<firewall>:4444/webconsole/APIController`
(legacy XML) and `https://<firewall>:4444/api/v1/` (modern JSON, XGS firmware 20+).

| Data | Endpoint | Format |
|---|---|---|
| IPS events | `/api/v1/monitor/ips` | JSON |
| ATP events | `/api/v1/monitor/atp` | JSON |
| Web filter logs | `/api/v1/monitor/webfilter` | JSON |
| Application control | `/api/v1/monitor/appfilter` | JSON |
| Traffic analytics | `/api/v1/monitor/interface` | JSON |
| Firewall rule hits | `/api/v1/config/network/firewall_rule` | JSON |
| Auth / admin log | `/api/v1/monitor/admin` | JSON |
| VPN tunnels | `/api/v1/monitor/ipsec` | JSON |
| SSL VPN sessions | `/api/v1/monitor/sslvpn` | JSON |
| System health | `/api/v1/monitor/services` | JSON |

All calls are GET with Bearer token auth (token obtained via
`POST /api/v1/login` with the read-only admin credentials). Tokens have
a configurable TTL (default 30 min); the pull script refreshes automatically.

---

## Delivery & Operations

| Item | Detail |
|---|---|
| **Alert detection cadence** | Hourly — alerts detected within 1 hour via Central Partner API |
| **XGS data pull cadence** | Every 4 hours (matches Meraki security events cadence; India 24×7) |
| **CP ticket creation** | Automatic on new alert detection (billable to client contract) |
| **Aging reminders** | Email to support@technijian.com if alert open > 24h without response |
| **Report delivery date** | 1st of each month by 9:00 AM local time |
| **Format** | Microsoft Word (.docx), white-labeled with your branding |
| **Historical access** | All prior reports available for download, 12-month default |
| **On-demand runs** | Available on Advanced and Enterprise tiers |
| **Setup time** | Essentials: 1 business day. Advanced/Enterprise: 2–3 days (per-firewall API setup) |
| **Data residency** | US-based processing; no tenant data retained after report generation |

---

## Frequently Asked Questions

**Q: What's the difference between Essentials and Advanced in plain English?**
Essentials tells you about alerts that Sophos has already classified and
surfaced to the dashboard. Advanced goes directly to the firewall log
engine and pulls the raw events — every IPS signature that fired, every
malware callback that was blocked, every web site that was denied —
before Sophos has had a chance to suppress or aggregate them.

**Q: Do clients need to do anything for Advanced tier?**
They need to approve a read-only API user on each firewall and allow
Technijian's IP to reach the management interface. We handle setup;
the client's part is a 15-minute configuration call per site.

**Q: Does the XGS REST API give you everything the firewall log viewer shows?**
Yes — the on-box API reads the same log database as the Central dashboard
and the local log viewer. You get the same data, just structured as JSON
for programmatic analysis instead of a paginated UI.

**Q: Can we white-label this?**
Yes. Your logo, your colors, your cover page. No "Powered by Technijian"
attribution.

**Q: What if a client has one XGS firewall and five Meraki APs?**
Sophos report covers the firewall layer; Meraki report covers wireless.
Bundle pricing applies — see Bundle section.

**Q: Does this replace a SIEM?**
For the firewall layer, Advanced provides comparable visibility to a SIEM
specifically scoped to Sophos events — IPS, ATP, web filter, traffic — at
a fraction of the cost. It does not correlate across multiple data sources
(endpoint, email, identity) the way a full SIEM does. Think of it as
"firewall SIEM" rather than "enterprise SIEM."

**Q: What isn't covered?**
Sophos Endpoint / Intercept X (covered under Huntress Endpoint Monitoring),
Sophos Email Security, on-premise Sophos UTM Manager (SUM) without Central
management, and multi-source correlation across identity/endpoint/email
(that's a SIEM project, priced separately).

---

## Competitive Comparison

| | **Sophos Reporting (Essentials)** | **Sophos Reporting (Advanced)** | Sophos Central (built-in) | Perch SIEM | Auvik |
|---|---|---|---|---|---|
| Branded DOCX deliverable | ✅ | ✅ | ❌ | ❌ | ❌ |
| Auto CP ticket on alert | ✅ | ✅ | ❌ | ❌ | ❌ |
| IPS per-signature events | — | ✅ | ✅ raw | ✅ | ❌ |
| ATP / malware callback detail | — | ✅ | ✅ raw | ✅ | ❌ |
| Web filter category analytics | — | ✅ | ✅ raw | ❌ | ❌ |
| Traffic analytics | — | ✅ | ✅ raw | Partial | ✅ |
| Per-user threat activity | — | ✅ | ✅ raw | Partial | ❌ |
| Automated monthly delivery | ✅ | ✅ | ❌ | ❌ | ❌ |
| White-label | ✅ | ✅ | ❌ | ❌ | ❌ |
| Bundles with M365 / Meraki | ✅ | ✅ | n/a | ❌ | ❌ |
| Public per-tenant pricing | ✅ | ✅ | Free | ~$300–800/site | ~$29/device |
| MSP volume discount | ✅ | ✅ | n/a | Contact sales | Contact sales |

---

## One-Pager Summary (designer-ready copy blocks)

### Headline
**Full firewall visibility. Automatic tickets. Monthly report on the 1st.**

### Sub-headline
IPS signatures, malware callbacks, web filter violations, and VPN events —
pulled directly from your Sophos XGS, classified automatically, and
delivered as a branded monthly report. At a fraction of SIEM cost.

### Three value pillars

**See everything your firewall sees.**
The Sophos Central dashboard shows you alerts after they've been filtered
and summarized. We pull directly from the XGS log engine — every IPS
signature, every ATP detection, every policy violation — so nothing is
missed between syncs.

**Turn alerts into billable tickets automatically.**
Every new Sophos alert creates a Client Portal ticket within 1 hour,
billable against the client's contract, assigned to your India team.
If the alert ages past 24 hours without a response, a reminder email fires.
You stop losing billable work.

**SIEM-quality data without SIEM-level cost.**
Competitive MSSP threat monitoring runs $300–$800/site/month. Advanced
at $199/month gives you equivalent firewall-layer visibility — IPS, ATP,
web filter, user activity — white-labeled with your brand, delivered as
a Word doc your client can actually read.

### Pricing snapshot (one-pager callout box)

```
Starting at $99/month per Sophos tenant

Essentials (Central API)       $99/mo    Alerts, inventory, connectivity
Advanced  (+ XGS REST API)    $199/mo    + IPS/IDS, ATP, web filter, traffic
Enterprise (6+ firewalls)     $299/mo    Multi-site, full features, SLA

Annual plans save 17%
Bundle with Meraki: save 10%
Bundle with M365: save 10%
Bundle all three: save 15%

No contracts on monthly plans.
Setup in 1–3 business days.
```

### Call to action options
- "Get your first report free — no credit card required"
- "Start your 30-day trial"
- "See a sample Advanced report" (link to redacted sample PDF)
- "Book a 15-minute demo"

### Contact / footer
[Your company name] · [website] · [email] · [phone]
Sophos Gold / Platinum Partner · Microsoft Solutions Partner · Cisco Meraki Partner

---

*Document version: 2.0 — 2026-04-30*
*v1.0 covered Central Partner API only (Essentials tier). v2.0 adds Advanced/Enterprise*
*tiers using XGS device-side REST API for full on-box log access.*
*Pricing subject to change; existing subscribers grandfathered at signup price.*
