import pandas as pd
import numpy as np
import re

FILE = r'c:\vscode\annual-client-review\annual-client-review\clients\bwh\2025\all-ticket_timeE_bwh_2025.xlsx'

df = pd.read_excel(FILE)

# ── Clean hours: treat NaN (and any literal "NULL" strings) as 0 ──
for col in ['NH_HoursWorked', 'AH_HoursWorked', 'Onsite_HoursWorked']:
    df[col] = pd.to_numeric(df[col].replace('NULL', np.nan), errors='coerce').fillna(0)

df['Total_Hours'] = df['NH_HoursWorked'] + df['AH_HoursWorked'] + df['Onsite_HoursWorked']
df['Month'] = df['StartDateTime'].dt.month
df['MonthName'] = df['StartDateTime'].dt.strftime('%b')
df['DayOfWeek'] = df['StartDateTime'].dt.dayofweek  # 0=Mon, 5=Sat, 6=Sun
df['IsWeekend'] = df['DayOfWeek'].isin([5, 6])

# ═══════════════════════════════════════════════════════════════════
# SECTION 1: Month-by-Month Metrics
# ═══════════════════════════════════════════════════════════════════
months = range(1, 13)
month_names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

rows = []
for m in months:
    mdf = df[df['Month'] == m]
    tickets = mdf['TicketID'].nunique()
    nh = mdf['NH_HoursWorked'].sum()
    ah = mdf['AH_HoursWorked'].sum()
    onsite = mdf['Onsite_HoursWorked'].sum()
    total = mdf['Total_Hours'].sum()
    entries = len(mdf)
    hpt = total / tickets if tickets > 0 else 0
    weekend = mdf['IsWeekend'].sum()
    rows.append({
        'Month': month_names[m-1],
        'Tickets': tickets,
        'NH Hrs': round(nh, 2),
        'AH Hrs': round(ah, 2),
        'Onsite Hrs': round(onsite, 2),
        'Total Hrs': round(total, 2),
        'Entries': entries,
        'Hrs/Ticket': round(hpt, 2),
        'Weekend': int(weekend),
    })

rdf = pd.DataFrame(rows)

# Totals
total_row = {
    'Month': '**TOTAL**',
    'Tickets': df['TicketID'].nunique(),
    'NH Hrs': round(rdf['NH Hrs'].sum(), 2),
    'AH Hrs': round(rdf['AH Hrs'].sum(), 2),
    'Onsite Hrs': round(rdf['Onsite Hrs'].sum(), 2),
    'Total Hrs': round(rdf['Total Hrs'].sum(), 2),
    'Entries': int(rdf['Entries'].sum()),
    'Hrs/Ticket': round(rdf['Total Hrs'].sum() / df['TicketID'].nunique(), 2),
    'Weekend': int(rdf['Weekend'].sum()),
}
# Averages (per month that has data)
active_months = rdf[rdf['Entries'] > 0]
n_active = len(active_months)
avg_row = {
    'Month': '**AVG**',
    'Tickets': round(active_months['Tickets'].mean(), 1),
    'NH Hrs': round(active_months['NH Hrs'].mean(), 2),
    'AH Hrs': round(active_months['AH Hrs'].mean(), 2),
    'Onsite Hrs': round(active_months['Onsite Hrs'].mean(), 2),
    'Total Hrs': round(active_months['Total Hrs'].mean(), 2),
    'Entries': round(active_months['Entries'].mean(), 1),
    'Hrs/Ticket': round(active_months['Hrs/Ticket'].mean(), 2),
    'Weekend': round(active_months['Weekend'].mean(), 1),
}

rdf = pd.concat([rdf, pd.DataFrame([total_row, avg_row])], ignore_index=True)

print("## Monthly Time Entry Metrics - BWH 2025\n")
print(rdf.to_markdown(index=False))

# Weekend %
total_entries = len(df)
weekend_entries = int(df['IsWeekend'].sum())
weekend_pct = round(weekend_entries / total_entries * 100, 1) if total_entries else 0
print(f"\n**Weekend entries (full year):** {weekend_entries} / {total_entries} = **{weekend_pct}%**\n")

# ═══════════════════════════════════════════════════════════════════
# SECTION 2: Ticket Categorization
# ═══════════════════════════════════════════════════════════════════

