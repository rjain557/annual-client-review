"""Pull real work done from CP tickets + time entries and surface it,
positively framed, in each data source's monthly report.

For a given (client_slug, year, month, data_source), reads the per-month
tickets + time entries already pulled by the ``client-portal-pull``
skill at::

    clients/<slug>/monthly/<YYYY-MM>/tickets.json
    clients/<slug>/monthly/<YYYY-MM>/time_entries.json

Categorizes each item by data source via keyword matching on the
``Title``, ``Categories``, and ``Notes`` fields — items that don't
match any data source are silently dropped (so we never claim work
that wasn't done for that area, and we never include ambiguous items).

Returns a list of human-readable bullets per data source, scrubbed to
show only what Technijian *did* (no failures, no escalations, no SLA
misses) — matches the positive-framing theme of the monthly reports.

Used by every monthly report builder. Wired into the
"What Technijian Did For You" section so each report shows only the
work relevant to that data source.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CLIENTS_ROOT = REPO_ROOT / "clients"

# Data-source keyword map. First match wins. Patterns are case-insensitive
# regex tested against the joined Title + Categories + Notes text. Order
# matters — more-specific vendor names go first so "Veeam 365" doesn't
# misclassify as Veeam VBR.
DATA_SOURCE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("crowdstrike",  re.compile(r"\b(crowdstrike|falcon)\b", re.I)),
    ("huntress",     re.compile(r"\bhuntress\b", re.I)),
    ("sophos",       re.compile(r"\b(sophos|xgs)\b", re.I)),
    ("meraki",       re.compile(r"\b(meraki|cisco\s+(switch|access\s+point|wan)|MR\d+|MS\d+|MX\d+)\b", re.I)),
    ("veeam-365",    re.compile(r"\b(veeam[\s-]?365|veeam\s+for\s+(microsoft|m)?365|vb365)\b", re.I)),
    ("veeam-one",    re.compile(r"\bveeam\s*one\b", re.I)),
    ("veeam-vbr",    re.compile(r"\b(veeam(\s+backup)?(\s+&\s+replication)?|VBR\b|backup\s+job|backup\s+repository|restore\s+point)\b", re.I)),
    ("vcenter",      re.compile(r"\b(vcenter|vmware|esxi|vsphere|virtual\s+machine|VM\s+(snapshot|template))\b", re.I)),
    ("mailstore",    re.compile(r"\bmailstore\b", re.I)),
    ("m365",         re.compile(r"\b(microsoft\s+365|office\s+365|exchange\s+online|sharepoint\s+online|intune|azure\s+ad\b|entra\s+id|ms\s+teams|outlook\s+(client|setup|migration))\b", re.I)),
    ("me-ec",        re.compile(r"\b(myrmm|my\s+rmm|manage[\s-]?engine|endpoint\s+central|patch(es|ing)?|windows\s+update)\b", re.I)),
]

# Negative-language strip-list — phrases we DROP from the rendered bullet
# so that no client-facing bullet describes a failure mode.
NEGATIVE_PATTERNS = re.compile(
    r"\b(failed|failure|error|errored|crash|crashed|missed\s+sla|breach|"
    r"escalat\w+|incomplete|unable\s+to|could\s+not|broke|broken)\b",
    re.I,
)


def _strip_html(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"<[^>]+>", " ", s)


def _hours_from(timediff: str) -> float | None:
    """Parse ``"-\n0.82 hrs"`` or ``"0.5 hrs"`` style strings."""
    if not timediff:
        return None
    m = re.search(r"([\d.]+)\s*hrs?", str(timediff), re.I)
    return float(m.group(1)) if m else None


def _classify(title: str, categories: list[str], notes: str) -> str | None:
    """Return the data-source slug or ``None`` if no clean classification."""
    blob = " ".join([title or "", " ".join(categories or []), _strip_html(notes or "")])
    for source, pat in DATA_SOURCE_PATTERNS:
        if pat.search(blob):
            return source
    return None


def _is_positive(title: str, notes: str) -> bool:
    """True if the item describes work we want to surface to the client.
    False if it contains negative language we'd rather not put in a
    client-facing report."""
    blob = (title or "") + " " + _strip_html(notes or "")
    return not NEGATIVE_PATTERNS.search(blob)


def _summarize_ticket(t: dict) -> str:
    """Compose a positive-framed bullet from a ticket record."""
    title = (t.get("Title") or "").strip().rstrip(".") or "Worked on a service request"
    hours = float(t.get("TotalHours_NH") or 0) + float(t.get("TotalHours_AH") or 0)
    techs = ", ".join(t.get("Resources") or [])
    parts = [title]
    if techs:
        parts.append(f"(handled by {techs})")
    if hours and hours > 0:
        parts.append(f"— {hours:.1f}h of tech effort")
    return " ".join(parts)


def _summarize_entry(e: dict) -> str:
    """Compose a positive-framed bullet from a time-entry record."""
    title = (e.get("Title") or "").strip().rstrip(".") or "Performed scheduled service work"
    hours = _hours_from(e.get("TimeDiff") or "")
    parts = [title]
    if hours and hours > 0:
        parts.append(f"— {hours:.1f}h on {e.get('TimeEntryDate') or ''}")
    return " ".join(parts)


def load(slug: str, year: int, month: int) -> tuple[list[dict], list[dict]]:
    """Return (tickets, time_entries) for the client+month."""
    base = CLIENTS_ROOT / slug / "monthly" / f"{year:04d}-{month:02d}"
    tickets: list[dict] = []
    entries: list[dict] = []
    tp = base / "tickets.json"
    if tp.exists():
        try:
            data = json.loads(tp.read_text(encoding="utf-8"))
            tickets = data if isinstance(data, list) else (data.get("tickets") or [])
        except Exception:
            pass
    ep = base / "time_entries.json"
    if ep.exists():
        try:
            data = json.loads(ep.read_text(encoding="utf-8"))
            entries = data if isinstance(data, list) else (data.get("entries") or [])
        except Exception:
            pass
    return tickets, entries


def highlights_for(slug: str, year: int, month: int, data_source: str, *, max_items: int = 6) -> list[str]:
    """Return a list of positive-framed bullet strings describing what
    Technijian did for this client this month, scoped to ``data_source``.

    ``data_source`` is one of: me-ec, huntress, crowdstrike, sophos,
    meraki, vcenter, veeam-vbr, veeam-one, veeam-365, mailstore, m365.

    Empty list if no qualifying work — caller should fall back to the
    default narrative rather than render an empty section.
    """
    tickets, entries = load(slug, year, month)
    out: list[str] = []
    seen: set[str] = set()

    for t in tickets:
        title = t.get("Title") or ""
        notes = ""
        if not _is_positive(title, notes):
            continue
        if _classify(title, t.get("Categories") or [], notes) != data_source:
            continue
        bullet = _summarize_ticket(t)
        if bullet.lower() not in seen:
            seen.add(bullet.lower())
            out.append(bullet)
        if len(out) >= max_items:
            return out

    for e in entries:
        title = e.get("Title") or ""
        notes = e.get("Notes") or ""
        if not _is_positive(title, notes):
            continue
        if _classify(title, [e.get("ConName") or ""], notes) != data_source:
            continue
        bullet = _summarize_entry(e)
        if bullet.lower() not in seen:
            seen.add(bullet.lower())
            out.append(bullet)
        if len(out) >= max_items:
            return out

    return out


def render_section(doc, slug: str, year: int, month: int, data_source: str, brand) -> None:
    """Append a "Service Highlights" subsection to the doc with the
    client's positive-framed work bullets for this data source. No-op
    if no qualifying work — caller should not render an empty header."""
    items = highlights_for(slug, year, month, data_source)
    if not items:
        return
    brand.add_body(
        doc,
        "Specific work delivered this month",
        bold=True, size=12, color=brand.DARK_CHARCOAL,
    )
    brand.add_body(
        doc,
        "These items are pulled directly from the time entries and "
        "tickets logged by Technijian's team during the period — actual "
        "work, not estimates.",
    )
    for b in items:
        brand.add_bullet(doc, b)


__all__ = ["highlights_for", "render_section", "load", "DATA_SOURCE_PATTERNS"]
