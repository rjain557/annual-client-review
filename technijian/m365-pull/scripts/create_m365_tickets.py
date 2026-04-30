"""Create CP tickets for every specific M365 finding.

For each tenant in gdap_status.csv that has data on disk, walk every
finding and open one ticket per issue with full remediation steps.

Issue types (each becomes its own ticket):
  Compliance fails:
    - MFA registration low
    - Conditional Access not configured
    - Legacy authentication not blocked
    - Excessive Global Administrators
    - Low Secure Score
    - Excessive guest accounts

  Storage:
    - Per critical resource (>=90% used) — P1
    - Per warn resource (>=75% used)     — P2

  Sign-in security:
    - Active brute-force attack (one ticket per tenant w/ top targets)
    - Password spray from IP (one ticket per offending IP)
    - Successful foreign sign-in (one ticket per tenant)
    - Legacy auth client connection observed (one ticket per tenant)
    - At-risk risky sign-in event (one ticket per individual at-risk user)

TECHNIJIAN findings are routed to the Internal Contract (ContractID=3977).
Client findings are billed against each client's active signed contract.
Clients without an active contract are skipped and surfaced in a CSV.

Usage:
    python create_m365_tickets.py --dry-run            # plan only
    python create_m365_tickets.py --month 2026-04      # for real
    python create_m365_tickets.py --only AAOC,BWH      # subset
    python create_m365_tickets.py --skip TECHNIJIAN
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PIPELINE_ROOT = HERE.parent
REPO = PIPELINE_ROOT.parent.parent
CLIENTS_ROOT = REPO / "clients"
STATE_DIR = PIPELINE_ROOT / "state"
GDAP_CSV = STATE_DIR / "gdap_status.csv"

CP_LIB = REPO / "scripts" / "clientportal"
sys.path.insert(0, str(CP_LIB))
import cp_tickets  # noqa: E402


# ---------------------------------------------------------------------------
# Loaders (same shape as the report builder)
# ---------------------------------------------------------------------------

def load_clients(only: set[str] | None, skip: set[str]) -> list[dict]:
    if not GDAP_CSV.exists():
        return []
    out = []
    with open(GDAP_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = row.get("client_code", "").strip().upper()
            if row.get("status", "").strip().lower() != "approved":
                continue
            if not row.get("tenant_id", "").strip():
                continue
            if only and code not in only:
                continue
            if code in skip:
                continue
            notes = (row.get("notes") or "").lower()
            if "pending app consent" in notes:
                continue  # no data yet
            out.append({
                "code": code,
                "name": row.get("client_name", code),
                "tenant_id": row["tenant_id"].strip(),
            })
    return out


def _load_json(p: Path):
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_latest_dir(parent: Path, pattern: str) -> Path | None:
    if not parent.exists():
        return None
    matches = sorted(parent.glob(pattern), reverse=True)
    return matches[0] if matches else None


def load_findings(code: str, month_str: str) -> dict[str, Any]:
    base = CLIENTS_ROOT / code.lower() / "m365"
    findings: dict[str, Any] = {
        "compliance": _load_json(base / "compliance" / month_str / "compliance_summary.json"),
        "storage": None,
        "security": None,
        "threats": None,
        "risky_signins": [],
    }
    storage_root = base / "storage"
    latest_storage = _find_latest_dir(storage_root, "2026-W*") if storage_root.exists() else None
    if latest_storage:
        findings["storage"] = _load_json(latest_storage / "storage_summary.json")
    if base.exists():
        sec_dirs = sorted(
            (d for d in base.iterdir() if d.is_dir() and d.name.startswith("2026-")),
            reverse=True
        )
        if sec_dirs:
            findings["security"] = _load_json(sec_dirs[0] / "pull_summary.json")
            findings["threats"] = _load_json(sec_dirs[0] / "threat_summary.json")
            findings["risky_signins"] = _load_json(sec_dirs[0] / "risky_signins.json") or []
    return findings


# ---------------------------------------------------------------------------
# Ticket templates
# ---------------------------------------------------------------------------

def t_legacy_auth(client: dict) -> dict:
    return {
        "title": f"M365 Security: Block Legacy Authentication for {client['code']}",
        "priority": "Same Day",
        "description": f"""Legacy authentication is currently NOT blocked in the {client['name']} M365 tenant ({client['tenant_id']}).

Why this matters:
Legacy auth protocols (POP3, IMAP, SMTP, MAPI over HTTP, EAS, Other clients) bypass Conditional Access and MFA. This is the #1 attack vector for credential stuffing and password-spray campaigns. Microsoft has been deprecating these protocols since 2022.

