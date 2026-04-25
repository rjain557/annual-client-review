"""Draft per-tech training emails as .eml files with the personalized
training DOCX and the flagged-entries CSV attached. Drafts open natively in
Outlook; user reviews TO address, then sends.

Output (per tech): by-tech/<slug>/email-draft.eml
Plus a master manifest at: by-tech/email-drafts-manifest.csv

Usage: python _draft-tech-emails.py [YEAR]
"""
import csv
import re
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent.parent.parent
YEAR = sys.argv[1] if len(sys.argv) > 1 else "2026"
ROOT = REPO / "technijian" / "tech-training" / YEAR
BY_TECH = ROOT / "by-tech"

FROM_ADDR = "rjain@technijian.com"
DOMAIN = "technijian.com"

# Override addresses if known (slug -> email)
EMAIL_OVERRIDES: dict[str, str] = {
    # "P-Biswal": "pbiswal@technijian.com",
}


def slug_to_display(slug: str) -> str:
    m = re.match(r"([A-Z])-(.+)", slug)
    if m:
        return f"{m.group(1)}. {m.group(2).replace('-', ' ')}"
    return slug.replace("-", " ")


def slug_to_first_name(slug: str) -> str:
    # Best-effort: most slugs are "X-LastName"; we don't actually have first names.
    # Use the display name (e.g. "P. Biswal") so the greeting is "Hi P. Biswal,".
    return slug_to_display(slug)


def slug_to_email(slug: str) -> str:
    if slug in EMAIL_OVERRIDES:
        return EMAIL_OVERRIDES[slug]
    parts = slug.split("-")
    if len(parts) == 2:
        # Initial + Lastname → first letter + lastname
        return f"{parts[0].lower()}{parts[1].lower()}@{DOMAIN}"
    return f"{slug.lower().replace('-', '.')}@{DOMAIN}"


def read_summary(slug: str):
    """Pull totals from training.md frontmatter-ish lines."""
    md = (BY_TECH / slug / "training.md").read_text(encoding="utf-8")
    def grab(pattern, cast=str, default=0):
        m = re.search(pattern, md)
        if not m:
            return default
        try:
            return cast(m.group(1).replace(",", ""))
        except ValueError:
            return default
    return {
        "total_entries": grab(r"Total entries logged:\*\*\s*([\d,]+)", int),
        "total_hours": grab(r"Total hours logged:\*\*\s*([\d,\.]+)", float, 0.0),
        "flagged_entries": grab(r"Flagged entries:\*\*\s*(\d+)", int),
        "flagged_hours": grab(r"Flagged hours:\*\*\s*([\d,\.]+)", float, 0.0),
    }


