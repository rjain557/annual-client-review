# M365 Findings — 2026-04 First Full Pull

> Pull date: 2026-04-30
> Tenants with access: 11/38 (29%)
> Tenants needing consent: 27 (5 GDAP holdouts + 22 Cloud Reseller)

## Access matrix

### ✅ HAVE ACCESS (11 tenants)
TECHNIJIAN, BIS, CBI, NOR, VAF, SAS, AAOC, ACU, BWH, HHOC, ORX

### ❌ NEED CONSENT (27 tenants)
- **GDAP — quick win, you have GA**: CBL, CCC, JRM, MRM, KES (5)
- **Cloud Reseller — needs each client's GA**: CALPARK, YEBO, ESV, LCS, VGR, JDH, TINC, CBSC, TOFF, TCAG, BOS, DISP, MAG, ICM, PDC, CDC, MKC, NAV, RMG, KFXM, TFG, HDS (22)

---

## High-priority findings → ticket candidates

### 🔴 CRITICAL — Storage about to fail
| Client | User / Resource | Used / Quota | % |
|---|---|---|---|
| **AAOC** | Mailbox (anonymized) | 48.7 / 50 GB | **97.4%** |

> AAOC has report anonymization on — display name is a hash. Tech needs to
> correlate via M365 admin → reports → toggle "Display concealed user names"
> off, then re-pull, OR read from `clients/aaoc/m365/storage/2026-W18/mailbox_usage.json`.

### 🟠 SECURITY — Active threats observed (last 30 days)

**TECHNIJIAN — risky sign-in still flagged `atRisk` (not remediated)**
- Parveen Biswal (`pbiswal@technijian.com`) — 4/15 — sign-in from Wallingford CT
- 7 risk reasons: UnfamiliarASN, UnfamiliarBrowser, UnfamiliarDevice, UnfamiliarIP,
  UnfamiliarLocation, UnfamiliarEASId, UnfamiliarTenantIPsubnet
- MITRE T1078.004 (Cloud Accounts)
- **Action**: confirm with Parveen if this was him traveling. If not, force password
  reset + revoke sessions + investigate.

**Sign-in volume + threat flags (last 30 days, chunked + parallel pull):**

| Client | Signins | Failed | % Fail | Risky | Threat flags |
|---|---:|---:|---:|---:|---|
| TECHNIJIAN | 42,802 | 9,597 | 22% | 11 | 🔴 brute_force, spray, foreign, legacy |
| ORX | 24,625 | 2,700 | 11% | 8 | 🔴 brute_force, spray, foreign, legacy |
| **AAOC** | 3,589 | **2,961** | **82%** | 0 | 🔴 brute_force, spray, foreign, legacy |
| HHOC | 2,561 | 16 | 0.6% | 0 | clean |
| **BWH** | 2,406 | **1,642** | **68%** | 2 | 🔴 brute_force, spray, foreign, legacy |
| VAF | 1,892 | 184 | 10% | 0 | 🟠 brute_force, spray, foreign |
| CBI | 429 | 116 | 27% | 0 | 🟠 brute_force, foreign |
| ACU | 20 | 7 | 35% | 0 | 🟠 foreign |
| BIS | 0 | 0 | n/a | 0 | no premium (30/30 chunks 403) |
| NOR | 0 | 0 | n/a | 0 | no premium |
| SAS | 0 | 0 | n/a | 0 | no premium |

> AAOC and BWH failure rates of 82% and 68% are **active credential-stuffing
> attacks** in progress — not normal user error.

> VAF was previously thought to lack AAD Premium — chunked queries succeeded
> with 1,892 sign-ins, so it does have premium.

**Premium-licensed (signin data available): 8/11** — TECHNIJIAN, CBI, VAF, AAOC, ACU, BWH, HHOC, ORX
**Non-premium (signin endpoint 403): 3/11** — BIS, NOR, SAS

### 🚨 Top brute-force targets (each user has hundreds–thousands of failed logins)

**TECHNIJIAN**
- ssingh@technijian.com — 2,729 failures
- rjain@technijian.com — 2,497 failures
- support@technijian.com — 1,577 failures
- kjagota@technijian.com — 414 failures

**AAOC**
- info@aaoc.com — **2,052 failures**
- debbied@aaoc.com — 744 failures
- help@aaoc.com — 38 failures
- administrator@aaoc.com — 36 failures

**BWH**
- dave@brandywine-homes.com — 771 failures
- scott@brandywine-homes.com — 425 failures
- brett@brandywine-homes.com — 227 failures

**ORX**
- vestrada@orthoxpress.com — 507 failures
- jsalamon@orthoxpress.com — 494 failures

### 🚨 Cross-tenant attacker IP — same actor hitting multiple Technijian clients

`182.72.80.174` appears as a password-spray source on:
- TECHNIJIAN (24 users)
- ORX (9 users)
- VAF (5 users)

This is a **coordinated MSP-wide credential-stuffing campaign**. Recommend
adding to a tenant-level CA block list across all clients simultaneously.

Other cross-tenant IPs to investigate: `64.58.142.218` (BWH 10 users),
`12.79.8.230` (ORX 31 users), `66.81.19.126` (TECHNIJIAN 19 users),
`98.153.179.90` (AAOC 5 users), `64.58.151.18` (VAF 13 users).

**Tenants with risky-sign-in events (P2 endpoint):**
- TECHNIJIAN: 11 events
- BWH: 2 events
- ORX: 8 events

