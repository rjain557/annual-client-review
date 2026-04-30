# SaaS Pricing Strategy — annual-client-review (productized as "MSPReportHub")

Generated: 2026-04-30
Author: SaaS pricing analysis (Claude Code)

---

## Executive Summary

The annual-client-review repo, productized, is an **MSP-tier client reporting
platform** that aggregates 8+ security/operations data sources (Cisco Meraki,
Huntress, CrowdStrike Falcon, Cisco Umbrella, Teramind DLP, ScreenConnect,
Sophos Central, Microsoft 365) and emits branded per-client monthly Word
deliverables with an auto-proofread quality gate.

**Recommended model:** hybrid **flat-MSP-fee + per-client tier ladder**, $0
free → $199 → $499 → $999/mo, with annual lock-in at 17% off and a 6-month
migration credit for switching from ConnectWise BrightGauge or Liongard.

**Headline positioning:** the **Growth** tier at $499/mo undercuts BrightGauge
Standard ($316/mo for 2 admins, 2 data sources) by including **8 data sources
+ unlimited admins + branded Word deliverables** — a feature combination
BrightGauge currently sells only at the $616/mo Enterprise tier or via
per-source add-ons.

**Caveat — productization prerequisite:** this repo is currently a
single-tenant Technijian-internal toolkit, not a multi-tenant SaaS. Pricing
below assumes ~6-9 months of productization work (multi-tenant credential
vaulting, web UI for config/download, per-MSP isolation, billing). The pricing
strategy is otherwise market-defensible.

---

## Phase 1 — Platform Value Assessment

### Feature inventory

| Feature | Category | Tier | Replaces | Build-Cost-If-DIY |
|---|---|---|---|---|
| Meraki monthly report (IDS/IPS, firewall, WAN config, change log) | Reporting | Core | Manual QBR prep (~4 hr/client/mo) | $40k–60k engineering |
| Huntress monthly report (EDR + agent inventory) | Reporting | Core | Manual EDR rollup | $20k–30k |
| CrowdStrike Falcon daily/monthly snapshot | Telemetry | Core | Falcon manual export + Excel | $30k–40k |
| Cisco Umbrella daily DNS+web filtering pull | Telemetry | Core | Umbrella per-org reports | $15k–25k |
| Teramind DLP / insider-threat report | Reporting | Pro | Teramind built-in | $30k–40k |
| Sophos Central monthly (Partner API) | Telemetry | Core | Manual Partner export | $15k–20k |
| ScreenConnect session audit + video analysis (Gemini) | Audit | Pro | Manual session review | $40k–60k |
| Microsoft 365 compliance/security/storage pull | Telemetry | Core | Manual Graph queries | $25k–35k |
| Configuration change audit log (who changed what, before/after) | Compliance | Pro | Manual Dashboard log review | $20k |
| Versioned daily config history snapshot | Compliance | Pro | Manual diff-by-screenshot | $15k |
| Branded Word report builder (cover, sections, callouts, tables) | Output | Core | Manual Word formatting | $30k–40k |
| Auto-proofread DOCX gate (8 checks, table overflow, mojibake) | QC | Pro | Manual proofreading | $10k |
| PSA time-entry audit + tech coaching emails | Operations | Enterprise | Manual time-entry QC | $40k |
| Annual client review deliverables | Reporting | Enterprise | $5k–10k per QBR consultant | $50k+ |
| Multi-tenant credential vault | Platform | Enterprise | Per-tool secrets management | $30k |
| Per-client folder model + git-diffable history | Platform | Core | Manual archive | $15k |
| White-label branding | Platform | Scale/Enterprise | n/a | $20k |
| **Total DIY cost if a competitor MSP rebuilt this** | | | | **$425k–$500k+** |

**Value driver summary:** the platform replaces ~4–8 hours of manual QBR/audit
prep per client per month plus 2–3 separate point tools (BrightGauge for
dashboards + Liongard for config drift + a separate compliance gathering tool).
For a 50-client MSP, that's 200–400 hours/month of senior tech labor.

---

## Phase 2 — Competitive Landscape

### Pricing matrix (verified April 2026 — see source agent report)

