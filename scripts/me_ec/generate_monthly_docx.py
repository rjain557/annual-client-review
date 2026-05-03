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

PROOFREADER = SHARED / "proofread_docx.py"
CLIENTS_ROOT = REPO_ROOT / "clients"

EXPECTED_SECTIONS = [
    "Executive Summary",
    "Patch Window",
    "Per-Machine Summary",
    "Severity Breakdown",
    "Vendor Breakdown",
    "Patches Installed",
    "Failed Installs",
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


def section_executive_summary(doc, customer_name: str, year: int, month: int, agg: dict) -> None:
    brand.add_section_header(doc, "Executive Summary")
    machines = len(agg["machines"])
    succeeded = agg["succeeded"]
    errored = agg["errored"]
    total = agg["total_installs"]

    brand.add_metric_card_row(doc, [
        (fmt_int(total),     "Patches installed",  brand.CORE_BLUE),
        (fmt_int(succeeded), "Succeeded",          brand.GREEN),
        (fmt_int(errored),   "Errored",            brand.RED if errored else brand.BRAND_GREY),
        (fmt_int(machines),  "Machines patched",   brand.TEAL),
    ])

    if total == 0:
        brand.add_callout_box(
            doc,
            f"No patches were installed for {customer_name} during "
            f"{month_label(year, month)}. This may be expected (small fleet, "
            f"no relevant patches released this month, or the patch deployment "
            f"task was suspended). See the Patch Window section below for the "
            f"client's configured schedule.",
        )
    else:
        success_rate = (succeeded / total * 100) if total else 0
        brand.add_body(
            doc,
            f"During {month_label(year, month)}, Technijian's automated patch "
            f"deployment installed {fmt_int(total)} patches across "
            f"{fmt_int(machines)} {customer_name} endpoints. The deployment "
            f"success rate was {success_rate:.1f}% "
            f"({fmt_int(succeeded)} succeeded / {fmt_int(errored)} errored). "
            f"Errored patches remain in the missing-patch queue and will "
            f"automatically retry during the next scheduled patch window.",
        )


def section_patch_window(doc, customer_name: str, windows: list[dict]) -> None:
    brand.add_section_header(doc, "Patch Window")
    if not windows:
        brand.add_callout_box(
            doc,
            f"{customer_name} has no Automated Patch Deployment task "
            f"configured in Endpoint Central. Patches are NOT being deployed "
            f"on a schedule for this client. Recommend opening a CP ticket "
            f"with India tech support to configure an APD task aligned with "
            f"the client's preferred maintenance window.",
            accent_hex=brand.RED_HEX,
            bg_hex="FCE8EA",
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


def section_patches_installed(doc, agg: dict, top_n: int = 25) -> None:
    brand.add_section_header(doc, "Patches Installed")
    counts = agg["patch_counts"]
    if not counts:
        brand.add_body(doc, "No patches installed this month.")
        return
    sorted_patches = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top = sorted_patches[:top_n]
    if len(sorted_patches) > top_n:
        brand.add_body(
            doc,
            f"Showing the top {top_n} of {fmt_int(len(sorted_patches))} unique "
            f"patches installed this month, ranked by number of endpoints "
            f"that received the patch.",
        )
    rows = [[name, fmt_int(n)] for name, n in top]
    brand.styled_table(
        doc,
        ["Patch", "Endpoints"],
        rows,
        col_widths=[5.0, 1.5],
    )


def section_failed(doc, agg: dict) -> None:
    brand.add_section_header(doc, "Failed Installs")
    failed = agg["failed"]
    if not failed:
        brand.add_callout_box(
            doc,
            "No patch installs failed this month. All deployments completed "
            "without an error code.",
            accent_hex=brand.GREEN_HEX,
            bg_hex="E9F7EE",
        )
        return
    brand.add_body(
        doc,
        f"{fmt_int(len(failed))} patch deployment(s) failed during this "
        f"month's windows. Failed patches stay in the missing-patch queue "
        f"and Endpoint Central will automatically retry them during the "
        f"next scheduled window. Persistent failures (same KB failing "
        f"three or more windows in a row) should be escalated to India "
        f"tech support for manual installation.",
    )
    rows = []
    for r in failed[:50]:
        rows.append([
            r.get("resource_name") or "",
            r.get("PATCHNAME") or "",
            SEVERITY.get(int(r.get("SEVERITYID") or 0), "Unspecified"),
            str(r.get("ERROR_CODE") or ""),
            fmt_ts(r.get("INSTALLED_TIME")),
        ])
    if len(failed) > 50:
        brand.add_body(
            doc,
            f"Showing the first 50 of {fmt_int(len(failed))} failed installs "
            f"(see the InstallPatchStatus SQL view for the full list).",
        )
    brand.styled_table(
        doc,
        ["Machine", "Patch", "Severity", "Error", "Time (UTC)"],
        rows,
        col_widths=[1.4, 2.4, 0.8, 0.6, 1.3],
        status_col=2,
    )


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
        "different reporting cadence, contact your Technijian account "
        "manager or open a ticket via the Client Portal.",
    )


# ---------------------------------------------------------------------------
# Build orchestration
# ---------------------------------------------------------------------------

def build_report(customer: dict, year: int, month: int, agg: dict, windows: list[dict], out_path: Path) -> None:
    customer_name = customer["CUSTOMER_NAME"]

    doc = brand.new_branded_document()
    render_cover_page(doc, customer_name, year, month)

    section_executive_summary(doc, customer_name, year, month, agg)
    section_patch_window(doc, customer_name, windows)
    section_per_machine(doc, agg)
    section_severity(doc, agg)
    section_vendor(doc, agg)
    section_patches_installed(doc, agg)
    section_failed(doc, agg)
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
                build_report(customer, year, month, agg, cust_windows, out)
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
