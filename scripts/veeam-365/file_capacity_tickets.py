"""
File Client Portal tickets for Veeam 365 issues identified in the
2026-05-02 pull. One ticket per issue, assigned to CHD : TS1 (India tech
support, DirID=205). Each ticket carries full step-by-step remediation.

Run:  python file_capacity_tickets.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "clientportal"))
import cp_tickets  # type: ignore

# CHD : TS1 = India tech support (default assignee for automated tickets)
ASSIGN_TO_CHD_TS1 = 205

# Veeam server identifiers (from keys/veeam-365.md and snapshot data)
VB365_HOST = "10.7.9.227"
VB365_NAME = "TE-DC-BK-365-01"

PRIORITY_SAME_DAY = 1255
PRIORITY_NEXT_DAY = 1256

SOURCE_SKILL = "veeam-365-pull"

TICKETS = [
    # ---------- 1. AFFG-O365 ----------
    {
        "code": "AFFG",
        "issue_key": "veeam-365:repo-capacity:AFFG-O365",
        "priority": PRIORITY_SAME_DAY,
        "metadata": {"repo_name": "AFFG-O365", "used_pct": 91.7, "free_gb": 80, "cap_tb": 1.0},
        "title": "Veeam 365 backup repo AFFG-O365 at 91.7% full — only 80 GB free of 1 TB",
        "description": """\
Issue (auto-detected from Veeam 365 REST pull, 2026-05-02):
The on-prem Veeam Backup for Microsoft 365 repository protecting AFFG's
M365 tenant (NETORGFT9014011.onmicrosoft.com) is at 91.7% capacity.

Repository: AFFG-O365
  Server   : {server} ({host})
  Path     : C:\\O365 Backups\\bkp_AFFG-365
  Used     : 920 GB (0.90 TB)
  Capacity : 1.00 TB
  Free     : 80 GB
  M365 tenant: NETORGFT9014011.onmicrosoft.com (34 users protected)

The backup currently runs every 10 minutes (EntireOrganization job
"AFFG-O365"). At the observed growth rate (~4% / month industry default
until ground-truth trend data is captured) AFFG will exhaust capacity
in approximately 8-10 weeks. The pulled snapshot lives at
clients/_veeam_365/snapshots/2026-05-02.json and the latest monthly
client report is at
clients/affg/veeam-365/reports/AFFG - Veeam 365 Monthly - 2026-05.docx.

Resolution steps (do all of these):

1. RDP into the Veeam Backup for Microsoft 365 server:
     {server} / {host}
     Credentials: see keys/veeam-365.md (Administrator account).

2. Inspect the C:\\O365 Backups\\ volume in File Explorer or with
   Get-PSDrive C — confirm the underlying disk has the same 1 TB cap as
   the repo metadata reports.

3. EXTEND or ADD capacity. Pick whichever applies based on disk layout:
     a. If the C: drive is the limit, attach a new VMDK (recommend at
        least 2 TB to give 12+ months of headroom) and add it as a new
        backup repository in Veeam:
          Backup Infrastructure → Backup Repositories →
          Add Repository → "AFFG-O365-V2" pointing to E:\\O365 Backups\\bkp_AFFG-365-V2
     b. If C: can be expanded, expand the underlying VMDK in vSphere,
        then extend the partition in Disk Management on the VB365 host.
        Confirm in the Veeam console that the repo's capacity field
        updates (Backup Repositories → AFFG-O365 → Properties).

4. If you added a new repo (option a):
     a. Edit the AFFG-O365 backup job:
          Backup → Jobs → AFFG-O365 → Edit → Storage step.
        Switch the destination to AFFG-O365-V2.
     b. Run the job manually once to seed the new repo.
     c. Once the new repo has at least one full backup, mark the old
        repo offline and (after 30 days of stable runs on the new repo)
        decommission it.
     d. The CP report next month will pick up the new repo automatically
        — no code changes required (the puller enumerates from
        /v8/Organizations/{{id}}/usedRepositories).

5. Verify recovery:
     Run:  cd c:/vscode/annual-client-review/annual-client-review-1/scripts/veeam-365
          python pull_full.py --only AFFG
     The console table should now show AFFG with usedSpaceBytes < 50%
     of capacityBytes. Confirm no "Warning" or "Failed" lastStatus on
     the next scheduled run.

