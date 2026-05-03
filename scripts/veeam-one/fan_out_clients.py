"""
Per-client fan-out of Veeam ONE REST snapshot data.

Reads the global Veeam ONE pull from `clients/_veeam_one/<date>/` and writes
per-client slices to `clients/<code>/veeam-one/<date>/` for every code that
has either:
  - a `bkp_<CODE>` repository in repositories.json, OR
  - a `DS-NBD1-<CODE>` business-view group in business_view_groups.json

Output per client:
    clients/<code>/veeam-one/<YYYY-MM-DD>/
        repository.json          # the bkp_<CODE> entry from Veeam ONE (capacity / runway / immutability)
        business_view.json       # all DS-NBD1-<CODE> + per-VM tags found
        backup_summary.json      # rolled-up posture for this client
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

REPO_NAME_RE = re.compile(r"^bkp[_\-]([A-Za-z0-9]+)", re.IGNORECASE)
BV_NAME_RE = re.compile(r"^DS[_\-]NBD1[_\-]([A-Za-z0-9]+)", re.IGNORECASE)

CODE_ALIAS = {
    "tech": "technijian",
    "tech1": "technijian",
}


def _alias(code: str) -> str:
    return CODE_ALIAS.get(code.lower(), code.lower())


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    print(f"  wrote {p.relative_to(REPO_ROOT)}  ({p.stat().st_size} bytes)")


def _human_bytes(n) -> str:
    if n is None:
        return "-"
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} EB"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--only", default=None, help="comma-list of client codes (post-alias)")
    args = ap.parse_args()

    src = REPO_ROOT / "clients" / "_veeam_one" / args.date
    if not src.exists():
        print(f"[fan-out] ERROR: {src} not found. Run scripts/veeam-one/pull_all.py first.")
        return 2

    repos = json.loads((src / "repositories.json").read_text(encoding="utf-8"))
    groups = json.loads((src / "business_view_groups.json").read_text(encoding="utf-8"))
    cats = json.loads((src / "business_view_categories.json").read_text(encoding="utf-8"))
    cat_by_id = {c["categoryId"]: c for c in cats}
    only = {c.strip().lower() for c in args.only.split(",")} if args.only else None

    # Build per-code repo + BV index
    repo_by_code: dict[str, list[dict]] = defaultdict(list)
    for r in repos:
        m = REPO_NAME_RE.match(r.get("name") or "")
        if m:
            repo_by_code[_alias(m.group(1))].append(r)

    groups_by_code: dict[str, list[dict]] = defaultdict(list)
    for g in groups:
        m = BV_NAME_RE.match(g.get("name") or "")
        if m:
            code = _alias(m.group(1))
            cat = cat_by_id.get(g.get("categoryId"), {})
            groups_by_code[code].append({**g, "categoryName": cat.get("name"), "objectType": cat.get("type")})

    codes = sorted(set(repo_by_code) | set(groups_by_code))
    if only:
        codes = [c for c in codes if c in only]
    print(f"[fan-out] Veeam ONE -> {len(codes)} client codes: {', '.join(codes)}")

    for code in codes:
        out_dir = REPO_ROOT / "clients" / code / "veeam-one" / args.date
        client_repos = repo_by_code.get(code, [])
        client_groups = groups_by_code.get(code, [])

        cap = sum((r.get("capacityBytes") or 0) for r in client_repos)
        free = sum((r.get("freeSpaceBytes") or 0) for r in client_repos)
        used_pct = round(100 * (1 - free / cap), 1) if cap else None
        runway_min = min((r.get("outOfSpaceInDays") for r in client_repos
                          if r.get("outOfSpaceInDays") is not None), default=None)

        _write(out_dir / "repository.json", client_repos)
        _write(out_dir / "business_view.json", client_groups)
        _write(out_dir / "backup_summary.json", {
            "client_code": code,
            "generated_at": datetime.now().isoformat(),
            "veeam_one_host": "TE-DC-VONE-01 (10.7.9.135)",
            "snapshot_date": args.date,
            "repositories": [
                {
                    "name": r.get("name"), "path": r.get("path"),
                    "capacity_human": _human_bytes(r.get("capacityBytes")),
                    "free_human": _human_bytes(r.get("freeSpaceBytes")),
                    "out_of_space_in_days": r.get("outOfSpaceInDays"),
                    "running_tasks": r.get("runningTasks"),
                    "max_concurrent_tasks": r.get("maxConcurrentTasks"),
                    "is_immutable": r.get("isImmutable"),
                    "state": r.get("state"),
                }
                for r in client_repos
            ],
            "totals": {
                "capacity_human": _human_bytes(cap),
                "free_human": _human_bytes(free),
                "used_percent": used_pct,
                "runway_days_min": runway_min,
            },
            "business_view_groups": [
                {"name": g.get("name"), "category": g.get("categoryName"),
                 "object_type": g.get("objectType")}
                for g in client_groups
            ],
        })

    print(f"\n[fan-out] done — wrote per-client veeam-one snapshot for {len(codes)} clients")
    return 0


if __name__ == "__main__":
    sys.exit(main())
