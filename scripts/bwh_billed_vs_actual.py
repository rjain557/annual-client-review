"""
BWH Billed vs Actual Hours Analysis
====================================
Compares contracted/billed labor hours from monthly invoices against
actual hours worked from time entries for each role category.

Contract adjustment context (April/May 2025):
  - US Tech Support (IRV-TS1, $125/hr): ~18.2 -> ~12.4 hrs/mo
  - Offshore NH (CHD-TS1, $15/hr): ~37.5 -> ~51.6 hrs/mo
  - Offshore AH (CHD-TS1 AH, $30/hr): ~38.9 -> ~45.4 hrs/mo
  - Systems Architect (IRV-AD1, $200/hr): flat at 5 hrs/mo
"""

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

pd.set_option('display.max_columns', 20)
pd.set_option('display.width', 200)
pd.set_option('display.float_format', lambda x: f'{x:.2f}')

BASE = r'c:\vscode\annual-client-review\annual-client-review\clients\bwh\2025'

# ============================================================================
# LOAD DATA
# ============================================================================
inv = pd.read_excel(f'{BASE}/allinv_items_too_bwh.xlsx')
time = pd.read_excel(f'{BASE}/all-ticket_timeE_bwh_2025.xlsx')

inv['InvoiceDate'] = pd.to_datetime(inv['InvoiceDate'])
inv['Month'] = inv['InvoiceDate'].dt.month
inv['MonthName'] = inv['InvoiceDate'].dt.strftime('%b')

time['StartDateTime'] = pd.to_datetime(time['StartDateTime'])
time['Month'] = time['StartDateTime'].dt.month
time['MonthName'] = time['StartDateTime'].dt.strftime('%b')

# Handle NaN in hours columns (already float64 with NaN, not string "NULL")
for col in ['NH_HoursWorked', 'AH_HoursWorked', 'Onsite_HoursWorked']:
    time[col] = pd.to_numeric(time[col], errors='coerce').fillna(0)

# ============================================================================
# SECTION 1: MONTHLY BILLED HOURS BY ROLE (from monthly invoices)
# ============================================================================
print("=" * 120)
print("SECTION 1: MONTHLY BILLED (CONTRACTED) HOURS BY ROLE")
print("Source: Monthly recurring invoice line items (price > 0)")
print("=" * 120)

# The billed hours come from the recurring monthly invoice items with a price > 0
# Items: Tech_Support.R ($125), OffShore_Support.R ($15), OffShore_Support.R.AF ($30), Systems_Architect.R ($200)
billed_items = inv[
    (inv['Item'].isin(['Tech_Support.R', 'OffShore_Support.R', 'OffShore_Support.R.AF', 'Systems_Architect.R'])) &
    (inv['price'] > 0)
].copy()

# Map items to role labels
item_map = {
    'Tech_Support.R': 'IT Support (IRV-TS1 $125)',
    'OffShore_Support.R': 'Offshore NH (CHD-TS1 $15)',
    'OffShore_Support.R.AF': 'Offshore AH (CHD-TS1 $30)',
    'Systems_Architect.R': 'Sys Architect (IRV-AD1 $200)'
}
billed_items['Role'] = billed_items['Item'].map(item_map)

# For May there are adjustment lines + regular lines. Sum them per month per role.
billed_monthly = billed_items.groupby(['Month', 'MonthName', 'Role'])['qty'].sum().reset_index()
billed_pivot = billed_monthly.pivot_table(index=['Month', 'MonthName'], columns='Role', values='qty', fill_value=0)

# Ensure columns are in a logical order
role_order = [
    'IT Support (IRV-TS1 $125)',
    'Offshore NH (CHD-TS1 $15)',
    'Offshore AH (CHD-TS1 $30)',
    'Sys Architect (IRV-AD1 $200)'
]
billed_pivot = billed_pivot.reindex(columns=role_order, fill_value=0)
billed_pivot['Total Billed'] = billed_pivot.sum(axis=1)

month_names = {1:'Jan',2:'Feb',3:'Mar',4:'Apr',5:'May',6:'Jun',7:'Jul',8:'Aug',9:'Sep',10:'Oct',11:'Nov',12:'Dec'}

