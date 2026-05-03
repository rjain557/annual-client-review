"""
Pull 2026 Veeam VBR backup data and fan out per hosted-client folder.

Uses the existing veeam-vbr skill's VeeamClient (auth + paged GET) but avoids
two endpoints that 5xx/404 on this v13.0.1.2067 install (`/jobs/states` and
`/alarms/triggered`). Synthesizes the equivalent state from `/sessions`.

Output shape (per hosted-client code that maps to a `bkp_<CODE>` job):

    clients/<code>/veeam-vbr/2026/
        jobs.json                # all jobs whose name starts bkp_<CODE> (case-insensitive)
        sessions_2026.json       # all sessions for those jobs since 2026-01-01
        repository.json          # the destination repo (capacity/free/state)
        summary.json             # KPIs: success/warn/fail counts, last successful
        latest_session.json      # the most recent session (any result)

Plus a global cross-org log under `clients/_veeam_vbr/2026-05-02/`:
    jobs.json, sessions_2026.json, storage.json, summary.json

Usage:
    python pull_2026_per_client.py
    python pull_2026_per_client.py --since 2026-01-01 --until 2026-05-02
    python pull_2026_per_client.py --only ccc,vaf,orx
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_SCRIPTS = REPO_ROOT / ".claude" / "skills" / "veeam-vbr" / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from veeam_client import VeeamClient  # noqa: E402

# bkp_<CODE>[_<suffix>] → client folder code (lowercase)
JOB_NAME_RE = re.compile(r"^bkp[_\-]([A-Za-z0-9]+)", re.IGNORECASE)

# Map source-system codes to repo client folders. The CP convention sometimes
# differs from the Veeam naming convention (`bkp_TECH` → `technijian/`).
CODE_ALIAS = {
    "tech": "technijian",
}


def code_from_job_name(name: str) -> str | None:
    if not name:
        return None
    m = JOB_NAME_RE.match(name.strip())
    if not m:
        return None
    raw = m.group(1).lower()
    return CODE_ALIAS.get(raw, raw)


def code_from_repo_name(name: str) -> str | None:
    return code_from_job_name(name)  # same convention


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    print(f"  wrote {p.relative_to(REPO_ROOT)}  ({p.stat().st_size} bytes)")


def _gb(b):
    return None if b is None else round(b / (1024 ** 3), 2)


def _summarize_sessions(sessions: list[dict]) -> dict:
    by_result: dict[str, int] = defaultdict(int)
    last_success = None
    last_failure = None
    last_any = None
    transferred = 0
    for s in sessions:
        result = (s.get("result") or {})
        rname = result.get("result") if isinstance(result, dict) else result
        by_result[rname or "Unknown"] += 1
        ct = s.get("creationTime")
        if ct:
            if last_any is None or ct > last_any.get("creationTime", ""):
                last_any = s
            if rname == "Success" and (last_success is None or ct > last_success.get("creationTime", "")):
                last_success = s
            if rname in ("Failed", "Warning") and (
                last_failure is None or ct > last_failure.get("creationTime", "")
            ):
                last_failure = s
        if isinstance(s.get("transferredSize"), (int, float)):
            transferred += s["transferredSize"]
    return {
        "session_count": len(sessions),
        "by_result": dict(by_result),
        "last_session_at": (last_any or {}).get("creationTime"),
        "last_session_result": ((last_any or {}).get("result") or {}).get("result")
        if isinstance((last_any or {}).get("result"), dict) else None,
        "last_success_at": (last_success or {}).get("creationTime"),
        "last_failure_at": (last_failure or {}).get("creationTime"),
        "last_failure_message": ((last_failure or {}).get("result") or {}).get("message")
        if isinstance((last_failure or {}).get("result"), dict) else None,
        "total_transferred_bytes": transferred,
        "total_transferred_gb": _gb(transferred),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-01-01")
    ap.add_argument("--until", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--only", default=None, help="comma-list of client codes (lowercase)")
    args = ap.parse_args()

    only = {c.strip().lower() for c in args.only.split(",")} if args.only else None
    snapshot_date = datetime.now().strftime("%Y-%m-%d")
    global_dir = REPO_ROOT / "clients" / "_veeam_vbr" / snapshot_date
    global_dir.mkdir(parents=True, exist_ok=True)

    c = VeeamClient()
    c.login()
    info = c.get("/serverInfo")
    print(f"[veeam-vbr] {info.get('name')} v{info.get('buildVersion')}")

    # -- Storage (repos) --
    print("[veeam-vbr] GET /backupInfrastructure/repositories + /states")
    repos = list(c.get_paged("/backupInfrastructure/repositories"))
    # /states returns capacityGB/freeGB/usedSpaceGB and isOnline/path/hostName.
    rstates = {x["id"]: x for x in c.get_paged("/backupInfrastructure/repositories/states") if "id" in x}
    repos_by_id = {}
    for r in repos:
        s = rstates.get(r.get("id"), {})
        cap_gb = s.get("capacityGB")
        free_gb = s.get("freeGB")
        used_gb = s.get("usedSpaceGB")
        repos_by_id[r["id"]] = {
            "id": r.get("id"),
            "name": r.get("name") or s.get("name"),
            "type": r.get("type") or s.get("type"),
            "path": s.get("path"),
            "hostName": s.get("hostName"),
            "isOnline": s.get("isOnline"),
            "capacityGB": cap_gb,
            "freeGB": free_gb,
            "usedSpaceGB": used_gb,
            "freePercent": round(100 * free_gb / cap_gb, 1) if (cap_gb and free_gb is not None) else None,
            "makeRecentBackupsImmutable": r.get("makeRecentBackupsImmutable"),
            "immutabilityDays": r.get("immutabilityDays"),
        }
    _write(global_dir / "storage.json", list(repos_by_id.values()))

    # -- Jobs --
    print("[veeam-vbr] GET /jobs")
    jobs = list(c.get_paged("/jobs"))
    print(f"           jobs={len(jobs)}")
    _write(global_dir / "jobs.json", jobs)

    jobs_by_id = {j["id"]: j for j in jobs}
    job_to_code: dict[str, str] = {}
    code_to_jobs: dict[str, list[dict]] = defaultdict(list)
    for j in jobs:
        code = code_from_job_name(j.get("name") or "")
        if code:
            job_to_code[j["id"]] = code
            code_to_jobs[code].append(j)

    # -- Sessions for 2026 --
    # Sessions endpoint accepts a creationTimeFilter (YYYY-MM-DD)
    print(f"[veeam-vbr] GET /sessions  (since={args.since}, until={args.until})")
    sessions: list[dict] = []
    # The /sessions endpoint paginates with skip/limit; we pull pages and
    # client-side filter by creationTime to avoid ordering surprises.
    since_iso = f"{args.since}T00:00:00"
    until_iso = f"{args.until}T23:59:59"
    page_size = 500
    skip = 0
    pages = 0
    while pages < 200:  # hard ceiling
        page = c.get("/sessions", params={
            "skip": skip,
            "limit": page_size,
            "orderColumn": "CreationTime",
            "orderAsc": "false",
        })
        data = (page or {}).get("data") or []
        if not data:
            break
        # Once the page's oldest session is before since_iso, we can stop —
        # but only if all rows in this page are older
        any_in_window = False
        for s in data:
            ct = s.get("creationTime") or ""
            if ct < since_iso:
                continue
            if ct > until_iso:
                continue
            sessions.append(s)
            any_in_window = True
        # Stop when even the newest row in the next page would be < since_iso
        oldest_in_page = min((s.get("creationTime") or "" for s in data), default="")
        if oldest_in_page and oldest_in_page < since_iso:
            break
        skip += len(data)
        pages += 1
    print(f"           sessions in [{args.since}..{args.until}] = {len(sessions)} (across {pages} pages)")
    _write(global_dir / "sessions_2026.json", sessions)

    # -- Index sessions per job --
    sessions_by_job: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        jid = s.get("jobId")
        if jid:
            sessions_by_job[jid].append(s)

    # -- Global summary --
    global_summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "vbr_server": info.get("name"),
        "vbr_build": info.get("buildVersion"),
        "window": {"since": args.since, "until": args.until},
        "totals": {
            "jobs": len(jobs),
            "jobs_with_client_code": len(job_to_code),
            "client_codes": sorted(code_to_jobs.keys()),
            "sessions_in_window": len(sessions),
            "repositories": len(repos),
        },
        "by_client": {
            code: {
                "job_count": len(jlist),
                "job_names": [j.get("name") for j in jlist],
                "session_count": sum(len(sessions_by_job.get(j["id"], [])) for j in jlist),
            }
            for code, jlist in sorted(code_to_jobs.items())
        },
        **_summarize_sessions(sessions),
    }
    _write(global_dir / "summary.json", global_summary)

    # -- Per-client fan-out --
    print(f"\n[veeam-vbr] fan-out to {len(code_to_jobs)} client codes")
    for code, jlist in sorted(code_to_jobs.items()):
        if only and code not in only:
            continue
        client_dir = REPO_ROOT / "clients" / code / "veeam-vbr" / "2026"
        client_dir.mkdir(parents=True, exist_ok=True)

        jids = [j["id"] for j in jlist]
        client_sessions = [s for jid in jids for s in sessions_by_job.get(jid, [])]
        # Sort sessions desc by creation time
        client_sessions.sort(key=lambda s: s.get("creationTime") or "", reverse=True)

        # Repos referenced by these jobs
        repo_ids = {(j.get("storage") or {}).get("backupRepositoryId") for j in jlist}
        repo_ids.discard(None)
        client_repos = [repos_by_id[rid] for rid in repo_ids if rid in repos_by_id]

        _write(client_dir / "jobs.json", jlist)
        _write(client_dir / "sessions_2026.json", client_sessions)
        _write(client_dir / "repository.json", client_repos)
        _write(client_dir / "latest_session.json", client_sessions[0] if client_sessions else None)
        _write(client_dir / "summary.json", {
            "client_code": code,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "vbr_server": info.get("name"),
            "window": {"since": args.since, "until": args.until},
            "jobs": [
                {"id": j["id"], "name": j.get("name"), "type": j.get("type"),
                 "schedule_local_time": (((j.get("schedule") or {}).get("daily") or {}).get("localTime")),
                 "destinationRepositoryId": (j.get("storage") or {}).get("backupRepositoryId")}
                for j in jlist
            ],
            "repositories": client_repos,
            **_summarize_sessions(client_sessions),
        })

    print("\n[veeam-vbr] done")
    print(f"  global:  clients/_veeam_vbr/{snapshot_date}/")
    print(f"  per-client: clients/<code>/veeam-vbr/2026/  (codes: {', '.join(sorted(code_to_jobs.keys()))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
