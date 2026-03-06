"""
BWH 2025 Time Entries - Comprehensive Analysis
File: all-ticket_timeE_bwh_2025.xlsx
"""

import pandas as pd
import numpy as np
import re
from collections import OrderedDict

# ── Load Data ──────────────────────────────────────────────────────────────
FILE = r"c:\vscode\annual-client-review\annual-client-review\clients\bwh\2025\all-ticket_timeE_bwh_2025.xlsx"
df = pd.read_excel(FILE, engine="openpyxl")

print("=" * 100)
print("BWH 2025 TIME ENTRIES — COMPREHENSIVE ANALYSIS")
print("=" * 100)
print(f"\nRows loaded: {len(df)}")
print(f"Columns: {list(df.columns)}")
print(f"\nFirst 3 rows sample:")
print(df.head(3).to_string())

# ── Convert "NULL" strings to 0 for numeric columns ───────────────────────
numeric_cols = ["NH_HoursWorked", "AH_HoursWorked", "Onsite_HoursWorked",
                "NH_Rate", "AH_Rate", "Onsite_Rate", "DriveTime"]

for col in numeric_cols:
    if col in df.columns:
        df[col] = df[col].replace("NULL", 0)
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

# Parse datetime columns
for col in ["StartDateTime", "EndDateTime"]:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")

# Total hours per entry
df["TotalHours"] = df["NH_HoursWorked"] + df["AH_HoursWorked"] + df["Onsite_HoursWorked"]

# Month column
df["Month"] = df["StartDateTime"].dt.to_period("M")
df["MonthName"] = df["StartDateTime"].dt.strftime("%Y-%m")
df["DayOfWeek"] = df["StartDateTime"].dt.day_name()
df["HourOfDay"] = df["StartDateTime"].dt.hour
df["IsWeekend"] = df["StartDateTime"].dt.dayofweek >= 5

# Fill Title/Notes for text matching
df["Title"] = df["Title"].fillna("").astype(str)
df["Notes"] = df["Notes"].fillna("").astype(str)
df["CombinedText"] = (df["Title"] + " " + df["Notes"]).str.lower()

# ── CATEGORY DEFINITIONS ──────────────────────────────────────────────────
# Order matters: more specific categories first, General IT last as catch-all
CATEGORIES = OrderedDict([
    ("Patch Management", {
        "keywords": ["patch", "missed or failed patch", "windows update", "patching"],
        "proactive": True
    }),
    ("Monitoring & Alerts", {
        "keywords": ["monitoring", "alert", "memory utilization", "disk utilization",
                      "device response", "ops manager", "opsmanager", "high memory",
                      "high cpu", "disk space", "service check"],
        "proactive": True
    }),
    ("Security & Endpoint", {
        "keywords": ["crowdstrike", "huntress", "malware", "antivirus", "umbrella",
                      "security", "threat", "detection", "endpoint protection",
                      "virus", "phishing", "ransomware"],
        "proactive": True
    }),
    ("Email & M365", {
        "keywords": ["email", "outlook", "teams", "sharepoint", "m365", "office 365",
                      "mailbox", "distribution list", "entra", "microsoft 365",
                      "exchange", "onedrive", "o365"],
        "proactive": False
    }),
    ("Backup & DR", {
        "keywords": ["backup", "veeam", "image backup", "disaster recovery", "restore",
                      "recovery point", "backup job", "backup failed"],
        "proactive": True
    }),
    ("RMM & Agent", {
        "keywords": ["rmm", "myremote", "connectwise", "automate", "labtech",
                      "screenconnect", "control agent", "agent offline"],
        "proactive": True
    }),
    ("Server Management", {
        "keywords": ["server", " vm ", "virtual machine", "reboot server",
                      "restart server", "hyper-v", "vmware", "esxi", "host server"],
        "proactive": False
    }),
    ("Phone / VoIP", {
        "keywords": ["phone", "3cx", "voip", "sip", "did", "ring group",
                      "extension", "call queue", "call forwarding", "fax line",
                      "telephone"],
        "proactive": False
    }),
    ("User Onboarding/Offboarding", {
        "keywords": ["onboard", "offboard", "new user", "new hire", "terminate",
                      "new employee", "user setup", "user creation", "account creation",
                      "employee termination"],
        "proactive": False
    }),
    ("Printing & Scanning", {
        "keywords": ["print", "scan", "printer", "scanner", "fax", "copier",
                      "print queue", "print driver"],
        "proactive": False
    }),
    ("Password & Account", {
        "keywords": ["password", "reset password", "account lock", "mfa", "2fa",
                      "authentication", "locked out", "account disabled",
                      "password expired", "login issue"],
        "proactive": False
    }),
    ("Firewall & Network", {
        "keywords": ["firewall", "network", "vpn", "dns", "dhcp", "wifi", "wireless",
                      "sophos", "switch", "router", "subnet", "vlan", "internet",
                      "connectivity"],
        "proactive": False
    }),
    ("Software Installation", {
        "keywords": ["install", "software", "update", "upgrade", "application",
                      "deploy", "uninstall", "license"],
        "proactive": False
    }),
    ("Workstation & Hardware", {
        "keywords": ["workstation", "desktop", "laptop", "hardware", "printer driver",
                      "monitor", "docking station", "keyboard", "mouse", "bios",
                      "blue screen", "bsod"],
        "proactive": False
    }),
    ("File & Permissions", {
        "keywords": ["file", "permission", "shared drive", "folder access",
                      "network drive", "mapped drive", "access denied",
                      "file share"],
        "proactive": False
    }),
    ("Domain & SSL", {
        "keywords": ["domain", "ssl", "certificate", "dns record", "cert",
                      "domain renewal", "active directory", " ad "],
        "proactive": False
    }),
    ("QuickBooks / App-Specific", {
        "keywords": ["quickbooks", "qb", "sage", "erp", "crm"],
        "proactive": False
    }),
    ("General IT Support", {
        "keywords": [],  # catch-all
        "proactive": False
    }),
])


