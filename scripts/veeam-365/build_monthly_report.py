"""
Build per-tenant monthly Veeam Backup for Microsoft 365 reports.

Reads the latest per-tenant feed under
  clients/<slug>/veeam-365/<YYYY-MM-DD>/data.json
and the historical snapshot stream under
  clients/_veeam_365/snapshots/<YYYY-MM-DD>.json

Produces a Technijian-branded Word document at
  clients/<slug>/veeam-365/reports/<Tenant> - Veeam 365 Monthly - YYYY-MM.docx

Sections:
  1. Cover + summary
  2. Backup posture KPI cards
  3. Per-module storage breakdown (proportional estimate from RP flags)
  4. Per-user backup coverage (mailbox + OneDrive)
  5. Storage trend with 3 / 6 / 9 / 12-month projection
  6. Recommendations
  7. Appendix: methodology

Auto-runs the proofread-report gate after save.

Usage:
  python build_monthly_report.py                       # all tenants, this month
  python build_monthly_report.py --month 2026-04
  python build_monthly_report.py --only JDH,BWH
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from docx.shared import Pt, Inches

# brand helpers (shared)
sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / "technijian" / "shared" / "scripts"))
from _brand import (  # type: ignore  # noqa: E402
    add_body, add_bullet, add_callout_box, add_color_bar, add_footer,
    add_header_logo, add_metric_card_row, add_page_break, add_section_header,
    set_default_style, standard_margins, styled_table,
    CORE_BLUE, CORE_ORANGE, TEAL, GREEN, RED, BRAND_GREY, DARK_CHARCOAL,
)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
GLOBAL_OUT = REPO_ROOT / "clients" / "_veeam_365"
SNAP_DIR = GLOBAL_OUT / "snapshots"
DEFAULT_MOM_GROWTH = 0.04   # 4% per month — fallback when we have <2 snapshots
PROJECTION_HORIZONS = [3, 6, 9, 12]  # months


def humanize_bytes(n: float | int | None) -> str:
    if n is None:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.2f} {u}"
        f /= 1024
    return f"{n} B"


def latest_data_for(slug: str, month: str | None) -> tuple[Path, dict]:
    base = (GLOBAL_OUT / "internal") if slug == "_internal" else (REPO_ROOT / "clients" / slug / "veeam-365")
    if not base.exists():
        raise FileNotFoundError(base)
    candidates = sorted(p for p in base.glob("*/data.json") if p.parent.name[:7] == (month or p.parent.name[:7]))
    if not candidates:
        raise FileNotFoundError(f"no data.json under {base} for month {month or 'any'}")
    pick = candidates[-1]
    return pick, json.loads(pick.read_text(encoding="utf-8"))


def load_history_for(slug_name: str) -> list[tuple[datetime, int, dict]]:
    """
    Return [(snapshot_date, totalBytes, perModuleBytesDict)] ordered oldest-first.
    Reads every clients/_veeam_365/snapshots/*.json and finds the matching tenant.
    """
    out = []
    if not SNAP_DIR.exists():
        return out
    for fp in sorted(SNAP_DIR.glob("*.json")):
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        for t in payload.get("tenants", []):
            if t.get("name", "").upper() != slug_name.upper():
                continue
            try:
                d = datetime.fromisoformat(payload["snapshotDate"])
            except Exception:
                continue
            out.append((d, t["totals"]["usedSpaceBytes"], t.get("modules") or {}))
    out.sort(key=lambda r: r[0])
    return out


def project_growth(history: list[tuple[datetime, int, dict]], current_bytes: int) -> tuple[float, str, list[tuple[int, int]]]:
    """
    Returns (mom_growth_rate, source_label, projections[(months, projected_bytes)])
    With <2 snapshots, fall back to DEFAULT_MOM_GROWTH.
    With ≥2 snapshots, fit a linear trend in log-space → equivalent compound MoM.
    """
    if len(history) >= 2:
        # MoM compound growth from linear regression of log(bytes) vs months_elapsed
        t0 = history[0][0]
        ms, ys = [], []
        for d, b, _ in history:
            months_elapsed = (d - t0).days / 30.4375
            if b > 0:
                ms.append(months_elapsed)
                ys.append(math.log(b))
        if len(ms) >= 2:
            mean_m = sum(ms) / len(ms)
            mean_y = sum(ys) / len(ys)
            num = sum((m - mean_m) * (y - mean_y) for m, y in zip(ms, ys))
            den = sum((m - mean_m) ** 2 for m in ms) or 1
            slope = num / den
            mom = math.exp(slope) - 1
            label = f"linear regression on {len(history)} snapshots"
            projections = [(h, int(current_bytes * (1 + mom) ** h)) for h in PROJECTION_HORIZONS]
            return (mom, label, projections)

    mom = DEFAULT_MOM_GROWTH
    label = f"industry default {mom*100:.0f}% MoM (will refine after 2+ monthly snapshots)"
    projections = [(h, int(current_bytes * (1 + mom) ** h)) for h in PROJECTION_HORIZONS]
    return (mom, label, projections)


def render_trend_chart(history: list[tuple[datetime, int, dict]], current_bytes: int,
                       projections: list[tuple[int, int]], tenant_name: str) -> Path:
    fig, ax = plt.subplots(figsize=(7.0, 3.2), dpi=150)

    # Historical points
    if history:
        hx = [d for d, _, _ in history]
        hy = [b / (1024**4) for _, b, _ in history]   # to TB
        ax.plot(hx, hy, marker="o", color="#006DB6", label="Observed snapshots", linewidth=2)

    # Today + projections
    today = datetime.now(timezone.utc)
    xs = [today] + [today.replace(year=today.year + (today.month + h - 1) // 12,
                                  month=((today.month + h - 1) % 12) + 1)
                    for h, _ in projections]
    ys = [current_bytes / (1024**4)] + [b / (1024**4) for _, b in projections]
    ax.plot(xs, ys, linestyle="--", marker="s", color="#F67D4B", label="Projection", linewidth=2)

    ax.set_ylabel("Backup size (TB)", color="#1A1A2E")
    ax.set_title(f"{tenant_name} — backup storage trend & projection", color="#1A1A2E", fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.autofmt_xdate()
    fig.tight_layout()
    out = Path(tempfile.gettempdir()) / f"veeam365_trend_{tenant_name.replace(' ','_')}_{os.getpid()}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def build_report(tenant: dict, month: str, out_dir: Path) -> Path:
    name = tenant["displayName"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tenant['name']} - Veeam 365 Monthly - {month}.docx"

    doc = Document()
    set_default_style(doc)
    standard_margins(doc)
    add_header_logo(doc)
    add_footer(doc)

    # ------- Cover -------
    add_color_bar(doc, "006DB6", height_pt=6)
    add_body(doc, f"{name} — Veeam Backup for Microsoft 365", bold=True, size=22, color=CORE_BLUE)
    add_body(doc, f"Monthly Backup Report — {month}", size=12, color=BRAND_GREY)
    add_body(doc, f"M365 tenant: {tenant.get('officeName') or '—'}", size=10, color=BRAND_GREY)
    add_body(doc, f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", size=10, color=BRAND_GREY)

    # ------- Executive Summary -------
    add_section_header(doc, "Executive Summary")
    add_callout_box(
        doc,
        f"{tenant['userCount']} M365 users in this tenant are protected by Veeam Backup "
        f"for Microsoft 365. Total backup storage in use is "
        f"{humanize_bytes(tenant['totals']['usedSpaceBytes'])} across "
        f"{len(tenant['repositories'])} repositor"
        f"{'y' if len(tenant['repositories'])==1 else 'ies'}, with "
        f"{len(tenant['jobs'])} active backup job"
        f"{'' if len(tenant['jobs'])==1 else 's'}. "
        f"This report breaks down storage by Microsoft 365 service, lists per-user "
        f"backup coverage, and projects how storage will grow over the next 12 months.",
    )

    # ------- KPI cards -------
    job_count = len(tenant["jobs"])
    last_status = (tenant["jobs"][0].get("lastStatus") if tenant["jobs"] else "—") or "—"
    user_count = tenant["userCount"]
    od_covered = tenant.get("onedriveCoveredUserCount")
    used_total = tenant["totals"]["usedSpaceBytes"]
    add_metric_card_row(doc, [
        (str(user_count), "M365 Users", CORE_BLUE),
        (str(od_covered) if od_covered is not None else "—", "Users w/ OneDrive backed up", TEAL),
        (humanize_bytes(used_total), "Backup Storage Used", CORE_ORANGE),
        (str(job_count), f"Backup Jobs ({last_status})", GREEN if last_status in ("Success","Running") else CORE_ORANGE),
    ])

    # ------- Backup Posture -------
    add_section_header(doc, "Backup Posture")
    posture_rows = []
    for j in tenant["jobs"]:
        posture_rows.append([
            j.get("name") or "-",
            j.get("backupType") or "-",
            j.get("lastRun") or "-",
            j.get("lastStatus") or "-",
            "Yes" if j.get("isEnabled") else "No",
            j.get("nextRun") or "-",
        ])
    if not posture_rows:
        posture_rows.append(["(no backup jobs configured)", "-", "-", "-", "-", "-"])
    styled_table(doc, ["Job", "Backup Type", "Last Run", "Status", "Enabled", "Next Run"],
                 posture_rows, col_widths=[1.3, 1.2, 1.4, 0.8, 0.6, 1.0], status_col=3)

    # repository row
    add_body(doc, "Backup repositories:", bold=True, size=11, color=DARK_CHARCOAL)
    repo_rows = [
        [
            r.get("repositoryName") or "-",
            humanize_bytes(r.get("usedSpaceBytes")),
            humanize_bytes(r.get("capacityBytes")),
            humanize_bytes(r.get("freeSpaceBytes")),
            r.get("repositoryPath") or "-",
        ]
        for r in tenant["repositories"]
    ]
    styled_table(doc, ["Repository", "Used", "Capacity", "Free", "Path"],
                 repo_rows, col_widths=[1.3, 0.9, 0.9, 0.9, 2.4])

    # ------- Per-module breakdown -------
    add_page_break(doc)
    add_section_header(doc, "Storage by M365 Module")
    add_body(
        doc,
        "Per-module bytes are estimated by attributing the tenant's total used "
        "backup storage in proportion to how often each service appeared in "
        "restore points over the last 90 days, weighted by industry-default "
        "ratios. For exact per-mailbox / per-site sizes, run the VB365 "
        "PowerShell module (Get-VBOEntityData).",
        size=10, color=BRAND_GREY,
    )
    mod_rows = []
    for mod_name in ("Exchange", "OneDrive", "SharePoint", "Teams"):
        m = tenant["modules"][mod_name]
        share = m["estimatedShare"]
        mod_rows.append([
            mod_name,
            humanize_bytes(m["estimatedBytes"]),
            f"{share*100:.1f}%",
            f"{m['rpFlagCount']:,} / {m['rpTotalCount']:,}",
        ])
    styled_table(doc, ["Module", "Estimated Storage", "Share of Total", "RP coverage (last 90d)"],
                 mod_rows, col_widths=[1.4, 1.5, 1.3, 2.0])

    # ------- Per-user coverage -------
    add_section_header(doc, "Per-User Backup Coverage")
    users = tenant["users"]
    add_body(
        doc,
        f"{tenant['userCount']} users in the M365 directory. "
        f"Mailbox coverage is set Yes for every user when the job is "
        f"EntireOrganization (current setting). OneDrive coverage is "
        f"determined by probing /users/{{id}}/onedrives.",
        size=10, color=BRAND_GREY,
    )
    show_n = min(50, len(users))
    user_rows = []
    for u in users[:show_n]:
        user_rows.append([
            u.get("displayName") or "-",
            u.get("email") or "-",
            "Yes" if u.get("hasMailbox") else ("—" if u.get("hasMailbox") is None else "No"),
            "Yes" if u.get("hasOneDrive") else ("—" if u.get("hasOneDrive") is None else "No"),
        ])
    styled_table(doc, ["Display Name", "Email", "Mailbox", "OneDrive"],
                 user_rows, col_widths=[2.0, 2.5, 0.8, 0.9])
    if len(users) > show_n:
        add_body(doc, f"… and {len(users) - show_n:,} additional users (full list in data.json).",
                 size=9, color=BRAND_GREY)

    # ------- Trend + projection -------
    add_page_break(doc)
    add_section_header(doc, "Storage Trend & Projection", accent_color=CORE_ORANGE)
    history = load_history_for(tenant["name"])
    mom, source_label, projections = project_growth(history, used_total)

    add_body(
        doc,
        f"Projection method: {source_label}. Compound monthly growth rate "
        f"used: {mom*100:.2f}%.",
        size=10, color=BRAND_GREY,
    )

    proj_rows = [["Today (snapshot)", humanize_bytes(used_total), "—"]]
    for h, b in projections:
        delta = b - used_total
        proj_rows.append([f"+{h} months", humanize_bytes(b), f"+{humanize_bytes(delta)}"])
    styled_table(doc, ["Horizon", "Projected Storage", "Δ vs today"],
                 proj_rows, col_widths=[2.0, 2.5, 2.0], bold_last_row=False)

    # chart
    chart_path = render_trend_chart(history, used_total, projections, tenant["displayName"])
    if chart_path.exists():
        doc.add_picture(str(chart_path), width=Inches(6.5))

    # ------- Recommendations -------
    add_section_header(doc, "Recommendations")
    last_repo = tenant["repositories"][0] if tenant["repositories"] else None
    if last_repo and last_repo.get("capacityBytes") and last_repo.get("freeSpaceBytes"):
        used_pct = 1 - (last_repo["freeSpaceBytes"] / last_repo["capacityBytes"])
        add_bullet(doc, f"Repository {last_repo['repositoryName']} is "
                        f"{used_pct*100:.0f}% full ({humanize_bytes(last_repo['freeSpaceBytes'])} free of "
                        f"{humanize_bytes(last_repo['capacityBytes'])} capacity).")
        # warn at projected horizon when it would fill up
        for h, b in projections:
            growth_per_repo = b - used_total
            if last_repo["freeSpaceBytes"] - growth_per_repo < 0.10 * last_repo["capacityBytes"]:
                add_bullet(doc,
                           f"Repository will hit ~90% utilization within {h} months at the current trend "
                           "— begin capacity planning now.",
                           bold_prefix="Capacity flag: ")
                break
    if od_covered is not None and user_count and od_covered < 0.5 * user_count:
        add_bullet(doc,
                   f"Only {od_covered}/{user_count} users have OneDrive backups. "
                   "Confirm whether the remainder are intentionally excluded "
                   "(licensing, role-based scope) or need to be added.",
                   bold_prefix="Coverage gap: ")
    add_bullet(doc, "Run this report monthly. The projection accuracy improves "
                    "with each snapshot — after 3 snapshots the linear-regression "
                    "fit replaces the industry-default growth assumption.")

    # ------- Appendix -------
    add_page_break(doc)
    add_section_header(doc, "Appendix: Methodology & Data Sources")
    add_body(doc, "Data sources", bold=True, size=11, color=DARK_CHARCOAL)
    add_bullet(doc, "Veeam Backup for Microsoft 365 REST API at https://10.7.9.227:4443/v8 "
                    "(OAuth2 password grant; self-signed TLS).")
    add_bullet(doc, "Endpoints used: /Organizations, /Organizations/{id}/usedRepositories, "
                    "/Organizations/{id}/users, /Organizations/{id}/users/{uid}/onedrives, "
                    "/BackupRepositories, /Jobs, /RestorePoints?backupTimeFrom=...")
    add_body(doc, "Per-module attribution caveat", bold=True, size=11, color=DARK_CHARCOAL)
    add_callout_box(
        doc,
        "REST does not expose per-mailbox or per-OneDrive backup byte counts on this build. "
        "Per-module estimates reweight the total used storage by the share of restore points "
        "(over the trailing 90 days) that included each service. Treat the numbers as informed "
        "estimates, not invoiced figures. For ground-truth per-user/per-team sizes use the "
        "VB365 PowerShell module Get-VBOEntityData.",
    )
    add_body(doc, "Trend projection", bold=True, size=11, color=DARK_CHARCOAL)
    add_bullet(doc, "With <2 monthly snapshots: project at 4%/month compound.")
    add_bullet(doc, "With ≥2 snapshots: linear regression on log(bytes) over time.")

    doc.save(out_path)
    return out_path


REPORT_SECTIONS = [
    "Executive Summary",
    "Backup Posture",
    "Storage by M365 Module",
    "Per-User Backup Coverage",
    "Storage Trend & Projection",
    "Recommendations",
    "Appendix",
]


def proofread(path: Path) -> bool:
    """Run the shared proofreader against the Veeam-365 section list."""
    proofread_module = REPO_ROOT / "technijian" / "shared" / "scripts" / "proofread_docx.py"
    if not proofread_module.exists():
        print(f"  ! proofread_docx.py missing at {proofread_module}")
        return True
    import subprocess
    r = subprocess.run(
        [sys.executable, str(proofread_module), str(path),
         "--sections", ",".join(REPORT_SECTIONS)],
        capture_output=True, text=True,
    )
    print(r.stdout, end="")
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
    return r.returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM (default = current month)")
    ap.add_argument("--only", help="comma-separated tenant names (case-insensitive)")
    args = ap.parse_args()
    month = args.month or datetime.now().strftime("%Y-%m")
    only = {x.strip().upper() for x in args.only.split(",")} if args.only else None

    summary_path = GLOBAL_OUT / "tenant_summary.json"
    if not summary_path.exists():
        print(f"ERROR: {summary_path} missing — run pull_full.py first.", file=sys.stderr)
        sys.exit(2)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    tenants = summary["tenants"]
    if only:
        tenants = [t for t in tenants if t["name"].upper() in only]

    fail = 0
    for t in tenants:
        slug = t["clientSlug"]
        out_dir = (GLOBAL_OUT / "internal" / "reports") if slug == "_internal" else (REPO_ROOT / "clients" / slug / "veeam-365" / "reports")
        try:
            path = build_report(t, month, out_dir)
            print(f"OK  {path}")
            ok = proofread(path)
            if not ok:
                fail += 1
        except Exception as e:
            print(f"FAIL  {t['name']}: {e}", file=sys.stderr)
            fail += 1
    sys.exit(fail and 1 or 0)


if __name__ == "__main__":
    main()
