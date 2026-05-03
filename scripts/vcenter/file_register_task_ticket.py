"""One-shot: file an internal CP ticket for India support to register the
Technijian-DailyVCenterPull scheduled task on the host workstation.

Filed against Technijian internal contract (DirID=139, ContractID=3977).
Priority: When Convenient (1257). Assignee: CHD : TS1 (DirID 205, default).

Run once:
    py -3 scripts/vcenter/file_register_task_ticket.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "clientportal"))
import cp_tickets  # type: ignore

TITLE = "Register Technijian-DailyVCenterPull scheduled task (vCenter daily pipeline)"

DESCRIPTION = """\
INTERNAL TICKET — Technijian house infrastructure.

CONTEXT
=======
We just shipped a new daily-pull pipeline for VMware vCenter (172.16.9.252).
Skill `vcenter-rest` + repo runner at:

    C:\\VSCode\\annual-client-review\\annual-client-review\\scripts\\vcenter\\
    (annual-client-review-1\\ on the dev box; same path under the
    production-workstation convention used by all the other daily pulls)

The skill is built and verified; vCenter advanced setting `5-min interval =
collection level 3` is already applied (raised by Claude Code on 2026-05-02
via `set_perf_level.py`). Only remaining step: register the Windows
scheduled task on the workstation that hosts the rest of the daily-pull
schedule (Huntress 01:00, Umbrella 02:00, CrowdStrike 03:00, Teramind 04:00,
Meraki 05:00). New task slot: vCenter at 06:00 PT.

The user-side rule "no scheduled-task registration on the dev box" is the
reason this is being routed to the production workstation owner via this
ticket rather than executed by the dev box that wrote the skill.

WHAT TO DO (step by step)
=========================

1. RDP / log in to the production workstation that already runs the other
   daily-pull tasks (the same box that has `Technijian-DailyMerakiPull`,
   `Technijian-DailyHuntressPull`, etc. registered). It must be running as
   the user account that owns the OneDrive keyvault sync at
   `<OneDrive>\\Documents\\VSCODE\\keys\\` — SYSTEM cannot read those files.

2. Make sure the repo is up to date:

       cd /d c:\\vscode\\annual-client-review\\annual-client-review
       git pull

   If the path on this workstation differs (e.g. ends in
   `annual-client-review-1`), `cd` to wherever your existing daily-pull
   repo lives. The wrapper resolves its own repo root via `pushd
   "%~dp0..\\.."`, so it works wherever it sits.

3. Verify the wrapper exists at the expected path:

       dir scripts\\vcenter\\run-daily-vcenter.cmd

   Expected: file present, ~1 KB. If missing, the repo is out of date —
   pull again or re-clone.

4. Verify the keyvault has vCenter credentials:

       dir "%USERPROFILE%\\OneDrive - Technijian, Inc\\Documents\\VSCODE\\keys\\vcenter.md"

   Expected: file present. If missing, escalate — do NOT register the task
   yet; the .cmd will fail every run with a creds-not-found error.

5. Verify Python 3 + required packages are installed (same prereqs as the
   other daily pulls). One-line smoke test:

       py -3 -c "import requests, urllib3, pyVmomi, openpyxl; print('OK')"

   If any module is missing:

       py -3 -m pip install requests urllib3 pyvmomi openpyxl

6. Verify connectivity to vCenter from this workstation. From PowerShell:

       Test-NetConnection -ComputerName 172.16.9.252 -Port 443

   Expected: `TcpTestSucceeded : True`. If False, the workstation isn't on
   the management LAN — escalate (network or VPN issue, NOT a Claude/script
   issue).

7. Optional sanity test BEFORE registering the task — runs the skill
   client's smoke test (auth + counts; does not modify anything):

       set PYTHONIOENCODING=utf-8
       py -3 "%USERPROFILE%\\.claude\\skills\\vcenter-rest\\scripts\\vcenter_client.py"

   Expected output includes lines like:
       vCenter version: ... 8.0.0.10200
       VM count: 205
       Datastore count: 25
       Host count: 14
       Active alarms: 0

   Numbers will drift as inventory changes; the point is to confirm the
   client can authenticate and see the cluster.

8. Register the scheduled task. Open an elevated `cmd.exe` and run (single
   command — the carets are line continuations):

       schtasks /create ^
         /tn "Technijian-DailyVCenterPull" ^
         /tr "c:\\vscode\\annual-client-review\\annual-client-review\\scripts\\vcenter\\run-daily-vcenter.cmd" ^
         /sc DAILY ^
         /st 06:00 ^
         /ru "%USERNAME%" ^
         /f

   ADJUST THE /tr PATH IF YOUR REPO LIVES ELSEWHERE. Common variants:
       c:\\vscode\\annual-client-review\\annual-client-review\\scripts\\vcenter\\run-daily-vcenter.cmd
       c:\\vscode\\annual-client-review\\annual-client-review-1\\scripts\\vcenter\\run-daily-vcenter.cmd

   `/ru "%USERNAME%"` MUST be the same account that runs the other
   daily-pull tasks (Huntress, Meraki, etc.). Confirm with:

       schtasks /query /tn "Technijian-DailyHuntressPull" /v /fo LIST | findstr "Run As"

