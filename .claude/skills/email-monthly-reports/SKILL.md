---
name: email-monthly-reports
description: "Use when the user asks to send, draft, compose, or preview the monthly Technijian client report delivery email — branded HTML email with summary highlights and OneDrive/SharePoint links to every monthly report. Sent (with --apply) from clientportal@technijian.com via Microsoft Graph. Reads recipients from clients/<slug>/_meta.json (Recipient_Emails), report links from the Teams upload manifest at clients/<slug>/_monthly_report_uploads/<YYYY-MM>.json, and pulls headline KPIs from each data source's data files for the email body. Defaults to --dry-run, writes HTML preview per client. Examples: \"send April 2026 monthly reports to clients\", \"draft monthly report emails\", \"preview the monthly delivery email for AAVA\"."
---

# Monthly client report delivery email

Composes a Technijian-branded HTML email per client summarizing the
month's monitoring activity and linking out to every report uploaded
to the client's Teams Monthly Reports folder. Sends (when `--apply`)
from `clientportal@technijian.com` via Microsoft Graph
`/users/{mailbox}/sendMail`.

## Prerequisites

1. **Reports generated** — each per-data-source builder must have run
   for the target month (ME EC, Huntress, CrowdStrike, Meraki, Sophos,
   Veeam VBR, Veeam ONE, vCenter, MailStore, Veeam-365, M365).
2. **Reports uploaded to Teams** — `teams-upload-monthly` skill has
   written the manifest at
   `clients/<slug>/_monthly_report_uploads/<YYYY-MM>.json`. The email
   skill reads OneDrive links from this manifest only — it does NOT
   call Graph for links.
3. **`_meta.json` populated** — built by
   `scripts/clientportal/build_client_meta.py`. The skill reads
   `Active`, `Send_Ready`, and `Recipient_Emails` and skips clients
   that don't satisfy all three.

## Run

```bash
cd c:/VSCode/annual-client-review/annual-client-review-1

# Dry-run: writes HTML previews, sends nothing
python scripts/email_reports/send_monthly_email.py --month 2026-04

# Dry-run with internal recipient (sanity-check the rendered email)
python scripts/email_reports/send_monthly_email.py --month 2026-04 --to-only support@technijian.com

# Send for one client
python scripts/email_reports/send_monthly_email.py --month 2026-04 --only AAVA --apply

# Send to all eligible clients
python scripts/email_reports/send_monthly_email.py --month 2026-04 --apply
```

Each run writes a per-client preview to:

```
clients/<slug>/_monthly_report_emails/<YYYY-MM>.html
```

— review these in any browser before going live.

## Email content

- **Header**: blue gradient with "Technijian Monthly Reports" + client
  name + month label.
- **Highlights**: 1-line summary per data source extracted from the
  underlying data files. Today the skill extracts:
  - **Huntress**: incident, signal, and platform-report counts ("reviewed
    by the Huntress 24×7 SOC")
  - **CrowdStrike**: alert count + Critical/High count ("reviewed by
    Falcon Overwatch")
  - **ME EC**: cumulative installed-patch count + endpoint count
  - **Veeam VBR**: backup session success rate
  - **vCenter**: VM count and powered-on count
- **Reports table**: clickable OneDrive link per uploaded report.
- **CTA button**: "Open Reports Folder" → SharePoint folder URL.
- **Footer**: Technijian contact line + reply-to support@technijian.com.

## Auth

Uses the **HiringPipeline-Automation** app (App Client ID 4c009c1b)
with Application-mode `Mail.Send` from
`%USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/m365-graph.md`.
Sends from `clientportal@technijian.com`. CC's `support@technijian.com`
on every send so the support inbox has a record.

## Recipient resolution

`Recipient_Emails` in `clients/<slug>/_meta.json` is the source of truth
— it's populated by `build_client_meta.py` using the 2-layer rule
(portal designation → contract signer). The email skill reads this
field directly. To override (e.g. internal review send), pass
`--to-only support@technijian.com,rjain@technijian.com`.

## Highlights extraction — extending

`build_highlights()` in `send_monthly_email.py` calls one helper per
data source. To add Veeam ONE, MailStore, M365, etc. as highlights,
add a `_highlight_<source>(client_dir, year, month)` function that
returns a one-sentence string (or `None` to skip) and append it to the
list inside `build_highlights()`.

## Gotchas

- **No upload manifest** → skill skips the client. Run the
  `teams-upload-monthly` skill first.
- **Client not Active or Send_Ready=False** → skipped silently. This
  matches the rest of Technijian's per-client send pipeline.
- **No recipients in `_meta.json`** → skipped. Re-run
  `scripts/clientportal/build_client_meta.py --only <CODE>` to refresh.
- **Mail.Send "send-as" semantics** — the HiringPipeline-Automation app
  has Application-mode `Mail.Send`, which lets it call `/users/{any-mailbox}/sendMail`
  in the tenant. For `clientportal@technijian.com` to be allowed,
  Application Access Policies in Exchange Online must scope the app to
  that mailbox. If sends 403 with "ApplicationAccessPolicy", run
  `New-ApplicationAccessPolicy` to grant the app access to clientportal's
  mailbox.

## Related

- `teams-upload-monthly` — must run first to populate the manifest.
- `client-portal-pull` + `build_client_meta.py` — owners of the
  `_meta.json` recipient list.
- `proofread-report` — already gated each data-source builder's output.