print("\n{:<6} {:>22} {:>22} {:>22} {:>24} {:>14}".format(
    'Month', 'IT Support', 'Offshore NH', 'Offshore AH', 'Sys Architect', 'TOTAL'))
print("-" * 120)
for idx, row in billed_pivot.iterrows():
    mo = idx[1]
    print("{:<6} {:>22.2f} {:>22.2f} {:>22.2f} {:>24.2f} {:>14.2f}".format(
        mo, row.iloc[0], row.iloc[1], row.iloc[2], row.iloc[3], row.iloc[4]))
print("-" * 120)
print("{:<6} {:>22.2f} {:>22.2f} {:>22.2f} {:>24.2f} {:>14.2f}".format(
    'TOTAL',
    billed_pivot.iloc[:,0].sum(),
    billed_pivot.iloc[:,1].sum(),
    billed_pivot.iloc[:,2].sum(),
    billed_pivot.iloc[:,3].sum(),
    billed_pivot.iloc[:,4].sum()))

# ============================================================================
# SECTION 2: MONTHLY ACTUAL HOURS BY ROLE TYPE (from time entries)
# ============================================================================
print("\n\n" + "=" * 120)
print("SECTION 2: MONTHLY ACTUAL HOURS WORKED BY ROLE")
print("Source: Time entries (ticket_timeE)")
print("  RoleType 1232 (Tech Support): NH + Onsite hours")
print("  RoleType 1236 (Off-Shore): NH hours = Offshore NH actual, AH hours = Offshore AH actual")
print("=" * 120)

# Tech Support (1232): NH + Onsite
tech = time[time['RoleType'] == 1232].copy()
tech_monthly = tech.groupby(['Month', 'MonthName']).agg(
    IT_Support_NH=('NH_HoursWorked', 'sum'),
    IT_Support_Onsite=('Onsite_HoursWorked', 'sum')
).reset_index()
tech_monthly['IT Support Actual'] = tech_monthly['IT_Support_NH'] + tech_monthly['IT_Support_Onsite']

# Offshore (1236): NH = offshore NH hours, AH = offshore AH hours
offshore = time[time['RoleType'] == 1236].copy()
offshore_monthly = offshore.groupby(['Month', 'MonthName']).agg(
    Offshore_NH_Actual=('NH_HoursWorked', 'sum'),
    Offshore_AH_Actual=('AH_HoursWorked', 'sum')
).reset_index()

# Merge
actual = pd.merge(tech_monthly[['Month', 'MonthName', 'IT Support Actual']],
                  offshore_monthly[['Month', 'Offshore_NH_Actual', 'Offshore_AH_Actual']],
                  on='Month', how='outer').fillna(0)
actual['Total Actual'] = actual['IT Support Actual'] + actual['Offshore_NH_Actual'] + actual['Offshore_AH_Actual']

# Sort
actual = actual.sort_values('Month')

print("\n{:<6} {:>22} {:>22} {:>22} {:>14}".format(
    'Month', 'IT Support', 'Offshore NH', 'Offshore AH', 'TOTAL'))
print("-" * 90)
for _, row in actual.iterrows():
    mo = month_names.get(int(row['Month']), '?')
    print("{:<6} {:>22.2f} {:>22.2f} {:>22.2f} {:>14.2f}".format(
        mo,
        row['IT Support Actual'],
        row['Offshore_NH_Actual'],
        row['Offshore_AH_Actual'],
        row['Total Actual']))
print("-" * 90)
print("{:<6} {:>22.2f} {:>22.2f} {:>22.2f} {:>14.2f}".format(
    'TOTAL',
    actual['IT Support Actual'].sum(),
    actual['Offshore_NH_Actual'].sum(),
    actual['Offshore_AH_Actual'].sum(),
    actual['Total Actual'].sum()))

# NOTE: Systems Architect has no separate RoleType in time entries; they're not tracked
# separately, so we focus on the three labor categories.

# ============================================================================
# SECTION 3: BILLED vs ACTUAL COMPARISON (side by side, per month)
# ============================================================================
print("\n\n" + "=" * 140)
print("SECTION 3: BILLED vs ACTUAL COMPARISON TABLE (Jan-Dec 2025)")
print("  Positive over/under = OVER-billed (billed > actual = client paying for unused hours)")
print("  Negative over/under = UNDER-billed (actual > billed = we are giving away hours)")
print("=" * 140)

