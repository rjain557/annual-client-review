# ORX Cost Optimization Analysis
## Response to 35–50% IT Spend Reduction Request

**Prepared by:** Technijian Inc.
**Date:** March 5, 2026
**Current Annual Spend:** $292,988
**Target Range:** $146,000–$191,000 (35–50% reduction)
**Compliance Framework:** HIPAA — all recommendations validated against HIPAA Security Rule requirements
**Hosting:** Technijian Data Center (no cloud migration planned)

---

## Executive Summary

After reviewing the full 2025 annual data and applying HIPAA compliance constraints, we've identified **$26K–$52K in actionable savings (9–18%)** through advisory restructuring, development billing optimization, licensing right-sizing, and modest infrastructure consolidation.

Key factors limiting deeper cuts: HIPAA mandates dual-layer endpoint protection, dev/prod server segmentation, email archiving retention, and layered email security. The overnight offshore model ($15/hr) is already ORX's primary cost optimization lever — it routes non-urgent work (patching, monitoring, maintenance) to the lowest rate tier. Cutting overnight hours would increase daytime costs.

---

## Current Spend Breakdown

| Category | Annual | % of Total |
|---|---|---|
| IT Support Labor | $53,485 | 18.3% |
| CTO Advisory | $36,688 | 12.5% |
| Software Development | $27,659 | 9.4% |
| Cloud Hosting (Compute/Storage) | $54,962 | 18.8% |
| Security & Endpoint (CrowdStrike + Huntress) | $14,080 | 4.8% |
| Backup & Archiving | $13,801 | 4.7% |
| Monitoring & RMM | $9,237 | 3.2% |
| M365 & SPLA Licensing | $30,461 | 10.4% |
| Email Security (Anti-Spam + DMARC) | $6,377 | 2.2% |
| Network & Firewall | $6,120 | 2.1% |
| VoIP / Telephony | $5,919 | 2.0% |
| DNS Filtering (Cisco Umbrella / Secure Internet) | $7,580 | 2.6% |
| Pen Testing | $1,981 | 0.7% |
| SSL/Domains/Other Licensing | $4,313 | 1.5% |
| Hardware & One-Time | $24,165 | 8.2% |
| **TOTAL** | **$292,988** | **100%** |

*Note: Cisco Umbrella and Secure Internet are the same DNS filtering service billed as two components (per-device agent + platform fee). Combined: $7,580/yr. Previously reported as separate line items.*

---

## HIPAA Compliance Constraints

| HIPAA Requirement | Impact on Cost Optimization |
|---|---|
| **§164.312(c) — Integrity Controls** | Dev/prod environment segmentation must be maintained; dev SQL and app servers cannot be merged with production |
| **§164.310(a)(2)(ii) — Facility Security** | Redundant AD domain controllers required for availability of access controls |
| **§164.312(a)(1) — Access Control** | RDP CALs must cover all users accessing ePHI systems |
| **§164.312(e)(1) — Transmission Security** | Layered email security (anti-spam) must remain on all mailboxes handling PHI |
| **§164.312(c)(1) — Audit Controls** | Email archiving retention period: minimum 6 years; aggressive reduction not advisable |
| **§164.308(a)(1)(ii)(A) — Risk Analysis** | Dual EDR (CrowdStrike + Huntress) provides defense-in-depth; removing a layer increases residual risk |
| **§164.308(a)(6) — Contingency Plan** | Backup coverage must include all systems processing/storing ePHI |
| **§164.312(d) — Authentication** | Pen testing validates access controls — must be maintained |

---

## Area 1: Infrastructure Consolidation

**Current State (March 2026):** 25 servers (down from 27 in Dec — VLAN14 and OPSPRB decommissioned), hosted in Technijian DC
**Current Cost:** $54,962/yr ($4,580/mo)

### Compute & Storage Breakdown

