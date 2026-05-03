"""List MailStore SPE users with mailbox sizes.

For every running instance (or a chosen one), prints a table of users with:
  - userName
  - fullName
  - email addresses
  - authentication method
  - MFA status
  - approx mailbox size (sum of folder_stats rows whose folder name starts with the username)
  - approx message count

Mailbox size approximation: GetFolderStatistics returns one row per folder.
The first path segment of `folderName` is the user's archive root, e.g.
`alice@orthoxpress.com/Inbox`. We sum all folders whose first segment matches
each user.

Usage:
  python list_users.py                       # all running instances
  python list_users.py --instance icmlending
  python list_users.py --csv users.csv       # also write CSV
"""
from __future__ import annotations

import argparse
import csv
import sys

from spe_client import Client, SPEError, fmt_bytes


def index_folder_sizes(folder_stats: list[dict]) -> dict[str, tuple[int, int]]:
    """Return {firstSegment: (total_bytes, total_messages)}."""
    roll: dict[str, tuple[int, int]] = {}
    for f in folder_stats:
        name = f.get("folderName") or f.get("name") or ""
        if not name:
            continue
        root = name.split("/", 1)[0].lower()
        sz = f.get("size") or f.get("totalSize") or 0
        ct = f.get("count") or f.get("messageCount") or 0
        cur_sz, cur_ct = roll.get(root, (0, 0))
        roll[root] = (cur_sz + (sz or 0), cur_ct + (ct or 0))
    return roll


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", action="append", default=None)
    ap.add_argument("--csv", default=None, help="Optional CSV output path.")
    args = ap.parse_args(argv)

    c = Client()
    instances = [i for i in c.list_instances("*") if i.get("status") == "running"]
    if args.instance:
        instances = [i for i in instances if i["instanceID"] in args.instance]
    if not instances:
        print("No instances matched.", file=sys.stderr)
        return 1

    rows = []
    for inst in instances:
        iid = inst["instanceID"]
        print(f"\n=== {iid} ===")
        try:
            users = c.users(iid)
            fstats = c.folder_statistics(iid)
        except SPEError as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            continue
        sizes = index_folder_sizes(fstats)
        print(f"  {len(users)} user(s)\n")
        print(f"  {'userName':30s} {'fullName':30s} {'auth':12s} {'mfa':10s} {'mailbox':>14s} {'msgs':>10s}  emails")
        print(f"  {'-'*30} {'-'*30} {'-'*12} {'-'*10} {'-'*14} {'-'*10}  ------")
        for u in sorted(users, key=lambda x: (x.get("userName") or "").lower()):
            uname = u.get("userName") or ""
            try:
                info = c.user_info(iid, uname)
            except SPEError:
                info = {}
            emails = ", ".join((info.get("emailAddresses") or []))
            sz, ct = sizes.get(uname.lower(), (0, 0))
            row = {
                "instance": iid,
                "userName": uname,
                "fullName": info.get("fullName") or u.get("fullName") or "",
                "authentication": (info.get("authentication") or {}).get("type") or info.get("authentication") or "",
                "mfa": info.get("mfaStatus") or u.get("mfaStatus") or "",
                "mailbox_bytes": sz,
                "messages": ct,
                "emails": emails,
            }
            rows.append(row)
            print(f"  {row['userName'][:30]:30s} {(row['fullName'] or '')[:30]:30s} "
                  f"{str(row['authentication'])[:12]:12s} {str(row['mfa'])[:10]:10s} "
                  f"{fmt_bytes(sz):>14s} {ct:>10d}  {emails[:80]}")

    if args.csv and rows:
        from pathlib import Path
        p = Path(args.csv)
        with p.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nWrote {len(rows)} row(s) to {p}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