CATEGORIES = [
    ("Patch Management",
     r"patch|windows update|missed or failed"),
    ("Monitoring & Alerts",
     r"monitoring|alert|memory utilization|disk utilization|response time|ops manager|cpu|threshold"),
    ("Security & Endpoint",
     r"crowdstrike|huntress|malware|antivirus|umbrella|security|threat|detection|malwarebytes|defender|virus|spam|phishing"),
    ("Backup & DR",
     r"backup|veeam|image backup|restore|disaster recovery|replication"),
    ("RMM & Agent",
     r"rmm|agent|automate|connectwise|myremote|my remote"),
    ("Email & M365",
     r"email|outlook|teams|sharepoint|m365|office 365|mailbox|distribution|entra|onedrive|calendar|exchange"),
    ("Server Management",
     r"server|vm |virtual machine|reboot|restart|hyper-v|active directory|ad |group policy|gpo"),
    ("Software Installation",
     r"install|software|update|upgrade|application|deploy"),
    ("Phone / VoIP",
     r"phone|3cx|voip|sip|\bdid\b|ring group|extension|call|voicemail|fax"),
    ("User Onboarding/Offboarding",
     r"onboard|offboard|new user|new hire|terminate|new employee|setup for|setup user"),
    ("Workstation & Hardware",
     r"workstation|desktop|laptop|hardware|dock|monitor|keyboard|mouse"),
    ("Printing & Scanning",
     r"print|scan|printer|scanner|fax|copier"),
    ("Password & Account",
     r"password|reset password|account lock|mfa|2fa|authentication|unlock"),
    ("Firewall & Network",
     r"firewall|network|vpn|dns|dhcp|wifi|wireless|sophos|switch|router|internet"),
    ("File & Permissions",
     r"file|permission|shared drive|folder|access|mapping"),
    ("Domain & SSL",
     r"domain|ssl|certificate"),
    ("QuickBooks",
     r"quickbooks|qb"),
]

# Proactive categories
PROACTIVE = {
    "Patch Management", "Monitoring & Alerts", "Security & Endpoint",
    "Backup & DR", "RMM & Agent",
}

def categorize(title, notes):
    title_str = str(title).lower() if pd.notna(title) else ''
    notes_str = str(notes).lower() if pd.notna(notes) else ''
    # Check title first
    for cat, pattern in CATEGORIES:
        if re.search(pattern, title_str, re.IGNORECASE):
            return cat
    # Then check notes
    for cat, pattern in CATEGORIES:
        if re.search(pattern, notes_str, re.IGNORECASE):
            return cat
    return "General IT Support"

# Categorize at entry level first, but we need ticket-level categorization
# Get unique tickets with their title and notes (use first occurrence)
ticket_df = df.groupby('TicketID').agg({
    'Title': 'first',
    'Notes': 'first',
    'Total_Hours': 'sum',
}).reset_index()

ticket_df['Category'] = ticket_df.apply(lambda r: categorize(r['Title'], r['Notes']), axis=1)

# Summary by category
cat_summary = ticket_df.groupby('Category').agg(
    Tickets=('TicketID', 'count'),
    Total_Hours=('Total_Hours', 'sum'),
).reset_index()
cat_summary['Avg Hrs/Ticket'] = (cat_summary['Total_Hours'] / cat_summary['Tickets']).round(2)
cat_summary['Total_Hours'] = cat_summary['Total_Hours'].round(2)
cat_summary['Proactive'] = cat_summary['Category'].apply(lambda c: 'Yes' if c in PROACTIVE else 'No')
cat_summary = cat_summary.sort_values('Tickets', ascending=False).reset_index(drop=True)
cat_summary.columns = ['Category', 'Tickets', 'Hours', 'Avg Hrs/Ticket', 'Proactive']

# Add total row
cat_total = pd.DataFrame([{
    'Category': '**TOTAL**',
    'Tickets': cat_summary['Tickets'].sum(),
    'Hours': round(cat_summary['Hours'].sum(), 2),
    'Avg Hrs/Ticket': round(cat_summary['Hours'].sum() / cat_summary['Tickets'].sum(), 2),
    'Proactive': '',
}])
cat_summary = pd.concat([cat_summary, cat_total], ignore_index=True)

print("\n## Ticket Categorization - BWH 2025\n")
print(cat_summary.to_markdown(index=False))

# Proactive vs Reactive summary
proactive_tickets = ticket_df[ticket_df['Category'].isin(PROACTIVE)]
reactive_tickets = ticket_df[~ticket_df['Category'].isin(PROACTIVE)]
print(f"\n**Proactive tickets:** {len(proactive_tickets)} ({round(len(proactive_tickets)/len(ticket_df)*100,1)}%) | "
      f"**Hours:** {round(proactive_tickets['Total_Hours'].sum(),2)}")
print(f"**Reactive tickets:** {len(reactive_tickets)} ({round(len(reactive_tickets)/len(ticket_df)*100,1)}%) | "
      f"**Hours:** {round(reactive_tickets['Total_Hours'].sum(),2)}")
