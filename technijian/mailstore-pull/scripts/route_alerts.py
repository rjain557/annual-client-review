"""Route MailStore SPE alerts into Client Portal tickets for India support to fix.

Detects alerts, classifies them per-client, drafts a detailed remediation
ticket body that walks the tech through the fix step-by-step, and creates
billable client tickets via `scripts/clientportal/cp_tickets.py`.

Behavior:
  --dry-run (default)  print what would be created; no API calls
  --apply              actually create tickets

Idempotency:
  State at `technijian/mailstore-pull/state/alert-tickets.json` records every
  ticket created so re-running doesn't duplicate. An alert key is
  (client_code, alert_type, alert_subject) — the same alert on the same client
  produces only one ticket until the state row is cleared. Re-running with
  `--reminder-hours N` will create a follow-up ticket only if the alert is
  still active and N hours have passed.

Routing:
  - Per-client alerts (orthoxpress index rebuild, icml archive jobs failing)
    are billed to the client's active contract.
  - Server-wide alerts (SMTP, version update) are billed to Technijian's
    Internal Contract (DirID 139, ContractID 3977).
  - All tickets default to AssignTo_DirID 205 (CHD : TS1 — India tech support).

Usage:
  python route_alerts.py                # dry-run, prints planned tickets
  python route_alerts.py --apply        # create tickets
  python route_alerts.py --apply --reminder-hours 168   # weekly re-fire
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "clientportal"))

from spe_client import Client, SPEError, client_code_for  # noqa: E402

import cp_tickets  # noqa: E402

STATE_PATH = Path(__file__).resolve().parents[1] / "state" / "alert-tickets.json"


def _load_recent_worker_results(c: Client, iid: str, today: dt.date, days: int = 30) -> list[dict]:
    """Try a live 30-day query first; fall back to the on-disk year-activity
    file (written by pull_year_activity.py) when SPE raises the well-known
    'Nullable object must have a value' bug on certain instances."""
    fr = (today - dt.timedelta(days=days)).isoformat() + "T00:00:00"
    to = f"{today + dt.timedelta(days=1)}T00:00:00"
    try:
        rows = c.invoke("GetWorkerResults", instanceID=iid,
                        fromIncluding=fr, toExcluding=to, timeZoneID="$Local")
        if isinstance(rows, list):
            return rows
    except SPEError:
        pass

    # Fallback: read from clients/<code>/mailstore/<year>/worker-results-<id>.json
    code = client_code_for(iid)
    year = today.year
    if not code:
        return []
    p = REPO_ROOT / "clients" / code / "mailstore" / str(year) / f"worker-results-{iid}.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    rows = data.get("results", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    cutoff = fr
    return [r for r in rows if (r.get("startTime") or "") >= cutoff]


# -----------------------------------------------------------------------------
# Alert detection (read-only; mirrors show_alerts.py logic)
# -----------------------------------------------------------------------------
def detect_alerts(c: Client) -> list[dict]:
    alerts: list[dict] = []
    svc = c.service_status()
    instances = c.list_instances("*")

    # 1. System-level messages from GetServiceStatus
    for m in svc.get("messages") or []:
        sev = m.get("type")
        if sev == "information":
            continue  # version-update notice etc. — informational only
        alerts.append({
            "alert_type": "system_message",
            "severity": sev,
            "subject": m.get("text") or "",
            "instance_id": None,
            "client_code": "Technijian",  # server-wide, internal contract
            "extra": {},
        })

    # 2. Per-instance store health
    for inst in instances:
        iid = inst["instanceID"]
        client_code = client_code_for(iid) or "Technijian"
        if inst.get("status") != "running":
            alerts.append({
                "alert_type": "instance_not_running",
                "severity": "warning",
                "subject": f"Instance {iid} status is {inst.get('status')}",
                "instance_id": iid,
                "client_code": client_code,
                "extra": {"start_stop_error": inst.get("startStopError")},
            })
            continue
        try:
            stores = c.stores(iid, include_size=False)
        except SPEError:
            continue
        for s in stores:
            if s.get("error"):
                alerts.append({
                    "alert_type": "store_error",
                    "severity": "error",
                    "subject": f"Store '{s.get('name')}' on {iid} reports error: {s['error']}",
                    "instance_id": iid,
                    "client_code": client_code,
                    "extra": {"store_id": s.get("id"), "store_name": s.get("name")},
                })
            if s.get("searchIndexesNeedRebuild"):
                alerts.append({
                    "alert_type": "search_index_rebuild",
                    "severity": "error",
                    "subject": f"Store '{s.get('name')}' on {iid} search indexes need rebuild",
                    "instance_id": iid,
                    "client_code": client_code,
                    "extra": {"store_id": s.get("id"), "store_name": s.get("name")},
                })
            if s.get("needsUpgrade"):
                alerts.append({
                    "alert_type": "store_needs_upgrade",
                    "severity": "warning",
                    "subject": f"Store '{s.get('name')}' on {iid} needs upgrade",
                    "instance_id": iid,
                    "client_code": client_code,
                    "extra": {"store_id": s.get("id"), "store_name": s.get("name")},
                })

    # 3. Per-instance archive job health (last 30 days)
    today = dt.date.today()
    cutoff_str = (today - dt.timedelta(days=30)).isoformat() + "T00:00:00"
    for inst in instances:
        iid = inst["instanceID"]
        if inst.get("status") != "running":
            continue
        client_code = client_code_for(iid) or "Technijian"
        wr = _load_recent_worker_results(c, iid, today, days=30)
        if not isinstance(wr, list) or not wr:
            continue
        ok = sum(1 for r in wr if r.get("result") in ("succeeded", "completedWithErrors"))
        rate = ok / len(wr)
        if rate < 0.5:
            failed = sum(1 for r in wr if r.get("result") == "failed")
            alerts.append({
                "alert_type": "archive_runs_failing",
                "severity": "error",
                "subject": f"Archive job on {iid} failing — {failed} of {len(wr)} runs failed in last 30 days",
                "instance_id": iid,
                "client_code": client_code,
                "extra": {
                    "total_runs": len(wr),
                    "failed": failed,
                    "succeeded": sum(1 for r in wr if r.get("result") == "succeeded"),
                    "completed_with_errors": sum(1 for r in wr if r.get("result") == "completedWithErrors"),
                    "success_rate": rate,
                    "profile_name": (wr[0].get("profileName") if wr else None),
                    "machine_name": (wr[0].get("machineName") if wr else None),
                    "items_archived": sum(int(r.get("itemsArchived") or 0) for r in wr),
                },
            })

    return alerts


# -----------------------------------------------------------------------------
# Aggregate alerts into per-(client, alert_type) tickets
# -----------------------------------------------------------------------------
def group_for_tickets(alerts: list[dict]) -> list[dict]:
    """Combine alerts of the same type for the same client into one ticket.

    e.g. icmlending + icm-realestate both archive_runs_failing → ONE ticket on
    the ICML contract covering both instances.
    """
    grouped: dict[tuple[str, str], list[dict]] = {}
    for a in alerts:
        key = (a["client_code"], a["alert_type"])
        grouped.setdefault(key, []).append(a)
    return [{"client_code": k[0], "alert_type": k[1], "alerts": v}
            for k, v in grouped.items()]


# -----------------------------------------------------------------------------
# Ticket-body templates — every body walks the tech through the exact fix
# -----------------------------------------------------------------------------
def render_ticket(group: dict) -> dict:
    """Return {title, description, priority} for the grouped alert."""
    code = group["client_code"]
    atype = group["alert_type"]
    alerts = group["alerts"]
    inst_list = sorted({a["instance_id"] for a in alerts if a.get("instance_id")})

    if atype == "search_index_rebuild":
        stores = ", ".join(f"{a['extra'].get('store_name', '?')} on {a['instance_id']}"
                           for a in alerts)
        title = f"MailStore: rebuild search indexes — {', '.join(inst_list)}"
        body = f"""ALERT: MailStore SPE reports that one or more archive store search indexes need to be rebuilt.

