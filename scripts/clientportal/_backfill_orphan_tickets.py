"""
One-shot — backfill the 11 CP tickets opened earlier today by other
pipelines (before they migrate to the tracked wrapper) into
`state/cp_tickets.json` so the central monitor covers them
immediately.

Run once:
    python scripts/clientportal/_backfill_orphan_tickets.py

Idempotent on issue_key — re-running overwrites the entry but keeps
`history` accumulated.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ticket_state  # type: ignore

CREATED_AT = "2026-05-02T20:01:00+00:00"  # approximate filing time

ORPHANS = [
    # ---------- MailStore (3 tickets) ----------
    {
        "issue_key": "mailstore:smtp-failures:Technijian",
        "ticket_id": 1452674,
        "client_code": "Technijian",
        "source_skill": "mailstore-spe-pull",
        "title": "MailStore: Technijian SMTP archive failures (route_alerts.py)",
        "priority_id": 1255,  # Same Day
        "metadata": {"orphan_backfill": True, "source_file": "technijian/mailstore-pull/scripts/route_alerts.py"},
    },
    {
        "issue_key": "mailstore:index-rebuild:ORX",
        "ticket_id": 1452675,
        "client_code": "ORX",
        "source_skill": "mailstore-spe-pull",
        "title": "MailStore: ORX (orthoxpress) search-index rebuild outstanding",
        "priority_id": 1256,  # Next Day
        "metadata": {"orphan_backfill": True, "instance": "orthoxpress"},
    },
    {
        "issue_key": "mailstore:archive-jobs-failing:ICML",
        "ticket_id": 1452676,
        "client_code": "ICML",
        "source_skill": "mailstore-spe-pull",
        "title": "MailStore: ICML archive jobs FAILING — both ICM instances 100% failure for 2026",
        "priority_id": 1255,  # Same Day
        "metadata": {"orphan_backfill": True, "instances": ["icmlending", "icm-realestate"]},
    },
    # ---------- Veeam VBR (8 tickets, #1452728-1452735) ----------
    {
        "issue_key": "veeam-vbr:repo-capacity:bkp_VAF",
        "ticket_id": 1452728,
        "client_code": "VAF",
        "source_skill": "veeam-vbr",
        "title": "URGENT: bkp_VAF backup repository at 97.5% capacity (6-day runway to outage)",
        "priority_id": 1253,  # Critical
        "metadata": {"repo": "bkp_VAF", "used_pct": 97.5, "free_gb": 151.8, "cap_tb": 6.0, "runway_days": 6},
    },
    {
        "issue_key": "veeam-vbr:imt-threshold-check:Bkp_VAF_IMT",
        "ticket_id": 1452729,
        "client_code": "VAF",
        "source_skill": "veeam-vbr",
        "title": "VAF: Bkp_VAF_IMT immediate-mode repository failing threshold-check (15+ in last week)",
        "priority_id": 1255,  # Same Day
        "metadata": {"repo": "Bkp_VAF_IMT", "failure_count": 15},
    },
    {
        "issue_key": "veeam-vbr:rpc-timeouts:VAF",
        "ticket_id": 1452730,
        "client_code": "VAF",
        "source_skill": "veeam-vbr",
        "title": "VAF: 56x VBR RPC timeouts ('Time is out / Failed to invoke rpc command') on production VMs",
        "priority_id": 1255,
        "metadata": {"rpc_timeout_count": 56, "vms": ["VAF-DC-FS-01", "VAF-DC-SQL-01", "VAF-DC-AD-01"]},
    },
    {
        "issue_key": "veeam-vbr:repo-capacity:bkp_ORX",
        "ticket_id": 1452731,
        "client_code": "ORX",
        "source_skill": "veeam-vbr",
        "title": "URGENT: bkp_ORX backup repository at 80.8% capacity (3-day runway to outage)",
        "priority_id": 1253,  # Critical
        "metadata": {"repo": "bkp_ORX", "used_pct": 80.8, "free_tb": 3.5, "cap_tb": 18.0, "runway_days": 3},
    },
    {
        "issue_key": "veeam-vbr:imt-threshold-check:Bkp_ORX_IMT",
        "ticket_id": 1452732,
        "client_code": "ORX",
        "source_skill": "veeam-vbr",
        "title": "ORX: Bkp_ORX_IMT repository threshold-check failures (18+ in last week)",
        "priority_id": 1255,
        "metadata": {"repo": "Bkp_ORX_IMT", "failure_count": 18},
    },
    {
        "issue_key": "veeam-vbr:rpc-timeouts:ORX",
        "ticket_id": 1452733,
        "client_code": "ORX",
        "source_skill": "veeam-vbr",
        "title": "ORX: 48x VBR RPC timeouts ('Time is out') on TS/VDI/CB VMs",
        "priority_id": 1255,
        "metadata": {"rpc_timeout_count": 48, "vms": ["ORX-DC-CB-01", "ORX-DC-VDI-GI", "ORX-DC-TS-03"]},
    },
    {
        "issue_key": "veeam-vbr:vsphere-tag-missing:MAX",
        "ticket_id": 1452734,
        "client_code": "MAX",
        "source_skill": "veeam-vbr",
        "title": "MAX: vSphere tag 'MAX' missing - 18x 'Tag MAX is unavailable' in 2026, blocking VM enumeration",
        "priority_id": 1255,
        "metadata": {"vsphere_tag": "MAX", "warning_count": 18},
    },
    {
        "issue_key": "veeam-vbr:imt-and-shared-nfs:MAX",
        "ticket_id": 1452735,
        "client_code": "MAX",
        "source_skill": "veeam-vbr",
        "title": "MAX: Bkp_MAX_IMT threshold-check failure + bkp_TECH NFS share intermittently unavailable",
        "priority_id": 1255,
        "metadata": {"imt_failures": 12, "nfs_unavail_count": 5, "shared_with": "bkp_TECH"},
    },
]


for t in ORPHANS:
    entry = ticket_state.backfill(
        issue_key=t["issue_key"],
        ticket_id=t["ticket_id"],
        client_code=t["client_code"],
        source_skill=t["source_skill"],
        title=t["title"],
        priority_id=t["priority_id"],
        assign_to_dir_id=205,
        created_at=CREATED_AT,
        metadata=t["metadata"],
    )
    print(f"Backfilled  #{entry['ticket_id']:>8}  {entry['client_code']:<11}  {t['source_skill']:<22}  {t['issue_key']}")

print(f"\nState file: {ticket_state.STATE_FILE}")
print(f"Open count: {len(ticket_state.list_open())}")