9. Verify the registration:

       schtasks /query /tn "Technijian-DailyVCenterPull" /v /fo LIST

   Expected highlights:
       TaskName: \\Technijian-DailyVCenterPull
       Next Run Time: <tomorrow 6:00 AM>
       Status: Ready
       Schedule: At 6:00 AM every day
       Task To Run: c:\\vscode\\...\\scripts\\vcenter\\run-daily-vcenter.cmd
       Run As User: <same as other daily-pull tasks>

10. Test-run the task immediately (does NOT wait for 06:00):

        schtasks /run /tn "Technijian-DailyVCenterPull"

    The wrapper should kick off and write a log to:

        scripts\\vcenter\\state\\run-<YYYY-MM-DD>.log

    Inspect:

        dir scripts\\vcenter\\state\\
        type scripts\\vcenter\\state\\run-<today>.log

    Expected log highlights (last lines):
        [dump] hosts/clusters/datacenters/networks done
        [dump] vms.json done (205 VMs)
        [dump] datastores.json done (25)
        [dump] luns.json done (336)
        [dump] alerts.json done (0)
        [vm_perf] 200/205 done
        [storage_perf] host 10.100.1.42 done (... series)
        [split] 205 VMs total, 11 system VMs skipped
        [split]   CCC: 3 VMs ... TECHNIJIAN: 139 VMs ... VG: 1 VMs
        [agg] vm_perf: added/replaced 1 day buckets -> .../vm_perf_daily.json
        [agg] storage_perf: added/replaced 1 day buckets -> .../storage_perf_daily.json
        [daily] OK (<today's date>)
        === <today> vcenter daily pull end (exit 0) ===

    Total runtime: ~10-25 minutes (most of it is the per-VM perf walk —
    one VM at a time per `vpxd.stats.maxQueryMetrics=64`).

11. Verify per-client outputs were refreshed. Pick any hosted client:

        dir clients\\orx\\vcenter\\2026\\

    Expected:
        alerts.json
        datastores.json
        luns.json
        storage_perf.json
        storage_perf_daily.json    <-- new accumulator (or grew by 1 day)
        summary.json
        summary.xlsx
        vm_perf.json
        vm_perf_daily.json         <-- new accumulator (or grew by 1 day)
        vms.json

    The two `*_daily.json` files are the year-long accumulators that grow
    one bucket per day. After 30 days you'll have 30 daily peak/avg/p95
    buckets per VM and per datastore, ready for trend reports.

12. Confirm task settings are right (open Task Scheduler GUI):
    - Trigger: Daily at 06:00, recurring
    - Settings: "Run only when user is logged on" = checked (required for
      OneDrive keyvault access)
    - Settings: "If the task fails, restart every 1 hour, attempt 3 times"
      (matches other daily-pull tasks)

13. Reply on this ticket with:
    - The exact `/tr` path you used (so we can fix workstation.md if it
      differs from the documented path)
    - Output of `schtasks /query /tn "Technijian-DailyVCenterPull" /v /fo LIST`
    - First-run exit code (should be 0)
    - Path to the log file (`scripts\\vcenter\\state\\run-<date>.log`)
    - Any deltas vs the expected output above

ROLLBACK (if anything goes sideways)
====================================

       schtasks /delete /tn "Technijian-DailyVCenterPull" /f

This stops the daily run. The skill itself stays in place; nothing else is
affected. We can re-register after fixing whatever the issue was.

REFERENCE
=========
- Workstation playbook: `workstation.md` §69 (credentials + smoke + the
  vCenter advanced setting context) and §70 (this registration command).
- System spec: `docs/system-specification.md` §5.15 (full pipeline detail)
  + §10 (scheduled-tasks table — `Technijian-DailyVCenterPull` row).
- Skill: `~/.claude/skills/vcenter-rest/`.
- Repo runner source: `scripts/vcenter/{daily_run.py, run-daily-vcenter.cmd,
  client_overrides.json}`.

Why this is being assigned to India support: per the rule
`feedback_no_dev_box_schedules` ("never run Register-ScheduledTask here;
document setup in workstation.md"), Claude Code on the dev box does not
register scheduled tasks. India support performs the registration on the
correct production workstation.
"""


def main() -> int:
    print(f"[ticket] filing: {TITLE}")
    print(f"[ticket] description length: {len(DESCRIPTION)} chars")
    print()
    result = cp_tickets.create_ticket_for_code(
        "Technijian",
        title=TITLE,
        description=DESCRIPTION,
        priority=1257,           # When Convenient
        # assign_to_dir_id=205,  # default = CHD : TS1
        # role_type=1232,        # default = Tech Support
        # status=1259,           # default = New
    )
    print(json.dumps({k: v for k, v in result.items() if k != "xml_in"},
                      indent=2, default=str))
    if result.get("ticket_id"):
        print(f"[ticket] OK — TicketID = {result['ticket_id']}")
        return 0
    print(f"[ticket] WARNING — ticket_id not extracted; check 'raw' above")
    return 1


if __name__ == "__main__":
    sys.exit(main())
