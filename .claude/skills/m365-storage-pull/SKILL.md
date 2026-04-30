# m365-storage-pull

Weekly M365 storage usage monitoring per GDAP-approved client tenant.
Tracks Mailbox, OneDrive, SharePoint, and Teams storage with per-user/per-site
breakdowns and warns when approaching quota limits.

## When to invoke

Trigger phrases: "m365 storage", "mailbox full", "onedrive quota", "sharepoint
storage", "teams storage", "storage usage", "near capacity", "storage warning",
"who's using the most storage", "m365 storage pull".

## What it monitors

| Service | Granularity | Threshold |
|---|---|---|
| Exchange Mailbox | Per user: used / quota / % | Warn ≥75%, Critical ≥90% |
| OneDrive | Per user: used / quota / % | Warn ≥75%, Critical ≥90% |
| SharePoint sites | Per site: used / quota / % | Warn ≥75%, Critical ≥90% |
| Teams | Teams channel files = SharePoint team sites (flagged `isTeamsSite=true`) | Same thresholds |

> Teams has no separate quota. Channel files → SharePoint. Chat attachments
> and recordings → user's OneDrive. Both are captured by this pull.

## Output per client (`clients/<code>/m365/storage/YYYY-WW/`)

```
mailbox_usage.json      per-mailbox: usedGB, quotaGB, pctUsed
onedrive_usage.json     per-user: usedGB, quotaGB, pctUsed
sharepoint_usage.json   per-site: usedGB, quotaGB, pctUsed, isTeamsSite, fileCount
org_totals.json         org-level totals (mailbox / onedrive / sharepoint)
storage_summary.json    alerts list sorted by pctUsed + alert_counts
```

## Storage summary structure

```json
{
  "alerts": [
    {
      "service": "mailbox",
      "identifier": "john@client.com",
      "storageUsedGB": 48.2,
      "quotaGB": 50.0,
      "pctUsed": 96.4,
      "severity": "critical"
    }
  ],
  "alert_counts": { "critical": 2, "warn": 5 }
}
```

## Prerequisites

- `keys/m365-partner-graph.md` — App ID + Client Secret filled in
- `state/gdap_status.csv` — approved tenants
- `Reports.Read.All` permission (already granted)

## Usage

```cmd
cd c:\vscode\annual-client-review\annual-client-review

REM current week, all tenants (D7 report window)
python technijian\m365-pull\scripts\pull_m365_storage.py

REM 30-day window for fuller picture
python technijian\m365-pull\scripts\pull_m365_storage.py --period D30

REM specific clients
python technijian\m365-pull\scripts\pull_m365_storage.py --only BWH,ORX
```

## Scheduled task

```
Task name:  Technijian-WeeklyM365StoragePull
Trigger:    Weekly, Monday 07:00 PT
Action:     cmd /c "cd /d C:\vscode\annual-client-review\annual-client-review && technijian\m365-pull\run-m365-storage.cmd"
Run as:     %USERNAME%
```

## Privacy note

Some M365 tenants anonymize report data by default (UPNs show as GUIDs).
If you see obfuscated identifiers, ask the client admin to run in their tenant:
```
PATCH https://graph.microsoft.com/v1.0/admin/reportSettings
{ "displayConcealedNames": false }
```
Or they can toggle it in Microsoft 365 Admin Center → Settings → Org settings →
Reports → "Display concealed user, group, and site names in reports".
