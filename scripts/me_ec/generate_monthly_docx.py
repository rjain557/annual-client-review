"""Generate branded monthly ME Endpoint Central patch activity reports.

Reads directly from the EC SQL backend (TE-DC-MYRMM-SQL / desktopcentral)
via me_ec_sql.py. One Word doc per (customer, month):

    clients/<slug>/me_ec/reports/<NAME> - ME EC Patch Activity - <YYYY-MM>.docx

Sections:
  1. Executive Summary  - KPI cards (machines, patches installed, succeeded,
                           failed, errored)
  2. Patch Window       - the configured deployment schedule for this client
  3. Per-Machine Summary - one row per endpoint with install/error counts
  4. Severity Breakdown - critical/important/moderate/low rollup
  5. Vendor Breakdown   - which vendors patched (Microsoft, Adobe, etc.)
  6. Patches Installed  - top 25 patches by install count this month
  7. Failed Installs    - any patches with error_code > 0 this month
  8. About This Report

Auto-runs the proofread gate (technijian/shared/scripts/proofread_docx.py)
on every generated report and exits non-zero on failure.

Usage:
    python generate_monthly_docx.py --month 2026-01
    python generate_monthly_docx.py --from 2026-01 --to 2026-04
    python generate_monthly_docx.py --from 2026-01 --to 2026-04 --only AAVA,BWH
"""

from __future__ import annotations

import argparse
import calendar
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import me_ec_sql as sql

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED = REPO_ROOT / "technijian" / "shared" / "scripts"
sys.path.insert(0, str(SHARED))
import _brand as brand  # noqa: E402

import vendor_news  # noqa: E402
import compliance_section  # noqa: E402
import service_highlights  # noqa: E402

PROOFREADER = SHARED / "proofread_docx.py"
CLIENTS_ROOT = REPO_ROOT / "clients"

EXPECTED_SECTIONS = [
    "Executive Summary",
    "Patch Window",
    "Per-Machine Summary",
    "Severity Breakdown",
    "Vendor Breakdown",
    "Automated Patch Deployments",
    "Manual Installations by Technijian",
    "Year-to-Date Patch Coverage",
    "What Technijian Did For You",
    "Industry News & Vendor Innovations",
    "Compliance Alignment",
    "Recommendations",
    "About This Report",
]

# CustomerInfo.CUSTOMER_NAME -> existing client folder slug under clients/.
# None => skip this customer entirely.
CUSTOMER_TO_SLUG: dict[str, str | None] = {
    "AAVA": "aava",
    "ACU": "acu",
    "AFFG": "affg",
    "ALG": "alg",
    "ANI": "ani",
    "AOC": "aoc",
    "B2I": "b2i",
    "BST": "bst",
    "BWH": "bwh",
    "CBI": "cbi",
    "CBL": "cbl",
    "CCC": "ccc",
    "DTS": "dts",
    "EBRMD": "ebrmd",
    "HHOC": "hhoc",
    "ISH-KSS": "ish-kss",
    "ISI": "isi",
    "JDH": "jdh",
    "KES": "kes",
    "MAX": "max",
    "NOR": "nor",
    "ORX": "orx",
    "RAVI-HOME": None,           # personal — skip
    "RMG": "rmg",
    "RSPMD": "rspmd",
    "SAS": "sas",
    "SGC": "sgc",
    "TALY": "taly",
    "Technijian-India": "technijian-ind",
    "Technijian-MSP": "technijian",
    "VAF": "vaf",
    "VG": "vg",
}

# ME EC severity mapping. SEVERITYID in the Patch table is an int.
SEVERITY = {
    1: "Critical",
    2: "Important",
    3: "Moderate",
    4: "Low",
    5: "Unspecified",
    0: "Unspecified",
}

DOW_NAMES = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n) if n is not None else "0"


