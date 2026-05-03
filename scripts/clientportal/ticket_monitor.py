"""
Ticket-monitor CLI — sends reminder emails for open CP tickets that
haven't been touched within the reminder window (default 24h).

Reads state from `state/cp_tickets.json` (managed by ticket_state.py).
Reminder destination is support@technijian.com (override via --to).

Commands:
    python ticket_monitor.py list                 # all tickets in state
    python ticket_monitor.py list --open          # only unresolved
    python ticket_monitor.py check                # send reminders for due tickets
    python ticket_monitor.py check --dry-run      # don't actually email
    python ticket_monitor.py check --hours 48     # custom reminder window
    python ticket_monitor.py resolve 1452721 --note "fixed by SK"
    python ticket_monitor.py resolve veeam-365:repo-capacity:AFFG-O365 --note "..."

Recommend a cron / scheduled task to run `check` daily on the production
workstation (the dev box is excluded per feedback_no_dev_box_schedules).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ticket_state  # noqa: E402
import ticket_email  # noqa: E402


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _due_for_reminder(t: dict, threshold: timedelta) -> bool:
    """A ticket is due if it has no resolved_at AND
       (last_reminder_at OR created_at) is older than threshold."""
    if t.get("resolved_at"):
        return False
    last = _parse_iso(t.get("last_reminder_at")) or _parse_iso(t.get("created_at"))
    if not last:
        return False
    return (datetime.now(timezone.utc) - last) >= threshold


def cmd_list(args: argparse.Namespace) -> int:
    rows = ticket_state.list_open() if args.open else ticket_state.list_all()
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return 0
    if not rows:
        print("(no tickets in state)")
        return 0
    fmt = "  {:>10}  {:<10}  {:<22}  {:>8}  {:>3}  {}"
    print(fmt.format("Ticket", "Client", "Source", "Age", "Rem", "Title"))
    print(fmt.format("-" * 10, "-" * 10, "-" * 22, "-" * 8, "---", "-" * 50))
    now = datetime.now(timezone.utc)
    for t in sorted(rows, key=lambda x: x.get("created_at") or ""):
        created = _parse_iso(t.get("created_at"))
        age = "?"
        if created:
            h = int((now - created).total_seconds() // 3600)
            age = f"{h}h" if h < 48 else f"{h // 24}d"
        status = " " if not t.get("resolved_at") else "R"
        print(fmt.format(
            t.get("ticket_id") or "-",
            (t.get("client_code") or "-")[:10],
            (t.get("source_skill") or "-")[:22],
            age,
            t.get("reminder_count", 0),
            f"{status} {(t.get('title') or '')[:60]}",
        ))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    threshold = timedelta(hours=args.hours)
    open_tickets = ticket_state.list_open()
    due = [t for t in open_tickets if _due_for_reminder(t, threshold)]
    print(f"open={len(open_tickets)}  threshold={args.hours}h  due={len(due)}  dry-run={args.dry_run}")
    if not due:
        return 0
    sent = 0
    failed = 0
    for t in due:
        result = ticket_email.send_reminder(t, to_address=args.to, dry_run=args.dry_run)
        ok = result.get("sent") or args.dry_run
        if ok and not args.dry_run:
            ticket_state.mark_reminder_sent(t["issue_key"], to=args.to)
            sent += 1
        elif args.dry_run:
            print(f"  DRY  #{t.get('ticket_id')}  {t.get('client_code')}  {result['subject']!r}")
        else:
            failed += 1
            print(f"  FAIL #{t.get('ticket_id')}  status={result.get('status')}  body={result.get('body')[:200]}",
                  file=sys.stderr)
        if not args.dry_run:
            print(f"  {'OK ' if ok else 'FAIL'}  #{t.get('ticket_id')}  {t.get('client_code')}  reminder #{int(t.get('reminder_count') or 0)+1}")
    print(f"\nReminders sent: {sent}.  Failed: {failed}.")
    return 1 if failed else 0


def cmd_resolve(args: argparse.Namespace) -> int:
    target = args.target
    if target.isdigit():
        target_val: int | str = int(target)
    else:
        target_val = target
    entry = ticket_state.mark_resolved(target_val, note=args.note)
    print(f"OK  resolved {target}  ticket_id={entry.get('ticket_id')}  client={entry.get('client_code')}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="CP ticket monitor — reminders + state")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="list tickets in state")
    p.add_argument("--open", action="store_true", help="only unresolved tickets")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("check", help="send reminder emails for due tickets")
    p.add_argument("--hours", type=float, default=24.0,
                   help="reminder threshold (hours since created_at or last_reminder_at)")
    p.add_argument("--to", default=ticket_email.DEFAULT_TO,
                   help="reminder recipient (default support@technijian.com)")
    p.add_argument("--dry-run", action="store_true",
                   help="don't actually send emails")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("resolve", help="mark a ticket resolved (stops reminders)")
    p.add_argument("target", help="ticket_id (int) or issue_key (string)")
    p.add_argument("--note", default=None, help="resolution note")
    p.set_defaults(func=cmd_resolve)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