| Resource | Qty | Rate | Monthly |
|---|---|---|---|
| Production Storage | 7 TB | $200/TB | $1,400 |
| Cloud VM vCores | 176 | $6.25/core | $1,100 |
| Backup Storage | 18 TB | $50/TB | $900 |
| Replicated Storage | 7 TB | $100/TB | $700 |
| Cloud VM Memory | 360 GB | $0.63/GB | $227 |
| Shared Bandwidth | 1 | $15.00 | $15 |
| **Total** | | | **$4,342** |

### HIPAA Segmentation — Servers That Must Remain Separate

| Server Group | Servers | Reason |
|---|---|---|
| Production SQL | SQL-01, SQL-02 | Production ePHI database workloads |
| Dev/Test SQL | SQL-03 | HIPAA-required dev/prod segmentation |
| Production App | APP-01 or APP-04 | Production application serving |
| Dev/Test App | APP-01 or APP-04 | Separate dev environment for compliance |
| Domain Controllers | AD-03, AD-04 | HIPAA availability — redundant access controls |
| Production IIS | IIS1, IIS2 | Web-facing production (HA pair) |
| File Servers | FS-01, FS-02 | ePHI document storage + redundancy |
| Terminal Servers | TS-03, TS-04 | User access to applications |
| 3CX / VoIP | 3CX-01 | Phone system |
| Production CRM | OXPLIVE | OXPLive production |
| Test CRM | OXPTEST | Dev/test environment |

### Consolidation Opportunities

1. **VDI Consolidation (5 VDI hosts + 1 golden image → 3 total):** Only 2–4 active VDI licenses. Consolidate to 2 active hosts + 1 golden image.
   - **Savings:** ~2 servers decommissioned = **~$150/mo ($1,800/yr)**

2. **JRMEDSVR01 Review:** Verify this server's workload. If legacy or idle, decommission.
   - **Potential savings:** $100–$150/mo ($1,200–$1,800/yr)

3. **Storage Tier Optimization:**
   - 18 TB backup at $50/TB = $900/mo — evaluate cold storage tier for backups older than 90 days (HIPAA requires retention, not instant access)
   - 7 TB replicated at $100/TB — confirm all 7 TB requires real-time replication vs. daily sync
   - **Potential savings:** $200–$400/mo ($2,400–$4,800/yr)

**Infrastructure Savings Summary:**

| Action | Timeline | Annual Savings |
|---|---|---|
| VDI consolidation (6 → 3) | 1–3 months | $1,800 |
| JRMEDSVR01 review | 1 month | $0–$1,800 |
| Storage tier optimization | 1–3 months | $2,400–$4,800 |
| **Total Infrastructure** | | **$4,200–$8,400** |

*Note: 2 servers (VLAN14, OPSPRB) already decommissioned between Dec 2025 and Mar 2026. March baseline is 25 servers.*

---

## Area 2: Security Stack

**Current State:** Dual EDR + DNS filtering + pen testing
**Current Cost:** $14,080 (endpoint) + $7,580 (DNS filtering) + $1,981 (pen testing) = **$23,641/yr**

### Current Security Layers

| Tool | Endpoints | Monthly | Annual | Function |
|---|---|---|---|---|
| CrowdStrike (Desktop + Server) | 84 | $760 | $9,120 | Automated EDR, threat detection, AV |
| Huntress (Desktop + Server) | 83 | $415 | $4,980 | Human-managed threat hunting, EDR |
| Cisco Umbrella / Secure Internet | 80 + platform | $632 | $7,580 | DNS security, web filtering |
| Pen Testing | 18 IPs | $63 | $756 | Continuous pen testing |
| **Total** | | **$1,870** | **$22,436** | |

*Note: Cisco Umbrella and Secure Internet are the same service — per-device agent ($316/mo) + platform subscription ($312/mo). Previously counted as two separate services.*

### HIPAA-Compliant Recommendations