def categorize_text(text):
    """Categorize a ticket based on combined title + notes text."""
    text = text.lower()
    for cat, info in CATEGORIES.items():
        if cat == "General IT Support":
            continue  # skip catch-all during keyword scan
        for kw in info["keywords"]:
            if kw in text:
                return cat
    return "General IT Support"


# ── Build ticket-level DataFrame ──────────────────────────────────────────
ticket_agg = df.groupby("TicketID").agg(
    Title=("Title", "first"),
    CombinedText=("CombinedText", lambda x: " ".join(x)),
    NH_Hours=("NH_HoursWorked", "sum"),
    AH_Hours=("AH_HoursWorked", "sum"),
    Onsite_Hours=("Onsite_HoursWorked", "sum"),
    TotalHours=("TotalHours", "sum"),
    EntryCount=("TicketEntryID", "count"),
    Technicians=("AssignedName", lambda x: ", ".join(sorted(set(str(v) for v in x if str(v) != "NULL")))),
    RoleTypes=("RoleTypeTxt", lambda x: ", ".join(sorted(set(str(v) for v in x if str(v) != "NULL")))),
    FirstEntry=("StartDateTime", "min"),
    LastEntry=("StartDateTime", "max"),
).reset_index()

ticket_agg["Category"] = ticket_agg["CombinedText"].apply(categorize_text)
ticket_agg["IsProactive"] = ticket_agg["Category"].apply(
    lambda c: CATEGORIES.get(c, {}).get("proactive", False)
)

# ══════════════════════════════════════════════════════════════════════════
# 1. TICKET CATEGORIZATION
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 100)
print("1. TICKET CATEGORIZATION")
print("=" * 100)

cat_summary = ticket_agg.groupby("Category").agg(
    TicketCount=("TicketID", "count"),
    TotalHours=("TotalHours", "sum"),
    AvgHoursPerTicket=("TotalHours", "mean"),
    IsProactive=("IsProactive", "first"),
).reset_index()
cat_summary = cat_summary.sort_values("TicketCount", ascending=False)

print(f"\n{'Category':<35} {'Tickets':>8} {'Total Hrs':>10} {'Avg Hrs/Tkt':>12} {'Type':>12}")
print("-" * 80)
total_tickets = 0
total_hours = 0
for _, row in cat_summary.iterrows():
    ptype = "PROACTIVE" if row["IsProactive"] else "REACTIVE"
    print(f"{row['Category']:<35} {row['TicketCount']:>8} {row['TotalHours']:>10.1f} "
          f"{row['AvgHoursPerTicket']:>12.2f} {ptype:>12}")
    total_tickets += row["TicketCount"]
    total_hours += row["TotalHours"]
