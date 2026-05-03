"""Build a Technijian-branded monthly Email Archive activity report from
MailStore SPE per-client snapshots and 2026 worker-results history.

For every client folder that has `clients/<code>/mailstore/<latest>/snapshot-*.json`
this builder:

  1. Aggregates one or more MailStore *instances* into a single client report
     (e.g. `icml` covers both `icmlending` and `icm-realestate`).
  2. Lists every mailbox being archived (user list from `users` snapshot).
  3. Reports current datastore size per instance + total across the client.
  4. Computes archive-run health for the trailing 30 days from worker results
     and surfaces a YELLOW/RED callout when archiving is unhealthy.
  5. Projects storage at 3 / 6 / 9 / 12 months out using two independent
     methods:
        - **historical**: total_messages / years_of_history × avg_msg_size
        - **recent (30d)**: items archived in the trailing 30 days × 12
     The methods often disagree when archive runs are failing — the divergence
     is the story.

Usage:
  python build_monthly_report.py --month 2026-05
  python build_monthly_report.py --month 2026-05 --only ICML
  python build_monthly_report.py --month 2026-05 --skip ORX

Output:
  clients/<code>/mailstore/monthly/<YYYY-MM>/<CODE>-Email-Archive-Monthly-<YYYY-MM>.docx
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED = REPO_ROOT / "technijian" / "shared" / "scripts"
sys.path.insert(0, str(SHARED))
import _brand as brand  # noqa: E402

from docx.shared import Inches, Pt  # noqa: E402

# Reverse map: client code -> [instanceID, ...]
CLIENT_TO_INSTANCES = {
    "icml": ["icmlending", "icm-realestate"],
    "orx": ["orthoxpress"],
}

# Hide service accounts from the per-mailbox table (they're not real mailboxes).
SERVICE_USERS = {"$archiveadmin", "archiveadmin", "admin", "$builtin", "$system"}


# -----------------------------------------------------------------------------
# Loaders
# -----------------------------------------------------------------------------
def latest_snapshot_dir(client_dir: Path) -> Path | None:
    root = client_dir / "mailstore"
    if not root.is_dir():
        return None
    candidates = [d for d in root.iterdir() if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name)]
    if not candidates:
        return None
    return sorted(candidates, key=lambda d: d.name)[-1]


def load_snapshot(snap_dir: Path, instance_id: str) -> dict | None:
    p = snap_dir / f"snapshot-{instance_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def load_worker_results(client_dir: Path, instance_id: str, year: int) -> list[dict]:
    p = client_dir / "mailstore" / str(year) / f"worker-results-{instance_id}.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("results", [])
    return data if isinstance(data, list) else []


# -----------------------------------------------------------------------------
# Calculation helpers
# -----------------------------------------------------------------------------
def fmt_gb(mb: float | int | None) -> str:
    if mb is None:
        return "—"
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.0f} MB"


def fmt_msgs(n: int | None) -> str:
    if n is None:
        return "—"
    return f"{n:,}"


def parse_iso(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", ""))
    except ValueError:
        return None


def oldest_store_date(stores: list[dict]) -> dt.date | None:
    """Stores are named YYYY-MM by convention. Pick the earliest."""
    earliest = None
    for s in stores or []:
        name = (s.get("name") or "").strip()
        m = re.match(r"(\d{4})-(\d{2})", name)
        if m:
            d = dt.date(int(m.group(1)), int(m.group(2)), 1)
            if earliest is None or d < earliest:
                earliest = d
    return earliest


def archive_health(worker_results: list[dict], today: dt.date, days: int = 30) -> dict:
    """Summarize the trailing window of archive runs."""
    cutoff = today - dt.timedelta(days=days)
    runs = [r for r in worker_results
            if (r.get("startTime") or "") >= f"{cutoff}T00:00:00"]
    succeeded = sum(1 for r in runs if r.get("result") == "succeeded")
    completed_with_errors = sum(1 for r in runs if r.get("result") == "completedWithErrors")
    failed = sum(1 for r in runs if r.get("result") == "failed")
    cancelled = sum(1 for r in runs if r.get("result") == "cancelled")
    items = sum(int(r.get("itemsArchived") or 0) for r in runs)
    healthy = succeeded + completed_with_errors  # CWE still produces archived items
    rate = (healthy / len(runs)) if runs else 0.0
    return {
        "window_days": days,
        "total_runs": len(runs),
        "succeeded": succeeded,
        "completed_with_errors": completed_with_errors,
        "failed": failed,
        "cancelled": cancelled,
        "items_archived": items,
        "success_rate": rate,
    }


def project_storage(current_mb: float, monthly_growth_mb: float, months: int) -> float:
    return current_mb + monthly_growth_mb * months


# -----------------------------------------------------------------------------
# Per-instance + per-client roll-up
# -----------------------------------------------------------------------------
def build_instance_facts(snap: dict, worker_results: list[dict], today: dt.date) -> dict:
    stats = snap.get("statistics") or {}
    inst = snap.get("instance") or {}
    stores = snap.get("stores") or []
    users_raw = snap.get("users") or []
    users_user_facing = [u for u in users_raw if u.get("userName", "").lower() not in SERVICE_USERS]
    user_info = snap.get("user_info") or {}

    total_mb = stats.get("totalSizeMB") or 0
    total_msgs = stats.get("numberOfMessages") or 0
    avg_msg_kb = ((total_mb * 1024) / total_msgs) if total_msgs else 0  # KB per message

    # Historical projection — total_messages / years × avg_msg_size
    oldest = oldest_store_date(stores)
    years_history = ((today - oldest).days / 365.25) if oldest else 0
    hist_msgs_per_yr = (total_msgs / years_history) if years_history else 0
    hist_mb_per_yr = (hist_msgs_per_yr * avg_msg_kb) / 1024

    # Recent (30d run-rate)
    health = archive_health(worker_results, today, days=30)
    recent_msgs_30d = health["items_archived"]
    recent_mb_per_yr = (recent_msgs_30d * avg_msg_kb / 1024) * (365.25 / 30)

    return {
        "instance_id": inst.get("instanceID"),
        "host": inst.get("instanceHost"),
        "status": inst.get("status"),
        "total_mb": total_mb,
        "total_msgs": total_msgs,
        "avg_msg_kb": avg_msg_kb,
        "store_count": len(stores),
        "stores": stores,
        "users_all": users_raw,
        "users_user_facing": users_user_facing,
        "user_info": user_info,
        "oldest_store": oldest,
        "years_history": years_history,
        "hist_msgs_per_yr": hist_msgs_per_yr,
        "hist_mb_per_yr": hist_mb_per_yr,
        "recent_msgs_30d": recent_msgs_30d,
        "recent_mb_per_yr": recent_mb_per_yr,
        "health": health,
    }


def aggregate_client(facts_per_instance: list[dict]) -> dict:
    total_mb = sum(f["total_mb"] for f in facts_per_instance)
    total_msgs = sum(f["total_msgs"] for f in facts_per_instance)
    user_count = sum(len(f["users_user_facing"]) for f in facts_per_instance)
    return {
        "total_mb": total_mb,
        "total_msgs": total_msgs,
        "user_count": user_count,
        "instance_count": len(facts_per_instance),
    }


# -----------------------------------------------------------------------------
# Report rendering
# -----------------------------------------------------------------------------
def health_status_label(rate: float, total_runs: int) -> tuple[str, str]:
    """Return (label, color_hex)."""
    if total_runs == 0:
        return ("No archive runs in window", brand.CORE_ORANGE_HEX)
    if rate >= 0.95:
        return ("Healthy", brand.GREEN_HEX)
    if rate >= 0.5:
        return ("Degraded", brand.CORE_ORANGE_HEX)
    return ("Critical — archiving is failing", brand.RED_HEX)


def month_label(month: str) -> str:
    return dt.datetime.strptime(month, "%Y-%m").strftime("%B %Y")


def render_report(*, code: str, location_name: str, month: str,
                  facts: list[dict], rollup: dict, today: dt.date,
                  out_path: Path) -> None:
    doc = brand.new_branded_document()
    brand.render_cover(
        doc,
        title=f"{location_name}",
        subtitle="Email Archive Monthly Report",
        footer_note="Confidential — prepared by Technijian for the named client.",
        date_text=month_label(month),
    )
    brand.add_page_break(doc)

    # ---- Executive Summary --------------------------------------------------
    brand.add_section_header(doc, "Executive Summary")
    health_rates = [f["health"]["success_rate"] for f in facts if f["health"]["total_runs"] > 0]
    overall_rate = sum(health_rates) / len(health_rates) if health_rates else 0.0
    overall_runs = sum(f["health"]["total_runs"] for f in facts)
    label, _hex = health_status_label(overall_rate, overall_runs)

    # 12-month projection — historical (more conservative, less affected by short-term outages)
    proj_12mo_hist = sum(project_storage(f["total_mb"], f["hist_mb_per_yr"] / 12, 12) for f in facts)

    brand.add_metric_card_row(doc, [
        (str(rollup["user_count"]), "Mailboxes archived", brand.CORE_BLUE),
        (fmt_gb(rollup["total_mb"]), "Total archive size", brand.CORE_BLUE),
        (label, "Archive health (30d)",
         brand.GREEN if overall_rate >= 0.95 else (brand.CORE_ORANGE if overall_rate >= 0.5 else brand.RED)),
        (fmt_gb(proj_12mo_hist), "12-month projected size", brand.TEAL),
    ])
    brand.add_body(doc, "")
    brand.add_body(doc,
        f"This report covers the email archive Technijian operates for "
        f"{location_name} as of {today.isoformat()}. The archive holds "
        f"{rollup['total_msgs']:,} messages across {rollup['user_count']} mailboxes "
        f"and consumes {fmt_gb(rollup['total_mb'])} of storage. Sections that follow "
        f"detail the mailboxes under archive, current and per-store storage usage, "
        f"trailing-30-day archive job health, and storage growth projections at "
        f"3, 6, 9, and 12 months.")

    # Surface degraded archives in a callout
    bad = [f for f in facts if f["health"]["total_runs"] > 0 and f["health"]["success_rate"] < 0.5]
    if bad:
        names = ", ".join(f["instance_id"] for f in bad)
        brand.add_callout_box(
            doc,
            f"ATTENTION: archive job runs for the following instance(s) are failing in "
            f"the trailing 30 days — {names}. New email is not being added to the archive "
            f"on the affected instance(s). See the Archive Health table below for details. "
            f"Recommend opening a Technijian support ticket to restore the failing archive profile(s).",
            accent_hex=brand.RED_HEX,
            bg_hex="FDECEC",
        )

    brand.add_page_break(doc)

    # ---- Archive Inventory --------------------------------------------------
    brand.add_section_header(doc, "Archive Inventory")
    inv_rows = []
    for f in facts:
        inv_rows.append([
            f["instance_id"],
            f["host"] or "—",
            f["status"] or "—",
            len(f["users_user_facing"]),
            f["store_count"],
            fmt_msgs(f["total_msgs"]),
            fmt_gb(f["total_mb"]),
            f["oldest_store"].isoformat() if f["oldest_store"] else "—",
        ])
    inv_rows.append([
        "TOTAL", "", "",
        rollup["user_count"], sum(f["store_count"] for f in facts),
        fmt_msgs(rollup["total_msgs"]), fmt_gb(rollup["total_mb"]), "",
    ])
    brand.styled_table(
        doc,
        ["Instance", "Host", "Status", "Boxes", "Stores", "Messages", "Size", "Oldest store"],
        inv_rows,
        col_widths=[1.05, 0.85, 0.7, 0.55, 0.55, 0.95, 0.75, 1.1],
        bold_last_row=True,
    )

    # ---- Mailboxes Being Archived ------------------------------------------
    brand.add_body(doc, "")
    brand.add_section_header(doc, "Mailboxes Being Archived")
    brand.add_body(doc,
        "Each user below has a mailbox actively under archive. The estimated size "
        "is allocated proportionally across mailboxes within the same archive "
        "instance — MailStore does not return a per-mailbox figure directly via the "
        "Management API. Service accounts (e.g. $archiveadmin) are excluded.")
    for f in facts:
        if not f["users_user_facing"]:
            continue
        per_user_mb = (f["total_mb"] / len(f["users_user_facing"])) if f["users_user_facing"] else 0
        rows = []
        for u in sorted(f["users_user_facing"], key=lambda x: (x.get("userName") or "").lower()):
            uname = u.get("userName") or ""
            info = (f["user_info"] or {}).get(uname) or {}
            emails = ", ".join((info.get("emailAddresses") or []) or [])
            auth = info.get("authentication") or {}
            auth_type = auth.get("type") if isinstance(auth, dict) else str(auth)
            rows.append([
                uname,
                info.get("fullName") or u.get("fullName") or "—",
                emails or "—",
                str(auth_type) if auth_type else "—",
                u.get("mfaStatus") or info.get("mfaStatus") or "—",
                fmt_gb(per_user_mb),
            ])
        brand.add_body(doc, f"{f['instance_id']} — {len(f['users_user_facing'])} mailbox(es), "
                            f"{fmt_gb(f['total_mb'])} total ≈ {fmt_gb(per_user_mb)} per mailbox",
                       bold=True, color=brand.DARK_CHARCOAL)
        brand.styled_table(
            doc,
            ["Username", "Full name", "Email addresses", "Auth", "MFA", "Est. size"],
            rows,
            col_widths=[1.3, 1.2, 1.75, 0.65, 0.55, 0.95],
        )
        brand.add_body(doc, "")

    brand.add_page_break(doc)

    # ---- Archive Job Health -------------------------------------------------
    brand.add_section_header(doc, "Archive Job Health (Trailing 30 Days)")
    h_rows = []
    for f in facts:
        h = f["health"]
        rate_label, _ = health_status_label(h["success_rate"], h["total_runs"])
        rate_pct = f"{h['success_rate'] * 100:.1f}%" if h["total_runs"] else "—"
        h_rows.append([
            f["instance_id"],
            h["total_runs"],
            h["succeeded"],
            h["completed_with_errors"],
            h["failed"],
            h["cancelled"],
            fmt_msgs(h["items_archived"]),
            rate_pct,
            rate_label,
        ])
    brand.styled_table(
        doc,
        ["Instance", "Runs", "OK", "OK w/Err", "Fail", "Cancel",
         "Items", "Success %", "Status"],
        h_rows,
        col_widths=[1.0, 0.5, 0.5, 0.75, 0.5, 0.6, 0.85, 0.65, 1.15],
        status_col=8,
    )

    # ---- Per-Store Detail --------------------------------------------------
    brand.add_body(doc, "")
    brand.add_section_header(doc, "Per-Store Storage Detail")
    s_rows = []
    for f in facts:
        for s in f["stores"]:
            sz_bytes = s.get("statisticsSize") or 0
            sz_mb = sz_bytes / (1024 * 1024)
            flags = []
            if s.get("error"): flags.append("ERROR")
            if s.get("searchIndexesNeedRebuild"): flags.append("INDEX REBUILD NEEDED")
            if s.get("needsUpgrade"): flags.append("NEEDS UPGRADE")
            s_rows.append([
                f["instance_id"],
                s.get("name") or "—",
                s.get("requestedState") or "—",
                fmt_msgs(s.get("statisticsCount") or 0),
                fmt_gb(sz_mb),
                ", ".join(flags) if flags else "Healthy",
            ])
    if s_rows:
        brand.styled_table(
            doc,
            ["Instance", "Store", "State", "Messages", "Size", "Health"],
            s_rows,
            col_widths=[1.2, 1.0, 0.8, 1.1, 0.8, 1.6],
            status_col=5,
        )

    brand.add_page_break(doc)

    # ---- Storage Growth Projections ----------------------------------------
    brand.add_section_header(doc, "Storage Growth & Projections")
    brand.add_body(doc,
        "Projections use two independent methods so any divergence is visible:")
    brand.add_bullet(doc, "uses the average message volume since the archive was first opened (smooths short-term outages).",
                     bold_prefix="Historical: ")
    brand.add_bullet(doc, "uses the items archived in the trailing 30 days, scaled to a year (catches recent acceleration or stalls).",
                     bold_prefix="Recent (30d): ")
    brand.add_body(doc,
        "When the archive job is failing, the recent figure trends to zero and the "
        "historical figure is the better planning baseline.")

    proj_rows = []
    for f in facts:
        for label, mb_per_yr in [("Historical", f["hist_mb_per_yr"]),
                                  ("Recent (30d)", f["recent_mb_per_yr"])]:
            mb_per_mo = mb_per_yr / 12
            proj_rows.append([
                f["instance_id"],
                label,
                fmt_gb(f["total_mb"]),
                fmt_gb(mb_per_mo),
                fmt_gb(project_storage(f["total_mb"], mb_per_mo, 3)),
                fmt_gb(project_storage(f["total_mb"], mb_per_mo, 6)),
                fmt_gb(project_storage(f["total_mb"], mb_per_mo, 9)),
                fmt_gb(project_storage(f["total_mb"], mb_per_mo, 12)),
            ])

    # Client total (historical + recent rollups)
    total_hist_per_mo = sum(f["hist_mb_per_yr"] for f in facts) / 12
    total_recent_per_mo = sum(f["recent_mb_per_yr"] for f in facts) / 12
    cur_total = rollup["total_mb"]
    proj_rows.append([
        "TOTAL", "Historical", fmt_gb(cur_total), fmt_gb(total_hist_per_mo),
        fmt_gb(project_storage(cur_total, total_hist_per_mo, 3)),
        fmt_gb(project_storage(cur_total, total_hist_per_mo, 6)),
        fmt_gb(project_storage(cur_total, total_hist_per_mo, 9)),
        fmt_gb(project_storage(cur_total, total_hist_per_mo, 12)),
    ])
    proj_rows.append([
        "TOTAL", "Recent (30d)", fmt_gb(cur_total), fmt_gb(total_recent_per_mo),
        fmt_gb(project_storage(cur_total, total_recent_per_mo, 3)),
        fmt_gb(project_storage(cur_total, total_recent_per_mo, 6)),
        fmt_gb(project_storage(cur_total, total_recent_per_mo, 9)),
        fmt_gb(project_storage(cur_total, total_recent_per_mo, 12)),
    ])
    brand.styled_table(
        doc,
        ["Instance", "Method", "Now", "/month", "+3 mo", "+6 mo", "+9 mo", "+12 mo"],
        proj_rows,
        col_widths=[1.05, 0.95, 0.75, 0.7, 0.75, 0.75, 0.75, 0.8],
        bold_last_row=True,
    )

    # Trend lines (text-based ASCII sparkline using historical method)
    brand.add_body(doc, "")
    brand.add_body(doc, "Visual trend (historical projection, total client):", bold=True, color=brand.DARK_CHARCOAL)
    series = [(0, cur_total)] + [(m, project_storage(cur_total, total_hist_per_mo, m)) for m in (3, 6, 9, 12)]
    max_mb = max(v for _, v in series) or 1
    bar_rows = []
    for m, v in series:
        bar_len = int((v / max_mb) * 40)
        bar_rows.append([f"+{m} mo" if m else "Now", fmt_gb(v), "█" * bar_len])
    brand.styled_table(
        doc,
        ["Time", "Size", "Trend"],
        bar_rows,
        col_widths=[0.7, 1.0, 4.5],
    )

    # ---- Recommendations ---------------------------------------------------
    brand.add_body(doc, "")
    brand.add_section_header(doc, "Recommendations")
    recs: list[str] = []
    for f in facts:
        h = f["health"]
        if h["total_runs"] > 0 and h["success_rate"] < 0.5:
            recs.append(f"Investigate the failing archive profile on {f['instance_id']} — "
                        f"{h['failed']} of {h['total_runs']} runs in the last 30 days failed and "
                        f"no new messages were captured. Recheck source-mailbox credentials, "
                        f"network reachability, and Microsoft 365 throttling.")
        for s in f["stores"]:
            if s.get("searchIndexesNeedRebuild"):
                recs.append(f"Rebuild the search indexes on store '{s.get('name')}' "
                            f"of {f['instance_id']} (admins can do this from the SPE management console "
                            f"or via the API: SelectAllStoreIndexesForRebuild + RebuildSelectedStoreIndexes).")
            if s.get("needsUpgrade"):
                recs.append(f"Upgrade store '{s.get('name')}' on {f['instance_id']} to the current archive format.")
        # Projection-based capacity warning
        proj_12 = project_storage(f["total_mb"], f["hist_mb_per_yr"] / 12, 12)
        if proj_12 > f["total_mb"] * 1.5:
            recs.append(f"Plan for ~{fmt_gb(proj_12 - f['total_mb'])} of additional storage on "
                        f"{f['instance_id']} over the next 12 months at the historical growth rate.")
    if not recs:
        recs.append("Archive is healthy. No action items at this time.")
    for r in recs:
        brand.add_bullet(doc, r)

    # ---- Methodology footer -------------------------------------------------
    brand.add_body(doc, "")
    brand.add_section_header(doc, "About This Report", accent_color=brand.CORE_ORANGE)
    brand.add_body(doc,
        "Data is pulled directly from the on-prem MailStore Service Provider Edition "
        "(SPE) Management API. Per-mailbox sizes are estimated by even allocation "
        "across mailboxes within an instance because SPE does not expose a per-user "
        "size in the API in this version. Trend lines are linear projections — the "
        "historical line treats each year of archive history as equal weight, while "
        "the recent line treats the last 30 days as representative. Both are useful; "
        "neither models seasonal mail volume.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)


# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------
def location_name_for(client_dir: Path, fallback: str) -> str:
    meta_p = client_dir / "_meta.json"
    if meta_p.exists():
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            return meta.get("Location_Name") or fallback
        except Exception:
            pass
    return fallback


def main(argv: list[str] | None = None) -> int:
    today = dt.date.today()
    default_month = f"{today.year}-{today.month:02d}"

    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=default_month, help="YYYY-MM (default: current month)")
    ap.add_argument("--only", default=None, help="Comma-separated client codes to include (uppercase)")
    ap.add_argument("--skip", default=None, help="Comma-separated client codes to exclude (uppercase)")
    ap.add_argument("--no-proofread", action="store_true", help="Skip the proofread gate.")
    args = ap.parse_args(argv)

    only = {c.strip().lower() for c in args.only.split(",")} if args.only else None
    skip = {c.strip().lower() for c in args.skip.split(",")} if args.skip else set()
    year = int(args.month[:4])

    written: list[Path] = []
    for code, instances in CLIENT_TO_INSTANCES.items():
        if only is not None and code not in only:
            continue
        if code in skip:
            continue
        client_dir = REPO_ROOT / "clients" / code
        snap_dir = latest_snapshot_dir(client_dir)
        if not snap_dir:
            print(f"[{code.upper()}] no snapshot directory found, skipping.", file=sys.stderr)
            continue
        facts = []
        for iid in instances:
            snap = load_snapshot(snap_dir, iid)
            if not snap:
                print(f"[{code.upper()}] missing snapshot for {iid}, skipping instance.", file=sys.stderr)
                continue
            wr = load_worker_results(client_dir, iid, year)
            facts.append(build_instance_facts(snap, wr, today))
        if not facts:
            print(f"[{code.upper()}] no instance data, skipping report.", file=sys.stderr)
            continue
        rollup = aggregate_client(facts)
        loc = location_name_for(client_dir, code.upper())
        out_dir = client_dir / "mailstore" / "monthly" / args.month
        out_path = out_dir / f"{code.upper()}-Email-Archive-Monthly-{args.month}.docx"
        render_report(code=code, location_name=loc, month=args.month,
                      facts=facts, rollup=rollup, today=today, out_path=out_path)
        size = out_path.stat().st_size
        print(f"[{code.upper()}] wrote {out_path} ({size:,} bytes; "
              f"{rollup['user_count']} mailboxes, {fmt_gb(rollup['total_mb'])} total)")
        written.append(out_path)

    if not written:
        print("No reports written.", file=sys.stderr)
        return 1

    # Proofread gate
    if not args.no_proofread:
        proof = REPO_ROOT / "technijian" / "shared" / "scripts" / "proofread_docx.py"
        if proof.exists():
            sys.stdout.flush()
            expected_sections = ",".join([
                "Executive Summary",
                "Archive Inventory",
                "Mailboxes Being Archived",
                "Archive Job Health",
                "Per-Store Storage Detail",
                "Storage Growth & Projections",
                "Recommendations",
                "About This Report",
            ])
            rc = subprocess.run(
                [sys.executable, str(proof), "--sections", expected_sections, "--quiet"]
                + [str(p) for p in written]
            ).returncode
            if rc != 0:
                print("[proofread] FAILED — one or more reports did not pass the gate.", file=sys.stderr)
                return rc
            print(f"[proofread] OK — {len(written)} report(s) passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
