"""Copy generated client monthly reports into each client's MS Teams team.

For every client folder under ``clients/<slug>/`` the script:

  1. Resolves the Teams team whose ``displayName`` matches the client code
     (uppercased: AAVA, BWH, etc.). Skip with a warning if no team.
  2. Finds the "Monthly Reports" channel on that team. Skip with a warning
     if the channel is not present (we do not have Channel.Create scope —
     a tech needs to create it manually one time per team).
  3. Creates a subfolder named ``<MonthName>-<Year>`` (e.g. ``April-2026``)
     under the channel's Files folder if missing.
  4. Uploads every monthly report for that client+month into the folder
     (Meraki, Sophos, Huntress, CrowdStrike, ME EC, M365, vCenter, Veeam
     VBR, Veeam ONE, MailStore, Veeam-365). Existing files with the same
     name are replaced.

Channel-level access is NOT modified by this script — the channel is a
standard channel and inherits "all team members" permissions, which is
what the client needs.

Usage:
    python upload_monthly_reports.py --month 2026-04                 # all clients
    python upload_monthly_reports.py --month 2026-04 --only AAVA,BWH
    python upload_monthly_reports.py --month 2026-04 --dry-run       # default
    python upload_monthly_reports.py --month 2026-04 --apply         # actually upload

The script defaults to ``--dry-run`` to keep production state safe. Pass
``--apply`` explicitly when you're ready to copy files into Teams.
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import teams_api as t  # noqa: E402

REPO_ROOT = HERE.parent.parent
CLIENTS_ROOT = REPO_ROOT / "clients"

# Each entry: (label shown in summary, glob pattern relative to client folder).
# Globs use Path.glob, so they're applied with `client_dir.glob(pattern)`.
REPORT_LOCATIONS = [
    ("ME EC",        "me_ec/reports/*ME EC Patch Activity - {ym}.docx"),
    ("Huntress",     "huntress/monthly/{ym}/*Cybersecurity-Activity-{ym}.docx"),
    ("CrowdStrike",  "crowdstrike/monthly/{ym}/*CrowdStrike-Activity-{ym}.docx"),
    ("Sophos",       "sophos/monthly/{ym}/*.docx"),
    ("Meraki",       "meraki/reports/*Meraki Monthly Activity - {ym}.docx"),
    ("M365",         "m365/monthly/{ym}/*.docx"),
    ("vCenter",      "vcenter/reports/*vCenter Monthly Infrastructure - {ym}.docx"),
    ("Veeam VBR",    "veeam-vbr/reports/*Veeam VBR Monthly Backup - {ym}.docx"),
    ("Veeam ONE",    "veeam-one/reports/*Veeam ONE Monthly Health - {ym}.docx"),
    ("Veeam 365",    "veeam-365/reports/*{ym}*.docx"),
    ("MailStore",    "mailstore/reports/*{ym}*.docx"),
]

CHANNEL_NAME = "Monthly Reports"


def month_folder_name(year: int, month: int) -> str:
    """``2026-04`` -> ``April-2026``."""
    return f"{calendar.month_name[month]}-{year}"


def find_reports_for_client(client_dir: Path, year: int, month: int) -> list[tuple[str, Path]]:
    """Return [(label, path), ...] for every report this client has for the month."""
    ym = f"{year:04d}-{month:02d}"
    out: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for label, pattern in REPORT_LOCATIONS:
        for p in client_dir.glob(pattern.format(ym=ym)):
            if not p.is_file():
                continue
            key = str(p.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((label, p))
    return out


def slug_to_team_name(slug: str) -> str:
    """Convert ``aava`` to ``AAVA``. Special-cases for client teams whose
    Teams displayName differs from the lowercased slug — confirmed against
    the live tenant 2026-05-03."""
    overrides = {
        "technijian": "Technijian",
        "technijian-ind": "Tech India",
    }
    return overrides.get(slug.lower(), slug.upper())


def upload_for_client(slug: str, year: int, month: int, *, dry_run: bool) -> dict:
    client_dir = CLIENTS_ROOT / slug
    if not client_dir.exists():
        return {"slug": slug, "skipped": "no client folder"}
    reports = find_reports_for_client(client_dir, year, month)
    if not reports:
        return {"slug": slug, "skipped": "no reports for this month"}

    team_name = slug_to_team_name(slug)
    result: dict = {
        "slug": slug, "team_name": team_name,
        "report_count": len(reports), "uploaded": 0, "skipped": None, "issues": [],
    }
    if dry_run:
        result["uploaded"] = 0
        result["dry_run"] = True
        result["report_labels"] = [r[0] for r in reports]
        return result

    team = t.find_team_by_displayname(team_name)
    if team is None:
        result["skipped"] = f"team '{team_name}' not found in tenant"
        return result
    team_id = team["id"]

    channel = t.find_channel(team_id, CHANNEL_NAME)
    if channel is None:
        try:
            channel = t.create_channel(
                team_id, CHANNEL_NAME,
                description="Technijian-generated monthly monitoring reports.",
            )
            result["channel_created"] = True
        except Exception as exc:
            result["skipped"] = f"could not create '{CHANNEL_NAME}' channel: {exc}"
            return result
    channel_id = channel["id"]

    folder = t.get_channel_folder(team_id, channel_id)
    drive_id = folder["parentReference"]["driveId"]
    channel_folder_id = folder["id"]

    month_label = month_folder_name(year, month)
    month_folder = t.find_or_create_subfolder(drive_id, channel_folder_id, month_label, create=True)
    if month_folder is None:
        result["skipped"] = f"could not create month folder '{month_label}'"
        return result
    month_folder_id = month_folder["id"]

    upload_records: list[dict] = []
    for label, path in reports:
        try:
            item = t.upload_file_to_folder(drive_id, month_folder_id, path)
            result["uploaded"] += 1
            upload_records.append({
                "label": label,
                "filename": path.name,
                "web_url": item.get("webUrl"),
                "size": item.get("size"),
            })
        except Exception as exc:
            result["issues"].append(f"{label}: {exc}")

    result["month_folder_web_url"] = month_folder.get("webUrl")
    result["uploads"] = upload_records

    # Write a manifest the email skill consumes so it doesn't need to hit
    # Graph again to get the OneDrive links.
    manifest_dir = client_dir / "_monthly_report_uploads"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"{year:04d}-{month:02d}.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "team_name": team_name,
                "month": f"{year:04d}-{month:02d}",
                "month_folder": month_folder_name(year, month),
                "month_folder_web_url": month_folder.get("webUrl"),
                "uploads": upload_records,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--month", required=True, help="YYYY-MM (e.g. 2026-04)")
    ap.add_argument("--only", help="Comma-separated client slugs to include")
    ap.add_argument("--skip", help="Comma-separated client slugs to skip")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--dry-run", action="store_true", default=True,
                     help="Print what would happen, do not upload (default).")
    grp.add_argument("--apply", action="store_true",
                     help="Actually create folders and upload files.")
    args = ap.parse_args(argv)

    dry_run = not args.apply

    year, month = (int(x) for x in args.month.split("-"))
    only = {s.strip().lower() for s in (args.only or "").split(",") if s.strip()}
    skip = {s.strip().lower() for s in (args.skip or "").split(",") if s.strip()}

    print(f"== Teams upload {'DRY-RUN' if dry_run else 'APPLY'}: {args.month} ==")
    print(f"   month folder: {month_folder_name(year, month)}")
    print(f"   channel:      {CHANNEL_NAME}")
    print()

    summary: list[dict] = []
    for client_dir in sorted([d for d in CLIENTS_ROOT.iterdir() if d.is_dir() and not d.name.startswith("_")]):
        slug = client_dir.name
        if only and slug not in only:
            continue
        if slug in skip:
            continue
        try:
            r = upload_for_client(slug, year, month, dry_run=dry_run)
        except Exception as exc:
            r = {"slug": slug, "skipped": f"error: {exc}"}
        summary.append(r)
        print(f"  [{slug}] " + json.dumps({k: v for k, v in r.items() if k != "slug"}, default=str))

    print(f"\n== Summary ({len(summary)} clients) ==")
    if dry_run:
        print("DRY-RUN: no files were uploaded. Pass --apply to upload.")
    else:
        total_uploaded = sum(int(r.get("uploaded") or 0) for r in summary)
        skipped = [r for r in summary if r.get("skipped")]
        print(f"  uploaded:    {total_uploaded} files across {len(summary) - len(skipped)} clients")
        print(f"  skipped:     {len(skipped)} clients")
        for r in skipped:
            print(f"    - {r['slug']}: {r.get('skipped')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