# Build comparison DataFrame
comp = pd.DataFrame()
for mo in range(1, 13):
    mo_name = month_names[mo]

    # Billed
    billed_row = billed_pivot.loc[billed_pivot.index.get_level_values(0) == mo]
    if len(billed_row) > 0:
        b_it = billed_row.iloc[0, 0]
        b_nh = billed_row.iloc[0, 1]
        b_ah = billed_row.iloc[0, 2]
        b_sa = billed_row.iloc[0, 3]
    else:
        b_it = b_nh = b_ah = b_sa = 0

    # Actual
    actual_row = actual[actual['Month'] == mo]
    if len(actual_row) > 0:
        a_it = actual_row['IT Support Actual'].values[0]
        a_nh = actual_row['Offshore_NH_Actual'].values[0]
        a_ah = actual_row['Offshore_AH_Actual'].values[0]
    else:
        a_it = a_nh = a_ah = 0

    b_total = b_it + b_nh + b_ah + b_sa
    a_total = a_it + a_nh + a_ah  # no SA actuals tracked

    comp = pd.concat([comp, pd.DataFrame([{
        'Month': mo_name,
        'Billed_IT': b_it, 'Actual_IT': a_it, 'Delta_IT': b_it - a_it,
        'Billed_NH': b_nh, 'Actual_NH': a_nh, 'Delta_NH': b_nh - a_nh,
        'Billed_AH': b_ah, 'Actual_AH': a_ah, 'Delta_AH': b_ah - a_ah,
        'Billed_SA': b_sa,
        'Billed_Total': b_total, 'Actual_Total': a_total, 'Delta_Total': b_total - a_total
    }])], ignore_index=True)

# Print IT Support
print("\n--- IT SUPPORT (IRV-TS1, $125/hr) ---")
print("{:<6} {:>10} {:>10} {:>10} {:>10}".format('Month', 'Billed', 'Actual', 'Delta', 'Util%'))
print("-" * 50)
for _, r in comp.iterrows():
    util = (r['Actual_IT'] / r['Billed_IT'] * 100) if r['Billed_IT'] > 0 else 0
    print("{:<6} {:>10.2f} {:>10.2f} {:>+10.2f} {:>9.0f}%".format(
        r['Month'], r['Billed_IT'], r['Actual_IT'], r['Delta_IT'], util))

print("\n--- OFFSHORE NH (CHD-TS1, $15/hr) ---")
print("{:<6} {:>10} {:>10} {:>10} {:>10}".format('Month', 'Billed', 'Actual', 'Delta', 'Util%'))
print("-" * 50)
for _, r in comp.iterrows():
    util = (r['Actual_NH'] / r['Billed_NH'] * 100) if r['Billed_NH'] > 0 else 0
    print("{:<6} {:>10.2f} {:>10.2f} {:>+10.2f} {:>9.0f}%".format(
        r['Month'], r['Billed_NH'], r['Actual_NH'], r['Delta_NH'], util))

print("\n--- OFFSHORE AH (CHD-TS1 AH, $30/hr) ---")
print("{:<6} {:>10} {:>10} {:>10} {:>10}".format('Month', 'Billed', 'Actual', 'Delta', 'Util%'))
print("-" * 50)
for _, r in comp.iterrows():
    util = (r['Actual_AH'] / r['Billed_AH'] * 100) if r['Billed_AH'] > 0 else 0
    print("{:<6} {:>10.2f} {:>10.2f} {:>+10.2f} {:>9.0f}%".format(
        r['Month'], r['Billed_AH'], r['Actual_AH'], r['Delta_AH'], util))

# Grand summary
print("\n--- MONTHLY TOTALS (all labor excl. Sys Architect) ---")
print("{:<6} {:>10} {:>10} {:>10} {:>10}  {:>12}".format(
    'Month', 'Billed', 'Actual', 'Delta', 'Util%', 'Billed $'))
print("-" * 65)
for _, r in comp.iterrows():
    util = (r['Actual_Total'] / (r['Billed_Total'] - r['Billed_SA']) * 100) if (r['Billed_Total'] - r['Billed_SA']) > 0 else 0
    billed_cost = r['Billed_IT']*125 + r['Billed_NH']*15 + r['Billed_AH']*30 + r['Billed_SA']*200
    print("{:<6} {:>10.2f} {:>10.2f} {:>+10.2f} {:>9.0f}%  ${:>11,.2f}".format(
        r['Month'], r['Billed_Total'] - r['Billed_SA'], r['Actual_Total'],
        (r['Billed_Total'] - r['Billed_SA']) - r['Actual_Total'], util, billed_cost))

