# Repo Conventions — annual-client-review

This file is loaded automatically by Claude Code when working in this repo.
Every contributor (human or agent) should follow these rules. They are the
result of multiple iterations and exist to keep the per-client deliverables
consistent and portable across workstations.

## Branded Word reports — use `_brand.py`

**All branded DOCX outputs in this repo MUST import `_brand` from the shared
location. Do not duplicate OXML helpers, do not roll a local color palette.**

```python
import sys
from pathlib import Path
SHARED = Path(__file__).resolve().parents[N] / "technijian" / "shared" / "scripts"
sys.path.insert(0, str(SHARED))
import _brand as brand

doc = brand.new_branded_document()                  # margins, header logo, footer
brand.render_cover(doc, title=..., subtitle=..., footer_note=..., date_text=...)
brand.add_section_header(doc, "Executive Summary")  # branded section bar + title
brand.styled_table(doc, headers, rows, col_widths=..., status_col=...)
brand.add_metric_card_row(doc, [(value, label, color), ...])
brand.add_callout_box(doc, text)
brand.add_body(doc, paragraph_text)
brand.add_bullet(doc, bullet_text, bold_prefix="Status:")
```

Brand palette comes from the JS canonical kit at
`c:/vscode/tech-branding/tech-branding/scripts/brand-helpers.js`. The
Python module at `technijian/shared/scripts/_brand.py` mirrors that kit:
- `CORE_BLUE` `#006DB6` — section headers, table headers
- `CORE_ORANGE` `#F67D4B` — divider bars, accent
- `TEAL`, `GREEN`, `RED` — status coloring (info, healthy, critical)
- `DARK_CHARCOAL`, `BRAND_GREY` — body text
- Font: **Open Sans**
- Logo: `c:/vscode/tech-branding/tech-branding/assets/logos/png/technijian-logo-full-color-600x125.png`

If `_brand.py` is missing a helper two pipelines need, add it to `_brand.py`
rather than inlining locally — never fork. The historical local copy at
`technijian/huntress-pull/scripts/_brand.py` is preserved for compatibility
but is **not** the authoritative source — the canonical copy lives at
`technijian/shared/scripts/_brand.py`.

## Proofread gate on every report

**Every report builder calls `proofread_docx.py` after `doc.save()` and exits
non-zero on failure.** This is a hard rule — the proofreader catches missing
sections, placeholders, all-blank tables, and mojibake before reports ship to
clients.

```python
import subprocess, sys
from pathlib import Path
PROOFREADER = Path(__file__).resolve().parents[N] / "technijian" / "shared" / "scripts" / "proofread_docx.py"
EXPECTED_SECTIONS = "Executive Summary,...,About This Report"

sys.stdout.flush()
rc = subprocess.run(
    [sys.executable, str(PROOFREADER),
     "--sections", EXPECTED_SECTIONS, "--quiet"]
    + [str(p) for p in generated_paths if p.exists()]
).returncode
if rc != 0:
    print("[proofread] FAILED — one or more reports did not pass the gate.")
    sys.exit(rc)
```

The proofreader is documented under `.claude/skills/proofread-report/SKILL.md`.

## Per-client output layout

All client deliverables go under `clients/<code>/<tool>/...` where `<code>` is
the lowercase Client Portal LocationCode. Existing folders include:

```
clients/<code>/
  data/                 source-system snapshots (per pipeline)
  monthly/<YYYY-MM>/    monthly time-entry / ticket pulls
  crowdstrike/<date>/   daily Falcon agent + incident pulls
  huntress/<date>/      daily Huntress agent inventory + monthly reports
  screenconnect/<year>/ ScreenConnect session audit CSVs
  meraki/               Meraki firewall events, IDS/IPS, configs, monthly reports
```

**Never put per-client data under `clients/_meraki/`, `clients/_<tool>/`, or
any underscored namespace at the same level.** Underscore-prefixed folders
under `clients/` are reserved for cross-org logs (`clients/_meraki_logs/`),
not per-client data. The per-client convention is non-negotiable — it is what
makes annual-review docx generators discover the right inputs automatically.