print("-" * 80)
print(f"{'TOTAL':<35} {total_tickets:>8} {total_hours:>10.1f}")

# Show sample tickets per category
print("\n--- Sample Tickets per Category (up to 5) ---")
for cat in cat_summary["Category"]:
    subset = ticket_agg[ticket_agg["Category"] == cat].nlargest(5, "TotalHours")
    print(f"\n  [{cat}]")
    for _, t in subset.iterrows():
        title_short = t["Title"][:80] if len(t["Title"]) > 80 else t["Title"]
        print(f"    Ticket #{t['TicketID']}  {t['TotalHours']:.1f} hrs  \"{title_short}\"")


# ══════════════════════════════════════════════════════════════════════════
# 2. MONTHLY VOLUME TABLE
# ══════════════════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("2. MONTHLY VOLUME TABLE")
print("=" * 100)

monthly = df.groupby("MonthName").agg(
    UniqueTickets=("TicketID", "nunique"),
    NH_Hours=("NH_HoursWorked", "sum"),
    AH_Hours=("AH_HoursWorked", "sum"),
    Onsite_Hours=("Onsite_HoursWorked", "sum"),
    TotalHours=("TotalHours", "sum"),
    TimeEntries=("TicketEntryID", "count"),
).reset_index()
monthly["HrsPerTicket"] = monthly["TotalHours"] / monthly["UniqueTickets"]
monthly = monthly.sort_values("MonthName")

print(f"\n{'Month':<10} {'Tickets':>8} {'US Overnight':>13} {'US Daytime':>11} "
      f"{'Onsite':>8} {'Total Hrs':>10} {'Hrs/Tkt':>8} {'Entries':>8}")
print("-" * 85)
for _, row in monthly.iterrows():
    print(f"{row['MonthName']:<10} {row['UniqueTickets']:>8} {row['NH_Hours']:>13.1f} "
          f"{row['AH_Hours']:>11.1f} {row['Onsite_Hours']:>8.1f} {row['TotalHours']:>10.1f} "
          f"{row['HrsPerTicket']:>8.2f} {row['TimeEntries']:>8}")
print("-" * 85)
print(f"{'TOTAL':<10} {monthly['UniqueTickets'].sum():>8} {monthly['NH_Hours'].sum():>13.1f} "
      f"{monthly['AH_Hours'].sum():>11.1f} {monthly['Onsite_Hours'].sum():>8.1f} "
      f"{monthly['TotalHours'].sum():>10.1f} {'':>8} {monthly['TimeEntries'].sum():>8}")

# Year-over-year monthly avg
avg_tickets = monthly["UniqueTickets"].mean()
avg_hours = monthly["TotalHours"].mean()
print(f"\nMonthly Averages: {avg_tickets:.0f} tickets/month, {avg_hours:.1f} hours/month")


# ══════════════════════════════════════════════════════════════════════════
# 3. TECHNICIAN ANALYSIS
# ══════════════════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("3. TECHNICIAN ANALYSIS")
print("=" * 100)

tech = df.groupby("AssignedName").agg(
    TotalHours=("TotalHours", "sum"),
    NH_Hours=("NH_HoursWorked", "sum"),
    AH_Hours=("AH_HoursWorked", "sum"),
    Onsite_Hours=("Onsite_HoursWorked", "sum"),
    Entries=("TicketEntryID", "count"),
    UniqueTickets=("TicketID", "nunique"),
    RoleType=("RoleTypeTxt", lambda x: x.mode().iloc[0] if len(x.mode()) > 0 else "Unknown"),
    RoleTypeID=("RoleType", lambda x: x.mode().iloc[0] if len(x.mode()) > 0 else "Unknown"),
    FirstEntry=("StartDateTime", "min"),
    LastEntry=("StartDateTime", "max"),
).reset_index()
tech = tech.sort_values("TotalHours", ascending=False)
tech["Primary"] = tech["TotalHours"] >= 100

print(f"\n{'Technician':<30} {'Role':<25} {'Total Hrs':>9} {'NH Hrs':>8} {'AH Hrs':>8} "
      f"{'Onsite':>7} {'Entries':>7} {'Tickets':>7} {'Primary?':>9}")