Remediation steps:
1. Sign in to https://entra.microsoft.com as a Global Administrator (use GDAP if you don't hold a permanent admin role).
2. Navigate to: Protection > Conditional Access > Policies > New policy.
3. Configure the policy:
   - Name: "Baseline: Block Legacy Authentication"
   - Users: All users (exclude break-glass account)
   - Cloud apps: All cloud apps
   - Conditions > Client apps: Configure Yes, then check ONLY:
     * Exchange ActiveSync clients
     * Other clients (POP, IMAP, SMTP, MAPI, etc.)
   - Access controls > Grant: Block access
   - Enable policy: Report-only first to verify nothing breaks, then On.
4. Run policy in Report-only for 7 days. Review the sign-in logs filtered to this policy to identify any service accounts or legacy clients still authenticating.
5. Update those service accounts to modern auth (OAuth2 / SMTP AUTH disabled).
6. Switch the policy from Report-only to On.

Verification:
- Sign-in logs > filter Client app = "Exchange ActiveSync" OR "Other clients" -> these should now show as Blocked.
- Re-run M365 compliance pull: 'Legacy Authentication Blocked' should change from FAIL to PASS.

References:
- https://learn.microsoft.com/en-us/entra/identity/conditional-access/howto-conditional-access-policy-block-legacy
- See M365 monthly report at clients/{client['code'].lower()}/m365/reports/2026-04/{client['code']}-M365-Activity-2026-04.docx
""",
    }


def t_no_ca_policies(client: dict) -> dict:
    return {
        "title": f"M365 Security: Configure Baseline Conditional Access for {client['code']}",
        "priority": "Same Day",
        "description": f"""The {client['name']} M365 tenant ({client['tenant_id']}) currently has 0 enabled Conditional Access policies (or is relying on Security Defaults only).

Why this matters:
Without Conditional Access, MFA enforcement, location-based controls, device compliance, and risk-based access cannot be applied. Security Defaults is a one-size-fits-all toggle that lacks granularity for break-glass accounts, service principals, or location restrictions.

Recommended baseline policies (deploy in this order):
1. "Block Legacy Authentication" — covered in separate ticket.
2. "Require MFA for All Users":
   - Users: All users (exclude one break-glass GA account)
   - Cloud apps: All cloud apps
   - Grant: Require multi-factor authentication
3. "Require MFA for Privileged Roles":
   - Users: Directory roles = Global Admin, Privileged Role Admin, Authentication Admin, etc.
   - Cloud apps: All cloud apps
   - Grant: Require MFA + Require compliant device
4. "Block Sign-in from Outside Allowed Locations" (optional):
   - Define Named Locations for the client's office IPs / countries.
   - Block any country not on the allowlist.

Steps:
1. Sign in to https://entra.microsoft.com as Global Admin (GDAP).
2. First create a break-glass account: Users > New user, name "Emergency Access", assign Global Admin, exclude from all CA policies, store password in a sealed envelope or LastPass.
3. Protection > Conditional Access > Policies > New policy. Build each policy above.
4. Always use Report-only mode first for 3-7 days, review sign-in logs, then enable.

Verification:
- Re-run M365 compliance pull: 'Conditional Access Policies' should change from FAIL to PASS (>=2 enabled).
- Sign-in logs filtered by each policy should show successful MFA enforcement.

References:
- https://learn.microsoft.com/en-us/entra/identity/conditional-access/concept-conditional-access-policies
""",
    }


def t_low_mfa(client: dict, value: str) -> dict:
    return {
        "title": f"M365 Security: Increase MFA Registration for {client['code']} ({value})",
        "priority": "Next Day",
        "description": f"""MFA registration is at {value} for the {client['name']} M365 tenant ({client['tenant_id']}). Microsoft and Technijian baseline target is 100% of licensed users registered.

Why this matters:
Users who haven't registered MFA can still authenticate with password only when CA policies are gradually rolled out. Attackers find these accounts via brute-force/spray and use them as initial access. Every unregistered user is a credential-attack waiting to land.

Remediation steps:
1. Pull the unregistered user list:
   - Sign in to https://entra.microsoft.com
   - Protection > Authentication methods > User registration details
   - Filter: 'Methods registered' = 'None' OR 'Default method' = 'Not set'
   - Export as CSV.
2. Group by department / function — coordinate with the client's HR/IT contact to confirm each user is still active.
3. Enable a Registration Campaign:
   - Protection > Authentication methods > Registration campaign
   - State: Enabled, target the unregistered group, snooze 0 days (immediate prompt at next sign-in)
4. Send proactive email from the client's admin to all unregistered users with the registration URL: https://aka.ms/mfasetup
5. Set a 14-day deadline. After that, enable a CA policy targeting the unregistered group with grant = Require MFA registration.
6. After 30 days, audit: target should be >95% registered.