For per-tool slug-to-LocationCode mapping (when source-system slugs differ
from CP codes), each tool ships a small `_org_mapping.py` (Meraki) or
`_state/<tool>-org-mapping.json` (Huntress, Umbrella, CrowdStrike). When
onboarding a new external org, add the mapping there, not by overriding paths.

## Skills live in this repo

**Repo-specific skills go in `<repo>/.claude/skills/<name>/SKILL.md`**, not
under `~/.claude/skills/`. Claude Code auto-discovers them when the workspace
is opened. Do not duplicate to `~/.claude/skills/` — that breaks portability
when work moves to another workstation. Currently bundled:

```
.claude/skills/meraki-pull/             daily Meraki pull (events, IDS/IPS, configs)
.claude/skills/meraki-monthly-report/   monthly Meraki Word reports
.claude/skills/proofread-report/        DOCX quality gate
```

Other skills (`client-portal-pull`, `huntress-daily-pull`, `monthly-client-pull`,
`tech-time-entry-audit`, etc.) are in the process of being migrated from
user-scope to repo-scope. New skills go straight into the repo.

## Credentials live in OneDrive, not in code

API keys, OAuth secrets, and service passwords go in:

```
%USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/<service>.md
```

One markdown file per service. Format:

```markdown
# <Service> API Credentials

## Account Info
- **Platform:** ...
- **Base URL:** ...
- **Auth Type:** ...

## Credentials
- **API Key:** <value>
- **API Secret:** <value>
```

Helper modules read these files via regex (see `meraki_api.get_api_key()`,
`cp_api._read_keyvault_creds()`, `huntress_api.get_credentials()`). Always
prefer env vars (`<SERVICE>_API_KEY`) when running headless / scheduled,
falling back to the keyfile when env vars are absent.

**Never commit credentials to the repo.** The OneDrive vault is shared across
the operator's workstations via OneDrive sync; the repo is git-tracked and
public-adjacent.

## Memory and vault

Auto-memory at `~/.claude/projects/<slug>/memory/` is system-managed by Claude
Code and stays workstation-local. The canonical, portable store is the
Obsidian vault at:

```
%USERPROFILE%/OneDrive - Technijian, Inc/Documents/obsidian/annual-client-review/
```

Run `vault:sync` on the source workstation to mirror auto-memory into the
vault before moving to a new machine. Session logs land at
`conversation-log/YYYY-MM-DD.md`.

## Pipeline schedules (Windows Task Scheduler)

To avoid contention, daily pulls are staggered:

| Task | Time | Pipeline |
|---|---|---|
| Technijian-DailyHuntressPull | 01:00 | Huntress |
| Technijian-DailyUmbrellaPull | 02:00 | Cisco Umbrella |
| Technijian-DailyCrowdStrikePull | 03:00 | CrowdStrike Falcon |
| Technijian-DailyTeramindPull | 04:00 | Teramind on-prem |
| Technijian-DailyMerakiPull | 05:00 | Cisco Meraki |
| Technijian-MonthlyClientPull | Day 1, 07:00 | Client Portal monthly |
| Technijian-MonthlySophosPull | Day 1, 07:00 | Sophos Central Partner |
| Technijian-MonthlyScreenConnectPull | Day 28, 20:00 | ScreenConnect (interactive) |

All scheduled tasks must run as the workstation user (`/ru "%USERNAME%"`),
not SYSTEM — SYSTEM cannot read the OneDrive-synced keyvault.

## When extending the codebase

1. Read this file first.
2. Read `workstation.md` for the existing per-pipeline conventions.
3. Search vault knowledge: `obsidian/annual-client-review/Knowledge/` for
   skill design notes, and `obsidian/annual-client-review/memory/` for
   feedback memories ("don't do X", "always do Y").
4. New branded DOCX → import `_brand`. New report builder → wire the
   proofread gate. New per-client output → put it under `clients/<code>/`.
   New skill → put the SKILL.md in `<repo>/.claude/skills/`.
5. New external service → keyfile in OneDrive vault, helper module that
   reads it, env-var override.
