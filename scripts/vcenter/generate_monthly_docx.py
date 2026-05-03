"""Generate branded monthly vCenter infrastructure report per client.

Reads from ``clients/<slug>/vcenter/<YEAR>/{summary,vms,datastores,alerts,luns}.json``
and writes one Word doc per (client, month) at::

    clients/<slug>/vcenter/reports/<NAME> - vCenter Monthly Infrastructure - <YYYY-MM>.docx

vCenter snapshots are point-in-time, so every month's report references
the most recent snapshot under <YEAR>/. The report frames the state of
the client's virtualization fleet at the time of generation.

Sections:
  1. Executive Summary  - KPI cards (VMs, powered on, hosts, datastores,
                          active alarms)
  2. Virtual Machine Inventory  - per-VM table (name, vCPU, RAM, OS, state)
  3. Storage Capacity  - per-datastore used/free/percent
  4. What Technijian Did For You
  5. Recommendations
  6. About This Report

Auto-runs the proofread gate.

Usage:
    python generate_monthly_docx.py --month 2026-03
    python generate_monthly_docx.py --from 2026-01 --to 2026-04
    python generate_monthly_docx.py --month 2026-04 --only CCC,CSS
"""

from __future__ import annotations

import argparse
import calendar
import json
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
    "Virtual Machine Inventory",
    "Storage Capacity",
    "VM Power & Right-Sizing",
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


def find_snapshot_year_dir(client_dir: Path, target_year: int) -> Path | None:
    vc_root = client_dir / "vcenter"
    if not vc_root.exists():
        return None
    candidate = vc_root / str(target_year)
    if candidate.exists():
        return candidate
    # Fall back to the most recent year folder available
    years = sorted([p for p in vc_root.iterdir() if p.is_dir() and p.name.isdigit()])
    return years[-1] if years else None


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def render_cover(doc, customer: str, year: int, month: int):
    brand.render_cover(
        doc,
        title="Virtualization Infrastructure Report",
        subtitle=f"{customer} — {month_label(year, month)}",
        date_text=f"Generated {datetime.now().strftime('%Y-%m-%d')}",
        footer_note="Confidential — prepared by Technijian for the named client only.",
    )
    brand.add_page_break(doc)


def section_executive_summary(doc, customer: str, year: int, month: int, summary: dict, alerts: list):
    brand.add_section_header(doc, "Executive Summary")
    vm_count = int(summary.get("vm_count") or 0)
    powered_on = int(summary.get("vm_powered_on") or 0)
    ds_count = int(summary.get("datastore_count") or 0)
    alarm_count = len(alerts) if isinstance(alerts, list) else int(summary.get("active_alarms") or 0)

    brand.add_metric_card_row(doc, [
        (fmt_int(vm_count),    "Virtual Machines",  brand.CORE_BLUE),
        (fmt_int(powered_on),  "Powered On",        brand.GREEN),
        (fmt_int(ds_count),    "Datastores",        brand.TEAL),
        (fmt_int(alarm_count), "Active Alarms",     brand.CORE_ORANGE if alarm_count else brand.GREEN),
    ])

    if vm_count == 0:
        brand.add_callout_box(
            doc,
            f"No virtual machines were under Technijian-managed vCenter for "
            f"{customer} during {month_label(year, month)}. Snapshot taken "
            f"{summary.get('pulled_at') or 'recently'}.",
        )
    else:
        brand.add_body(
            doc,
            f"Technijian's vCenter monitoring tracked {fmt_int(vm_count)} "
            f"virtual machine(s) and {fmt_int(ds_count)} datastore(s) for "
            f"{customer} during {month_label(year, month)}, with "
            f"{fmt_int(powered_on)} VM(s) running normally at the snapshot "
            f"time. Capacity, configuration, and alarm posture were all under "
            f"continuous monitoring.",
        )