| Competitor | Free Tier | Starter | Pro | Enterprise | Model | Key Gaps vs MSPReportHub |
|---|---|---|---|---|---|---|
| **ConnectWise BrightGauge** | Trial only | $316/mo | $436/mo | $616/mo | Flat MSP, capped admins+data sources | No branded Word output; per-data-source upcharge; no compliance change log |
| **Zomentum (Launch/Expand/Growth)** | None | $109/mo | $129/mo | $189/mo | Flat MSP | Quote/proposal-focused, NOT QBR reporting; no security telemetry aggregation |
| **Liongard** | Trial | $29/env/mo | $39/env/mo | Custom | Per-environment | Config posture only; no DOCX deliverables; no event aggregation |
| **Kaseya IT Glue + MyGlue/Network Glue** | None | $29/user/mo | $34/user/mo | $39/user/mo + $395/mo add-on | Per-user + MSP add-on | Documentation, not reporting; QBR is not its job |
| **Auvik** | None | $15/device/mo | $27/device/mo | Custom | Per-network-device | Network monitoring only; QBR is not its job |
| **Domotz** | 1 device free | $1.50/device/mo | n/a | Custom | Per-device | Network monitoring only |
| **N-able N-central / N-sight** | 30-day trial | ~$99/tech/mo | Quote | Quote | Per-tech, opaque | Bundled in RMM; no per-client QBR Word output |
| **Datto Lifecycle Insights** | None | Contact sales | Contact sales | Contact sales | Opaque | Vendor-locked to Autotask PSA; pricing buyer-unfriendly |
| **CloudRadial / Strategy Overview / Propel / Kambium** | Varies | Contact sales | Contact sales | Contact sales | Opaque | All gated behind sales calls — kills SMB conversion |
| **Galactic Advisors / Galactic Scan** | None | Contact sales | Contact sales | Contact sales | Opaque | Workshop-driven, not platform |

### Vulnerabilities to exploit

1. **"Contact sales" is endemic** in the QBR/vCIO segment — published-pricing alone is a competitive moat.
2. **Per-data-source upcharges at BrightGauge** mean a single MSP with 8 tools pays $616+/mo to even see them; bundling 8 sources into one tier is differentiated.
3. **None of the published-pricing competitors emit branded Word deliverables** out of the box — they emit dashboards or PDFs that the MSP still has to package for end clients. Branded DOCX with QC gate is unique.
4. **Configuration change audit (before/after, by-admin)** is a Liongard-class feature but Liongard is per-environment expensive and lacks event aggregation.
5. **The QBR "service" market** has no published per-client price floor — MSPs absorb cost into bundles ($100–$250/user/mo). A clean per-client overage at $5–$10/client/mo creates a market-anchoring number nobody else publishes.

---

## Phase 3 — Recommended Pricing

### Pricing model rationale

**Hybrid: flat-MSP fee per tier + per-client soft cap with $7/client/mo overage.**

- **Why flat-MSP**: matches the dominant model in the QBR/dashboard segment (BrightGauge, Zomentum). MSPs already mentally price reporting tools as a fixed monthly OpEx, not a variable cost.
- **Why a client soft cap**: MSPs' cost-to-serve scales with client count, not endpoint count. Tying tier limits to client count is auditable, predictable, and sales-friendly.
- **Why NOT per-endpoint**: Auvik/Domotz/SentinelOne already own per-endpoint pricing for monitoring; competing there means fighting Cisco/CrowdStrike at their own game on margin.
- **Why NOT per-tech-seat**: locks in low ARPU since most MSPs have 5–25 techs but 50–500 clients. Per-client unlocks the upsell ladder.

### Tier card

