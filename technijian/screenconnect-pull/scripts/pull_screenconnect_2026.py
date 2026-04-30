"""Pull all ScreenConnect 2026 activity and recordings, convert to MP4, upload to Teams.

Data sources:
  - SQLite DB: \\\\10.100.14.10\\C$\\Program Files (x86)\\ScreenConnect\\App_Data\\Session.db
  - Recordings: \\\\10.100.14.10\\E$\\Myremote Recording\\  (flat dir, proprietary format)

Steps:
  1. Copy Session.db locally (WAL lock makes remote queries unreliable).
  2. Build session -> client map from CustomProperty1.
  3. Scan recordings dir, match each file to a client via session UUID (bytes_le).
  4. Convert each recording: .crv (no extension) -> .avi (RecordingConverter) -> .mp4 (FFmpeg).
  5. Write each .mp4 to OneDrive FileCabinet / {client}-{year}-{month}/ (auto-syncs to Teams).
  6. Emit audit_log.json: one row per recording with session metadata + Teams OneDrive URL.

Usage:
    python pull_screenconnect_2026.py [--dry-run] [--client BWH]
    python pull_screenconnect_2026.py --audit-only   # skip conversion, just write audit CSV

Output: OneDrive FileCabinet\\{CLIENT}-{YEAR}-{MONTH}\\  (auto-syncs to Teams)
Audit:  OneDrive FileCabinet\\_audit\\audit_log.json
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
REMOTE_DB   = r'\\10.100.14.10\C$\Program Files (x86)\ScreenConnect\App_Data\Session.db'
REMOTE_RECS = r'R:\\'          # mapped via: net use R: "\\10.100.14.10\E$\Myremote Recording" /persistent:yes
REMOTE_RECS_UNC = r'\\10.100.14.10\E$\Myremote Recording'   # fallback if R: not mapped
LOCAL_DB_COPY = Path(r'C:\tmp\sc_db\Session.db')

# ── regex ──────────────────────────────────────────────────────────────────────
UUID_RE = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
REC_RE  = re.compile(
    rf'^({UUID_RE})-({UUID_RE})-'
    rf'(\d{{4}})-(\d{{2}})-(\d{{2}})-(\d{{2}})-(\d{{2}})-(\d{{2}})-'
    rf'\d{{4}}-\d{{2}}-\d{{2}}-\d{{2}}-\d{{2}}-\d{{2}}$'
)


def refresh_local_db() -> Path:
    """Copy Session.db (and WAL) from TE-DC-MYRMT-01 to local temp."""
    LOCAL_DB_COPY.parent.mkdir(parents=True, exist_ok=True)
    print("Copying Session.db from server ...")
    shutil.copy2(REMOTE_DB, LOCAL_DB_COPY)
    wal = Path(REMOTE_DB + '-wal')
    if wal.exists():
        try:
            shutil.copy2(wal, LOCAL_DB_COPY.parent / 'Session.db-wal')
        except Exception:
            pass  # WAL might be locked; the .db snapshot is still useful
    print(f"  Copied to {LOCAL_DB_COPY} ({LOCAL_DB_COPY.stat().st_size // 1024 // 1024} MB)")
    return LOCAL_DB_COPY


def build_session_map(db: Path) -> dict[str, dict]:
    """Return {session_uuid_str: {client, machine, name, session_type}} from local DB."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    cur = con.cursor()
    cur.execute("""
        SELECT SessionID, CustomProperty1, GuestMachineName, Name, SessionType
        FROM Session
    """)
    result = {}
    for row in cur.fetchall():
        try:
            sid = str(uuid.UUID(bytes_le=row[0]))
            result[sid] = {
                'client':  row[1] or '',
                'machine': row[2] or '',
                'name':    row[3] or '',
                'type':    row[4],
            }
        except Exception:
            pass
    con.close()
    return result


def _recordings_dir(override: str | None = None) -> Path:
    """Return the best available recordings directory (mapped drive preferred)."""
    if override:
        return Path(override)
    mapped = Path(REMOTE_RECS)
    if mapped.exists():
        return mapped
    return Path(REMOTE_RECS_UNC)


