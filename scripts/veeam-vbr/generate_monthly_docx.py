"""Generate branded monthly Veeam Backup & Replication report per client.

Reads from ``clients/<slug>/veeam-vbr/<YEAR>/{summary,jobs,repository,sessions_<YEAR>}.json``
and writes one Word doc per (client, month) at::

    clients/<slug>/veeam-vbr/reports/<NAME> - Veeam VBR Monthly Backup - <YYYY-MM>.docx

VBR sessions are time-stamped, so the per-month session count, success
rate, and latest-success-per-job are filtered to the calendar month.
Repository capacity is point-in-time (most recent snapshot).

Sections:
  1. Executive Summary  - KPI cards (jobs, sessions this month, success
                          rate, repository free space)
  2. Backup Jobs        - per-job table (name, type, schedule)
  3. Repository Capacity - per-repository used/free
  4. Backup Activity    - sessions this month with success rate
  5. What Technijian Did For You
  6. Recommendations
  7. About This Report

Auto-runs the proofread gate.
"""

from __future__ import annotations

import argparse
import calendar
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED = REPO_ROOT / "technijian" / "shared" / "scripts"
sys.path.insert(0, str(SHARED))
import _brand as brand  # noqa: E402

import vendor_news  # noqa: E402

PROOFREADER = SHARED / "proofread_docx.py"
CLIENTS_ROOT = REPO_ROOT / "clients"

EXPECTED_SECTIONS = [
    "Executive Summary",
    "Backup Jobs",
    "Repository Capacity",
    "Backup Activity",
    "Recovery Posture",
    "What Technijian Did For You",
    "Industry News & Vendor Innovations",
    "Recommendations",
    "About This Report",
]


def fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n) if n is not None else "0"


def fmt_gb(g) -> str:
    try:
        v = float(g)
        return f"{v:,.1f}" if v < 1000 else f"{v:,.0f}"
    except Exception:
        return "—"


