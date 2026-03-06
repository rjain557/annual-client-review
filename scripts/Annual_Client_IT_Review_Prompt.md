# Annual Client IT Review — Analysis Prompt

## Purpose

This prompt generates a comprehensive annual IT review report for any managed services client. It dynamically detects the client's contract cycle (3, 6, or 12 months), analyzes all billing and time entry data, and produces a professional Word document with financial analysis, service inventory, ticket categorization, and forward-looking projections.

---

## Required Inputs

Upload the following data files for the client under review. Column names may vary — the analysis should adapt to whatever schema is present.

### 1. Time Entries Export (Excel)
All time/labor entries for the review period. Expected fields (adapt as needed):
- Ticket ID, Title, Description/Notes
- Technician/Assigned Name
- Role Type (e.g., Off-Shore Tech Support, Tech Support, CTO, Development)
- Hours: Normal Hours (NH), After-Hours (AH), Onsite
- Date worked

### 2. Invoice Line Items Export (Excel)
All invoices with line-item detail for the review period. Expected fields:
- Invoice Date, Invoice Type (Monthly, Weekly, WeeklyOut, Recurring, OneTimeOut)
- Item code, Description
- Quantity, Unit Price, Line Total

### 3. Client Details / Service Inventory (Excel, optional but recommended)
Current service counts by category, ideally with one sheet per service. Common sheets:
- M365 Licensing (user list with license type)
- Server & Memory Details
- User List / User Archiving
- Security tools (CrowdStrike, Huntress, Cisco Umbrella, etc.)
- Backup (Veeam 365, Image Backup)
- Monitoring (ManageEngine, MyRemote, Ops Manager)
- VoIP / DIDs
- Storage, Network Devices, etc.

---

## Analysis Instructions

You are an IT services financial analyst. Analyze the uploaded data and produce a professional Word document (.docx) covering the sections below. Work through each section methodically, showing your data exploration before generating the report.

### Step 0: Detect Contract Cycle

Before anything else, determine the client's billing cycle by analyzing the invoice data:

```
CYCLE DETECTION LOGIC:
1. Filter to Monthly invoices only (InvoiceType = 'Monthly')
2. Extract unique invoice months
3. Count total months with invoices
4. Look at labor line items specifically:
   - If labor rates/quantities change every 3 months → 3-month cycle
   - If labor rates/quantities change every 6 months → 6-month cycle  
   - If labor rates/quantities are consistent all 12 months → 12-month cycle
   - If only partial year of data → note the coverage period

KEY INDICATORS:
- Rate changes on labor items (e.g., CTO rate goes from $X to $Y)
- Quantity changes on labor allotments (e.g., support hours jump from 100 to 150)
- New labor line items appearing mid-year
- Invoice total step-changes between periods

Report the detected cycle and the adjustment periods found.
```

### Step 1: Data Exploration

Before generating any report content, explore and summarize the raw data:

```
TIME ENTRIES:
- Total entries, unique tickets, date range
- Hours by role type (NH, AH, Onsite)
- Unique technicians and hours per tech
- Identify primary resources (>100 hrs)

INVOICES:
- Total invoices by type (Monthly, Weekly, WeeklyOut, Recurring, OneTimeOut)
- Revenue by invoice type
- Date range coverage
- Monthly run rate trend

CLIENT DETAILS (if provided):
- List all sheets and counts per service
- Note the inventory date
```

### Step 2: Report Sections

Generate a Word document with the following sections. Adapt section numbering and content to what the data supports.

---

#### Section 1: Support Scope & Coverage

Summarize the overall engagement:
- Annual contract value and monthly run rate
- Total hours delivered (by NH, AH, Onsite)
- Remote vs. onsite split
- Number of unique technicians; identify primary resources
- Services included in the monthly contract vs. billed separately

**IMPORTANT — Offshore time zone framing:**
Offshore "after-hours" (AH) refers to India after-hours = US business hours (daytime support). Offshore "normal hours" (NH) refers to India business hours = US overnight (monitoring/maintenance). Frame the coverage model accordingly — this is 24/7 coverage, not a premium-rate issue.

---

#### Section 2: Effective Blended Rates

Calculate blended rates per role using **billed hours from Monthly + WeeklyOut invoices** (not time entry hours, which may under-report due to retainer structures):

```
For each role (IT Support, Development, CTO, etc.):
  Contracted Revenue = SUM(Monthly invoice line items for role)
  Overage Revenue = SUM(WeeklyOut invoice line items for role)
  Total Revenue = Contracted + Overage
  Billed Hours = SUM(qty from Monthly + WeeklyOut for role)
  Blended Rate = Total Revenue / Billed Hours
```

Include a rate card table showing each tier with rate and coverage context:
- Offshore Support (US Daytime) — rate, coverage note
- Offshore Support (US Overnight) — rate, coverage note
- US Tech Support (Remote / Onsite) — rate
- Development (US / Offshore) — rate
- CTO / Advisory — rate, retainer structure

**Watch for retainer structures:** If a role bills a fixed monthly quantity regardless of actual hours (e.g., CTO at 15 hrs/month), note this as a retainer and calculate the blended rate using billed hours, not time entry hours.

---

#### Section 3: Licensing & Recurring Services

**3.1 Monthly Contract Breakdown by Service Category**

Group all Monthly invoice line items into categories and show annual totals:
- Labor (Support, Dev, CTO)
- Cloud Hosting (VMs, compute, storage)
- Security & Endpoint Protection
- Backup & Archiving
- Monitoring & Management (RMM, Ops Manager, Patch Management)
- Email Security (Anti-Spam, DKIM)
- Network & Firewall
- VoIP / Telephony
- Secure Internet
- Pen Testing
- Other

Show a representative monthly invoice detail (typically the most recent month) with all line items, quantities, rates, and totals.

