"""
Meraki org slug -> per-client folder code mapping.

`meraki_api.slugify(org["name"])` produces the Meraki org slug. The destination
client folder name comes from this map. Keys are Meraki slugs, values are the
existing `clients/<code>/` folder names (lowercase).

Add an entry here when you onboard a new Meraki org. Unknown slugs fall back
to using the slug itself as the folder name (so a brand-new org doesn't fail
the pull — it just lands in `clients/<slug>/meraki/` which the operator can
rename later).
"""

from __future__ import annotations

# Meraki org slug -> clients/<code>/ folder name (matches CP LocationCode lowercase)
ORG_TO_CLIENT_FOLDER: dict[str, str] = {
    "technijian_inc":   "technijian",       # Technijian internal infra
    "aranda_tooling":   "arnd",             # CP code ARND
    "aoc":              "aoc",
    "bwh":              "bwh",
    "orx":              "orx",
    "vaf":              "vaf",
    "vg":               "vg",
    # Dormant (403, no active license):
    "technijian":       "technijian",
    "gsc":              "gsc",
}


def client_folder(meraki_slug: str) -> str:
    """Resolve a Meraki org slug to the clients/<code>/ folder name."""
    return ORG_TO_CLIENT_FOLDER.get(meraki_slug, meraki_slug)