**CrowdStrike + Huntress: KEEP BOTH.**
Defense-in-depth is a HIPAA best practice and a compliance necessity. CrowdStrike provides automated EDR and threat intelligence; Huntress adds a human-managed threat hunting layer that catches what automation misses. For a healthcare org handling ePHI, dual-layer endpoint protection is non-negotiable. A single healthcare breach averages $10.9M (IBM 2025). The $14,100/yr is compliance insurance.

**Cisco Umbrella / Secure Internet → CloudBrink Migration:**
The current Umbrella/SI service ($7,580/yr) is being migrated to CloudBrink. This is a **compliance upgrade**, not a cost play — CloudBrink enables taking OXPLive (ORX's CRM) off direct internet access for HIPAA compliance. Cost will depend on CloudBrink per-seat pricing but should be comparable. Any cost delta (positive or negative) will be reflected in the next billing cycle.

**Pen Testing ($756/yr): KEEP.** Required for HIPAA risk analysis (§164.308(a)(1)(ii)(A)).

**Security Savings Summary:**

| Action | Annual Savings |
|---|---|
| CloudBrink migration (Umbrella/SI replacement) | Cost-neutral (compliance upgrade) |
| **Total Security** | **$0** |

*Security is not the right place to find cost savings under HIPAA. The current $23.6K/yr protects against breach costs that would dwarf the annual IT spend.*

---

## Area 3: Dev & Advisory Restructuring

**Current State:** CTO and Dev work mixed into the support contract
**Current Cost:** $64,347/yr (22% of total spend)

### 2025 Breakdown

| Role | Contracted | Overage | Total | Hours | Eff. Rate |
|---|---|---|---|---|---|
| CTO Advisory | $30,375 | $6,313 | $36,688 | 160 | $229/hr |
| Software Dev | $14,850 | $12,809 | $27,659 | 285 | $97/hr |
| **Total** | **$45,225** | **$19,122** | **$64,347** | **445** | **$145/hr** |

### A. CTO Retainer Restructuring: 15 hrs/mo → 8 hrs/mo

| | Current | Proposed |
|---|---|---|
| Monthly Hours | 15 | 8 |
| Hourly Rate | $225/hr (volume) | $250/hr (standard) |
| Monthly Cost | $3,375 | $2,000 |
| Overage Rate | $250/hr | $250/hr |
| Annual Contracted | $40,500 | $24,000 |

**Important:** Reducing from 15 to 8 hours eliminates the volume discount — the rate goes from $225/hr back to the standard $250/hr. Savings come from fewer contracted hours, not from rate reduction.

Post-Q1 2025, actual CTO usage averaged ~10 hrs/mo. At 8 contracted + ~2 overage/mo:
- Projected annual: $24,000 + ($250 × 2 × 12) = **$30,000/yr**
- vs. current: $36,688 (contracted + overage)
- **Net savings: ~$6,700/yr**

If CTO usage stays at or below 8 hrs/mo (no overage):
- **Savings: $16,500/yr**

**Realistic range: $6,700–$16,500/yr**

### B. Development Billing Restructuring

Currently, 374 hours of dev work is buried in support tickets — making IT support costs impossible to evaluate independently. The restructuring separates dev into two tracks:

**Track 1: Booked Development (Offshore, Tiered Volume Pricing)**

| Monthly Hours | Rate | Monthly Cost |
|---|---|---|
| Up to 40 hrs | $45/hr | Up to $1,800 |
| 40–80 hrs | $40/hr | $1,600–$3,200 |
| 80–120 hrs | $35/hr | $2,800–$4,200 |

- Rate tier is set based on the **average actual hours from the previous 6-month billing cycle**
- As development scales, the per-hour rate decreases — incentivizing committed volume
- 2025 offshore dev averaged ~23.75 hrs/mo → starts at $45/hr tier
- If volume increases to 40+ hrs/mo in the next cycle, rate drops to $40/hr

**Track 2: Proposal-Based Development (Fixed Price)**

- Fixed-price engagements scoped per project
- Billed at **$150/hr effective rate** to cover unforeseen hours and project risk
- Appropriate for defined deliverables with clear acceptance criteria

**Development Project Management:**

- Each project gets a **project ticket with child tickets** for each phase (GSD format)
- **End-of-week (EOW) status emails** with:
  - Week-to-date (WTD) hours worked
  - Month-to-date (MTD) hours worked
  - Phase progress and next steps
- Full visibility into dev spend separate from IT support

**Development Cost Projection:**

| Scenario | Monthly | Annual | vs. 2025 ($27,659) |
|---|---|---|---|
| Current volume (24 hrs/mo @ $45) | $1,080 | $12,960 | −$14,699 (−53%) |
| Growth (50 hrs/mo @ $40 blended) | $2,000 | $24,000 | −$3,659 (−13%) |
| High volume (90 hrs/mo @ $35 blended) | $3,150 | $37,800 | +$10,141 (+37%) |

*Note: 2025 dev included $12,809 in overage. The tiered model eliminates surprise overage by setting rates based on actual usage patterns from the prior cycle.*

**Dev/Advisory Savings Summary:**

| Action | Annual Savings |
|---|---|
| CTO retainer reduction (15 → 8 hrs, rate to $250) | $6,700–$16,500 |
| Dev restructuring (tiered + visibility) | $3,600–$14,700 |
| **Total Dev/Advisory** | **$10,300–$31,200** |

---

## Area 4: Licensing & Backup Optimization

**Current State:** $34,774 recurring + $13,801 backup = $48,575/yr
**Focus:** M365 right-sizing, SPLA reduction, backup optimization within HIPAA retention rules

### M365 License Audit

| License | Seats | In Use | Unused | Monthly Waste |
|---|---|---|---|---|
| M365 Business Standard | 69 | 64 | 5 | $75/mo |
| M365 Business Basic | 78 | 72 | 6 | $43/mo |
| Power BI Pro | 18 | 16 | 2 | $34/mo |
| **Total Unused** | | | **13** | **$152/mo ($1,824/yr)** |

**Quick win: Reclaim 13 unused licenses → $1,824/yr savings**

### M365 Tier Optimization

Not all 64 Standard users may need desktop Office apps. If some only use web/mobile:
- Each downgrade from Standard ($15/mo) to Basic ($7.20/mo) saves $7.80/mo
- If 15 users can downgrade: **$1,404/yr savings**

### SPLA & Server Licensing

| License | Annual | Tied To |
|---|---|---|
| RDP/User CAL | $5,520 | 50 CALs for terminal server access |
| Server Std 2-Core | $5,418 | 86 cores (server licensing) |
| SQL Server Standard | $222 | 1 license |
| **Total** | **$11,160** | |

- **RDP CALs:** Under HIPAA, all users accessing ePHI systems must have proper licensed access. If VDI drops from 6→3 hosts, CALs may reduce from 50→45. **Savings: $552/yr**
- **Server cores:** With 25 servers (already down from 27) and VDI consolidation to 23, cores reduce from 86→76. **Savings: $525/yr**

### Copilot Evaluation

- 1 seat at $360/mo ($4,320/yr) — started Sep 2025
- **HIPAA concern:** Confirm Microsoft Copilot is covered under your existing BAA. Microsoft includes Copilot in their BAA as of 2025, but verify the specific SKU.
- **ROI question:** Is this single seat delivering $360/mo in productivity?
- **Recommendation:** If BAA-covered and ROI-justified, keep. Otherwise cancel. **Potential savings: $4,320/yr**

### Backup & Archiving (HIPAA-Constrained)

| Service | Count | Rate | Monthly | Annual |
|---|---|---|---|---|
| Veeam 365 Backup | 199 | $2.50 | $498 | $5,970 |
| Image Backup (Servers) | 27 | $15.00 | $405 | $4,860 |
| Email Archiving | 142 | $2.50 | $355 | $4,260 |
| **Total** | | | **$1,258** | **$15,090** |

**HIPAA retention rules limit aggressive cuts:**

- **Email Archiving:** HIPAA requires 6-year retention minimum. Former employees' archives must be preserved. Conservative reduction from 142→120 (remove only verified non-PHI mailboxes like generic aliases). **Savings: $660/yr**
- **Veeam 365 Backup:** Jumped from 128→199. Audit for shared/inactive mailboxes that don't contain PHI. Conservative reduction to 175. **Savings: $720/yr**
- **Image Backup:** Tracks server count. With decommissioning from 27→23: **Savings: $720/yr**

### Other Licensing

| Item | Annual | Recommendation |
|---|---|---|
| Sophos 1C-4G (Irvine) | $1,320 | Keep — perimeter security required |
| Edge Appliance (Irvine) | $1,200 | Review if SD-WAN covers this function |
| SSL Certificates | $843 | Consolidate: wildcard covers most subdomains |
| Domains | $177 | Keep — minimal cost |

**SSL Consolidation:** Wildcard cert (*.orthoxpress.com) covers most subdomains, but 7+ individual certs are also active ($843/yr). **Savings: ~$400/yr**

**Licensing & Backup Savings Summary:**

| Action | Annual Savings |
|---|---|
| Reclaim unused M365 licenses | $1,824 |
| Downgrade 15 Standard → Basic | $1,404 |
| Cancel Copilot (if no ROI) | $4,320 |
| Reduce RDP CALs (50 → 45) | $552 |
| Reduce Server cores (86 → 76) | $525 |
| Email archiving audit (142 → 120) | $660 |
| Veeam 365 audit (199 → 175) | $720 |
| Image backup (27 → 23) | $720 |
| SSL consolidation | $400 |
| **Total Licensing & Backup** | **$11,125** |

---

## Area 5: Additional Optimization Levers

### VoIP Audit

- 80 DID phone numbers at $3.60/mo = $3,456/yr
- Audit for unused DIDs — if 20 are inactive: **savings $864/yr**

### Overnight Offshore Model — Already Optimized

**The current overnight model is NOT a cost to cut — it IS ORX's primary cost optimization.**

| Shift | Rate | 2025 Hours | Annual Cost | Work Type |
|---|---|---|---|---|
| US Daytime (Offshore AH) | $30/hr | 840 | $25,200 | Same-day support, user-facing |
| US Overnight (Offshore NH) | $15/hr | 1,263 | $18,945 | Patch management, monitoring, maintenance |

The overnight shift deliberately routes non-urgent operational work — patch management failures, monitoring alerts, scheduled maintenance — to the $15/hr rate. This is 60% of all offshore hours at half the daytime rate. Reducing overnight hours would push this work to the $30/hr daytime shift, **increasing costs by up to $18,945/yr**.

### Anti-Spam / Email Security — HIPAA-Required

- 136 mailboxes at $4.25/mo = $6,936/yr
- **HIPAA constraint:** Email is the #1 PHI exposure vector. Third-party anti-spam provides a layer beyond M365's built-in EOP. Under HIPAA's defense-in-depth posture, this must remain on all mailboxes. **No savings.**

**Additional Savings Summary:**

| Action | Annual Savings |
|---|---|
| VoIP DID audit | $864 |
| **Total Additional** | **$864** |

---

## Consolidated Savings Summary

### Phase 1: Quick Wins (0–3 months)

| Action | Annual Savings |
|---|---|
| Reclaim 13 unused M365 licenses | $1,824 |
| Downgrade 15 Standard → Basic | $1,404 |
| Cancel Copilot (if no ROI) | $4,320 |
| Email archiving audit (142 → 120) | $660 |
| Veeam 365 audit (199 → 175) | $720 |
| SSL consolidation | $400 |
| VoIP DID audit | $864 |
| **Phase 1 Total** | **$10,192** |

### Phase 2: Contract & Infrastructure Restructuring (3–6 months)

| Action | Annual Savings |
|---|---|
| CTO retainer restructuring (15 → 8 hrs @ $250/hr) | $6,700–$16,500 |
| Dev billing restructuring (tiered + project-based) | $3,600–$14,700 |
| VDI consolidation (6 → 3) | $1,800 |
| JRMEDSVR01 review | $0–$1,800 |
| Storage tier optimization | $2,400–$4,800 |
| Reduce RDP CALs & Server cores | $1,077 |
| Image backup (27 → 23) | $720 |
| **Phase 2 Total** | **$16,297–$41,397** |

### Additional Ongoing Optimization (6+ months)

| Action | Annual Savings |
|---|---|
| Edge Appliance review (if SD-WAN covers) | $1,200 |
| Dev volume scaling into lower rate tiers | Variable |
| Quarterly license audits (prevent waste accumulation) | Variable |

---

## Overall Projection

| Scenario | Annual Savings | New Spend | % Reduction |
|---|---|---|---|
| **Phase 1 only** (quick wins) | $10,192 | $282,796 | **3%** |
| **Phase 1 + 2** (realistic target) | $26,489–$51,589 | $241,399–$266,499 | **9–18%** |

### Why 35–50% Is Extremely Difficult Under HIPAA

The gap between the 35–50% target and the realistic 9–18% comes from HIPAA-mandated costs that cannot be reduced:

| HIPAA-Protected Cost | Annual | Why It Can't Be Cut |
|---|---|---|
| Dual EDR (CrowdStrike + Huntress) | $14,100 | Defense-in-depth for ePHI endpoints |
| DNS Filtering (→ CloudBrink) | ~$7,580 | HIPAA transmission security + CRM isolation |
| Dev/test server infrastructure | ~$8,000 | Dev/prod segmentation required |
| AD redundancy (2 controllers) | ~$3,600 | Access control availability |
| Email archiving (core 120 users) | $3,600 | 6-year retention requirement |
| Anti-spam (all mailboxes) | $6,936 | PHI transmission security |
| Pen testing | $756 | Risk analysis requirement |
| Overnight offshore model | $18,945 | Already the lowest-cost lever (cutting it increases costs) |
| **Total HIPAA floor** | **~$63,500** | |

Additionally, core managed services (monitoring, RMM, backup, patching) at ~$32K/yr are operational necessities for a 136-user environment.

### Path to Further Savings Beyond Phase 2

Additional reductions beyond 18% can be achieved through:

1. **Dev volume scaling** — As development hours increase past 40 hrs/mo, the rate drops from $45 to $40/hr; past 80 hrs/mo it drops to $35/hr. Higher committed volume = lower cost per hour.

2. **Continued infrastructure optimization** — As servers age out and workloads evolve, further consolidation opportunities may emerge (e.g., Edge Appliance retirement if SD-WAN fully covers).

3. **Quarterly license audits** — Preventing waste accumulation by reviewing seats every quarter rather than annually.

---

## Recommended Approach

**Target: 15–18% reduction (~$245K) within 6 months.**

| Month | Action | Impact |
|---|---|---|
| Month 1 | Execute Phase 1 quick wins | −$10K/yr |
| Months 2–3 | Restructure CTO retainer (8 hrs @ $250) | −$7K–$17K/yr |
| Months 2–3 | Implement dev billing tiers + GSD project tracking | −$4K–$15K/yr |
| Months 3–6 | VDI consolidation + storage optimization | −$4K–$8K/yr |
| Ongoing | Quarterly license audits | Prevent waste |

### Cost Optimization vs. Risk Trade-offs

| Savings Tier | Annual Spend | Risk Level | HIPAA Impact |
|---|---|---|---|
| Conservative (Phase 1) | $283K | None | Fully compliant |
| Moderate (Phase 1+2) | $241K–$266K | Low | Compliant, advisory coverage reduced |

---

*Prepared for discussion — all figures based on 2025 actual spend data, March 2026 service inventory (25 servers), and HIPAA Security Rule requirements (45 CFR §164.308–312). Technijian DC hosting assumed throughout.*