print("-" * 120)
for _, row in tech.iterrows():
    role = str(row["RoleType"])[:24]
    prim = "YES" if row["Primary"] else ""
    print(f"{str(row['AssignedName'])[:29]:<30} {role:<25} {row['TotalHours']:>9.1f} "
          f"{row['NH_Hours']:>8.1f} {row['AH_Hours']:>8.1f} {row['Onsite_Hours']:>7.1f} "
          f"{row['Entries']:>7} {row['UniqueTickets']:>7} {prim:>9}")
print("-" * 120)
print(f"{'TOTAL':<56} {tech['TotalHours'].sum():>9.1f} "
      f"{tech['NH_Hours'].sum():>8.1f} {tech['AH_Hours'].sum():>8.1f} "
      f"{tech['Onsite_Hours'].sum():>7.1f} {tech['Entries'].sum():>7} ")

primary_techs = tech[tech["Primary"]]
print(f"\nPrimary Resources (100+ hours): {len(primary_techs)}")
for _, row in primary_techs.iterrows():
    span = ""
    if pd.notna(row["FirstEntry"]) and pd.notna(row["LastEntry"]):
        span = f" (active {row['FirstEntry'].strftime('%Y-%m-%d')} to {row['LastEntry'].strftime('%Y-%m-%d')})"
    print(f"  - {row['AssignedName']}: {row['TotalHours']:.1f} hrs, {row['UniqueTickets']} tickets{span}")


# ══════════════════════════════════════════════════════════════════════════
# 4. COVERAGE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("4. COVERAGE ANALYSIS")
print("=" * 100)

# Weekend vs Weekday
print("\n--- Weekend vs Weekday ---")
weekend_entries = df["IsWeekend"].sum()
weekday_entries = len(df) - weekend_entries
print(f"  Weekday entries: {weekday_entries} ({weekday_entries/len(df)*100:.1f}%)")
print(f"  Weekend entries: {weekend_entries} ({weekend_entries/len(df)*100:.1f}%)")

weekend_hours = df[df["IsWeekend"]]["TotalHours"].sum()
weekday_hours = df[~df["IsWeekend"]]["TotalHours"].sum()
print(f"  Weekday hours:  {weekday_hours:.1f}")
print(f"  Weekend hours:  {weekend_hours:.1f}")

# Day of week breakdown
print("\n--- Entries by Day of Week ---")
dow_counts = df["DayOfWeek"].value_counts()
dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
for day in dow_order:
    cnt = dow_counts.get(day, 0)
    hrs = df[df["DayOfWeek"] == day]["TotalHours"].sum()
    print(f"  {day:<12} {cnt:>6} entries   {hrs:>8.1f} hours")

# Hour of day distribution
print("\n--- Hour-of-Day Distribution (24hr) ---")
hour_counts = df.groupby("HourOfDay").agg(
    Entries=("TicketEntryID", "count"),
    Hours=("TotalHours", "sum")
)
print(f"  {'Hour':<6} {'Entries':>8} {'Hours':>10}")
for hour in range(24):
    if hour in hour_counts.index:
        e = hour_counts.loc[hour, "Entries"]
        h = hour_counts.loc[hour, "Hours"]
        bar = "#" * int(e / max(hour_counts["Entries"]) * 40)
        print(f"  {hour:02d}:00  {e:>8} {h:>10.1f}  {bar}")
    else:
        print(f"  {hour:02d}:00  {0:>8} {0:>10.1f}")

# NH vs AH split
total_nh = df["NH_HoursWorked"].sum()
total_ah = df["AH_HoursWorked"].sum()
total_onsite = df["Onsite_HoursWorked"].sum()
grand_total = total_nh + total_ah + total_onsite

print(f"\n--- Hours Type Split ---")
print(f"  NH (US Overnight / Off-hours):  {total_nh:>10.1f} hrs  ({total_nh/grand_total*100:.1f}%)")
print(f"  AH (US Daytime / After-hours):  {total_ah:>10.1f} hrs  ({total_ah/grand_total*100:.1f}%)")
print(f"  Onsite:                         {total_onsite:>10.1f} hrs  ({total_onsite/grand_total*100:.1f}%)")
print(f"  Grand Total:                    {grand_total:>10.1f} hrs")