def top_flag_code(slug: str) -> str | None:
    csv_path = BY_TECH / slug / "flagged-entries.csv"
    counts: dict[str, int] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            for c in (row.get("Flags") or "").split(";"):
                if c:
                    counts[c] = counts.get(c, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


FLAG_DESCRIPTIONS = {
    "H1": "logging more time than expected on routine work (patch, agent updates, monitoring alerts)",
    "H2": "using vague titles like \"Help\", \"Fix\", or \"Issue\" on entries longer than 30 minutes",
    "H3": "logging a single time-block over 8 hours — break into separate entries",
    "H4": "exceeding 12 hours total in one day across tickets — verify dates",
    "H5": "creating multiple entries on the same ticket on the same day — consolidate them",
}


def build_html_body(slug: str, display: str, summary: dict, top_flag: str | None) -> str:
    pct_e = summary["flagged_entries"] / max(summary["total_entries"], 1) * 100
    pct_h = summary["flagged_hours"] / max(summary["total_hours"], 0.01) * 100
    focus = ""
    if top_flag and top_flag in FLAG_DESCRIPTIONS:
        focus = (
            f'<p><b>Your most common flag is <span style="color:#F67D4B">{top_flag}</span></b> — '
            f'{FLAG_DESCRIPTIONS[top_flag]}. The attached training document walks through your '
            f'specific entries and what to change going forward.</p>'
        )

    return f"""<html><body style="font-family:'Open Sans',Arial,sans-serif;color:#1A1A2E;font-size:11pt;line-height:1.5;">
<div style="height:6px;background:#006DB6;margin-bottom:20px;"></div>

<p>Hi {display},</p>

<p>As part of an internal effort to clean up how Technijian time entries appear on client invoices,
I ran a review of every time entry logged across all clients during {YEAR}. The goal is not to
audit anyone — it is to give each tech a personal view of where the entries they log might look
unreasonable to a client reading their weekly in-contract invoice, so we can correct things
<em>before</em> the invoice is committed.</p>

<p><b>Your {YEAR} numbers:</b></p>
<ul>
  <li>You logged <b>{summary['total_entries']:,} time entries</b> totalling <b>{summary['total_hours']:,.2f} hours</b>
      across all clients.</li>
  <li>The audit flagged <b>{summary['flagged_entries']} entries ({summary['flagged_hours']:,.2f} hours)</b> —
      <b>{pct_e:.1f}%</b> of your entries by count, <b>{pct_h:.1f}%</b> by hours.</li>
</ul>

{focus}

<p><b>Two attachments to review:</b></p>
<ul>
  <li><b>{slug}-Training.docx</b> — your personalized branded training document. Cover page, your
      stats, breakdown by client and category, your 12 most-flagged entries, and concrete advice
      on what to write differently next time.</li>
  <li><b>flagged-entries.csv</b> — every flagged entry of yours (client, date, title, hours, cap,
      flag codes, reasons). Filterable in Excel.</li>
</ul>

<p style="background:#F8F9FA;border-left:4px solid #F67D4B;padding:12px 16px;margin:16px 0;">
<b>New weekly cadence — starting this week:</b><br>
Every <b>Thursday</b> we will run this scan against the week's logged entries and email each tech
their personalized flagged-entries list <b>before</b> Friday's weekly in-contract invoice is
committed. That gives you a window to revise titles, consolidate duplicate entries, or reassign
hours so your time appears the way it should on the invoice the client receives.
</p>

<p><b>What you can do today:</b></p>
<ol>
  <li>Open the attached training document and read the personalized advice.</li>
  <li>Skim the CSV to see your specific flagged entries.</li>
  <li>Going forward, follow the six general rules at the bottom of the training doc — most
      flags disappear when titles are descriptive and same-ticket entries are consolidated.</li>
</ol>

<p>If anything in the analysis looks wrong (mis-classified work, a one-off P1 incident that
genuinely needed the time), reply with the date and ticket and I will adjust the rules so it
does not flag next time.</p>

<p>Thanks,<br>Ravi</p>

<div style="margin-top:24px;padding-top:12px;border-top:1px solid #E9ECEF;color:#59595B;font-size:9pt;">
Technijian &nbsp;|&nbsp; 18 Technology Dr., Ste 141, Irvine, CA 92618 &nbsp;|&nbsp;
949.379.8500 &nbsp;|&nbsp; technijian.com<br>
<i>Internal — Tech Training. This message and its attachments are for the named recipient only.</i>
</div>
</body></html>"""


def build_text_body(slug: str, display: str, summary: dict, top_flag: str | None) -> str:
    pct_e = summary["flagged_entries"] / max(summary["total_entries"], 1) * 100
    pct_h = summary["flagged_hours"] / max(summary["total_hours"], 0.01) * 100
    focus = ""
    if top_flag and top_flag in FLAG_DESCRIPTIONS:
        focus = f"\nYour most common flag is {top_flag} — {FLAG_DESCRIPTIONS[top_flag]}. The attached training document walks through your specific entries and what to change going forward.\n"

    return (
        f"Hi {display},\n\n"
        f"As part of an internal effort to clean up how Technijian time entries appear on client "
        f"invoices, I ran a review of every time entry logged across all clients during {YEAR}. "
        f"The goal is not to audit anyone — it is to give each tech a personal view of where the "
        f"entries they log might look unreasonable to a client reading their weekly in-contract "
        f"invoice, so we can correct things before the invoice is committed.\n\n"
        f"Your {YEAR} numbers:\n"
        f"  - You logged {summary['total_entries']:,} time entries totalling {summary['total_hours']:,.2f} hours across all clients.\n"
        f"  - The audit flagged {summary['flagged_entries']} entries ({summary['flagged_hours']:,.2f} hours) — {pct_e:.1f}% by count, {pct_h:.1f}% by hours.\n"
        f"{focus}\n"
        f"Two attachments to review:\n"
        f"  - {slug}-Training.docx — your personalized branded training document. Cover page, your stats, breakdown by client and category, your 12 most-flagged entries, and concrete advice on what to write differently next time.\n"
        f"  - flagged-entries.csv — every flagged entry of yours (client, date, title, hours, cap, flag codes, reasons).\n\n"
        f"NEW WEEKLY CADENCE — STARTING THIS WEEK:\n"
        f"Every Thursday we will run this scan against the week's logged entries and email each "
        f"tech their personalized flagged-entries list BEFORE Friday's weekly in-contract invoice "
        f"is committed. That gives you a window to revise titles, consolidate duplicate entries, "
        f"or reassign hours so your time appears the way it should on the invoice the client "
        f"receives.\n\n"
        f"What you can do today:\n"
        f"  1. Open the attached training document and read the personalized advice.\n"
        f"  2. Skim the CSV to see your specific flagged entries.\n"
        f"  3. Going forward, follow the six general rules at the bottom of the training doc — "
        f"most flags disappear when titles are descriptive and same-ticket entries are consolidated.\n\n"
        f"If anything in the analysis looks wrong (mis-classified work, a one-off P1 incident that "
        f"genuinely needed the time), reply with the date and ticket and I will adjust the rules so "
        f"it does not flag next time.\n\n"
        f"Thanks,\nRavi\n\n"
        f"--\nTechnijian | 18 Technology Dr., Ste 141, Irvine, CA 92618 | 949.379.8500 | technijian.com\n"
        f"Internal — Tech Training. This message and its attachments are for the named recipient only.\n"
    )


def build_eml(slug: str) -> tuple[Path, dict]:
    folder = BY_TECH / slug
    docx_path = folder / f"{slug}-Training.docx"
    csv_path = folder / "flagged-entries.csv"
    if not docx_path.exists() or not csv_path.exists():
        return None, {"error": "missing artifacts", "slug": slug}

    display = slug_to_display(slug)
    to_addr = slug_to_email(slug)
    summary = read_summary(slug)
    top_flag = top_flag_code(slug)

    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    msg["To"] = to_addr
    msg["Subject"] = f"[Action] Your {YEAR} time-entry training review — adjustments before Friday invoices"
    msg["X-Unsent"] = "1"   # Outlook hint: open as draft, not sent
    msg.set_content(build_text_body(slug, display, summary, top_flag))
    msg.add_alternative(build_html_body(slug, display, summary, top_flag), subtype="html")

    # attach DOCX
    with docx_path.open("rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=docx_path.name,
        )
    # attach CSV
    with csv_path.open("rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="text",
            subtype="csv",
            filename=csv_path.name,
        )

    eml_path = folder / "email-draft.eml"
    eml_path.write_bytes(bytes(msg))

    return eml_path, {
        "slug": slug,
        "display": display,
        "to": to_addr,
        "total_entries": summary["total_entries"],
        "total_hours": round(summary["total_hours"], 2),
        "flagged_entries": summary["flagged_entries"],
        "flagged_hours": round(summary["flagged_hours"], 2),
        "top_flag": top_flag or "",
        "eml_path": str(eml_path.relative_to(REPO)),
        "docx_attached": docx_path.name,
        "csv_attached": csv_path.name,
    }


def main() -> None:
    if not BY_TECH.exists():
        print(f"No by-tech folder at {BY_TECH}. Run _audit-all-clients.py first.")
        return

    results = []
    for d in sorted(BY_TECH.iterdir()):
        if not d.is_dir():
            continue
        eml, info = build_eml(d.name)
        if eml:
            results.append(info)
            print(f"  drafted: {info['display']:<20} -> {info['to']:<40}  flagged={info['flagged_entries']:>3} ({info['flagged_hours']:>5.1f}h) top={info['top_flag']}")
        else:
            print(f"  SKIPPED {d.name}: {info.get('error')}")

    # manifest
    manifest = BY_TECH / "email-drafts-manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "slug", "display", "to", "total_entries", "total_hours",
            "flagged_entries", "flagged_hours", "top_flag",
            "docx_attached", "csv_attached", "eml_path",
        ])
        w.writeheader()
        w.writerows(results)
    print(f"\nManifest: {manifest}")
    print(f"Total drafts: {len(results)}")
    print(f"\nNext steps:")
    print(f"  1. Open each .eml in Outlook to preview (double-click).")
    print(f"  2. If any TO addresses are wrong, edit EMAIL_OVERRIDES dict in this script and re-run.")
    print(f"  3. Send from Outlook (each .eml opens as a new draft because of X-Unsent: 1 header).")


if __name__ == "__main__":
    main()