def scan_recordings(session_map: dict,
                    client_filter: str | None = None,
                    year_filter: str = '2026',
                    recordings_dir: str | None = None) -> list[dict]:
    """Return list of recording dicts ready for conversion/upload."""
    recs = []
    rec_dir = _recordings_dir(recordings_dir)
    print(f"  Recordings dir: {rec_dir}")
    for f in rec_dir.iterdir():
        m = REC_RE.match(f.name)
        if not m:
            continue
        session_id    = m.group(1)
        connection_id = m.group(2)
        year, month, day = m.group(3), m.group(4), m.group(5)
        hour, minute, second = m.group(6), m.group(7), m.group(8)
        start_dt = f"{year}-{month}-{day}T{hour}:{minute}:{second}Z"

        if year != year_filter:
            continue  # only process recordings from the target year

        info   = session_map.get(session_id, {})
        client = info.get('client', '')

        if not client:
            continue  # skip unmatched (session purged from DB or no CP1)
        if client_filter and client.upper() != client_filter.upper():
            continue

        recs.append({
            'src_path':     str(f),
            'filename':     f.name,
            'session_id':   session_id,
            'connection_id': connection_id,
            'client':       client,
            'machine':      info.get('machine', ''),
            'session_name': info.get('name', ''),
            'session_type': info.get('type', ''),
            'year':         year,
            'month':        month,
            'day':          day,
            'start_dt':     start_dt,
            'size_bytes':   f.stat().st_size,
        })
    return recs


def _resolve_converter() -> Path | None:
    # Repo-bundled copy (preferred — works on any workstation after git clone)
    repo_bin = Path(__file__).resolve().parents[2] / 'bin' / 'SessionCaptureProcessor' / 'ScreenConnectSessionCaptureProcessor.exe'
    if repo_bin.exists():
        return repo_bin
    # Fallback: local install
    local = Path(r'C:\tools\SessionCaptureProcessor\ScreenConnectSessionCaptureProcessor.exe')
    if local.exists():
        return local
    return None