# Onsite details
print(f"\n--- Onsite Details ---")
onsite_entries = df[df["Onsite_HoursWorked"] > 0]
if len(onsite_entries) > 0:
    print(f"  Total onsite entries: {len(onsite_entries)}")
    print(f"  Total onsite hours: {onsite_entries['Onsite_HoursWorked'].sum():.1f}")
    print(f"\n  {'Date':<12} {'TicketID':>8} {'Hours':>6} {'Technician':<25} Title")
    print("  " + "-" * 100)
    for _, row in onsite_entries.sort_values("StartDateTime").iterrows():
        dt = row["StartDateTime"].strftime("%Y-%m-%d") if pd.notna(row["StartDateTime"]) else "N/A"
        title_short = str(row["Title"])[:50]
        print(f"  {dt:<12} {row['TicketID']:>8} {row['Onsite_HoursWorked']:>6.1f} "
              f"{str(row['AssignedName'])[:24]:<25} {title_short}")
else:
    print("  No onsite entries found.")

# Drive time
drive_entries = df[df["DriveTime"] > 0]
if len(drive_entries) > 0:
    print(f"\n--- Drive Time Details ---")
    print(f"  Total drive time entries: {len(drive_entries)}")
    print(f"  Total drive time hours: {drive_entries['DriveTime'].sum():.1f}")


# ══════════════════════════════════════════════════════════════════════════
# 5. TOP 20 TICKETS BY HOURS
# ══════════════════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("5. TOP 20 TICKETS BY HOURS")
print("=" * 100)

top20 = ticket_agg.nlargest(20, "TotalHours")
print(f"\n{'#':>3} {'TicketID':>9} {'Total Hrs':>10} {'NH Hrs':>8} {'AH Hrs':>8} "
      f"{'Entries':>7} {'Category':<25} {'Title':<50}")
print("-" * 130)
for i, (_, row) in enumerate(top20.iterrows(), 1):
    title_short = row["Title"][:49] if len(row["Title"]) > 49 else row["Title"]
    print(f"{i:>3} {row['TicketID']:>9} {row['TotalHours']:>10.1f} {row['NH_Hours']:>8.1f} "
          f"{row['AH_Hours']:>8.1f} {row['EntryCount']:>7} {row['Category']:<25} {title_short:<50}")

# Also print technicians for top 20
print(f"\n--- Top 20 Ticket Details (Technicians & Roles) ---")
for i, (_, row) in enumerate(top20.iterrows(), 1):
    print(f"  #{i} Ticket {row['TicketID']}: {row['Technicians']}")
    print(f"      Roles: {row['RoleTypes']}")


# ══════════════════════════════════════════════════════════════════════════
# 6. PROACTIVE VS REACTIVE SPLIT
# ══════════════════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("6. PROACTIVE VS REACTIVE SPLIT")
print("=" * 100)

proactive = ticket_agg[ticket_agg["IsProactive"]]
reactive = ticket_agg[~ticket_agg["IsProactive"]]

print(f"\n{'Type':<15} {'Tickets':>8} {'Ticket %':>9} {'Hours':>10} {'Hour %':>8} {'Avg Hrs/Tkt':>12}")
print("-" * 65)
total_t = len(ticket_agg)
total_h = ticket_agg["TotalHours"].sum()
p_t = len(proactive)
p_h = proactive["TotalHours"].sum()
r_t = len(reactive)
r_h = reactive["TotalHours"].sum()
print(f"{'PROACTIVE':<15} {p_t:>8} {p_t/total_t*100:>8.1f}% {p_h:>10.1f} {p_h/total_h*100:>7.1f}% {p_h/p_t if p_t else 0:>12.2f}")
print(f"{'REACTIVE':<15} {r_t:>8} {r_t/total_t*100:>8.1f}% {r_h:>10.1f} {r_h/total_h*100:>7.1f}% {r_h/r_t if r_t else 0:>12.2f}")
print("-" * 65)
print(f"{'TOTAL':<15} {total_t:>8} {'100.0%':>9} {total_h:>10.1f} {'100.0%':>8}")

