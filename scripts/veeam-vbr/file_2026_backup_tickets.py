"""
File CP tickets for the 2026 backup posture issues uncovered by the
Veeam ONE + VBR pulls. One ticket per distinct technical issue per
client. All tickets billable to the client's active contract, assigned
to CHD : TS1 (DirID 205) — India tech support pod.

Usage:
    python file_2026_backup_tickets.py --dry-run   # build XML, no API call
    python file_2026_backup_tickets.py             # live — create tickets
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "clientportal"))
import cp_tickets  # noqa: E402

# Priority IDs from CP lookup view
PRI_CRITICAL = 1253
PRI_SAME_DAY = 1255
PRI_NEXT_DAY = 1256

TICKETS = [
    # ---- VAF ----
    dict(
        code="VAF",
        priority=PRI_CRITICAL,
        title="URGENT: bkp_VAF backup repository at 97.5% capacity (6-day runway to outage)",
        description=(
            "Veeam ONE is reporting bkp_VAF (the VAF backup repository on TE-DC-BK-VBR-01) "
            "at 97.5% used as of 2026-05-02. Veeam ONE projects the repo will be FULL in 6 DAYS "
            "at the current ingest rate.\n\n"
            "Repo details:\n"
            "  - Name: bkp_VAF\n"
            "  - Path: nfs3://10.7.9.225:/bkp_VAF\n"
            "  - Capacity: 6.0 TB\n"
            "  - Free: 151.8 GB (2.5%)\n"
            "  - Out-of-space ETA (Veeam ONE): 6 days\n"
            "  - Immutability: not enabled\n\n"
            "Action required by India TS1:\n"
            "1. Open Veeam Backup & Replication console on TE-DC-BK-VBR-01.\n"
            "2. Confirm current retention on bkp_VAF job (currently 14-day forward-incremental). "
            "   If retention can be tightened to 7 days WITHOUT violating client backup policy, "
            "   apply the change and trigger a retention scrub to free space.\n"
            "3. If retention is at policy floor, escalate to infrastructure: expand the underlying "
            "   NFS volume (10.7.9.225:/bkp_VAF on the NetApp/TrueNAS host that serves bkp_VAF) "
            "   by at least 4 TB to give a 90-day runway buffer.\n"
            "4. After expansion, force a config rescan in VBR: Backup Infrastructure > Backup "
            "   Repositories > bkp_VAF > Properties > Next > Apply.\n"
            "5. Verify Veeam ONE dashboard refreshes new capacity within 1 hour.\n"
            "6. Reply on this ticket with: (a) action taken, (b) new capacity, (c) new free %, "
            "   (d) whether retention was changed.\n\n"
            "Context:\n"
            "  - VBR server: TE-DC-BK-VBR-01 (10.7.9.220) v13.0.1.2067\n"
            "  - Veeam ONE: TE-DC-VONE-01 (10.7.9.135)\n"
            "  - 2026 YTD sessions for VAF: 268 (96 Success / 6 Warning / 166 Failed)\n"
            "  - Many of the 166 failures are repository-threshold-check errors that will "
            "    cascade until the capacity issue is resolved."
        ),
    ),
    dict(
        code="VAF",
        priority=PRI_SAME_DAY,
        title="VAF: Bkp_VAF_IMT immediate-mode repository failing threshold-check (15+ in last week)",
        description=(
            "VBR job Bkp_VAF_IMT (immediate-mode / hot backup) has failed 15+ times in 2026 with:\n\n"
            "    \"Cannot perform repository threshold check, failed to get space info: "
            "repository \\\"Bkp_VAF_IMT\\\"\"\n\n"
            "Most recent failure: 2026-05-02 00:03:05 PT.\n\n"
            "This is distinct from the bkp_VAF capacity issue (separate ticket). The Bkp_VAF_IMT "
            "repository appears to be unreachable for capacity introspection — VBR cannot read "
            "free-space info, which causes every job run to abort the threshold check.\n\n"
            "Action required by India TS1:\n"
            "1. Open VBR console > Backup Infrastructure > Backup Repositories > Bkp_VAF_IMT.\n"
            "2. Right-click > Properties — verify the path/share is correct and the gateway "
            "   server is online.\n"
            "3. Click 'Test path' button. If it fails, capture the exact error.\n"
            "4. From TE-DC-BK-VBR-01 powershell: test the underlying NFS/SMB mount manually.\n"
            "   (If NFS: `Test-NetConnection 10.7.9.225 -Port 2049`; \n"
            "    if SMB:  `Test-Path \\\\<server>\\<share>`)\n"
            "5. If the share is unreachable: investigate why the storage host (likely 10.7.9.225) "
            "   is rejecting Veeam's gateway server. Check firewall, NFS exports, root_squash.\n"
            "6. After fix: Backup Infrastructure > Backup Repositories > Bkp_VAF_IMT > Rescan.\n"
            "7. Force-run the next Bkp_VAF_IMT job and confirm it completes Success.\n"
            "8. Reply on this ticket with root cause + remediation."
        ),
    ),
    dict(
        code="VAF",
        priority=PRI_SAME_DAY,
        title="VAF: 56x VBR RPC timeouts ('Time is out / Failed to invoke rpc command') on production VMs",
        description=(
            "The VAF backup job has hit 'Task failed. Error: Time is out / Failed to invoke "
            "rpc command' 56 times in 2026 across production VMs. Symptom = the VBR proxy "
            "loses its RPC channel to the guest VM (or to vCenter) mid-backup.\n\n"
            "Affected VMs (most-impacted first):\n"
            "  - VAF-DC-FS-01 (file server, 18x Processing failures)\n"
            "  - VAF-DC-SQL-01 (SQL server, 13x Processing failures)\n"
            "  - VAF-DC-AD-01 (domain controller, 6x Processing failures)\n\n"
            "Also seen 13x: \"Tag VAF is unavailable, VMs residing on it will be skipped from "
            "processing\" — vSphere tag drift, and 6x: \"Host was not found. Id: "
            "[6e1c2b73-a9a3-4df1-9d94-3daae193ec7a], HostRef: [host-51005]\" — stale ESXi host "
            "reference in VBR's cache.\n\n"
            "Action required by India TS1:\n"
            "1. RDP to TE-DC-BK-VBR-01. In VBR console, run a 'Rescan' on the vCenter "
            "   172.16.9.252 connection: Backup Infrastructure > Managed Servers > "
            "   172.16.9.252 > Rescan. This will clear the stale host-51005 reference.\n"
            "2. Verify VMware Tools is current on VAF-DC-FS-01, VAF-DC-SQL-01, VAF-DC-AD-01:\n"
            "   `vmware-toolbox-cmd -v` from each guest, or via vCenter > VM Summary tab. "
            "   Upgrade if not 12.x+.\n"
            "3. On the vCenter side, confirm vSphere tag 'VAF' still exists and is applied to "
            "   every VAF VM. The job's include rule is `Tag = VAF` — if the tag was renamed/"
            "   removed, all backups go null.\n"
            "4. Force-run the bkp_VAF job after the above and watch the session log for any "
            "   remaining RPC timeouts.\n"
            "5. If RPC timeouts persist on FS/SQL specifically: it's likely VSS quiescence "
            "   stalls on those workloads. Consider switching those two VMs to "
            "   crash-consistent or app-aware processing with truncate-only on SQL.\n"
            "6. Reply with: which VMs still fail, what action resolved each."
        ),
    ),
    # ---- ORX ----
    dict(
        code="ORX",
        priority=PRI_CRITICAL,
        title="URGENT: bkp_ORX backup repository at 80.8% capacity (3-day runway to outage)",
        description=(
            "Veeam ONE is reporting bkp_ORX (the ORX backup repository on TE-DC-BK-VBR-01) "
            "with only 3 DAYS of runway before it fills.\n\n"
            "Repo details:\n"
            "  - Name: bkp_ORX\n"
            "  - Path: nfs3://10.7.9.225:/bkp_ORX\n"
            "  - Capacity: 18.0 TB\n"
            "  - Free: 3.5 TB (19.2%)\n"
            "  - Out-of-space ETA (Veeam ONE): 3 days  ← MOST URGENT IN ESTATE\n"
            "  - Immutability: not enabled\n\n"
            "Action required by India TS1 (TODAY, before next backup window 2026-05-02 19:00 PT):\n"
            "1. Open VBR console on TE-DC-BK-VBR-01 > Backup Infrastructure > Backup "
            "   Repositories > bkp_ORX.\n"
            "2. Check current job retention on bkp_ORX (likely 14-day forward-inc + GFS).\n"
            "3. PRIMARY ACTION: expand the underlying NFS volume on 10.7.9.225 by at least 8 TB. "
            "   The ORX backup ingest rate is roughly 1 TB/day, so 8 TB buys ~8 days of working "
            "   buffer plus reasonable retention headroom.\n"
            "4. SECONDARY ACTION (only if expansion is blocked): trim retention to 10 days and "
            "   trigger an immediate retention scrub. Coordinate with the ORX account team — "
            "   contractual retention may be 14 days minimum.\n"
            "5. After expansion: VBR > Backup Repositories > bkp_ORX > Rescan, then verify "
            "   Veeam ONE dashboard updates within 1 hour.\n"
            "6. Reply on ticket with: action taken, new capacity, new free %, retention change "
            "   (if any).\n\n"
            "Context:\n"
            "  - VBR server: TE-DC-BK-VBR-01 (10.7.9.220) v13.0.1.2067\n"
            "  - 2026 YTD sessions for ORX: 292 (88 Success / 6 Warning / 198 Failed)\n"
            "  - Failure count is high and will worsen as repo fills."
        ),
    ),
    dict(
        code="ORX",
        priority=PRI_SAME_DAY,
        title="ORX: Bkp_ORX_IMT repository threshold-check failures (18+ in last week)",
        description=(
            "VBR job Bkp_ORX_IMT (immediate-mode / hot backup) has failed 18+ times in 2026 "
            "with:\n\n"
            "    \"Cannot perform repository threshold check, failed to get space info: "
            "repository \\\"Bkp_ORX_IMT\\\"\"\n\n"
            "Most recent failure: 2026-05-02 00:19:39 PT. Same root pattern is hitting bkp_VAF "
            "and bkp_MAX (separate tickets). Likely a shared IMT-repository registration or "
            "gateway-server visibility problem.\n\n"
            "Action required by India TS1:\n"
            "1. VBR console > Backup Infrastructure > Backup Repositories > Bkp_ORX_IMT > "
            "   Properties.\n"
            "2. Verify path / share / gateway-server selection is correct and online.\n"
            "3. Click 'Test path' — capture the exact error if it fails.\n"
            "4. From TE-DC-BK-VBR-01 PowerShell: test the mount manually "
            "   (`Test-NetConnection 10.7.9.225 -Port 2049` for NFS).\n"
            "5. If the underlying storage rejects Veeam's gateway: check NFS exports, root_squash, "
            "   firewall on 10.7.9.225.\n"
            "6. Rescan Bkp_ORX_IMT after fix; force-run next Bkp_ORX_IMT job.\n"
            "7. Reply with root cause + remediation."
        ),
    ),
    dict(
        code="ORX",
        priority=PRI_SAME_DAY,
        title="ORX: 48x VBR RPC timeouts ('Time is out') on TS/VDI/CB VMs",
        description=(
            "The ORX backup job has hit 'Task failed. Error: Time is out / Failed to invoke "
            "rpc command' 48 times in 2026 (28 + 20 variants).\n\n"
            "Affected VMs:\n"
            "  - ORX-DC-CB-01 (10x Processing failures)\n"
            "  - ORX-DC-VDI-GI (10x)\n"
            "  - ORX-DC-TS-03 (9x)\n"
            "  - 9x \"Job has failed unexpectedly\" — generic abort\n"
            "  - 9x \"Operation was canceled by user .\\\\Administrator\" — manual cancellations "
            "    (likely the on-call team killing stuck jobs)\n\n"
            "Action required by India TS1:\n"
            "1. RDP to TE-DC-BK-VBR-01. Rescan the vCenter 172.16.9.252 connection in VBR "
            "   (Backup Infrastructure > Managed Servers > 172.16.9.252 > Rescan).\n"
            "2. Confirm VMware Tools is current on ORX-DC-CB-01, ORX-DC-VDI-GI, ORX-DC-TS-03.\n"
            "3. On vCenter, verify vSphere tag 'ORX' is applied to all ORX production VMs.\n"
            "4. For VDI VMs (ORX-DC-VDI-GI in particular): consider switching from app-aware "
            "   processing to crash-consistent — VDI sessions are noisy and VSS quiescence "
            "   often times out.\n"
            "5. Force-run bkp_ORX after the above; watch session log for remaining RPC "
            "   timeouts.\n"
            "6. Reply with: which VMs still fail, what action resolved each, and whether the "
            "   manual job-cancel pattern can be eliminated by the above fixes."
        ),
    ),
    # ---- MAX ----
    dict(
        code="MAX",
        priority=PRI_SAME_DAY,
        title="MAX: vSphere tag 'MAX' missing - 18x 'Tag MAX is unavailable' in 2026, blocking VM enumeration",
        description=(
            "VBR job bkp_MAX has logged 18x in 2026:\n\n"
            "    \"Tag MAX is unavailable, VMs residing on it will be skipped from "
            "processing\"\n\n"
            "The job's include rule is `Tag = MAX` — when the tag is missing on vCenter the "
            "job runs but processes ZERO VMs. We may have unprotected MAX workloads as a "
            "result.\n\n"
            "Action required by India TS1:\n"
            "1. Connect to vCenter 172.16.9.252.\n"
            "2. Menu > Tags & Custom Attributes > Tags.\n"
            "3. Confirm tag 'MAX' exists in the appropriate category. If missing, recreate it "
            "   in the same category that the other client tags use (TOR, CCC, VAF, etc. — "
            "   check one of those for the canonical category, likely 'Client' or similar).\n"
            "4. Once the tag exists, locate every MAX-* VM on the cluster and apply the tag:\n"
            "   - VMs > filter by name pattern 'MAX-*' (MAX-DC-AD-01, MAX-DC-FS-01, "
            "     MAX-DC-VDI-002, MAX-DC-VDI-GI, etc.)\n"
            "   - Right-click each > Tags & Custom Attributes > Assign Tag > MAX.\n"
            "5. Force-run bkp_MAX from VBR. Confirm the session log no longer warns "
            "   'Tag MAX is unavailable' AND that VMs are processed.\n"
            "6. Reply with: count of VMs found, count of VMs successfully tagged, last "
            "   bkp_MAX session result post-fix."
        ),
    ),
    dict(
        code="MAX",
        priority=PRI_SAME_DAY,
        title="MAX: Bkp_MAX_IMT threshold-check failure + bkp_TECH NFS share intermittently unavailable",
        description=(
            "Two distinct but related issues hitting MAX backups in 2026:\n\n"
            "Issue 1 - Bkp_MAX_IMT threshold-check failure (12x):\n"
            "    \"Cannot perform repository threshold check, failed to get space info: "
            "repository \\\"Bkp_MAX_IMT\\\"\"\n"
            "  Same pattern hitting Bkp_VAF_IMT and Bkp_ORX_IMT (separate tickets).\n\n"
            "Issue 2 - bkp_TECH NFS share unavailable (5x):\n"
            "    \"Selected gateway server bkp_TECH is unavailable: NFS share "
            "    'nfs3://10.7.9.230:/bkp_TECH' is unavailable\"\n"
            "  This means MAX backups are being routed via the bkp_TECH gateway and that gateway "
            "  goes offline intermittently. NOTE: bkp_TECH is the Technijian primary repo, so "
            "  intermittent unavailability there also affects internal Technijian backups — "
            "  worth flagging upstream.\n\n"
            "Also note: there is no dedicated 'bkp_MAX' repository in Veeam ONE. MAX backups "
            "appear to land on shared infrastructure (likely bkp_TECH) which is why issue 2 "
            "has client impact.\n\n"
            "Action required by India TS1:\n"
            "1. Verify where Bkp_MAX and Bkp_MAX_IMT actually write to: VBR console > Jobs > "
            "   bkp_MAX > Edit > Storage > note the destination repository.\n"
            "2. If MAX is on shared bkp_TECH: open a follow-up planning ticket (do NOT fix in "
            "   this ticket) to provision a dedicated bkp_MAX repository, mirroring the "
            "   bkp_<CODE> pattern used for every other hosted client.\n"
            "3. For Bkp_MAX_IMT: VBR > Backup Repositories > Bkp_MAX_IMT > Properties > Test "
            "   Path. Capture exact error. Most likely the underlying NFS share isn't mounted "
            "   on the gateway server.\n"
            "4. For the bkp_TECH NFS unavailability: Test-NetConnection 10.7.9.230 -Port 2049 "
            "   from TE-DC-BK-VBR-01. Check the NFS host (10.7.9.230) for service health, "
            "   nfsd process, and recent log entries during the timestamps of the failures "
            "   (timestamps are in clients/max/veeam-vbr/2026/sessions_2026.json).\n"
            "5. After fixes, force-run bkp_MAX and Bkp_MAX_IMT, confirm both complete "
            "   Success.\n"
            "6. Reply with: destination repo of MAX jobs, root cause of NFS unavailability, "
            "   whether a dedicated bkp_MAX repo is needed."
        ),
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build XML, skip API call")
    ap.add_argument("--only-first", action="store_true",
                    help="only file the first ticket (sanity check)")
    args = ap.parse_args()

    receipts = []
    for i, t in enumerate(TICKETS, 1):
        if args.only_first and i > 1:
            break
        print(f"\n[{i}/{len(TICKETS)}] {t['code']:6s} {t['title'][:80]}")
        try:
            r = cp_tickets.create_ticket_for_code(
                t["code"],
                title=t["title"],
                description=t["description"],
                priority=t["priority"],
                dry_run=args.dry_run,
            )
            tid = r.get("ticket_id")
            mode = "DRY-RUN" if args.dry_run else "CREATED"
            print(f"  {mode}  ticket_id={tid}")
            receipts.append({"index": i, "code": t["code"], "title": t["title"],
                             "priority": t["priority"], "ticket_id": tid,
                             "dry_run": args.dry_run})
        except Exception as e:
            print(f"  ERROR  {e}")
            receipts.append({"index": i, "code": t["code"], "title": t["title"],
                             "error": str(e)})

    log = REPO_ROOT / "clients" / "_veeam_vbr" / "2026-05-02" / (
        "tickets_filed.json" if not args.dry_run else "tickets_dryrun.json"
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps(receipts, indent=2, default=str), encoding="utf-8")
    print(f"\nreceipts -> {log.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