Special considerations:
- Service accounts and shared mailboxes should be excluded from MFA — use app passwords or migrate to managed identity.
- Break-glass GA accounts should NOT use MFA — store credentials in a vault.

Verification:
- Re-run M365 compliance pull next month: 'MFA Registration' should improve significantly.
- Failed-MFA-prompt count in sign-in logs (failureReason contains 'MFA') should drop.

References:
- https://learn.microsoft.com/en-us/entra/identity/authentication/howto-mfa-nudge-enrollment
- https://aka.ms/mfasetup
""",
    }


def t_too_many_admins(client: dict, value: str) -> dict:
    return {
        "title": f"M365 Security: Reduce Global Admin Count for {client['code']} ({value})",
        "priority": "Next Day",
        "description": f"""The {client['name']} M365 tenant ({client['tenant_id']}) has {value} configured. Microsoft and CIS benchmark recommend 2-3 Global Admins maximum, plus one break-glass emergency account.

Why this matters:
Every Global Admin is a tier-0 identity. Compromise = total tenant takeover (mailboxes, OneDrive, all users, full audit log access, can disable other admins). Excessive GA = increased blast radius and SOX/HIPAA finding risk.

Remediation steps:
1. List current Global Admins:
   - https://entra.microsoft.com > Identity > Roles & admins > Global Administrator > Assignments
   - Or PowerShell: Get-MgDirectoryRoleMember -DirectoryRoleId <GA-role-id>
2. For each GA, ask: does this person actually need full Global Admin, or would a scoped role suffice?
   - Daily admin work usually needs: User Administrator + Privileged Role Administrator + Authentication Administrator
   - Mail/Calendar issues: Exchange Administrator
   - SharePoint/OneDrive: SharePoint Administrator
   - Teams: Teams Administrator
   - Audit/security review: Security Reader or Compliance Administrator
3. For users who do need GA temporarily, enable Privileged Identity Management (PIM) — they can elevate to GA with MFA + justification for a 4-8 hour window, instead of holding the role permanently.
4. Reduce permanent GA assignments to: 2-3 named accounts + 1 break-glass.
5. Document who has what role in clients/{client['code'].lower()}/data/admin-roles-{datetime.now().strftime('%Y-%m')}.md.

Verification:
- Re-run M365 compliance pull: 'Global Administrator Count' should change to PASS (<=3).
- Privileged Identity Management dashboard should show role activations rather than permanent assignments.

References:
- https://learn.microsoft.com/en-us/entra/identity/role-based-access-control/best-practices
- https://learn.microsoft.com/en-us/entra/id-governance/privileged-identity-management/pim-configure
""",
    }


def t_low_secure_score(client: dict, value: str) -> dict:
    return {
        "title": f"M365 Security: Improve Secure Score for {client['code']} ({value})",
        "priority": "When Convenient",
        "description": f"""Microsoft Secure Score for {client['name']} ({client['tenant_id']}) is at {value}. Technijian target is >=60% of available score.

Why this matters:
Secure Score is Microsoft's normalized scoring of identity, device, app, and data security posture. Low score correlates with measurable increase in incident likelihood. It's also tracked in audits (SOC 2, HIPAA, PCI).

Remediation steps:
1. Sign in to https://security.microsoft.com > Microsoft Secure Score.
2. Sort 'Improvement actions' by Score impact (descending).
3. For each action ranked High impact + Low effort, click through to see the specific gap and the recommended fix. Common quick wins:
   - Enable Self-Service Password Reset
   - Enable Sign-in risk policy (P2 only)
   - Enable User risk policy (P2 only)
   - Block the Outlook desktop client connecting via legacy auth
   - Enforce MFA for Outlook Web Access
   - Enable mailbox auditing
4. Track the score weekly. Aim for +5 points per week.
5. Document each action taken in clients/{client['code'].lower()}/data/secure-score-actions-{datetime.now().strftime('%Y-%m')}.md.

Notes:
- Some actions require additional licensing (Defender for Office 365 P2, Entra ID P2). Check available SKUs before committing.
- A few "third-party" actions (e.g. install endpoint protection) may already be satisfied by Huntress/CrowdStrike but Microsoft can't see that — you can mark them as 'Resolved through third party' to claim the points.

Verification:
- Re-run M365 compliance pull: 'Microsoft Secure Score' should improve.
- Secure Score history graph in Microsoft 365 Defender shows the trend.

References:
- https://learn.microsoft.com/en-us/microsoft-365/security/defender/microsoft-secure-score
""",
    }


def t_excessive_guests(client: dict, value: str) -> dict:
    return {
        "title": f"M365 Security: Audit Guest Accounts for {client['code']} ({value})",
        "priority": "Next Day",
        "description": f"""The {client['name']} M365 tenant ({client['tenant_id']}) has {value}. External guests need regular review — stale guests are a quiet attack surface.

