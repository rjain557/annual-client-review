"""
Central state file for every CP ticket opened by an automated pipeline.

Schema (state/cp_tickets.json at the repo root):

{
  "schemaVersion": 1,
  "tickets": {
    "<issue_key>": {
      "ticket_id": 1452721,
      "issue_key":  "veeam-365:repo-capacity:AFFG-O365",
      "client_code": "AFFG",
      "source_skill": "veeam-365-pull",
      "title": "...",
      "priority_id": 1255,
      "assign_to_dir_id": 205,
      "created_at": "2026-05-02T20:01:00Z",
      "last_reminder_at": null,
      "reminder_count": 0,
      "resolved_at": null,
      "resolved_note": null,
      "metadata": { ... source-specific extras ... },
      "history": [
        {"ts": "...", "event": "created"},
        {"ts": "...", "event": "reminder", "to": "support@technijian.com"},
        {"ts": "...", "event": "resolved", "note": "fixed by SK"}
      ]
    },
    ...
  }
}

`issue_key` is the dedup fingerprint chosen by the caller. Convention:
    "<source-skill>:<issue-type>:<resource-id>"
Examples:
    veeam-365:repo-capacity:AFFG-O365
    veeam-365:repo-capacity:TECH-O365
    veeam-365:job-warning:ALG-O365
    sophos:open-alerts:AAVA
    mailstore:archive-jobs-failing:icmlending
    veeam-vbr:repo-capacity:VAF-Repo

The same issue_key recurring after the previous one was resolved is fine
— the entry stays keyed by issue_key but `ticket_id` updates and
`history` accumulates.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = REPO_ROOT / "state" / "cp_tickets.json"
SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_state() -> dict:
    return {"schemaVersion": SCHEMA_VERSION, "tickets": {}}


def load() -> dict:
    if not STATE_FILE.exists():
        return _empty_state()
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return _empty_state()


def save(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def get(issue_key: str) -> dict | None:
    return load().get("tickets", {}).get(issue_key)


def has_open(issue_key: str) -> bool:
    """True iff a ticket exists for issue_key AND has not been resolved."""
    t = get(issue_key)
    return bool(t and not t.get("resolved_at"))


def add(
    *,
    issue_key: str,
    ticket_id: int,
    client_code: str,
    source_skill: str,
    title: str,
    priority_id: int,
    assign_to_dir_id: int,
    metadata: dict | None = None,
) -> dict:
    """Record a newly-created ticket. Idempotent — overwrites the entry
    for this issue_key (e.g. if a previously-resolved issue recurred)."""
    state = load()
    now = _now_iso()
    entry = state["tickets"].get(issue_key) or {}
    history = entry.get("history") or []
    entry.update({
        "ticket_id": ticket_id,
        "issue_key": issue_key,
        "client_code": client_code,
        "source_skill": source_skill,
        "title": title,
        "priority_id": priority_id,
        "assign_to_dir_id": assign_to_dir_id,
        "created_at": now,
        "last_reminder_at": None,
        "reminder_count": 0,
        "resolved_at": None,
        "resolved_note": None,
        "metadata": metadata or {},
    })
    history.append({"ts": now, "event": "created", "ticket_id": ticket_id})
    entry["history"] = history
    state["tickets"][issue_key] = entry
    save(state)
    return entry


def mark_reminder_sent(issue_key: str, *, to: str) -> dict:
    state = load()
    entry = state["tickets"].get(issue_key)
    if not entry:
        raise KeyError(f"unknown issue_key: {issue_key}")
    now = _now_iso()
    entry["last_reminder_at"] = now
    entry["reminder_count"] = int(entry.get("reminder_count") or 0) + 1
    entry.setdefault("history", []).append({"ts": now, "event": "reminder", "to": to})
    save(state)
    return entry


def mark_resolved(issue_key_or_ticket_id: str | int, note: str | None = None) -> dict:
    state = load()
    entry = None
    if isinstance(issue_key_or_ticket_id, int) or (isinstance(issue_key_or_ticket_id, str) and issue_key_or_ticket_id.isdigit()):
        tid = int(issue_key_or_ticket_id)
        for v in state["tickets"].values():
            if int(v.get("ticket_id") or 0) == tid:
                entry = v
                break
    else:
        entry = state["tickets"].get(issue_key_or_ticket_id)
    if not entry:
        raise KeyError(f"no ticket matching {issue_key_or_ticket_id!r}")
    now = _now_iso()
    entry["resolved_at"] = now
    entry["resolved_note"] = note
    entry.setdefault("history", []).append({"ts": now, "event": "resolved", "note": note})
    save(state)
    return entry


def list_open() -> list[dict]:
    state = load()
    return [t for t in state.get("tickets", {}).values() if not t.get("resolved_at")]


def list_all() -> list[dict]:
    return list(load().get("tickets", {}).values())


def backfill(
    *,
    issue_key: str,
    ticket_id: int,
    client_code: str,
    source_skill: str,
    title: str,
    priority_id: int,
    assign_to_dir_id: int,
    created_at: str,
    metadata: dict | None = None,
) -> dict:
    """Like add() but lets the caller pin the created_at timestamp.
    Used to register tickets that were filed before the state file existed."""
    state = load()
    entry = {
        "ticket_id": ticket_id,
        "issue_key": issue_key,
        "client_code": client_code,
        "source_skill": source_skill,
        "title": title,
        "priority_id": priority_id,
        "assign_to_dir_id": assign_to_dir_id,
        "created_at": created_at,
        "last_reminder_at": None,
        "reminder_count": 0,
        "resolved_at": None,
        "resolved_note": None,
        "metadata": metadata or {},
        "history": [{"ts": created_at, "event": "created", "ticket_id": ticket_id, "backfilled": True}],
    }
    state["tickets"][issue_key] = entry
    save(state)
    return entry
