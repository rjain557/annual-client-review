"""
BWH Invoice Comprehensive Analysis
File: allinv_items_too_bwh.xlsx
"""
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.width', 220)
pd.set_option('display.max_colwidth', 60)
pd.set_option('display.float_format', lambda x: f'{x:,.2f}')

FILE = r'c:\vscode\annual-client-review\annual-client-review\clients\bwh\2025\allinv_items_too_bwh.xlsx'

print("=" * 120)
print("BWH INVOICE COMPREHENSIVE ANALYSIS")
print("=" * 120)

df = pd.read_excel(FILE, engine='openpyxl')
print(f"\nLoaded {len(df)} rows, {len(df.columns)} columns")
print(f"Columns: {list(df.columns)}")
print(f"\nColumn dtypes:\n{df.dtypes}")
print(f"\nInvoiceType value counts:\n{df['InvoiceType'].value_counts()}")
print(f"\nUnique InvoiceIDs: {df['InvoiceID'].nunique()}")

# Convert InvoiceDate to datetime
df['InvoiceDate'] = pd.to_datetime(df['InvoiceDate'], errors='coerce')
df['YearMonth'] = df['InvoiceDate'].dt.to_period('M')
df['Month'] = df['InvoiceDate'].dt.strftime('%Y-%m')

# Fill NaN in string columns
df['Item'] = df['Item'].fillna('').astype(str)
df['Description'] = df['Description'].fillna('').astype(str)

# Ensure numeric columns
for col in ['qty', 'price', 'LineTotal', 'InvoiceTotal']:
    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

print(f"\nDate range: {df['InvoiceDate'].min()} to {df['InvoiceDate'].max()}")
print(f"Unique months: {sorted(df['Month'].dropna().unique())}")

# ============================================================
# 1. CONTRACT CYCLE DETECTION
# ============================================================
print("\n" + "=" * 120)
print("1. CONTRACT CYCLE DETECTION")
print("=" * 120)

monthly = df[df['InvoiceType'] == 'Monthly'].copy()
print(f"\nMonthly invoices: {len(monthly)} line items across {monthly['InvoiceID'].nunique()} invoices")
print(f"Monthly invoice months: {sorted(monthly['Month'].dropna().unique())}")

# Labor keywords
labor_keywords = ['Support', 'TS1', 'CTO', 'AD1', 'Dev', 'PR1', 'OffShore', 'Offshore']

def is_labor(item, desc):
    item_str = str(item).upper()
    desc_str = str(desc).upper()
    for kw in labor_keywords:
        if kw.upper() in item_str or kw.upper() in desc_str:
            return True
    return False

monthly['IsLabor'] = monthly.apply(lambda r: is_labor(r['Item'], r['Description']), axis=1)
labor = monthly[monthly['IsLabor']].copy()

print(f"\nLabor line items found: {len(labor)}")
print(f"Unique labor items: {labor['Item'].nunique()}")

print("\n--- LABOR ITEMS: QTY AND PRICE PER MONTH ---")
for item_code in sorted(labor['Item'].unique(), key=str):
    item_data = labor[labor['Item'] == item_code]
    desc = item_data['Description'].iloc[0]
    print(f"\n  Item: {item_code} | Description: {desc}")
    print(f"  {'Month':<12} {'Qty':>8} {'Price':>12} {'LineTotal':>12}")
    print(f"  {'-'*48}")
    for month in sorted(item_data['Month'].unique()):
        m_data = item_data[item_data['Month'] == month]
        for _, row in m_data.iterrows():
            print(f"  {month:<12} {row['qty']:>8.1f} {row['price']:>12.2f} {row['LineTotal']:>12.2f}")

    # Detect rate/qty changes
    monthly_prices = item_data.groupby('Month')['price'].first()
    monthly_qtys = item_data.groupby('Month')['qty'].first()
    price_changes = monthly_prices.diff().ne(0).sum()
    qty_changes = monthly_qtys.diff().ne(0).sum()
    if price_changes > 1 or qty_changes > 1:
        print(f"  ** CHANGE DETECTED: price changed {price_changes-1} times, qty changed {qty_changes-1} times **")
    else:
        print(f"  (Stable: no rate or quantity changes)")