def _resolve_ffmpeg() -> str | None:
    import subprocess, os
    candidates = [
        'ffmpeg',
        str(Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WinGet' / 'Links' / 'ffmpeg.exe'),
        r'C:\ffmpeg\bin\ffmpeg.exe',
        r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
    ]
    for exe in candidates:
        try:
            subprocess.run([exe, '-version'], capture_output=True, check=True)
            return exe
        except Exception:
            continue
    return None


def convert_recording(rec: dict, out_dir: Path, *,
                      converter: Path, ffmpeg: str,
                      crf: int = 28, preset: str = 'slow',
                      dry_run: bool = False) -> dict:
    """Convert one recording file to MP4. Returns updated rec dict with mp4_path / error."""
    import subprocess
    src = Path(rec['src_path'])
    client = rec['client']
    # Folder: {client}-{year}-{month}  e.g.  BWH-2026-04
    dest_dir = out_dir / f"{client}-{rec['year']}-{rec['month']}"
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    date_str = f"{rec['year']}{rec['month']}{rec['day']}"
    stem = f"{date_str}_{client}_{rec['session_id'][:8]}_{rec['connection_id'][:8]}"
    avi_path = dest_dir / f"{stem}.avi"
    mp4_path = dest_dir / f"{stem}.mp4"

    if dry_run:
        rec['mp4_path'] = str(mp4_path)
        rec['skipped'] = False
        rec['dry_run'] = True
        return rec

    if mp4_path.exists():
        rec['mp4_path'] = str(mp4_path)
        rec['skipped'] = True
        return rec

    t0 = time.time()
    # Step 1: CRV -> AVI
    try:
        result = subprocess.run(
            [str(converter), str(src), str(avi_path)],
            capture_output=True, timeout=600
        )
        if result.returncode != 0:
            rec['error'] = f"Converter exit {result.returncode}: {result.stderr[:200]!r}"
            return rec
    except Exception as e:
        rec['error'] = f"Converter error: {e}"
        return rec

    # Step 2: AVI -> MP4
    try:
        result = subprocess.run([
            ffmpeg, '-y', '-i', str(avi_path),
            '-c:v', 'libx264', '-crf', str(crf), '-preset', preset,
            '-c:a', 'aac', '-b:a', '128k',
            '-movflags', '+faststart',
            str(mp4_path)
        ], capture_output=True, timeout=1800)
        if result.returncode != 0:
            rec['error'] = f"FFmpeg exit {result.returncode}: {result.stderr[-300:].decode('utf-8','replace')}"
            return rec
    except Exception as e:
        rec['error'] = f"FFmpeg error: {e}"
        return rec
    finally:
        if avi_path.exists():
            avi_path.unlink(missing_ok=True)

    rec['mp4_path'] = str(mp4_path)
    rec['mp4_size_bytes'] = mp4_path.stat().st_size
    rec['elapsed_seconds'] = round(time.time() - t0, 1)
    return rec


def upload_recording(rec: dict, *, dry_run: bool = False) -> dict:
    """Upload converted MP4 to Teams and store the OneDrive share URL in rec['teams_url']."""
    if 'mp4_path' not in rec or rec.get('error'):
        return rec
    sys.path.insert(0, str(Path(__file__).parent))
    from upload_to_teams import upload_file, get_token, load_destination

    if dry_run:
        rec['teams_url'] = f"https://teams.microsoft.com/dry-run/{rec['client']}/{rec['year']}-{rec['month']}/{Path(rec['mp4_path']).name}"
        return rec

    try:
        dest = load_destination()
        token = get_token()
        subfolder = dest['subfolder'].format(
            client_code=rec['client'], year=rec['year'], month=rec['month']
        )
        rename = dest['rename'].format(
            date=f"{rec['year']}{rec['month']}{rec['day']}",
            client_code=rec['client'],
            session_id=rec['session_id'],
        )
        result = upload_file(
            token=token,
            team_id=dest['team_id'],
            channel_id=dest['channel_id'],
            local_path=Path(rec['mp4_path']),
            subfolder=subfolder,
            remote_name=rename,
        )
        rec['teams_url'] = result.get('webUrl', '')
        rec['teams_drive_item_id'] = result.get('id', '')
    except Exception as e:
        rec['upload_error'] = str(e)
    return rec


def process_avi_dir(avi_dir: Path, session_map: dict,
                    out_dir: Path, ffmpeg: str,
                    client_filter: str | None = None,
                    year_filter: str = '2026',
                    crf: int = 28, preset: str = 'slow',
                    dry_run: bool = False) -> list[dict]:
    """Process a directory of pre-downloaded AVI files (from SessionCaptureProcessor GUI).

    Tries to parse filenames using the standard SC recording regex.  Falls back to
    scanning for any UUID that matches a session in session_map.
    """
    import subprocess
    # UUID pattern for fallback matching
    _UUID_PAT = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)

    recs = []
    avi_files = sorted(avi_dir.glob('*.avi'))
    print(f"  Found {len(avi_files)} AVI files in {avi_dir}")

    for f in avi_files:
        stem = f.stem
        # Try full SC filename pattern first (same as CRV but with .avi extension)
        m = REC_RE.match(stem)
        if m:
            session_id    = m.group(1)
            connection_id = m.group(2)
            year, month, day = m.group(3), m.group(4), m.group(5)
            hour, minute, second = m.group(6), m.group(7), m.group(8)
        else:
            # Fallback: find any UUID in filename that matches a known session
            uuids = _UUID_PAT.findall(stem)
            session_id = next((u.lower() for u in uuids if u.lower() in session_map), None)
            if not session_id:
                continue
            connection_id = uuids[1].lower() if len(uuids) > 1 else '00000000-0000-0000-0000-000000000000'
            # Extract date from filename digits if present
            digits = re.findall(r'\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}', stem)
            if digits:
                parts = digits[0].split('-')
                year, month, day = parts[0], parts[1], parts[2]
                hour, minute, second = parts[3], parts[4], parts[5]
            else:
                year, month, day = year_filter, '01', '01'
                hour, minute, second = '00', '00', '00'

        if year != year_filter:
            continue

        info   = session_map.get(session_id, {})
        client = info.get('client', '')
        if not client:
            continue
        if client_filter and client.upper() != client_filter.upper():
            continue

        dest_dir = out_dir / f"{client}-{year}-{month}"
        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)

        date_str = f"{year}{month}{day}"
        mp4_stem = f"{date_str}_{client}_{session_id[:8]}_{connection_id[:8]}"
        mp4_path = dest_dir / f"{mp4_stem}.mp4"

        rec = {
            'src_path':       str(f),
            'filename':       f.name,
            'session_id':     session_id,
            'connection_id':  connection_id,
            'client':         client,
            'machine':        info.get('machine', ''),
            'session_name':   info.get('name', ''),
            'session_type':   info.get('type', ''),
            'year':           year,
            'month':          month,
            'day':            day,
            'start_dt':       f"{year}-{month}-{day}T{hour}:{minute}:{second}Z",
            'size_bytes':     f.stat().st_size,
            'mp4_path':       str(mp4_path),
        }

        if dry_run:
            rec['dry_run'] = True
            recs.append(rec)
            continue

        if mp4_path.exists():
            rec['skipped'] = True
            recs.append(rec)
            continue

        import time
        t0 = time.time()
        try:
            result = subprocess.run([
                ffmpeg, '-y', '-i', str(f),
                '-c:v', 'libx264', '-crf', str(crf), '-preset', preset,
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                str(mp4_path)
            ], capture_output=True, timeout=1800)
            if result.returncode != 0:
                rec['error'] = f"FFmpeg exit {result.returncode}: {result.stderr[-300:].decode('utf-8', 'replace')}"
            else:
                rec['mp4_size_bytes']   = mp4_path.stat().st_size
                rec['elapsed_seconds']  = round(time.time() - t0, 1)
        except Exception as e:
            rec['error'] = f"FFmpeg error: {e}"

        recs.append(rec)

    return recs


