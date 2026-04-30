# m365-security-pull

Daily pull of Azure AD sign-in logs per GDAP-approved client M365 tenant.
Detects brute-force attacks, password sprays, foreign logins, legacy auth use,
and MFA failures. Archives per-client snapshots for trend analysis.

## When to invoke

Trigger phrases: "m365 security pull", "sign-in logs", "login attempts",
"brute force", "m365 threats", "azure ad security", "pull m365 security",
"who's trying to hack", "foreign logins", "failed logins".

## What it does

For every client with an approved GDAP entry in `state/gdap_status.csv`:

1. Pulls `/auditLogs/signIns` for the 24h window
2. Extracts failed sign-ins (`status.errorCode != 0`)
3. Pulls risky sign-ins + risky users (Entra P2 only — empty list if not licensed)
4. Runs threat detection: brute-force (≥10 failures/user), password spray
   (≥5 users from same IP), foreign logins, legacy auth, MFA failures

Output per client (`clients/<code>/m365/YYYY-MM-DD/`):
```
signin_logs.json       all sign-ins in window
failed_signins.json    failed only
risky_signins.json     medium/high risk (P2)
risky_users.json       flagged accounts (P2)
threat_summary.json    brute-force/spray/foreign flags + lists
pull_summary.json      counts, errors, flags
```

## Prerequisites

- `keys/m365-partner-graph.md` — App ID + Client Secret filled in
- `technijian/m365-pull/state/gdap_status.csv` — at least one row with
  `status=approved` and a valid `tenant_id`
- Azure app permissions granted:
  - `AuditLog.Read.All`
  - `IdentityRiskEvent.Read.All` (P2 features)
  - `IdentityRiskyUser.Read.All` (P2 features)

## Usage

```cmd
cd c:\vscode\annual-client-review\annual-client-review

REM last 24h, all GDAP tenants
python technijian\m365-pull\scripts\pull_m365_security.py

REM last 7 days (first run / catch-up)
python technijian\m365-pull\scripts\pull_m365_security.py --hours 168

REM specific clients
python technijian\m365-pull\scripts\pull_m365_security.py --only BWH,ORX

REM specific date
python technijian\m365-pull\scripts\pull_m365_security.py --date 2026-04-29
```

## Scheduled task (workstation.md section)

```
Task name:  Technijian-DailyM365SecurityPull
Trigger:    Daily 06:00 PT
Action:     cmd /c "cd /d C:\vscode\annual-client-review\annual-client-review && technijian\m365-pull\run-m365-security.cmd"
Run as:     %USERNAME%
```

## Adding a client (GDAP approved)

Edit `technijian/m365-pull/state/gdap_status.csv` and add a row:
```
BWH,Brandywine Homes,<tenant-id>,2026-05-01,2026-05-03,approved,
```
The tenant_id is the client's Azure AD Directory ID (found in their Entra admin center
or in the GDAP approval email).

## Data retention note

Azure AD sign-in logs: 7 days on basic Entra, 30 days on P1/P2.
Run this daily and the archived JSON becomes your long-term history.
