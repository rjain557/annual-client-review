# m365-compliance-pull

Monthly M365 compliance posture snapshot per GDAP-approved client tenant.
Scores each client's security configuration with pass/warn/fail checks and
archives the raw data for report generation.

## When to invoke

Trigger phrases: "m365 compliance", "compliance posture", "secure score",
"mfa coverage", "conditional access check", "admin roles", "m365 config",
"security defaults", "pull m365 compliance", "m365 configuration audit".

## What it checks

| Check | Pass | Warn | Fail |
|---|---|---|---|
| MFA Registration % | ≥90% users | ≥70% | <70% |
| Conditional Access Policies | ≥2 enabled | 1 enabled | 0 |
| Legacy Auth Blocked | CA policy or security defaults | — | Not blocked |
| Global Administrator Count | ≤3 | ≤5 | >5 |
| Microsoft Secure Score | ≥60% | ≥40% | <40% |
| Guest User Count | 0 | ≤10 | >10 |

## Output per client (`clients/<code>/m365/compliance/YYYY-MM/`)

```
secure_score.json           Microsoft Secure Score + control breakdown
conditional_access.json     all CA policies (state, conditions, controls)
security_defaults.json      isEnabled flag
mfa_registration.json       per-user MFA registration status
admin_roles.json            privileged role members (Global Admin etc.)
guest_users.json            external guest accounts
subscribed_skus.json        license SKUs (for reconciliation with Pax8)
compliance_summary.json     overall posture + check results
```

## Prerequisites

- `keys/m365-partner-graph.md` — App ID + Client Secret filled in
- `technijian/m365-pull/state/gdap_status.csv` — approved tenants
- Azure app permissions granted:
  - `Policy.Read.All` — conditional access, security defaults
  - `SecurityEvents.Read.All` — secure score
  - `UserAuthenticationMethod.Read.All` — MFA registration
  - `RoleManagement.Read.Directory` — admin roles
  - `Directory.Read.All`, `User.Read.All` — guest users, members

## Usage

```cmd
cd c:\vscode\annual-client-review\annual-client-review

REM current month, all tenants
python technijian\m365-pull\scripts\pull_m365_compliance.py

REM specific month
python technijian\m365-pull\scripts\pull_m365_compliance.py --month 2026-04

REM specific clients
python technijian\m365-pull\scripts\pull_m365_compliance.py --only BWH,ORX
```

## Scheduled task (workstation.md section)

```
Task name:  Technijian-MonthlyM365CompliancePull
Trigger:    Monthly, Day 2, 08:00 PT
Action:     cmd /c "cd /d C:\vscode\annual-client-review\annual-client-review && technijian\m365-pull\run-m365-compliance.cmd"
Run as:     %USERNAME%
```

## Integration with license reconciliation

`subscribed_skus.json` (from this pull) + Pax8 cost data = Phase 1 margin audit.
Add `clients/_m365_gdap_status.csv` to track GDAP approval per client.
