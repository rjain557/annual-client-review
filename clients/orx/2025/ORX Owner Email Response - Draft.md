# Draft Email Response to ORX Owner

---

**Subject:** RE: IT Cost Optimization — Analysis & Recommendations

Hi [Owner Name],

Thank you for raising this — it's exactly the kind of strategic conversation we want to be having with you. I've gone through the full 2025 annual review data to build a concrete picture of where the $293K is going and where we can meaningfully optimize.

One important factor that shapes every recommendation: **ORX operates under HIPAA.** This means certain costs — dual-layer endpoint protection, dev/prod server segmentation, email archiving retention, redundant domain controllers — are compliance-mandated and can't simply be cut. I've built all the numbers below with that constraint in mind.

Here's the breakdown across your four focus areas:

---

### 1. Infrastructure — $4K–$8K savings potential

Your March 2026 baseline is **25 servers** (down from 27 — VLAN14 and OPSPRB were already decommissioned). Of the remaining 25, most are HIPAA-required: dev/prod SQL separation (SQL-01/02 production, SQL-03 dev), redundant AD controllers, separate app/IIS environments, and the OXPLIVE/OXPTEST CRM pair.

**What we can consolidate:**

- **VDI servers (6 → 3):** You have 5 VDI hosts + 1 golden image but only 2–4 active VDI licenses. Consolidating to 2 active + 1 golden image saves ~$1,800/yr.
- **JRMEDSVR01:** Needs workload review — if legacy/idle, decommission for ~$1,200–$1,800/yr.
- **Storage tiering:** 18TB backup at $50/TB can be moved to cold tier for older backups (HIPAA requires retention, not instant access). Replicated storage at $100/TB — verify all 7TB needs real-time replication. Savings: $2,400–$4,800/yr.

**What we cannot consolidate (HIPAA):** SQL servers (dev/prod segmentation), AD controllers (availability), App/IIS pairs, file server redundancy, CRM environments.

### 2. Security — Compliance Upgrade, Not Cost Cut

I want to be direct: **security is not the right place to find savings under HIPAA.**

- **CrowdStrike + Huntress ($14,100/yr): KEEP BOTH.** These are complementary, not redundant. CrowdStrike provides automated EDR and threat intelligence. Huntress adds human-managed threat hunting that catches what automation misses. For a healthcare org handling ePHI, dual-layer endpoint protection is defense-in-depth best practice. A single healthcare breach averages $10.9M (IBM 2025). This $14K/yr is compliance insurance.
- **Cisco Umbrella / Secure Internet → CloudBrink:** These are actually the same DNS filtering service billed as two components (per-device + platform = $7,580/yr combined). We're migrating to CloudBrink to take OXPLive off direct internet access for HIPAA compliance. Cost should be comparable — this is a compliance improvement, not a savings play.
- **Pen testing ($756/yr):** Required for HIPAA risk analysis. Non-negotiable at this price.
- **Anti-spam ($6,936/yr):** PHI exposure vector #1 is email. Third-party anti-spam stays on all mailboxes.

### 3. Dev & Advisory Separation — $10K–$31K savings potential

This is your highest-impact area. CTO + Dev currently runs $64K/yr (22% of total spend), and the biggest issue is that dev work is mixed into support tickets, making it impossible to evaluate either one independently.

**CTO Advisory: 15 hrs/mo → 8 hrs/mo**

Important to note: reducing to 8 hours moves the rate from $225/hr (volume) back to the standard $250/hr. The savings come from fewer committed hours, not a lower rate.

| | Current | Proposed |
|---|---|---|
| Hours/month | 15 | 8 |
| Rate | $225/hr | $250/hr |
| Monthly | $3,375 | $2,000 |
| With typical 2 hrs/mo overage | ~$3,375 | ~$2,500 |

Post-Q1 2025, actual CTO usage averaged ~10 hrs/mo. Realistic savings: **$6,700–$16,500/yr** depending on overage frequency.

**Development: Restructured Billing Model**

We're proposing two tracks to give you full visibility and budget control:

**Track 1 — Booked offshore development (tiered volume pricing):**

| Monthly Hours | Rate |
|---|---|
| Up to 40 hrs | $45/hr |
| 40–80 hrs | $40/hr |
| 80–120 hrs | $35/hr |

Rate tiers scale based on the average actual hours from the previous 6-month billing cycle. More committed volume = lower rate. Each project will have a **project ticket with child tickets** for each phase (GSD format), with **end-of-week (EOW) status emails** reporting week-to-date and month-to-date hours.

**Track 2 — Proposal-based work (fixed price):**
Fixed-price engagements at an effective $150/hr rate, which covers unforeseen hours and project risk. Appropriate for defined deliverables with clear scope.

At the current 2025 average of ~24 hrs/mo offshore, the tiered model projects to **~$13K/yr** vs. the $27.7K spent in 2025 — a significant reduction driven by eliminating surprise overage and proper cycle-based rate setting.

### 4. Licensing & Backup — $11K savings potential

**Quick wins (this month):**

- 13 unused M365 licenses across Standard, Basic, and Power BI — reclaim for **$1,824/yr**
- 15 Standard users who only use web/mobile can downgrade to Basic — **$1,404/yr**
- 1 Copilot seat at $360/mo ($4,320/yr) — evaluate ROI and confirm BAA coverage

**Backup & archiving (HIPAA-constrained):**

HIPAA requires 6-year retention, so we can't aggressively cut archiving. Conservative audits:
- Email archiving 142 → 120 (non-PHI mailboxes only): **$660/yr**
- Veeam 365 199 → 175 (shared/inactive without PHI): **$720/yr**
- Server backup and SPLA tracking server consolidation: **~$1,800/yr**
- SSL wildcard covering individual certs: **$400/yr**

### A Note on Overnight Hours

I want to flag that the current overnight offshore model ($15/hr) is already ORX's primary cost optimization lever. Those 1,263 overnight hours aren't "extra" — they're deliberately routing non-urgent work (patch management, monitoring alerts, scheduled maintenance) to the lowest possible rate. Cutting overnight hours would push that work to the $30/hr daytime shift, **increasing** costs. This model is working as designed.

---

### Summary

| Phase | Timeline | Annual Savings | Running Spend |
|---|---|---|---|
| Phase 1: Quick wins (licensing + backup audits) | Month 1 | ~$10K | $283K (3%) |
| Phase 2: CTO + Dev restructuring + infra | Months 2–6 | ~$16K–$41K | $242K–$267K (9–18%) |

### On the 35–50% Target

I want to be transparent about the gap. Under HIPAA, roughly **$64K/yr is a compliance floor** — dual EDR, DNS filtering, dev server segmentation, AD redundancy, email archiving, anti-spam, pen testing, and the overnight model that's already saving money. On top of that, core managed services (monitoring, RMM, backup, patching) at ~$32K/yr are operational necessities for 136 users.

Getting to 18% (~$242K) is achievable within 6 months through the advisory/dev restructuring and infrastructure optimization. Beyond that, further reductions would come from continued optimization of the dev billing model as volume scales into lower rate tiers, and ongoing quarterly license audits to prevent waste accumulation.

**I recommend we schedule a call to walk through the detailed analysis.** The Phase 1 quick wins ($10K) can start immediately with no service disruption, and the CTO/dev restructuring can begin as soon as we align on the new billing model.

What works for a 30-minute call this week?

Best regards,
[Your Name]
Technijian Inc.

---

*Attachment: ORX Cost Optimization Analysis (detailed breakdown with HIPAA compliance annotations)*
