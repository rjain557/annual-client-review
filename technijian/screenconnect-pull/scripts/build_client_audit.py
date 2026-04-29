"""Build a per-client ScreenConnect audit log for a given year.

For each recording session:
  - Machine name, logged-in end-user (from Session.db)
  - Technician name(s) who connected (EventType=1, Host field)
  - Recording start/end times (from filename)
  - Duration in minutes
  - teams_url (OneDrive link — populated after conversion + upload; blank until then)

Output written to: clients/{client_code}/screenconnect/{year}/
  - audit_sessions.csv   — one row per recording session
  - audit_sessions.json  — same data, JSON

Usage:
    python build_client_audit.py --client BWH [--year 2026] [--no-refresh-db]
    python build_client_audit.py --client BWH --from-audit-json C:\\converted\\sc-2026\\audit_log.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
REMOTE_DB        = r'\\10.100.14.10\C$\Program Files (x86)\ScreenConnect\App_Data\Session.db'
REMOTE_RECS      = r'R:\\'           # mapped via: net use R: "\\10.100.14.10\E$\Myremote Recording" /persistent:yes
REMOTE_RECS_UNC  = r'\\10.100.14.10\E$\Myremote Recording'
LOCAL_DB         = Path(r'C:\tmp\sc_db\Session.db')
REPO_ROOT   = Path(__file__).resolve().parents[3]  # annual-client-review root

# ── datetime conversion (.NET Ticks) ──────────────────────────────────────────
_TICKS_OFFSET = 621355968000000000  # ticks from 0001-01-01 to Unix epoch

def ticks_to_dt(ticks: int) -> datetime:
    return datetime.fromtimestamp((ticks - _TICKS_OFFSET) / 10_000_000, tz=timezone.utc)

def ticks_to_iso(ticks: int) -> str:
    return ticks_to_dt(ticks).strftime('%Y-%m-%dT%H:%M:%SZ')

# ── regex for recording filename ──────────────────────────────────────────────
UUID_RE = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
REC_RE  = re.compile(
    rf'^({UUID_RE})-({UUID_RE})-'
    rf'(\d{{4}})-(\d{{2}})-(\d{{2}})-(\d{{2}})-(\d{{2}})-(\d{{2}})-'
    rf'(\d{{4}})-(\d{{2}})-(\d{{2}})-(\d{{2}})-(\d{{2}})-(\d{{2}})$'
)


def load_session_map(db: Path, client: str) -> dict:
    """Load all sessions for a client as {session_uuid: {machine, user, name, type}}."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("""
        SELECT SessionID, Name, GuestMachineName, GuestLoggedOnUserName, SessionType
        FROM Session WHERE CustomProperty1 = ?
    """, (client,))
    result = {}
    for r in cur.fetchall():
        try:
            sid = str(uuid.UUID(bytes_le=r['SessionID']))
            result[sid] = {
                'raw_id':  r['SessionID'],
                'machine': r['GuestMachineName'] or r['Name'] or '',
                'user':    r['GuestLoggedOnUserName'] or '',
                'name':    r['Name'] or '',
                'type':    r['SessionType'],
            }
        except Exception:
            pass
    con.close()
    return result


def load_tech_events(db: Path, session_map: dict) -> dict:
    """Load EventType=1 (Connected) events for sessions, keyed by session UUID.

    Returns {session_uuid: [{'tech': ..., 'time': ISO string}, ...]}
    """
    raw_ids = [info['raw_id'] for info in session_map.values()]
    if not raw_ids:
        return {}

    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    ph = ','.join('?' * len(raw_ids))
    cur.execute(f"""
        SELECT SessionID, Host, Time
        FROM SessionEvent
        WHERE SessionID IN ({ph}) AND EventType = 1 AND Host != ''
        ORDER BY Time ASC
    """, raw_ids)
    result: dict[str, list] = defaultdict(list)
    for r in cur.fetchall():
        try:
            sid = str(uuid.UUID(bytes_le=r['SessionID']))
            result[sid].append({'tech': r['Host'], 'time': ticks_to_iso(r['Time'])})
        except Exception:
            pass
    con.close()
    return dict(result)


def _recordings_dir() -> Path:
    p = Path(REMOTE_RECS)
    return p if p.exists() else Path(REMOTE_RECS_UNC)


def scan_recordings_for_client(client: str, session_map: dict, year: str) -> list[dict]:
    """Scan the recordings directory and return records for this client/year."""
    records = []
    for f in _recordings_dir().iterdir():
        m = REC_RE.match(f.name)
        if not m:
            continue
        session_id    = m.group(1)
        connection_id = m.group(2)
        sy, smo, sd, sh, smn, ss = m.group(3), m.group(4), m.group(5), m.group(6), m.group(7), m.group(8)
        ey, emo, ed, eh, emn, es = m.group(9), m.group(10), m.group(11), m.group(12), m.group(13), m.group(14)

        if sy != year:
            continue
        if session_id not in session_map:
            continue

        start_dt = f"{sy}-{smo}-{sd}T{sh}:{smn}:{ss}Z"
        end_dt   = f"{ey}-{emo}-{ed}T{eh}:{emn}:{es}Z"
        try:
            start = datetime.fromisoformat(start_dt.replace('Z', '+00:00'))
            end   = datetime.fromisoformat(end_dt.replace('Z', '+00:00'))
            duration_minutes = round((end - start).total_seconds() / 60, 1)
        except Exception:
            duration_minutes = None

        info = session_map[session_id]
        records.append({
            'session_id':      session_id,
            'connection_id':   connection_id,
            'machine':         info['machine'],
            'end_user':        info['user'],
            'session_name':    info['name'],
            'session_type':    'Support' if info['type'] == 2 else 'Access' if info['type'] == 1 else str(info['type']),
            'year':            sy,
            'month':           smo,
            'day':             sd,
            'recording_start': start_dt,
            'recording_end':   end_dt,
            'duration_minutes': duration_minutes,
            'file_size_bytes': f.stat().st_size,
            'filename':        f.name,
            'tech_events':     [],  # filled in next step
            'teams_url':       '',  # filled in after upload
        })
    return records


def enrich_with_techs(records: list[dict], tech_events: dict) -> None:
    """Attach tech connect events to each record (in-place)."""
    for rec in records:
        events = tech_events.get(rec['session_id'], [])
        rec['tech_events'] = events
        # Primary tech = first one who connected
        rec['tech_name'] = events[0]['tech'] if events else ''
        rec['tech_connect_time'] = events[0]['time'] if events else ''
        # All unique techs (comma-sep)
        unique_techs = list(dict.fromkeys(e['tech'] for e in events))
        rec['all_techs'] = ', '.join(unique_techs)


def merge_teams_urls(records: list[dict], audit_log_path: Path) -> None:
    """If a completed audit_log.json exists from pull_screenconnect_2026.py,
    merge Teams URLs into these records by (session_id, connection_id)."""
    if not audit_log_path.exists():
        return
    with open(audit_log_path, encoding='utf-8') as f:
        prior = json.load(f)
    url_map = {
        (r.get('session_id', ''), r.get('connection_id', '')): r.get('teams_url', '')
        for r in prior if r.get('teams_url')
    }
    for rec in records:
        key = (rec['session_id'], rec['connection_id'])
        if key in url_map:
            rec['teams_url'] = url_map[key]


def write_outputs(records: list[dict], out_dir: Path, client: str, year: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # CSV — flattened for Excel
    csv_fields = [
        'recording_start', 'recording_end', 'duration_minutes',
        'tech_name', 'all_techs', 'machine', 'end_user',
        'session_type', 'session_id', 'connection_id',
        'month', 'day', 'file_size_bytes', 'teams_url',
    ]
    csv_path = out_dir / f'{client}-SC-Audit-{year}.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=csv_fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(sorted(records, key=lambda r: r['recording_start']))

    # JSON — full detail including tech_events list
    json_path = out_dir / f'{client}-SC-Audit-{year}.json'
    json_path.write_text(
        json.dumps(sorted(records, key=lambda r: r['recording_start']),
                   indent=2, default=str),
        encoding='utf-8'
    )

    # Summary
    total = len(records)
    with_tech = sum(1 for r in records if r['tech_name'])
    with_url  = sum(1 for r in records if r['teams_url'])
    total_mb  = sum(r['file_size_bytes'] for r in records) // 1024 // 1024
    months    = sorted(set(r['month'] for r in records))
    print(f"\n{client} ScreenConnect Audit — {year}")
    print(f"  {total} recording sessions  |  {total_mb} MB raw")
    print(f"  {with_tech} with tech name  |  {with_url} with Teams URL")
    print(f"  Months: {', '.join(months)}")
    print(f"\n  CSV:  {csv_path}")
    print(f"  JSON: {json_path}")


def all_client_codes(db: Path) -> list[str]:
    """Return all distinct non-empty CustomProperty1 values from Session table."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    cur = con.cursor()
    cur.execute("SELECT DISTINCT CustomProperty1 FROM Session WHERE CustomProperty1 != '' ORDER BY CustomProperty1")
    codes = [r[0] for r in cur.fetchall()]
    con.close()
    return codes


