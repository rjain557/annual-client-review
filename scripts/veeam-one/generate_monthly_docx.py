"""Generate branded monthly Veeam ONE health report per client.

Reads from ``clients/<slug>/veeam-one/<DATE>/{backup_summary,business_view,repository}.json``
and writes one Word doc per (client, month) at::

    clients/<slug>/veeam-one/reports/<NAME> - Veeam ONE Monthly Health - <YYYY-MM>.docx

Veeam ONE snapshots are point-in-time, so each month's report references
the most recent snapshot. The narrative is forward-looking: capacity
runway, repository state, business-view coverage.

Sections:
  1. Executive Summary  - KPI cards (repos, capacity used %, runway days)
  2. Repository Capacity - per-repo with runway projection
  3. Business View Coverage - what categories are being protected
  4. What Technijian Did For You
  5. Recommendations
  6. About This Report

Auto-runs the proofread gate.
"""

from __future__ import annotations

import argparse
import calendar
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED = REPO_ROOT / "technijian" / "shared" / "scripts"
sys.path.insert(0, str(SHARED))
import _brand as brand  # noqa: E402

import vendor_news  # noqa: E402
import service_highlights  # noqa: E402

PROOFREADER = SHARED / "proofread_docx.py"
CLIENTS_ROOT = REPO_ROOT / "clients"