Why this matters:
Each B2B guest is an external identity with some level of access to SharePoint sites, Teams channels, mailboxes, or shared documents. When the guest leaves their employer or their account is compromised, that access remains until explicitly revoked. This is a top finding in M365 audits.

Remediation steps:
1. Pull the full guest user list:
   - https://entra.microsoft.com > Users > All users > filter 'User type' = 'Guest'
   - Export to CSV with columns: UserPrincipalName, Mail, CreatedDateTime, lastSignInDateTime, AccountEnabled.
2. Identify guests who haven't signed in in 90+ days:
   - PowerShell: Get-MgAuditLogSignIn -Filter "createdDateTime ge ..." OR check 'Last interactive sign-in' on each guest
3. Coordinate with client to confirm which guests are still needed. For each one no longer required:
   - Block sign-in (Edit user > Block sign-in: Yes)
   - Wait 30 days for any objections, then delete.
4. Configure Access Reviews (Entra ID P2 required):
   - Identity Governance > Access Reviews > New
   - Scope: All guest users; recurring quarterly
   - Reviewers: Resource owners (Teams/SharePoint owners) or named admin
   - Auto-apply results so denied access is removed automatically.
5. Tighten guest invite settings:
   - Identity > External Identities > External collaboration settings
   - Guest invite restrictions: 'Only users assigned to specific admin roles can invite guest users' (or stricter).
   - Self-service sign up: Disabled unless explicitly needed.

Verification:
- Re-run M365 compliance pull: 'Guest User Count' should drop.
- Access Reviews dashboard shows recurring reviews completing.

References:
- https://learn.microsoft.com/en-us/entra/identity/users/users-restrict-guest-permissions
- https://learn.microsoft.com/en-us/entra/id-governance/access-reviews-overview
""",
    }


def t_storage_critical(client: dict, alert: dict) -> dict:
    name = alert.get("displayName", "")[:60]
    svc = (alert.get("service") or "").title()
    used = alert.get("storageUsedGB", 0)
    quota = alert.get("quotaGB", 0)
    pct = alert.get("pctUsed", 0)
    return {
        "title": f"M365 Storage CRITICAL: {svc} '{name}' at {pct:.1f}% for {client['code']}",
        "priority": "Critical" if pct >= 95 else "Same Day",
        "description": f"""URGENT: {svc} resource '{name}' in {client['name']} M365 tenant ({client['tenant_id']}) is at {pct:.1f}% of quota ({used:.1f} of {quota:.0f} GB).

Why this matters:
At >=90% the resource is at imminent risk of:
- Mailboxes: incoming mail begins to bounce (NDR sent to senders); user cannot send mail.
- OneDrive: Files App stops syncing locally, new uploads fail.
- SharePoint sites: file uploads and edits fail; document libraries become read-only.

Remediation steps:
1. Notify the resource owner. Email template:
   "Your {svc.lower()} '{name}' is currently at {pct:.1f}% of its {quota:.0f} GB quota.
   Mail/sync may stop working soon. Please archive or delete content within 48 hours."

2. Quick wins (do these first):
   - Mailbox: empty Deleted Items, archive 1+ year old emails to a PST or online archive (if licensed).
   - OneDrive: empty Recycle Bin (it counts against quota for 30 days), move large media files to SharePoint or local storage.
   - SharePoint: review largest files in 'Site contents' > 'Documents' > sort by Size descending; archive or delete.

3. If the user genuinely needs the space:
   - Mailbox: enable Online Archive (requires Exchange Online Archiving SKU or Microsoft 365 E3+). 100 GB additional capacity.
   - OneDrive: increase quota — Admin Center > SharePoint > More features > User profiles > Manage user profiles > select user > Set storage. Can go up to 5 TB on E3/E5.
   - SharePoint: increase site collection storage from Admin Center > Active sites > select site > Storage limit.

4. Record the resolution in the client's CP ticket history and update the M365 storage-summary.json on next pull.

Verification:
- Re-run M365 storage pull (technijian/m365-pull/scripts/pull_m365_storage.py --period D7).
- Resource should drop below 75%.