def section_vm_inventory(doc, vms: list[dict]):
    brand.add_section_header(doc, "Virtual Machine Inventory")
    if not vms:
        brand.add_body(doc, "No virtual machines reported in this snapshot.")
        return
    brand.add_body(
        doc,
        f"Each row below is a VM Technijian manages on your behalf. "
        f"Configuration shown is the live state at snapshot time.",
    )
    rows = []
    for vm in sorted(vms, key=lambda v: (v.get("name") or "").lower()):
        name = (vm.get("name") or "")[:40]
        cpus = vm.get("cpu_count") or vm.get("num_cpu") or vm.get("vcpu") or "—"
        mem_mb = vm.get("memory_mb") or vm.get("memory_size_MB") or vm.get("memory") or 0
        try:
            ram_gb = f"{int(mem_mb)/1024:.1f}" if int(mem_mb) >= 1024 else f"{int(mem_mb)} MB"
        except Exception:
            ram_gb = str(mem_mb)
        os_name = (vm.get("guest_os") or vm.get("os") or vm.get("guestFullName") or "—")[:40]
        state = vm.get("power_state") or vm.get("powerState") or "—"
        if state and state.startswith("POWERED_"):
            state = state.replace("POWERED_", "").title()
        rows.append([name, str(cpus), str(ram_gb), os_name, state])
    brand.styled_table(
        doc,
        ["VM Name", "vCPU", "RAM (GB)", "Operating System", "State"],
        rows[:80],
        col_widths=[1.8, 0.6, 0.9, 2.4, 0.8],
        status_col=4,
    )
    if len(rows) > 80:
        brand.add_body(
            doc,
            f"Showing 80 of {fmt_int(len(rows))} VMs. Full list available on "
            f"request — email support@technijian.com.",
        )


def section_storage(doc, datastores: list[dict]):
    brand.add_section_header(doc, "Storage Capacity")
    if not datastores:
        brand.add_body(doc, "No datastores reported in this snapshot.")
        return
    rows = []
    for ds in datastores:
        name = (ds.get("name") or "")[:40]
        cap_gb = ds.get("capacity_gb") or (
            int(ds.get("capacity") or 0) / (1024**3) if ds.get("capacity") else 0
        )
        free_gb = ds.get("free_gb") or (
            int(ds.get("free_space") or 0) / (1024**3) if ds.get("free_space") else 0
        )
        used_gb = (cap_gb or 0) - (free_gb or 0)
        used_pct = (used_gb / cap_gb * 100) if cap_gb else 0
        ds_type = ds.get("type") or "—"
        status = "Healthy"
        if used_pct >= 90:
            status = "Critical"
        elif used_pct >= 80:
            status = "High"
        elif used_pct >= 70:
            status = "Medium"
        rows.append([
            name,
            f"{cap_gb:,.0f}" if cap_gb else "—",
            f"{free_gb:,.0f}" if free_gb else "—",
            f"{used_pct:.1f}%",
            ds_type,
            status,
        ])
    brand.styled_table(
        doc,
        ["Datastore", "Capacity (GB)", "Free (GB)", "Used %", "Type", "Status"],
        rows,
        col_widths=[1.7, 1.0, 0.9, 0.8, 0.8, 1.0],
        status_col=5,
    )


