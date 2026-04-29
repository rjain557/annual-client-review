#!/usr/bin/env python3
"""
pull_teramind_daily.py - Daily Teramind compliance snapshot.

Pulls the last 24 h (or custom window) of activity data from the on-premise
Teramind server and writes per-day snapshots to:

  technijian/teramind-pull/YYYY-MM-DD/
    account.json
    agents.json + agents.csv
    computers.json
    departments.json
    behavior_groups.json
    behavior_policies.json
    run_log.json

  technijian/teramind-pull/state/YYYY-MM-DD.json   (same as run_log)

  Per-cube activity summaries (account-wide):
    activity.json, sessions.json, alerts.json, file_transfers.json,
    keystrokes.json, emails.json, searches.json, cli.json, printing.json

  Per-agent insider-threat data:
    risk_scores.json        [{agent_id, email, score, percentile}]
    agent_details.json
    last_devices.json

Usage
-----
  # Default - last 24 h
  python technijian/teramind-pull/scripts/pull_teramind_daily.py

  # Custom lookback
  python ... --hours 48

  # Dry run (no API calls, just print plan)
  python ... --dry-run

  # Specific pull date (anchors window end to 09:00 UTC of that date)
  python ... --date 2026-04-28
"""

import argparse
import csv
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).parent))

import teramind_api


# ── helpers ──────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


def compute_window(run_at, hours=24):
    """Return (start_ts, end_ts) as Unix seconds."""
    end_ts = int(run_at.timestamp())
    start_ts = end_ts - int(hours * 3600)
    return start_ts, end_ts