Time-sensitive: this resource may begin to fail within days at current growth rate. Treat as P1 if mail-bouncing impact is observed.
""",
    }


def t_storage_warn(client: dict, alert: dict) -> dict:
    name = alert.get("displayName", "")[:60]
    svc = (alert.get("service") or "").title()
    used = alert.get("storageUsedGB", 0)
    quota = alert.get("quotaGB", 0)
    pct = alert.get("pctUsed", 0)
    return {
        "title": f"M365 Storage Warn: {svc} '{name}' at {pct:.1f}% for {client['code']}",
        "priority": "Next Day",
        "description": f"""{svc} resource '{name}' in {client['name']} M365 tenant ({client['tenant_id']}) is at {pct:.1f}% ({used:.1f} of {quota:.0f} GB).

Why this matters:
At 75-89% utilization the resource is approaching quota. It will hit critical (>=90%) within weeks at typical growth rates. Proactive cleanup now is cheaper than emergency cleanup at 95%.

Remediation steps:
1. Email the resource owner — see template in any of the *_critical tickets — and ask them to clean up within 14 days.
2. Suggest standard cleanup:
   - Mailbox: empty Deleted Items, archive emails older than 1 year.
   - OneDrive: empty Recycle Bin, audit 'Files on Demand' usage so cloud-only files don't count locally.
   - SharePoint: identify largest files, move very-old project archives to a separate site or to Glacier/cold storage.
3. If growth continues, plan a storage upgrade SKU change at the next contract review.
4. Verify on next weekly storage pull (Monday 07:00 PT) that usage trends downward.
""",
    }


def t_brute_force(client: dict, threats: dict) -> dict:
    bf = (threats.get("brute_force_users") or [])[:10]
    bf_lines = "\n".join(f"  - {u.get('user','')} ({u.get('failures',0)} failed attempts)" for u in bf)
    return {
        "title": f"M365 Security: ACTIVE Brute-Force Attack against {client['code']} users",
        "priority": "Critical",
        "description": f"""ACTIVE THREAT: brute-force authentication attempts detected against {client['name']} M365 tenant ({client['tenant_id']}) over the last 30 days.

Top targets (10+ failed sign-ins each):
{bf_lines}

Why this matters:
A user account with 10+ failed sign-ins in 30 days is being actively attacked. If the account doesn't have MFA registered or enforced, the next successful guess is account takeover — and from there the attacker pivots to mailbox rules (forwarding/exfil), OneDrive data access, or BEC fraud against the client's contacts.