def section_vm_rightsizing(doc, vms: list[dict]):
    """Identify VMs that may be over-provisioned or candidates for
    decommission. Findings are advisory — they help the client see
    cost-saving opportunities Technijian's monitoring surfaces."""
    brand.add_section_header(doc, "VM Power & Right-Sizing")
    if not vms:
        brand.add_body(doc, "No virtual machines reported in this snapshot.")
        return

    powered_off = []
    for vm in vms:
        state = (vm.get("power_state") or vm.get("powerState") or "").upper()
        if "OFF" in state:
            powered_off.append(vm)

    # Over-allocated heuristic: VMs with >16 vCPU or >64GB RAM that are still
    # powered on. Tunable per environment — these are conservative starting
    # thresholds intended to flag candidates for review, not to declare
    # them wasteful.
    oversized = []
    for vm in vms:
        try:
            cpus = int(vm.get("cpu_count") or vm.get("num_cpu") or vm.get("vcpu") or 0)
            mem_mb = int(vm.get("memory_mb") or vm.get("memory_size_MB") or vm.get("memory") or 0)
        except Exception:
            continue
        if cpus > 16 or mem_mb > 64 * 1024:
            oversized.append((vm, cpus, mem_mb))

    if not powered_off and not oversized:
        brand.add_callout_box(
            doc,
            "All VMs in this snapshot are powered on and within typical "
            "right-sizing thresholds (≤16 vCPU, ≤64 GB RAM). The fleet is "
            "running lean.",
            accent_hex=brand.GREEN_HEX,
            bg_hex="E9F7EE",
        )
        return

    brand.add_body(
        doc,
        "Technijian flags VMs that look like decommission or right-sizing "
        "candidates. Review with your Technijian contact before changing "
        "any of these — they're starting points, not directives.",
    )

    if powered_off:
        brand.add_body(
            doc,
            "Powered-off VMs (potential decommission candidates)",
            bold=True, size=12, color=brand.DARK_CHARCOAL,
        )
        rows = []
        for vm in powered_off[:30]:
            rows.append([
                (vm.get("name") or "")[:40],
                (vm.get("guest_os") or vm.get("os") or vm.get("guestFullName") or "—")[:35],
                vm.get("cpu_count") or vm.get("num_cpu") or "—",
                f"{int(vm.get('memory_mb') or 0)/1024:.0f} GB" if vm.get("memory_mb") else "—",
            ])
        brand.styled_table(
            doc,
            ["VM Name", "OS", "vCPU", "RAM"],
            rows,
            col_widths=[2.2, 2.2, 0.8, 1.2],
        )

    if oversized:
        brand.add_body(
            doc,
            "Large allocations (review for right-sizing)",
            bold=True, size=12, color=brand.DARK_CHARCOAL,
        )
        rows = []
        for vm, cpus, mem_mb in oversized[:20]:
            rows.append([
                (vm.get("name") or "")[:40],
                str(cpus),
                f"{mem_mb/1024:.0f} GB",
                "Review",
            ])
        brand.styled_table(
            doc,
            ["VM Name", "vCPU", "RAM", "Action"],
            rows,
            col_widths=[2.4, 0.8, 1.2, 2.0],
            status_col=3,
        )


def section_what_technijian_did(doc, customer: str, year: int, month: int, summary: dict, vms: list, alerts: list):
    brand.add_section_header(doc, "What Technijian Did For You")
    vm_count = int(summary.get("vm_count") or 0)
    powered_on = int(summary.get("vm_powered_on") or 0)
    bullets = []
    if vm_count:
        bullets.append((
            f"Monitored {fmt_int(vm_count)} virtual machines 24×7 ",
            f"on Technijian's managed VMware vCenter platform during "
            f"{month_label(year, month)}, with {fmt_int(powered_on)} VM(s) "
            f"actively running.",
        ))
    bullets.append((
        "Captured configuration baselines: ",
        "VM specifications (vCPU, RAM, disk, OS), datastore capacity, "
        "host configuration, and active alarms were all snapshotted for "
        "compliance documentation and change tracking.",
    ))
    if not alerts:
        bullets.append((
            "No active vCenter alarms required attention this month: ",
            "the virtualization fleet ran cleanly with no triggered host, "
            "datastore, or VM alarms at snapshot time.",
        ))
    else:
        bullets.append((
            f"Reviewed {fmt_int(len(alerts))} active alarm(s) ",
            "and triaged each to determine whether action was required, "
            "scheduled, or could be cleared as expected behavior.",
        ))
    bullets.append((
        "Provided capacity planning visibility: ",
        "datastore utilization is tracked monthly so capacity expansions "
        "are coordinated well before any storage hits a threshold.",
    ))
    for prefix, text in bullets:
        brand.add_bullet(doc, text, bold_prefix=prefix)


