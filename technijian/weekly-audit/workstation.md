# Weekly Time-Entry Audit - Workstation Setup

This is the playbook for the **production workstation** that runs the weekly
time-entry audit every Friday at 7:00 AM PST. Follow these steps once on the
target box, then leave the scheduled task running.

The development environment (the box where this code is authored and committed)
does **not** need any of this - it just commits the scripts. Only the
production workstation needs the secrets, the scheduled task, and the Outlook
mailbox access.

---

## 1. Prerequisites

### 1.1 OS

- Windows 10 / 11, 64-bit.
- Admin rights on the local machine for the initial install steps; the
  scheduled task itself runs as the signed-in user (no admin needed at run time).

### 1.2 Hardware / network

- Always-on or wake-on-schedule machine. Friday 7am PST runs assume the box
  is awake or wakes itself.
- Outbound internet to:
  - `https://api-clientportal.technijian.com` (Client Portal API)
  - `https://login.microsoftonline.com` (M365 token endpoint)
  - `https://graph.microsoft.com` (M365 Graph)
  - `https://github.com` (only for the initial git clone + push)

### 1.3 Accounts

- A signed-in Windows user account that the scheduled task will run under.
  Recommended: a dedicated `svc-tj-audit` local account; otherwise the
  primary user account (`rjain@technijian.com`'s local profile) works.
- That account must have read access to the OneDrive keyfiles listed below
  (or have its own copies).

---

## 2. Install software

Run all of these in an elevated PowerShell, except where noted.

### 2.1 Git

```powershell
winget install -e --id Git.Git
```

After install, verify in a fresh shell:

```powershell
git --version
```

### 2.2 Python 3.10 or newer

```powershell
winget install -e --id Python.Python.3.12
```

Reopen the shell. Verify:

```powershell
python --version
python -m pip --version
```

If Python 3.12 is unavailable, 3.10 / 3.11 / 3.13 are all fine. The scripts
require **3.9+** (uses `zoneinfo`, type hints with `|`).

### 2.3 Microsoft 365 desktop apps (Outlook + Word)

Outlook is needed only if a human is going to spot-check the drafts before
they send. Word is **not** required - the scripts use `python-docx` and never
launch Word.

Click-to-Run install via Microsoft 365 portal under
`https://www.microsoft.com/account/services` for the user.

### 2.4 The git repo

Clone into the same path used in development so absolute paths in scripts
keep working:

```powershell
mkdir C:\vscode\annual-client-review
cd C:\vscode\annual-client-review
git clone https://github.com/<orgname>/annual-client-review.git
cd annual-client-review
```

Replace `<orgname>` with the org or user that owns the GitHub repo. (The
repo URL is whatever `git remote get-url origin` returns on the dev box.)

### 2.5 Python dependencies

```powershell
cd C:\vscode\annual-client-review\annual-client-review
python -m pip install --upgrade pip
python -m pip install python-docx openpyxl
```

The audit pipeline uses only `python-docx` (Word output) and the standard
library. `openpyxl` is installed for the existing annual reports the same
workstation may also run.

---

## 3. Credentials

Two keyfiles must exist on the workstation. They are **never committed** to
git. Either copy them from the OneDrive sync, or recreate them.

### 3.1 Microsoft Graph (M365)

Path: `C:\Users\<username>\OneDrive - Technijian, Inc\Documents\VSCODE\keys\m365-graph.md`

Format (the file is parsed for these exact strings - keep the labels):

```markdown
# M365 Graph - HiringPipeline-Automation App

**App Client ID:** <APP_CLIENT_ID>
**Tenant ID:**     <TENANT_ID>
**Client Secret:** <CLIENT_SECRET>
```

Required Graph **application** permissions on the app registration:

- `Mail.Read`
- `Mail.Send`
- `Mail.ReadWrite`

Admin consent must be granted on the tenant. Verify in Azure Portal -
App registrations - `<App Name>` - API permissions.

The skill mailbox is hard-coded to `RJain@technijian.com` (set in
`_secrets.py` `DEFAULT_MAILBOX`). If the workstation should send from a
different mailbox, set the env var `M365_MAILBOX` (see step 4 below) before
running.

### 3.2 Client Portal API

Path: `C:\Users\<username>\OneDrive - Technijian, Inc\Documents\VSCODE\keys\client-portal.md`

Format:

```markdown
# Client Portal API - svc-weekly-audit

**UserName:** <username>
**Password:** <password>
```

The account named here authenticates against
`https://api-clientportal.technijian.com/api/auth/token`. It must have
permission to read time entries across all active clients (the existing
reporting role is sufficient).

### 3.3 (Alternative) Environment variables

Instead of the keyfiles you can set:

```
M365_TENANT_ID
M365_CLIENT_ID
M365_CLIENT_SECRET
M365_MAILBOX            (optional, defaults to RJain@technijian.com)
CP_USERNAME
CP_PASSWORD
```

Env vars take precedence over the keyfiles. Use this option only if storing
secrets in OneDrive is not acceptable on this workstation.

---

## 4. First run (smoke test)

Confirm everything is wired before scheduling.

### 4.1 Verify imports

```powershell
cd C:\vscode\annual-client-review\annual-client-review
python -c "
import sys
sys.path.insert(0, r'technijian\weekly-audit\scripts')
from _shared import cycle_id_for, week_window
print('cycle:', cycle_id_for())
print('window:', week_window())
"
```

Expected output: a recent ISO week and a 7-day window ending today.

### 4.2 Verify M365 + Client Portal auth

```powershell
python -c "
import sys
sys.path.insert(0, r'technijian\tech-training\scripts')
from _secrets import get_m365_credentials
t,c,s,m = get_m365_credentials()
print('M365 OK; mailbox =', m)
"

python -c "
import sys
sys.path.insert(0, r'scripts\clientportal')
import cp_api
print('CP login...'); s = cp_api.login()
print('  token len:', len(s.token))
"
```

Each should print one OK line. Any traceback means the keyfile or env var is
wrong - fix before proceeding.

### 4.3 Pipeline dry-run with one client only

```powershell
python technijian\weekly-audit\scripts\1_pull_weekly.py --only BWH
python technijian\weekly-audit\scripts\2_audit_weekly.py
python technijian\weekly-audit\scripts\3_build_weekly_docs.py
python technijian\weekly-audit\scripts\4_email_weekly.py --drafts-only
```

Then open Outlook on `RJain@technijian.com` -> Drafts and check that:

- Each tech in the affected client received a draft.
- The draft has both attachments (.docx + .csv).
- The greeting and stats look right.
- The signature renders.

If everything looks right, send manually from Outlook (or run
`python technijian\weekly-audit\scripts\4_email_weekly.py --send-existing`).

### 4.4 Full pipeline trial

Once the smoke test passes:

```powershell
python technijian\weekly-audit\scripts\run_weekly.py --drafts-only
```

This pulls every active client, flags the week, builds docs, and creates
drafts without sending. Inspect 3-4 random drafts in Outlook. When happy:

```powershell
python technijian\weekly-audit\scripts\4_email_weekly.py --send-existing
```

This is also the recovery path if a future run creates drafts but the send
fails.

---

## 5. Schedule the Friday 7am PST run

Use Windows Task Scheduler. The skill file
`~/.claude/skills/weekly-time-audit/SKILL.md` describes the operational
contract; this section just wires the cron-equivalent.

### 5.1 Create a wrapper batch file

The task triggers a one-line batch wrapper instead of `python.exe`
directly - it gives clean stdout/stderr capture and a stable path.

Save as `C:\vscode\annual-client-review\annual-client-review\technijian\weekly-audit\run_weekly.bat`:

```bat
@echo off
setlocal
cd /d C:\vscode\annual-client-review\annual-client-review
set LOG=technijian\weekly-audit\state\last-run.log
echo. >> %LOG%
echo ==== %date% %time% ==== >> %LOG%
python technijian\weekly-audit\scripts\run_weekly.py >> %LOG% 2>&1
endlocal
```

Test the wrapper from a non-elevated shell:

```cmd
C:\vscode\annual-client-review\annual-client-review\technijian\weekly-audit\run_weekly.bat
```

### 5.2 Register the scheduled task

Open Task Scheduler -> Create Task (NOT Create Basic Task).

**General tab:**
- Name: `Technijian Weekly Time-Entry Audit`
- Description: `Pulls last 7 days of time entries, flags outliers, emails techs.`
- Run only when user is logged on (default) - scripts need OneDrive paths,
  which require the user profile.
- Configure for: Windows 10 / 11.

**Triggers tab -> New:**
- Begin the task: On a schedule
- Settings: Weekly
- Start: next Friday at `07:00:00 AM`
- Recur every: 1 weeks on **Friday**.
- Synchronize across time zones: **unchecked** (so it tracks local Pacific time).
- Workstation must be set to Pacific Time. Verify with
  `tzutil /g` -> should print `Pacific Standard Time`.

**Actions tab -> New:**
- Action: Start a program
- Program/script: `C:\vscode\annual-client-review\annual-client-review\technijian\weekly-audit\run_weekly.bat`
- Start in (optional): `C:\vscode\annual-client-review\annual-client-review`

**Conditions tab:**
- Wake the computer to run this task: **checked**.
- Start only if a network connection is available: **checked**.

**Settings tab:**
- Allow task to be run on demand: checked.
- Run task as soon as possible after a scheduled start is missed: checked.
- If the task fails, restart every: 15 minutes, attempt up to 3 times.
- Stop the task if it runs longer than: 1 hour (the full pipeline is
  typically 5-15 minutes; 1 hour is generous).

Click OK. Provide the user account password when prompted.

### 5.3 Equivalent PowerShell registration (one-liner)

If you prefer scripted registration over the GUI:

```powershell
$action  = New-ScheduledTaskAction `
    -Execute 'C:\vscode\annual-client-review\annual-client-review\technijian\weekly-audit\run_weekly.bat' `
    -WorkingDirectory 'C:\vscode\annual-client-review\annual-client-review'

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 7:00am

$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartInterval (New-TimeSpan -Minutes 15) -RestartCount 3

Register-ScheduledTask `
    -TaskName 'Technijian Weekly Time-Entry Audit' `
    -Description 'Pulls last 7 days of time entries, flags outliers, emails techs.' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -User $env:USERNAME
```

---

## 6. Post-run commit

The pipeline writes outputs into `technijian/weekly-audit/<YYYY-WWnn>/`. To
keep the audit history committed:

### 6.1 Manual

```powershell
cd C:\vscode\annual-client-review\annual-client-review
git pull --rebase
git add technijian/weekly-audit/<cycle> technijian/weekly-audit/by-tech
git commit -m "weekly audit <cycle>"
git push
```

### 6.2 (Optional) Auto-commit at end of pipeline

Append to `run_weekly.bat` after the python line:

```bat
git pull --rebase >> %LOG% 2>&1
git add technijian/weekly-audit/ >> %LOG% 2>&1
git commit -m "weekly audit %date%" >> %LOG% 2>&1
git push >> %LOG% 2>&1
```

Only enable auto-commit if the workstation has a configured git identity
and a credential helper that doesn't prompt. Test once interactively before
relying on it from the scheduled task.

---

## 7. Monitoring

### 7.1 Last-run log

`technijian/weekly-audit/state/last-run.log` (appended each run).

### 7.2 Per-cycle JSON

- `technijian/weekly-audit/<cycle>/run_log.json` - pipeline-level success / failures.
- `technijian/weekly-audit/<cycle>/audit_log.json` - audit summary.
- `technijian/weekly-audit/<cycle>/by-tech/outlook-drafts-sent.csv` - per-email status.

### 7.3 Self-check email (optional)

Add a simple watchdog in `run_weekly.bat` that emails on failure:

```bat
if %ERRORLEVEL% NEQ 0 (
    powershell -Command "Send-MailMessage -SmtpServer smtp.office365.com -UseSsl -Port 587 -From svc-tj-audit@technijian.com -To rjain@technijian.com -Subject 'Weekly audit FAILED' -Body 'see %LOG%' -Credential (Get-Credential)"
)
```

In practice the easier check is: every Friday by 8am PST, RJain expects to
see the run-log JSON committed. If it isn't there, investigate.

---

## 8. Updating the skill

Updates flow through git. On the workstation:

```powershell
cd C:\vscode\annual-client-review\annual-client-review
git pull --rebase
```

No re-registration of the scheduled task is required as long as the script
paths don't change.

If `_shared.py` `CATEGORY_CAP` rules are tuned, document the change in the
commit message - the per-tech history files at
`technijian/weekly-audit/by-tech/<slug>/history.csv` will then have a mix
of pre/post-tuning flags, which is fine but worth being aware of when
analyzing trends.

---

## 9. Decommission / move to a different workstation

To move the schedule to a different box:

1. Disable the scheduled task on the old box:
   `Disable-ScheduledTask -TaskName 'Technijian Weekly Time-Entry Audit'`
2. Run sections 1-5 on the new box.
3. Confirm one full run on the new box (drafts-only is fine).
4. Unregister the task on the old box:
   `Unregister-ScheduledTask -TaskName 'Technijian Weekly Time-Entry Audit' -Confirm:$false`

The repo and all per-cycle outputs follow git, so no data needs to be moved
manually.
