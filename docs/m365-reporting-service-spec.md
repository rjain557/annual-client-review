# Microsoft 365 Monthly Reporting Service
## Full Specification & Pricing — Brochure / One-Pager Source

---

## Service Name Options (choose one for branding)

- **M365 Insight Reports** — clear, enterprise-feel
- **ClearDesk M365** — friendly, MSP-facing
- **360° Microsoft 365 Reporting** — client-facing, recognizable
- **M365 Monthly Health Report** — utilitarian, descriptive

---

## Elevator Pitch (use on cover of brochure)

> Every month, your Microsoft 365 environment generates thousands of signals
> about security threats, unused licenses, compliance gaps, and storage
> bloat. Most MSPs never see it. We turn it into a branded, plain-English
> report on your desk by the 1st — automatically.

---

## Who It's For

### Primary buyer: MSPs and IT consultancies
MSPs who manage Microsoft 365 tenants for 5–200 clients and currently
produce QBRs manually, use the native Admin Center, or don't report on
M365 health at all.

**Ideal profile:**
- 10–150 managed M365 tenants
- Microsoft CSP partner (Direct or Indirect)
- Currently spending 2–4 hours per client per month on M365 reporting
- Has clients asking "are we secure?" or "are we wasting money on licenses?"

### Secondary buyer: Internal IT / vCISO
In-house IT teams managing a single large M365 tenant who need a monthly
executive-ready deliverable for the board or compliance officer.

---

## The Problem We Solve

| Pain Point | Without This Service | With This Service |
|---|---|---|
| License waste | Unknown — MSPs over-provision "just in case" | Identified monthly with dollar savings estimate |
| Security posture | Checked ad-hoc or never | Scored monthly, trend tracked |
| Compliance status | Pulled manually from Compliance Center | Aggregated automatically, section in every report |
| QBR prep time | 2–4 hrs/client/month at $75–$150/hr | 0 hrs — report is ready on the 1st |
| Client trust | "We keep the lights on" | "Here's proof of what we did and what we found" |
| Stale accounts | Discovered during audits (too late) | Flagged every month before they become a breach |

---

## What Every Report Includes

Reports are delivered as **branded Microsoft Word documents (.docx)**
with your company logo, colors, and cover page. Each report covers
one M365 tenant for one calendar month.

### Section 1 — Executive Summary
- KPI strip: total users, licensed users, active users, security score,
  license waste estimate ($), compliance issues flagged
- Month-over-month change indicators (up/down/stable)
- Plain-English status narrative: "Your environment is healthy / needs
  attention in 2 areas"

### Section 2 — License Usage & Optimization
- **License inventory**: every SKU assigned (E1, E3, E5, Business Basic,
  Business Premium, Copilot, Power BI, Visio, Project, etc.)
- **Assigned vs active use**: how many licenses assigned vs how many
  users actually signed in within the billing period
- **Waste identification**: licenses assigned to inactive or disabled accounts
- **Overprovisioned SKU analysis**: users on E5 not using Defender P2,
  Purview, or Advanced eDiscovery — eligible for E3 downgrade
- **Dollar savings estimate**: monthly savings if recommendations implemented
  (based on current Microsoft list price per SKU)
- **Guest and external user licenses**: shared mailboxes, room accounts,
  external identities consuming licenses
- **Month-over-month delta**: licenses added, removed, or changed

### Section 3 — Security Posture
- **Microsoft Secure Score**: current score, prior month score, industry
  benchmark comparison, top 5 improvement actions
- **MFA coverage**: % of users with MFA enabled, breakdown by auth method
  (Authenticator app, SMS, OATH hardware token), admin accounts without MFA
- **Conditional Access policies**: active policy count, policy gaps
  (users/apps/locations not covered), legacy authentication blocked or not
- **Privileged account audit**: Global Admins, Exchange Admins,
  SharePoint Admins — count, last login, MFA status
- **Sign-in risk summary**: high/medium/low risk sign-ins from Entra ID
  Identity Protection (where licensed)
- **Microsoft Defender for Office 365**: phishing attempts caught,
  malware blocked, safe link click events (where licensed)

### Section 4 — Compliance Status
- **Data Loss Prevention (DLP)**: active policies, policy violations last 30
  days, top violation types, unprotected sensitive data locations
- **Sensitivity labels**: label coverage % (labeled vs unlabeled files in
  SharePoint/OneDrive), top applied labels, unlabeled high-value sites
