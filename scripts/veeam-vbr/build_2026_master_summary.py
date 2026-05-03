"""
Build a single roll-up CSV + JSON across all hosted clients with the
2026 backup posture (jobs, sessions, success/fail rate, repo runway).

Reads:
    clients/<code>/veeam-vbr/2026/summary.json   (per-client VBR summary)
    clients/<code>/veeam-one/<date>/backup_summary.json  (capacity/runway)

Writes:
    clients/_veeam_vbr/2026-05-02/master_2026_summary.csv
    clients/_veeam_vbr/2026-05-02/master_2026_summary.json
"""
from __future__ import annotations
import csv
import json
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DATE = datetime.now().strftime("%Y-%m-%d")
GLOBAL_DIR = REPO_ROOT / "clients" / "_veeam_vbr" / SNAPSHOT_DATE


def main() -> int:
    rows = []
    for client_dir in sorted((REPO_ROOT / "clients").glob("*/veeam-vbr/2026")):
        code = client_dir.parent.parent.name
        if code.startswith("_"):
            continue
        vbr = json.loads((client_dir / "summary.json").read_text(encoding="utf-8"))
        one_path = REPO_ROOT / "clients" / code / "veeam-one" / SNAPSHOT_DATE / "backup_summary.json"
        one = json.loads(one_path.read_text(encoding="utf-8")) if one_path.exists() else {}

        by_result = vbr.get("by_result", {})
        succ = by_result.get("Success", 0)
        warn = by_result.get("Warning", 0)
        fail = by_result.get("Failed", 0)
        total = succ + warn + fail
        succ_rate = round(100 * succ / total, 1) if total else None

        totals = (one or {}).get("totals", {})
        rows.append({
            "client_code": code,
            "job_count": len(vbr.get("jobs", [])),
            "job_names": "; ".join(j["name"] for j in vbr.get("jobs", [])),
            "sessions_2026": vbr.get("session_count"),
            "success": succ,
            "warning": warn,
            "failed": fail,
            "success_rate_pct": succ_rate,
            "last_session_at": vbr.get("last_session_at"),
            "last_session_result": vbr.get("last_session_result"),
            "last_success_at": vbr.get("last_success_at"),
            "last_failure_at": vbr.get("last_failure_at"),
            "last_failure_message": (vbr.get("last_failure_message") or "")[:160],
            "repo_capacity": totals.get("capacity_human"),
            "repo_free": totals.get("free_human"),
            "repo_used_pct": totals.get("used_percent"),
            "repo_runway_days": totals.get("runway_days_min"),
        })

    rows.sort(key=lambda r: (r["repo_runway_days"] is None, r["repo_runway_days"] or 99999))

    out_csv = GLOBAL_DIR / "master_2026_summary.csv"
    out_json = GLOBAL_DIR / "master_2026_summary.json"
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    fields = list(rows[0].keys()) if rows else []
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    out_json.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")

    print(f"wrote {out_csv.relative_to(REPO_ROOT)}")
    print(f"wrote {out_json.relative_to(REPO_ROOT)}")

    print("\n=== 2026 Backup Posture (sorted by runway risk) ===")
    print(f"{'Client':<14} {'Sessions':>9} {'Succ%':>6} {'Fail':>5}  "
          f"{'Cap':>9} {'Free':>9} {'Used%':>6} {'Runway':>7}  Last")
    print("-" * 110)
    for r in rows:
        runway = f"{r['repo_runway_days']}d" if r["repo_runway_days"] is not None else "-"
        last = (r["last_session_at"] or "-")[:19]
        print(f"{r['client_code']:<14} {r['sessions_2026']:>9} "
              f"{(r['success_rate_pct'] or 0):>5.1f}% {r['failed']:>5}  "
              f"{(r['repo_capacity'] or '-'):>9} {(r['repo_free'] or '-'):>9} "
              f"{(r['repo_used_pct'] or 0):>5.1f}% {runway:>7}  {last}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
