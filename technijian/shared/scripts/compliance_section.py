"""Shared "Compliance Alignment" section renderer for monthly reports.

Reads ``clients/<slug>/_compliance.json`` (built by
``scripts/compliance/classify_clients.py``) and writes a branded section
explaining the regulatory framework(s) the client operates under and
how Technijian's monitoring stack supports those obligations.

Used by Huntress, CrowdStrike, ME EC, and Sophos monthly builders.

If the compliance file is missing, the section is skipped gracefully —
callers should not crash when a client hasn't been classified yet.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CLIENTS_ROOT = REPO_ROOT / "clients"


def load_compliance(slug: str) -> dict | None:
    path = CLIENTS_ROOT / slug / "_compliance.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# How Technijian's stack maps to each compliance framework. One bullet
# per framework, focused on what we actively contribute (not a full
# audit checklist).
FRAMEWORK_TO_SUPPORT = {
    "HIPAA": (
        "endpoint detection & response (Huntress + CrowdStrike), patch "
        "management (Endpoint Central), access auditing, and 24x7 incident "
        "response satisfy the technical safeguard requirements of 45 CFR "
        "§164.312 (access control, audit controls, integrity, transmission "
        "security)."
    ),
    "HITECH": (
        "automated detection of suspicious access events and Technijian's "
        "documented incident-response process keeps the breach-notification "
        "clock from running silently — any potential PHI exposure is "
        "investigated and timestamped within hours."
    ),
    "California CMIA": (
        "the same access-auditing and detection pipeline that supports HIPAA "
        "also covers California's stricter CMIA confidentiality requirements "
        "for medical information."
    ),
    "SOC 2": (
        "continuous monitoring, change tracking, patch evidence, and incident "
        "logs are produced monthly so SOC 2 Type II auditors can sample "
        "directly from the artifacts Technijian already generates."
    ),
    "GLBA": (
        "endpoint protection plus role-based access enforcement help satisfy "
        "the GLBA Safeguards Rule's information-security program "
        "requirements (16 CFR §314)."
    ),
    "PCI DSS": (
        "system patching, anti-malware, and continuous vulnerability "
        "monitoring satisfy PCI DSS 4.0 Requirements 5, 6, 11, and 12. "
        "Technijian's monthly reports are the audit evidence."
    ),
    "ABA Model Rule 1.6": (
        "EDR + identity threat detection block the kind of credential and "
        "data-exfiltration tradecraft that risks attorney-client privileged "
        "information; reasonable-effort protection is documented monthly."
    ),
    "State Bar Ethics": (
        "data-loss controls, encryption-at-rest enforcement, and incident "
        "monitoring address the technology-competence and confidentiality "
        "duties most state bars now enforce."
    ),
    "California CCPA": (
        "breach-detection and incident-response capabilities support CCPA "
        "§1798.150 reasonable-security obligations and the 72-hour "
        "notification window for incidents involving California-resident PII."
    ),
    "Fair Housing Act": (
        "audit logs around resident applicant data demonstrate the "
        "non-discrimination and recordkeeping controls the Fair Housing Act "
        "requires."
    ),
    "ITAR (if defense)": (
        "endpoint controls and access logging help support ITAR §126 "
        "technical-data export controls when applicable to the customer's "
        "contract scope."
    ),
    "CMMC (if DoD)": (
        "Endpoint Central inventory, patch evidence, and EDR detection "
        "logs map to multiple CMMC Level 1 and Level 2 practices "
        "(AC, AU, CM, IR, SI domains)."
    ),
    "FCRA": (
        "audit logging around access to consumer-report data supports the "
        "FCRA §607 permissible-purpose and accuracy obligations."
    ),
    "FTC Safeguards Rule (if dealer)": (
        "the same security-program controls that cover GLBA also satisfy "
        "the FTC Safeguards Rule for non-bank financial institutions "
        "(including auto dealers)."
    ),
    "EPA records": (
        "tamper-evident audit logs around recordkeeping systems support EPA "
        "regulatory document-retention requirements."
    ),
    "DOT regulations": (
        "EDR and access controls protect the systems holding driver-hour, "
        "manifest, and DOT-regulated records."
    ),
    "State charitable registration": (
        "donor-data protection controls and breach-detection capabilities "
        "support state charitable-registration security expectations."
    ),
    "SOC 2 (if customer-required)": (
        "the same continuous-monitoring artifacts (these monthly reports) "
        "are the evidence base most enterprise customers ask for during "
        "vendor SOC 2 reviews."
    ),
}


def render_section(doc, slug: str, brand) -> None:
    """Append a Compliance Alignment section to ``doc``.

    No-op (skipped silently) if the client has no ``_compliance.json``.
    """
    record = load_compliance(slug)
    if not record:
        return

    industry = record.get("industry") or "General Business"
    rationale = record.get("compliance_rationale") or ""
    sensitivity = record.get("data_sensitivity") or ""
    frameworks = record.get("compliance_scope") or []

    brand.add_section_header(doc, "Compliance Alignment")
    brand.add_body(
        doc,
        f"This client's industry classification is {industry}. Based on "
        f"that classification, the data Technijian's stack is helping "
        f"protect is most likely characterized as: {sensitivity}.",
    )

    if rationale:
        brand.add_body(doc, rationale, size=10.5)

    if frameworks:
        brand.add_body(
            doc,
            "How Technijian's monitoring stack supports each framework:",
            bold=True, size=11, color=brand.DARK_CHARCOAL,
        )
        for fw in frameworks:
            support = FRAMEWORK_TO_SUPPORT.get(fw)
            if not support:
                # Fallback — generic support statement
                support = (
                    "Technijian's continuous monitoring, access logging, and "
                    "incident-response posture address the underlying "
                    "security obligations."
                )
            brand.add_bullet(doc, support, bold_prefix=f"{fw}: ")

    brand.add_body(
        doc,
        "This classification was generated automatically from the client's "
        "name and contact-domain signals. If the industry or compliance "
        "scope shown here doesn't match your operations, please reply to "
        "this report and we'll update the classification — Technijian's "
        "team can also produce a deeper compliance-posture report on "
        "request.",
        size=9.5, color=brand.BRAND_GREY,
    )


__all__ = ["render_section", "load_compliance", "FRAMEWORK_TO_SUPPORT"]
