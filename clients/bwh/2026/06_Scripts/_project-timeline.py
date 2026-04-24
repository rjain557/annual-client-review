"""Project-hour timeline: which months carried the most Project: work."""
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # clients/BWH/
HERE = ROOT / "03_Accounting"

month_proj = defaultdict(float)
month_total = defaultdict(float)
proj_monthly_cat = defaultdict(lambda: defaultdict(float))

with (HERE / "work-categories-by-month.csv").open("r", encoding="utf-8", newline="") as f:
    reader = csv.reader(f)
    header = next(reader)
    proj_idx = [i for i, h in enumerate(header) if h.startswith("Project:")]
    for row in reader:
        m = row[0]
        if m == "TOTAL":
            continue
        tot = float(row[-1])
        proj = sum(float(row[i]) for i in proj_idx)
        month_proj[m] = proj
        month_total[m] = tot
        for i in proj_idx:
            proj_monthly_cat[m][header[i]] += float(row[i])

print(f"{'Month':<10}{'Total':>8}{'Project':>10}{'%':>6}  top project category")
for m in sorted(month_total):
    proj = month_proj[m]
    tot = month_total[m]
    pct = (proj / tot * 100) if tot else 0
    top = ""
    if proj_monthly_cat[m]:
        tc = max(proj_monthly_cat[m].items(), key=lambda kv: kv[1])
        if tc[1] > 0:
            top = f"{tc[1]:5.1f}h  {tc[0][9:]}"
    print(f"{m:<10}{tot:8.1f}{proj:10.1f}{pct:5.0f}%  {top}")

# top 10 project-heavy months
print("\n=== TOP 10 PROJECT-HEAVY MONTHS ===")
for m, proj in sorted(month_proj.items(), key=lambda kv: -kv[1])[:10]:
    cats = sorted(proj_monthly_cat[m].items(), key=lambda kv: -kv[1])[:3]
    c_str = "; ".join(f"{v:.1f}h {k[9:]}" for k, v in cats if v > 0)
    print(f"  {m}: {proj:5.1f}h project of {month_total[m]:5.1f}h total — {c_str}")