**3.2 Recurring Licensing (Billed Separately)**

Itemize all Recurring invoice items:
- M365 licenses by type (Standard, Basic, Power BI, Copilot, Visio, etc.)
- SPLA licensing (RDP CALs, Server Std, SQL Server)
- SSL certificates (annual)
- Domain registrations (annual)
- Hardware/network subscriptions (Sophos, Edge, VeloCloud)

**3.3 Service Count Tracking (if Client Details provided)**

Compare the latest service inventory against the most recent billed month:
- Show December (or latest) billed count → Current inventory count → Change
- Frame changes as organic growth and provisioning adjustments, NOT billing errors
- Calculate net monthly cost change from the count differences
- Note per-device cost (~$55–60/month per new desktop across the full stack)

---

#### Section 4: Projects & One-Time Spend

Itemize all non-recurring spend:

**4.1 Labor Overage** (WeeklyOut invoices)
- Break down by role, rate, hours, and month
- Note which periods had the heaviest overage and why

**4.2 Hardware Purchases** (OneTimeOut invoices with hardware items)

**4.3 Software Renewals** (OneTimeOut with software/license items)

**4.4 Other One-Time** (setup fees, configuration, late fees, etc.)

**4.5 Predictability Recommendations**
- List expected annual renewals with amounts
- Suggest hardware lifecycle budget based on device count and age
- Recommend right-sizing contract allotments if overage was concentrated

---

#### Section 5: Ticket Categorization

Categorize all unique tickets by analyzing title, description, and notes fields:

```
CATEGORIZATION APPROACH:
1. Parse each ticket's Title + Notes for keywords
2. Assign to categories (examples below — adapt to client's environment):
   - Patch Management
   - General IT Support
   - Monitoring & Alerts
   - Security & Endpoint
   - Email & M365
   - Backup & DR
   - RMM & Agent Management
   - Server Management
   - Software Installation & Updates
   - Phone / VoIP
   - User Onboarding/Offboarding
   - Software Development
   - Workstation & Hardware
   - Printing & Scanning
   - Password & Account Management
   - Firewall & Network
   - File & Permissions
   - Domain & SSL
   - Application-specific (QuickBooks, etc.)

3. Flag each category as Proactive or Reactive
4. Calculate: ticket count, total hours, avg hours/ticket per category
```

Present as a table sorted by ticket count descending, with proactive/reactive flag.

---

#### Section 6: Service Metrics & Trends

**Monthly Volume Table:** Tickets, US Overnight (NH) hours, US Daytime (AH) hours, total hours, hours/ticket by month.

**Notable Trends:**
- Proactive vs. reactive split
- Coverage model balance (US daytime vs overnight hours)
- Monthly volume spikes with context (incidents, projects)
- Development hours hidden in support tickets

**Recommendations:** Based on the data patterns, suggest:
- Automation opportunities (high-volume, low-touch categories)
- Coverage balance monitoring
- Separate tracking for dev work vs. support
- Quarterly count reconciliation
- Hardware refresh budgeting
- Renewal calendar consolidation

---

#### Section 7: Summary

One-page executive summary:
- Total annual spend and per-employee cost
- What's included (scope of managed services)
- Top optimization opportunities with estimated impact

---

#### Section 8: Budget Projections

Project the next calendar year using detected contract cycle:

**Labor Projection:**
```
- Use the DETECTED CYCLE (3/6/12 months) to project labor
- Current run rate × 12 = baseline contracted labor
- If 2025 had a mid-year rate change, note that the prior year total 
  was artificially low/high and project using the current rate
- Contracted labor adjusts every [cycle] months based on actual utilization
- Estimate overage based on historical pattern (trending down if contract 
  was recently right-sized, or similar to prior year if unchanged)
```

**Managed Services Projection:**
```
- Device-based services adjust monthly on the invoice to match actual counts
- Use the latest month's run rate as the baseline
- Note per-desktop incremental cost for growth planning
- Do NOT project aggressive growth curves — this fluctuates naturally
```

**Recurring Licensing Projection:**
- Carry forward current rates
- Note any pilots (e.g., Copilot) that were partial-year in the review period
- Adjust for known seat count changes

**One-Time / Projects Projection:**
- Known annual renewals (list with amounts)
- Hardware lifecycle budget recommendation
- Exclude items that won't recur (3-year licenses, one-time setups)

**Grand Total:**
- Side-by-side table: Prior Year Actual vs. Projected, with Change column
- Narrative explaining the key drivers of any year-over-year change
- Key assumptions listed as bullets

---

## Output Format

Generate a professional Word document (.docx) with:
- Title page with client name, review period, date, Technijian branding
- Table of contents
- Consistent formatting: dark blue headers (#1B3A5C), alternating row shading in tables
- All financial figures right-aligned in tables
- Summary/totals rows in dark blue with white text
- Highlight rows (warnings, key findings) in light yellow/amber
- Page breaks between major sections

---

## Key Principles

1. **Offshore AH = US Daytime.** Always frame offshore after-hours as US business hours coverage, not a premium-rate concern.

2. **Use billed hours, not time entry hours** for blended rate calculations. Time entries may under-report due to retainer structures.

3. **Device services adjust monthly.** Don't frame count changes as billing errors — they're normal monthly adjustments.

4. **Labor adjusts on the detected cycle.** If the cycle is 6 months, project H1 and H2 separately. If 3 months, project by quarter.

5. **Growth projections should be modest.** Use the latest run rate as baseline. Don't extrapolate aggressive growth curves from a single quarter's changes.

6. **Categorize tickets programmatically.** Use keyword matching on titles and notes to classify all tickets, not manual sampling.

7. **Show your work.** Before generating the report, print summary statistics so the user can verify the data looks right before committing to the document.