6. Reply on this ticket with:
     - Disk action taken (extend vs new repo)
     - New capacity in TB
     - Timestamp of first successful run on the new/extended repo

Reference / context:
- Skill: .claude/skills/veeam-365-pull/SKILL.md
- Keys: keys/veeam-365.md (OneDrive vault)
- Pull script: scripts/veeam-365/pull_full.py
- This ticket auto-filed by file_capacity_tickets.py
""".format(server=VB365_NAME, host=VB365_HOST),
    },
    # ---------- 2. TECH-O365 (Technijian internal) ----------
    {
        "code": "Technijian",
        "issue_key": "veeam-365:repo-capacity:TECH-O365",
        "priority": PRIORITY_NEXT_DAY,
        "metadata": {"repo_name": "TECH-O365", "used_pct": 86.0, "free_tb": 0.98, "cap_tb": 7.0},
        "title": "Veeam 365 backup repo TECH-O365 at 86% full — 0.98 TB free of 7 TB",
        "description": """\
Issue (auto-detected from Veeam 365 REST pull, 2026-05-02):
The Veeam 365 repository protecting Technijian's own M365 tenant
(Technijian365.onmicrosoft.com — 297 users) is at 86% capacity.

Repository: TECH-O365
  Server   : {server} ({host})
  Path     : C:\\O365 Backups\\bkp_TECH-365
  Used     : 6.01 TB
  Capacity : 7.00 TB
  Free     : 0.98 TB
  M365 tenant: Technijian365.onmicrosoft.com

Currently the largest tenant on the server. At ~4%/month growth the
free space will drop below 0.5 TB in 3 months and to zero in 6-7 months.

Resolution steps:

1. RDP into {server} ({host}). Credentials in keys/veeam-365.md.

2. Decide between extend-in-place and add-new-repo. For Technijian's
   own data, prefer extending in place to keep restore-point chains
   intact (we have 6+ months of dailies on this repo).

3. Extend the C:\\O365 Backups\\ volume to 14 TB (double current cap):
     a. In vSphere, grow the data VMDK from 7 TB to 14 TB.
     b. On the host: Disk Management → Extend Volume → use new space.
     c. Open the Veeam console → Backup Infrastructure → Backup
        Repositories → TECH-O365 → Properties → Save (forces capacity
        re-read).

4. If extending isn't an option, add a new repo TECH-O365-V2 on a fresh
   VMDK, switch the TECH-O365 backup job to the new repo, and retire
   the old repo after 30 days of clean runs on the new one.

5. Verify with:
     cd c:/vscode/annual-client-review/annual-client-review-1/scripts/veeam-365
     python pull_full.py --only TECHNIJIAN
   The TECH-O365 row should show free > 50% of capacity.

6. Reply with disk action, new capacity, and confirmation of first
   successful backup post-resize.

Note: this is INTERNAL (DirID=139, Internal Contract 3977). It exists
purely to track the work — no client-facing report.

Auto-filed by scripts/veeam-365/file_capacity_tickets.py.
""".format(server=VB365_NAME, host=VB365_HOST),
    },
    # ---------- 3. ALG-O365 capacity + Warning ----------
    {
        "code": "ALG",
        "issue_key": "veeam-365:repo-capacity-and-warning:ALG-O365",
        "priority": PRIORITY_SAME_DAY,
        "metadata": {"repo_name": "ALG-O365", "used_pct": 85.6, "job_status": "Warning"},
        "title": "Veeam 365 ALG-O365 — repo at 85.6% full AND last job run returned Warning",
        "description": """\
Two related issues on ALG's Veeam 365 backup, both detected by the
2026-05-02 REST pull:

ISSUE A — Repository capacity:
  Repository: ALG-O365
  Server   : {server} ({host})
  Path     : C:\\O365 Backups\\bkp_ALG-365
  Used     : 2.57 TB
  Capacity : 3.00 TB
  Free     : 0.43 TB (14.4% free)
  M365 tenant: NETORG672839.onmicrosoft.com (35 users)

ISSUE B — Backup job in Warning state:
  Job      : ALG-O365
  Last run : 2026-05-02T19:10:22Z
  Status   : Warning  (NOT Success / Running / Failed)
  Enabled  : True
  Next run : 2026-05-03T08:00:00Z (note: daily, not every-10-min like
              other tenants — schedule is "Daily 08:00 UTC")

Resolution steps:

PART 1 — Investigate the Warning (do this first; root cause may
inform the capacity decision):

1. RDP into {server} ({host}). Credentials in keys/veeam-365.md.

2. Open the Veeam Backup for Microsoft 365 console.

3. Navigate to History → Job Sessions → filter on Job = ALG-O365.

4. Open the most recent session (2026-05-02T19:10:22Z, Status =
   Warning). Read the messages tab — typical Warning causes:
     - Item failed to back up (corrupt mailbox / blocked by retention
       policy / Microsoft Graph throttling)
     - Repository running low on free space (Veeam pre-flight warning)
     - Single-item permission denied (e.g. shared mailbox without
       Application impersonation)

5. Capture the Warning text in this ticket reply, then proceed to
   Part 2 (capacity remediation) which often clears the Warning if it
   was a low-space pre-flight.

PART 2 — Capacity:

6. RDP into {server} ({host}) (same session).

7. Extend the C:\\O365 Backups\\ volume by at least 2 TB:
     a. vSphere → grow data VMDK from 3 TB to 5 TB.
     b. Disk Management → Extend Volume.
     c. Veeam console → Backup Repositories → ALG-O365 → Properties
        → confirm capacity re-reads.

8. (Alternative) Add a new repo ALG-O365-V2 (5 TB), edit the ALG-O365
   job → Storage step → repoint to the new repo. Run job once
   manually. Decommission old repo after 30 days of clean runs.

9. Verify:
     cd c:/vscode/annual-client-review/annual-client-review-1/scripts/veeam-365
     python pull_full.py --only ALG
   ALG row should show: lastStatus=Success (not Warning), free space
   > 1 TB.

10. Reply with:
      - Warning root cause + resolution from step 4
      - Capacity action taken + new size
      - First successful Success-state run after the change

Reference:
- Skill: .claude/skills/veeam-365-pull/SKILL.md
- Snapshot: clients/_veeam_365/snapshots/2026-05-02.json
- Latest report: clients/alg/veeam-365/reports/ALG - Veeam 365 Monthly - 2026-05.docx
- Auto-filed by scripts/veeam-365/file_capacity_tickets.py
""".format(server=VB365_NAME, host=VB365_HOST),
    },
    # ---------- 4. ORX migration cleanup ----------
    {
        "code": "ORX",
        "issue_key": "veeam-365:migration-cleanup:ORX",
        "priority": PRIORITY_NEXT_DAY,
        "metadata": {"old_repo": "ORX-O365", "new_repo": "ORX_365_New", "anomaly": "used > capacity"},
        "title": "Veeam 365 ORX — verify migration to new repo + retire stale ORX-O365 repo (capacity anomaly)",
        "description": """\
Issue (auto-detected from Veeam 365 REST pull, 2026-05-02):
ORX has TWO Veeam 365 repositories, suggesting a migration is in
progress. The data is inconsistent and needs verification.

Repositories on {server} ({host}):

  Repo A — OLD (suspected orphan):
    Name     : ORX-O365
    Path     : C:\\O365 Backups\\bkp_ORX-365
    Used     : 3.82 TB    <-- IMPOSSIBLE
    Capacity : 0.10 TB    <-- This says 109 GB
    Free     : 0.03 TB
    Anomaly  : usedSpaceBytes (3.82 TB) > capacityBytes (109 GB).
               Either the underlying volume was shrunk while data
               remained, or the repo's capacity metadata is stale and
               the volume was removed without unmounting the repo.

  Repo B — NEW (suspected target):
    Name     : ORX_365_New
    Path     : C:\\O365 Backups\\bkp_ORX365
    Used     : 0.28 TB
    Capacity : 5.00 TB    <-- Clean, plenty of headroom
    Free     : 4.72 TB

Active job state:
  Job      : ORX-365
  Status   : Running
  Last run : NULL  <-- never recorded a completed run
  Enabled  : True
  Next run : 2026-05-02T20:10:00Z (every 10 min)

The fact that lastRun is NULL strongly suggests the job was just
re-pointed at ORX_365_New and the first run has not finished yet.

Resolution steps:

1. RDP into {server} ({host}). Credentials in keys/veeam-365.md.

2. Open the Veeam Backup for Microsoft 365 console.

3. Verify the ORX-365 backup job's destination repository:
     Backup → Jobs → ORX-365 → Edit → Storage step.
   Confirm it points to ORX_365_New (NOT the old ORX-O365).
   If it still points to the old repo, repoint to ORX_365_New now.

