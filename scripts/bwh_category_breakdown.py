"""
BWH Invoice Category Breakdown - All 4 Tasks
"""
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

pd.set_option('display.max_colwidth', 60)
pd.set_option('display.width', 200)
pd.set_option('display.max_rows', 500)
pd.set_option('display.float_format', lambda x: f'{x:,.2f}')

FILE = r'c:\vscode\annual-client-review\annual-client-review\clients\bwh\2025\allinv_items_too_bwh.xlsx'
df = pd.read_excel(FILE)

# Normalize - handle NaN properly
df['Item_str'] = df['Item'].fillna('').astype(str).str.strip()
df['Desc_str'] = df['Description'].fillna('').astype(str).str.strip()

# ─────────────────────────────────────────────────────────────────────
# Categorization function
# ─────────────────────────────────────────────────────────────────────
def categorize(row):
    item = row['Item_str']
    desc = row['Desc_str']
    item_up = item.upper()
    desc_up = desc.upper()

    # --- Labor ---
    if any(x in item for x in ['Tech_Support', 'TS1']) or item == 'Tech_Support.R':
        if 'AFTER' in desc_up or '.AF' in item:
            return ('Labor', 'IT Support (After-Hours)')
        return ('Labor', 'IT Support')
    if 'OffShore_Support' in item or 'OffShore' in item:
        if '.AF' in item or 'AH' in desc_up or 'AFTER' in desc_up:
            return ('Labor', 'Offshore Support (After-Hours)')
        return ('Labor', 'Offshore Support (Normal)')
    if 'Systems_Architect' in item or 'AD1' in item or 'Architect' in item_up:
        return ('Labor', 'Systems Architect')
    if item == '0. Labor:US:Remote:CTO':
        return ('Labor', 'CTO')
    if 'Dev' in item_up and 'PR1' in item_up:
        return ('Labor', 'Development')
    # generic labor items that appear on Invoice type
    if item.startswith('0. Labor'):
        return ('Labor', 'Labor/Project')

    # --- Security & Endpoint ---
    # Huntress Server first (more specific)
    if item == 'AVHS' or ('HUNTRESS' in desc_up and 'SERVER' in desc_up):
        return ('Security & Endpoint', 'Huntress Server')
    # Huntress Desktop
    if item == 'AVMH' or ('HUNTRESS' in desc_up):
        return ('Security & Endpoint', 'Huntress')
    # CrowdStrike
    if item_up.startswith('AV') and item not in ('AVMH', 'AVHS'):
        return ('Security & Endpoint', 'CrowdStrike')
    if 'CROWDSTRIKE' in desc_up or 'AV PROTECTION' in desc_up or 'AVM PROTECTION' in desc_up:
        return ('Security & Endpoint', 'CrowdStrike')
    # Phishing
    if item == 'PHT' or 'PHISHING' in desc_up or 'CYBERTRAINING' in desc_up:
        return ('Security & Endpoint', 'Phishing Training')

    # --- Backup & Archiving ---
    if item == 'IB' or 'IMAGE BACKUP' in desc_up:
        return ('Backup & Archiving', 'Image Backup')
    # VONE must come before V365 to avoid matching on "VEEAM" keyword
    if item == 'VONE' or 'VEEAM ONE' in desc_up:
        return ('Backup & Archiving', 'Veeam ONE')
    if item == 'V365' or 'VEEAM' in desc_up or 'M365 BACKUP' in desc_up:
        if 'STORAGE' in desc_up:
            return ('Backup & Archiving', 'Veeam 365 / M365 Backup Storage')
        return ('Backup & Archiving', 'Veeam 365')
    if 'TB-BSTR' in item or 'BACKUP STORAGE' in desc_up:
        return ('Backup & Archiving', 'Backup Storage')
    if 'SERVER CLOUD BACKUP' in desc_up:
        return ('Backup & Archiving', 'Server Cloud Backup')

    # --- Monitoring & Management ---
    if item == 'OPS-NET':
        return ('Monitoring & Management', 'Ops Manager Network')
    if item == 'PMW':
        return ('Monitoring & Management', 'Patch Management')
    if item == 'MR':
        return ('Monitoring & Management', 'My Remote')
    if item == 'OPS-BKP':
        return ('Monitoring & Management', 'Config Backup')
    if item == 'OPS-TR':
        return ('Monitoring & Management', 'Traffic Monitor')
    if item == 'OPS-PRT':
        return ('Monitoring & Management', 'Ops Manager Port')
    if item == 'OPS-WF':
        return ('Monitoring & Management', 'WiFi Monitor')
    if item == 'OPS-ST':
        return ('Monitoring & Management', 'Storage Monitor')
    if item == 'SA':
        return ('Monitoring & Management', 'Site Assessment')
    if item == 'MDU':
        return ('Monitoring & Management', 'My Disk')
    if 'NETWORK ASSESSMENT' in desc_up:
        return ('Monitoring & Management', 'Network Assessment')

    # --- Email Security ---
    if item in ('ASA', 'ASB') or 'ANTI-SPAM' in desc_up or 'ANTI SPAM' in desc_up:
        return ('Email Security', 'Anti-Spam')
    if item == 'DKIM' or 'DKIM' in desc_up or 'DMARC' in desc_up:
        return ('Email Security', 'DKIM/DMARC')

    # --- Secure Internet ---
    if item == 'SI' or 'SECURE INTERNET' in desc_up:
        return ('Secure Internet', 'Secure Internet')

    # --- Pen Testing ---
    if item == 'RTPT' or 'PEN TEST' in desc_up:
        return ('Pen Testing', 'Pen Testing')

    # --- Network & Firewall ---
    if 'SOPHOS' in desc_up or 'FIREWALL' in desc_up or 'EDGE' in desc_up:
        return ('Network & Firewall', 'Network/Firewall')

    # --- Cloud Hosting ---
    if any(kw in desc_up for kw in ['CLOUD', 'VPS', ' VM ', 'STORAGE']) and 'BACKUP' not in desc_up:
        return ('Cloud Hosting', 'Cloud')

    # --- Products / Hardware (for Invoice type) ---
    if '3. Products' in item:
        return ('Hardware', 'Hardware')

    # --- Licensing ---
    if 'LICENSING' in item_up or 'M365' in desc_up or 'ENTRA' in desc_up:
        return ('Software/Renewals', 'Software/Licensing')

    # --- E-Recycling ---
    if 'CED' in item or 'RECYCL' in desc_up:
        return ('Other', 'E-Recycling')

    return ('Uncategorized', item + ' / ' + desc)

