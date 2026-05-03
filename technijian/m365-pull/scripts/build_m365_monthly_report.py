"""Build branded monthly M365 activity reports per client.

For each tenant in gdap_status.csv that has data on disk, generate:
    clients/<code>/m365/reports/<YYYY-MM>/<CODE>-M365-Activity-<YYYY-MM>.docx

Sections (matched by proofreader):
    Executive Summary
    Identity & Access
    Storage Posture
    Sign-in Security
    Findings & Recommendations
    About This Report

Sources read per client:
    clients/<code>/m365/compliance/<YYYY-MM>/compliance_summary.json
    clients/<code>/m365/storage/<YYYY-Wnn>/storage_summary.json
    clients/<code>/m365/<YYYY-MM-DD>/pull_summary.json + threat_summary.json

Usage:
    python build_m365_monthly_report.py                  # current month, all
    python build_m365_monthly_report.py --month 2026-04
    python build_m365_monthly_report.py --only BWH,ORX
    python build_m365_monthly_report.py --skip JDH
    python build_m365_monthly_report.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
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

SHARED = REPO / "technijian" / "shared" / "scripts"
sys.path.insert(0, str(SHARED))
import _brand as brand  # noqa: E402

PROOFREADER = SHARED / "proofread_docx.py"
EXPECTED_SECTIONS = ("Executive Summary,Identity & Access,License Inventory,"
                     "Storage Posture,Sign-in Security,Findings & Recommendations,"
                     "About This Report")

# Friendly display names for common M365 SKU part numbers
_SKU_NAMES: dict[str, str] = {
    "SPE_E1": "Microsoft 365 E1",
    "SPE_E3": "Microsoft 365 E3",
    "SPE_E5": "Microsoft 365 E5",
    "O365_BUSINESS_ESSENTIALS": "Microsoft 365 Business Basic",
    "O365_BUSINESS_PREMIUM": "Microsoft 365 Business Standard",
    "SPB": "Microsoft 365 Business Premium",
    "ENTERPRISEPACK": "Office 365 E3",
    "ENTERPRISEPREMIUM": "Office 365 E5",
    "STANDARDPACK": "Office 365 E1",
    "EXCHANGESTANDARD": "Exchange Online Plan 1",
    "EXCHANGEENTERPRISE": "Exchange Online Plan 2",
    "AAD_PREMIUM": "Azure AD Premium P1",
    "AAD_PREMIUM_P2": "Azure AD Premium P2",
    "POWER_BI_PRO": "Power BI Pro",
    "POWER_BI_STANDARD": "Power BI (free)",
    "Microsoft_365_Copilot": "Microsoft 365 Copilot",
    "VISIOCLIENT": "Visio Plan 2",
    "PROJECTPREMIUM": "Project Plan 5",
    "PROJECTPROFESSIONAL": "Project Plan 3",
    "INTUNE_A": "Microsoft Intune Plan 1",
    "EMS": "Enterprise Mobility + Security E3",
    "EMSPREMIUM": "Enterprise Mobility + Security E5",
    "MDATP_XPLAT": "Microsoft Defender for Endpoint P2",
    "THREAT_INTELLIGENCE": "Microsoft Defender for Office 365 P2",
    "STREAM": "Microsoft Stream",
    "WINDOWS_STORE": "Windows Store for Business",
    "MCOSTANDARD": "Skype for Business Online Plan 2",
    "TEAMS_FREE": "Microsoft Teams (free)",
    "TEAMS_EXPLORATORY": "Microsoft Teams Exploratory",
}


# ---------------------------------------------------------------------------
# Data loading
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
            out.append({
                "code": code,
                "name": row.get("client_name", code),
                "tenant_id": row["tenant_id"].strip(),
                "notes": row.get("notes", ""),
            })
    return out


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_latest_dir(parent: Path, pattern: str) -> Path | None:
    if not parent.exists():
        return None
    matches = sorted(parent.glob(pattern), reverse=True)
    return matches[0] if matches else None


def load_client_data(code: str, month_str: str) -> dict[str, Any]:
    """Pull the latest compliance, storage, security data for one client."""
    base = CLIENTS_ROOT / code.lower() / "m365"
    data: dict[str, Any] = {
        "code": code,
        "month": month_str,
        "compliance": None,
        "storage": None,
        "security": None,
        "threats": None,
        "risky_signins": [],
        "mailbox_usage": [],
        "onedrive_usage": [],
        "sharepoint_usage": [],
        "subscribed_skus": [],
        "user_licenses": [],
        "available": False,
    }

    # Compliance
    comp_dir = base / "compliance" / month_str
    summary_p = comp_dir / "compliance_summary.json"
    data["compliance"] = _load_json(summary_p)
    data["subscribed_skus"] = _load_json(comp_dir / "subscribed_skus.json") or []
    data["user_licenses"] = _load_json(comp_dir / "user_licenses.json") or []

    # Storage — pick the latest week dir
    storage_root = base / "storage"
    latest_storage = _find_latest_dir(storage_root, "2026-W*") if storage_root.exists() else None
    if latest_storage:
        data["storage"] = _load_json(latest_storage / "storage_summary.json")
        data["mailbox_usage"] = _load_json(latest_storage / "mailbox_usage.json") or []
        data["onedrive_usage"] = _load_json(latest_storage / "onedrive_usage.json") or []
        data["sharepoint_usage"] = _load_json(latest_storage / "sharepoint_usage.json") or []
        data["storage_week"] = latest_storage.name

    # Security — pick the latest dated dir under m365/
    if base.exists():
        sec_dirs = sorted(
            (d for d in base.iterdir() if d.is_dir() and d.name.startswith("2026-")),
            reverse=True
        )
        if sec_dirs:
            sec_dir = sec_dirs[0]
            data["security"] = _load_json(sec_dir / "pull_summary.json")
            data["threats"] = _load_json(sec_dir / "threat_summary.json")
            data["risky_signins"] = _load_json(sec_dir / "risky_signins.json") or []
            data["security_dir"] = sec_dir.name

    data["available"] = bool(data["compliance"] or data["storage"] or data["security"])
    return data


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _posture_color(status: str):
    s = (status or "").lower()
    if s == "fail":
        return brand.RED
    if s == "warn":
        return brand.CORE_ORANGE
    return brand.GREEN


def _alert_badge(flags: dict) -> tuple[str, Any]:
    """Return (label, color) summarizing threat flags."""
    if not flags:
        return ("No data", brand.BRAND_GREY)
    actv = [k for k, v in flags.items() if v]
    if not actv:
        return ("Clean", brand.GREEN)
    if any(k in actv for k in ("has_brute_force", "has_password_spray")):
        return (f"{len(actv)} threats", brand.RED)
    return (f"{len(actv)} alerts", brand.CORE_ORANGE)


def section_executive_summary(doc, client: dict, data: dict) -> None:
    brand.add_section_header(doc, "Executive Summary")

    name = client["name"]
    month = data["month"]
    brand.add_body(doc,
        f"This report summarizes Microsoft 365 security, compliance, and "
        f"storage posture for {name} for the month ending {month}. "
        f"It is generated from Microsoft Graph API data captured via "
        f"Technijian's GDAP partner relationship and Cloud Solution "
        f"Provider access.")

    # Metric cards: posture | signins | failed | alerts
    comp = data.get("compliance") or {}
    posture = comp.get("posture") or {}
    overall = posture.get("overall", "n/a").upper() or "N/A"
    posture_color = _posture_color(posture.get("overall"))

    sec = data.get("security") or {}
    counts = sec.get("counts") or {}
    total_signins = counts.get("total_signins", 0)
    failed_signins = counts.get("failed_signins", 0)

    threats = data.get("threats") or {}
    flags = threats.get("flags") if threats else {}
    alert_label, alert_color = _alert_badge(flags or {})

    storage = data.get("storage") or {}
    storage_alerts = storage.get("alert_counts") or {}
    crit_count = storage_alerts.get("critical", 0)
    warn_count = storage_alerts.get("warn", 0)
    storage_total = crit_count + warn_count
    storage_label = "Healthy" if storage_total == 0 else f"{crit_count} crit / {warn_count} warn"
    storage_color = brand.GREEN if storage_total == 0 else (brand.RED if crit_count else brand.CORE_ORANGE)

    cards = [
        (overall, "Compliance Posture", posture_color),
        (f"{total_signins:,}", "Sign-in Events (30d)", brand.CORE_BLUE),
        (f"{failed_signins:,}", "Failed Sign-ins", brand.RED if failed_signins > 100 else brand.BRAND_GREY),
        (alert_label, "Threat Flags", alert_color),
    ]
    brand.add_metric_card_row(doc, cards)
    doc.add_paragraph()

    # High-level callout summarizing the most urgent thing
    callout_lines = []
    if crit_count:
        callout_lines.append(f"{crit_count} resource(s) at >=90% storage quota — risk of mail/sync failure.")
    if flags and any(flags.get(k) for k in ("has_brute_force", "has_password_spray")):
        callout_lines.append("Active brute-force or password-spray attempt(s) detected against user accounts.")
    risky = data.get("risky_signins") or []
    at_risk = [r for r in risky if r.get("riskState") == "atRisk"]
    if at_risk:
        callout_lines.append(f"{len(at_risk)} risky sign-in event(s) currently at-risk and not remediated.")
    if posture.get("overall") == "fail":
        fail_count = posture.get("fail_count", 0)
        callout_lines.append(f"{fail_count} compliance check(s) failing — see Identity & Access section.")
    if not callout_lines:
        callout_lines.append("No critical findings this period.")

    brand.add_callout_box(doc, "  ".join(callout_lines))
    doc.add_paragraph()


def section_identity_access(doc, client: dict, data: dict) -> None:
    brand.add_section_header(doc, "Identity & Access")

    comp = data.get("compliance")
    if not comp:
        brand.add_body(doc,
            "No compliance data was available for this tenant during this "
            "reporting period. See the About This Report section for context.")
        return

    posture = comp.get("posture") or {}
    checks = posture.get("checks") or []

    brand.add_body(doc,
        "Microsoft Graph reports the following identity, access, and "
        "compliance posture against Technijian's baseline. Items flagged "
        "as Fail or Warn are summarized in the Findings section.")

    if not checks:
        brand.add_body(doc, "No posture checks recorded.")
        return

    # Status column rendering: "PASS" / "WARN" / "FAIL"
    rows = []
    for c in checks:
        status_label = (c.get("status") or "").upper()
        rows.append([
            c.get("check", ""),
            status_label,
            c.get("value", ""),
            c.get("detail", ""),
        ])

    brand.styled_table(
        doc,
        headers=["Check", "Status", "Result", "Best Practice"],
        rows=rows,
        col_widths=[1.6, 0.7, 1.6, 2.5],
        status_col=1,
    )
    doc.add_paragraph()


def section_license_inventory(doc, client: dict, data: dict) -> None:
    brand.add_section_header(doc, "License Inventory")

    skus = data.get("subscribed_skus") or []
    user_licenses = data.get("user_licenses") or []

    if not skus:
        brand.add_body(doc,
            "No license subscription data was available for this tenant "
            "during this reporting period.")
        return

    # Build sku_id -> user list index for fast lookup
    sku_user_map: dict[str, list[str]] = {}
    for u in user_licenses:
        upn = u.get("userPrincipalName", "")
        for sku_id in (u.get("skuIds") or []):
            sku_user_map.setdefault(sku_id, []).append(upn)

    # Filter to paid/countable SKUs — skip unlimited free tiers and suspended
    UNLIMITED = 1_000  # viral/free plans (FLOW_FREE, CCIBOTS_VIRAL, etc.) allocate 10k+
    _FREE_PARTS = {"FREE", "VIRAL", "EXPLORATORY", "TRIAL", "PRIVPREV"}

    paid_skus = []
    for sku in skus:
        prepaid = sku.get("prepaidUnits") or {}
        purchased = prepaid.get("enabled", 0)
        part = sku.get("skuPartNumber", "").upper()
        if purchased >= UNLIMITED:
            continue  # free-tier / viral / unlimited seats
        if any(tok in part for tok in _FREE_PARTS):
            continue  # viral preview or free tier by name
        if sku.get("capabilityStatus") in ("Warning", "Deleted"):
            continue
        paid_skus.append(sku)

    if not paid_skus:
        brand.add_body(doc,
            "No countable paid license SKUs found for this tenant.")
        return

    brand.add_body(doc,
        "Summary of all Microsoft 365 license subscriptions — purchased seats, "
        "assigned seats, and available (unassigned) seats that could be "
        "returned or reduced at next renewal.")

    # Summary table
    total_purchased = total_assigned = total_free = 0
    summary_rows = []
    skus_with_free: list[dict] = []

    for sku in sorted(paid_skus, key=lambda s: s.get("skuPartNumber", "")):
        part_num = sku.get("skuPartNumber", "")
        display = _SKU_NAMES.get(part_num, part_num)
        prepaid = sku.get("prepaidUnits") or {}
        purchased = prepaid.get("enabled", 0)
        assigned = sku.get("consumedUnits", 0)
        free = max(0, purchased - assigned)
        sku_id = sku.get("skuId", "")

        total_purchased += purchased
        total_assigned += assigned
        total_free += free

        if free > 0:
            status = "UNUSED SEATS"
            skus_with_free.append({
                "display": display,
                "sku_id": sku_id,
                "purchased": purchased,
                "assigned": assigned,
                "free": free,
                "users": sku_user_map.get(sku_id, []),
            })
        else:
            status = "FULLY USED"

        summary_rows.append([display, str(purchased), str(assigned), str(free), status])

    # Totals row
    summary_rows.append([
        "TOTAL",
        str(total_purchased),
        str(total_assigned),
        str(total_free),
        f"{total_free} seats available",
    ])

    brand.styled_table(
        doc,
        headers=["License / SKU", "Purchased", "Assigned", "Free", "Status"],
        rows=summary_rows,
        col_widths=[2.8, 0.8, 0.8, 0.6, 1.5],
        status_col=4,
    )
    doc.add_paragraph()

    if total_free == 0:
        brand.add_callout_box(doc,
            "All purchased licenses are fully assigned. No seats available "
            "for reduction at this time.",
            accent_hex=brand.GREEN_HEX, bg_hex="EAF7EE")
        doc.add_paragraph()
        return

    # Per-SKU user lists for SKUs with unused seats
    brand.add_body(doc,
        "License holders for SKUs with unassigned seats:",
        bold=True, color=brand.DARK_CHARCOAL)
    brand.add_body(doc,
        "Review each list below. Users who no longer need the license can be "
        "unassigned in the Microsoft 365 Admin Center to reduce costs at renewal.",
        color=brand.BRAND_GREY)
    doc.add_paragraph()

    for item in skus_with_free:
        brand.add_body(doc,
            f"{item['display']}  —  {item['assigned']} assigned, "
            f"{item['free']} of {item['purchased']} seats available",
            bold=True, color=brand.CORE_BLUE)
        users = item["users"]
        if users:
            user_rows = [[u] for u in sorted(users)[:50]]
            brand.styled_table(
                doc,
                headers=["User Principal Name"],
                rows=user_rows,
                col_widths=[6.5],
            )
        else:
            brand.add_body(doc,
                "No users currently assigned to this SKU "
                "(consumed count may reflect service accounts).",
                color=brand.BRAND_GREY)
        doc.add_paragraph()


def section_storage(doc, client: dict, data: dict) -> None:
    brand.add_section_header(doc, "Storage Posture")

    storage = data.get("storage")
    if not storage:
        brand.add_body(doc, "No storage data was available for this tenant.")
        return

    brand.add_body(doc,
        "Microsoft 365 mailbox, OneDrive, and SharePoint storage usage "
        "as reported by the M365 reporting service. Resources at 90% or "
        "above of quota are critical and may begin to fail.")

    alerts = storage.get("alerts") or []
    if not alerts:
        brand.add_callout_box(doc,
            "All mailboxes, OneDrive accounts, and SharePoint sites are below the "
            "75% usage threshold. No action required this period.",
            accent_hex=brand.GREEN_HEX, bg_hex="EAF7EE")
        doc.add_paragraph()
        return

    # Top alerts table (limit to 25 to keep page count sane)
    rows = []
    for a in alerts[:25]:
        sev = (a.get("severity") or "").upper()
        used = a.get("storageUsedGB", 0)
        quota = a.get("quotaGB", 0)
        pct = a.get("pctUsed", 0)
        rows.append([
            a.get("service", ""),
            a.get("displayName", "")[:40],
            f"{used:.1f} / {quota:.0f} GB",
            f"{pct:.1f}%",
            sev,
        ])

    brand.styled_table(
        doc,
        headers=["Service", "Resource", "Used / Quota", "% Used", "Severity"],
        rows=rows,
        col_widths=[1.0, 2.4, 1.4, 0.8, 0.8],
        status_col=4,
    )
    doc.add_paragraph()

    if len(alerts) > 25:
        brand.add_body(doc,
            f"Showing top 25 of {len(alerts)} flagged resources. Full list "
            f"in the underlying JSON snapshot.", color=brand.BRAND_GREY)


def section_signin_security(doc, client: dict, data: dict) -> None:
    brand.add_section_header(doc, "Sign-in Security")

    sec = data.get("security")
    threats = data.get("threats") or {}

    if not sec or sec.get("counts", {}).get("total_signins", 0) == 0:
        # Either no premium license OR genuinely zero signins.
        notes = (client.get("notes") or "")
        if any(s in notes.lower() for s in ("not in scope", "pending app consent")):
            brand.add_body(doc,
                "Sign-in security data is pending — admin consent has not yet "
                "been granted for this tenant.")
            return
        brand.add_body(doc,
            "No detailed sign-in audit log data was available for this "
            "tenant. This typically indicates the tenant lacks an Azure AD "
            "Premium P1 or P2 license, which is required for the sign-in "
            "audit log API endpoint. The compliance posture section above "
            "still reflects the available identity data.")
        return

    counts = sec.get("counts") or {}
    total = counts.get("total_signins", 0)
    failed = counts.get("failed_signins", 0)
    risky = counts.get("risky_signins", 0)
    pct_failed = (failed / total * 100) if total else 0

    brand.add_body(doc,
        f"During the 30-day window ending {data.get('security_dir', data['month'])}, "
        f"this tenant logged {total:,} sign-in events with {failed:,} "
        f"({pct_failed:.1f}%) failing authentication. {risky} risky sign-in "
        f"event(s) were flagged by Microsoft Identity Protection.")

    # Threat flag table
    flags = threats.get("flags") or {}
    flag_rows = [
        ["Brute-force activity", "FAIL" if flags.get("has_brute_force") else "PASS",
         "10+ failures against a single user in the window"],
        ["Password spray", "FAIL" if flags.get("has_password_spray") else "PASS",
         "5+ users targeted from a single IP"],
        ["Successful foreign sign-in", "FAIL" if flags.get("has_foreign_success") else "PASS",
         "Successful login from outside the United States"],
        ["Legacy authentication", "FAIL" if flags.get("has_legacy_auth") else "PASS",
         "Bypasses MFA — should be blocked via Conditional Access"],
        ["High MFA failure rate", "FAIL" if flags.get("high_mfa_failures") else "PASS",
         "5+ MFA failures observed (potential MFA fatigue attack)"],
    ]
    brand.styled_table(
        doc,
        headers=["Threat Indicator", "Status", "Detection Rule"],
        rows=flag_rows,
        col_widths=[2.1, 0.8, 3.6],
        status_col=1,
    )
    doc.add_paragraph()

    # Top brute-force targets
    bf = threats.get("brute_force_users") or []
    if bf:
        brand.add_body(doc, "Top brute-force targets:", bold=True, color=brand.DARK_CHARCOAL)
        bf_rows = [[u.get("user", ""), str(u.get("failures", 0))] for u in bf[:10]]
        brand.styled_table(
            doc,
            headers=["User", "Failed Attempts"],
            rows=bf_rows,
            col_widths=[4.5, 2.0],
        )
        doc.add_paragraph()

    # Password spray IPs
    spray = threats.get("password_spray_ips") or []
    if spray:
        brand.add_body(doc, "Password-spray source IPs:", bold=True, color=brand.DARK_CHARCOAL)
        spray_rows = [[s.get("ip", ""), str(len(s.get("users_targeted", [])))]
                      for s in spray[:10]]
        brand.styled_table(
            doc,
            headers=["Source IP", "Users Targeted"],
            rows=spray_rows,
            col_widths=[3.0, 2.0],
        )
        doc.add_paragraph()

    # Risky sign-ins still at-risk
    risky_list = data.get("risky_signins") or []
    at_risk = [r for r in risky_list if r.get("riskState") == "atRisk"]
    if at_risk:
        brand.add_body(doc,
            f"{len(at_risk)} risky sign-in event(s) currently at-risk "
            f"(not remediated or dismissed):",
            bold=True, color=brand.DARK_CHARCOAL)
        rows = []
        for r in at_risk[:10]:
            loc = r.get("location") or {}
            rows.append([
                r.get("userPrincipalName", "")[:30],
                r.get("ipAddress", ""),
                f"{loc.get('city','')}, {loc.get('countryOrRegion','')}".strip(", "),
                (r.get("activityDateTime", "") or "")[:10],
            ])
        brand.styled_table(
            doc,
            headers=["User", "IP Address", "Location", "Date"],
            rows=rows,
            col_widths=[2.0, 1.4, 1.7, 1.0],
        )
        doc.add_paragraph()


def section_findings(doc, client: dict, data: dict) -> None:
    brand.add_section_header(doc, "Findings & Recommendations")

    findings: list[tuple[str, str, str]] = []  # (priority, title, action)

    comp = data.get("compliance") or {}
    posture = comp.get("posture") or {}
    for c in posture.get("checks") or []:
        if c.get("status") == "fail":
            check = c.get("check", "")
            value = c.get("value", "")
            if check == "MFA Registration":
                findings.append(("P2",
                    f"MFA registration low at {value}",
                    "Run an enrollment campaign — every user must register MFA. "
                    "Plan: registration policy + email + 30-day grace + force at login."))
            elif check == "Legacy Authentication Blocked":
                findings.append(("P1",
                    "Legacy auth not blocked",
                    "Add Conditional Access policy 'Block Legacy Authentication' "
                    "(targets all users, all cloud apps, client apps = legacy). "
                    "This bypasses MFA and is the #1 path for credential compromise."))
            elif check == "Conditional Access Policies":
                findings.append(("P2",
                    "No Conditional Access policies configured",
                    "Deploy baseline CA: block legacy auth, require MFA for admins, "
                    "require compliant device for sensitive apps."))
            elif check == "Global Administrator Count":
                findings.append(("P2",
                    f"{value} — too many",
                    "Reduce to 2-3 named Global Admins + emergency break-glass. "
                    "Move others to Privileged Role Admin or scoped roles."))
            elif check == "Microsoft Secure Score":
                findings.append(("P3",
                    f"Secure Score {value}",
                    "Review the Microsoft Secure Score dashboard for tenant-specific "
                    "improvement actions ranked by impact and effort."))
            elif check == "Guest User Count":
                findings.append(("P3",
                    f"{value} guest accounts",
                    "Audit external collaboration. Remove inactive guests, enable "
                    "guest access reviews, restrict guest invite to specific users."))

    storage = data.get("storage") or {}
    for a in (storage.get("alerts") or []):
        if a.get("severity") == "critical":
            findings.append(("P1",
                f"{a.get('service','').title()} '{a.get('displayName','')[:40]}' at {a.get('pctUsed',0):.1f}%",
                "Approaching quota. Open CP ticket: archive old data, increase "
                "storage SKU, or migrate large items to SharePoint/OneDrive shared site."))

    threats = data.get("threats") or {}
    flags = threats.get("flags") or {}
    if flags.get("has_brute_force"):
        bf = (threats.get("brute_force_users") or [])[:3]
        users = ", ".join(u.get("user", "") for u in bf)
        findings.append(("P1",
            "Active brute-force attempts in progress",
            f"Targeted accounts: {users}. Verify MFA enforcement, consider "
            "tenant-level CA block on attacker IPs (see Sign-in Security section)."))
    if flags.get("has_password_spray"):
        findings.append(("P1",
            "Password-spray attack detected",
            "A single IP attempted credential stuffing across multiple users. "
            "Add the source IP(s) to a Conditional Access deny list."))
    if flags.get("has_foreign_success"):
        findings.append(("P2",
            "Successful sign-in from non-US country",
            "Confirm with each affected user. If not authorized, force password "
            "reset, revoke active sessions, and review what was accessed."))
    if flags.get("has_legacy_auth"):
        findings.append(("P2",
            "Legacy auth client connections observed",
            "Some clients are still authenticating via SMTP/IMAP/POP3/EAS without "
            "modern auth. Identify devices and migrate to modern protocols."))

    risky = data.get("risky_signins") or []
    at_risk = [r for r in risky if r.get("riskState") == "atRisk"]
    if at_risk:
        users = sorted({r.get("userPrincipalName", "") for r in at_risk})[:5]
        findings.append(("P1",
            f"{len(at_risk)} unresolved risky sign-in(s) flagged by Identity Protection",
            f"Affected users: {', '.join(users)}. Verify each was the user; "
            "if compromised, force password reset, revoke sessions, investigate."))

    if not findings:
        brand.add_callout_box(doc,
            "No actionable findings this period. Continue monitoring per the "
            "established cadence.",
            accent_hex=brand.GREEN_HEX, bg_hex="EAF7EE")
        doc.add_paragraph()
        return

    # Sort by priority
    pri_order = {"P1": 0, "P2": 1, "P3": 2}
    findings.sort(key=lambda f: pri_order.get(f[0], 9))

    rows = [[p, title, action] for p, title, action in findings]
    brand.styled_table(
        doc,
        headers=["Priority", "Finding", "Recommended Action"],
        rows=rows,
        col_widths=[0.7, 2.0, 3.8],
        status_col=0,
    )
    doc.add_paragraph()


def section_about(doc, client: dict, data: dict) -> None:
    brand.add_section_header(doc, "About This Report")

    brand.add_body(doc,
        "This report is automatically generated each month from Microsoft "
        "Graph API data captured via Technijian's Cloud Solution Provider "
        "and GDAP (Granular Delegated Admin Privileges) partner relationships.")

    brand.add_body(doc,
        "Data sources & cadences:", bold=True, color=brand.DARK_CHARCOAL)
    brand.add_bullet(doc, "Daily 06:00 PT — sign-in audit logs (last 24h)",
        bold_prefix="Security pull: ")
    brand.add_bullet(doc, "Weekly Mon 07:00 PT — MFA, Conditional Access, admin roles, secure score",
        bold_prefix="Compliance pull: ")
    brand.add_bullet(doc, "Weekly Mon 07:00 PT — mailbox, OneDrive, SharePoint usage (D7)",
        bold_prefix="Storage pull: ")
    brand.add_bullet(doc, "Monthly 1st 07:30 PT — D180 storage trend",
        bold_prefix="Trend pull: ")

    brand.add_body(doc,
        "Definitions:", bold=True, color=brand.DARK_CHARCOAL)
    brand.add_bullet(doc, "Authentication failure where status.errorCode != 0 (wrong password, MFA fail, blocked, etc).",
        bold_prefix="Failed sign-in: ")
    brand.add_bullet(doc, "10 or more failed sign-ins against a single user account within the window.",
        bold_prefix="Brute-force flag: ")
    brand.add_bullet(doc, "5 or more distinct users targeted from a single source IP.",
        bold_prefix="Password spray flag: ")
    brand.add_bullet(doc, "Authenticated sign-in originating from outside the United States.",
        bold_prefix="Foreign success flag: ")
    brand.add_bullet(doc, "Connection via Exchange ActiveSync, IMAP, POP3, SMTP — bypasses MFA.",
        bold_prefix="Legacy auth flag: ")
    brand.add_bullet(doc, "Risky sign-in flagged by Microsoft Identity Protection (Azure AD Premium P2 only).",
        bold_prefix="Risky sign-in: ")

    notes = client.get("notes", "")
    tenant_id = client["tenant_id"]
    brand.add_body(doc,
        f"Tenant: {client['name']} ({tenant_id})",
        size=9, color=brand.BRAND_GREY)
    if notes:
        brand.add_body(doc, f"Notes: {notes}",
            size=9, color=brand.BRAND_GREY)

    brand.add_body(doc,
        "Questions about this report? Email support@technijian.com.",
        color=brand.BRAND_GREY)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_one_report(client: dict, month_str: str, dry_run: bool) -> Path | None:
    code = client["code"]
    data = load_client_data(code, month_str)

    # Skip tenants whose CSV row indicates the app has not yet been consented.
    # Their on-disk data (if any) is just error stubs from earlier failed pulls.
    notes = (client.get("notes") or "").lower()
    if "pending app consent" in notes:
        print(f"  [skip] {code} — pending app consent ({client.get('notes','')})")
        return None

    if not data["available"]:
        print(f"  [skip] {code} — no M365 data on disk")
        return None

    # If compliance only contains errors (no real posture checks), skip too —
    # this prevents misleading reports for tenants where every API call failed.
    comp = data.get("compliance") or {}
    posture = comp.get("posture") or {}
    has_real_data = (bool(posture.get("checks"))
                     or bool(data.get("storage"))
                     or bool((data.get("security") or {}).get("counts")))
    if not has_real_data:
        print(f"  [skip] {code} — only error stubs on disk, no real data")
        return None

    if dry_run:
        avail = ", ".join(k for k in ("compliance", "storage", "security") if data.get(k))
        print(f"  [dry-run] {code} — would build report. Available data: {avail}")
        return None

    out_dir = CLIENTS_ROOT / code.lower() / "m365" / "reports" / month_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{code}-M365-Activity-{month_str}.docx"

    doc = brand.new_branded_document()
    brand.render_cover(
        doc,
        title="M365 Activity Report",
        subtitle=client["name"],
        footer_note=("Confidential — prepared by Technijian for the addressee only."),
        date_text=f"Reporting period: {month_str}",
    )
    brand.add_page_break(doc)

    section_executive_summary(doc, client, data)
    section_identity_access(doc, client, data)
    section_license_inventory(doc, client, data)
    section_storage(doc, client, data)
    section_signin_security(doc, client, data)
    section_findings(doc, client, data)
    section_about(doc, client, data)

    doc.save(str(out_path))
    print(f"  [ok] {code} -> {out_path.relative_to(REPO)}")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Build branded M365 monthly reports")
    ap.add_argument("--month", help="YYYY-MM (default: current month)")
    ap.add_argument("--only", help="Comma-separated client codes")
    ap.add_argument("--skip", help="Comma-separated client codes to skip")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    month_str = args.month if args.month else now.strftime("%Y-%m")
    only = {c.strip().upper() for c in args.only.split(",")} if args.only else None
    skip = {c.strip().upper() for c in args.skip.split(",")} if args.skip else set()

    clients = load_clients(only, skip)
    if not clients:
        print("No clients in gdap_status.csv match the filter.")
        return

    print(f"M365 Monthly Reports | month: {month_str} | tenants: {len(clients)}")

    generated: list[Path] = []
    for client in clients:
        try:
            p = build_one_report(client, month_str, args.dry_run)
            if p:
                generated.append(p)
        except Exception as exc:
            print(f"  [error] {client['code']}: {exc}")
            traceback.print_exc()

    if args.dry_run:
        return

    if not generated:
        print("\nNo reports generated.")
        return

    print(f"\nProofreading {len(generated)} report(s)...")
    sys.stdout.flush()
    rc = subprocess.run(
        [sys.executable, str(PROOFREADER),
         "--sections", EXPECTED_SECTIONS, "--quiet"]
        + [str(p) for p in generated]
    ).returncode
    if rc != 0:
        print("[proofread] FAILED — one or more reports did not pass the gate.")
        sys.exit(rc)
    print(f"[proofread] OK — all {len(generated)} report(s) passed.")


if __name__ == "__main__":
    main()