4. Trigger a manual run of the ORX-365 job and let it complete.
   Watch the session log → expect a full / large incremental on the
   first run after the repo switch.

5. Once the manual run shows Success in History → Job Sessions, the
   lastRun field will populate. Verify with:
     cd c:/vscode/annual-client-review/annual-client-review-1/scripts/veeam-365
     python pull_full.py --only ORX

6. Audit the OLD repo (ORX-O365):
     Backup Infrastructure → Backup Repositories → ORX-O365 →
     Properties.
   - If it says "Repository unavailable" or shows the volume as
     missing, that explains the capacity anomaly. The old VMDK was
     removed without first unmounting the repo in Veeam.
   - Check that the new repo (ORX_365_New) has at least one full
     backup with all 4 services (Exchange / OneDrive / SharePoint /
     Teams). Use the latest restore point listed under Restore →
     Microsoft 365 Backup → ORX.

7. After ORX_365_New has 30 days of consecutive successful runs:
     a. Right-click ORX-O365 (the old one) → Disable.
     b. Wait 7 days, confirm no operational issues.
     c. Right-click → Remove. Choose "Remove from configuration"
        (data already gone if the volume was removed; otherwise
        delete the data folder).

8. Reply on this ticket with:
     - Step 3 result (was the job pointing at the old or new repo?)
     - Step 4 timestamp + Success / Failed
     - Step 5 lastRun value
     - Step 6 finding on the old repo (truly orphaned vs still has data)
     - Step 7 schedule (when do we expect to remove ORX-O365)

Why this matters:
The puller currently sums usedSpaceBytes across BOTH repos for ORX,
so the per-tenant total reported in the monthly client report is
double-counting until the old repo is removed. The client-facing
report at clients/orx/veeam-365/reports/ORX - Veeam 365 Monthly -
2026-05.docx shows ORX = 4.10 TB, but the real usage (new repo only)
is closer to 0.28 TB.

Reference:
- Skill: .claude/skills/veeam-365-pull/SKILL.md
- Snapshot: clients/_veeam_365/snapshots/2026-05-02.json
- Auto-filed by scripts/veeam-365/file_capacity_tickets.py
""".format(server=VB365_NAME, host=VB365_HOST),
    },
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build XML payloads without calling the SP")
    args = ap.parse_args()

    receipts = []
    for spec in TICKETS:
        print(f"\n* {spec['code']:<12}  Priority={spec['priority']}  {spec['title'][:80]}")
        try:
            if args.dry_run:
                # No state side-effect on dry-run — just build XML via raw create_ticket_for_code
                r = cp_tickets.create_ticket_for_code(
                    spec["code"],
                    title=spec["title"],
                    description=spec["description"],
                    priority=spec["priority"],
                    assign_to_dir_id=ASSIGN_TO_CHD_TS1,
                    role_type=1232,
                    dry_run=True,
                )
                print(f"   DRY-RUN  XML built ({len(r.get('xml_in') or '')} chars)")
                receipts.append({"code": spec["code"], "ticket_id": None, "skipped": False,
                                 "issue_key": spec["issue_key"], "title": spec["title"]})
                continue

            r = cp_tickets.create_ticket_for_code_tracked(
                spec["code"],
                issue_key=spec["issue_key"],
                source_skill=SOURCE_SKILL,
                title=spec["title"],
                description=spec["description"],
                priority=spec["priority"],
                assign_to_dir_id=ASSIGN_TO_CHD_TS1,
                role_type=1232,
                metadata=spec.get("metadata"),
            )
            tid = r.get("ticket_id")
            if r.get("skipped"):
                print(f"   SKIP     existing ticket #{tid} for issue_key={spec['issue_key']!r}")
            else:
                print(f"   OK       TicketID={tid}  state recorded")
            receipts.append({"code": spec["code"], "ticket_id": tid, "skipped": r.get("skipped"),
                             "issue_key": spec["issue_key"], "title": spec["title"]})
        except Exception as e:
            print(f"   FAIL     {e}")
            receipts.append({"code": spec["code"], "error": str(e), "title": spec["title"]})

    print("\n" + "=" * 70)
    print("Summary:")
    print(json.dumps(receipts, indent=2))


if __name__ == "__main__":
    main()