df[['Category', 'SubCategory']] = df.apply(categorize, axis=1, result_type='expand')

# ═════════════════════════════════════════════════════════════════════
# TASK 1: Monthly Invoice Categorization
# ═════════════════════════════════════════════════════════════════════
print("=" * 120)
print("TASK 1: MONTHLY INVOICE CATEGORIZATION")
print("=" * 120)

monthly = df[df['InvoiceType'] == 'Monthly'].copy()

# 1a. Complete list of unique Item codes with category
print("\n--- 1a. ALL Unique Item Codes in Monthly Invoices with Category Assignment ---\n")
item_cats = monthly.groupby(['Item_str', 'Desc_str', 'Category', 'SubCategory']).agg(
    count=('LineTotal', 'size'),
    total=('LineTotal', 'sum')
).reset_index().sort_values(['Category', 'SubCategory', 'Item_str'])

print(f"{'Item':<40} {'Description':<55} {'Category':<25} {'SubCategory':<30} {'Count':>5} {'Total':>12}")
print("-" * 170)
for _, r in item_cats.iterrows():
    print(f"{r['Item_str']:<40} {r['Desc_str'][:54]:<55} {r['Category']:<25} {r['SubCategory']:<30} {r['count']:>5} {r['total']:>12,.2f}")

# 1b. Summary table
print("\n\n--- 1b. Monthly Invoice Summary: Category | Annual Total | Avg Monthly | # Line Items ---\n")
summary = monthly.groupby(['Category', 'SubCategory']).agg(
    annual_total=('LineTotal', 'sum'),
    line_items=('LineTotal', 'size')
).reset_index()
summary['avg_monthly'] = summary['annual_total'] / 12
summary = summary.sort_values('annual_total', ascending=False)

print(f"{'Category':<25} {'SubCategory':<30} {'Annual Total':>14} {'Avg Monthly':>14} {'# Items':>8}")
print("-" * 95)
for _, r in summary.iterrows():
    print(f"{r['Category']:<25} {r['SubCategory']:<30} ${r['annual_total']:>12,.2f} ${r['avg_monthly']:>12,.2f} {r['line_items']:>8}")
print("-" * 95)
print(f"{'TOTAL':<56} ${summary['annual_total'].sum():>12,.2f} ${summary['annual_total'].sum()/12:>12,.2f} {summary['line_items'].sum():>8}")