### 🟡 STORAGE — approaching quota (≥75%)
| Client | Resource | Used / Quota | % |
|---|---|---|---|
| BWH | SharePoint "Projects Owners" | 908 / 1024 GB | 88.7% |
| BWH | Teams "Company Administrator" | 0.9 / 1 GB | 87.6% |
| BWH | Mailbox: Angela Meyer | 43.2 / 50 GB | 86.4% |
| AAOC | Mailbox (anonymized) | 42.4 / 50 GB | 84.9% |
| VAF | Mailbox: Mike Chun | 41.5 / 50 GB | 83.1% |
| VAF | Mailbox: Amanda Holmes | 41.4 / 50 GB | 82.7% |
| VAF | Mailbox: Myrna Uribe | 41.3 / 50 GB | 82.6% |
| BWH | Mailbox: Julio Sanchez | 78.7 / 100 GB | 78.7% |
| BWH | Mailbox: Alex Hernandez | 78.6 / 100 GB | 78.6% |
| BWH | Mailbox: Michael Habitz | 77.7 / 100 GB | 77.7% |
| AAOC | Mailbox (anonymized) | 38.3 / 50 GB | 76.6% |

### 🟡 COMPLIANCE — posture failures by client

#### TECHNIJIAN (own tenant) — most fails
- ❌ MFA Registration: **9.1%** (149/1644 users)
- ❌ Legacy Auth NOT blocked
- ❌ 8 Global Admins (best practice 2-3)
- ❌ 1388 guest accounts (likely MSP-related, but review)
- ⚠️  Secure Score: 42.6%

#### Per-client posture
| Client | MFA % | CA Policies | Legacy Auth | Global Admins | Guests | Secure Score |
|---|---|---|---|---|---|---|
| BIS | n/a | ❌ 0 | ✅ defaults | ✅ 1 | ✅ 0 | ⚠️ 45.8% |
| CBI | ⚠️ 88.2% | ✅ 2 | ❌ unblocked | ✅ 1 | ✅ 0 | ✅ 65.7% |
| NOR | n/a | ❌ 0 | ✅ defaults | ✅ 1 | ✅ 0 | ✅ 89.3% |
| VAF | ❌ **50.6%** | ✅ 2 | ❌ unblocked | ✅ 3 | ⚠️ 1 | ✅ 100% |
| SAS | n/a | ❌ 0 | ❌ unblocked | ✅ 3 | ✅ 0 | ❌ 33.1% |
| AAOC | ❌ **30.4%** | ✅ 3 | ❌ unblocked | ✅ 3 | ✅ 0 | ✅ 78.2% |
| ACU | ❌ 50.0% | ✅ 3 | ❌ unblocked | ❌ 6 | ⚠️ 1 | ✅ 83.4% |
| BWH | ❌ 42.1% | ✅ 3 | ❌ unblocked | ⚠️ 4 | ❌ **77** | ⚠️ 44.9% |
| HHOC | ❌ **7.5%** | ⚠️ 1 | ❌ unblocked | ✅ 2 | ❌ **222** | ⚠️ 52.6% |
| ORX | ❌ 40.3% | ✅ 3 | ❌ unblocked | ✅ 3 | ⚠️ 8 | ❌ 34.5% |

**Themes — fix once, ticket many times:**
1. **Legacy Auth not blocked** — 9 of 11 tenants. Single-policy fix per tenant
   (CA policy: Block Legacy Authentication). Massive risk reduction.
2. **MFA registration low** — TECHNIJIAN 9.1%, HHOC 7.5%, AAOC 30.4%. These need
   user-by-user enrollment campaigns.
3. **Excessive guests** — BWH 77, HHOC 222 — review external collaboration.

---

## Recommended ticket creation flow

### Per-tenant ticket types
| Finding | Severity | Suggested CP category |
|---|---|---|
| Storage ≥90% | P1 | Email Issue / Storage |
| Storage 75-90% | P2 | Storage Cleanup |
| Brute-force flagged | P1 | Security Incident |
| Foreign success login | P2 | Security Review |
| MFA registration <50% | P3 | Security Hardening |
| Legacy auth not blocked | P3 | Security Hardening |
| Risky user atRisk | P1 | Security Incident |

### Diff-and-ticket logic (recommended)
Run after each pull. Compare current `*_summary.json` against last week's. Only
ticket on:
- New finding (didn't exist last run)
- Severity escalation (was warn, now critical)

Don't ticket on:
- Same finding still present (already ticketed last week — leave it open)
- Resolved findings (close any open ticket of that type)

---

## Cadence (see `CADENCE.md`)

| Pull | Cadence | Window |
|------|---------|--------|
| Security | Daily 06:00 PT | last 24h |
| Compliance | Weekly Mon 07:00 PT | snapshot |
| Storage (operational) | Weekly Mon 07:00 PT | last 7d |
| Storage (trend) | Monthly 1st 07:30 PT | last 180d |

## Implementation notes

- All 3 pull scripts now support `--workers N` (parallel tenants) and the
  security script supports `--chunk-hours N` (sign-in chunking) — addresses
  per-tenant timeout failures we hit on TECHNIJIAN and BWH (1644 / 183 user
  tenants × 30 day window).
- `state/gdap_status.csv` is the single source of truth for which tenants
  to pull. Remove a row to skip a client; flip `status` to `pending` to
  pause without deleting.
- Default workers = 6, default chunk = 24h. Each tenant has its own Graph
  rate limit so 6-way parallelism is safe even at scale.