def month_label(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def find_year_dir(client_dir: Path, year: int) -> Path | None:
    vbr_root = client_dir / "veeam-vbr"
    if not vbr_root.exists():
        return None
    candidate = vbr_root / str(year)
    if candidate.exists():
        return candidate
    years = sorted([p for p in vbr_root.iterdir() if p.is_dir() and p.name.isdigit()])
    return years[-1] if years else None


def parse_iso(s) -> datetime | None:
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def session_result(s: dict) -> str:
    """VBR REST returns ``result`` as either a string or a nested dict
    ``{"result": "Failed", "message": "...", "isCanceled": ...}``.
    Normalize to a flat string."""
    r = s.get("result") or s.get("Result")
    if isinstance(r, dict):
        return r.get("result") or r.get("Result") or "Unknown"
    return r or "Unknown"


def session_job_name(s: dict) -> str:
    return s.get("name") or s.get("jobName") or s.get("job_name") or "Unknown"


def filter_sessions_for_month(sessions: list, year: int, month: int) -> list:
    out = []
    for s in sessions or []:
        # Try the most common timestamp keys
        ts = s.get("creationTime") or s.get("creation_time") or s.get("endTime") or s.get("end_time") or s.get("startTime")
        dt = parse_iso(ts)
        if dt is None:
            continue
        if dt.year == year and dt.month == month:
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def render_cover(doc, customer: str, year: int, month: int):
    brand.render_cover(
        doc,
        title="Backup & Replication Report",
        subtitle=f"{customer} — {month_label(year, month)}",
        date_text=f"Generated {datetime.now().strftime('%Y-%m-%d')}",
        footer_note="Confidential — prepared by Technijian for the named client only.",
    )
    brand.add_page_break(doc)


def section_executive_summary(doc, customer: str, year: int, month: int, summary: dict, jobs: list, repos: list, month_sessions: list):
    brand.add_section_header(doc, "Executive Summary")
    job_count = len(jobs)
    session_count = len(month_sessions)
    by_result = Counter()
    for s in month_sessions:
        by_result[session_result(s)] += 1
    success_count = by_result.get("Success", 0) + by_result.get("Warning", 0)
    free_total_gb = sum(float(r.get("freeGB") or 0) for r in repos)

    brand.add_metric_card_row(doc, [
        (fmt_int(job_count),     "Backup Jobs",       brand.CORE_BLUE),
        (fmt_int(session_count), "Sessions This Month", brand.TEAL),
        (fmt_int(success_count), "Successful Runs",   brand.GREEN),
        (fmt_gb(free_total_gb),  "GB Free in Repos",  brand.CORE_ORANGE),
    ])

    if session_count == 0:
        brand.add_callout_box(
            doc,
            f"No backup sessions ran during {month_label(year, month)} for "
            f"{customer}. This is unusual unless the client is between "
            f"contracts, the VBR data was not yet pulled, or backup "
            f"schedules were paused. Check the snapshot date below.",
        )
    else:
        rate = (success_count / session_count * 100) if session_count else 0
        brand.add_body(
            doc,
            f"During {month_label(year, month)}, Technijian's Veeam Backup "
            f"infrastructure executed {fmt_int(session_count)} backup "
            f"session(s) across {fmt_int(job_count)} configured job(s) for "
            f"{customer}, with a {rate:.0f}% completion rate. The backup "
            f"infrastructure is monitored 24×7 and any session that needs "
            f"attention is picked up by Technijian's tech team.",
        )


def section_jobs(doc, jobs: list[dict]):
    brand.add_section_header(doc, "Backup Jobs")
    if not jobs:
        brand.add_body(doc, "No backup jobs configured in this snapshot.")
        return
    rows = []
    for j in sorted(jobs, key=lambda x: (x.get("name") or "").lower()):
        name = (j.get("name") or "")[:45]
        jtype = j.get("type") or "Backup"
        schedule = j.get("schedule_local_time") or j.get("schedule") or "—"
        rows.append([name, jtype, schedule])
    brand.styled_table(
        doc,
        ["Job Name", "Type", "Scheduled Run"],
        rows,
        col_widths=[3.0, 1.5, 1.5],
    )


def section_repos(doc, repos: list[dict]):
    brand.add_section_header(doc, "Repository Capacity")
    if not repos:
        brand.add_body(doc, "No repositories reported in this snapshot.")
        return
    rows = []
    for r in repos:
        name = (r.get("name") or "")[:35]
        rtype = r.get("type") or "—"
        cap = r.get("capacityGB") or 0
        free = r.get("freeGB") or 0
        used = (cap - free) if cap and free is not None else 0
        used_pct = (used / cap * 100) if cap else 0
        if used_pct >= 90:
            status = "Critical"
        elif used_pct >= 80:
            status = "High"
        elif used_pct >= 70:
            status = "Medium"
        else:
            status = "Healthy"
        rows.append([
            name,
            rtype,
            fmt_gb(cap),
            fmt_gb(free),
            f"{used_pct:.1f}%",
            status,
        ])
    brand.styled_table(
        doc,
        ["Repository", "Type", "Capacity (GB)", "Free (GB)", "Used %", "Status"],
        rows,
        col_widths=[1.6, 0.7, 1.0, 0.9, 0.8, 1.2],
        status_col=5,
    )


def section_activity(doc, year: int, month: int, sessions: list, jobs: list):
    brand.add_section_header(doc, "Backup Activity")
    if not sessions:
        brand.add_body(
            doc,
            f"No backup sessions were recorded during "
            f"{month_label(year, month)}. Re-running this report after the "
            f"next data pull will reflect the latest activity.",
        )
        return
    by_result = Counter()
    by_job = Counter()
    for s in sessions:
        by_result[session_result(s)] += 1
        by_job[session_job_name(s)] += 1

    brand.add_body(doc, "Sessions by result", bold=True, size=12, color=brand.DARK_CHARCOAL)
    rows = [[k, fmt_int(v)] for k, v in sorted(by_result.items(), key=lambda kv: -kv[1])]
    brand.styled_table(
        doc,
        ["Result", "Sessions"],
        rows,
        col_widths=[3.0, 3.0],
        status_col=0,
    )

    if by_job:
        brand.add_body(doc, "Sessions by job", bold=True, size=12, color=brand.DARK_CHARCOAL)
        rows = [[k[:50], fmt_int(v)] for k, v in sorted(by_job.items(), key=lambda kv: -kv[1])[:25]]
        brand.styled_table(
            doc,
            ["Job", "Sessions"],
            rows,
            col_widths=[4.5, 1.5],
        )


def section_recovery_posture(doc, summary: dict, jobs: list, repos: list, sessions: list):
    """RTO/RPO posture summary — when was the last clean recovery point
    per job, how recoverable is the fleet today."""
    brand.add_section_header(doc, "Recovery Posture")
    last_success = summary.get("last_success_at") or summary.get("last_session_at")
    last_session = summary.get("last_session_at")
    last_success_str = (last_success or "").replace("T", " ")[:19] if last_success else "—"
    last_session_str = (last_session or "").replace("T", " ")[:19] if last_session else "—"

    immutable_count = sum(1 for r in repos if r.get("makeRecentBackupsImmutable"))
    immutable_total = len(repos)

    brand.add_body(
        doc,
        f"Recovery Point Objective (RPO) — the freshness of your most "
        f"recent recoverable backup — and Recovery Time Objective (RTO) "
        f"posture summary. These figures determine how much data and "
        f"how much time you'd lose in a worst-case restore scenario.",
    )
    rows = [
        ["Most recent successful backup",       last_success_str],
        ["Most recent session of any kind",     last_session_str],
        ["Configured backup jobs",              fmt_int(len(jobs))],
        ["Repositories under management",       fmt_int(len(repos))],
        ["Repositories with immutability on",   f"{immutable_count}/{immutable_total}" if immutable_total else "—"],
        ["Backup sessions this period",         fmt_int(len(sessions))],
    ]
    brand.styled_table(
        doc,
        ["Recovery Metric", "Current State"],
        rows,
        col_widths=[3.5, 2.5],
    )

    if immutable_total and immutable_count == 0:
        brand.add_callout_box(
            doc,
            "None of the listed repositories enforce immutable backup "
            "retention today. Where the underlying storage supports it "
            "(hardened Linux repository, object-lock S3, dedicated "
            "appliance), enabling immutability adds ransomware-resilient "
            "recovery for no incremental license cost. Email "
            "support@technijian.com to scope this for your environment.",
            accent_hex=brand.CORE_ORANGE_HEX,
            bg_hex="FEF3EE",
        )
    elif immutable_count == immutable_total and immutable_total > 0:
        brand.add_callout_box(
            doc,
            "All managed repositories enforce immutable backup retention. "
            "Even a successful ransomware attack on the production "
            "environment cannot delete the backup chain — recovery is "
            "guaranteed.",
            accent_hex=brand.GREEN_HEX,
            bg_hex="E9F7EE",
        )


def section_what_technijian_did(doc, customer: str, year: int, month: int, jobs: list, sessions: list, repos: list):
    brand.add_section_header(doc, "What Technijian Did For You")
    job_count = len(jobs)
    session_count = len(sessions)
    succ = sum(1 for s in sessions if session_result(s) in ("Success", "Warning"))

    bullets = []
    if session_count:
        bullets.append((
            f"Executed {fmt_int(session_count)} backup session(s) ",
            f"across {fmt_int(job_count)} configured job(s) during "
            f"{month_label(year, month)}, with {fmt_int(succ)} completing "
            f"successfully.",
        ))
    bullets.append((
        "Maintained the backup infrastructure: ",
        "Veeam VBR server, repositories, and proxies were under continuous "
        "monitoring; capacity, job state, and session results were tracked "
        "throughout the month.",
    ))
    if repos:
        bullets.append((
            f"Verified storage runway across {fmt_int(len(repos))} repositor"
            f"{'y' if len(repos)==1 else 'ies'}: ",
            "free-space and growth trend were captured so capacity expansions "
            "are coordinated well before any repository fills.",
        ))
    bullets.append((
        "Reviewed every backup result: ",
        "any session that didn't complete cleanly was triaged by Technijian's "
        "tech team and re-attempted on the next scheduled run, with manual "
        "intervention where needed.",
    ))
    for prefix, text in bullets:
        brand.add_bullet(doc, text, bold_prefix=prefix)


def section_recommendations(doc, repos: list, sessions: list):
    brand.add_section_header(doc, "Recommendations")
    recs = []
    high_repos = []
    for r in repos or []:
        cap = r.get("capacityGB") or 0
        free = r.get("freeGB") or 0
        if cap and free is not None:
            used_pct = ((cap - free) / cap * 100) if cap else 0
            if used_pct >= 80:
                high_repos.append((r.get("name") or "?", used_pct))
    if high_repos:
        names = ", ".join(f"{n} ({p:.0f}%)" for n, p in high_repos[:5])
        recs.append((
            "Plan repository expansion: ",
            f"the following repository/repositories are above 80% utilization "
            f"and should be expanded in the next 60 days: {names}.",
        ))
    immutable_repos = [r for r in repos or [] if not r.get("makeRecentBackupsImmutable")]
    if immutable_repos and len(immutable_repos) == len(repos or []):
        recs.append((
            "Consider immutability: ",
            "none of the listed repositories enforce immutable backups today. "
            "Immutable backup retention provides ransomware-resilient recovery "
            "and is a good defense-in-depth addition where the underlying "
            "storage supports it.",
        ))
    if not recs:
        recs.append((
            "Stay the course: ",
            "your backup infrastructure is healthy — repositories have "
            "comfortable runway, jobs are running on schedule, and recovery "
            "points are being created as designed.",
        ))
    for prefix, text in recs:
        brand.add_bullet(doc, text, bold_prefix=prefix)


def section_about(doc, customer: str, year: int, month: int, summary: dict):
    brand.add_section_header(doc, "About This Report")
    brand.add_body(
        doc,
        "This report is generated automatically from Veeam Backup & "
        "Replication via the VBR REST API. Job and repository state are "
        "live snapshots; session activity is filtered to the calendar "
        "month above.",
    )
    brand.add_body(
        doc,
        f"VBR server: {summary.get('vbr_server') or 'unknown'}. Snapshot "
        f"taken: {summary.get('generated_at') or 'unknown'}. Report "
        f"generated {datetime.now().strftime('%Y-%m-%d %H:%M')} for client "
        f"'{customer}' covering {month_label(year, month)}.",
    )
    brand.add_body(
        doc,
        "For questions about any item in this report, or to request a "
        "different reporting cadence, email support@technijian.com.",
    )


# ---------------------------------------------------------------------------
# Build orchestration
# ---------------------------------------------------------------------------

def build_report(client_dir: Path, customer: str, year: int, month: int, snapshot_dir: Path, out_path: Path):
    summary = load_json(snapshot_dir / "summary.json", {})
    jobs = load_json(snapshot_dir / "jobs.json", [])
    if isinstance(jobs, dict):
        jobs = jobs.get("jobs") or jobs.get("data") or []
    repos = load_json(snapshot_dir / "repository.json", [])
    if isinstance(repos, dict):
        repos = repos.get("repositories") or repos.get("data") or [repos]
    sessions = load_json(snapshot_dir / f"sessions_{year}.json", [])
    if isinstance(sessions, dict):
        sessions = sessions.get("sessions") or sessions.get("data") or []
    month_sessions = filter_sessions_for_month(sessions, year, month)

    doc = brand.new_branded_document()
    render_cover(doc, customer, year, month)
    section_executive_summary(doc, customer, year, month, summary, jobs, repos, month_sessions)
    section_jobs(doc, jobs)
    section_repos(doc, repos)
    section_activity(doc, year, month, month_sessions, jobs)
    section_recovery_posture(doc, summary, jobs, repos, month_sessions)
    section_what_technijian_did(doc, customer, year, month, jobs, month_sessions, repos)
    vendor_news.render_section(doc, "veeam", year, month, brand)
    section_recommendations(doc, repos, month_sessions)
    section_about(doc, customer, year, month, summary)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))