Immediate actions (within 4 hours):
1. For EACH targeted user:
   - Verify they have MFA registered (https://entra.microsoft.com > Users > select user > Authentication methods).
   - If not registered, force registration: enable MFA per-user, send the user the registration link, follow up by phone.
   - Force a password reset and revoke all active refresh tokens (https://entra.microsoft.com > Users > select user > Sessions > Revoke all sessions).
   - Review their sign-in logs for ANY successful sign-in in the last 30 days from an unknown IP. If found — assume compromise; do an inbox-rule audit and a OneDrive access audit.

2. Tenant-level CA policy block:
   - Identify the source IPs from sign-in logs (filter to failed sign-ins, group by IP address).
   - Add the top offending IPs as a Named Location ('Hostile IPs').
   - Create a CA policy: Block sign-in when location = 'Hostile IPs', users = All.
   - Cross-reference with other Technijian client tenants — same attacker IPs may be hitting multiple clients (see TECHNIJIAN report's cross-tenant IP findings).

3. Enable Sign-in Risk policy (Entra ID P2 required):
   - Protection > Conditional Access > Sign-in risk policy
   - Risk = Medium and above > Require MFA + password change.

4. Notify the client's IT contact. Document the timeline of the attack and Technijian's response in the ticket.

Verification:
- Re-run M365 security pull tomorrow. Brute-force flag should clear or substantially drop within 7-14 days.
- Failed sign-in count in sign-in logs should drop.

Source data: clients/{client['code'].lower()}/m365/2026-03-31/threat_summary.json
Full attack details (top 100 events): clients/{client['code'].lower()}/m365/2026-03-31/failed_signins.json

DO NOT close this ticket until each targeted user has been verified safe and MFA is enforced.
""",
    }


def t_password_spray(client: dict, threats: dict) -> dict:
    sp = (threats.get("password_spray_ips") or [])[:5]
    sp_lines = "\n".join(f"  - {s.get('ip','')} ({len(s.get('users_targeted', []))} users targeted)" for s in sp)
    return {
        "title": f"M365 Security: Password-Spray Attack against {client['code']}",
        "priority": "Critical",
        "description": f"""ACTIVE THREAT: password-spray attack detected against {client['name']} M365 tenant ({client['tenant_id']}). A small number of source IPs are attempting common passwords across many user accounts.

Source IPs and users targeted (top 5):
{sp_lines}

Why this matters:
Password spray is the inverse of brute-force: instead of many passwords against one user (which triggers lockout), the attacker tries one password against many users. It evades classic lockout policies and is the #1 successful attack pattern against M365 in 2025-2026 per Microsoft Threat Intelligence.

Immediate actions (within 4 hours):
1. Block each source IP at the tenant level (CA policy or Smart Lockout / Tenant Restrictions):
   - https://entra.microsoft.com > Protection > Named Locations > New
   - Add each source IP as a Trusted? = NO location, mark as 'Hostile IPs'.
   - Create CA policy: Block sign-in when location = Hostile IPs, users = All users (except break-glass).

2. Audit each targeted user list per IP:
   - Open clients/{client['code'].lower()}/m365/2026-03-31/threat_summary.json
   - For each user targeted, check whether ANY successful sign-in occurred from any unusual IP in the last 30 days.
   - If yes -> treat as potential compromise: force password reset, revoke sessions, audit inbox rules, audit data access.

3. Enable Smart Lockout if not already on:
   - Lockout threshold: 10 failed sign-ins
   - Lockout duration: 60 seconds (Microsoft recommends short lockouts for spray defense)
   - https://entra.microsoft.com > Protection > Authentication methods > Password protection.

4. Cross-tenant correlation: this same attacker IP may be active across multiple Technijian-managed tenants. Check the TECHNIJIAN M365 monthly report for cross-tenant IP overlap and add to a shared deny list if applicable.

5. Notify the client's IT contact via phone (not just email — email may be the attacker's channel).

Verification:
- Re-run M365 security pull tomorrow. Spray flag should clear within days once IPs are blocked.

Source: clients/{client['code'].lower()}/m365/2026-03-31/threat_summary.json
""",
    }


def t_foreign_success(client: dict, threats: dict) -> dict:
    fl = [f for f in (threats.get("foreign_logins") or []) if f.get("success")]
    countries = sorted({f["country"] for f in fl[:50]})
    return {
        "title": f"M365 Security: Successful Foreign Sign-ins in {client['code']}",
        "priority": "Same Day",
        "description": f"""Sign-in events from outside the United States with a successful authentication outcome were observed in {client['name']} M365 tenant ({client['tenant_id']}).

Countries observed: {', '.join(countries)}

Why this matters:
A successful foreign sign-in is either: (a) a legitimate user traveling, (b) a remote contractor, or (c) account takeover. The first two are routine; the third is a security incident. We must verify which of these applies.

Steps:
1. Pull the foreign sign-in list:
   - clients/{client['code'].lower()}/m365/2026-03-31/threat_summary.json -> 'foreign_logins' array (filter success=true)
   - For each entry: user, IP, country, timestamp.

2. For EACH user with a foreign successful sign-in:
   a. Contact the user via phone (not email — if compromised, the attacker reads email):
      "We saw a sign-in from <country> on <date>. Was this you?"
   b. If YES: confirm legitimate, document in this ticket, optionally add a CA policy carve-out for the user's known travel locations.
   c. If NO: assume compromise.
      - Force password reset.
      - Revoke all sessions: https://entra.microsoft.com > Users > <user> > Sessions > Revoke all sessions
      - Inbox-rule audit: https://outlook.office.com > Settings > Mail > Rules. Look for forwarding to external addresses; delete any.
      - Mailbox audit: https://compliance.microsoft.com > Audit > search for the user, last 30 days. Look for MailItemsAccessed, MessageSent, FileDownloaded events from the foreign IP.
      - Notify client management; engage Technijian SOC if BEC/exfil is suspected.

3. Configure baseline geo-restriction:
   - https://entra.microsoft.com > Protection > Named Locations > define 'Allowed Countries' (US + any legitimate countries).
   - CA policy: Block sign-in if location is NOT in 'Allowed Countries' (start in Report-only).

Verification:
- After remediation: foreign success flag should drop on next pull.
- Compromised user accounts (if any) confirmed clean.

Source: clients/{client['code'].lower()}/m365/2026-03-31/threat_summary.json
""",
    }


def t_legacy_auth_observed(client: dict) -> dict:
    return {
        "title": f"M365 Security: Legacy Auth Connections Observed in {client['code']}",
        "priority": "Next Day",
        "description": f"""Sign-in logs show clients still authenticating to {client['name']} M365 tenant ({client['tenant_id']}) via legacy protocols (Exchange ActiveSync, IMAP, POP3, SMTP, MAPI, or 'Other clients').

Why this matters:
These clients bypass Conditional Access and MFA. Even if you deploy a 'Block Legacy Authentication' policy (separate ticket), there may be some service accounts, multi-function printers, or older line-of-business apps still using these protocols. They need to be identified and migrated before the block goes live, or those services will silently fail.

Steps:
1. Pull the legacy sign-in list:
   - https://entra.microsoft.com > Monitoring > Sign-in logs > filter Client App = legacy values
   - Export the last 30 days as CSV.

2. Group by user / app to identify:
   - Service accounts (e.g. scanner@client.com, mfp01@client.com) -> migrate to Modern Auth + OAuth2 if possible, or rotate to managed identities.
   - Old smartphones / desktop clients -> push users to Outlook Mobile (which uses modern auth).
   - 3rd-party apps (legacy CRMs, scanners) -> contact the vendor for a modern-auth-capable version, or front them with a service like Microsoft 365 SMTP relay with OAuth.

3. Disable per-user/per-mailbox legacy protocols where modernized:
   - Exchange Admin Center > Mailboxes > select user > Email apps > disable POP, IMAP, SMTP, MAPI as appropriate.

4. Once usage is cleaned up, deploy the Block Legacy Authentication CA policy in Enforce mode.

Verification:
- Re-run M365 security pull. Legacy auth flag should drop or clear.
- 'Legacy Authentication Blocked' compliance check should change to PASS.

Source: clients/{client['code'].lower()}/m365/2026-03-31/threat_summary.json -> 'legacy_auth_logins' array.
""",
    }


def t_at_risk_signin(client: dict, events: list[dict]) -> dict:
    """One ticket per (client, user) with all atRisk events for that user listed."""
    user = events[0].get("userPrincipalName", "")
    event_lines = []
    for e in events:
        loc = e.get("location") or {}
        where = f"{loc.get('city','')}, {loc.get('countryOrRegion','')}".strip(", ")
        when = (e.get("activityDateTime", "") or "")[:19]
        ip = e.get("ipAddress", "")
        event_lines.append(f"  - {when}  IP {ip}  {where}")
    events_block = "\n".join(event_lines) if event_lines else "  (none)"

    return {
        "title": f"M365 Security: AtRisk Sign-in(s) for {user} ({client['code']})",
        "priority": "Same Day",
        "description": f"""Microsoft Identity Protection has flagged {len(events)} risky sign-in event(s) for this user in the {client['name']} M365 tenant ({client['tenant_id']}) that have NOT been remediated or dismissed.

User: {user}

Events (most recent first):
{events_block}

Why this matters:
'atRisk' = Identity Protection still considers the user as having an elevated risk of compromise. The event hasn't been confirmed as legitimate (which would dismiss it) or remediated (password reset). It will continue to cause downstream policy effects (e.g., Sign-in Risk CA policy challenges) until cleared.

Steps:
1. Verify with the user via phone (do NOT email — if compromised, the attacker reads email):
   "We saw {len(events)} sign-in attempt(s) flagged as risky over the past 30 days. Were you traveling, or did you change devices/browsers? See the event list above."

2. If ALL events were LEGITIMATE:
   - Sign in to https://entra.microsoft.com > Protection > Risky users > find the user
   - Click 'Confirm user safe' or 'Dismiss user risk'.
   - Document in this ticket.

3. If ANY event looks COMPROMISED (especially unfamiliar IP/location/device):
   - https://entra.microsoft.com > Protection > Risky users > select user > 'Confirm user compromised'
   - Force password reset.
   - Revoke all sessions: Users > {user} > Sessions > Revoke all sessions.
   - Audit inbox rules (https://outlook.office.com > Settings > Mail > Rules) — delete any forwarding rules.
   - Run a mailbox audit (https://compliance.microsoft.com > Audit) for the user, last 30 days.
   - If sensitive data was accessed -> escalate to Technijian SOC and notify the client.

4. After remediation, the riskState should change from 'atRisk' to 'remediated' or 'dismissed'.

Verification:
- Re-run M365 security pull. The event(s) should drop from risky_signins.json with riskState=atRisk.

Source: clients/{client['code'].lower()}/m365/2026-03-31/risky_signins.json
""",
    }


# ---------------------------------------------------------------------------
# Per-client ticket plan
# ---------------------------------------------------------------------------

def plan_tickets_for_client(client: dict, findings: dict) -> list[dict]:
    code = client["code"]
    plan: list[dict] = []

    # ---------- Compliance fails ----------
    comp = findings.get("compliance") or {}
    posture = comp.get("posture") or {}
    for c in posture.get("checks") or []:
        if c.get("status") != "fail":
            continue
        check = c.get("check", "")
        value = c.get("value", "")
        if check == "Legacy Authentication Blocked":
            plan.append(t_legacy_auth(client))
        elif check == "Conditional Access Policies":
            plan.append(t_no_ca_policies(client))
        elif check == "MFA Registration":
            plan.append(t_low_mfa(client, value))
        elif check == "Global Administrator Count":
            plan.append(t_too_many_admins(client, value))
        elif check == "Microsoft Secure Score":
            plan.append(t_low_secure_score(client, value))
        elif check == "Guest User Count":
            plan.append(t_excessive_guests(client, value))

    # ---------- Storage ----------
    storage = findings.get("storage") or {}
    for a in storage.get("alerts") or []:
        if a.get("severity") == "critical":
            plan.append(t_storage_critical(client, a))
        elif a.get("severity") == "warn":
            plan.append(t_storage_warn(client, a))

    # ---------- Threat flags ----------
    threats = findings.get("threats") or {}
    flags = threats.get("flags") or {}
    if flags.get("has_brute_force"):
        plan.append(t_brute_force(client, threats))
    if flags.get("has_password_spray"):
        plan.append(t_password_spray(client, threats))
    if flags.get("has_foreign_success"):
        plan.append(t_foreign_success(client, threats))
    if flags.get("has_legacy_auth"):
        plan.append(t_legacy_auth_observed(client))

    # ---------- At-risk risky sign-ins (one ticket per user with all their atRisk events) ----------
    risky = findings.get("risky_signins") or []
    at_risk = [r for r in risky if r.get("riskState") == "atRisk"]
    by_user: dict[str, list[dict]] = {}
    for event in at_risk:
        upn = event.get("userPrincipalName", "")
        by_user.setdefault(upn, []).append(event)
    for upn, events in by_user.items():
        # Sort newest first
        events.sort(key=lambda e: e.get("activityDateTime", ""), reverse=True)
        plan.append(t_at_risk_signin(client, events))

    return plan


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Create CP tickets for M365 findings")
    ap.add_argument("--month", help="YYYY-MM (default: current month)")
    ap.add_argument("--only", help="Comma-separated client codes")
    ap.add_argument("--skip", help="Comma-separated client codes to skip")
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan-only: show how many tickets would be created and the titles")
    ap.add_argument("--apply", action="store_true",
                    help="Actually create tickets in CP. Without this flag, runs in dry-run mode.")
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        print("Refusing to run without --dry-run or --apply. "
              "Run with --dry-run first to see the plan.")
        sys.exit(1)

    now = datetime.now(timezone.utc)
    month_str = args.month if args.month else now.strftime("%Y-%m")
    only = {c.strip().upper() for c in args.only.split(",")} if args.only else None
    skip = {c.strip().upper() for c in args.skip.split(",")} if args.skip else set()

    clients = load_clients(only, skip)
    if not clients:
        print("No clients in scope.")
        return

    print(f"M365 Ticket Creation | month: {month_str} | mode: "
          f"{'APPLY' if args.apply else 'DRY-RUN'} | tenants: {len(clients)}")
    print("")

    all_plans: list[tuple[dict, list[dict]]] = []
    total_tickets = 0
    for client in clients:
        findings = load_findings(client["code"], month_str)
        plan = plan_tickets_for_client(client, findings)
        all_plans.append((client, plan))
        total_tickets += len(plan)
        print(f"  {client['code']:<12} {len(plan)} ticket(s)")
        for t in plan:
            print(f"    [{t['priority']:<15}] {t['title']}")

    print(f"\nPlan total: {total_tickets} ticket(s) across {len(clients)} tenant(s).")

    if not args.apply:
        print("\nRun with --apply to actually create the tickets.")
        return

    # ---- Apply ----
    print("\nCreating tickets in Client Portal...")
    receipts: list[dict] = []
    failed: list[dict] = []
    for client, plan in all_plans:
        for t in plan:
            try:
                result = cp_tickets.create_ticket_for_code(
                    client["code"],
                    title=t["title"],
                    description=t["description"],
                    priority=t["priority"],
                )
                tid = result.get("ticket_id")
                receipts.append({
                    "client_code": client["code"],
                    "ticket_id": tid,
                    "title": t["title"],
                    "priority": t["priority"],
                })
                print(f"  [ok] {client['code']} #{tid} {t['title']}")
            except Exception as exc:
                failed.append({
                    "client_code": client["code"],
                    "title": t["title"],
                    "error": str(exc)[:300],
                })
                print(f"  [error] {client['code']} '{t['title']}': {exc}")
                traceback.print_exc()

    # Save receipts
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    receipt_path = STATE_DIR / f"tickets-{month_str}-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    receipt_path.write_text(json.dumps({
        "run_at": now.isoformat(),
        "month": month_str,
        "tickets_created": len(receipts),
        "tickets_failed": len(failed),
        "receipts": receipts,
        "failed": failed,
    }, indent=2), encoding="utf-8")
    print(f"\nDone. Created: {len(receipts)} | Failed: {len(failed)} | Receipt: {receipt_path}")


if __name__ == "__main__":
    main()