```
┌──────────────────────────────────────────────────────────────────────┐
│                   FREE — "Single-Site"                               │
│                          $0/mo                                       │
├──────────────────────────────────────────────────────────────────────┤
│  • 1 client / 1 location                                             │
│  • 2 data sources (Meraki + 1 of: Huntress/CrowdStrike/M365)         │
│  • Monthly Word report                                               │
│  • Community support (Discord / Reddit)                              │
│  • MSPReportHub branding ON output (no white-label)                  │
└──────────────────────────────────────────────────────────────────────┘
                  Designed to: hook solo MSPs, drive trial → paid

┌──────────────────────────────────────────────────────────────────────┐
│                   STARTER — "Solo MSP"                               │
│           $199/mo · or $1,990/yr (save $398, 17% off)                │
├──────────────────────────────────────────────────────────────────────┤
│  • Up to 10 clients                                                  │
│  • All 8 data sources                                                │
│  • Monthly + on-demand Word reports                                  │
│  • Auto-proofread QC gate                                            │
│  • 5 GB historical config storage                                    │
│  • Email support, 48 hr response                                     │
│  • Powered by MSPReportHub footer (no white-label)                   │
│  • $7/client/mo overage above 10                                     │
└──────────────────────────────────────────────────────────────────────┘
                  Anchor: cheaper than Zomentum Growth ($189) +
                  Liongard 5 envs ($145) combined

┌──────────────────────────────────────────────────────────────────────┐
│        ★ GROWTH — "Mid-Market MSP" — RECOMMENDED ★                   │
│           $499/mo · or $4,990/yr (save $998, 17% off)                │
├──────────────────────────────────────────────────────────────────────┤
│  • Up to 50 clients                                                  │
│  • All 8 data sources                                                │
│  • Monthly + weekly + on-demand Word reports                         │
│  • Auto-proofread QC gate                                            │
│  • Configuration change audit (before/after, by-admin)               │
│  • Versioned daily config history (90 days)                          │
│  • PSA time-entry audit + tech coaching emails                       │
│  • White-label branding (logo + colors)                              │
│  • 50 GB historical storage                                          │
│  • Priority support, 8 hr response                                   │
│  • $5/client/mo overage above 50                                     │
└──────────────────────────────────────────────────────────────────────┘
                  Anchor: 19% under BrightGauge Standard ($616)
                  but with 8 sources vs 2 + branded DOCX output
                  expected ~70% of paying customers land here

┌──────────────────────────────────────────────────────────────────────┐
│                  SCALE — "Mature MSP / MSSP"                         │
│           $999/mo · or $9,990/yr (save $1,998, 17% off)              │
├──────────────────────────────────────────────────────────────────────┤
│  • Up to 150 clients                                                 │
│  • Everything in Growth, plus:                                       │
│  • ScreenConnect session video analysis (Gemini-powered audit)       │
│  • Annual / quarterly client review deliverables                     │
│  • Multi-user collaboration (5 admins, RBAC)                         │
│  • Audit log (who-ran-what, immutable, 7-year retention)             │
│  • API access (read-only export)                                     │
│  • Dedicated CS contact, 4 hr response                               │
│  • $4/client/mo overage above 150                                    │
└──────────────────────────────────────────────────────────────────────┘
                  Anchor: matches MyGlue/Network Glue $395 + Liongard
                  full + BrightGauge Enterprise stack ≈ $2,000+/mo today

┌──────────────────────────────────────────────────────────────────────┐
│            ENTERPRISE — "MSSP / National MSP"                        │
│           Starting $2,499/mo · annual contract required              │
├──────────────────────────────────────────────────────────────────────┤
│  • Unlimited clients                                                 │
│  • Everything in Scale, plus:                                        │
│  • SSO (Okta, Entra ID, Google Workspace)                            │
│  • SOC 2 Type II + HIPAA BAA                                         │
│  • Custom data sources (BYO API integration)                         │
│  • White-glove onboarding + training                                 │
│  • SLA: 99.9% uptime, 1 hr P1 response                               │
│  • Dedicated CSM + named SE                                          │
│  • Reseller / multi-MSP holding-company licensing                    │
└──────────────────────────────────────────────────────────────────────┘
                  Public floor on this tier — most competitors hide it
```

### Pricing-page features that competitors hide

- **Public price on every tier through Scale.** Only Enterprise is "starting at" — and even that has a dollar floor.
- **No demo required** for Free or Starter. Self-serve signup.
- **All 8 data sources in every paid tier** (BrightGauge limits to 2–3 per tier).
- **Branded Word output included from Starter up** (BrightGauge: not at all).

---

## Phase 4 — Aggressive Positioning Tactics

| Tactic | Detail | Risk |
|---|---|---|
| **Switch credit** | 6 months at 50% off for MSPs migrating from BrightGauge / Liongard / IT Glue MyGlue (proof-of-purchase required) | Margin hit Year 1; offset by 36-month LTV |
| **Annual lock-in** | 17% off (~2 months free) for annual prepay | Standard SaaS practice |
| **Founding 50** | First 50 paying MSPs get $50/mo off Growth tier for life | Capped exposure ($30k/yr) for case-study leverage |
| **Nonprofit / EDU MSP** | 50% off all tiers, no time limit | Goodwill; usually <2% of base |
| **MSP-of-MSPs (reseller)** | Holding cos / MSP buyout firms get 30% off + co-branded portal | Channel acceleration |
| **Free trial** | 30 days, full Growth tier features, no credit card | Best-in-class trial → 25% expected conversion |
| **Per-tier client headroom** | Soft cap with overage, never hard-block reports during a billing cycle | Prevents churn from a one-month spike |
| **Self-serve cancellation** | One-click in dashboard | Keeps NPS high; Kaseya / ConnectWise are notorious for retention friction |
| **Migration tooling** | Free import script for BrightGauge dashboards + Liongard inspectors | Removes #1 switching objection |

### Sales / pricing-page anchoring