# ============================================================================
# SECTION 4: CURRENT CYCLE ANALYSIS (May-Dec 2025, post-adjustment)
# ============================================================================
print("\n\n" + "=" * 140)
print("SECTION 4: CURRENT CYCLE DEEP DIVE (May-Dec 2025 -- Post-Adjustment)")
print("=" * 140)

current = comp[comp['Month'].isin(['May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'])].copy()
n_months = len(current)

print(f"\nMonths in current cycle: {n_months}")

# Average monthly billed/actual per role
print("\n--- AVERAGE MONTHLY HOURS (May-Dec 2025) ---")
print("{:<25} {:>12} {:>12} {:>12} {:>12}".format(
    'Role', 'Avg Billed', 'Avg Actual', 'Avg Delta', 'Util Rate'))
print("-" * 80)

roles = [
    ('IT Support ($125)', 'Billed_IT', 'Actual_IT', 'Delta_IT'),
    ('Offshore NH ($15)', 'Billed_NH', 'Actual_NH', 'Delta_NH'),
    ('Offshore AH ($30)', 'Billed_AH', 'Actual_AH', 'Delta_AH'),
]
for label, bc, ac, dc in roles:
    avg_b = current[bc].mean()
    avg_a = current[ac].mean()
    avg_d = current[dc].mean()
    util = (avg_a / avg_b * 100) if avg_b > 0 else 0
    print("{:<25} {:>12.2f} {:>12.2f} {:>+12.2f} {:>11.0f}%".format(
        label, avg_b, avg_a, avg_d, util))

# Totals
avg_b_total = sum(current[bc].mean() for _, bc, _, _ in roles)
avg_a_total = sum(current[ac].mean() for _, _, ac, _ in roles)
util_total = (avg_a_total / avg_b_total * 100) if avg_b_total > 0 else 0
print("-" * 80)
print("{:<25} {:>12.2f} {:>12.2f} {:>+12.2f} {:>11.0f}%".format(
    'TOTAL (excl SA)', avg_b_total, avg_a_total, avg_b_total - avg_a_total, util_total))

# Trend analysis
print("\n--- MONTHLY TREND (May-Dec 2025) ---")
print("{:<6} {:>12} {:>14} {:>14}".format('Month', 'IT Actual', 'NH Actual', 'AH Actual'))
print("-" * 50)
for _, r in current.iterrows():
    print("{:<6} {:>12.2f} {:>14.2f} {:>14.2f}".format(
        r['Month'], r['Actual_IT'], r['Actual_NH'], r['Actual_AH']))

# Compute trend: first half vs second half of current cycle
first_half = current.head(4)  # May-Aug
second_half = current.tail(4)  # Sep-Dec

print("\n--- TREND: 1st Half (May-Aug) vs 2nd Half (Sep-Dec) ---")
print("{:<25} {:>14} {:>14} {:>14}".format('Metric', 'May-Aug Avg', 'Sep-Dec Avg', 'Change'))
print("-" * 70)
for label, _, ac, _ in roles:
    fh = first_half[ac].mean()
    sh = second_half[ac].mean()
    chg = sh - fh
    direction = "UP" if chg > 0.5 else ("DOWN" if chg < -0.5 else "STABLE")
    print("{:<25} {:>14.2f} {:>14.2f} {:>+12.2f}  ({})".format(label, fh, sh, chg, direction))

# Recommended allotment based on actual usage + buffer
print("\n--- RECOMMENDED ALLOTMENT FOR NEXT CYCLE ---")
print("(Based on current cycle avg actual + 10% buffer, rounded to nearest 0.5)")
print("{:<25} {:>12} {:>12} {:>14} {:>12}".format(
    'Role', 'Avg Actual', 'Current Bil', 'Recommended', 'Change'))
print("-" * 80)

def round_half(x):
    return round(x * 2) / 2

