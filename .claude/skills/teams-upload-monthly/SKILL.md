---
name: teams-upload-monthly
description: "Use when the user asks to copy, upload, publish, or sync the monthly client reports into MS Teams — to a Monthly Reports channel on each client's team, organized into Month-Year subfolders. Reads from clients/<slug>/<source>/reports/ and clients/<code>/<source>/monthly/<YYYY-MM>/ folders, finds the team named after the client code, locates or creates the Month-Year folder under the channel's SharePoint folder, and uploads every monthly report. Defaults to --dry-run; --apply does the actual upload. Examples: \"upload April 2026 reports to Teams\", \"sync monthly reports to client teams\", \"publish March reports to clients' Monthly Reports channel\"."
---

# Teams upload — monthly client reports

Copies generated client monthly reports into each client's MS Teams team
under a **Monthly Reports** channel, organized into **Month-Year**
subfolders (`April-2026`, `March-2026`, etc.). Members of the client's
team automatically have access to the channel folder — no per-channel
permission step needed.

## Prerequisites

- **One-time per client team**: a tech with Teams admin rights creates a
  channel named exactly `Monthly Reports` on each client's team. The
  Teams-Connector app does NOT have `Channel.Create` scope, so the
  uploader will skip clients whose team is missing this channel.
- **Teams team naming**: the team's `displayName` must equal the client
  code (e.g. `AAVA`, `BWH`). Special-case mappings live in
  `slug_to_team_name()` in `upload_monthly_reports.py` for the few
  clients whose Teams name diverges from the client folder slug
  (Technijian-MSP, Technijian-India, ISH-KSS).
- **Generated reports**: monthly DOCX files must exist under each
  client's data-source subfolder. Run the per-source builders first
  (see ME EC, Huntress, CrowdStrike, Sophos, Meraki, Veeam VBR, Veeam
  ONE, vCenter, Veeam-365, MailStore, M365 monthly report skills).

## Run

```bash
cd c:/VSCode/annual-client-review/annual-client-review-1

python scripts/teams_upload/upload_monthly_reports.py --month 2026-04                       # dry-run all clients
python scripts/teams_upload/upload_monthly_reports.py --month 2026-04 --only AAVA,BWH       # dry-run subset
python scripts/teams_upload/upload_monthly_reports.py --month 2026-04 --apply               # upload
python scripts/teams_upload/upload_monthly_reports.py --month 2026-04 --only AAVA --apply   # upload one
```

## Output

For each client successfully uploaded, the script writes a manifest:

```
clients/<slug>/_monthly_report_uploads/<YYYY-MM>.json
```

This manifest captures the OneDrive `webUrl` for every uploaded file and
the parent folder URL. The **email-monthly-reports** skill consumes this
manifest to build the client-facing email with clickable links (so the
email skill never needs to hit Graph again).

## Auth

Uses the **Teams-Connector** app (App Client ID 331ce1b5) with
Application-mode credentials from
`%USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/teams-connector.md`.

Permissions needed: `Group.Read.All`, `TeamMember.Read.All`,
`Files.ReadWrite.All`, `Sites.ReadWrite.All`. All currently granted.

## Reports the uploader picks up

The `REPORT_LOCATIONS` list in `upload_monthly_reports.py` maps each data
source to a glob pattern. Today it covers:

| Data source | Pattern |
|---|---|
| ME EC | `me_ec/reports/*ME EC Patch Activity - {ym}.docx` |
| Huntress | `huntress/monthly/{ym}/*Cybersecurity-Activity-{ym}.docx` |
| CrowdStrike | `crowdstrike/monthly/{ym}/*CrowdStrike-Activity-{ym}.docx` |
| Sophos | `sophos/monthly/{ym}/*.docx` |
| Meraki | `meraki/reports/*Meraki Monthly Activity - {ym}.docx` |
| M365 | `m365/monthly/{ym}/*.docx` |
| vCenter | `vcenter/reports/*vCenter Monthly Infrastructure - {ym}.docx` |
| Veeam VBR | `veeam-vbr/reports/*Veeam VBR Monthly Backup - {ym}.docx` |
| Veeam ONE | `veeam-one/reports/*Veeam ONE Monthly Health - {ym}.docx` |
| Veeam 365 | `veeam-365/reports/*{ym}*.docx` |
| MailStore | `mailstore/reports/*{ym}*.docx` |

Add new data sources by appending to the list — the skill auto-picks up
files matching the new pattern.

## Gotchas

- **Channel not present** → uploader skips the client and logs the gap.
  Email a tech to create `Monthly Reports` on that client's team.
- **Team displayName mismatch** → client's team must match the lowercased
  client folder slug after applying `slug_to_team_name()`. Add overrides
  for new exceptions.
- **SharePoint conflict resolution** → existing files with the same name
  are **replaced** (`@microsoft.graph.conflictBehavior=replace`). This
  keeps the link stable across re-runs.
- **File size** → simple-upload endpoint (PUT to `.../content`) is used,
  good for files under ~4 MB. Our DOCX reports are 70-100 KB, so this is
  fine. If we ever need >4 MB uploads, switch to the resumable upload
  session API.