print("\n--- MONTHLY INVOICE TOTALS (from InvoiceTotal, per unique invoice) ---")
monthly_inv_totals = monthly.drop_duplicates(subset=['InvoiceID'])[['InvoiceID', 'Month', 'InvoiceTotal']].sort_values('Month')
for _, row in monthly_inv_totals.iterrows():
    print(f"  {row['Month']:<12} Invoice #{row['InvoiceID']:<10} Total: ${row['InvoiceTotal']:>12,.2f}")

# ============================================================
# 2. MONTHLY CONTRACT BREAKDOWN BY CATEGORY
# ============================================================
print("\n" + "=" * 120)
print("2. MONTHLY CONTRACT BREAKDOWN BY CATEGORY")
print("=" * 120)

def categorize(item, desc):
    item_u = str(item).upper()
    desc_u = str(desc).upper()

    # Labor
    for kw in ['SUPPORT', 'TS1', 'AD1', 'PR1', 'CTO', 'DEV', 'OFFSHORE']:
        if kw in item_u or kw in desc_u:
            return 'Labor'

    # Cloud Hosting
    for kw in ['VM', 'VPS', 'COMPUTE', 'STORAGE', 'CLOUD', 'AZURE', 'AWS']:
        if kw in item_u or kw in desc_u:
            return 'Cloud Hosting'

    # Security & Endpoint
    for kw in ['CROWDSTRIKE', 'HUNTRESS', 'UMBRELLA', 'CS-', 'HT-', ' CS ', 'ENDPOINT']:
        if kw in item_u or kw in desc_u:
            return 'Security & Endpoint'
    # Also check for CS or HT at start of item
    if item_u.startswith('CS') or item_u.startswith('HT'):
        return 'Security & Endpoint'

    # Backup & Archiving
    for kw in ['IB-', 'VEEAM', 'V365', 'ARCHIVE', 'BACKUP', 'IMAGE']:
        if kw in item_u or kw in desc_u:
            return 'Backup & Archiving'
    if item_u.startswith('IB'):
        return 'Backup & Archiving'

    # Monitoring & Management
    for kw in ['RMM', 'OPS', 'MR-', 'PMW', 'MANAGE', 'PATCH', 'MYREMOTE', 'MONITOR', 'REMOTE']:
        if kw in item_u or kw in desc_u:
            return 'Monitoring & Management'
    if item_u.startswith('MR'):
        return 'Monitoring & Management'

    # Email Security
    for kw in ['ANTI-SPAM', 'DKIM', 'DMARC', 'ASB', 'ASP', 'SPAM', 'ANTISPAM']:
        if kw in item_u or kw in desc_u:
            return 'Email Security'

    # Network & Firewall
    for kw in ['SOPHOS', 'FIREWALL', 'VELOCLOUD', 'EDGE', 'NETWORK', 'SWITCH', 'ROUTER', 'FW-', 'FW ']:
        if kw in item_u or kw in desc_u:
            return 'Network & Firewall'
    if item_u.startswith('FW'):
        return 'Network & Firewall'

    # VoIP / Telephony
    for kw in ['3CX', 'SIP', 'DID', 'PHONE', 'VOIP', 'SMS', 'TELEPHONY', 'PBX']:
        if kw in item_u or kw in desc_u:
            return 'VoIP / Telephony'

    # Secure Internet
    for kw in ['SI-', 'SECURE INTERNET', 'FILTERING', 'WEB FILTER']:
        if kw in item_u or kw in desc_u:
            return 'Secure Internet'
    if item_u.startswith('SI'):
        return 'Secure Internet'

    # Pen Testing
    for kw in ['PEN', 'PENTEST', 'PEN TEST', 'PENETRATION']:
        if kw in item_u or kw in desc_u:
            return 'Pen Testing'

    return 'Other'

monthly['Category'] = monthly.apply(lambda r: categorize(r['Item'], r['Description']), axis=1)

# Count months for avg calculation
num_months = monthly['Month'].nunique()
print(f"\nNumber of monthly invoice months: {num_months}")

cat_summary = monthly.groupby('Category')['LineTotal'].agg(['sum', 'count']).sort_values('sum', ascending=False)
cat_summary['avg_monthly'] = cat_summary['sum'] / num_months
cat_summary.columns = ['Annual Total', 'Line Count', 'Avg Monthly']