recommendations = {}
for label, bc, ac, _ in roles:
    avg_a = current[ac].mean()
    avg_b = current[bc].mean()
    rec = round_half(avg_a * 1.10)  # 10% buffer
    recommendations[label] = (avg_a, avg_b, rec)
    chg = rec - avg_b
    print("{:<25} {:>12.2f} {:>12.2f} {:>14.1f} {:>+12.1f}".format(
        label, avg_a, avg_b, rec, chg))

# Systems Architect stays flat
print("{:<25} {:>12} {:>12} {:>14.1f} {:>+12.1f}".format(
    'Sys Architect ($200)', 'N/A', '5.00', 5.0, 0.0))

# ============================================================================
# SECTION 5: ANNUALIZED PROJECTION FOR 2026
# ============================================================================
print("\n\n" + "=" * 140)
print("SECTION 5: ANNUALIZED 2026 PROJECTION")
print("Based on current cycle (May-Dec 2025) utilization patterns")
print("=" * 140)

rates = {
    'IT Support ($125)': 125,
    'Offshore NH ($15)': 15,
    'Offshore AH ($30)': 30,
    'Sys Architect ($200)': 200,
}

print("\n--- 2026 MONTHLY LABOR ALLOTMENT OPTIONS ---")
print()

# Option A: Keep current contract as-is
print("OPTION A: KEEP CURRENT CONTRACT (no changes)")
print("{:<25} {:>10} {:>10} {:>14} {:>14}".format(
    'Role', 'Mo Hrs', 'Ann Hrs', 'Mo Cost', 'Ann Cost'))
print("-" * 80)
total_mo_a = 0
total_ann_a = 0
current_allotments = {
    'IT Support ($125)': 12.43,
    'Offshore NH ($15)': 51.56,
    'Offshore AH ($30)': 45.42,
    'Sys Architect ($200)': 5.00,
}
for role, hrs in current_allotments.items():
    rate = rates[role]
    mo_cost = hrs * rate
    ann_cost = mo_cost * 12
    total_mo_a += mo_cost
    total_ann_a += ann_cost
    print("{:<25} {:>10.2f} {:>10.2f} ${:>13,.2f} ${:>13,.2f}".format(
        role, hrs, hrs*12, mo_cost, ann_cost))
print("-" * 80)
print("{:<25} {:>10} {:>10} ${:>13,.2f} ${:>13,.2f}".format(
    'TOTAL', '', '', total_mo_a, total_ann_a))

print()

# Option B: Right-size to actual usage + 10% buffer
print("OPTION B: RIGHT-SIZE TO ACTUAL USAGE (+10% buffer)")
print("{:<25} {:>10} {:>10} {:>14} {:>14} {:>14}".format(
    'Role', 'Mo Hrs', 'Ann Hrs', 'Mo Cost', 'Ann Cost', 'vs Current'))
print("-" * 95)
total_mo_b = 0
total_ann_b = 0
right_sized = {}
for label, bc, ac, _ in roles:
    avg_a = current[ac].mean()
    rec = round_half(avg_a * 1.10)
    right_sized[label] = rec

right_sized['Sys Architect ($200)'] = 5.0

for role, hrs in right_sized.items():
    rate = rates[role]
    mo_cost = hrs * rate
    ann_cost = mo_cost * 12
    total_mo_b += mo_cost
    total_ann_b += ann_cost
    curr_cost = current_allotments[role] * rate * 12
    delta_cost = ann_cost - curr_cost
    print("{:<25} {:>10.1f} {:>10.1f} ${:>13,.2f} ${:>13,.2f} ${:>+13,.2f}".format(
        role, hrs, hrs*12, mo_cost, ann_cost, delta_cost))
print("-" * 95)
curr_total_ann = total_ann_a
delta_total = total_ann_b - curr_total_ann
print("{:<25} {:>10} {:>10} ${:>13,.2f} ${:>13,.2f} ${:>+13,.2f}".format(
    'TOTAL', '', '', total_mo_b, total_ann_b, delta_total))

print()

# Option C: Right-size to actual (no buffer) -- aggressive
print("OPTION C: TIGHT FIT (actual avg, no buffer - aggressive)")
print("{:<25} {:>10} {:>10} {:>14} {:>14} {:>14}".format(
    'Role', 'Mo Hrs', 'Ann Hrs', 'Mo Cost', 'Ann Cost', 'vs Current'))
