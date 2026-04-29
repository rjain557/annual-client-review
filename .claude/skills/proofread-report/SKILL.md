---
name: proofread-report
description: "Use when the user asks to proofread, validate, or quality-check a Technijian-branded Word report; or wire automatic proofreading into a new report builder. Structural + content gate that catches missing sections, placeholders, all-blank tables, mojibake encoding errors, and undersized files before reports ship to clients. Auto-called by every report builder after `doc.save()`. Examples: \"proofread these reports\", \"check report quality\", \"add proofreading to a builder\", \"validate Q1 2026 reports before sending\"."
---

# Proofread DOCX Reports

Structural + content proofreader for every Technijian-branded Word
deliverable. Reports go to clients and are irrecoverable once sent — this
gate exists so a defective deliverable fails the build instead of landing
in someone's inbox.

Script: `technijian/shared/scripts/proofread_docx.py` (~400 lines, stdlib + python-docx).
Verified passing on **182 reports** at last full run (3 Teramind compliance, 116 Huntress monthly, 54 tech-training, 9 annual/quarterly).

## What it checks

| # | Check | Severity |
|---|---|---|
| 1 | File exists, is readable | fail |
| 2 | File size ≥ `--min-kb` (default 10 KB) | fail |
| 3 | Document opens via python-docx | fail |
| 4 | Cover page first paragraph not blank/placeholder | fail |
| 5 | Expected section headers present (case-insensitive, searches table cells too) | fail |
| 6 | No all-blank tables (excluding decorative color bars + bar+title section header tables) | fail |
| 7 | No placeholder text: `TODO`, `TBD`, `[placeholder]`, `[Your Name]`, `[Recipient]`, `[client name]`, `[date]`, `[insert ...]` | fail |
| 8 | No mojibake artifacts (cp1252 double-encoding patterns, `Aâ€...`, `A,," `, etc.) | fail |
| 9 | At least one callout box (single-cell table) | warn |
| 10 | At least one metric card row (multi-column table in first half) | warn |

Warnings don't fail the build unless `--strict` is passed. Issues do.

## Usage

```bash
# One report
python technijian/shared/scripts/proofread_docx.py path/to/Report.docx

# Many reports, expecting specific sections
python technijian/shared/scripts/proofread_docx.py \
  --sections "Executive Summary,Endpoint Protection,Recommendations" \
  path/to/*.docx

# JSON output for CI / other tools
python technijian/shared/scripts/proofread_docx.py --json path/to/Report.docx

# Treat warnings as failures (CI mode)
python technijian/shared/scripts/proofread_docx.py --strict path/to/Report.docx
```

Exit codes: `0` pass, `1` issues, `2` file not found / can't open.

## Section strings by report type

```
# Teramind compliance
"Executive Summary,Endpoint Monitoring Coverage,DLP Policy Status,Activity Summary,Insider-Threat Risk Assessment,What Technijian Did For You,Recommendations,About This Report"

# Huntress monthly
"Executive Summary,Endpoint Protection,Threat Activity This Month,What Technijian Did For You,Recommendations,About This Report"

# Meraki monthly activity
"Executive Summary,Network & Device Inventory,Security Posture,IDS/IPS & AMP Events,Firewall / Network Activity,Daily Trend"
```

Add new section sets here when adding new report types.

## Wiring into a new report builder

Every `generate_*_docx.py` should call this script after `doc.save()` and
exit non-zero if it fails. Boilerplate:

```python
import subprocess, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[N]   # adjust N for your script depth
PROOFREADER = REPO_ROOT / "technijian" / "shared" / "scripts" / "proofread_docx.py"
EXPECTED_SECTIONS = "Executive Summary,...,About This Report"

# After all docx files are generated:
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

## Builders currently wired in

| Builder | Located at |
|---|---|
| Teramind compliance | `technijian/teramind-pull/scripts/build_teramind_compliance_report.py` |
| Huntress monthly | `technijian/huntress-pull/scripts/build_monthly_report.py` |
| Meraki monthly | `scripts/meraki/generate_monthly_docx.py` |

## Why this exists (design context)

`_brand.add_section_header()` renders Technijian section headers as a
**2-column table** (narrow color bar + title text), NOT a heading-style
paragraph. Standard linters miss this — they look for `Heading 1` /
`Heading 2` styles and find none. The proofreader walks all paragraph and
table-cell text to find sections, and excludes color-bar tables and
bar+title tables from the all-blank-table check so they don't trip false
positives.

Mojibake guard catches the cp1252 double-encoding pattern that ships
when text is written as utf-8 but a tool re-decodes as cp1252 (`Aâ€`,
`A,,"`, `A---`). It's saved a few client deliverables.

## Gotchas

- **"Section missing" can mean two things.** Either the heading really isn't
  there (real bug) or the section name in `--sections` doesn't match the
  rendered text (off-by-one in punctuation, plurals, etc.). Open the doc and
  verify before "fixing" the builder.
- **Color bar tables are 1-cell, no text.** The check correctly skips them.
  But if you build a 1-cell table with text (e.g., a callout) and accidentally
  leave it empty, the all-blank-tables check WILL fire.
- **Don't stack `--strict` on day-one.** Get all 7 scored checks green first;
  THEN tighten with `--strict` once both warning checks (callout + metric
  cards) are in the report.
- **Min-kb default is 10**. For very simple reports (1-page memo), bump to
  `--min-kb 5` rather than 10.