# Category-level rollup
print("\n\n--- 1b (rollup). Monthly Invoice Summary by Top-Level Category ---\n")
cat_summary = monthly.groupby('Category').agg(
    annual_total=('LineTotal', 'sum'),
    line_items=('LineTotal', 'size')
).reset_index()
cat_summary['avg_monthly'] = cat_summary['annual_total'] / 12
cat_summary = cat_summary.sort_values('annual_total', ascending=False)

print(f"{'Category':<30} {'Annual Total':>14} {'Avg Monthly':>14} {'# Items':>8}")
print("-" * 70)
for _, r in cat_summary.iterrows():
    print(f"{r['Category']:<30} ${r['annual_total']:>12,.2f} ${r['avg_monthly']:>12,.2f} {r['line_items']:>8}")
print("-" * 70)
print(f"{'TOTAL':<30} ${cat_summary['annual_total'].sum():>12,.2f} ${cat_summary['annual_total'].sum()/12:>12,.2f} {cat_summary['line_items'].sum():>8}")

# 1c. December 2025 Monthly invoice
print("\n\n--- 1c. December 2025 Monthly Invoice - Complete Line Items ---\n")
dec = monthly[(monthly['InvoiceDate'].dt.month == 12) & (monthly['InvoiceDate'].dt.year == 2025)].copy()
dec = dec.sort_values(['Category', 'SubCategory', 'Item_str'])

print(f"Invoice #{dec['InvoiceID'].iloc[0]}  |  Date: {dec['InvoiceDate'].iloc[0].strftime('%Y-%m-%d')}  |  Invoice Total: ${dec['InvoiceTotal'].iloc[0]:,.2f}")
print()
print(f"{'Category':<25} {'SubCategory':<28} {'Item':<25} {'Description':<50} {'Qty':>6} {'Price':>10} {'Line Total':>12}")
print("-" * 160)
for _, r in dec.iterrows():
    print(f"{r['Category']:<25} {r['SubCategory']:<28} {r['Item_str'][:24]:<25} {r['Desc_str'][:49]:<50} {r['qty']:>6.0f} ${r['price']:>9,.2f} ${r['LineTotal']:>11,.2f}")
print("-" * 160)
print(f"{'':>134} TOTAL: ${dec['LineTotal'].sum():>11,.2f}")

# By-category subtotals for Dec
print("\n  Dec 2025 Subtotals by Category:")
dec_cat = dec.groupby('Category')['LineTotal'].sum().sort_values(ascending=False)
for cat, total in dec_cat.items():
    print(f"    {cat:<30} ${total:>10,.2f}")
print(f"    {'TOTAL':<30} ${dec_cat.sum():>10,.2f}")


# ═════════════════════════════════════════════════════════════════════
# TASK 2: Recurring Invoice Breakdown
# ═════════════════════════════════════════════════════════════════════
print("\n\n" + "=" * 120)
print("TASK 2: RECURRING INVOICE BREAKDOWN")
print("=" * 120)

recurring = df[df['InvoiceType'] == 'Recurring'].copy()
recurring['month'] = recurring['InvoiceDate'].dt.to_period('M')

rec_summary = recurring.groupby(['Item_str', 'Desc_str']).agg(
    first_month=('month', 'min'),
    last_month=('month', 'max'),
    appearances=('month', 'nunique'),
    typical_qty=('qty', 'median'),
    min_qty=('qty', 'min'),
    max_qty=('qty', 'max'),
    typical_price=('price', 'median'),
    monthly_cost=('LineTotal', 'median'),
    total_cost=('LineTotal', 'sum')
).reset_index().sort_values('total_cost', ascending=False)

print(f"\n{'Item':<45} {'Description':<40} {'First':>8} {'Last':>8} {'#Mo':>4} {'Qty':>5} {'Price':>10} {'Mo Cost':>12} {'Annual':>12}")
print("-" * 150)
for _, r in rec_summary.iterrows():
    print(f"{r['Item_str'][:44]:<45} {r['Desc_str'][:39]:<40} {str(r['first_month']):>8} {str(r['last_month']):>8} {r['appearances']:>4} {r['typical_qty']:>5.0f} ${r['typical_price']:>9,.2f} ${r['monthly_cost']:>11,.2f} ${r['total_cost']:>11,.2f}")
print("-" * 150)
print(f"{'TOTAL RECURRING (actual billed)':<95} {'':>12} {'':>12} ${rec_summary['total_cost'].sum():>11,.2f}")


