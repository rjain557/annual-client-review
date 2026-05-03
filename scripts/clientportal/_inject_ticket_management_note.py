"""
One-shot — append a 'Ticket management' awareness section to every SKILL.md
in .claude/skills/ so that future Claude instances reading any skill know
to route ticket creation through cp-ticket-management.

Two flavors:
  - 'migration' block for skills that currently create CP tickets directly
  - 'awareness' block for everything else

Idempotent: skips files that already contain the marker line.
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / ".claude" / "skills"

MARKER = "<!-- ticket-management-note: cp-ticket-management -->"

# Skills that currently create CP tickets directly (need migration)
TICKET_CREATORS: dict[str, dict] = {
    "cp-create-ticket": {
        "current_state_path": "(no state — bare SP wrapper)",
        "note": "This is the underlying SP wrapper. New callers should use "
                "`cp_tickets.create_ticket_for_code_tracked(...)` from the "
                "tracked wrapper added 2026-05-02 — see "
                "[../cp-ticket-management/SKILL.md] for the convention. "
                "The raw `create_ticket(...)` / `create_ticket_for_code(...)` "
                "functions still exist for manual / one-off use.",
    },
    "sophos-pull": {
        "current_state_path": "technijian/sophos-pull/state/alert-tickets.json",
        "note": "`route_alerts.py` runs hourly and opens client-billable "
                "tickets to CHD : TS1. **Pending migration** to the central "
                "tracked wrapper. After migration its existing 24h reminder "
                "loop in `email_support.py` can retire (the central monitor "
                "covers reminders).",
    },
    "mailstore-spe-pull": {
        "current_state_path": "technijian/mailstore-pull/state/<auto>",
        "note": "`route_alerts.py` opens CP tickets for archive-store "
                "alerts. **Pending migration** to the central tracked "
                "wrapper. Backfill the 3 existing tickets (#1452674 "
                "Technijian SMTP, #1452675 ORX index, #1452676 ICML "
                "archive-jobs FAILING) via `ticket_state.backfill(...)`.",
    },
    "veeam-vbr": {
        "current_state_path": "(in-script TICKETS list in file_2026_backup_tickets.py)",
        "note": "`scripts/veeam-vbr/file_2026_backup_tickets.py` files "
                "8 tickets per yearly run for capacity/health/RPC issues. "
                "**Pending migration** to the central tracked wrapper. "
                "Backfill the 8 already-filed tickets (#1452728-#1452735) "
                "via `ticket_state.backfill(...)`.",
    },
}

AWARENESS_BLOCK = f"""

{MARKER}

## Ticket management

If this skill ever needs to open a CP ticket for an issue it detects
(capacity warning, threshold breach, persistent failure), use the
tracked wrapper from the **cp-ticket-management** skill —
`cp_tickets.create_ticket_for_code_tracked(...)` in
`scripts/clientportal/cp_tickets.py`. The central state file at
`state/cp_tickets.json` deduplicates on `issue_key`
(convention: `<source-skill>:<issue-type>:<resource-id>`) and
`scripts/clientportal/ticket_monitor.py check` (daily 06:00 PT on the
production workstation) sends 24h reminder emails to
support@technijian.com for any open ticket. **Don't call
`cp_tickets.create_ticket(...)` directly** — the raw call bypasses
state and reminders.
"""


def _migration_block(skill_name: str, info: dict) -> str:
    return f"""

{MARKER}

## Ticket management — migration to cp-ticket-management

This skill currently opens CP tickets directly. State today:
`{info["current_state_path"]}`.

{info["note"]}

**Migration steps** (see ../cp-ticket-management/SKILL.md):

1. Replace `cp_tickets.create_ticket(...)` /
   `cp_tickets.create_ticket_for_code(...)` with
   `cp_tickets.create_ticket_for_code_tracked(...)`.
2. Pick a stable `issue_key` per unique issue
   (convention: `{skill_name}:<issue-type>:<resource-id>`).
3. Pass `source_skill="{skill_name}"`.
4. Pass `metadata={{...}}` with the data points that justified the
   ticket (counts, percentages, server names).
5. Backfill any existing open tickets via
   `ticket_state.backfill(...)` — template at
   `scripts/veeam-365/_backfill_state.py`.

After migration: the central monitor at
`scripts/clientportal/ticket_monitor.py check` handles 24h reminders to
support@technijian.com automatically. Retire this skill's local
reminder loop / state file.
"""


def main() -> None:
    updated = []
    skipped = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name
        f = skill_dir / "SKILL.md"
        if not f.exists():
            continue

        # Skip the cp-ticket-management skill itself + veeam-365-pull (already updated)
        if skill_name in ("cp-ticket-management", "veeam-365-pull"):
            skipped.append((skill_name, "already integrated"))
            continue

        text = f.read_text(encoding="utf-8")
        if MARKER in text:
            skipped.append((skill_name, "marker present"))
            continue

        if skill_name in TICKET_CREATORS:
            block = _migration_block(skill_name, TICKET_CREATORS[skill_name])
        else:
            block = AWARENESS_BLOCK

        # Strip trailing newlines, then add the block + a single newline
        new_text = text.rstrip() + block.rstrip() + "\n"
        f.write_text(new_text, encoding="utf-8")
        updated.append(skill_name)

    print(f"Updated {len(updated)} SKILL.md files:")
    for s in updated:
        kind = "MIGRATION" if s in TICKET_CREATORS else "awareness"
        print(f"  {kind:<10}  {s}")
    print(f"\nSkipped {len(skipped)}:")
    for s, why in skipped:
        print(f"  {why:<22}  {s}")


if __name__ == "__main__":
    main()