- **Retention policies**: active policies, locations covered, any gaps
  (mailboxes or sites not covered by a retention policy)
- **Audit log status**: unified audit log enabled/disabled, retention
  period configured
- **eDiscovery readiness**: hold policies active, custodians configured

### Section 5 — Storage & Capacity
- **Exchange Online mailboxes**: total mailbox count, storage used vs quota,
  top 10 largest mailboxes, mailboxes approaching quota (>80%)
- **SharePoint Online**: total sites, storage used vs tenant quota,
  top 10 largest sites by GB, external sharing enabled sites
- **OneDrive for Business**: total storage used, users approaching quota,
  users with no OneDrive activity in 90+ days
- **Archive mailboxes**: auto-archive enabled/disabled, archive size

### Section 6 — User Health
- **Stale accounts**: users with no login in 30/60/90 days (still licensed)
- **Disabled accounts still licensed**: direct savings opportunity flagged
- **Guest accounts**: total guests, guests not active in 90 days,
  external domains with most guest access
- **Password policy**: password expiration enabled or passkeys/passwordless
  configured, users with password never expires
- **New users and departures**: accounts created and deleted this month

### Section 7 — What We Did For You This Month
- Summary of any M365 changes made during the month (admin actions
  visible in the audit log: policy changes, license assignments,
  new user onboarding, etc.)
- Technician hours logged against M365-related tickets (if PSA integrated)

### Section 8 — Recommendations
- Prioritized action list (P1/P2/P3) with estimated effort and savings
- License right-sizing table: specific users + specific SKU downgrade
  recommendations with dollar impact
- Security hardening steps not yet implemented
- Compliance gaps with remediation path

---

## Pricing

### Model: Per-Tenant / Per-Month, User-Count Banded

Pricing is based on the number of **licensed users** in the tenant
(as reported by Microsoft 365 Admin Center). Billed per tenant per month.

| Band | Licensed Users | Monthly | Annual (save 17%) | Per-Day Equivalent |
|---|---|---|---|---|
| **XS** | 1 – 10 | **$15** | $150/yr | $0.50/day |
| **S** | 11 – 25 | **$29** | $290/yr | $0.97/day |
| **M** | 26 – 50 | **$49** | $490/yr | $1.63/day |
| **L** | 51 – 100 | **$79** | $790/yr | $2.63/day |
| **XL** | 101+ | **$129** | $1,290/yr | $4.30/day |

**User count definition:** Licensed users = users with at least one
Microsoft 365 paid license assigned, as reported by
`/reports/microsoft.graph.getOffice365ActiveUserCounts`. Does not include
shared mailboxes, room/equipment accounts, or guest users.

**Volume discount (MSPs with 20+ tenants):**
Contact us for MSP volume pricing. Typical volume break is 15% off
list for 20–49 tenants, 25% off for 50+ tenants.

### What's Included at Every Tier

| Feature | XS $15 | S $29 | M $49 | L $79 | XL $129 |
|---|---|---|---|---|---|
| All 8 report sections | ✅ | ✅ | ✅ | ✅ | ✅ |
| Branded Word DOCX deliverable | ✅ | ✅ | ✅ | ✅ | ✅ |
| License waste analysis + $ savings estimate | ✅ | ✅ | ✅ | ✅ | ✅ |
| Auto-proofread quality gate | ✅ | ✅ | ✅ | ✅ | ✅ |
| Monthly delivery (1st of month) | ✅ | ✅ | ✅ | ✅ | ✅ |
| White-label branding (your logo/colors) | ✅ | ✅ | ✅ | ✅ | ✅ |
| 12-month trend history | ✅ | ✅ | ✅ | ✅ | ✅ |
| On-demand report generation | — | ✅ | ✅ | ✅ | ✅ |
| Conditional access gap analysis | — | ✅ | ✅ | ✅ | ✅ |
| Defender for O365 threat summary | — | ✅ | ✅ | ✅ | ✅ |
| Compliance pack (DLP/sensitivity labels) | — | — | ✅ | ✅ | ✅ |
| eDiscovery readiness section | — | — | ✅ | ✅ | ✅ |
| API export (JSON) | — | — | — | ✅ | ✅ |
| HIPAA / SOC 2 / PCI compliance mapping | — | — | — | ✅ | ✅ |
| 7-year audit log retention | — | — | — | — | ✅ |
| Dedicated customer success contact | — | — | — | — | ✅ |
| SLA: report delivery by 1st of month 9 AM | — | — | — | — | ✅ |

