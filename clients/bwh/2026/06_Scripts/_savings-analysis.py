"""Per-project savings vs. $150/hr proposal rate.

The point: if these projects had been quoted as separate SOWs / T&M proposals,
they would have been billed at $150/hr for every hour — regardless of whether
the work was delivered from India or the USA pod. Because they were absorbed
into the monthly support stream, the client avoided that premium proposal
billing. This script computes per-project:
  - hours by pod (India vs USA)
  - hypothetical proposal cost at $150/hr
  - India vs USA contribution to savings
"""
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # clients/BWH/
HERE = ROOT / "03_Accounting"
SRC = HERE / "project-candidate-tickets.csv"

PROPOSAL_RATE = 150.00   # per contract 4924, over-contract / proposal T&M rate

proj_hours = defaultdict(lambda: defaultdict(float))   # category -> bucket -> hours
proj_total = defaultdict(float)
# role = "India NH" / "India AH" / "USA NH" / "USA AH"
# bucket = "India" or "USA"

with SRC.open("r", encoding="utf-8", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        cat = row.get("Category", "").strip()
        role = row.get("Role", "").strip()
        hrs = float(row.get("Hours") or 0)
        if role.startswith("India"):
            bucket = "India"
        elif role.startswith("USA"):
            bucket = "USA"
        else:
            bucket = "Other"
        proj_hours[cat][bucket] += hrs
        proj_hours[cat]["Total"] += hrs
        proj_total[cat] += hrs

grand_total_hrs = sum(proj_total.values())
grand_india = sum(proj_hours[c]["India"] for c in proj_hours)
grand_usa   = sum(proj_hours[c]["USA"] for c in proj_hours)

# sort by total hours descending
sorted_cats = sorted(proj_total.items(), key=lambda kv: -kv[1])

print(f"Proposal rate assumed: ${PROPOSAL_RATE:.2f}/hr (USA + India both)\n")
print(f"{'Project':<60}{'India':>8}{'USA':>8}{'Total':>8}{'Proposal':>12}")
print("-" * 96)
for cat, tot in sorted_cats:
    ind = proj_hours[cat]["India"]
    usa = proj_hours[cat]["USA"]
    cost = tot * PROPOSAL_RATE
    label = cat.replace("Project: ", "")[:58]
    print(f"{label:<60}{ind:>8.2f}{usa:>8.2f}{tot:>8.2f}{cost:>12,.2f}")
print("-" * 96)
print(f"{'TOTAL':<60}{grand_india:>8.2f}{grand_usa:>8.2f}{grand_total_hrs:>8.2f}{grand_total_hrs*PROPOSAL_RATE:>12,.2f}")

# Write CSV
out = HERE / "savings-per-project.csv"
with out.open("w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Project", "India_hrs", "USA_hrs", "Total_hrs",
                "Proposal_cost_at_150", "India_proposal_cost", "USA_proposal_cost"])
    for cat, tot in sorted_cats:
        ind = proj_hours[cat]["India"]
        usa = proj_hours[cat]["USA"]
        w.writerow([
            cat.replace("Project: ", ""),
            round(ind, 2), round(usa, 2), round(tot, 2),
            round(tot * PROPOSAL_RATE, 2),
            round(ind * PROPOSAL_RATE, 2),
            round(usa * PROPOSAL_RATE, 2),
        ])
    w.writerow(["TOTAL",
                round(grand_india, 2),
                round(grand_usa, 2),
                round(grand_total_hrs, 2),
                round(grand_total_hrs * PROPOSAL_RATE, 2),
                round(grand_india * PROPOSAL_RATE, 2),
                round(grand_usa * PROPOSAL_RATE, 2)])

print(f"\nWrote: {out}")
print(f"\nTotal project hours: {grand_total_hrs:.2f}")
print(f"  India: {grand_india:.2f} hrs ({grand_india/grand_total_hrs*100:.1f}%)")
print(f"  USA:   {grand_usa:.2f} hrs ({grand_usa/grand_total_hrs*100:.1f}%)")
print(f"\nHypothetical proposal value at ${PROPOSAL_RATE}/hr: ${grand_total_hrs*PROPOSAL_RATE:,.2f}")