print(f"\n{'Category':<30} {'Annual Total':>14} {'Avg Monthly':>14} {'Line Count':>12}")
print("-" * 75)
for cat, row in cat_summary.iterrows():
    print(f"{cat:<30} ${row['Annual Total']:>12,.2f} ${row['Avg Monthly']:>12,.2f} {int(row['Line Count']):>12}")
print(f"{'TOTAL':<30} ${cat_summary['Annual Total'].sum():>12,.2f} ${cat_summary['Avg Monthly'].sum():>12,.2f} {int(cat_summary['Line Count'].sum()):>12}")

print("\n--- DETAILED LINE ITEMS PER CATEGORY ---")
for cat in cat_summary.index:
    cat_data = monthly[monthly['Category'] == cat]
    print(f"\n  === {cat} ===")

    item_agg = cat_data.groupby(['Item', 'Description']).agg(
        months=('Month', 'nunique'),
        avg_qty=('qty', 'mean'),
        avg_price=('price', 'mean'),
        avg_line=('LineTotal', 'mean'),
        total=('LineTotal', 'sum'),
        min_qty=('qty', 'min'),
        max_qty=('qty', 'max'),
        min_price=('price', 'min'),
        max_price=('price', 'max')
    ).sort_values('total', ascending=False)

    print(f"  {'Item':<20} {'Description':<45} {'Months':>6} {'AvgQty':>8} {'AvgPrice':>10} {'AvgLine':>12} {'AnnualTot':>12}")
    print(f"  {'-'*115}")
    for (item, desc), row in item_agg.iterrows():
        desc_short = str(desc)[:44]
        print(f"  {str(item):<20} {desc_short:<45} {int(row['months']):>6} {row['avg_qty']:>8.1f} {row['avg_price']:>10.2f} {row['avg_line']:>12.2f} {row['total']:>12.2f}")
        if row['min_qty'] != row['max_qty'] or row['min_price'] != row['max_price']:
            print(f"  {'':>20} ** Qty range: {row['min_qty']:.1f}-{row['max_qty']:.1f}, Price range: ${row['min_price']:.2f}-${row['max_price']:.2f}")

# ============================================================
# 3. RECURRING LICENSING BREAKDOWN
# ============================================================
print("\n" + "=" * 120)
print("3. RECURRING LICENSING BREAKDOWN")
print("=" * 120)

recurring = df[df['InvoiceType'] == 'Recurring'].copy()
print(f"\nRecurring invoices: {len(recurring)} line items across {recurring['InvoiceID'].nunique()} invoices")
print(f"Recurring months: {sorted(recurring['Month'].dropna().unique())}")

rec_num_months = recurring['Month'].nunique() if recurring['Month'].nunique() > 0 else 1

rec_agg = recurring.groupby(['Item', 'Description']).agg(
    occurrences=('Month', 'count'),
    unique_months=('Month', 'nunique'),
    avg_qty=('qty', 'mean'),
    avg_price=('price', 'mean'),
    avg_line=('LineTotal', 'mean'),
    total=('LineTotal', 'sum'),
    min_qty=('qty', 'min'),
    max_qty=('qty', 'max'),
    min_price=('price', 'min'),
    max_price=('price', 'max')
).sort_values('total', ascending=False)

print(f"\n{'Item':<20} {'Description':<50} {'Occur':>5} {'AvgQty':>8} {'AvgPrice':>10} {'MonthlyCost':>12} {'AnnualCost':>12}")
print("-" * 120)
for (item, desc), row in rec_agg.iterrows():
    monthly_cost = row['avg_line']
    annual_cost = row['total']
    desc_short = str(desc)[:49]
    print(f"{str(item):<20} {desc_short:<50} {int(row['occurrences']):>5} {row['avg_qty']:>8.1f} {row['avg_price']:>10.2f} {monthly_cost:>12.2f} {annual_cost:>12.2f}")
    if row['min_qty'] != row['max_qty'] or row['min_price'] != row['max_price']:
        print(f"{'':>20} ** Qty range: {row['min_qty']:.1f}-{row['max_qty']:.1f}, Price range: ${row['min_price']:.2f}-${row['max_price']:.2f}")

