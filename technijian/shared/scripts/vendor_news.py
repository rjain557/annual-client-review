"""Shared helper for the "Industry News & Vendor Innovations" section in
monthly client reports.

Loads curated vendor news for a given (vendor, year, month) from
``technijian/shared/data/vendor_news/<vendor>/<YYYY-MM>.json`` and
renders a branded section into a python-docx document.

Each JSON file is an array of items::

    [
      {
        "type": "feature|case-study|threat-report|industry-recognition",
        "title": "...",
        "summary": "...",
        "why_it_matters": "...",
        "date": "2026-03-24",       (optional)
        "source_url": "..."         (optional)
      }
    ]

If the file doesn't exist or is empty, ``render_section`` writes a
single neutral paragraph saying news will be published shortly — that
keeps the proofreader happy without forcing fake content.

Used by Huntress and CrowdStrike monthly report builders. To extend to
other vendors (Sophos, Meraki, etc.), just create the matching folder
under ``data/vendor_news/`` and pass the new vendor name to
``render_section``.
"""

from __future__ import annotations

import json
from pathlib import Path

from docx.document import Document as _Document

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "technijian" / "shared" / "data" / "vendor_news"

VENDOR_LABELS = {
    "huntress":    "Huntress",
    "crowdstrike": "CrowdStrike",
    "sophos":      "Sophos",
    "meraki":      "Cisco Meraki",
    "manageengine": "ManageEngine",
    "veeam":       "Veeam",
    "mailstore":   "MailStore",
}

TYPE_LABELS = {
    "feature":              "New feature",
    "case-study":           "Case study",
    "threat-report":        "Threat intelligence",
    "industry-recognition": "Industry recognition",
}


def load(vendor: str, year: int, month: int) -> list[dict]:
    """Return the list of news items for (vendor, year, month).

    Empty list if the file is missing or unreadable — callers should
    handle that gracefully (the renderer below does)."""
    path = DATA_ROOT / vendor.lower() / f"{year:04d}-{month:02d}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def render_section(doc: _Document, vendor: str, year: int, month: int, brand) -> None:
    """Append a branded "Industry News & Vendor Innovations" section to the doc.

    ``brand`` is the imported ``_brand`` module (passed in to avoid
    circular imports — every caller already has it in scope).
    """
    label = VENDOR_LABELS.get(vendor.lower(), vendor.title())
    items = load(vendor, year, month)

    brand.add_section_header(doc, "Industry News & Vendor Innovations")

    if not items:
        brand.add_body(
            doc,
            f"{label} announced no major platform changes this month. "
            f"Routine detection-content updates and sensor improvements "
            f"continued to roll out automatically. Technijian tracks "
            f"{label}'s release notes monthly so future updates land in "
            f"this section as they're published.",
        )
        return

    brand.add_body(
        doc,
        f"Highlights from {label} this month — features, threat "
        f"intelligence, and industry recognition that affect the "
        f"protection on your endpoints.",
    )

    for item in items:
        kind = (item.get("type") or "").strip().lower()
        kind_label = TYPE_LABELS.get(kind, "Update")
        title = (item.get("title") or "").strip()
        summary = (item.get("summary") or "").strip()
        why = (item.get("why_it_matters") or "").strip()
        url = (item.get("source_url") or "").strip()
        date_str = (item.get("date") or "").strip()

        # Title line — bold, sized up
        prefix = f"[{kind_label}] "
        suffix = f"  ({date_str})" if date_str else ""
        brand.add_body(
            doc,
            f"{prefix}{title}{suffix}",
            bold=True,
            size=12,
            color=brand.DARK_CHARCOAL,
        )

        if summary:
            brand.add_body(doc, summary, size=10.5)

        if why:
            brand.add_bullet(
                doc,
                why,
                bold_prefix="Why it matters: ",
            )

        if url:
            brand.add_body(
                doc,
                f"Source: {url}",
                size=9,
                color=brand.BRAND_GREY,
                italic=True,
            )


__all__ = ["load", "render_section", "VENDOR_LABELS", "TYPE_LABELS"]
