"""Read-only contacts library backed by the tech-legal repo.

The source of truth for client contacts is the `tech-legal` repo at
`C:\\vscode\\tech-legal\\tech-legal\\clients\\<CODE>\\CONTACTS.md`. Each
file is a structured markdown document with sections:

    # <Full Name> (<CODE>)
    **Client Code:** <CODE>
    **Portal DirID:** <int>

    ## Contract Signer
    <free text or "*Not designated in portal*">

    ## Invoice Recipient
    <free text or "*Not designated in portal*">

    ## Primary Contact
    <free text or "*Not designated in portal*">

    ## All Active Users (N)

    ### <Name>
    - **Email:** <email>
    - **Phone:** <phone or N/A>
    - **Role:** <C1|C2|C3|...>

This module:
  - Parses every CONTACTS.md under tech-legal/clients/.
  - Optionally cross-references against `GET /api/clients/active` from the
    Client Portal, matching by Portal DirID first and LocationCode second.
  - Returns structured records, not formatted text. Callers (report builders,
    email senders) decide how to render.

The annual-client-review repo never copies contact data into its own files.
Every read goes back through this module so tech-legal stays the single
source of truth.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# Default path to the tech-legal repo. Override with TECH_LEGAL_ROOT env var
# or pass `tech_legal_root=` to load_all().
DEFAULT_TECH_LEGAL_ROOT = Path(r"C:\vscode\tech-legal\tech-legal")
DEFAULT_CLIENTS_DIRNAME = "clients"

NOT_DESIGNATED = "*Not designated in portal*"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Contact:
    name: str
    email: str | None = None
    phone: str | None = None
    role: str | None = None  # C1 / C2 / C3 / ...

    @property
    def has_email(self) -> bool:
        return bool(self.email and "@" in self.email)


@dataclass
class ClientContacts:
    code: str
    name: str
    dir_id: int | None
    contract_signer: str | None
    invoice_recipient: str | None
    primary_contact: str | None
    users: list[Contact] = field(default_factory=list)
    source_path: Path | None = None

    @property
    def has_designated_recipient(self) -> bool:
        return any(bool(x) for x in (self.contract_signer,
                                      self.invoice_recipient,
                                      self.primary_contact))

    def emails_with_role(self, role: str) -> list[str]:
        role = role.upper()
        return [u.email for u in self.users
                if u.has_email and (u.role or "").upper() == role]

    def all_emails(self) -> list[str]:
        return [u.email for u in self.users if u.has_email]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^#\s+(.+?)\s*\(([A-Za-z0-9_]+)\)\s*$", re.M)
_DIRID_RE = re.compile(r"\*\*Portal DirID:\*\*\s*(\d+)", re.I)
_CODE_RE = re.compile(r"\*\*Client Code:\*\*\s*([A-Za-z0-9_]+)", re.I)


def _section_text(md: str, heading: str) -> str:
    """Return the text under a `## heading` until the next `##` or end."""
    pat = re.compile(rf"##\s+{re.escape(heading)}\s*\n(.+?)(?=^##\s|\Z)", re.S | re.M)
    m = pat.search(md)
    if not m:
        return ""
    body = m.group(1).strip()
    if body == NOT_DESIGNATED:
        return ""
    return body


def _parse_users(md: str) -> list[Contact]:
    """Parse the `## All Active Users (N)` section into Contact records."""
    section = ""
    pat_active = re.compile(r"##\s+All Active Users\s*\(\d+\)\s*\n(.+)", re.S)
    m = pat_active.search(md)
    if not m:
        return []
    section = m.group(1)

    # Stop at next ## heading if present
    next_h = re.search(r"^##\s", section, re.M)
    if next_h:
        section = section[:next_h.start()]

    users: list[Contact] = []
    # Split by ### headings
    blocks = re.split(r"(?m)^###\s+", section)
    for blk in blocks:
        blk = blk.strip()
        if not blk:
            continue
        first_line, _, rest = blk.partition("\n")
        name = first_line.strip()
        email = phone = role = None
        for line in rest.splitlines():
            mm = re.match(r"-\s*\*\*(\w+):\*\*\s*(.+)$", line.strip())
            if not mm:
                continue
            key, value = mm.group(1).lower(), mm.group(2).strip()
            if value.lower() in ("n/a", "na", "none", "-", ""):
                value = None
            if key == "email":
                email = value
            elif key == "phone":
                phone = value
            elif key == "role":
                role = value
        users.append(Contact(name=name, email=email, phone=phone, role=role))
    return users


def parse_contacts_md(path: Path) -> ClientContacts | None:
    """Parse a single CONTACTS.md file. Returns None if the file is missing
    or unparseable (no client header)."""
    if not path.exists():
        return None
    md = path.read_text(encoding="utf-8")
    h = _HEADER_RE.search(md)
    if not h:
        return None
    name = h.group(1).strip()
    code = h.group(2).strip().upper()
    code_match = _CODE_RE.search(md)
    if code_match:
        code = code_match.group(1).strip().upper()
    dir_id = None
    di = _DIRID_RE.search(md)
    if di:
        try:
            dir_id = int(di.group(1))
        except ValueError:
            dir_id = None
    return ClientContacts(
        code=code,
        name=name,
        dir_id=dir_id,
        contract_signer=_section_text(md, "Contract Signer") or None,
        invoice_recipient=_section_text(md, "Invoice Recipient") or None,
        primary_contact=_section_text(md, "Primary Contact") or None,
        users=_parse_users(md),
        source_path=path,
    )


# ---------------------------------------------------------------------------
# Bulk load + match
# ---------------------------------------------------------------------------

def load_all_tech_legal_contacts(
    tech_legal_root: Path | str | None = None,
    clients_subdir: str = DEFAULT_CLIENTS_DIRNAME,
) -> dict[str, ClientContacts]:
    """Walk tech-legal/clients/<CODE>/CONTACTS.md. Returns {CODE: ClientContacts}."""
    root = Path(tech_legal_root) if tech_legal_root else DEFAULT_TECH_LEGAL_ROOT
    clients_dir = root / clients_subdir
    if not clients_dir.exists():
        raise FileNotFoundError(
            f"tech-legal clients dir not found: {clients_dir}. "
            f"Pass tech_legal_root= or set TECH_LEGAL_ROOT env var.")
    out: dict[str, ClientContacts] = {}
    for d in sorted(p for p in clients_dir.iterdir() if p.is_dir()):
        f = d / "CONTACTS.md"
        info = parse_contacts_md(f)
        if info:
            out[info.code] = info
    return out


@dataclass
class ClientMatch:
    code: str                       # uppercased LocationCode
    cp_dir_id: int | None
    cp_name: str | None
    legal: ClientContacts | None
    match_method: str               # "dir_id" | "code" | "missing_legal" | "stale_legal"


def cross_reference(
    tech_legal: dict[str, ClientContacts],
    active_clients: list[dict],
) -> list[ClientMatch]:
    """Match active CP clients to tech-legal entries.
    Match priority: DirID first, then LocationCode case-insensitive.
    Active clients are the authoritative active set; tech-legal entries with
    no active CP match are flagged stale (separate list, see stale_legal())."""
    legal_by_dir: dict[int, ClientContacts] = {}
    for c in tech_legal.values():
        if c.dir_id is not None:
            legal_by_dir[c.dir_id] = c

    out: list[ClientMatch] = []
    for cp in active_clients:
        code = (cp.get("LocationCode") or "").upper()
        dir_id = cp.get("DirID")
        cp_name = cp.get("Location_Name") or ""
        legal = None
        method = "missing_legal"
        if dir_id is not None and dir_id in legal_by_dir:
            legal = legal_by_dir[dir_id]
            method = "dir_id"
        elif code and code in tech_legal:
            legal = tech_legal[code]
            method = "code"
        out.append(ClientMatch(
            code=code, cp_dir_id=dir_id, cp_name=cp_name,
            legal=legal, match_method=method,
        ))
    return out


def stale_legal(
    tech_legal: dict[str, ClientContacts],
    active_clients: list[dict],
) -> list[ClientContacts]:
    """tech-legal entries that have no matching active CP client. Probably
    terminated, renamed, or never made it back into the active set."""
    active_dirs = {cp.get("DirID") for cp in active_clients
                    if cp.get("DirID") is not None}
    active_codes = {(cp.get("LocationCode") or "").upper() for cp in active_clients}
    out = []
    for c in tech_legal.values():
        if c.dir_id is not None and c.dir_id in active_dirs:
            continue
        if c.code in active_codes:
            continue
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# Recipient helpers (consumed by report-sender pipelines)
# ---------------------------------------------------------------------------

# Email local-parts that are organizational mailboxes, not individuals. These
# are NEVER candidates for a "who can sign contracts" designation.
_GENERIC_LOCALPARTS = {
    "accounting", "accounts", "accountspayable", "accounts_payable", "ap",
    "ar", "billing", "invoice", "invoices", "payments", "payroll",
    "admin", "administrator", "info", "office", "support", "service",
    "services", "help", "helpdesk", "it", "technijian", "noreply",
    "no-reply", "do-not-reply", "postmaster", "abuse", "mailmaster",
    "scan", "scanner", "copier", "fax", "print", "printer",
    "logistics", "customs", "maintenance", "marine", "machinecenter",
    "customerservice", "memberdesk", "membership", "advocacy",
    "compliance", "careers", "bids", "conference", "president",
    "user1", "user2", "user3", "user4",
    "backup", "backup365", "beservice", "jdh365", "onelogin",
    "m365", "sharepoint", "teams", "smtp", "smtprelay",
    "controller",  # often a generic group mailbox
}

# Title keywords that signal contract-signing authority.
_SIGNER_TITLE_KEYWORDS = (
    "ceo", "president", "owner", "principal", "partner",
    "managing director", "managing partner", "founder", "co-founder",
    "cfo", "coo", "cio", "cto", "vp ", " vp", "vice president",
    "director", "general counsel", "general manager",
    "controller of",  # disambiguate from generic "controller@" mailbox
)


def is_generic_email(email: str | None) -> bool:
    if not email or "@" not in email:
        return True
    local = email.split("@", 1)[0].lower()
    return local in _GENERIC_LOCALPARTS


def _looks_like_signer_title(text: str | None) -> bool:
    if not text:
        return False
    t = text.lower()
    return any(k in t for k in _SIGNER_TITLE_KEYWORDS)


def likely_signers(legal: ClientContacts) -> list[Contact]:
    """Heuristic: return the Active Users most likely authorized to sign
    contracts/proposals/estimates, ranked best-first.

    Ranking signal (high to low):
      1. Designated `Primary Contact` / `Invoice Recipient` / `Contract Signer`
         line that includes a Title containing CEO/President/Owner/etc.
      2. Active User with a personal-name email AND not a generic localpart.
      3. Active User whose Phone is set (often C1 owners/principals).

    Generic-mailbox emails (accounting@, ap@, service@, scanner@, etc.) are
    ALWAYS filtered out here even when the role is C1.
    """
    if legal is None:
        return []

    # Build score per user
    scored: list[tuple[int, Contact]] = []
    for u in legal.users:
        if not u.has_email or is_generic_email(u.email):
            continue
        score = 0
        # Personal-looking name (two words, capitalized) bumps confidence
        if u.name and len(u.name.split()) >= 2 and any(c.isupper() for c in u.name):
            score += 2
        # Has phone -> usually a real human, often a principal
        if u.phone:
            score += 1
        # Role weighting (C1 generally outranks C2 outranks C3)
        rk = (u.role or "").upper()
        if rk == "C1":
            score += 3
        elif rk == "C2":
            score += 2
        elif rk == "C3":
            score += 1
        # Title match in the designation text (rare but valuable)
        if _looks_like_signer_title(legal.primary_contact) and (
            u.email and u.email.lower() in (legal.primary_contact or "").lower()):
            score += 5
        scored.append((score, u))

    scored.sort(key=lambda kv: -kv[0])
    return [u for _, u in scored]


def report_recipients(
    legal: ClientContacts,
) -> list[str]:
    """Return the list of email addresses authorized to receive client-facing
    reports / proposals / contracts.

    Strict resolution: ONLY emails parsed out of the portal-designated
    `Primary Contact`, `Invoice Recipient`, or `Contract Signer` sections of
    the tech-legal CONTACTS.md file. No fallback to generic role lists -
    "C1" in the portal means "portal user", not "signer".

    Returns an empty list when no designated recipient is set. The caller
    must treat empty as "needs portal designation; do not send" and surface
    the gap. Use `likely_signers(legal)` to suggest who in the user list
    most plausibly should be designated.
    """
    if legal is None:
        return []
    out: list[str] = []
    for label in (legal.primary_contact, legal.invoice_recipient, legal.contract_signer):
        if not label:
            continue
        for email in _extract_emails(label):
            if email not in out:
                out.append(email)
    return out


def _extract_emails(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)


__all__ = [
    "Contact",
    "ClientContacts",
    "ClientMatch",
    "DEFAULT_TECH_LEGAL_ROOT",
    "parse_contacts_md",
    "load_all_tech_legal_contacts",
    "cross_reference",
    "stale_legal",
    "report_recipients",
    "likely_signers",
    "is_generic_email",
]