# Proactive breakdown by category
print(f"\n--- Proactive Categories Breakdown ---")
pro_cats = proactive.groupby("Category").agg(
    Tickets=("TicketID", "count"),
    Hours=("TotalHours", "sum"),
).sort_values("Tickets", ascending=False)
for _, row in pro_cats.iterrows():
    print(f"  {row.name:<35} {row['Tickets']:>5} tickets   {row['Hours']:>8.1f} hours")

# Reactive breakdown by category
print(f"\n--- Reactive Categories Breakdown ---")
react_cats = reactive.groupby("Category").agg(
    Tickets=("TicketID", "count"),
    Hours=("TotalHours", "sum"),
).sort_values("Tickets", ascending=False)
for _, row in react_cats.iterrows():
    print(f"  {row.name:<35} {row['Tickets']:>5} tickets   {row['Hours']:>8.1f} hours")

# Monthly proactive/reactive trend
print(f"\n--- Monthly Proactive vs Reactive Trend ---")
# Map ticket category back to entries
df_merged = df.merge(ticket_agg[["TicketID", "Category", "IsProactive"]], on="TicketID", how="left")
monthly_pr = df_merged.groupby(["MonthName", "IsProactive"]).agg(
    Tickets=("TicketID", "nunique"),
    Hours=("TotalHours", "sum"),
).reset_index()

months_sorted = sorted(df_merged["MonthName"].dropna().unique())
print(f"  {'Month':<10} {'Pro Tkts':>9} {'Pro Hrs':>9} {'React Tkts':>11} {'React Hrs':>10} {'Pro %':>7}")
print("  " + "-" * 60)
for m in months_sorted:
    pro_row = monthly_pr[(monthly_pr["MonthName"] == m) & (monthly_pr["IsProactive"] == True)]
    react_row = monthly_pr[(monthly_pr["MonthName"] == m) & (monthly_pr["IsProactive"] == False)]
    pt = pro_row["Tickets"].values[0] if len(pro_row) > 0 else 0
    ph = pro_row["Hours"].values[0] if len(pro_row) > 0 else 0
    rt = react_row["Tickets"].values[0] if len(react_row) > 0 else 0
    rh = react_row["Hours"].values[0] if len(react_row) > 0 else 0
    total_m_t = pt + rt
    pro_pct = pt / total_m_t * 100 if total_m_t > 0 else 0
    print(f"  {m:<10} {pt:>9} {ph:>9.1f} {rt:>11} {rh:>10.1f} {pro_pct:>6.1f}%")


# ══════════════════════════════════════════════════════════════════════════
# SUMMARY STATS
# ══════════════════════════════════════════════════════════════════════════
print("\n\n" + "=" * 100)
print("EXECUTIVE SUMMARY")
print("=" * 100)
print(f"""
  Total time entries:          {len(df):,}
  Total unique tickets:        {ticket_agg['TicketID'].nunique():,}
  Total hours worked:          {grand_total:,.1f}
  Average hours per ticket:    {grand_total / ticket_agg['TicketID'].nunique():.2f}
  Average entries per ticket:  {len(df) / ticket_agg['TicketID'].nunique():.1f}

  Date range:                  {df['StartDateTime'].min().strftime('%Y-%m-%d')} to {df['StartDateTime'].max().strftime('%Y-%m-%d')}
  Months covered:              {df['MonthName'].nunique()}
  Unique technicians:          {df['AssignedName'].nunique()}
  Primary resources (100+ hrs): {len(primary_techs)}

  NH (US Overnight) hours:     {total_nh:,.1f} ({total_nh/grand_total*100:.1f}%)
  AH (US Daytime) hours:       {total_ah:,.1f} ({total_ah/grand_total*100:.1f}%)
  Onsite hours:                {total_onsite:,.1f} ({total_onsite/grand_total*100:.1f}%)

  Proactive tickets:           {p_t} ({p_t/total_t*100:.1f}%) — {p_h:.1f} hours
  Reactive tickets:            {r_t} ({r_t/total_t*100:.1f}%) — {r_h:.1f} hours

  Weekend coverage:            {weekend_entries} entries ({weekend_entries/len(df)*100:.1f}%)
  RoleType 1236 (Offshore):    {len(df[df['RoleType']==1236])} entries
  RoleType 1232 (Tech Support): {len(df[df['RoleType']==1232])} entries
""")

print("=" * 100)
print("ANALYSIS COMPLETE")
print("=" * 100)
