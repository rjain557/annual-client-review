"""
Pull VBR backup configuration + storage state from Veeam ONE.

Writes JSON snapshots into clients/_veeam_one/<date>/ (cross-org log; per-client
fan-out is downstream because Veeam ONE has no native client-org concept).

Output:
  clients/_veeam_one/<YYYY-MM-DD>/
    backup_servers.json
    repositories.json
    scaleout_repositories.json
    backup_summary.json     (rolled-up KPIs ready for the annual review)

Usage:
  python pull_vbr.py
  python pull_vbr.py --date 2026-05-02     (override date stamp)
  python pull_vbr.py --out path/to/dir     (custom output dir, skip date)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import veeam_one_api as v

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    print(f"  wrote {p.relative_to(REPO_ROOT)}  ({p.stat().st_size} bytes)")


def _human_bytes(n) -> str:
    if n is None: return "—"
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} EB"


def _summarize(servers: list[dict], repos: list[dict], sobr: list[dict]) -> dict:
    total_cap   = sum((r.get("capacityBytes") or 0) for r in repos)
    total_free  = sum((r.get("freeSpaceBytes") or 0) for r in repos)
    used_pct    = round(100 * (1 - total_free / total_cap), 1) if total_cap else None
    repos_warn  = [r for r in repos if (r.get("outOfSpaceInDays") or 9999) < 30]
    repos_state = {r["name"]: r.get("state") for r in repos}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "vbr_servers": [
            {
                "name": s["name"], "version": s["version"],
                "platform": s.get("platform"),
                "connection_state": s.get("connectionState"),
                "configuration_backup": s.get("isConfigurationBackupEnabled"),
                "best_practice_check": s.get("bestPracticeCheckStatus"),
                "last_bp_check": s.get("lastBestPracticeCheckDate"),
            } for s in servers
        ],
        "repository_count": len(repos),
        "sobr_count": len(sobr),
        "total_capacity_bytes": total_cap,
        "total_capacity_human": _human_bytes(total_cap),
        "total_free_bytes": total_free,
        "total_free_human":  _human_bytes(total_free),
        "used_percent": used_pct,
        "repos_lt_30d_runway": [
            {"name": r["name"], "out_of_space_in_days": r.get("outOfSpaceInDays"),
             "free_human": _human_bytes(r.get("freeSpaceBytes")),
             "capacity_human": _human_bytes(r.get("capacityBytes"))}
            for r in repos_warn
        ],
        "repo_states": repos_state,
        "immutable_repo_count": sum(1 for r in repos if r.get("isImmutable")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--out", default=None,
                    help="explicit output dir (skip clients/_veeam_one/<date>/)")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else \
              REPO_ROOT / "clients" / "_veeam_one" / args.date
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[veeam-one vbr] target: {out_dir}")

    info = v.whoami()
    print(f"[veeam-one] {info['service']} v{info['version']} on {info['machine']}")

    print("[veeam-one] GET vbr/backupServers …")
    servers = v.list_backup_servers()
    _write(out_dir / "backup_servers.json", servers)

    print("[veeam-one] GET vbr/repositories …")
    repos = v.list_repositories()
    _write(out_dir / "repositories.json", repos)

    print("[veeam-one] GET vbr/scaleOutRepositories …")
    sobr = v.list_scaleout_repositories()
    _write(out_dir / "scaleout_repositories.json", sobr)

    print("[veeam-one] GET agents (Veeam ONE Agents per VBR server) …")
    agents = v.list_agents()
    _write(out_dir / "agents.json", agents)

    summary = _summarize(servers, repos, sobr)
    _write(out_dir / "backup_summary.json", summary)

    print("\n[veeam-one] summary")
    for line in [
        f"  VBR servers     : {len(servers)}",
        f"  Repositories    : {summary['repository_count']}",
        f"  Scale-out (SOBR): {summary['sobr_count']}",
        f"  Total capacity  : {summary['total_capacity_human']}",
        f"  Total free      : {summary['total_free_human']}",
        f"  Used            : {summary['used_percent']}%",
        f"  Immutable repos : {summary['immutable_repo_count']}",
        f"  <30d runway     : {len(summary['repos_lt_30d_runway'])}",
    ]:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