---

## Bundle Pricing — With Meraki Monitoring

For clients who also have Cisco Meraki, bundle both services and save 10%.

| M365 Band | M365 Only | + Meraki ($150/org) | 10% Bundle Price | Annual Bundle/client |
|---|---|---|---|---|
| XS (1–10 users) | $15 | $165 | **$149/mo** | $1,788/yr |
| S (11–25 users) | $29 | $179 | **$161/mo** | $1,932/yr |
| M (26–50 users) | $49 | $199 | **$179/mo** | $2,148/yr |
| L (51–100 users) | $79 | $229 | **$206/mo** | $2,472/yr |
| XL (101+ users) | $129 | $279 | **$251/mo** | $3,012/yr |

---

## ROI & Savings Calculator

### Time savings (primary ROI driver)

| MSP profile | Manual M365 reporting time | Hourly cost | Monthly labor cost | Service cost | Monthly savings |
|---|---|---|---|---|---|
| 10 tenants, avg M-band | 10 × 2 hrs × $75 | $75/hr | $1,500 | $490 | **$1,010** |
| 25 tenants, mixed bands | 25 × 2.5 hrs × $75 | $75/hr | $4,688 | $1,000 est. | **$3,688** |
| 50 tenants, mixed bands | 50 × 2.5 hrs × $75 | $75/hr | $9,375 | $1,800 est. | **$7,575** |

### License waste savings (secondary ROI driver — direct client benefit)

Industry benchmark: MSPs typically find **$8–$25 per user per month** in
license waste on first audit (unused licenses, overprovisioned SKUs,
disabled accounts still licensed).

| Tenant size | Conservative waste found | After fixing waste | Service cost | Net first-month impact |
|---|---|---|---|---|
| 20 users (S-band) | $8 × 20 = $160 saved | $160 – $29 = **+$131** | $29 | Client saves $131 in month 1 |
| 50 users (M-band) | $10 × 50 = $500 saved | $500 – $49 = **+$451** | $49 | Client saves $451 in month 1 |
| 100 users (L-band) | $12 × 100 = $1,200 saved | $1,200 – $79 = **+$1,121** | $79 | Client saves $1,121 in month 1 |

**The service typically pays for itself in the first report through license
savings alone** — before counting the labor savings.

---

## Technical Requirements

### What we need from you (setup, one-time)

1. **Microsoft 365 Admin credentials** — Global Reader role is sufficient
   (read-only; we never modify your tenant). For Defender/Compliance data:
   Security Reader + Compliance Data Administrator roles.
2. **Azure AD App Registration** — we provide a step-by-step setup guide;
   takes 15 minutes. Grants delegated or application permissions to
   Microsoft Graph API.
3. **Your branding assets** — logo (PNG, min 600px wide) + primary/secondary
   hex color codes.

### Microsoft Graph API permissions required

| Permission | Type | Purpose |
|---|---|---|
| `Reports.Read.All` | Application | License and activity reports |
| `User.Read.All` | Application | User inventory, last sign-in |
| `Directory.Read.All` | Application | Groups, roles, guest users |
| `SecurityEvents.Read.All` | Application | Defender alerts |
| `Policy.Read.All` | Application | Conditional access, DLP policies |
| `InformationProtectionPolicy.Read.All` | Application | Sensitivity labels |
| `Mail.ReadBasic.All` | Application | Mailbox size metrics |
| `Sites.Read.All` | Application | SharePoint/OneDrive storage |
| `AuditLog.Read.All` | Application | Sign-in logs, audit events |

All permissions are **read-only**. We never write to, modify, or delete
data in your tenant.

### Supported Microsoft 365 plans

Full report available for tenants with any of:
- Microsoft 365 Business Basic / Standard / Premium
- Microsoft 365 E1 / E3 / E5
- Office 365 E1 / E3 / E5

Some sections require specific add-on licenses:
- Defender for Office 365 section: requires Defender for O365 Plan 1 or 2
- Identity Protection section: requires Entra ID P1 or P2
- Advanced Compliance/eDiscovery: requires M365 E5 Compliance or Purview add-on

Sections are automatically omitted (not shown as blank) when the required
license is not present in the tenant.

---

## Delivery & Operations

