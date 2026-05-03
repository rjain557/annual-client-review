"""Fan-out VBR pull: per-client backup data + MSP-wide storage / alerts.

Output layout (matches existing `clients/<code>/<tool>/` convention):

    clients/<code>/veeam-vbr/<YYYY>/
        backups-<YYYY-MM-DD>.json    # jobs (config + last-N sessions) for this client
        backup-jobs.csv              # convenience flat table
    clients/_veeam_vbr/<YYYY-MM-DD>/
        storage.json                 # MSP-wide repos + SOBR (single Veeam server)
        alerts.json                  # MSP-wide triggered alarms
        unmapped.json                # jobs whose name didn't resolve to a client
        run.log                      # mapping decisions

Usage:
    python pull_per_client.py --year 2026
    python pull_per_client.py --year 2026 --dry-run
    python pull_per_client.py --year 2026 --sessions 5

`--dry-run` runs the full pull and prints the routing table without writing
any per-client files (use it to vet `state/veeam-vbr-job-mapping.json`).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _job_resolver import REPO_ROOT, resolve_client
from get_alerts import collect as collect_alerts
from get_storage import collect_proxies, collect_repos, collect_sobr
from get_vm_backups import collect as collect_vm_backups
from veeam_client import VeeamClient


def _today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.now().year,
                    help="year folder under clients/<code>/veeam-vbr/<YYYY>/")
    ap.add_argument("--sessions", type=int, default=5,
                    help="recent sessions per job to include")
    ap.add_argument("--dry-run", action="store_true",
                    help="don't write per-client files; print routing table")
    ap.add_argument("--clients-root", default=str(REPO_ROOT / "clients"),
                    help="override clients/ directory root")
    ap.add_argument("--host")
    ap.add_argument("--keyfile")
    args = ap.parse_args()

    clients_root = Path(args.clients_root)
    today = _today_iso()
    year = args.year
    msp_dir = clients_root / "_veeam_vbr" / today
    if not args.dry_run:
        msp_dir.mkdir(parents=True, exist_ok=True)

    log_lines: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        log_lines.append(msg)

    log(f"[veeam-vbr] year={year} today={today} dry_run={args.dry_run}")

    c = VeeamClient(host=args.host, keyfile=args.keyfile)
    c.login()
    log(f"[veeam-vbr] auth OK -> {c.base}")

    # ---- 1. MSP-wide: storage + alerts -------------------------------------
    storage = {
        "fetchedAt": today,
        "repositories": collect_repos(c),
        "scaleOutRepositories": collect_sobr(c),
        "proxies": collect_proxies(c),
    }
    alerts = collect_alerts(c)
    log(f"[veeam-vbr] storage: {len(storage['repositories'])} repos / "
        f"{len(storage['scaleOutRepositories'])} SOBR / "
        f"{len(storage['proxies'])} proxies")
    log(f"[veeam-vbr] alerts:  {len(alerts.get('malwareEvents', []))} malware "
        f"+ {len(alerts.get('securityFindings', []))} security findings")
    if not args.dry_run:
        (msp_dir / "storage.json").write_text(
            json.dumps(storage, indent=2, default=str), encoding="utf-8")
        (msp_dir / "alerts.json").write_text(
            json.dumps(alerts, indent=2, default=str), encoding="utf-8")

    # ---- 2. per-job + fan-out ---------------------------------------------
    jobs = collect_vm_backups(c, sessions_per_job=args.sessions)
    log(f"[veeam-vbr] jobs: {len(jobs)} total")

    by_client: dict[str, list] = {}
    unmapped: list = []
    routing: list[tuple[str, str | None, str]] = []

    for j in jobs:
        code, reason = resolve_client(j.get("name"), j.get("id"))
        routing.append((j.get("name") or "", code, reason))
        if code is None and not reason.startswith("ignore:"):
            unmapped.append({"job": j, "reason": reason})
            continue
        if code is None:
            continue  # ignored
        by_client.setdefault(code, []).append(j)

    log(f"[veeam-vbr] mapped {sum(len(v) for v in by_client.values())} jobs "
        f"-> {len(by_client)} clients; unmapped={len(unmapped)}")

    # ---- 3. write per-client files ----------------------------------------
    for code, client_jobs in sorted(by_client.items()):
        client_dir = clients_root / code / "veeam-vbr" / str(year)
        if not args.dry_run:
            client_dir.mkdir(parents=True, exist_ok=True)
            (client_dir / f"backups-{today}.json").write_text(
                json.dumps(client_jobs, indent=2, default=str), encoding="utf-8")
            # convenience CSV (one row per job)
            with (client_dir / "backup-jobs.csv").open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow([
                    "name", "type", "status", "lastResult",
                    "lastRunStartTime", "lastRunEndTime", "nextRunStartTime",
                    "destinationRepository", "objectsCount", "backupSizeGB",
                    "lastSessionTransferredGB", "lastSessionDurationSec",
                ])
                for j in client_jobs:
                    # Fall back to recentSessions[0] when /jobs/states is unavailable
                    sess = (j.get("recentSessions") or [{}])[0]
                    status = j.get("status") or sess.get("state")
                    last_result = j.get("lastResult") or sess.get("result")
                    last_start = j.get("lastRunStartTime") or sess.get("creationTime")
                    last_end = j.get("lastRunEndTime") or sess.get("endTime")
                    bs = j.get("backupSize")
                    transferred = sess.get("transferredSize")
                    duration = None
                    if sess.get("creationTime") and sess.get("endTime"):
                        try:
                            from datetime import datetime as _dt
                            t0 = _dt.fromisoformat(str(sess["creationTime"]).replace("Z", "+00:00"))
                            t1 = _dt.fromisoformat(str(sess["endTime"]).replace("Z", "+00:00"))
                            duration = int((t1 - t0).total_seconds())
                        except Exception:
                            pass
                    w.writerow([
                        j.get("name"), j.get("type"), status, last_result,
                        last_start, last_end, j.get("nextRunStartTime"),
                        j.get("destinationRepository"), j.get("objectsCount"),
                        round(bs / (1024**3), 2) if bs else "",
                        round(transferred / (1024**3), 2) if transferred else "",
                        duration if duration is not None else "",
                    ])
        log(f"  -> clients/{code}/veeam-vbr/{year}/  ({len(client_jobs)} jobs)")

    # ---- 4. unmapped + run log --------------------------------------------
    if not args.dry_run:
        (msp_dir / "unmapped.json").write_text(
            json.dumps(unmapped, indent=2, default=str), encoding="utf-8")
        (msp_dir / "run.log").write_text("\n".join(log_lines), encoding="utf-8")

    # routing table to stdout (always)
    print("\nROUTING")
    print(f"{'job':50}  {'->':4}  {'client':12}  reason")
    for name, code, reason in routing:
        print(f"{name[:50]:50}  ->    {code or '<unmapped>':12}  {reason}")

    return 0 if not unmapped else 1


if __name__ == "__main__":
    sys.exit(main())