print(f"\n{'TOTAL':>70} ${rec_agg['avg_line'].sum():>12,.2f} ${rec_agg['total'].sum():>12,.2f}")

# ============================================================
# 4. ONE-TIME / PROJECT SPEND
# ============================================================
print("\n" + "=" * 120)
print("4. ONE-TIME / PROJECT SPEND (InvoiceType = 'Invoice')")
print("=" * 120)

onetime = df[df['InvoiceType'] == 'Invoice'].copy()
print(f"\nOne-time invoices: {len(onetime)} line items across {onetime['InvoiceID'].nunique()} invoices")

def categorize_onetime(item, desc):
    item_u = str(item).upper()
    desc_u = str(desc).upper()

    for kw in ['HARDWARE', 'LAPTOP', 'DESKTOP', 'MONITOR', 'PRINTER', 'DOCK', 'CABLE', 'AP ', 'ACCESS POINT',
               'SWITCH', 'UPS', 'NIC', 'ADAPTER', 'KEYBOARD', 'MOUSE', 'HEADSET', 'WEBCAM', 'RAM', 'SSD',
               'HARD DRIVE', 'SERVER', 'RACK', 'PDU']:
        if kw in item_u or kw in desc_u:
            return 'Hardware'

    for kw in ['LICENSE', 'RENEWAL', 'SUBSCRIPTION', 'SOFTWARE', 'ANNUAL', 'RENEW', 'ADOBE', 'MICROSOFT',
               'OFFICE', 'WINDOWS', 'VMWARE', 'VEEAM', 'ANTIVIRUS', 'SSL', 'CERT', 'DOMAIN']:
        if kw in item_u or kw in desc_u:
            return 'Software/Renewals'

    for kw in ['LABOR', 'OVERAGE', 'HOUR', 'HRS', 'SUPPORT', 'TS1', 'AD1', 'PR1', 'CTO', 'DEV', 'OFFSHORE',
               'CONSULT', 'INSTALL', 'SETUP', 'CONFIG', 'MIGRATION', 'PROJECT']:
        if kw in item_u or kw in desc_u:
            return 'Labor/Project'

    return 'Other'

onetime['SubCategory'] = onetime.apply(lambda r: categorize_onetime(r['Item'], r['Description']), axis=1)

print(f"\n--- ALL ONE-TIME LINE ITEMS ---")
print(f"{'Date':<12} {'InvID':<10} {'Item':<20} {'Description':<50} {'Qty':>6} {'Price':>10} {'LineTotal':>12} {'SubCat':<18}")
print("-" * 140)
for _, row in onetime.sort_values('InvoiceDate').iterrows():
    date_str = row['InvoiceDate'].strftime('%Y-%m-%d') if pd.notna(row['InvoiceDate']) else 'N/A'
    desc_short = str(row['Description'])[:49]
    print(f"{date_str:<12} {str(row['InvoiceID']):<10} {str(row['Item']):<20} {desc_short:<50} {row['qty']:>6.1f} {row['price']:>10.2f} {row['LineTotal']:>12.2f} {row['SubCategory']:<18}")

print(f"\n--- ONE-TIME SPEND BY SUB-CATEGORY ---")
subcat_totals = onetime.groupby('SubCategory')['LineTotal'].agg(['sum', 'count']).sort_values('sum', ascending=False)
print(f"{'SubCategory':<25} {'Total':>14} {'Items':>8}")
print("-" * 50)
for subcat, row in subcat_totals.iterrows():
    print(f"{subcat:<25} ${row['sum']:>12,.2f} {int(row['count']):>8}")
print(f"{'TOTAL':<25} ${subcat_totals['sum'].sum():>12,.2f} {int(subcat_totals['count'].sum()):>8}")

# ============================================================
# 5. WEEKLY INVOICE ITEMS
# ============================================================
print("\n" + "=" * 120)
print("5. WEEKLY INVOICE ITEMS")
print("=" * 120)

weekly = df[df['InvoiceType'] == 'Weekly'].copy()
print(f"\nWeekly invoices: {len(weekly)} line items across {weekly['InvoiceID'].nunique()} invoices")