print("-" * 95)
total_mo_c = 0
total_ann_c = 0
tight = {}
for label, bc, ac, _ in roles:
    avg_a = current[ac].mean()
    rec = round_half(avg_a)
    tight[label] = rec

tight['Sys Architect ($200)'] = 5.0

for role, hrs in tight.items():
    rate = rates[role]
    mo_cost = hrs * rate
    ann_cost = mo_cost * 12
    total_mo_c += mo_cost
    total_ann_c += ann_cost
    curr_cost = current_allotments[role] * rate * 12
    delta_cost = ann_cost - curr_cost
    print("{:<25} {:>10.1f} {:>10.1f} ${:>13,.2f} ${:>13,.2f} ${:>+13,.2f}".format(
        role, hrs, hrs*12, mo_cost, ann_cost, delta_cost))
print("-" * 95)
delta_total_c = total_ann_c - curr_total_ann
print("{:<25} {:>10} {:>10} ${:>13,.2f} ${:>13,.2f} ${:>+13,.2f}".format(
    'TOTAL', '', '', total_mo_c, total_ann_c, delta_total_c))

# ============================================================================
# SECTION 6: UTILIZATION HEATMAP (visual summary)
# ============================================================================
print("\n\n" + "=" * 140)
print("SECTION 6: UTILIZATION SUMMARY HEATMAP")
print("  < 80% = OVER-PROVISIONED  |  80-120% = RIGHT-SIZED  |  > 120% = UNDER-PROVISIONED")
print("=" * 140)

print("\n{:<6} {:>16} {:>16} {:>16}".format('Month', 'IT Support', 'Offshore NH', 'Offshore AH'))
print("-" * 58)
for _, r in comp.iterrows():
    vals = []
    for bc, ac in [('Billed_IT','Actual_IT'), ('Billed_NH','Actual_NH'), ('Billed_AH','Actual_AH')]:
        if r[bc] > 0:
            u = r[ac] / r[bc] * 100
            if u < 80:
                tag = f"{u:5.0f}% OVER"
            elif u > 120:
                tag = f"{u:5.0f}% UNDER"
            else:
                tag = f"{u:5.0f}% OK"
        else:
            tag = "  N/A"
        vals.append(tag)
    print("{:<6} {:>16} {:>16} {:>16}".format(r['Month'], vals[0], vals[1], vals[2]))

# Annual summary
print("\n" + "=" * 140)
print("EXECUTIVE SUMMARY")
print("=" * 140)

for label, bc, ac, _ in roles:
    full_year_b = comp[bc].sum()
    full_year_a = comp[ac].sum()
    curr_b = current[bc].sum()
    curr_a = current[ac].sum()
    curr_util = (curr_a / curr_b * 100) if curr_b > 0 else 0
    full_util = (full_year_a / full_year_b * 100) if full_year_b > 0 else 0

    print(f"\n{label}:")
    print(f"  Full Year:     Billed {full_year_b:>8.2f} hrs | Actual {full_year_a:>8.2f} hrs | Util {full_util:.0f}%")
    print(f"  Current Cycle: Billed {curr_b:>8.2f} hrs | Actual {curr_a:>8.2f} hrs | Util {curr_util:.0f}%")

    avg_a = current[ac].mean()
    avg_b = current[bc].mean()
    if curr_util < 80:
        print(f"  STATUS: OVER-PROVISIONED -- avg actual {avg_a:.1f} vs billed {avg_b:.1f}. Consider reducing.")
    elif curr_util > 120:
        print(f"  STATUS: UNDER-PROVISIONED -- avg actual {avg_a:.1f} vs billed {avg_b:.1f}. Consider increasing.")
    else:
        print(f"  STATUS: RIGHT-SIZED -- avg actual {avg_a:.1f} vs billed {avg_b:.1f}. No change needed.")

# Total cost impact
print(f"\n--- COST IMPACT SUMMARY ---")
print(f"  Current annual labor cost (Option A):  ${total_ann_a:>12,.2f}")
print(f"  Right-sized +10% buffer  (Option B):   ${total_ann_b:>12,.2f}  (delta: ${delta_total:>+10,.2f})")
print(f"  Tight fit, no buffer     (Option C):   ${total_ann_c:>12,.2f}  (delta: ${delta_total_c:>+10,.2f})")
print()