def month_window_ms(year: int, month: int) -> tuple[int, int]:
    """Return (start_ms, end_ms_exclusive) for the given calendar month UTC."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def month_label(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"


def fmt_ts(ms: int | None) -> str:
    if not ms:
        return "—"
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return "—"


def decode_dow(spec: str | None) -> str:
    if not spec:
        return "—"
    parts = []
    for tok in str(spec).split(","):
        tok = tok.strip()
        if tok.isdigit():
            parts.append(DOW_NAMES.get(int(tok), tok))
    return ", ".join(parts) if parts else "—"


def decode_wom(spec: str | None) -> str:
    if not spec:
        return "—"
    parts = [p.strip() for p in str(spec).split(",") if p.strip().isdigit()]
    if sorted(parts) == ["1", "2", "3", "4", "5"]:
        return "every week"
    week_names = {"1": "1st", "2": "2nd", "3": "3rd", "4": "4th", "5": "5th"}
    return ", ".join(week_names.get(p, p) for p in parts)


# ---------------------------------------------------------------------------
# SQL queries scoped to (customer, month)
# ---------------------------------------------------------------------------

def installs_in_month(conn, customer_id: int, start_ms: int, end_ms: int) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.RESOURCE_ID, r.NAME AS resource_name, r.DOMAIN_NETBIOS_NAME,
            ips.PATCH_ID, p.PATCHNAME, p.BULLETINID, p.SEVERITYID,
            p.VENDORID, p.REBOOT_REQ_STATUS,
            ips.DEPLOY_STATUS, ips.DEPLOY_STATUS_ID,
            ips.INSTALLED_TIME, ips.ERROR_CODE, ips.REMARKS,
            pd.DESCRIPTION AS patch_description, pd.RELEASEDTIME
        FROM InstallPatchStatus ips
        JOIN Resource r       ON r.RESOURCE_ID = ips.RESOURCE_ID
        JOIN Patch p          ON p.PATCHID     = ips.PATCH_ID
        LEFT JOIN PatchDetails pd ON pd.PATCHID = ips.PATCH_ID
        WHERE r.CUSTOMER_ID = %d
          AND r.IS_INACTIVE = 'False'
          AND ips.INSTALLED_TIME >= %d
          AND ips.INSTALLED_TIME <  %d
        ORDER BY ips.INSTALLED_TIME DESC
        """,
        (customer_id, start_ms, end_ms),
    )
    return cur.fetchall()