if len(weekly) > 0:
    print(f"Weekly date range: {weekly['InvoiceDate'].min()} to {weekly['InvoiceDate'].max()}")
    print(f"Weekly months: {sorted(weekly['Month'].dropna().unique())}")

    print(f"\n--- ALL WEEKLY LINE ITEMS ---")
    print(f"{'Date':<12} {'InvID':<10} {'Item':<20} {'Description':<50} {'Qty':>6} {'Price':>10} {'LineTotal':>12} {'InvTotal':>12}")
    print("-" * 135)
    for _, row in weekly.sort_values('InvoiceDate').iterrows():
        date_str = row['InvoiceDate'].strftime('%Y-%m-%d') if pd.notna(row['InvoiceDate']) else 'N/A'
        desc_short = str(row['Description'])[:49]
        print(f"{date_str:<12} {str(row['InvoiceID']):<10} {str(row['Item']):<20} {desc_short:<50} {row['qty']:>6.1f} {row['price']:>10.2f} {row['LineTotal']:>12.2f} {row['InvoiceTotal']:>12.2f}")

    print(f"\n--- WEEKLY ITEM SUMMARY ---")
    weekly_summary = weekly.groupby(['Item', 'Description']).agg(
        count=('InvoiceID', 'count'),
        total_qty=('qty', 'sum'),
        avg_qty=('qty', 'mean'),
        avg_price=('price', 'mean'),
        total=('LineTotal', 'sum')
    ).sort_values('total', ascending=False)

    print(f"{'Item':<20} {'Description':<50} {'Count':>6} {'TotalQty':>10} {'AvgPrice':>10} {'Total':>12}")
    print("-" * 110)
    for (item, desc), row in weekly_summary.iterrows():
        desc_short = str(desc)[:49]
        print(f"{str(item):<20} {desc_short:<50} {int(row['count']):>6} {row['total_qty']:>10.1f} {row['avg_price']:>10.2f} {row['total']:>12.2f}")
else:
    print("No Weekly invoices found.")

# ============================================================
# 6. FULL DECEMBER 2025 INVOICE DETAIL
# ============================================================
print("\n" + "=" * 120)
print("6. FULL DECEMBER 2025 INVOICE DETAIL")
print("=" * 120)

dec = df[(df['InvoiceDate'].dt.year == 2025) & (df['InvoiceDate'].dt.month == 12)].copy()
print(f"\nDecember 2025 total line items: {len(dec)}")

for inv_type in dec['InvoiceType'].unique():
    type_data = dec[dec['InvoiceType'] == inv_type]
    print(f"\n--- {inv_type} Invoices in December 2025 ---")
    print(f"Line items: {len(type_data)}, Unique invoices: {type_data['InvoiceID'].nunique()}")

    for inv_id in sorted(type_data['InvoiceID'].unique()):
        inv_data = type_data[type_data['InvoiceID'] == inv_id].sort_values('Item')
        inv_total = inv_data['InvoiceTotal'].iloc[0]
        inv_date = inv_data['InvoiceDate'].iloc[0].strftime('%Y-%m-%d')
        print(f"\n  Invoice #{inv_id} | Date: {inv_date} | Invoice Total: ${inv_total:,.2f}")
        print(f"  {'Item':<20} {'Description':<50} {'Qty':>8} {'Price':>10} {'LineTotal':>12}")
        print(f"  {'-'*102}")
        line_sum = 0
        for _, row in inv_data.iterrows():
            desc_short = str(row['Description'])[:49]
            print(f"  {str(row['Item']):<20} {desc_short:<50} {row['qty']:>8.1f} {row['price']:>10.2f} {row['LineTotal']:>12.2f}")
            line_sum += row['LineTotal']
        print(f"  {'':>70} {'Sum of Lines:':>10} ${line_sum:>11,.2f}")

# ============================================================
# 7. MONTHLY REVENUE TREND
# ============================================================
print("\n" + "=" * 120)
print("7. MONTHLY REVENUE TREND")
print("=" * 120)

# Get unique invoice totals per invoice per month
# For each InvoiceType and month, sum unique invoice totals
all_months = sorted(df['Month'].dropna().unique())

print(f"\n{'Month':<10} {'Monthly':>14} {'Recurring':>14} {'Invoice(1x)':>14} {'Weekly':>14} {'Grand Total':>14}")
print("-" * 85)