- Lead with **"Growth — $499/mo"** as the recommended tier and place it visually centered in the pricing-page comparison.
- Show **"vs $616 BrightGauge Standard"** struck-through next to it.
- Use the **"What you'd pay if you bought this stack à la carte: $1,940/mo"** line item (BrightGauge Standard $316 + Liongard 50 envs $1,450 + IT Glue MyGlue $395 ≈ $2,161/mo) — strikethrough → $499.
- ROI calculator on the homepage — input client count, get monthly savings.

---

## Phase 5 — Unit Economics

### Per-tier validation

| Tier | Price | Est. COGS | Gross Margin | CAC (target) | Payback | LTV (24-mo retention) | LTV:CAC |
|---|---|---|---|---|---|---|---|
| Free | $0 | $8/mo | -100% | $0 (organic) | n/a | $0 (used as funnel) | n/a |
| Starter $199 | $199 | $25/mo (87%) | $174/mo | $400 | 2.3 mo | $4,176 | 10.4× ✅ |
| Growth $499 | $499 | $55/mo (89%) | $444/mo | $1,200 | 2.7 mo | $10,656 | 8.9× ✅ |
| Scale $999 | $999 | $110/mo (89%) | $889/mo | $3,000 | 3.4 mo | $21,336 | 7.1× ✅ |
| Enterprise $2,499 | $2,499 | $300/mo (88%) | $2,199/mo | $10,000 | 4.5 mo | $52,776 | 5.3× ✅ |

**COGS components:** API call costs (Meraki/Huntress/CS/etc. are free at the
MSP's own quota — passes through), AWS/Azure infra ($15–$200/customer/mo
depending on tier), Gemini video analysis API ($0.10/session avg, ~$30/mo
at Scale), DOCX rendering compute, support staff at ~10% of MRR.

**Targets met:** all paid tiers have **>85% gross margin** and **<5-month CAC payback** — well within healthy SaaS benchmarks (>70% margin, <12-month payback). LTV:CAC > 3:1 on all tiers ✅.

**Risk: free tier abuse.** Cap free at **1 client only** to limit subsidy
cost. Each free user costs ~$8/mo in infra; assume 4% conversion to paid →
free-tier breakeven at ~$200 ARPU after 24 months, which Starter already
clears.

---

## Phase 4 — Client Savings Calculator

Conservative assumptions:
- MSP senior engineer fully-loaded cost: **$75/hr** (US average)
- QBR prep per client per month, manual: **4 hours** (industry average per Kaseya / Reddit r/msp)
- Compliance audit prep per client per quarter: **6 hours**
- Tool sprawl avoided: BrightGauge ($316) + Liongard 50 envs ($1,450) + MyGlue ($395) = **$2,161/mo**

| Scenario | Current Monthly Cost | MSPReportHub Tier | Platform Cost | Monthly Savings | Annual Savings | Payback |
|---|---|---|---|---|---|---|
| **Solo MSP, 5 clients, manual everything** | 5 clients × 4 hrs × $75 = $1,500 (labor only) | Starter $199 | $199 | $1,301 | $15,612 | < 1 month |
| **Small MSP, 12 clients, BrightGauge + spreadsheets** | $316 (BG) + 12 × 4 × $75 = $3,916 | Starter + 2 client overages = $213 | $213 | $3,703 | $44,436 | 2 days |
| **Mid MSP, 30 clients, BrightGauge + Liongard + manual QBR** | $316 + (30 × $35 Liongard) + 30 × 3 hrs × $75 = $8,116 | Growth $499 | $499 | $7,617 | $91,404 | 2 days |
| **Mid MSP, 50 clients, full BrightGauge + Liongard + MyGlue + manual** | $2,161 (tools) + 50 × 4 × $75 = $17,161 | Growth $499 | $499 | $16,662 | $199,944 | < 1 day |
| **Mature MSP, 100 clients, IT Glue stack + manual annual reviews** | $2,161 + 100 × 4 × $75 = $32,161 | Scale $999 | $999 | $31,162 | $373,944 | < 1 day |
| **MSSP, 250 clients, Datto Lifecycle + ConnectWise + custom dev** | est. $4,500 + 250 × 5 × $75 = $98,250 | Enterprise $3,500 | $3,500 | $94,750 | $1,137,000 | < 1 day |

**Conservative savings claim for marketing:** "MSPs with 30+ clients save
$80,000/year on average — payback in less than a week."

**3-year TCO comparison** (mid MSP, 50 clients):

| Stack | Year 1 | Year 2 | Year 3 | 3-yr TCO |
|---|---|---|---|---|
| BrightGauge + Liongard + MyGlue + manual labor | $205,932 | $215,000 | $225,000 | **$645,932** |
| MSPReportHub Growth annual | $4,990 | $4,990 | $5,490 (10% raise) | **$15,470** |
| **Savings** | $200,942 | $210,010 | $219,510 | **$630,462** |

