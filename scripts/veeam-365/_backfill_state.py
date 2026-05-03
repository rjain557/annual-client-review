"""One-shot: backfill the 4 Veeam 365 tickets filed earlier today into
state/cp_tickets.json so the monitor pipeline can track them."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clientportal"))
import ticket_state  # type: ignore

CREATED_AT = "2026-05-02T20:01:00+00:00"   # actual filing timestamp from this session

TICKETS = [
    {
        "issue_key": "veeam-365:repo-capacity:AFFG-O365",
        "ticket_id": 1452721,
        "client_code": "AFFG",
        "title": "Veeam 365 backup repo AFFG-O365 at 91.7% full — only 80 GB free of 1 TB",
        "priority_id": 1255,
        "metadata": {"repo_name": "AFFG-O365", "used_pct": 91.7, "free_gb": 80, "cap_tb": 1.0},
    },
    {
        "issue_key": "veeam-365:repo-capacity:TECH-O365",
        "ticket_id": 1452722,
        "client_code": "Technijian",
        "title": "Veeam 365 backup repo TECH-O365 at 86% full — 0.98 TB free of 7 TB",
        "priority_id": 1256,
        "metadata": {"repo_name": "TECH-O365", "used_pct": 86.0, "free_tb": 0.98, "cap_tb": 7.0},
    },
    {
        "issue_key": "veeam-365:repo-capacity-and-warning:ALG-O365",
        "ticket_id": 1452723,
        "client_code": "ALG",
        "title": "Veeam 365 ALG-O365 — repo at 85.6% full AND last job run returned Warning",
        "priority_id": 1255,
        "metadata": {"repo_name": "ALG-O365", "used_pct": 85.6, "job_status": "Warning"},
    },
    {
        "issue_key": "veeam-365:migration-cleanup:ORX",
        "ticket_id": 1452724,
        "client_code": "ORX",
        "title": "Veeam 365 ORX — verify migration to new repo + retire stale ORX-O365 repo (capacity anomaly)",
        "priority_id": 1256,
        "metadata": {"old_repo": "ORX-O365", "new_repo": "ORX_365_New", "anomaly": "used > capacity"},
    },
]

for t in TICKETS:
    entry = ticket_state.backfill(
        issue_key=t["issue_key"],
        ticket_id=t["ticket_id"],
        client_code=t["client_code"],
        source_skill="veeam-365-pull",
        title=t["title"],
        priority_id=t["priority_id"],
        assign_to_dir_id=205,
        created_at=CREATED_AT,
        metadata=t["metadata"],
    )
    print(f"Backfilled  #{entry['ticket_id']:>8}  {entry['client_code']:<10}  {t['issue_key']}")

print(f"\nState file: {ticket_state.STATE_FILE}")
print(f"Open count: {len(ticket_state.list_open())}")