grand_totals = {'Monthly': 0, 'Recurring': 0, 'Invoice': 0, 'Weekly': 0}

for month in all_months:
    month_data = df[df['Month'] == month]
    totals = {}
    for inv_type in ['Monthly', 'Recurring', 'Invoice', 'Weekly']:
        type_data = month_data[month_data['InvoiceType'] == inv_type]
        # Sum of line totals for this type in this month
        totals[inv_type] = type_data['LineTotal'].sum()
        grand_totals[inv_type] += totals[inv_type]

    grand = sum(totals.values())
    print(f"{month:<10} ${totals['Monthly']:>12,.2f} ${totals['Recurring']:>12,.2f} ${totals['Invoice']:>12,.2f} ${totals['Weekly']:>12,.2f} ${grand:>12,.2f}")

print("-" * 85)
gt = sum(grand_totals.values())
print(f"{'ANNUAL':>10} ${grand_totals['Monthly']:>12,.2f} ${grand_totals['Recurring']:>12,.2f} ${grand_totals['Invoice']:>12,.2f} ${grand_totals['Weekly']:>12,.2f} ${gt:>12,.2f}")

print(f"\n--- REVENUE TREND USING INVOICE TOTALS (unique invoice amounts per month) ---")
print(f"{'Month':<10} {'Monthly':>14} {'Recurring':>14} {'Invoice(1x)':>14} {'Weekly':>14} {'Grand Total':>14}")
print("-" * 85)

grand_totals2 = {'Monthly': 0, 'Recurring': 0, 'Invoice': 0, 'Weekly': 0}

for month in all_months:
    month_data = df[df['Month'] == month]
    totals = {}
    for inv_type in ['Monthly', 'Recurring', 'Invoice', 'Weekly']:
        type_data = month_data[month_data['InvoiceType'] == inv_type]
        # Use unique invoice totals
        unique_invs = type_data.drop_duplicates(subset=['InvoiceID'])[['InvoiceID', 'InvoiceTotal']]
        totals[inv_type] = unique_invs['InvoiceTotal'].sum()
        grand_totals2[inv_type] += totals[inv_type]

    grand = sum(totals.values())
    print(f"{month:<10} ${totals['Monthly']:>12,.2f} ${totals['Recurring']:>12,.2f} ${totals['Invoice']:>12,.2f} ${totals['Weekly']:>12,.2f} ${grand:>12,.2f}")

print("-" * 85)
gt2 = sum(grand_totals2.values())
print(f"{'ANNUAL':>10} ${grand_totals2['Monthly']:>12,.2f} ${grand_totals2['Recurring']:>12,.2f} ${grand_totals2['Invoice']:>12,.2f} ${grand_totals2['Weekly']:>12,.2f} ${gt2:>12,.2f}")

# ============================================================
# BONUS: COMPLETE ITEM CODE DUMP
# ============================================================
print("\n" + "=" * 120)
print("BONUS: ALL UNIQUE ITEM CODES AND DESCRIPTIONS")
print("=" * 120)

all_items = df.groupby(['InvoiceType', 'Item', 'Description']).agg(
    occurrences=('InvoiceID', 'count'),
    avg_qty=('qty', 'mean'),
    avg_price=('price', 'mean'),
    total=('LineTotal', 'sum')
).sort_values(['InvoiceType', 'total'], ascending=[True, False])

for inv_type in ['Monthly', 'Recurring', 'Invoice', 'Weekly']:
    type_items = all_items.loc[inv_type] if inv_type in all_items.index.get_level_values(0) else pd.DataFrame()
    if len(type_items) == 0:
        continue
    print(f"\n--- {inv_type} Items ---")
    print(f"{'Item':<20} {'Description':<55} {'Occur':>5} {'AvgQty':>8} {'AvgPrice':>10} {'Total':>12}")
    print("-" * 115)
    for (item, desc), row in type_items.iterrows():
        desc_short = str(desc)[:54]
        print(f"{str(item):<20} {desc_short:<55} {int(row['occurrences']):>5} {row['avg_qty']:>8.1f} {row['avg_price']:>10.2f} {row['total']:>12.2f}")

print("\n" + "=" * 120)
print("ANALYSIS COMPLETE")
print("=" * 120)
