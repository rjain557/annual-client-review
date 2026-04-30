# M365 Pull Cadence Recommendation

> Goal: keep client M365 posture data current enough to drive ticket creation
> in the Client Portal, without burning Graph API quota or storage.

## TL;DR — recommended cadences

| Pull | Cadence | Window | Why this cadence |
|------|---------|--------|------------------|
| **Security** (sign-ins, alerts, incidents) | **Daily 06:00 PT** | last 24h | Threats are hot — same-day detection drives same-day tickets |
| **Compliance** (MFA %, CA, Secure Score, admins, guests) | **Weekly Mon 07:00 PT** | snapshot | Posture changes are slow; daily would be noise |
| **Storage** (mailbox/OneDrive/SharePoint) | **Weekly Mon 07:00 PT** | last 7d (D7) | Microsoft updates these reports daily but quota changes are gradual |
| **Storage trend** (long lookback) | **Monthly 1st 07:00 PT** | last 180d (D180) | Captures growth trajectory for capacity planning |

Stagger times to avoid contention with existing pulls (Huntress 01:00,
Umbrella 02:00, CrowdStrike 03:00, Teramind 04:00, Meraki 05:00).

## Per-pull rationale

### Security — daily

**Window: `last 24h`, run at 06:00 PT**

What it captures:
- Sign-in logs (every authentication event)
- Failed sign-ins (errorCode != 0)
- Risky sign-ins (P2 only — `riskLevelAggregated = medium/high`)
- Risky users (P2 only)
- Threat heuristics (brute-force, password spray, foreign-login)

**Why daily:** sign-in attacks happen in minutes, not weeks. A daily pull
gives same-day visibility for ticket creation. Graph retention is ~30 days
in v1.0 so we can't go back further than that anyway — daily cadence keeps
us inside the retention window.

**Ticket triggers:**
- Brute-force attempt against any user (≥10 failed sign-ins in 1h)
- Password spray attempt (≥3 failed sign-ins across ≥10 users in 1h)
- Successful sign-in from unusual country
- Risky user flagged at high risk
- Admin account sign-in failure

### Compliance — weekly

**Window: snapshot, run Mon 07:00 PT**

What it captures:
- Conditional Access policy inventory + state
- MFA registration % (the metric that matters)
- Admin role membership (who has Global Admin / Privileged Auth Admin)
- Security Defaults state
- Guest user count
- Subscribed SKUs (license inventory)
- Microsoft Secure Score

**Why weekly:** these things change on the order of days/weeks, not minutes.
Daily would produce identical results 6 days out of 7. Weekly catches:
- New admin assignments (audit weekly is a SOX-grade cadence)
- License changes from billing
- New CA policies deployed
- MFA enrollment progress (after MFA campaigns)

**Ticket triggers:**
- New Global Admin appeared since last run
- MFA registration % dropped (someone unregistered)
- CA policy disabled or deleted
- New unmanaged guest user invited
- Secure Score dropped >5% week-over-week

### Storage — weekly + monthly

**Weekly (D7)**: catches users approaching mailbox/OneDrive quota limits
that need cleanup tickets *this week* before they bounce mail or fail to
sync.

**Monthly (D180)**: captures storage growth trends for annual reviews and
capacity planning. The same script with `--period D180` answers: "is BWH's
SharePoint growth consuming their tenant capacity?"

**Ticket triggers:**
- Any mailbox ≥90% used (critical — mail will start bouncing)
- Any OneDrive ≥90% (sync will fail)
- Any SharePoint site ≥90% of site quota
- Org-level total ≥85% of tenant capacity (need add-on storage SKU)

## Setup

All scripts already filter on `gdap_status.csv` rows where `status=approved`.
Use `--only` flag to scope to currently-accessible tenants (11 today, will
grow as more tenants consent).

Scheduled tasks (production workstation only — **never on dev box**, see
`feedback_no_dev_box_schedules.md`):

```cmd
REM Daily security pull
schtasks /create /tn "Technijian-DailyM365Security" ^
  /sc daily /st 06:00 /ru "%USERNAME%" ^
  /tr "cmd /c c:\vscode\annual-client-review\annual-client-review\technijian\m365-pull\run-m365-security.cmd"

REM Weekly compliance + storage pull (Monday)
schtasks /create /tn "Technijian-WeeklyM365Posture" ^
  /sc weekly /d MON /st 07:00 /ru "%USERNAME%" ^
  /tr "cmd /c c:\vscode\annual-client-review\annual-client-review\technijian\m365-pull\run-m365-weekly.cmd"

REM Monthly storage trend pull (1st of month)
schtasks /create /tn "Technijian-MonthlyM365StorageTrend" ^
  /sc monthly /mo 1 /d 1 /st 07:30 /ru "%USERNAME%" ^
  /tr "cmd /c c:\vscode\annual-client-review\annual-client-review\technijian\m365-pull\run-m365-monthly-storage.cmd"
```

## Ticket creation pattern

The pulls write `*_summary.json` files per client containing `alerts[]` and
`posture.checks[]` arrays — these are the ticket sources.

Recommended flow:
1. Pull writes summary → `clients/<code>/m365/.../*_summary.json`
2. **Diff against last run's summary** (so we don't re-ticket the same MFA gap every week)
3. New findings → create CP ticket via `cp_api.create_ticket()`
4. Resolved findings (was-failing, now-passing) → close any open ticket of
   that finding type for that client

A `ticket_m365_findings.py` script would sit alongside the pulls and do
this diff-and-ticket step. It does NOT need to run on the same cadence as
the pull — could be `pull → ticket` chained in the same .cmd, or a
separate task that runs 30 minutes after the pull completes.

## Volume sanity check

Per pull, per tenant, per run:

| Pull | Bytes written | Files written |
|------|---------------|---------------|
| Security (1 day) | 1-50 MB depending on user count | 6 JSONs |
| Compliance | 50-500 KB | 8 JSONs |
| Storage (D7) | 50 KB - 5 MB | 5 JSONs |

Rough yearly estimate for 11 tenants at recommended cadence:
- Security: 11 tenants × 365 days × 10 MB avg = ~40 GB/year
- Compliance: 11 × 52 × 200 KB = ~115 MB/year
- Storage weekly: 11 × 52 × 1 MB = ~600 MB/year
- Storage monthly: 11 × 12 × 5 MB = ~660 MB/year

**~42 GB/year total** for 11 tenants. Scales linearly to ~150 GB if all
38 tenants come online.

## Open questions

1. **Anonymized reports**: Microsoft anonymizes user identities in usage
   reports (mailbox/OneDrive/SharePoint) by default. The hashes in
   `displayName` aren't actionable for tickets. Either:
   - Disable anonymization in each tenant's M365 admin → Reports → "Display
     concealed user, group, and site names" = OFF. (per-tenant manual setting)
   - Or accept that storage tickets reference hashes and the tech has to
     correlate via M365 admin manually.

2. **P2 features (risky users, risky sign-ins)**: Require Azure AD Premium
   P2 license. Tenants without P2 will get empty arrays — that's expected,
   not an error.

3. **Sign-in log retention**: 30 days in v1.0 Graph regardless of license.
   For longer retention, would need to ship sign-ins to Sentinel or a SIEM.
