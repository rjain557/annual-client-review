"""Pull VM backup configuration + recent performance from VBR.

Combines per-job config (`/jobs`) with last-run state (`/jobs/states`) and
optionally the most recent N sessions per job (`/sessions?jobIdFilter=...`)
to produce a per-job summary suitable for an annual review:

    [
      {
        "id": "...",
        "name": "Backup Job - VMware",
        "type": "Backup",
        "status": "Running",
        "lastResult": "Success",
        "lastRunStartTime": "...",
        "lastRunEndTime": "...",
        "nextRunStartTime": "...",
        "destinationRepository": "...",
        "objects": [{"name": "...", "type": "VirtualMachine", ...}],
        "recentSessions": [{"creationTime": "...", "endTime": "...",
                            "result": "Success", "progressPercent": 100,
                            "processedObjects": N, "totalSize": bytes,
                            "transferredSize": bytes, "speedBps": ...}, ...]
      },
      ...
    ]

Usage:
    python get_vm_backups.py                       # JSON to stdout
    python get_vm_backups.py --out backups.json
    python get_vm_backups.py --sessions 5          # last 5 sessions per job
    python get_vm_backups.py --no-sessions         # skip session details
    python get_vm_backups.py --type Backup,BackupCopy
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from veeam_client import VeeamApiError, VeeamClient


def _index_by_id(items, key="id"):
    return {x[key]: x for x in items if isinstance(x, dict) and key in x}


def collect(c: VeeamClient, type_filter=None, sessions_per_job: int = 3):
    job_params = {}
    if type_filter:
        job_params["typeFilter"] = type_filter
    jobs = list(c.get_paged("/jobs", params=job_params))
    # /jobs/states is observed to 500 on some VBR builds; treat as optional.
    try:
        states = _index_by_id(c.get_paged("/jobs/states"))
    except (VeeamApiError, Exception) as e:
        print(f"[get_vm_backups] WARN /jobs/states unavailable: "
              f"{type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
        states = {}

    out = []
    for j in jobs:
        jid = j.get("id")
        st = states.get(jid, {})
        row = {
            "id": jid,
            "name": j.get("name"),
            "type": j.get("type"),
            "description": j.get("description"),
            "isHighPriority": j.get("isHighPriority"),
            "status": st.get("status"),
            "lastResult": st.get("lastResult"),
            "lastRunStartTime": st.get("lastRun"),
            "lastRunEndTime": st.get("lastEndTime"),
            "nextRunStartTime": st.get("nextRun"),
            "destinationRepository": st.get("destinationRepositoryName"),
            "objectsCount": st.get("objectsCount"),
            "backupSize": st.get("backupSize"),
            "dataSize": st.get("dataSize"),
            "objects": (
                j.get("virtualMachines", {}).get("includes")
                or j.get("computers", {}).get("includes")
                or j.get("backupObjects", {}).get("includes")
                or []
            ),
        }
        if sessions_per_job > 0 and jid:
            try:
                sess = list(
                    c.get_paged(
                        "/sessions",
                        params={
                            "jobIdFilter": jid,
                            "orderColumn": "CreationTime",
                            "orderAsc": "false",
                        },
                        limit=sessions_per_job,
                        max_pages=1,
                    )
                )
                projected = []
                for s in sess:
                    res = s.get("result")
                    if isinstance(res, dict):
                        result_str = res.get("result")
                        failure_msg = res.get("message")
                    else:
                        result_str = res
                        failure_msg = None
                    projected.append({
                        "id": s.get("id"),
                        "creationTime": s.get("creationTime"),
                        "endTime": s.get("endTime"),
                        "state": s.get("state"),
                        "result": result_str,
                        "failureMessage": failure_msg,
                        "progressPercent": s.get("progressPercent"),
                        "processedObjects": s.get("processedObjects"),
                        "totalSize": s.get("totalSize"),
                        "transferredSize": s.get("transferredSize"),
                        "speedBps": s.get("speed"),
                    })
                row["recentSessions"] = projected
            except Exception as e:
                row["recentSessions_error"] = str(e)
        out.append(row)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="write JSON to file (default: stdout)")
    ap.add_argument("--sessions", type=int, default=3, help="recent sessions per job")
    ap.add_argument("--no-sessions", action="store_true")
    ap.add_argument("--type", help="comma-list of job types (Backup, BackupCopy, ...)")
    ap.add_argument("--host")
    ap.add_argument("--keyfile")
    args = ap.parse_args()

    sessions = 0 if args.no_sessions else args.sessions
    types = args.type.split(",") if args.type else None

    c = VeeamClient(host=args.host, keyfile=args.keyfile)
    c.login()
    rows = collect(c, type_filter=types, sessions_per_job=sessions)

    payload = json.dumps(rows, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"wrote {len(rows)} jobs to {args.out}")
    else:
        print(payload)


if __name__ == "__main__":
    main()
