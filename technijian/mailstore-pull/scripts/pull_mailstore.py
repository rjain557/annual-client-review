"""Pull a full MailStore SPE snapshot for every running instance.

Walks every running instance on archive.technijian.com and writes per-client JSON
to clients/<code>/mailstore/<YYYY-MM-DD>/snapshot-<instance-id>.json.

Snapshot contains:
  env             — server version, licensee, hardware
  service_status  — system-wide message feed (alerts)
  instance        — instanceID, host, status, processID
  statistics      — totalSizeMB / messages / database / content / index
  live_stats      — current CPU/RAM of the instance worker
  stores          — per-store size, path, recovery state, index health
  users           — user list with full GetUserInfo (emails, privileges, MFA)
  folder_stats    — per-folder size + message count (= per-mailbox usage)
  jobs            — scheduled API jobs
  profiles        — archiving + export profiles
  configuration   — instance config, index config, compliance, directory services
  credentials     — stored archiving credentials (M365/IMAP/...)

Usage:
    python pull_mailstore.py                  # all running instances
    python pull_mailstore.py --instance icmlending
    python pull_mailstore.py --no-folder-stats   # skip per-folder breakdown
    python pull_mailstore.py --out C:/snaps      # custom output root
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from spe_client import Client, SPEError, client_code_for, fmt_mb


def pull_one(c: Client, inst: dict, *, with_folders: bool, with_users_detail: bool) -> dict:
    iid = inst["instanceID"]
    print(f"  [{iid}] statistics ... ", end="", flush=True)
    stats = safe(lambda: c.instance_statistics(iid), {})
    print(f"{stats.get('totalSizeMB','?')} MB / {stats.get('numberOfMessages','?')} msgs")

    print(f"  [{iid}] live_stats ... ", end="", flush=True)
    live = safe(lambda: c.instance_live(iid), {})
    print("ok" if live else "skipped")

    print(f"  [{iid}] stores ... ", end="", flush=True)
    stores = safe(lambda: c.stores(iid, include_size=True), [])
    print(f"{len(stores)} store(s)")

    print(f"  [{iid}] users ... ", end="", flush=True)
    users = safe(lambda: c.users(iid), [])
    print(f"{len(users)} user(s)")

    user_info: dict[str, dict] = {}
    if with_users_detail:
        for u in users:
            uname = u.get("userName")
            if not uname:
                continue
            try:
                user_info[uname] = c.user_info(iid, uname)
            except SPEError as e:
                user_info[uname] = {"_error": str(e)}

    folder_stats = []
    if with_folders:
        print(f"  [{iid}] folder_stats ... ", end="", flush=True)
        folder_stats = safe(lambda: c.folder_statistics(iid), [])
        print(f"{len(folder_stats)} folder(s)")

    print(f"  [{iid}] jobs/profiles/config ... ", end="", flush=True)
    jobs = safe(lambda: c.jobs(iid), [])
    profiles = safe(lambda: c.profiles(iid, raw=False), [])
    creds = safe(lambda: c.credentials_list(iid), [])
    cfg = {
        "instance": safe(lambda: c.instance_configuration(iid), {}),
        "index": safe(lambda: c.index_config(iid), {}),
        "compliance": safe(lambda: c.compliance_config(iid), {}),
        "directory_services": safe(lambda: c.directory_services_config(iid), {}),
    }
    print("ok")

    return {
        "instance": inst,
        "statistics": stats,
        "live_stats": live,
        "stores": stores,
        "users": users,
        "user_info": user_info,
        "folder_stats": folder_stats,
        "jobs": jobs,
        "profiles": profiles,
        "credentials": creds,
        "configuration": cfg,
    }


def safe(fn, default):
    try:
        return fn()
    except SPEError as e:
        print(f"WARN: {e}", file=sys.stderr)
        return default


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[3]
    default_out = repo_root / "clients"

    ap = argparse.ArgumentParser(description="Pull a full MailStore SPE snapshot per instance.")
    ap.add_argument("--instance", action="append", default=None,
                    help="Pull only the named instance (repeat to pick several). Default: all running.")
    ap.add_argument("--no-folder-stats", action="store_true", help="Skip per-folder mailbox size breakdown.")
    ap.add_argument("--no-user-detail", action="store_true", help="Skip per-user GetUserInfo expansion.")
    ap.add_argument("--out", default=str(default_out),
                    help=f"Output root (default: {default_out}). Per-client folder is created underneath.")
    ap.add_argument("--date", default=None, help="Override snapshot date (YYYY-MM-DD).")
    args = ap.parse_args(argv)

    out_root = Path(args.out)
    snap_date = args.date or dt.date.today().isoformat()

    c = Client()
    print(f"Connecting {c.base_url} ...")
    env = c.env_info()
    print(f"  SPE {env.get('version')} on {env.get('serverName')} (licensee: {env.get('licenseeName')})")

    svc = c.service_status()
    msg_counts = {}
    for m in svc.get("messages", []) or []:
        msg_counts[m["type"]] = msg_counts.get(m["type"], 0) + 1
    print(f"  service messages: {msg_counts}")

    instances = c.list_instances("*")
    running = [i for i in instances if i.get("status") == "running"]
    if args.instance:
        running = [i for i in running if i["instanceID"] in args.instance]

    if not running:
        print("No running instances matched.", file=sys.stderr)
        return 1

    print(f"\nPulling {len(running)} instance(s) for snapshot date {snap_date}\n")
    written = []
    for inst in running:
        iid = inst["instanceID"]
        code = client_code_for(iid) or iid.replace("-", "_")
        out_dir = out_root / code / "mailstore" / snap_date
        out_dir.mkdir(parents=True, exist_ok=True)
        snap = {
            "snapshot_date": snap_date,
            "pulled_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "env": env,
            "service_status": svc,
            "client_code": code,
            **pull_one(c, inst,
                       with_folders=not args.no_folder_stats,
                       with_users_detail=not args.no_user_detail),
        }
        out_path = out_dir / f"snapshot-{iid}.json"
        out_path.write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
        sz = snap["statistics"].get("totalSizeMB")
        nm = snap["statistics"].get("numberOfMessages")
        print(f"  -> {out_path}  ({fmt_mb(sz)} / {nm} msgs / {len(snap['users'])} users)\n")
        written.append(out_path)

    print(f"Done. Wrote {len(written)} snapshot(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