def section_recommendations(doc, datastores: list[dict], alerts: list):
    brand.add_section_header(doc, "Recommendations")
    recs = []
    # Datastores trending high
    high_used = []
    for ds in datastores or []:
        cap_gb = ds.get("capacity_gb") or 0
        free_gb = ds.get("free_gb") or 0
        if cap_gb and free_gb is not None:
            used_pct = ((cap_gb - free_gb) / cap_gb * 100) if cap_gb else 0
            if used_pct >= 80:
                high_used.append((ds.get("name") or "?", used_pct))
    if high_used:
        names = ", ".join(f"{n} ({p:.0f}%)" for n, p in high_used[:5])
        recs.append((
            "Plan capacity expansion: ",
            f"the following datastore(s) are above 80% utilization and "
            f"would benefit from a capacity review in the next 60 days: "
            f"{names}.",
        ))
    if alerts:
        recs.append((
            "Address open alarms: ",
            f"{fmt_int(len(alerts))} vCenter alarm(s) are active. Email "
            f"support@technijian.com if you'd like a walkthrough of each "
            f"and the planned remediation.",
        ))
    if not recs:
        recs.append((
            "Stay the course: ",
            "your virtualization fleet is healthy — capacity has comfortable "
            "runway, no alarms are active, and configuration is documented.",
        ))
    for prefix, text in recs:
        brand.add_bullet(doc, text, bold_prefix=prefix)


def section_about(doc, customer: str, year: int, month: int, summary: dict):
    brand.add_section_header(doc, "About This Report")
    brand.add_body(
        doc,
        "This report is generated automatically from VMware vCenter via the "
        "vSphere REST API. Configuration shown is a point-in-time snapshot — "
        "the most recent vCenter pull for the calendar month above.",
    )
    brand.add_body(
        doc,
        f"Snapshot taken: {summary.get('pulled_at') or 'unknown'} from "
        f"vCenter {summary.get('vcenter') or 'unknown'}. Report generated "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')} for client "
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
    vms = load_json(snapshot_dir / "vms.json", [])
    if isinstance(vms, dict):
        vms = vms.get("vms") or vms.get("data") or []
    datastores = load_json(snapshot_dir / "datastores.json", [])
    if isinstance(datastores, dict):
        datastores = datastores.get("datastores") or datastores.get("data") or []
    alerts = load_json(snapshot_dir / "alerts.json", [])
    if isinstance(alerts, dict):
        alerts = alerts.get("alerts") or alerts.get("active_alarms") or []

    doc = brand.new_branded_document()
    render_cover(doc, customer, year, month)
    section_executive_summary(doc, customer, year, month, summary, alerts)
    section_vm_inventory(doc, vms)
    section_storage(doc, datastores)
    section_vm_rightsizing(doc, vms)
    section_what_technijian_did(doc, customer, year, month, summary, vms, alerts)
    try:
        service_highlights.render_section(doc, client_dir.name, year, month, "vcenter", brand)
    except Exception:
        pass
    vendor_news.render_section(doc, "vmware", year, month, brand)
    section_recommendations(doc, datastores, alerts)
    section_about(doc, customer, year, month, summary)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))


def run_proofreader(generated: list[Path]) -> int:
    if not generated:
        return 0
    if not PROOFREADER.exists():
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
            snapshot = find_snapshot_year_dir(client_dir, year)
            if snapshot is None:
                continue
            customer = slug.upper()
            safe_label = "".join(c if c.isalnum() or c in " -_" else "_" for c in customer)
            out = client_dir / "vcenter" / "reports" / f"{safe_label} - vCenter Monthly Infrastructure - {year:04d}-{month:02d}.docx"
            build_report(client_dir, customer, year, month, snapshot, out)
            generated.append(out)
            print(f"  [{slug}] {year}-{month:02d} -> {out.relative_to(REPO_ROOT)}")

    print(f"\nGenerated {len(generated)} Word report(s)")
    return run_proofreader(generated)


if __name__ == "__main__":
    sys.exit(main())
