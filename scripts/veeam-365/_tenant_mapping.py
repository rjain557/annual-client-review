"""
Map VB365 organization names to CP client folder slugs.

The VB365 server happens to use names that already match CP location codes
for most tenants (JDH, BWH, ALG, ORX, AFFG, ACU, CBI). The 'Technijian' org
is internal — no client folder under clients/, so reports for it land in
`clients/_veeam_365/internal/`.
"""
from __future__ import annotations

# org name (case-insensitive) → CP client slug under clients/<slug>/
TENANT_TO_CLIENT: dict[str, str] = {
    "JDH": "jdh",
    "BWH": "bwh",
    "ALG": "alg",
    "ORX": "orx",
    "AFFG": "affg",
    "ACU": "acu",
    "CBI": "cbi",
    "TECHNIJIAN": "_internal",   # no clients/technijian/ folder; routes to _veeam_365/internal/
}

# friendly display name (overrides whatever VB365 has if needed)
TENANT_DISPLAY: dict[str, str] = {
    "JDH":   "JDH Pacific",
    "BWH":   "Brandywine Homes",
    "ALG":   "ALG",
    "ORX":   "ORX",
    "AFFG":  "AFFG",
    "ACU":   "ACU",
    "CBI":   "CBI",
    "TECHNIJIAN": "Technijian (internal)",
}


def slug_for(tenant_name: str) -> str:
    """Return the CP client slug for a VB365 org name; default to lowercased name."""
    return TENANT_TO_CLIENT.get(tenant_name.upper(), tenant_name.lower())


def display_for(tenant_name: str) -> str:
    return TENANT_DISPLAY.get(tenant_name.upper(), tenant_name)
