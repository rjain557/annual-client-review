"""Backfill teams_url in the ScreenConnect audit log using Microsoft Graph.

After process_avi_dir() places MP4 files into the OneDrive FileCabinet folder
(which auto-syncs to Teams), this script queries Graph for each file's webUrl
and writes it into the audit_log.json.  Run after the files have had a few
minutes to sync, then re-run build_client_audit.py --all --no-refresh-db.

Usage:
    python populate_teams_urls.py                    # update audit log in place
    python populate_teams_urls.py --dry-run          # print plan, no writes
    python populate_teams_urls.py --client BWH       # only one client
    python populate_teams_urls.py --year 2026

Auth: same Teams-Connector app creds as upload_to_teams.py
      (keys/teams-connector.md -> env TEAMS_TENANT_ID/CLIENT_ID/SECRET).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

SCRIPTS_DIR = Path(__file__).resolve().parent
STATE_DIR   = SCRIPTS_DIR.parent / "state"
sys.path.insert(0, str(SCRIPTS_DIR))
from _sc_secrets import get_teams_credentials  # noqa: E402

GRAPH         = "https://graph.microsoft.com/v1.0"
DEST_CFG      = STATE_DIR / "teams-destination.json"
ONEDRIVE_ROOT = Path(
    r"C:\Users\rjain\OneDrive - Technijian, Inc\Technijian - My Remote - FileCabinet"
)
AUDIT_LOG     = ONEDRIVE_ROOT / "_audit" / "audit_log.json"


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def get_token() -> str:
    tenant, cid, sec = get_teams_credentials()
    body = urlencode({
        "client_id":     cid,
        "client_secret": sec,
        "scope":         "https://graph.microsoft.com/.default",
        "grant_type":    "client_credentials",
    }).encode()
    req = Request(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


def graph_get(token: str, path: str) -> dict:
    req = Request(f"{GRAPH}{path}", headers={"Authorization": f"Bearer {token}"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def resolve_channel_drive(token: str, team_id: str, channel_id: str) -> tuple[str, str]:
    info = graph_get(token, f"/teams/{team_id}/channels/{channel_id}/filesFolder")
    pr = info.get("parentReference", {})
    return pr.get("driveId", ""), info.get("id", "")


def get_item_web_url(token: str, drive_id: str, relative_path: str) -> str | None:
    """Return webUrl for a file at relative_path inside the channel drive root.

    relative_path should be like 'BWH-2026-04/20260401_BWH_abc12345_def67890.mp4'
    Returns None if the file is not found (may not be synced yet).
    """
    encoded = quote(relative_path.replace("\\", "/"), safe="/")
    try:
        item = graph_get(token, f"/drives/{drive_id}/root:/{encoded}")
        return item.get("webUrl")
    except HTTPError as e:
        if e.code == 404:
            return None
        raise


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="Print plan only")
    ap.add_argument("--client", default=None,  help="Only process this client code")
    ap.add_argument("--year",   default="2026", help="Year filter (default: 2026)")
    ap.add_argument("--audit-log", default=str(AUDIT_LOG),
                    help="Path to audit_log.json (default: state/_audit/audit_log.json)")
    args = ap.parse_args()

    audit_path = Path(args.audit_log)
    if not audit_path.exists():
        print(f"ERROR: audit log not found: {audit_path}")
        print("  Run pull_screenconnect_2026.py --from-avi-dir first.")
        return 1

    records = json.loads(audit_path.read_text(encoding="utf-8"))
    targets = [
        r for r in records
        if not r.get("teams_url")
        and r.get("mp4_path")
        and not r.get("error")
        and not r.get("skipped")
        and not r.get("dry_run")
        and (not args.client or r.get("client", "").upper() == args.client.upper())
        and r.get("year", args.year) == args.year
    ]

    if not targets:
        print("No records need teams_url population.")
        return 0

    print(f"Records to populate: {len(targets)}")

    if not DEST_CFG.exists():
        print(f"ERROR: teams-destination.json not found at {DEST_CFG}")
        return 1
    cfg = json.loads(DEST_CFG.read_text(encoding="utf-8"))
    team_id    = cfg["team_id"]
    channel_id = cfg["channel_id"]

    if args.dry_run:
        for r in targets[:10]:
            mp4 = Path(r["mp4_path"])
            relative = f"{mp4.parent.name}/{mp4.name}"
            print(f"  [DRY-RUN] {relative}")
        if len(targets) > 10:
            print(f"  ... and {len(targets) - 10} more")
        return 0

    print("Authenticating to Microsoft Graph ...")
    token = get_token()
    drive_id, _ = resolve_channel_drive(token, team_id, channel_id)
    print(f"Channel drive: {drive_id}\n")

    updated = 0
    missing = 0
    token_refresh = time.time()

    for i, r in enumerate(targets):
        # Refresh token every 40 minutes
        if time.time() - token_refresh > 2400:
            token = get_token()
            token_refresh = time.time()

        mp4 = Path(r["mp4_path"])
        # mp4 is in FileCabinet/{CLIENT}-{year}-{month}/{filename}
        # relative path inside Teams channel root is {CLIENT}-{year}-{month}/{filename}
        if ONEDRIVE_ROOT in mp4.parents:
            relative = str(mp4.relative_to(ONEDRIVE_ROOT)).replace("\\", "/")
        else:
            # Fallback: use parent folder name + filename
            relative = f"{mp4.parent.name}/{mp4.name}"

        web_url = get_item_web_url(token, drive_id, relative)
        if web_url:
            r["teams_url"] = web_url
            updated += 1
            if (i + 1) % 50 == 0 or i == 0:
                print(f"  [{i+1}/{len(targets)}] {mp4.name} -> {web_url[:80]}...")
        else:
            missing += 1
            if missing <= 5:
                print(f"  [NOT FOUND] {relative} — not synced yet?")

    if not args.dry_run and updated:
        audit_path.write_text(
            json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nUpdated audit_log.json: {updated} URLs added, {missing} not found yet.")
        print("Run build_client_audit.py --all --no-refresh-db to update per-client CSVs.")
    else:
        print(f"\n{updated} URLs found, {missing} not found yet (no changes written — dry run).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