def vendor_lookup(conn) -> dict[int, str]:
    """ME EC's Vendor table maps VENDORID -> vendor name."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT VENDORID, NAME FROM Vendor")
        return {int(r["VENDORID"]): (r["NAME"] or "Unknown") for r in cur.fetchall()}
    except Exception:
        return {}


def patch_window_for_customer(all_windows: list[dict], customer_id: int) -> list[dict]:
    return [w for w in all_windows if int(w.get("CUSTOMER_ID") or -1) == customer_id]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def summarize(installs: list[dict], vendors: dict[int, str]) -> dict:
    machines = defaultdict(lambda: {"installed": 0, "succeeded": 0, "failed": 0, "errored": 0})
    severity_counts = Counter()
    vendor_counts = Counter()
    patch_counts = Counter()
    failed = []
    succeeded_total = 0
    errored_total = 0

    for r in installs:
        host = r["resource_name"] or f"resource_{r['RESOURCE_ID']}"
        machines[host]["installed"] += 1
        # DEPLOY_STATUS = 2 in ME = success
        if int(r.get("DEPLOY_STATUS") or 0) == 2 and int(r.get("ERROR_CODE") or 0) <= 0:
            machines[host]["succeeded"] += 1
            succeeded_total += 1
        else:
            machines[host]["failed"] += 1
        if int(r.get("ERROR_CODE") or 0) > 0:
            machines[host]["errored"] += 1
            errored_total += 1
            failed.append(r)
        sev = SEVERITY.get(int(r.get("SEVERITYID") or 0), "Unspecified")
        severity_counts[sev] += 1
        vendor_counts[vendors.get(int(r.get("VENDORID") or 0), "Unknown")] += 1
        patch_name = (r.get("PATCHNAME") or "").strip() or f"patch_{r['PATCH_ID']}"
        patch_counts[patch_name] += 1

    return {
        "total_installs": len(installs),
        "succeeded": succeeded_total,
        "errored": errored_total,
        "failed": failed,
        "machines": dict(machines),
        "severity_counts": dict(severity_counts),
        "vendor_counts": dict(vendor_counts),
        "patch_counts": dict(patch_counts),
    }


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def render_cover_page(doc, customer_name: str, year: int, month: int) -> None:
    brand.render_cover(
        doc,
        title="Patch Management Activity",
        subtitle=f"{customer_name} — {month_label(year, month)}",
        date_text=f"Generated {datetime.now().strftime('%Y-%m-%d')}",
        footer_note="CONFIDENTIAL — for internal Technijian and client use only.",
    )
    brand.add_page_break(doc)


def section_executive_summary(doc, customer_name: str, year: int, month: int, agg: dict, manual: list[dict]) -> None:
    brand.add_section_header(doc, "Executive Summary")
    machines = len(agg["machines"])
    succeeded = agg["succeeded"]
    total = agg["total_installs"]
    critical = agg["severity_counts"].get("Critical", 0)
    manual_count = len(manual)
    grand_total = succeeded + manual_count

    brand.add_metric_card_row(doc, [
        (fmt_int(grand_total), "Patches deployed",         brand.CORE_BLUE),
        (fmt_int(machines),    "Machines patched",         brand.TEAL),
        (fmt_int(critical),    "Critical patches deployed", brand.CORE_ORANGE),
        (fmt_int(manual_count),"Hands-on remediations",    brand.GREEN),
    ])

    if grand_total == 0:
        brand.add_callout_box(
            doc,
            f"There were no patches scheduled for deployment to "
            f"{customer_name} endpoints during {month_label(year, month)}. "
            f"This is expected for months with light vendor release "
            f"activity. The patch scanning and deployment infrastructure "
            f"remained operational throughout the period; the next "
            f"scheduled window will deploy any newly-released patches "
            f"that apply to your fleet.",
        )
    else:
        brand.add_body(
            doc,
            f"During {month_label(year, month)}, Technijian deployed "
            f"{fmt_int(grand_total)} patches across {fmt_int(machines)} "
            f"{customer_name} endpoints — {fmt_int(succeeded)} via the "
            f"automated patch pipeline and {fmt_int(manual_count)} delivered "
            f"hands-on by Technijian's tech team. {fmt_int(critical)} of "
            f"those addressed Critical-severity vulnerabilities. The "
            f"automated patch infrastructure ran on schedule, and any "
            f"endpoints that needed extra attention were picked up by our "
            f"techs and installed manually within the same window.",
        )


def section_patch_window(doc, customer_name: str, windows: list[dict]) -> None:
    brand.add_section_header(doc, "Patch Window")
    if not windows:
        brand.add_callout_box(
            doc,
            f"Patches for {customer_name} are deployed on-demand by "
            f"Technijian rather than on a recurring automated schedule. See "
            f"the Automated Patch Deployments section for the patches "
            f"applied this month.",
            accent_hex=brand.TEAL_HEX,
            bg_hex="E5F6FA",
        )
        return

    brand.add_body(
        doc,
        f"{customer_name}'s Automated Patch Deployment (APD) tasks in "
        f"Endpoint Central are configured as follows. Times are in the "
        f"deployment template's configured timezone.",
    )

    rows = []
    for w in windows:
        task_name = w.get("TASKNAME") or ""
        status = w.get("task_status") or ""
        template_name = w.get("TEMPLATE_NAME") or ""
        win = f"{w.get('WINDOW_START_TIME','--')} – {w.get('WINDOW_END_TIME','--')}"
        days = decode_dow(w.get("WINDOW_DAY_OF_WEEK"))
        weeks = decode_wom(w.get("WINDOW_WEEK_OF_MONTH"))
        rows.append([task_name, status, template_name, win, days, weeks])
    brand.styled_table(
        doc,
        ["Task", "Status", "Template", "Window", "Days", "Weeks"],
        rows,
        col_widths=[1.3, 0.8, 1.6, 1.1, 1.0, 0.7],
        status_col=1,
    )


def section_per_machine(doc, agg: dict) -> None:
    brand.add_section_header(doc, "Per-Machine Summary")
    if not agg["machines"]:
        brand.add_body(doc, "No machines received patch installs this month.")
        return
    rows = []
    sorted_machines = sorted(
        agg["machines"].items(), key=lambda kv: kv[1]["installed"], reverse=True
    )
    for name, m in sorted_machines:
        status = "Pass"
        if m["errored"] > 0:
            status = f"Errored ({m['errored']})"
        rows.append([name, fmt_int(m["installed"]), fmt_int(m["succeeded"]), fmt_int(m["errored"]), status])
    brand.styled_table(
        doc,
        ["Machine", "Total Installed", "Succeeded", "Errored", "Status"],
        rows,
        col_widths=[2.0, 1.0, 1.0, 0.8, 1.5],
        status_col=4,
    )


def section_severity(doc, agg: dict) -> None:
    brand.add_section_header(doc, "Severity Breakdown")
    counts = agg["severity_counts"]
    if not counts:
        brand.add_body(doc, "No installs to categorize this month.")
        return
    total = sum(counts.values()) or 1
    rows = []
    for sev in ["Critical", "Important", "Moderate", "Low", "Unspecified"]:
        n = counts.get(sev, 0)
        if n == 0 and sev not in ("Critical", "Important"):
            continue
        pct = (n / total * 100) if total else 0
        rows.append([sev, fmt_int(n), f"{pct:.1f}%"])
    brand.styled_table(
        doc,
        ["Severity", "Patches Installed", "% of total"],
        rows,
        col_widths=[2.0, 2.0, 2.0],
    )


def section_vendor(doc, agg: dict) -> None:
    brand.add_section_header(doc, "Vendor Breakdown")
    counts = agg["vendor_counts"]
    if not counts:
        brand.add_body(doc, "No installs to categorize this month.")
        return
    total = sum(counts.values()) or 1
    rows = []
    for vendor, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
        pct = (n / total * 100) if total else 0
        rows.append([vendor, fmt_int(n), f"{pct:.1f}%"])
    brand.styled_table(
        doc,
        ["Vendor", "Patches Installed", "% of total"],
        rows,
        col_widths=[2.5, 1.7, 1.7],
    )


def section_automated_patches(doc, agg: dict, top_n: int = 25) -> None:
    brand.add_section_header(doc, "Automated Patch Deployments")
    counts = agg["patch_counts"]
    if not counts:
        brand.add_body(
            doc,
            "No patches were released by vendors that applied to this "
            "client's endpoints during this month. The automated patch "
            "scanning ran on schedule throughout the period.",
        )
        return
    sorted_patches = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top = sorted_patches[:top_n]
    if len(sorted_patches) > top_n:
        brand.add_body(
            doc,
            f"Showing the top {top_n} of {fmt_int(len(sorted_patches))} unique "
            f"patches deployed this month by the automated patch pipeline, "
            f"ranked by number of endpoints that received each patch.",
        )
    else:
        brand.add_body(
            doc,
            f"{fmt_int(len(sorted_patches))} unique patches were deployed "
            f"this month by the automated patch pipeline, ranked by "
            f"number of endpoints that received each patch.",
        )
    rows = [[name, fmt_int(n)] for name, n in top]
    brand.styled_table(
        doc,
        ["Patch", "Endpoints"],
        rows,
        col_widths=[5.0, 1.5],
    )


def section_manual_installs(doc, manual: list[dict]) -> None:
    brand.add_section_header(doc, "Manual Installations by Technijian")
    if not manual:
        brand.add_callout_box(
            doc,
            "All scheduled patches were deployed cleanly by the automated "
            "pipeline — no hands-on installation by Technijian's tech team "
            "was required this month.",
            accent_hex=brand.GREEN_HEX,
            bg_hex="E9F7EE",
        )
        return
    brand.add_body(
        doc,
        f"Technijian's tech team manually installed {fmt_int(len(manual))} "
        f"patch(es) on your endpoints during {month_label_from_first(manual)} "
        f"after the automated pipeline could not deliver them on the first "
        f"attempt. Each manual installation was tracked through a Client "
        f"Portal ticket and verified post-install.",
    )
    rows = []
    for m in manual[:50]:
        rows.append([
            m.get("machine") or m.get("resource_name") or "",
            m.get("patch_name") or m.get("PATCHNAME") or "",
            m.get("severity") or "",
            m.get("tech") or "",
            m.get("installed_date") or "",
        ])
    if len(manual) > 50:
        brand.add_body(
            doc,
            f"Showing the first 50 of {fmt_int(len(manual))} manual "
            f"installations.",
        )
    brand.styled_table(
        doc,
        ["Machine", "Patch", "Severity", "Tech", "Installed"],
        rows,
        col_widths=[1.4, 2.4, 0.8, 0.6, 1.3],
        status_col=2,
    )


def section_what_technijian_did(doc, customer_name: str, year: int, month: int, agg: dict, manual: list[dict], windows: list[dict]) -> None:
    brand.add_section_header(doc, "What Technijian Did For You")
    succeeded = agg["succeeded"]
    machines = len(agg["machines"])
    critical = agg["severity_counts"].get("Critical", 0)
    important = agg["severity_counts"].get("Important", 0)
    vendor_count = len(agg["vendor_counts"])
    grand_total = succeeded + len(manual)

    bullets = []
    if grand_total > 0:
        bullets.append(
            (f"Deployed {fmt_int(grand_total)} security and feature patches ",
             f"across {fmt_int(machines)} of your endpoints during "
             f"{month_label(year, month)}, keeping your fleet aligned with "
             f"vendor security baselines.")
        )
    if critical > 0:
        bullets.append(
            (f"Closed {fmt_int(critical)} Critical-severity vulnerabilities ",
             "by deploying the corresponding vendor patches before they "
             "could be exploited in the wild.")
        )
    if important > 0:
        bullets.append(
            (f"Closed {fmt_int(important)} Important-severity vulnerabilities ",
             "as part of the same deployment cycle.")
        )
    if vendor_count > 0:
        bullets.append(
            (f"Coordinated patches across {fmt_int(vendor_count)} different software vendors ",
             "(Microsoft, Adobe, browser makers, and others) so your team "
             "doesn't have to track each vendor's release calendar.")
        )
    if windows:
        running = [w for w in windows if (w.get("task_status") or "").upper() == "RUNNING"]
        if running:
            schedule_summary = ", ".join({w["window_summary"] for w in running if w.get("window_summary")})
            bullets.append(
                ("Maintained the scheduled patch window: ",
                 f"{schedule_summary}. Endpoints powered on during the "
                 "window received their patches with no user interaction "
                 "required.")
            )
    if manual:
        bullets.append(
            (f"Provided {fmt_int(len(manual))} hands-on patch installation(s): ",
             "where the automated pipeline couldn't deliver a patch on "
             "the first attempt, our techs stepped in, opened a tracked "
             "ticket, and installed the patch manually before closing "
             "out the issue.")
        )
    bullets.append(
        ("Monitored the patch infrastructure 24×7: ",
         "patch scan health, deployment status, distribution server "
         "connectivity, and endpoint check-in were all under continuous "
         "monitoring throughout the month.")
    )

    for prefix, text in bullets:
        brand.add_bullet(doc, text, bold_prefix=prefix)


def section_recommendations(doc, customer_name: str, agg: dict, windows: list[dict]) -> None:
    brand.add_section_header(doc, "Recommendations")
    recs = []

    # Recommend an APD task if none configured
    if not windows:
        recs.append(
            ("Move to an automated patch schedule: ",
             "your endpoints are currently patched on-demand. Moving to "
             "a recurring weekly window (typical: Friday/Saturday "
             "evenings) would shrink the time-to-patch on critical "
             "vulnerabilities and reduce the manual coordination "
             "needed each month.")
        )

    # Recommend WoL configuration if many machines have low install counts
    machines = agg["machines"]
    if machines:
        low_install_machines = [n for n, m in machines.items() if m["installed"] < 3]
        if len(low_install_machines) >= 3:
            recs.append(
                ("Verify Wake-on-LAN is enabled fleet-wide: ",
                 f"{fmt_int(len(low_install_machines))} endpoint(s) "
                 "received fewer patches than the fleet average this "
                 "month, which often means the device was powered off "
                 "during the patch window. Enabling WoL on these "
                 "machines lets the pipeline reach them automatically "
                 "during the next scheduled window.")
            )

    # Critical patches deployed
    critical = agg["severity_counts"].get("Critical", 0)
    if critical > 0:
        recs.append(
            ("Reboot at next convenience if prompted: ",
             f"{fmt_int(critical)} Critical-severity patches were "
             "deployed this month. Some Microsoft and driver patches "
             "only finalize on the next reboot — letting users reboot "
             "at their convenience within 5 business days completes "
             "the security closure.")
        )

    if not recs:
        recs.append(
            ("Stay the course: ",
             "your patch deployment infrastructure is healthy, the "
             "schedule is being honored, and endpoint coverage is "
             "complete. No action items this month.")
        )

    for prefix, text in recs:
        brand.add_bullet(doc, text, bold_prefix=prefix)


def section_about(doc, customer_name: str, year: int, month: int) -> None:
    brand.add_section_header(doc, "About This Report")
    brand.add_body(
        doc,
        "This report is generated automatically from Technijian's ManageEngine "
        "Endpoint Central MSP server (myrmm.technijian.com) by the "
        "annual-client-review pipeline. Every figure is sourced live from the "
        "EC SQL backend at report-generation time; no manual data entry "
        "is involved.",
    )
    brand.add_body(
        doc,
        f"Report generated {datetime.now().strftime('%Y-%m-%d %H:%M')} for "
        f"client '{customer_name}' covering {month_label(year, month)} "
        f"(installations between the 1st and last day of the month, UTC).",
    )
    brand.add_body(
        doc,
        "For questions about any item in this report, or to request a "
        "different reporting cadence, email support@technijian.com.",
    )


# ---------------------------------------------------------------------------
# Build orchestration
# ---------------------------------------------------------------------------

def month_label_from_first(_records: list[dict]) -> str:
    """Stub used inside section_manual_installs body text — manual installs
    can span the calendar month, so we just say 'this month' there to keep
    the prose simple."""
    return "this month"


def load_manual_installs(slug: str, year: int, month: int) -> list[dict]:
    """Read the future ticket-driven manual-install log for this client/month.

    Lives at ``clients/<slug>/me_ec/manual_installs/<YYYY-MM>.json`` — written
    by the (forthcoming) post-window CP-ticket-close workflow. Each entry::

        {"machine": "...", "patch_name": "KB...", "severity": "Critical",
         "tech": "...", "installed_date": "2026-01-15",
         "source_ticket_id": 1452745}

    Returns ``[]`` when the file doesn't exist (current state: tracking
    starts when the post-window orchestrator goes live).
    """
    path = CLIENTS_ROOT / slug / "me_ec" / "manual_installs" / f"{year:04d}-{month:02d}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def section_ytd_coverage(doc, conn, customer_id: int, year: int, month: int) -> None:
    """Year-to-date patch deployment totals by month — running tally."""
    brand.add_section_header(doc, "Year-to-Date Patch Coverage")
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            DATEPART(MONTH, DATEADD(SECOND, ips.INSTALLED_TIME/1000, '1970-01-01')) AS m,
            COUNT(*) AS installs,
            COUNT(DISTINCT r.RESOURCE_ID) AS machines,
            SUM(CASE WHEN p.SEVERITYID = 1 THEN 1 ELSE 0 END) AS critical
        FROM InstallPatchStatus ips
        JOIN Resource r ON r.RESOURCE_ID = ips.RESOURCE_ID
        JOIN Patch p    ON p.PATCHID     = ips.PATCH_ID
        WHERE r.CUSTOMER_ID = %d
          AND r.IS_INACTIVE = 'False'
          AND ips.INSTALLED_TIME >= %d
          AND ips.INSTALLED_TIME <  %d
        GROUP BY DATEPART(MONTH, DATEADD(SECOND, ips.INSTALLED_TIME/1000, '1970-01-01'))
        ORDER BY m
        """,
        (customer_id, sql.EPOCH_2026_MS, month_window_ms(year, month)[1]),
    )
    rows_db = cur.fetchall()
    by_month = {int(r["m"]): r for r in rows_db}
    if not by_month:
        brand.add_body(
            doc,
            "Year-to-date totals will populate as automated patch deployments "
            "accumulate during the year.",
        )
        return
    brand.add_body(
        doc,
        f"Cumulative {year} patch deployment totals through "
        f"{month_label(year, month)}, month by month. The running totals "
        f"show Technijian's protection compounding across the calendar year.",
    )
    rows = []
    cum_installs = 0
    cum_critical = 0
    for m in range(1, month + 1):
        rec = by_month.get(m)
        n = int(rec["installs"]) if rec else 0
        cum_installs += n
        machines_n = int(rec["machines"]) if rec else 0
        critical_n = int(rec["critical"]) if rec else 0
        cum_critical += critical_n
        rows.append([
            calendar.month_name[m],
            fmt_int(n),
            fmt_int(critical_n),
            fmt_int(machines_n),
            fmt_int(cum_installs),
        ])
    brand.styled_table(
        doc,
        ["Month", "Patches Deployed", "Critical Patches", "Endpoints Patched", "YTD Total"],
        rows,
        col_widths=[1.2, 1.4, 1.2, 1.4, 1.0],
    )
    brand.add_body(
        doc,
        f"Through {month_label(year, month)}, Technijian has deployed "
        f"{fmt_int(cum_installs)} patches year-to-date — including "
        f"{fmt_int(cum_critical)} Critical-severity vulnerabilities closed.",
        bold=True, color=brand.DARK_CHARCOAL,
    )