def ts_iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def write_csv(path, rows, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ── per-cube pull ─────────────────────────────────────────────────────────────

def pull_cube(client, cube, start_ts, end_ts, dry_run):
    if dry_run:
        return {"cube": cube, "count": 0, "dry_run": True}
    try:
        rows = client.query_cube_all(cube, start_ts, end_ts)
        return {"cube": cube, "rows": rows, "count": len(rows), "error": None}
    except Exception as exc:
        return {"cube": cube, "rows": [], "count": 0, "error": str(exc)}


# ── per-agent insider-threat pull ─────────────────────────────────────────────

def pull_agent_risk(client, agent, start_ts, end_ts, dry_run):
    agent_id = agent["agent_id"]
    result = {
        "agent_id": agent_id,
        "email":    agent.get("email", ""),
        "department_id": agent.get("department_id"),
    }
    if dry_run:
        result.update({"score": None, "percentile": None, "dry_run": True})
        return result
    try:
        rs = client.get_risk_score(agent_id, start_ts, end_ts)
        result.update({
            "score":      rs.get("score", 0),
            "percentile": rs.get("percentile", 0),
        })
    except Exception as exc:
        result.update({"score": None, "percentile": None, "error": str(exc)})
    return result


def pull_agent_details(client, agent_id, start_ts, end_ts, dry_run):
    if dry_run:
        return {"agent_id": agent_id, "dry_run": True}
    try:
        return client.get_agent_details(agent_id, start_ts, end_ts)
    except Exception as exc:
        return {"agent_id": agent_id, "error": str(exc)}


def pull_agent_devices(client, agent_id, start_ts, end_ts, dry_run):
    if dry_run:
        return {"agent_id": agent_id, "dry_run": True}
    try:
        return client.get_last_devices(agent_id, start_ts, end_ts)
    except Exception as exc:
        return {"agent_id": agent_id, "error": str(exc)}


# ── main orchestrator ─────────────────────────────────────────────────────────

def run(args):
    run_at = _now()
    if args.date:
        anchor = datetime.strptime(args.date, "%Y-%m-%d").replace(
            hour=9, minute=0, second=0, tzinfo=timezone.utc
        )
        start_ts, end_ts = compute_window(anchor, hours=args.hours)
    else:
        start_ts, end_ts = compute_window(run_at, hours=args.hours)

    date_str = datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    out_dir  = REPO_ROOT / "technijian" / "teramind-pull" / date_str
    state_dir = REPO_ROOT / "technijian" / "teramind-pull" / "state"

    print(f"Teramind daily pull")
    print(f"  Window : {ts_iso(start_ts)} -> {ts_iso(end_ts)}")
    print(f"  Output : {out_dir}")
    print(f"  Dry run: {args.dry_run}")
    print()

    if args.dry_run:
        print("[dry-run] Would pull account, agents, computers, departments,")
        print("  behavior groups/policies, activity cubes, per-agent risk scores.")
        return

    client = teramind_api.TeramindClient()
    errors = []

    # ── account ──────────────────────────────────────────────────────────────
    print("Pulling account info...")
    account = client.get_account()
    write_json(out_dir / "account.json", account)

    # ── agents ───────────────────────────────────────────────────────────────
    print("Pulling agents...")
    agents_all = client.list_agents(include_deleted=False)
    write_json(out_dir / "agents.json", agents_all)

    agent_csv_fields = ["agent_id", "email", "email_address", "first_name",
                        "last_name", "department_id", "role", "deleted",
                        "last_web_login", "tracking_profile_id"]
    write_csv(out_dir / "agents.csv", agents_all, agent_csv_fields)
    print(f"  {len(agents_all)} active agent(s)")

    # ── computers ────────────────────────────────────────────────────────────
    print("Pulling computers...")
    computers = client.list_computers(include_deleted=False)
    write_json(out_dir / "computers.json", computers)

    computer_csv_fields = ["computer_id", "name", "fqdn", "os", "ip",
                           "client_mode", "pinged_at", "is_monitored", "is_deleted"]
    write_csv(out_dir / "computers.csv", computers, computer_csv_fields)
    print(f"  {len(computers)} active computer(s)")

    # ── departments ──────────────────────────────────────────────────────────
    print("Pulling departments...")
    departments = client.list_departments()
    write_json(out_dir / "departments.json", departments)

    # ── DLP / behavior ───────────────────────────────────────────────────────
    print("Pulling behavior groups + policies...")
    bgroups   = client.list_behavior_groups()
    bpolicies = client.list_behavior_policies()
    write_json(out_dir / "behavior_groups.json", bgroups)
    write_json(out_dir / "behavior_policies.json", bpolicies)

    # ── activity cubes ────────────────────────────────────────────────────────
    print("Pulling activity cubes...")
    cube_results = {}
    for cube in teramind_api.TeramindClient.CUBE_NAMES:
        print(f"  {cube}...")
        r = pull_cube(client, cube, start_ts, end_ts, dry_run=False)
        cube_results[cube] = r
        write_json(out_dir / f"{cube}.json", r)
        count = r.get("count", 0)
        err   = r.get("error")
        print(f"    => {count} row(s)" + (f"  [ERROR: {err}]" if err else ""))
        if err:
            errors.append({"cube": cube, "error": err})

    # ── per-agent risk scores ─────────────────────────────────────────────────
    print("Pulling per-agent risk scores...")
    risk_scores = []
    agent_details_all = []
    agent_devices_all = []
    for agent in agents_all:
        rs = pull_agent_risk(client, agent, start_ts, end_ts, dry_run=False)
        risk_scores.append(rs)
        if rs.get("error"):
            errors.append({"agent_id": agent["agent_id"], "risk_score_error": rs["error"]})

        details = pull_agent_details(client, agent["agent_id"], start_ts, end_ts, False)
        agent_details_all.append({"agent_id": agent["agent_id"], "data": details})

        devices = pull_agent_devices(client, agent["agent_id"], start_ts, end_ts, False)
        agent_devices_all.append({"agent_id": agent["agent_id"], "data": devices})

    write_json(out_dir / "risk_scores.json", risk_scores)
    write_json(out_dir / "agent_details.json", agent_details_all)
    write_json(out_dir / "last_devices.json", agent_devices_all)

    high_risk = [r for r in risk_scores if (r.get("score") or 0) > 50]
    print(f"  {len(risk_scores)} agent(s) scored; {len(high_risk)} high-risk (score > 50)")

    # ── run log ──────────────────────────────────────────────────────────────
    total_activity = sum(
        cube_results.get(c, {}).get("count", 0)
        for c in teramind_api.TeramindClient.CUBE_NAMES
    )
    run_log = {
        "run_at":            run_at.isoformat(),
        "window":            {"start": ts_iso(start_ts), "end": ts_iso(end_ts)},
        "date":              date_str,
        "host":              client.host,
        "agents_active":     len(agents_all),
        "computers_active":  len(computers),
        "departments":       len(departments),
        "behavior_policies": len(bpolicies),
        "cubes_pulled":      {c: cube_results[c].get("count", 0)
                              for c in teramind_api.TeramindClient.CUBE_NAMES},
        "total_activity_rows": total_activity,
        "high_risk_agents":  len(high_risk),
        "errors":            errors,
    }
    write_json(out_dir / "run_log.json", run_log)

    state_dir.mkdir(parents=True, exist_ok=True)
    write_json(state_dir / f"{date_str}.json", run_log)

    print()
    print(f"Done. {len(agents_all)} agents, {len(computers)} computers, "
          f"{total_activity} activity rows, {len(errors)} error(s)")
    print(f"Output: {out_dir}")
    if errors:
        print("Errors:")
        for e in errors:
            print(f"  {e}")


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Teramind daily compliance pull")
    p.add_argument("--hours",    type=float, default=24,
                   help="Lookback window in hours (default 24)")
    p.add_argument("--date",     help="Anchor date YYYY-MM-DD (window ends at 09:00 UTC)")
    p.add_argument("--dry-run",  action="store_true",
                   help="Print plan without making API calls")
    args = p.parse_args()

    try:
        run(args)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