# ═════════════════════════════════════════════════════════════════════
# TASK 3: One-Time Invoice Breakdown
# ═════════════════════════════════════════════════════════════════════
print("\n\n" + "=" * 120)
print("TASK 3: ONE-TIME INVOICE BREAKDOWN")
print("=" * 120)

invoices = df[df['InvoiceType'] == 'Invoice'].copy()

def classify_onetime(row):
    item = row['Item_str']
    desc = row['Desc_str'].upper()
    if '3. Products' in item:
        return 'Hardware'
    if any(x in desc for x in ['LICENSE', 'SUBSCRIPTION', 'RENEWAL', 'M365', 'ENTRA', 'SOPHOS', 'FIREWALL SUB']):
        return 'Software/Renewals'
    if any(x in item for x in ['0. Labor', 'CTO']):
        return 'Labor/Project'
    if 'RECYCL' in desc or 'CED' in item:
        return 'Other'
    # Recurring items that appear on Invoice type (mid-month adds)
    if row['Recurring'] == 'Monthly':
        return 'Software/Renewals'
    return 'Other'

invoices['Group'] = invoices.apply(classify_onetime, axis=1)

for group in ['Hardware', 'Software/Renewals', 'Labor/Project', 'Other']:
    grp = invoices[invoices['Group'] == group].sort_values('InvoiceDate')
    print(f"\n--- {group} ---")
    if len(grp) == 0:
        print("  (none)")
        continue
    print(f"  {'Date':<12} {'Item':<45} {'Description':<50} {'Qty':>5} {'Price':>10} {'Line Total':>12}")
    print("  " + "-" * 138)
    for _, r in grp.iterrows():
        print(f"  {r['InvoiceDate'].strftime('%Y-%m-%d'):<12} {r['Item_str'][:44]:<45} {r['Desc_str'][:49]:<50} {r['qty']:>5.0f} ${r['price']:>9,.2f} ${r['LineTotal']:>11,.2f}")
    print("  " + "-" * 138)
    print(f"  {'Subtotal':<108} ${grp['LineTotal'].sum():>11,.2f}")

print(f"\n{'TOTAL ONE-TIME INVOICES':<110} ${invoices['LineTotal'].sum():>11,.2f}")


# ═════════════════════════════════════════════════════════════════════
# TASK 4: Blended Rate Calculation
# ═════════════════════════════════════════════════════════════════════
print("\n\n" + "=" * 120)
print("TASK 4: BLENDED RATE CALCULATION")
print("=" * 120)

# NOTE: Weekly invoices are $0 time-tracking entries (no billing).
# Monthly invoices contain the actual billing: qty=hours, price=rate.
# The blended rate = total revenue / total hours billed (from Monthly invoices).
# Weekly entries provide hour detail cross-check only.

monthly_labor = monthly[monthly['Category'] == 'Labor'].copy()
weekly = df[df['InvoiceType'] == 'Weekly'].copy()
inv_labor = invoices[invoices['Group'] == 'Labor/Project'].copy()

# ---- Map weekly time entries to roles for cross-check ----
weekly['Desc_str'] = weekly['Description'].fillna('').astype(str).str.strip()
weekly['Item_str'] = weekly['Item'].fillna('').astype(str).str.strip()

def classify_weekly_role(row):
    item = row['Item_str']
    desc = row['Desc_str'].upper()
    if 'CHD' in item:
        if 'AFTER' in desc:
            return 'Offshore Support (After-Hours)'
        return 'Offshore Support (Normal)'
    if 'IRV' in item or item == 'Tech_Support.R':
        if 'AFTER' in desc:
            return 'IT Support (After-Hours/Overage)'
        if 'ONSITE' in item.upper():
            return 'IT Support (Onsite)'
        return 'IT Support (US)'
    return 'Other'

weekly['Role'] = weekly.apply(classify_weekly_role, axis=1)

# ---- Role definitions ----
roles = [
    ('IT Support (US)',              'Tech_Support.R',         125, ['IRV-TS1 Support Remote', 'Tech_Support.R']),
    ('Offshore Support (Normal)',    'OffShore_Support.R',      15, ['CHD-TS1 Support Remote']),
    ('Offshore Support (After-Hrs)', 'OffShore_Support.R.AF',   30, []),
    ('Systems Architect',            'Systems_Architect.R',    200, []),
]

print("\n--- 4a. Monthly Contracted Labor Detail (billed on Monthly invoices) ---\n")
print(f"{'Role':<32} {'Item':<28} {'Contract':>9} {'Billed Hrs':>11} {'Revenue':>14} {'Eff Rate':>10}")
print("-" * 108)