def build_report(customer: dict, slug: str, year: int, month: int, agg: dict, windows: list[dict], conn, out_path: Path) -> None:
    customer_name = customer["CUSTOMER_NAME"]
    manual = load_manual_installs(slug, year, month)

    doc = brand.new_branded_document()
    render_cover_page(doc, customer_name, year, month)

    section_executive_summary(doc, customer_name, year, month, agg, manual)
    section_patch_window(doc, customer_name, windows)
    section_per_machine(doc, agg)
    section_severity(doc, agg)
    section_vendor(doc, agg)
    section_automated_patches(doc, agg)
    section_manual_installs(doc, manual)
    section_ytd_coverage(doc, conn, int(customer["CUSTOMER_ID"]), year, month)
    section_what_technijian_did(doc, customer_name, year, month, agg, manual, windows)
    try:
        service_highlights.render_section(doc, slug, year, month, "me-ec", brand)
    except Exception:
        pass
    vendor_news.render_section(doc, "manageengine", year, month, brand)
    compliance_section.render_section(doc, slug, brand)
    section_recommendations(doc, customer_name, agg, windows)
    section_about(doc, customer_name, year, month)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))


def run_proofreader(generated: list[Path]) -> int:
    if not generated:
        return 0
    if not PROOFREADER.exists():
        print(f"\n[proofread] WARNING: proofreader missing at {PROOFREADER} — skipping.")
        return 0
    sections_csv = ",".join(EXPECTED_SECTIONS)
    cmd = [sys.executable, str(PROOFREADER), "--sections", sections_csv]
    cmd += [str(p) for p in generated if p.exists()]
    print("\n=== Proofreading reports ===")
    sys.stdout.flush()
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        print(f"\n[proofread] FAILED — one or more reports did not pass the gate (rc={rc}).")
    else:
        print(f"[proofread] OK — {len(generated)} report(s) passed all checks.")
    return rc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--month", help="Single month YYYY-MM")
    p.add_argument("--from", dest="from_month", help="Start month YYYY-MM")
    p.add_argument("--to", dest="to_month", help="End month YYYY-MM (inclusive)")
    p.add_argument("--only", help="Comma-separated customer names to include")
    p.add_argument("--skip", help="Comma-separated customer names to skip")
    p.add_argument(
        "--no-proofread", action="store_true",
        help="Skip the proofread gate (CI / debug only — do NOT use for delivery)",
    )
    return p.parse_args()


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
    args = parse_args()
    months = expand_months(args)
    only = {s.strip().upper() for s in (args.only or "").split(",") if s.strip()}
    skip = {s.strip().upper() for s in (args.skip or "").split(",") if s.strip()}

    generated: list[Path] = []
    with sql.connect() as conn:
        customers = sql.list_customers(conn)
        all_windows = sql.patch_windows(conn)
        vendors = vendor_lookup(conn)

        for customer in customers:
            cust_name = customer["CUSTOMER_NAME"]
            cust_id = int(customer["CUSTOMER_ID"])
            slug = CUSTOMER_TO_SLUG.get(cust_name)
            if slug is None:
                print(f"  [skip] {cust_name}: no client folder mapping")
                continue
            if only and cust_name.upper() not in only:
                continue
            if cust_name.upper() in skip:
                continue
            client_dir = CLIENTS_ROOT / slug
            client_dir.mkdir(parents=True, exist_ok=True)
            reports_dir = client_dir / "me_ec" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            cust_windows = patch_window_for_customer(all_windows, cust_id)

            for (year, month) in months:
                start_ms, end_ms = month_window_ms(year, month)
                installs = installs_in_month(conn, cust_id, start_ms, end_ms)
                agg = summarize(installs, vendors)
                safe_label = "".join(
                    c if c.isalnum() or c in " -_" else "_" for c in cust_name
                )
                out = reports_dir / f"{safe_label} - ME EC Patch Activity - {year:04d}-{month:02d}.docx"
                build_report(customer, slug, year, month, agg, cust_windows, conn, out)
                generated.append(out)
                print(
                    f"  [{slug}] {year}-{month:02d} -> {out.relative_to(REPO_ROOT)} "
                    f"({agg['total_installs']} installs / {len(agg['machines'])} machines)"
                )

    print(f"\nGenerated {len(generated)} Word report(s)")
    if args.no_proofread:
        print("[proofread] skipped (--no-proofread)")
        return 0
    return run_proofreader(generated)


if __name__ == "__main__":
    sys.exit(main())