def write_audit_log(recs: list[dict], out_path: Path) -> None:
    """Write audit_log.json and audit_log.csv from processed recording records."""
    import csv

    # JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(recs, indent=2, default=str), encoding='utf-8')

    # CSV
    csv_path = out_path.with_suffix('.csv')
    fields = ['client', 'year', 'month', 'day', 'session_id', 'connection_id',
              'session_name', 'machine', 'start_dt', 'size_bytes',
              'mp4_path', 'mp4_size_bytes', 'teams_url', 'error', 'skipped']
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(recs)
    print(f"Audit log: {out_path}  ({len(recs)} rows)")
    print(f"Audit CSV: {csv_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run',       action='store_true', help='Plan only, no conversion or upload')
    ap.add_argument('--audit-only',    action='store_true', help='Only write audit log, skip conversion/upload')
    ap.add_argument('--client',        default=None,        help='Filter to one client code e.g. BWH')
    ap.add_argument('--year',          default='2026',      help='Only process recordings from this year (default: 2026)')
    ap.add_argument('--output-dir',    default=r'C:\Users\rjain\OneDrive - Technijian, Inc\Technijian - My Remote - FileCabinet', help='Local output dir for MP4 files (OneDrive syncs automatically)')
    ap.add_argument('--upload',        action='store_true', help='Upload to Teams via Graph API (default: save locally, OneDrive syncs)')
    ap.add_argument('--no-refresh-db', action='store_true', help='Use existing local DB copy (skip copy step)')
    ap.add_argument('--recordings-dir', default=None,       help='Override recordings source dir (default: R:\\ then UNC fallback)')
    ap.add_argument('--from-avi-dir',  default=None,        help='Skip CRV step: compress pre-downloaded AVIs from this dir to MP4')
    ap.add_argument('--preset',        default='medium',    help='ffmpeg preset (default: medium). Use slow for better compression, ultrafast for speed.')
    ap.add_argument('--crf',           default=28, type=int, help='ffmpeg CRF quality (default: 28). Lower = better quality/larger file.')
    args = ap.parse_args()

    out_dir = Path(args.output_dir)

    # Step 1: refresh local DB copy
    if not args.no_refresh_db:
        refresh_local_db()

    # Step 2: build session map
    print("Building session map ...")
    session_map = build_session_map(LOCAL_DB_COPY)
    print(f"  {len(session_map)} sessions in DB")

    # ── AVI-first path (SessionCaptureProcessor GUI already transcoded) ──────
    if args.from_avi_dir:
        avi_dir = Path(args.from_avi_dir)
        if not avi_dir.is_dir():
            print(f"ERROR: --from-avi-dir {avi_dir} is not a directory")
            sys.exit(1)
        ffmpeg = _resolve_ffmpeg()
        if not ffmpeg:
            print("ERROR: ffmpeg not found on PATH.  Install: winget install --id Gyan.FFmpeg -e")
            sys.exit(2)
        print(f"\nProcessing pre-downloaded AVIs from {avi_dir} ...")
        recs = process_avi_dir(
            avi_dir, session_map, out_dir, ffmpeg,
            client_filter=args.client, year_filter=args.year,
            crf=args.crf, preset=args.preset,
            dry_run=args.dry_run,
        )
        ok      = sum(1 for r in recs if 'mp4_path' in r and not r.get('error') and not r.get('skipped') and not r.get('dry_run'))
        skipped = sum(1 for r in recs if r.get('skipped'))
        errors  = sum(1 for r in recs if r.get('error'))
        print(f"\n{'DRY RUN ' if args.dry_run else ''}Done: {ok} ok  {skipped} skipped  {errors} errors")
        write_audit_log(recs, out_dir / '_audit' / 'audit_log.json')
        return

    # ── Normal CRV path ───────────────────────────────────────────────────────
    print("Scanning recordings ...")
    recs = scan_recordings(session_map, client_filter=args.client,
                           year_filter=args.year, recordings_dir=args.recordings_dir)
    print(f"  {len(recs)} recordings matched")

    # Summarize
    from collections import Counter
    by_client = Counter(r['client'] for r in recs)
    for client, cnt in sorted(by_client.items()):
        total_mb = sum(r['size_bytes'] for r in recs if r['client'] == client) // 1024 // 1024
        print(f"    {client:12} {cnt:4} recordings  {total_mb:6} MB")

    if args.audit_only:
        write_audit_log(recs, out_dir / '_audit' / 'audit_log.json')
        return

    # Step 3: resolve tools
    converter = _resolve_converter()
    ffmpeg    = _resolve_ffmpeg()
    if not converter:
        print("\nERROR: ScreenConnect.RecordingConverter.exe not found.")
        print("  Copy it from the ConnectWise Control download portal to:")
        print("    C:\\tools\\ScreenConnect.RecordingConverter.exe")
        print("  Then re-run this script.")
        print("\nRunning in audit-only mode instead ...")
        write_audit_log(recs, out_dir / '_audit' / 'audit_log.json')
        sys.exit(2)
    if not ffmpeg:
        print("\nERROR: ffmpeg not found on PATH.")
        print("  Install: winget install --id Gyan.FFmpeg -e")
        sys.exit(2)

    print(f"\nConverter: {converter}")
    print(f"FFmpeg:    {ffmpeg}")

    # Step 4: convert + upload
    total = len(recs)
    ok = skipped = errors = 0
    for i, rec in enumerate(recs, 1):
        label = f"[{i}/{total}] {rec['client']} {rec['year']}-{rec['month']} {rec['session_id'][:8]}..."
        print(label, end=' ', flush=True)

        rec = convert_recording(rec, out_dir,
                                converter=converter, ffmpeg=ffmpeg,
                                dry_run=args.dry_run)
        if rec.get('error'):
            print(f"CONVERT ERROR: {rec['error']}")
            errors += 1
            continue
        if rec.get('skipped'):
            print('skip (exists)')
            skipped += 1
            continue

        if args.upload and not args.dry_run:
            rec = upload_recording(rec, dry_run=False)
            if rec.get('upload_error'):
                print(f"UPLOAD ERROR: {rec['upload_error']}")
            else:
                print(f"ok -> {rec.get('teams_url', '(no url)')}")
        else:
            print(f"ok -> {rec.get('mp4_path','')}")
        ok += 1

    print(f"\n{'DRY RUN ' if args.dry_run else ''}Done: {ok} ok  {skipped} skipped  {errors} errors")

    # Step 5: audit log
    write_audit_log(recs, out_dir / '_audit' / 'audit_log.json')


if __name__ == '__main__':
    main()