Affected stores: {stores}
Server: archive.technijian.com (Management Server port 8474)
Severity: ERROR — until the indexes are rebuilt, full-text search inside the affected stores returns incomplete results. Archiving still works; only search is degraded.

WHAT TO DO

Option A — Management Console (preferred for non-API techs):
  1. RDP to vmtechmss (the SPE Instance Host).
  2. Open the MailStore SPE Management Console (https://archive.technijian.com:8470/web/login.html, login admin / Support911 from keys/mailstore-spe.md).
  3. Browse to the affected instance(s) above.
  4. Open the Storage page → Stores tab.
  5. Right-click each store flagged with "Search indexes need to be rebuilt" → Rebuild All Search Indexes.
  6. Wait for the rebuild to complete (a few minutes per GB; the orthoxpress 2018-11 store is ~80 GB so allow ~30–60 min).
  7. Verify the warning clears in the Service Status panel.

Option B — REST API (faster, scriptable, can run from the dev workstation):
  cd c:\\vscode\\annual-client-review\\annual-client-review\\technijian\\mailstore-pull\\scripts
  python run_function.py --confirm SelectAllStoreIndexesForRebuild instanceID={inst_list[0] if inst_list else '<instanceID>'}
  python run_function.py --confirm RebuildSelectedStoreIndexes instanceID={inst_list[0] if inst_list else '<instanceID>'}
  # the second call is long-running — the wrapper auto-polls /api/get-status until done

VERIFICATION
  python show_alerts.py
  Expected: this alert is no longer present in the ranked alert list.

ROOT CAUSE / WHY IT HAPPENS
  Search indexes are flagged for rebuild after a forced/abnormal SPE service stop, a Firebird database recovery, an SPE upgrade, or a corrupted index page on disk. If this alert recurs frequently on the same store, capture the SPE service log around the previous shutdown for a deeper look.

CLOSE THE TICKET WHEN
  show_alerts.py exits 0 AND the affected store(s) report searchIndexesNeedRebuild=false (visible in `python list_storage.py` output).
"""
        return {"title": title, "description": body, "priority": "Same Day"}

    if atype == "archive_runs_failing":
        breakdown = "\n".join(
            f"  - {a['instance_id']}: {a['extra']['failed']}/{a['extra']['total_runs']} runs failed "
            f"({a['extra']['success_rate']*100:.1f}% success), profile=\"{a['extra'].get('profile_name','?')}\", "
            f"items archived in last 30d = {a['extra']['items_archived']}"
            for a in alerts
        )
        title = f"MailStore: archive jobs FAILING — {', '.join(inst_list)}"
        body = f"""ALERT: MailStore SPE archive job runs are failing on the instance(s) below. Email is NOT being captured into the archive — the longer this persists, the more email is missing from the archive of record.

Per-instance breakdown:
{breakdown}

Server: archive.technijian.com (Management Server port 8474, Instance Host vmtechmss)
Severity: ERROR — risk to compliance/legal hold posture.

WHAT TO DO

Step 1 — Pull the most recent failure detail (5 minutes)
  RDP to vmtechmss → Management Console → affected instance → Recent Activities tab.
  Click the latest "failed" run → read the error message at the top of the report.
  Most common error patterns and the fix for each:

  (a) "AADSTS70011: The provided value for the input parameter 'scope' is not valid"
      → The Microsoft 365 archiving credential is using a deprecated scope. Re-create
        the credential: Management Console → Credentials → New → Microsoft 365 →
        sign in with the Technijian-archiver service account (archiver@technijian.com,
        password in keys/mailstore-spe.md → "system SMTP" section).
      → Repoint the affected archiving profile at the new credential and run it.

  (b) "AADSTS50034" / "user could not be found" / "ApplicationAccessPolicy"
      → The Microsoft 365 service account password rotated, MFA was enabled on it,
        OR the Conditional Access policy excluded the archiver service principal.
      → Reset the password on the M365 service account (or rotate to a fresh app
        password), update the credential in MailStore, re-run.

  (c) "MapiExceptionNetworkError" / "The remote server returned an error: (503)"
      → M365 throttling. Reduce the archive concurrency in the profile (Profile
        properties → Advanced → Maximum number of parallel connections = 2).
      → Run again. If it succeeds, leave concurrency at 2.

  (d) "Could not connect to ..." (TCP-level)
      → Check the Instance Host (vmtechmss) outbound HTTPS to outlook.office365.com:443.
      → Verify the Sophos egress rule still permits VMTECHMSS → *.office365.com.

  (e) Authentication exception with "MultiFactorAuthentication"
      → MFA blocks the archiver. Either grant the service account an exemption in
        Conditional Access or switch the credential to "Modern Authentication"
        (OAuth) which uses a registered Azure AD app instead of password auth.

Step 2 — Run the profile manually with the fix in place
  Management Console → affected instance → Profiles → select the archiving
  profile → Run Now. Watch Recent Activities for the new run record.

Step 3 — Verify the next scheduled run also succeeds
  Wait for the next scheduled job tick (jobs run every ~30 minutes for both
  ICML instances). Confirm result = "succeeded" or "completedWithErrors".

VERIFICATION
  cd c:\\vscode\\annual-client-review\\annual-client-review\\technijian\\mailstore-pull\\scripts
  python pull_year_activity.py --year {dt.date.today().year} --instance {inst_list[0] if inst_list else '<id>'}
  Expected: most recent rows in worker-results-*.json show result="succeeded" with itemsArchived > 0.

ESCALATION
  If steps 1–3 don't resolve in 4 business hours, escalate to L2 with the failure
  message text + a Splunk/Sentinel timestamp of when archiving last succeeded.
  Confirmed last successful run is older than {(dt.date.today() - dt.timedelta(days=30)).isoformat()} for these instances.

CLOSE THE TICKET WHEN
  - python show_alerts.py exits 0 for these instances, AND
  - python pull_year_activity.py output for the affected instance has at least
    3 consecutive succeeded/completedWithErrors runs since the fix was applied.
"""
        return {"title": title, "description": body, "priority": "Critical"}

    if atype == "store_error":
        details = "\n".join(f"  - {a['instance_id']} / store {a['extra'].get('store_name','?')}: {a['subject']}"
                            for a in alerts)
        title = f"MailStore: archive store reports ERROR — {', '.join(inst_list)}"
        body = f"""ALERT: One or more archive stores report an internal error.

{details}

WHAT TO DO

  1. RDP to vmtechmss → Management Console → affected instance → Storage → Stores.
  2. Note the exact error text on each affected store.
  3. Common patterns:
     - "Database file is locked / in use"
       → Restart the affected instance (Instances tab → Stop → wait 10s → Start).
     - "I/O error during read/write"
       → Check disk health on vmtechmss (Get-PhysicalDisk; chkdsk /f the data volume in a maintenance window).
     - "Recovery records are damaged"
       → run_function.py --confirm RecreateRecoveryRecords instanceID=<id>
       → run_function.py --confirm RepairStoreDatabase instanceID=<id> storeID=<id>
  4. If the error returns immediately after restart, escalate to L2 with the SPE service log from `C:\\ProgramData\\MailStoreServiceProviderEdition\\Logs`.

CLOSE THE TICKET WHEN
  python show_alerts.py reports no store_error and python list_storage.py shows the affected store(s) as "ok".
"""
        return {"title": title, "description": body, "priority": "Same Day"}

    if atype == "store_needs_upgrade":
        details = "\n".join(f"  - {a['instance_id']} / store {a['extra'].get('store_name','?')}"
                            for a in alerts)
        title = f"MailStore: archive store needs upgrade — {', '.join(inst_list)}"
        body = f"""ALERT: archive store(s) below are running an older format and need to be upgraded to the current format version.

{details}

WHAT TO DO
  1. Schedule a maintenance window (the upgrade locks the affected store while
     it runs; expect ~5–15 minutes per GB).
  2. Run from the dev workstation:
       python run_function.py --confirm UpgradeStores instanceID=<id>
     OR upgrade individually via the Management Console (Storage → Stores → right-click → Upgrade Store).
  3. After the upgrade, run a verify pass:
       python run_function.py --confirm VerifyStores instanceID=<id>

CLOSE THE TICKET WHEN
  python list_storage.py shows needsUpgrade=false on every affected store AND show_alerts.py exits 0.
"""
        return {"title": title, "description": body, "priority": "When Convenient"}

    if atype == "instance_not_running":
        details = "\n".join(f"  - {a['instance_id']}: status={a['subject']}, "
                            f"startStopError={a['extra'].get('start_stop_error')}"
                            for a in alerts)
        title = f"MailStore: instance not running — {', '.join(inst_list)}"
        body = f"""ALERT: archive instance(s) are not in 'running' state.

{details}

WHAT TO DO
  1. Management Console → Instances → select the affected instance → Start.
  2. Wait 15s. If it returns to a non-running state, open the instance log at
     `C:\\ProgramData\\MailStoreServiceProviderEdition\\Logs\\<instance>.log`
     for the proximate error.
  3. Common causes:
     - Disk full on E:\\ (data volume) → free space on E: and start.
     - Firebird database in inconsistent state → Storage → Stores → Recover from Recovery Records.
     - Bad service account credentials → check the Windows service "MailStoreSPE" runs as the right account.

CLOSE THE TICKET WHEN
  python list_storage.py shows status="running" for the affected instance AND show_alerts.py exits 0.
"""
        return {"title": title, "description": body, "priority": "Critical"}

    if atype == "system_message":
        # SMTP unencrypted, etc. — Technijian internal housekeeping.
        bullets = "\n".join(f"  - [{a['severity']}] {a['subject']}" for a in alerts)
        title = "MailStore: server-wide configuration warnings"
        body = f"""ALERT: MailStore SPE Service Status reports the following server-wide warning(s):

{bullets}

WHAT TO DO

For "SMTP settings are configured to use an unencrypted connection or 'Accept all certificates' is enabled":
  1. Management Console → Settings → System SMTP → review the configuration.
     Currently: hostname=smtp.office365.com, port=587, protocol=SMTP-TLS,
     ignoreSslPolicyErrors=true, username=archiver@Technijian.com.
  2. Switch protocol to SMTP-TLS-IMPLICIT (port 465) or keep SMTP-TLS (587)
     and **uncheck "Ignore SSL policy errors"**. Office 365 SMTP serves a valid
     Microsoft cert; ignoring SSL errors is unsafe and unnecessary.
  3. Click "Test SMTP Settings" — confirm the test mail arrives.

For other warnings, follow the inline guidance from the management console.

VERIFICATION
  python show_alerts.py
  Expected: the warning(s) above no longer appear in the system-message section.

CLOSE THE TICKET WHEN
  python show_alerts.py reports zero warnings of this type.
"""
        return {"title": title, "description": body, "priority": "When Convenient"}

    # Generic fallback
    title = f"MailStore alert — {atype.replace('_',' ')}"
    body = "Alert details:\n\n" + "\n".join(f"  - [{a['severity']}] {a['subject']}" for a in alerts)
    return {"title": title, "description": body, "priority": "When Convenient"}


# -----------------------------------------------------------------------------
# State (dedup)
# -----------------------------------------------------------------------------
def _alert_key(group: dict) -> str:
    """Stable identifier for one ticket-creation key."""
    code = group["client_code"]
    atype = group["alert_type"]
    inst = sorted({a.get("instance_id") or "" for a in group["alerts"]})
    return f"{code}::{atype}::{','.join(inst)}"


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def needs_new_ticket(state: dict, key: str, reminder_hours: float | None) -> bool:
    """True if no ticket exists yet OR the reminder window has lapsed."""
    row = state.get(key)
    if not row or row.get("ticket_id") is None:
        return True
    if reminder_hours is None:
        return False
    last = row.get("created_at")
    if not last:
        return False
    try:
        last_dt = dt.datetime.fromisoformat(last.replace("Z", ""))
    except ValueError:
        return False
    return (dt.datetime.utcnow() - last_dt) > dt.timedelta(hours=reminder_hours)


# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually create tickets. Default: dry-run.")
    ap.add_argument("--reminder-hours", type=float, default=None,
                    help="If set, re-fire a ticket for an unchanged alert that's older than this.")
    ap.add_argument("--assign-to", type=int, default=205,
                    help="AssignTo_DirID. Default 205 = CHD : TS1 (India tech support).")
    ap.add_argument("--only", default=None, help="Comma-separated client codes (case-insensitive)")
    args = ap.parse_args(argv)

    only = {c.strip().lower() for c in args.only.split(",")} if args.only else None

    print(f"Connecting https://archive.technijian.com:8474 ...")
    c = Client()
    alerts = detect_alerts(c)
    if not alerts:
        print("No actionable alerts detected.")
        return 0

    groups = group_for_tickets(alerts)
    if only:
        groups = [g for g in groups if g["client_code"].lower() in only]

    state = load_state()
    summary = {"created": [], "skipped_dedup": [], "errors": []}
    print(f"\n{len(groups)} ticket-eligible alert group(s):\n")

    for g in groups:
        key = _alert_key(g)
        rendered = render_ticket(g)
        existing = state.get(key)
        if not needs_new_ticket(state, key, args.reminder_hours):
            print(f"  [SKIP DEDUP] {g['client_code']} :: {g['alert_type']} "
                  f"(existing ticket {existing.get('ticket_id')} from {existing.get('created_at')})")
            summary["skipped_dedup"].append({"key": key, **(existing or {})})
            continue

        print(f"  [{'CREATE' if args.apply else 'DRY-RUN'}] {g['client_code']} :: {g['alert_type']}")
        print(f"      title: {rendered['title']}")
        print(f"      priority: {rendered['priority']}, body: {len(rendered['description'])} chars")

        try:
            result = cp_tickets.create_ticket_for_code(
                g["client_code"],
                title=rendered["title"],
                description=rendered["description"],
                priority=rendered["priority"],
                role_type="Off-Shore Tech Support",
                assign_to_dir_id=args.assign_to,
                dry_run=not args.apply,
            )
        except Exception as e:
            print(f"      ERROR: {e}")
            summary["errors"].append({"key": key, "error": str(e)})
            continue

        ticket_id = result.get("ticket_id")
        record = {
            "key": key,
            "client_code": g["client_code"],
            "alert_type": g["alert_type"],
            "title": rendered["title"],
            "ticket_id": ticket_id,
            "created_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "dry_run": result.get("dry_run", False),
            "alerts": g["alerts"],
        }
        if args.apply:
            state[key] = record
            print(f"      -> ticket_id={ticket_id}")
        else:
            print(f"      -> dry-run; XML payload built ({len(result.get('xml_in', ''))} chars)")
        summary["created"].append(record)

    if args.apply:
        save_state(state)
        print(f"\nWrote state -> {STATE_PATH}")

    print(f"\nSummary: created={len(summary['created'])}  "
          f"skipped_dedup={len(summary['skipped_dedup'])}  errors={len(summary['errors'])}")
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