| Item | Detail |
|---|---|
| **Delivery date** | 1st of each month by 9:00 AM local time |
| **Format** | Microsoft Word (.docx), white-labeled with your branding |
| **Delivery method** | Email to your designated address + secure download portal |
| **Historical access** | All prior reports available for download, 12-month default |
| **On-demand runs** | Available on S-band and above; up to 3 per month |
| **Setup time** | Typically 1–2 business days after credentials received |
| **Data residency** | US-based processing; no tenant data retained after report generation |

---

## Frequently Asked Questions

**Q: Do you need Global Admin access?**
No. Global Reader is sufficient for all read operations. We provide a
step-by-step guide to create a dedicated service account with the minimum
required permissions.

**Q: Can we white-label this for our clients?**
Yes. Every report carries your logo and brand colors. There is no
"Powered by" attribution by default — the report is entirely your
deliverable to present to your clients.

**Q: What if a tenant drops below or exceeds a user-count band mid-month?**
Billing is based on the user count on the **last day of the prior month**
(the snapshot date used to generate the report). No retroactive adjustments.

**Q: Can we generate reports for Microsoft 365 Government (GCC) tenants?**
GCC (Government Community Cloud) tenants are supported on the L and XL
bands. GCC-High and DoD require Enterprise pricing — contact us.

**Q: What's not covered?**
This service covers Microsoft 365 cloud services only. It does not cover
on-premises Exchange, Active Directory, or Azure infrastructure outside
of Entra ID. Azure cost management and resource reporting is a separate
service.

**Q: How is this different from the Microsoft 365 Admin Center reports?**
The Admin Center shows raw data. Our service delivers a curated, branded,
narrative report with context, trend lines, prioritized recommendations,
and a license savings estimate — ready to send to your client's CEO or
board without any additional formatting.

---

## Competitive Comparison

| | **M365 Reporting Service** | Microsoft Admin Center | Gradient Synthesize | SysKit Point |
|---|---|---|---|---|
| Branded DOCX deliverable | ✅ | ❌ (PDF only, no branding) | ❌ (dashboard) | ❌ (dashboard) |
| License waste + $ savings estimate | ✅ | ❌ | ✅ | Partial |
| Security posture + Secure Score | ✅ | ✅ (raw data) | ❌ | ❌ |
| Compliance (DLP/labels/retention) | ✅ | ✅ (raw data) | ❌ | Partial |
| Storage utilization | ✅ | ✅ (raw data) | ❌ | ❌ |
| Automated monthly delivery | ✅ | ❌ (manual export) | ✅ | Partial |
| Auto-proofread quality gate | ✅ | n/a | n/a | n/a |
| Public pricing | ✅ | Free | $149–$399/mo flat | Contact sales |
| Per-tenant pricing (scales with MSP) | ✅ | n/a | ❌ (flat MSP fee) | ❌ (contact sales) |
| White-label | ✅ | ❌ | ❌ | ❌ |

---

## One-Pager Summary (designer-ready copy blocks)

### Headline
**Know exactly what's happening in every Microsoft 365 tenant.
Every month. Automatically.**

### Sub-headline
Branded monthly reports covering license waste, security posture,
compliance status, and storage — delivered to your inbox on the 1st.

### Three value pillars

**Find the waste.**
The average SMB wastes $8–$25 per user per month in unused or
overprovisioned Microsoft 365 licenses. We find it, quantify it,
and tell you exactly which users to change.

**Prove your value.**
Your clients don't see what you do. Every month, a branded report
shows them their security score, what threats were blocked, and
what you're protecting them from. That's a QBR in an envelope.

**Save the hours.**
The average MSP spends 2–3 hours per client per month pulling
M365 data manually. At 30 clients, that's 90 hours — gone.
We run every pull automatically on the 1st.

### Pricing snapshot (one-pager callout box)

```
Starting at $15/month per tenant

1–10 users    $15/mo       101+ users   $129/mo
11–25 users   $29/mo
26–50 users   $49/mo       Annual plans save 17%
51–100 users  $79/mo       Bundle with Meraki: save 10%

No contracts on monthly plans.
Setup in under 2 business days.
```

### Call to action options
- "Get your first report free — no credit card required"
- "Start your 30-day trial"
- "See a sample report" (link to redacted sample PDF)
- "Book a 15-minute demo"

### Contact / footer
[Your company name] · [website] · [email] · [phone]
Microsoft Solutions Partner · CSP Direct Partner

---

*Document version: 1.0 — 2026-04-30*
*Pricing subject to change; existing subscribers grandfathered at signup price.*