EXPECTED_SECTIONS = [
    "Executive Summary",
    "Repository Capacity",
    "Business View Coverage",
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


def month_label(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def find_latest_snapshot(client_dir: Path) -> Path | None:
    v1_root = client_dir / "veeam-one"
    if not v1_root.exists():
        return None
    snaps = sorted(
        [p for p in v1_root.iterdir() if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}", p.name)],
        reverse=True,
    )
    return snaps[0] if snaps else None


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def render_cover(doc, customer: str, year: int, month: int):
    brand.render_cover(
        doc,
        title="Backup Health Report",
        subtitle=f"{customer} — {month_label(year, month)}",
        date_text=f"Generated {datetime.now().strftime('%Y-%m-%d')}",
        footer_note="Confidential — prepared by Technijian for the named client only.",
    )
    brand.add_page_break(doc)


def section_executive_summary(doc, customer: str, year: int, month: int, summary: dict):
    brand.add_section_header(doc, "Executive Summary")
    repos = summary.get("repositories") or []
    totals = summary.get("totals") or {}

    repo_count = len(repos)
    used_pct = totals.get("used_percent")
    runway = totals.get("runway_days_min")
    cap_human = totals.get("capacity_human") or "—"

    used_pct_str = f"{used_pct:.0f}%" if used_pct is not None else "—"
    runway_str = f"{int(runway)} days" if runway is not None else "—"

    brand.add_metric_card_row(doc, [
        (fmt_int(repo_count), "Repositories Watched", brand.CORE_BLUE),
        (cap_human,           "Total Capacity",       brand.TEAL),
        (used_pct_str,        "Used Capacity",        brand.GREEN if (used_pct or 0) < 70 else brand.CORE_ORANGE),
        (runway_str,          "Storage Runway",       brand.GREEN if (runway or 0) > 90 else brand.CORE_ORANGE),
    ])

    if repo_count == 0:
        brand.add_callout_box(
            doc,
            f"No Veeam ONE-monitored repositories were found for {customer} "
            f"during {month_label(year, month)}. The snapshot may not have "
            f"been pulled yet, or this client may not be onboarded to "
            f"Veeam ONE monitoring.",
        )
    else:
        brand.add_body(
            doc,
            f"Technijian's Veeam ONE monitoring tracked {fmt_int(repo_count)} "
            f"backup repositor{'y' if repo_count==1 else 'ies'} for "
            f"{customer} as of {summary.get('snapshot_date') or 'recently'}. "
            f"Total capacity is {cap_human} with a projected runway of "
            f"{runway_str} at the current growth rate. Capacity, repository "
            f"state, and business-view coverage are under continuous "
            f"monitoring.",
        )


def section_repos(doc, repos: list[dict]):
    brand.add_section_header(doc, "Repository Capacity")
    if not repos:
        brand.add_body(doc, "No repositories reported in this snapshot.")
        return
    rows = []
    for r in repos:
        name = (r.get("name") or "")[:35]
        cap = r.get("capacity_human") or "—"
        free = r.get("free_human") or "—"
        runway = r.get("out_of_space_in_days")
        runway_str = f"{int(runway)} days" if runway is not None else "—"
        max_tasks = r.get("max_concurrent_tasks") or "—"
        immutable = "Yes" if r.get("is_immutable") else "No"
        state = r.get("state") or "—"
        if state.lower() == "ok":
            state_label = "Healthy"
        else:
            state_label = state
        rows.append([name, cap, free, runway_str, str(max_tasks), immutable, state_label])
    brand.styled_table(
        doc,
        ["Repository", "Capacity", "Free", "Runway", "Max Tasks", "Immutable", "State"],
        rows,
        col_widths=[1.4, 0.8, 0.8, 0.9, 0.8, 0.9, 0.9],
        status_col=6,
    )


def section_business_view(doc, summary: dict):
    brand.add_section_header(doc, "Business View Coverage")
    groups = summary.get("business_view_groups") or []
    if not groups:
        brand.add_body(
            doc,
            "No business view groups were configured in Veeam ONE for "
            "this client. Business view groups are an optional feature that "
            "lets us tag protected workloads (e.g. by department, "
            "datastore, or VM tag) for clearer SLA reporting.",
        )
        return
    brand.add_body(
        doc,
        f"Veeam ONE is tracking {fmt_int(len(groups))} business view "
        f"group(s) for this client — these tags are used to roll up "
        f"backup posture by category for clearer SLA reporting.",
    )
    rows = []
    for g in groups:
        rows.append([
            (g.get("name") or "")[:50],
            g.get("category") or "—",
            g.get("object_type") or "—",
        ])
    brand.styled_table(
        doc,
        ["Group Name", "Category", "Object Type"],
        rows,
        col_widths=[3.0, 1.5, 1.5],
    )


def section_recovery_posture(doc, summary: dict):
    """Recovery runway view from the Veeam ONE perspective."""
    brand.add_section_header(doc, "Recovery Posture")
    repos = summary.get("repositories") or []
    totals = summary.get("totals") or {}
    runway = totals.get("runway_days_min")
    used_pct = totals.get("used_percent")
    immutable_count = sum(1 for r in repos if r.get("is_immutable"))

    brand.add_body(
        doc,
        "Recovery posture is the combined picture of how much capacity "
        "we have, how fast it's being consumed, and how resistant the "
        "backup chain is to ransomware. Veeam ONE projects each of "
        "these and surfaces alarms before they become incidents.",
    )
    rows = [
        ["Repositories under monitoring",      fmt_int(len(repos))],
        ["Capacity utilization",               f"{used_pct:.0f}%" if used_pct is not None else "—"],
        ["Projected storage runway",           f"{int(runway)} days" if runway is not None else "—"],
        ["Repositories with immutability",     f"{immutable_count}/{len(repos)}" if repos else "—"],
    ]
    brand.styled_table(
        doc,
        ["Recovery Metric", "Current State"],
        rows,
        col_widths=[3.5, 2.5],
    )
    if runway is not None and runway < 60:
        brand.add_callout_box(
            doc,
            f"Projected runway is {int(runway)} days. Capacity expansion "
            f"should be scheduled now to keep the runway from dropping "
            f"below operational comfort.",
            accent_hex=brand.CORE_ORANGE_HEX,
            bg_hex="FEF3EE",
        )


def section_what_technijian_did(doc, customer: str, year: int, month: int, summary: dict):
    brand.add_section_header(doc, "What Technijian Did For You")
    repos = summary.get("repositories") or []
    bullets = []
    if repos:
        bullets.append((
            f"Monitored {fmt_int(len(repos))} backup repositor"
            f"{'y' if len(repos)==1 else 'ies'} ",
            f"via Veeam ONE during {month_label(year, month)}, capturing "
            f"capacity, free space, and projected runway every day.",
        ))
    bullets.append((
        "Tracked storage runway: ",
        "Veeam ONE projects when each repository will fill at the current "
        "growth rate; we use that signal to schedule capacity expansions "
        "well before any repository hits a critical threshold.",
    ))
    bullets.append((
        "Verified backup infrastructure health: ",
        "repository state, concurrent task limits, and immutability flags "
        "were all reviewed to keep the backup posture aligned with best "
        "practice.",
    ))
    bullets.append((
        "Maintained 24×7 alerting: ",
        "any repository that approaches a capacity or health threshold "
        "raises an alarm that's triaged by Technijian's tech team.",
    ))
    for prefix, text in bullets:
        brand.add_bullet(doc, text, bold_prefix=prefix)


def section_recommendations(doc, summary: dict):
    brand.add_section_header(doc, "Recommendations")
    recs = []
    repos = summary.get("repositories") or []
    runway = summary.get("totals", {}).get("runway_days_min")
    if runway is not None and runway < 90:
        recs.append((
            "Plan capacity expansion: ",
            f"projected storage runway is {int(runway)} days. We recommend "
            f"a capacity review now so expansion is coordinated before "
            f"the runway drops below 60 days.",
        ))
    immutable_off = [r for r in repos if not r.get("is_immutable")]
    if immutable_off and len(immutable_off) == len(repos):
        recs.append((
            "Enable immutability where supported: ",
            "none of the watched repositories enforce immutable backups "
            "today. Where the underlying storage supports it, immutable "
            "retention provides strong ransomware resilience.",
        ))
    bad_state = [r for r in repos if (r.get("state") or "").lower() != "ok"]
    if bad_state:
        names = ", ".join(r.get("name") or "?" for r in bad_state[:3])
        recs.append((
            "Review repositories not in 'Ok' state: ",
            f"{names}. Email support@technijian.com for a walkthrough of "
            f"the current condition and the planned remediation.",
        ))
    if not recs:
        recs.append((
            "Stay the course: ",
            "your backup repositories are healthy — runway is comfortable, "
            "state is clean, and Technijian's monitoring will catch any "
            "deviation early.",
        ))
    for prefix, text in recs:
        brand.add_bullet(doc, text, bold_prefix=prefix)


def section_about(doc, customer: str, year: int, month: int, summary: dict):
    brand.add_section_header(doc, "About This Report")
    brand.add_body(
        doc,
        "This report is generated automatically from Veeam ONE — the "
        "monitoring layer that watches Technijian's backup infrastructure "
        "24×7. Capacity, runway, and health state are live snapshots; the "
        "calendar month above identifies the reporting period.",
    )
    brand.add_body(
        doc,
        f"Veeam ONE host: {summary.get('veeam_one_host') or 'unknown'}. "
        f"Snapshot date: {summary.get('snapshot_date') or 'unknown'}. "
        f"Report generated {datetime.now().strftime('%Y-%m-%d %H:%M')} for "
        f"client '{customer}' covering {month_label(year, month)}.",
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
    summary = load_json(snapshot_dir / "backup_summary.json", {})
    if not summary.get("repositories"):
        # try to enrich from repository.json
        summary["repositories"] = summary.get("repositories") or load_json(snapshot_dir / "repository.json", []) or []
    if not summary.get("business_view_groups"):
        summary["business_view_groups"] = load_json(snapshot_dir / "business_view.json", []) or []

    doc = brand.new_branded_document()
    render_cover(doc, customer, year, month)
    section_executive_summary(doc, customer, year, month, summary)
    section_repos(doc, summary.get("repositories") or [])
    section_business_view(doc, summary)
    section_recovery_posture(doc, summary)
    section_what_technijian_did(doc, customer, year, month, summary)
    try:
        service_highlights.render_section(doc, client_dir.name, year, month, "veeam-one", brand)
    except Exception:
        pass
    vendor_news.render_section(doc, "veeam", year, month, brand)
    section_recommendations(doc, summary)
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
        snapshot = find_latest_snapshot(client_dir)
        if snapshot is None:
            continue
        for (year, month) in months:
            customer = slug.upper()
            safe_label = "".join(c if c.isalnum() or c in " -_" else "_" for c in customer)
            out = client_dir / "veeam-one" / "reports" / f"{safe_label} - Veeam ONE Monthly Health - {year:04d}-{month:02d}.docx"
            build_report(client_dir, customer, year, month, snapshot, out)
            generated.append(out)
            print(f"  [{slug}] {year}-{month:02d} -> {out.relative_to(REPO_ROOT)}")

    print(f"\nGenerated {len(generated)} Word report(s)")
    return run_proofreader(generated)


if __name__ == "__main__":
    sys.exit(main())
