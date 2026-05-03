"""Classify each active client by industry and likely compliance scope.

Reads ``clients/<slug>/_meta.json`` (Location_Name + recipient email
domains) and writes ``clients/<slug>/_compliance.json`` with::

    {
      "industry": "Healthcare",
      "industry_evidence": "Name contains 'MD' / 'medical' / ...",
      "primary_domain": "<example.com>" | null,
      "compliance_scope": ["HIPAA", "HITECH"],
      "compliance_rationale": "...",
      "data_sensitivity": "PHI",
      "classified_at": "2026-05-03",
      "classifier_version": "1"
    }

The classification is best-effort — built from client name keywords + email
domain hints. Each client's `_compliance.json` is the source of truth for
the Compliance Alignment section in monthly reports. Tech can override any
field manually; the script defaults to ``--no-overwrite`` so a hand-edited
file is never clobbered.

Usage:
    python classify_clients.py                # classify all active clients (skip existing)
    python classify_clients.py --only AAVA    # one client
    python classify_clients.py --overwrite    # re-classify even if file exists
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENTS_ROOT = REPO_ROOT / "clients"

CLASSIFIER_VERSION = "1"

# (compiled-regex pattern on the client name, industry label, evidence text,
#  compliance frameworks list, rationale, data sensitivity).
# Order matters — first match wins.
INDUSTRY_RULES: list[tuple[re.Pattern, str, str, list[str], str, str]] = [
    (re.compile(r"\b(MD|D\.?O\.?|DDS|DPM|PA|PC)\b|M\.D\.|medic|sportsmedicine|health|doctor|dental|ortho|clinic|cardiology|dermatology|oncology|pediatric|surgery|surgeon|hospital|nurse|patient|pharmacy|prosthet|chiroprac|optomet", re.I),
     "Healthcare",
     "Name indicates medical practice or healthcare provider",
     ["HIPAA", "HITECH", "California CMIA"],
     "All endpoints handle Protected Health Information (PHI). HIPAA Security Rule (45 CFR §164.302-318) requires administrative, physical, and technical safeguards. The HITECH Act extends breach-notification and audit obligations. California CMIA (Civil Code §56) adds state-specific patient confidentiality rules.",
     "PHI"),

    (re.compile(r"\bbank\b|capital|lending|financial|fund|wealth|insurance|invest|advisor|advisory|payroll|accounting", re.I),
     "Financial Services",
     "Name indicates financial services / advisory / lending",
     ["SOC 2", "GLBA", "PCI DSS"],
     "Financial-services clients handle non-public personal information (NPI) and payment data. GLBA Safeguards Rule requires a written information-security program. SOC 2 Type II is increasingly the de-facto standard for vendor diligence. PCI DSS applies wherever cards are accepted (including custodial fee processing).",
     "NPI / PCI"),

    (re.compile(r"\blaw\b|attorney|legal|paralegal", re.I),
     "Legal Services",
     "Name indicates law firm or legal services",
     ["ABA Model Rule 1.6", "State Bar Ethics", "California CCPA"],
     "Law firms handle attorney-client privileged data. ABA Model Rule 1.6(c) requires reasonable efforts to prevent unauthorized disclosure. California CCPA applies to firms that collect California residents' personal data above thresholds. Many corporate clients now require SOC 2 attestation from their outside counsel.",
     "Privileged communications"),

    (re.compile(r"apartment|realty|real estate|properties|housing|residential|leasing", re.I),
     "Real Estate / Property Management",
     "Name indicates property management or real-estate operations",
     ["PCI DSS", "Fair Housing Act", "California CCPA"],
     "Property managers process resident payments (rent, deposits, fees), triggering PCI DSS scope. Fair Housing Act records, applicant/resident PII, and California CCPA obligations all apply. Some clients also process credit/background checks bringing FCRA into scope.",
     "PCI / Resident PII"),

    (re.compile(r"\bhomes?\b|builders|construction|contractor|developer|build", re.I),
     "Construction / Homebuilding",
     "Name indicates construction or homebuilding",
     ["California CCPA"],
     "Construction firms typically have minimal regulatory compliance obligations beyond general business privacy law (CCPA for California-resident data, OSHA for safety records). Government contracts (DoD, DOE) bring CMMC or NIST 800-171 into scope when applicable.",
     "PII (employees, customers)"),

    (re.compile(r"hotel|hospitality|resort|inn|motel|\bspa\b|salon", re.I),
     "Hospitality",
     "Name indicates hotel, spa, or hospitality operation",
     ["PCI DSS", "California CCPA"],
     "Hotels and spas process card-present and card-not-present transactions, putting them firmly in PCI DSS scope. Guest PII (passport scans, ID) drives CCPA and state breach-notification obligations.",
     "PCI / Guest PII"),

    (re.compile(r"engineering|engineer|defense|aerospace|aviation|MFG\b|manufact|industries|industrial|container corp|fabricat|machining|tooling|silicon", re.I),
     "Engineering / Manufacturing",
     "Name indicates engineering or manufacturing",
     ["California CCPA", "ITAR (if defense)", "CMMC (if DoD)"],
     "Engineering and manufacturing firms vary widely in compliance scope. Defense/aerospace work brings ITAR (export-controlled technical data) and CMMC (DoD contractor cybersecurity). Civilian manufacturing is typically governed by general privacy law and customer-imposed SOC 2 / NIST 800-171 requirements.",
     "Trade secrets / Customer PII"),

    (re.compile(r"foundation|non.?profit|charity|association|community", re.I),
     "Non-profit / Association",
     "Name indicates non-profit / association",
     ["California CCPA", "State charitable registration"],
     "Non-profits handle donor PII, member records, and (for healthcare/educational nonprofits) regulated data. CCPA and state charitable-registration requirements apply broadly; HIPAA, FERPA, or other frameworks may overlay depending on the mission.",
     "Donor / member PII"),

    (re.compile(r"hotel|restaurant|retail|store|shop|brewery|cafe", re.I),
     "Retail / Hospitality",
     "Name indicates retail or hospitality",
     ["PCI DSS", "California CCPA"],
     "Retail and hospitality businesses process card payments; PCI DSS applies to all card data flows. Customer PII drives California CCPA obligations.",
     "PCI / Customer PII"),

    (re.compile(r"talent|staffing|recruit|hr\b|human resources", re.I),
     "Staffing / Talent",
     "Name indicates talent or staffing services",
     ["California CCPA", "FCRA"],
     "Staffing firms collect candidate PII (SSN, prior employment, references) and run background checks (FCRA). California CCPA imposes specific job-applicant disclosure rules.",
     "Candidate PII"),

    (re.compile(r"consulting|consultant|services|advisory(?! group)|solutions", re.I),
     "Professional Services / Consulting",
     "Name indicates professional services or consulting",
     ["SOC 2 (if customer-required)", "California CCPA"],
     "Consulting and professional-services firms typically inherit compliance scope from their customers — most large enterprise clients require SOC 2 Type II attestation as a condition of vendor onboarding. CCPA applies to California-resident data.",
     "Client confidential / Internal PII"),

    (re.compile(r"shipping|logistics|freight|transport", re.I),
     "Logistics / Transportation",
     "Name indicates logistics or shipping",
     ["California CCPA", "DOT regulations"],
     "Transportation firms handle commercial-customer data and DOT-regulated records (driver hours, hazmat manifests). Privacy obligations follow general state law.",
     "Customer / driver records"),

    (re.compile(r"trucking|trucks|automot|auto\b|autosport|dealership|dealers|seiner", re.I),
     "Automotive / Trucking",
     "Name indicates automotive or trucking",
     ["California CCPA", "FTC Safeguards Rule (if dealer)"],
     "Auto dealers fall under the FTC Safeguards Rule for customer financial data; trucking falls under DOT regs. Both handle California-resident PII triggering CCPA obligations.",
     "Customer PII / Financial"),

    (re.compile(r"waste|recycl|disposal|environmental", re.I),
     "Environmental Services",
     "Name indicates waste, recycling, or environmental services",
     ["California CCPA", "EPA records"],
     "Environmental services firms keep regulatory records (waste manifests, disposal logs) under EPA rules. General CCPA applies to customer/employee PII.",
     "Customer PII"),
]

DEFAULT_INDUSTRY = "General Business"
DEFAULT_COMPLIANCE = ["California CCPA"]
DEFAULT_RATIONALE = (
    "No clear industry signal in the client name — defaulting to general California "
    "business privacy law (CCPA) for any California-resident data the client processes. "
    "Tech can override the industry / compliance scope by editing this file."
)
DEFAULT_DATA_SENSITIVITY = "Customer / employee PII"


def classify(name: str, primary_domain: str | None) -> dict:
    name_full = f"{name} {primary_domain or ''}"
    for pat, industry, evidence, frameworks, rationale, sensitivity in INDUSTRY_RULES:
        m = pat.search(name_full)
        if m:
            return {
                "industry": industry,
                "industry_evidence": f"{evidence} (match: '{m.group(0)}')",
                "compliance_scope": frameworks,
                "compliance_rationale": rationale,
                "data_sensitivity": sensitivity,
            }
    return {
        "industry": DEFAULT_INDUSTRY,
        "industry_evidence": "No keyword match in name or domain",
        "compliance_scope": list(DEFAULT_COMPLIANCE),
        "compliance_rationale": DEFAULT_RATIONALE,
        "data_sensitivity": DEFAULT_DATA_SENSITIVITY,
    }


def primary_domain_from(meta: dict) -> str | None:
    emails = meta.get("Recipient_Emails") or []
    domains = []
    for e in emails:
        if "@" not in e:
            continue
        d = e.split("@")[-1].lower()
        if d.endswith("technijian.com"):
            continue
        if d in ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
                 "aol.com", "icloud.com", "live.com"):
            continue
        domains.append(d)
    return domains[0] if domains else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="Comma-separated client slugs")
    ap.add_argument("--overwrite", action="store_true",
                    help="Re-classify even if _compliance.json already exists")
    args = ap.parse_args(argv)

    only = {s.strip().lower() for s in (args.only or "").split(",") if s.strip()}

    written = 0
    skipped = 0
    for client_dir in sorted([d for d in CLIENTS_ROOT.iterdir() if d.is_dir() and not d.name.startswith("_")]):
        slug = client_dir.name
        if only and slug not in only:
            continue
        meta_path = client_dir / "_meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not meta.get("Active"):
            continue

        out_path = client_dir / "_compliance.json"
        if out_path.exists() and not args.overwrite:
            skipped += 1
            continue

        primary_domain = primary_domain_from(meta)
        c = classify(meta.get("Location_Name") or slug, primary_domain)
        record = {
            "client_code": meta.get("LocationCode") or slug.upper(),
            "client_name": meta.get("Location_Name") or slug,
            "primary_domain": primary_domain,
            **c,
            "classified_at": date.today().isoformat(),
            "classifier_version": CLASSIFIER_VERSION,
            "_note": "Tech can edit this file; the classifier won't overwrite it on re-runs unless --overwrite is passed.",
        }
        out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        written += 1
        print(f"  [{slug}] {record['industry']:32s} {record['compliance_scope']}")

    print(f"\nClassified: {written} written, {skipped} skipped (already had _compliance.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