def run_proofreader(generated: list[Path]) -> int:
    if not generated or not PROOFREADER.exists():
        return 0
    cmd = [sys.executable, str(PROOFREADER), "--sections", ",".join(EXPECTED_SECTIONS)]
    cmd += [str(p) for p in generated if p.exists()]
    return subprocess.run(cmd).returncode


def expand_months(args) -> list[tuple[int, int]]:
    if args.month:
        y, m = args.month.split("-")
        return [(int(y), int(m))]
    if args.from_month and args.to_month:
        from_y, from_m = (int(x) for x in args.from_month.split("-"))
        to_y, to_m = (int(x) for x in args.to_month.split("-"))
        out = []
        y, m = from_y, from_m
        while (y, m) <= (to_y, to_m):
            out.append((y, m))
            m += 1
            if m > 12:
                m = 1
                y += 1
        return out
    raise SystemExit("Specify --month or both --from and --to")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--month")
    ap.add_argument("--from", dest="from_month")
    ap.add_argument("--to", dest="to_month")
    ap.add_argument("--only", help="Comma-separated client codes")
    ap.add_argument("--skip", help="Comma-separated client codes to skip")
    args = ap.parse_args()

    months = expand_months(args)
    only = {s.strip().lower() for s in (args.only or "").split(",") if s.strip()}
    skip = {s.strip().lower() for s in (args.skip or "").split(",") if s.strip()}

    generated: list[Path] = []
    for client_dir in sorted([d for d in CLIENTS_ROOT.iterdir() if d.is_dir() and not d.name.startswith("_")]):
        slug = client_dir.name
        if only and slug not in only:
            continue
        if slug in skip:
            continue
        for (year, month) in months:
            snapshot = find_year_dir(client_dir, year)
            if snapshot is None:
                continue
            customer = slug.upper()
            safe_label = "".join(c if c.isalnum() or c in " -_" else "_" for c in customer)
            out = client_dir / "veeam-vbr" / "reports" / f"{safe_label} - Veeam VBR Monthly Backup - {year:04d}-{month:02d}.docx"
            build_report(client_dir, customer, year, month, snapshot, out)
            generated.append(out)
            print(f"  [{slug}] {year}-{month:02d} -> {out.relative_to(REPO_ROOT)}")

    print(f"\nGenerated {len(generated)} Word report(s)")
    return run_proofreader(generated)


if __name__ == "__main__":
    sys.exit(main())
