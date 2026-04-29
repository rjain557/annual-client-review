"""Audit the pulled week of time entries.

Reads the per-client CSVs written by 1_pull_weekly.py, runs the same H1-H5
flagging logic the annual audit uses, and writes:

  technijian/weekly-audit/<cycle>/
    SUMMARY.md                       cross-client weekly rollup
    all-flagged-entries.csv          master CSV (every flagged entry, with InvDetID)
    by-client/<client>/
      tech-outliers-summary.md
      tech-outliers-detail.csv
      tech-outliers-by-tech.csv
    by-tech/<tech-slug>/
      flagged-entries.csv            with coaching columns
      training.md                    personalized weekly training notes

  technijian/weekly-audit/by-tech/<tech-slug>/history.csv   (rolling, append)

Usage:
    python 2_audit_weekly.py
    python 2_audit_weekly.py --cycle 2026-W18
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _shared import (
    BY_TECH_HISTORY,
    TECH_TRAINING_SCRIPTS,
    cycle_dir,
    cycle_id_for,
    flag_entries,
    normalize_entry,
    slugify,
    write_csv,
    write_json,
)

# Import the existing coaching engine
_spec = importlib.util.spec_from_file_location("coaching", TECH_TRAINING_SCRIPTS / "_coaching.py")
_coach_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_coach_mod)
build_coaching = _coach_mod.build_coaching


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycle", help="cycle ID (default = current ISO week)")
    return ap.parse_args()


def load_pulled_entries(cycle_root: Path) -> list[dict]:
    raw_dir = cycle_root / "raw"
    if not raw_dir.exists():
        return []
    entries = []
    for client_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        code = client_dir.name
        csv_path = client_dir / "time_entries.csv"
        if not csv_path.exists():
            continue
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ent = normalize_entry(row, code)
                if ent:
                    entries.append(ent)
    return entries


def write_client_artifacts(out: Path, client: str, entries: list[dict],
                            flagged: list[dict]) -> dict:
    out.mkdir(parents=True, exist_ok=True)

    tech_totals = defaultdict(lambda: {"entries": 0, "hours": 0.0})
    for e in entries:
        t = tech_totals[e["Tech"]]
        t["entries"] += 1
        t["hours"] += e["Hours"]
    tech_agg = defaultdict(lambda: {"count": 0, "hours": 0.0, "flags": defaultdict(int)})
    for e in flagged:
        a = tech_agg[e["Tech"]]
        a["count"] += 1
        a["hours"] += e["Hours"]
        for code in e["FlagCodes"].split(";"):
            a["flags"][code] += 1

    rows = []
    for tech, agg in tech_agg.items():
        tot = tech_totals[tech]
        pct = (agg["hours"] / tot["hours"] * 100) if tot["hours"] else 0
        rows.append([tech, tot["entries"], round(tot["hours"], 2),
                     agg["count"], round(agg["hours"], 2), f"{pct:.1f}%",
                     agg["flags"].get("H1", 0), agg["flags"].get("H2", 0),
                     agg["flags"].get("H3", 0), agg["flags"].get("H4", 0),
                     agg["flags"].get("H5", 0)])
    rows.sort(key=lambda r: -r[4])
    with (out / "tech-outliers-by-tech.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Tech", "TotalEntries", "TotalHours", "FlaggedEntries",
                    "FlaggedHours", "FlaggedPctOfHours",
                    "H1_trivial_high", "H2_vague_title", "H3_entry>8h",
                    "H4_day>12h", "H5_dupe_day"])
        w.writerows(rows)

    with (out / "tech-outliers-detail.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["InvDetID", "Date", "Tech", "POD", "Shift", "Title", "Category",
                    "Hours", "CategoryCap", "DailyTotal", "Flags", "Reasons", "Requestor"])
        for e in sorted(flagged, key=lambda x: (-x["Hours"], x["Date"])):
            w.writerow([e.get("InvDetID", ""), e["Date"], e["Tech"], e["POD"], e["Shift"],
                        e["Title"], e["Category"], round(e["Hours"], 2), e["Cap"],
                        e["DailyTotal"], e["FlagCodes"], e["FlagReasons"], e["Requestor"]])

    total_h = sum(e["Hours"] for e in entries)
    flag_h = sum(e["Hours"] for e in flagged)
    with (out / "tech-outliers-summary.md").open("w", encoding="utf-8") as f:
        f.write(f"# {client.upper()} - Weekly Tech Time-Entry Review\n\n")
        f.write(f"**Entries scanned:** {len(entries):,}  \n")
        f.write(f"**Hours:** {total_h:,.2f}  \n")
        f.write(f"**Flagged entries:** {len(flagged):,} ({len(flagged)/max(len(entries),1)*100:.1f}%)  \n")
        f.write(f"**Flagged hours:** {flag_h:,.2f} ({flag_h/max(total_h,0.01)*100:.1f}%)  \n\n")
        if rows:
            f.write("## Techs ranked by flagged hours\n\n")
            f.write("| Tech | Total hrs | Flagged hrs | % | H1 | H2 | H3 | H4 | H5 |\n")
            f.write("|---|---:|---:|---:|---:|---:|---:|---:|---:|\n")
            for r in rows:
                f.write(f"| {r[0]} | {r[2]:,.1f} | {r[4]:,.1f} | {r[5]} | "
                        f"{r[6]} | {r[7]} | {r[8]} | {r[9]} | {r[10]} |\n")
    return {"client": client, "entries": len(entries), "hours": total_h,
            "flagged_entries": len(flagged), "flagged_hours": flag_h,
            "pct": (flag_h / total_h * 100) if total_h else 0}


def write_tech_artifacts(out_dir: Path, history_dir: Path, cycle: str,
                          tech: str, tech_entries: list[dict],
                          flagged_for_tech: list[dict]) -> dict:
    slug = slugify(tech)
    folder = out_dir / slug
    folder.mkdir(parents=True, exist_ok=True)

    # Detailed flagged-entries CSV with coaching columns + InvDetID for portal navigation
    with (folder / "flagged-entries.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["InvDetID", "Client", "Date", "Title", "Category", "Hours",
                    "CategoryCap", "DailyTotal", "Flags", "Reasons",
                    "Why_Flagged", "Suggested_Adjusted_Hours",
                    "Suggested_Title_If_Hours_Stay",
                    "Title_Must_Include"])
        for e in sorted(flagged_for_tech, key=lambda x: (-x["Hours"], x["Date"])):
            coach = build_coaching(e["Title"], e["Category"], e["Hours"])
            suggested_hours = min(e["Hours"], e["Cap"])
            w.writerow([
                e.get("InvDetID", ""),
                e["Client"].upper(),
                e["Date"],
                e["Title"],
                e["Category"],
                round(e["Hours"], 2),
                e["Cap"],
                e["DailyTotal"],
                e["FlagCodes"],
                e["FlagReasons"],
                coach["WhyFlagged"],
                f"{suggested_hours:.2f}",
                coach["GoodExample_Justified"],
                coach["MustInclude"],
            ])

    # Aggregates
    total_h = sum(e["Hours"] for e in tech_entries)
    flag_h = sum(e["Hours"] for e in flagged_for_tech)
    flag_n = len(flagged_for_tech)
    tot_n = len(tech_entries)

    flag_code_counts = defaultdict(int)
    cat_counts = defaultdict(lambda: {"n": 0, "h": 0.0})
    client_counts = defaultdict(lambda: {"n": 0, "h": 0.0})
    for e in flagged_for_tech:
        for c in e["FlagCodes"].split(";"):
            flag_code_counts[c] += 1
        cat_counts[e["Category"]]["n"] += 1
        cat_counts[e["Category"]]["h"] += e["Hours"]
        client_counts[e["Client"]]["n"] += 1
        client_counts[e["Client"]]["h"] += e["Hours"]

    # Personalized weekly training markdown
    with (folder / "training.md").open("w", encoding="utf-8") as f:
        f.write(f"# Weekly Tech Training - {tech}\n\n")
        f.write(f"**Cycle:** {cycle}  \n")
        f.write(f"**Total entries this week:** {tot_n:,}  \n")
        f.write(f"**Total hours this week:** {total_h:,.2f}  \n")
        f.write(f"**Flagged entries:** {flag_n} ({flag_n/max(tot_n,1)*100:.1f}%)  \n")
        f.write(f"**Flagged hours:** {flag_h:,.2f} ({flag_h/max(total_h,0.01)*100:.1f}%)  \n\n")

        f.write("## What to do before tonight's invoice run\n\n")
        f.write("For each flagged entry below, choose ONE:\n\n")
        f.write("1. **Adjust the hours down** to the suggested amount (you will not be paid "
                "for the difference, but the entry stays on the invoice as-is).\n")
        f.write("2. **Rewrite the title** to justify the hours actually logged "
                "(use the suggested title in the CSV as a starting point).\n\n")
        f.write("If neither change is made, the entry will appear on tonight's client invoice "
                "exactly as written and may be questioned by the client during their review.\n\n")

        f.write("## Flags breakdown\n\n")
        f.write("| Code | Count | Meaning |\n|---|---:|---|\n")
        legend = {"H1": "Routine work with hours exceeding category cap",
                  "H2": "Vague title (\"Help\", \"Fix\", etc.) with > 0.5h",
                  "H3": "Single entry > 8 hours",
                  "H4": "Tech daily total > 12 hours",
                  "H5": "Duplicate same-ticket same-day stacks"}
        for code in ["H1", "H2", "H3", "H4", "H5"]:
            if flag_code_counts[code]:
                f.write(f"| {code} | {flag_code_counts[code]} | {legend[code]} |\n")

        if client_counts:
            f.write("\n## Flagged entries by client\n\n")
            f.write("| Client | # flagged | Flagged hours |\n|---|---:|---:|\n")
            for c, v in sorted(client_counts.items(), key=lambda kv: -kv[1]["h"]):
                f.write(f"| {c.upper()} | {v['n']} | {v['h']:,.2f} |\n")

        f.write("\n## All your flagged entries this week\n\n")
        f.write("| Client | Date | Hours | Cap | Title | Reason |\n|---|---|---:|---:|---|---|\n")
        for e in sorted(flagged_for_tech, key=lambda x: -x["Hours"]):
            t = e["Title"].replace("|", "\\|")[:60]
            r = e["FlagReasons"].replace("|", "\\|")[:80]
            f.write(f"| {e['Client'].upper()} | {e['Date']} | {e['Hours']:.2f} | "
                    f"{e['Cap']} | {t} | {r} |\n")

        f.write("\n## Suggested rewrites (top 8)\n\n")
        for e in sorted(flagged_for_tech, key=lambda x: -x["Hours"])[:8]:
            coach = build_coaching(e["Title"], e["Category"], e["Hours"])
            suggested_hours = min(e["Hours"], e["Cap"])
            f.write(f"### {e['Client'].upper()} {e['Date']} - "
                    f"\"{e['Title'][:80]}\" ({e['Hours']:.2f}h)\n\n")
            f.write(f"- **Category:** {e['Category']}  \n")
            f.write(f"- **Why flagged:** {coach['WhyFlagged']}  \n")
            f.write(f"- **A good title must include:** {coach['MustInclude']}\n\n")
            f.write(f"**Option A - keep hours, rewrite title:**\n")
            f.write(f"> {coach['GoodExample_Justified']}\n\n")
            f.write(f"**Option B - drop hours to {suggested_hours:.2f}h, keep title or use:**\n")
            f.write(f"> {coach['GoodExample_AtCap']}\n\n")

    # Append to rolling history (per-tech CSV across all cycles - for pattern detection)
    history_file = history_dir / slug / "history.csv"
    history_file.parent.mkdir(parents=True, exist_ok=True)
    write_header = not history_file.exists()
    with history_file.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["Cycle", "InvDetID", "Client", "Date", "Title", "Category",
                        "Hours", "Cap", "Flags", "Reasons"])
        for e in flagged_for_tech:
            w.writerow([cycle, e.get("InvDetID", ""), e["Client"].upper(), e["Date"],
                        e["Title"], e["Category"], round(e["Hours"], 2), e["Cap"],
                        e["FlagCodes"], e["FlagReasons"]])

    return {"tech": tech, "slug": slug, "total_entries": tot_n,
            "total_hours": total_h, "flagged_entries": flag_n,
            "flagged_hours": flag_h}


def main() -> int:
    args = parse_args()
    cycle = args.cycle or cycle_id_for()
    cycle_root = cycle_dir(cycle)

    print(f"[{datetime.now():%H:%M:%S}] auditing cycle {cycle}")
    entries = load_pulled_entries(cycle_root)
    if not entries:
        print(f"  no pulled entries found under {cycle_root / 'raw'}.")
        print(f"  run 1_pull_weekly.py --cycle {cycle} first.")
        return 1
    print(f"  loaded {len(entries):,} entries from {cycle_root / 'raw'}")

    # Flag (single pass over the full week)
    flagged = flag_entries(entries)
    print(f"  flagged {len(flagged):,} entries")

    # Per-client artifacts
    by_client_root = cycle_root / "by-client"
    per_client_entries = defaultdict(list)
    per_client_flagged = defaultdict(list)
    for e in entries:
        per_client_entries[e["Client"]].append(e)
    for e in flagged:
        per_client_flagged[e["Client"]].append(e)

    client_rollup = []
    for client, ents in sorted(per_client_entries.items()):
        flgs = per_client_flagged.get(client, [])
        info = write_client_artifacts(by_client_root / client, client, ents, flgs)
        client_rollup.append(info)
        print(f"    {client:<8s} entries={info['entries']:4d} hrs={info['hours']:6.1f} "
              f"flagged={info['flagged_entries']:3d} ({info['flagged_hours']:5.1f}h)")

    # Per-tech artifacts (only for techs with at least one flagged entry)
    by_tech_root = cycle_root / "by-tech"
    per_tech_entries = defaultdict(list)
    per_tech_flagged = defaultdict(list)
    for e in entries:
        per_tech_entries[e["Tech"]].append(e)
    for e in flagged:
        per_tech_flagged[e["Tech"]].append(e)

    tech_summaries = []
    for tech in sorted(per_tech_flagged.keys()):
        if not per_tech_flagged[tech]:
            continue
        info = write_tech_artifacts(by_tech_root, BY_TECH_HISTORY, cycle, tech,
                                     per_tech_entries[tech], per_tech_flagged[tech])
        tech_summaries.append(info)

    # Master flagged CSV
    with (cycle_root / "all-flagged-entries.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["InvDetID", "Client", "Date", "Tech", "Title", "Category", "Hours",
                    "CategoryCap", "DailyTotal", "Flags", "Reasons"])
        for e in sorted(flagged, key=lambda x: (x["Client"], -x["Hours"])):
            w.writerow([e.get("InvDetID", ""), e["Client"].upper(), e["Date"],
                        e["Tech"], e["Title"], e["Category"], round(e["Hours"], 2),
                        e["Cap"], e["DailyTotal"], e["FlagCodes"], e["FlagReasons"]])

    # Top-level SUMMARY.md
    total_entries = len(entries)
    total_hours = sum(e["Hours"] for e in entries)
    total_flagged = len(flagged)
    total_flag_hours = sum(e["Hours"] for e in flagged)
    with (cycle_root / "SUMMARY.md").open("w", encoding="utf-8") as f:
        f.write(f"# Technijian Weekly Tech Time-Entry Audit - {cycle}\n\n")
        f.write(f"**Generated:** {datetime.now().isoformat(timespec='seconds')}\n\n")
        f.write(f"## Scope\n\n")
        f.write(f"- Clients with entries: {len(client_rollup)}\n")
        f.write(f"- Entries scanned: {total_entries:,}\n")
        f.write(f"- Hours scanned: {total_hours:,.2f}\n")
        f.write(f"- Flagged entries: {total_flagged} ({total_flagged/max(total_entries,1)*100:.1f}%)\n")
        f.write(f"- Flagged hours: {total_flag_hours:,.2f} "
                f"({total_flag_hours/max(total_hours,0.01)*100:.1f}%)\n\n")

        f.write(f"## Per-client rollup\n\n")
        f.write("| Client | Entries | Hours | Flagged Entries | Flagged Hours | % Flagged |\n")
        f.write("|---|---:|---:|---:|---:|---:|\n")
        for c in sorted(client_rollup, key=lambda x: -x["flagged_hours"]):
            f.write(f"| {c['client'].upper()} | {c['entries']:,} | {c['hours']:,.1f} | "
                    f"{c['flagged_entries']} | {c['flagged_hours']:,.1f} | {c['pct']:.1f}% |\n")

        if tech_summaries:
            f.write(f"\n## Per-tech ({len(tech_summaries)} techs flagged)\n\n")
            f.write("| Tech | Total hrs | Flagged hrs | Flagged entries |\n")
            f.write("|---|---:|---:|---:|\n")
            for s in sorted(tech_summaries, key=lambda x: -x["flagged_hours"]):
                f.write(f"| {s['tech']} | {s['total_hours']:,.1f} | "
                        f"{s['flagged_hours']:,.1f} | {s['flagged_entries']} |\n")

    write_json(cycle_root / "audit_log.json", {
        "cycle": cycle,
        "ran_at": datetime.now().isoformat(timespec="seconds"),
        "entries_scanned": total_entries,
        "hours_scanned": round(total_hours, 2),
        "flagged_entries": total_flagged,
        "flagged_hours": round(total_flag_hours, 2),
        "techs_flagged": len(tech_summaries),
        "clients_with_data": len(client_rollup),
    })

    print(f"\n[{datetime.now():%H:%M:%S}] DONE")
    print(f"  flagged: {total_flagged} entries / {total_flag_hours:.1f}h "
          f"across {len(tech_summaries)} techs")
    print(f"  outputs: {cycle_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