blended_rows = []
for role_name, item_code, contract_rate, wk_items in roles:
    role_mo = monthly_labor[monthly_labor['Item_str'] == item_code]
    mo_hrs = role_mo['qty'].sum()
    mo_rev = role_mo['LineTotal'].sum()
    eff = mo_rev / mo_hrs if mo_hrs > 0 else 0
    print(f"{role_name:<32} {item_code:<28} ${contract_rate:>8} {mo_hrs:>11.1f} ${mo_rev:>13,.2f} ${eff:>9,.2f}")
    blended_rows.append({
        'role': role_name, 'contract_rate': contract_rate,
        'mo_hrs': mo_hrs, 'mo_rev': mo_rev,
        'wk_items': wk_items,
    })

tot_mo_hrs = sum(r['mo_hrs'] for r in blended_rows)
tot_mo_rev = sum(r['mo_rev'] for r in blended_rows)
print("-" * 108)
print(f"{'TOTAL MONTHLY CONTRACTED':<61} {tot_mo_hrs:>11.1f} ${tot_mo_rev:>13,.2f} ${tot_mo_rev/tot_mo_hrs if tot_mo_hrs else 0:>9,.2f}")

# ---- Weekly hours cross-check ----
print("\n\n--- 4b. Weekly Time Entries (hour tracking, $0 billing - cross-check) ---\n")
wk_role_summary = weekly.groupby('Role').agg(
    hours=('qty', 'sum'),
    entries=('qty', 'size')
).reset_index().sort_values('hours', ascending=False)

print(f"{'Role (derived from weekly item)':<45} {'Hours':>10} {'# Entries':>10}")
print("-" * 68)
for _, r in wk_role_summary.iterrows():
    print(f"{r['Role']:<45} {r['hours']:>10.1f} {r['entries']:>10}")
print("-" * 68)
print(f"{'TOTAL WEEKLY TRACKED':<45} {wk_role_summary['hours'].sum():>10.1f} {wk_role_summary['entries'].sum():>10}")

print("\n  NOTE: Weekly entries have $0 price/$0 LineTotal. They are time logs only.")
print("  The Monthly invoices contain the actual billed hours and revenue.")

# ---- One-time labor ----
print("\n\n--- 4c. One-Time / Project Labor (from Invoice type) ---\n")
if len(inv_labor) > 0:
    print(f"{'Date':<12} {'Role':<25} {'Description':<42} {'Hrs':>6} {'Rate':>10} {'Total':>12}")
    print("-" * 111)
    onetime_total_rev = 0
    onetime_total_hrs = 0
    for _, r in inv_labor.sort_values('InvoiceDate').iterrows():
        desc_short = r['Desc_str'][:41]
        role_label = 'CTO' if 'CTO' in r['Item_str'] else ('Onsite' if 'Onsite' in r['Item_str'] else 'Project Labor')
        print(f"  {r['InvoiceDate'].strftime('%Y-%m-%d'):<10} {role_label:<25} {desc_short:<42} {r['qty']:>6.0f} ${r['price']:>9,.2f} ${r['LineTotal']:>11,.2f}")
        onetime_total_rev += r['LineTotal']
        onetime_total_hrs += r['qty']
    print("-" * 111)
    print(f"  {'TOTAL ONE-TIME LABOR':<78} {onetime_total_hrs:>6.0f} {'':>10} ${onetime_total_rev:>11,.2f}")

# ---- Final blended rate table ----
print("\n\n--- 4d. BLENDED RATE SUMMARY (Revenue / Hours = Blended Rate) ---\n")
print(f"{'Role':<35} {'Contract':>9} {'Mo Billed Hrs':>14} {'Mo Revenue':>14} {'1x Hrs':>8} {'1x Revenue':>12} {'Total Hrs':>10} {'Total Rev':>14} {'Blended':>10}")
print("-" * 130)

grand_rev = 0
grand_hrs = 0

for br in blended_rows:
    tot_hrs = br['mo_hrs']
    tot_rev = br['mo_rev']
    blended = tot_rev / tot_hrs if tot_hrs > 0 else 0
    grand_rev += tot_rev
    grand_hrs += tot_hrs
    print(f"{br['role']:<35} ${br['contract_rate']:>8} {br['mo_hrs']:>14.1f} ${br['mo_rev']:>13,.2f} {'0.0':>8} ${'0.00':>11} {tot_hrs:>10.1f} ${tot_rev:>13,.2f} ${blended:>9,.2f}")

