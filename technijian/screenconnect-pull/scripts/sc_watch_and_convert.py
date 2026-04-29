"""
Watches R:\ for AVI transcoding completion, then:
  1. Runs pull_screenconnect_2026.py --from-avi-dir R:\  (AVI -> MP4 into OneDrive FileCabinet)
  2. Runs build_client_audit.py --all                    (regenerate all per-client CSVs)
"""
import subprocess
import sys
import time
from pathlib import Path

RECORDINGS_DIR = Path(r'R:\\')
SCRIPT_DIR     = Path(r'c:\vscode\annual-client-review\annual-client-review\technijian\screenconnect-pull\scripts')
PULL_SCRIPT    = SCRIPT_DIR / 'pull_screenconnect_2026.py'
AUDIT_SCRIPT   = SCRIPT_DIR / 'build_client_audit.py'
LOG_FILE       = Path(r'c:\tmp\sc_watch.log')

CHECK_INTERVAL = 300   # check every 5 minutes
STABLE_CHECKS  = 3     # require 3 consecutive checks with same AVI count


def log(msg: str) -> None:
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def count_files(ext: str) -> int:
    try:
        return sum(1 for _ in RECORDINGS_DIR.iterdir() if _.suffix.lower() == ext)
    except Exception:
        return -1


def count_avi() -> int:
    try:
        return sum(1 for f in RECORDINGS_DIR.iterdir() if f.name.endswith('.avi'))
    except Exception:
        return -1


def count_crv() -> int:
    try:
        return sum(1 for f in RECORDINGS_DIR.iterdir() if '.' not in f.name)
    except Exception:
        return -1


def run(cmd: list, label: str) -> int:
    log(f"Running: {label}")
    result = subprocess.run(
        [sys.executable] + cmd,
        cwd=str(SCRIPT_DIR.parent.parent.parent),   # repo root
        timeout=7200,
    )
    log(f"  Exit code: {result.returncode}")
    return result.returncode


def main():
    log("Watcher started.")
    crv_total = count_crv()
    log(f"CRV files on R:\\: {crv_total}")

    prev_avi  = -1
    stable    = 0

    while True:
        avi = count_avi()
        crv = count_crv()
        pct = round(avi / crv * 100, 1) if crv > 0 else 0
        log(f"Progress: {avi}/{crv} AVI ({pct}%)")

        if avi == prev_avi and avi > 0:
            stable += 1
            log(f"  AVI count stable ({stable}/{STABLE_CHECKS})")
        else:
            stable = 0

        prev_avi = avi

        if stable >= STABLE_CHECKS:
            log(f"Transcoding appears complete ({avi} AVI files). Starting conversion pipeline...")
            break

        time.sleep(CHECK_INTERVAL)

    # Step 1: AVI -> MP4
    rc = run(
        [str(PULL_SCRIPT), '--from-avi-dir', str(RECORDINGS_DIR), '--no-refresh-db'],
        'pull_screenconnect_2026.py --from-avi-dir R:\\ --no-refresh-db'
    )
    if rc not in (0, 2):
        log(f"WARNING: pull script exited {rc}")

    # Step 2: rebuild all per-client audit CSVs
    rc = run(
        [str(AUDIT_SCRIPT), '--all', '--year', '2026', '--no-refresh-db'],
        'build_client_audit.py --all --year 2026 --no-refresh-db'
    )
    if rc not in (0,):
        log(f"WARNING: audit script exited {rc}")

    log("All done. Check OneDrive FileCabinet and clients/*/screenconnect/2026/ for outputs.")


if __name__ == '__main__':
    main()