def run_client(client: str, year: str, audit_log: Path) -> dict:
    """Build the audit for one client. Returns summary dict."""
    session_map = load_session_map(LOCAL_DB, client)
    tech_events  = load_tech_events(LOCAL_DB, session_map)
    records      = scan_recordings_for_client(client, session_map, year)
    enrich_with_techs(records, tech_events)
    if audit_log.exists():
        merge_teams_urls(records, audit_log)
    out_dir = REPO_ROOT / 'clients' / client.lower() / 'screenconnect' / year
    if records:
        write_outputs(records, out_dir, client, year)
    return {
        'client':      client,
        'sessions':    len(session_map),
        'recordings':  len(records),
        'with_tech':   sum(1 for r in records if r['tech_name']),
        'with_url':    sum(1 for r in records if r['teams_url']),
        'total_mb':    sum(r['file_size_bytes'] for r in records) // 1024 // 1024,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--client',         default=None, help='Single client code e.g. BWH (omit with --all)')
    ap.add_argument('--all',            action='store_true', help='Run for every client in the DB')
    ap.add_argument('--year',           default='2026')
    ap.add_argument('--no-refresh-db',  action='store_true')
    ap.add_argument('--audit-log',
                    default=r'C:\Users\rjain\OneDrive - Technijian, Inc\Technijian - My Remote - FileCabinet\_audit\audit_log.json',
                    help='Path to audit_log.json from pull_screenconnect_2026.py (for OneDrive URLs)')
    args = ap.parse_args()

    if not args.client and not args.all:
        ap.error('Provide --client CODE or --all')

    # Refresh local DB copy once
    if not args.no_refresh_db:
        import shutil
        print("Copying Session.db from server ...")
        LOCAL_DB.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REMOTE_DB, LOCAL_DB)
        wal = Path(REMOTE_DB + '-wal')
        if wal.exists():
            try:
                shutil.copy2(wal, LOCAL_DB.parent / 'Session.db-wal')
            except Exception:
                pass
        print(f"  Copied ({LOCAL_DB.stat().st_size // 1024 // 1024} MB)")

    audit_log = Path(args.audit_log)

    if args.all:
        clients = all_client_codes(LOCAL_DB)
        print(f"\nBuilding audits for {len(clients)} clients — year {args.year}\n")
        summary_rows = []
        for client in clients:
            print(f"  {client} ...", end=' ', flush=True)
            row = run_client(client, args.year, audit_log)
            summary_rows.append(row)
            print(f"{row['recordings']} recordings  {row['total_mb']} MB  "
                  f"{row['with_tech']} w/tech  {row['with_url']} w/url")

        # Print summary table
        total_recs = sum(r['recordings'] for r in summary_rows)
        total_mb   = sum(r['total_mb']   for r in summary_rows)
        with_recs  = sum(1 for r in summary_rows if r['recordings'] > 0)
        print(f"\n{'-'*62}")
        print(f"  {with_recs}/{len(clients)} clients have recordings  |  "
              f"{total_recs} total  |  {total_mb} MB")
        print(f"  Outputs: clients/{{client}}/screenconnect/{args.year}/")

    else:
        client = args.client.upper()
        out_dir = REPO_ROOT / 'clients' / client.lower() / 'screenconnect' / args.year
        print(f"Loading {client} sessions ...")
        session_map = load_session_map(LOCAL_DB, client)
        print(f"  {len(session_map)} sessions")
        tech_events = load_tech_events(LOCAL_DB, session_map)
        sessions_with_techs = sum(1 for sid in session_map if sid in tech_events)
        print(f"  {sessions_with_techs} sessions have tech connect events")
        records = scan_recordings_for_client(client, session_map, args.year)
        print(f"  {len(records)} recordings found")
        enrich_with_techs(records, tech_events)
        if audit_log.exists():
            merge_teams_urls(records, audit_log)
            urls_merged = sum(1 for r in records if r['teams_url'])
            print(f"  {urls_merged} OneDrive URLs merged from {audit_log.name}")
        write_outputs(records, out_dir, client, args.year)


if __name__ == '__main__':
    main()