# CTO
cto = inv_labor[inv_labor['Item_str'].str.contains('CTO', na=False)]
if len(cto) > 0:
    cto_rev = cto['LineTotal'].sum()
    cto_hrs = cto['qty'].sum()
    cto_rate = cto_rev / cto_hrs if cto_hrs > 0 else 0
    grand_rev += cto_rev
    grand_hrs += cto_hrs
    print(f"{'CTO (One-Time)':<35} {'$250':>9} {'0.0':>14} ${'0.00':>13} {cto_hrs:>8.1f} ${cto_rev:>11,.2f} {cto_hrs:>10.1f} ${cto_rev:>13,.2f} ${cto_rate:>9,.2f}")

# Onsite one-time
onsite = inv_labor[inv_labor['Item_str'].str.contains('Onsite', na=False)]
if len(onsite) > 0:
    os_rev = onsite['LineTotal'].sum()
    os_hrs = onsite['qty'].sum()
    os_rate = os_rev / os_hrs if os_hrs > 0 else 0
    grand_rev += os_rev
    grand_hrs += os_hrs
    print(f"{'Onsite Labor (One-Time)':<35} {'$150':>9} {'0.0':>14} ${'0.00':>13} {os_hrs:>8.1f} ${os_rev:>11,.2f} {os_hrs:>10.1f} ${os_rev:>13,.2f} ${os_rate:>9,.2f}")

# Generic project labor (not CTO, not Onsite)
gen_labor = inv_labor[~inv_labor['Item_str'].str.contains('CTO|Onsite', na=False)]
if len(gen_labor) > 0:
    gl_rev = gen_labor['LineTotal'].sum()
    gl_hrs = gen_labor['qty'].sum()
    gl_rate = gl_rev / gl_hrs if gl_hrs > 0 else 0
    grand_rev += gl_rev
    grand_hrs += gl_hrs
    print(f"{'Project Labor (One-Time)':<35} {'$150':>9} {'0.0':>14} ${'0.00':>13} {gl_hrs:>8.1f} ${gl_rev:>11,.2f} {gl_hrs:>10.1f} ${gl_rev:>13,.2f} ${gl_rate:>9,.2f}")

print("-" * 130)
print(f"{'GRAND TOTAL ALL LABOR':<35} {'':>9} {tot_mo_hrs:>14.1f} ${tot_mo_rev:>13,.2f} {onetime_total_hrs:>8.0f} ${onetime_total_rev:>11,.2f} {grand_hrs:>10.1f} ${grand_rev:>13,.2f} ${grand_rev/grand_hrs if grand_hrs else 0:>9,.2f}")

print("\n  KEY INSIGHT: Weekly entries ($0 revenue) track time but do NOT bill.")
print("  All labor billing flows through Monthly invoices (qty=hrs, price=rate).")
print("  Blended rate = Monthly Revenue / Monthly Billed Hours for each role.")
print(f"  Overall blended rate across all labor (incl one-time): ${grand_rev/grand_hrs if grand_hrs else 0:,.2f}/hr")


# ═════════════════════════════════════════════════════════════════════
# GRAND SUMMARY
# ═════════════════════════════════════════════════════════════════════
print("\n\n" + "=" * 120)
print("GRAND SUMMARY - ALL BWH 2025 INVOICES")
print("=" * 120)

type_totals = df.groupby('InvoiceType').agg(
    total=('LineTotal', 'sum'),
    items=('LineTotal', 'size'),
    invoices=('InvoiceID', 'nunique')
).sort_values('total', ascending=False)

print(f"\n{'Invoice Type':<20} {'# Invoices':>12} {'# Line Items':>14} {'Total Revenue':>16}")
print("-" * 65)
for typ, r in type_totals.iterrows():
    print(f"{typ:<20} {r['invoices']:>12} {r['items']:>14} ${r['total']:>15,.2f}")
print("-" * 65)
print(f"{'TOTAL':<20} {type_totals['invoices'].sum():>12} {type_totals['items'].sum():>14} ${type_totals['total'].sum():>15,.2f}")

# Check for any uncategorized
uncat = df[df['Category'] == 'Uncategorized']
if len(uncat) > 0:
    print(f"\n*** WARNING: {len(uncat)} UNCATEGORIZED line items ***")
    for _, r in uncat.iterrows():
        print(f"  Type={r['InvoiceType']} Item=[{r['Item_str']}] Desc=[{r['Desc_str']}] Total=${r['LineTotal']:,.2f}")