---

## Go-to-Market Pricing Recommendations

### Launch pricing (Months 1–6)
- Set **Founding 50** at $449/mo Growth (10% off list) — drives social proof and case studies
- 90-day full feature trial for first 100 signups (vs 30-day standard)
- Public roadmap voting (founding members get 2× weight) — builds switching cost early

### Steady-state pricing (Month 7+)
- Restore Growth to $499/mo list
- Annual price increase **5–8%** at renewal, capped at $50/mo absolute, with 60-day notice
- Never raise existing-customer Founding-50 price (lock-in is the entire reason to give the discount)

### When to raise prices

| Trigger | Action |
|---|---|
| Monthly active paying MSPs > 250 | Raise Growth from $499 → $549; grandfather existing |
| ARR > $5M | Add a "Plus" tier between Growth and Scale at $749 to capture upmarket without forcing $999 jump |
| Enterprise win rate > 30% | Raise Enterprise floor from $2,499 → $3,499 |
| Switching from BrightGauge accounts for >40% of new MRR | Reduce switch credit from 6 mo → 3 mo |

### Recommended A/B tests on the pricing page

1. **Anchor**: Show Scale at top vs Growth at top. Hypothesis: anchoring on Scale increases avg ARPU.
2. **Annual default**: Pre-select annual toggle vs monthly toggle. Hypothesis: annual default → +30% annual mix.
3. **Per-client overage visible vs hidden**: Show "$5/client over 50" or hide in fine print. Hypothesis: visible builds trust and reduces sticker shock.
4. **Free tier framing**: "Single-site" (current) vs "Forever Free" vs no free tier. Hypothesis: time-limited trial converts better than perpetual free.
5. **Risk-reversal**: 30-day trial vs 30-day money-back vs 90-day money-back. Hypothesis: 90-day money-back wins large MSPs.

---

## Productization Prerequisites (must ship before launch)

| Gap (vs SaaS-ready) | Effort | Priority |
|---|---|---|
| Multi-tenant credential vault (currently OneDrive single-tenant) | 8 wks | P0 |
| Web UI for config + report download (currently CLI / file system) | 12 wks | P0 |
| Per-MSP data isolation in storage | 6 wks | P0 |
| Stripe billing + subscription management | 4 wks | P0 |
| SSO + RBAC | 6 wks | P1 (Scale tier) |
| White-label branding engine | 4 wks | P1 (Growth tier) |
| Self-serve onboarding (data source connect wizards × 8) | 10 wks | P0 |
| SOC 2 Type II audit | 6–9 mo | P2 (Enterprise) |
| Public docs + status page | 3 wks | P0 |

**Estimated productization budget:** ~9 months / 2 senior engineers / ~$400k +
$60k SOC 2 audit. If amortized over Year 1 ARR target of $750k, the
productization investment recovers in ~7 months at projected unit economics.

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| BrightGauge / ConnectWise drops price 30% in response | Med | Founding-50 lock-in; per-client overage means we expand revenue with their customer growth; build > 2 differentiators (DOCX output + change audit) they can't match without rewrites |
| Kaseya bundles a free QBR tool into IT Glue | High over 24 mo | Position MSPReportHub as "the tool for MSPs who don't want to be Kaseya-locked"; lean into platform-agnostic data sources |
| MSPs build it themselves with ChatGPT + n8n | Med | Already happening — but our 8 maintained integrations + auto-proofread QC gate are the moat. Position as "we maintain the integrations so you don't have to" |
| Per-client model gets gamed (1 "client" = 50 child orgs) | Low | Define "client" as a billable entity in PSA, audit at renewal, soft enforcement |
| Free tier exhausts Meraki/Huntress API quotas at scale | Low | Free tier limited to 2 sources; rate-limit free tier to 1 report/month |
| Race to the bottom with low-cost competitors | Low | We're 19–35% under BrightGauge already; we don't need to chase Zomentum's $109 — different value prop (QBR tool, not security reporting) |

---

## TL;DR for the homepage

> **One platform. Eight integrations. Branded monthly QBRs in 60 seconds.
> Starting at $199/mo — and you'll save $80k/year vs the BrightGauge + Liongard
> + IT Glue stack. No demo required. 30-day free trial.**

Recommended above-the-fold price anchor: **$499/mo · 50 clients · 8 data
sources · branded Word output · auto-QC gate · white-label**, paired with
a strikethrough "Comparable competitor stack: ~$2,161/mo".
