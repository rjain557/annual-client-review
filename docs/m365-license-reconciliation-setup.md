# M365 License Reconciliation — Setup Playbook

**Goal:** reconcile three sources per client, per month:

1. **Pax8 cost** — what Technijian pays Pax8 per SKU per client
2. **CP recurring invoice** — what Technijian charges the client per SKU
3. **M365 utilization** — assigned vs actually-active users in the client tenant (Graph API via GDAP)

Output: per-client branded DOCX showing margin (cost ↔ revenue) and idle-license recommendations, plus a portfolio rollup.

This file lists everything **you (the operator)** need to do. Items marked _Agent_ are what Claude will build once the prerequisite is in place — they are listed only so the sequencing is clear.

---

## Phase 1 — Pax8 + Margin Reconciliation (no GDAP needed)

Phase 1 answers: _are we losing money on any client's M365 line?_ It does not need any client cooperation.

### 1.1 Generate Pax8 API credentials

1. Sign in to <https://app.pax8.com> as a Pax8 admin.
2. Navigate to **Account Manager → Integrations** (or **User Profile → API Access** depending on which UI you have).
3. Click **Create API Token** (or **Create Application**).
4. Name it `Technijian-AnnualReview-Read`.
5. Scopes — request **read-only** for: Companies, Subscriptions, Products, Invoices, Orders. Skip any "modify" or "create" scopes.
6. Pax8 returns a **Client ID** and **Client Secret**. Copy both.

### 1.2 Save the credentials to the key vault

Create the file `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\pax8.md` with this content:

```markdown
# Pax8 Partner API Credentials

## Account Info
- **Platform:** Pax8 Partner API
- **Base URL:** https://api.pax8.com
- **Auth Type:** OAuth2 client credentials

## Credentials
- **Client ID:** <paste here>
- **Client Secret:** <paste here>

## Scopes
- read:companies, read:subscriptions, read:products, read:invoices, read:orders
```

(Same convention as `keys/m365-graph.md`, `keys/sophos.md`, etc. — the puller reads it via regex.)

### 1.3 Confirm the Pax8 MCP server reference

You said Pax8 publishes an MCP server. Paste me one of:

- The npm package name (e.g. `@pax8/mcp-server`), **or**
- The hosted MCP URL (e.g. `https://mcp.pax8.com/...`), **or**
- A link to Pax8's MCP docs page

Claude will add it via `claude mcp add pax8 ...` and verify connection before the puller is built.

### 1.4 Provide the Pax8 ↔ Client Portal mapping (or accept auto-derivation)

Pax8 identifies clients by its own customer ID. The Client Portal identifies them by `LocationCode` (e.g. `bwh`, `vaf`, `orx`). For Phase 1 I need a name match.

**Option A (recommended):** Claude pulls the Pax8 customer list, name-matches against `clients/<code>/_meta.json`, and writes a draft mapping at `technijian/pax8-pull/_org_mapping.json`. You eyeball it once and fix any ambiguous matches.

**Option B:** You hand me a CSV `pax8_customer_id,location_code` and we skip the auto-derivation. Slower if there are 30 clients.

**Pick one and tell me.**

### 1.5 _Agent_ — Phase 1 build steps (no action required from you)

For visibility, here is what Claude will build once 1.1–1.4 are done:

- `technijian/pax8-pull/scripts/pax8_api.py` — auth + list_companies + list_subscriptions + list_invoices
- `technijian/pax8-pull/scripts/pull_pax8_monthly.py` — writes `clients/<code>/pax8/<YYYY-MM>/subscriptions.json`
- `.claude/skills/pax8-pull/SKILL.md` — repo-scope skill, monthly cadence
- `technijian/pax8-pull/scripts/extract_recurring_invoices.py` — reads existing `clients/<code>/data/invoices.json`, filters `InvoiceType == 'Recurring'` (pattern already in `scripts/bwh_invoice_analysis.py`), writes `clients/<code>/invoices/<YYYY-MM>/recurring.json`
- `technijian/pax8-pull/scripts/build_margin_report.py` — branded DOCX per client + portfolio rollup; uses `_brand.py`; runs `proofread_docx.py` gate
- Schedule entry added to `workstation.md` under "Pipeline schedules"

**Phase 1 deliverable:** per-client and portfolio "License Margin Audit" DOCX showing Pax8 cost ↔ CP recurring price ↔ margin per SKU per client.

---

## Phase 2 — M365 Utilization via GDAP

Phase 2 adds: _are clients actually using what they pay for?_ This is gated on a Microsoft Partner relationship + each client granting GDAP. Plan on this taking 2–4 weeks of client back-and-forth.

### 2.1 Confirm Microsoft Partner status

1. Sign in to <https://partner.microsoft.com>.
2. **Account settings → Partner Profile** — confirm Technijian has an active **Microsoft AI Cloud Partner Program** membership (was MPN). Note the **Partner ID** (also called MPN ID).
3. If membership is lapsed or missing, renew/enroll before continuing — **GDAP cannot be requested without it.**

> If you transact M365 only via Pax8 (indirect reseller), you still need your **own** Partner ID and Partner Center account. Pax8 being your CSP indirect provider does not substitute. This is a common gap — verify before assuming.

**Tell me the Partner ID once confirmed.**

### 2.2 Register a multi-tenant Azure AD app

The current `HiringPipeline-Automation` app is single-tenant (Technijian only). Phase 2 needs a **new** app, multi-tenant, dedicated to GDAP/Graph reads.

1. <https://portal.azure.com> → **Microsoft Entra ID → App registrations → New registration**.
2. Name: `Technijian-Partner-Graph-Read`.
3. Supported account types: **Accounts in any organizational directory (Multitenant)**.
4. Redirect URI: leave blank (app-only flow).
5. Register. Copy the **Application (client) ID** and **Directory (tenant) ID**.
6. **Certificates & secrets → New client secret** — 24-month expiry, copy the **value** immediately (you won't see it again).
7. **API permissions → Add a permission → Microsoft Graph → Application permissions**, add:
    - `Organization.Read.All`
    - `LicenseAssignment.Read.All`
    - `Reports.Read.All`
    - `Directory.Read.All`
    - `User.Read.All`
8. Click **Grant admin consent for Technijian** (this only consents on Technijian's tenant; client tenants consent separately via GDAP in 2.3).

### 2.3 Save the new app's credentials

Create `%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\m365-graph-partner.md`:

```markdown
# Microsoft Graph (Partner Multi-Tenant) Credentials

## Azure AD App: Technijian-Partner-Graph-Read
- **Tenant ID (Technijian):** cab8077a-3f42-4277-b7bd-5c9023e826d8
- **Client ID:** <paste from step 2.2.5>
- **Client Secret:** <paste from step 2.2.6>
- **Secret expires:** <paste expiry date>

## Permissions (Application type, granted on Technijian + each GDAP-onboarded client tenant)
- Organization.Read.All
- LicenseAssignment.Read.All
- Reports.Read.All
- Directory.Read.All
- User.Read.All

## Usage
- Token endpoint per client tenant: https://login.microsoftonline.com/<client-tenant-id>/oauth2/v2.0/token
- Graph base: https://graph.microsoft.com/v1.0
```

> Keep this file separate from `m365-graph.md`. The Mail-only app stays untouched so existing pipelines (weekly-audit, Huntress, Teramind report email) keep working.

### 2.4 Onboard each client to GDAP

GDAP is a per-client approval. Two viable paths:

**Path A — via Pax8's GDAP wizard (preferred):**

1. <https://app.pax8.com> → the customer's record → **Microsoft 365 → GDAP**.
2. Use the wizard to send a GDAP request. Pax8 builds the request URL using Technijian's Partner ID. Roles to request:
    - **Global Reader** — read-only across the whole tenant (covers SKUs, license assignments, reports)
    - _(If you ever want to write — e.g. assign licenses programmatically — request Privileged Authentication Admin or License Admin then. For Phase 2 we only need read.)_
3. Pax8 emails the request URL to the client admin.
4. The client admin clicks the link, signs in to **their** tenant as Global Admin, reviews the requested role, and approves.

**Path B — direct via Partner Center (if Pax8 wizard unavailable for a client):**

1. <https://partner.microsoft.com> → **Customers → Request a reseller relationship** → choose **Granular Delegated Admin Permissions**.
2. Pick role: **Global Reader**. Duration: 730 days (max).
3. Microsoft generates an invitation URL. Email that URL to the client's Global Admin.
4. Client admin approves via the URL.

**Track GDAP status per client in a new file** `clients/_m365_gdap_status.csv`:

```csv
location_code,client_tenant_id,gdap_requested_at,gdap_approved_at,roles_granted,notes
bwh,<tenant-guid>,2026-04-30,,Global Reader,sent via Pax8
vaf,<tenant-guid>,2026-04-30,2026-05-02,Global Reader,
```

I will scaffold this file once you tell me which clients to start with.

### 2.5 Collect each client's tenant ID

Two ways to find a client's tenant ID:

**A — once GDAP is granted:** Claude calls `GET https://graph.microsoft.com/v1.0/contracts` (returns all customer tenants Technijian has a partner relationship with) — auto-discovery, no work for you.

**B — before GDAP is granted (for the request itself):** Ask the client admin, or look them up at <https://login.microsoftonline.com/<client-domain>/.well-known/openid-configuration> — the `issuer` URL contains the tenant GUID.

You don't need to do this manually for every client; the puller will discover via `/contracts` for any client whose GDAP is approved.

### 2.6 _Agent_ — Phase 2 build steps (no action required from you)

For visibility:

- `technijian/m365-pull/scripts/m365_partner_api.py` — token-per-client-tenant, retry on 401, respects throttling
- `technijian/m365-pull/scripts/pull_m365_monthly.py` — iterates `/contracts`, pulls SKUs + license assignments + activity reports per tenant → `clients/<code>/m365/<YYYY-MM>/`
- `.claude/skills/m365-pull/SKILL.md`
- Updated `build_margin_report.py` — adds **Assigned**, **Active 30d**, **Idle %** columns; flags idle ≥ 30% as recommendations
- Schedule entry in `workstation.md`

**Phase 2 deliverable:** per-client and portfolio "License Lifecycle Audit" DOCX with margin **and** utilization, including specific cancel/downsize/escalate recommendations.

---

## What Claude is NOT doing automatically

These are admin actions that require your judgement, an admin login, or third-party approval — they cannot be scripted:

- Generating Pax8 API tokens (1.1)
- Creating the Azure AD app and granting admin consent on Technijian's tenant (2.2)
- Confirming Microsoft Partner Program membership (2.1)
- Sending GDAP requests to clients (2.4) — possible to script via Pax8 API once we have it working, but the **client-side approval** is unavoidable
- Approving GDAP on the client side (the client's Global Admin must do this)

Everything else — pulling, reconciling, reporting, scheduling — is in scope for Claude to build.

---

## Suggested order of operations

1. Today — **1.1 → 1.4** (Pax8 creds + MCP reference + mapping decision). Claude builds Phase 1 in the same session. Phase 1 deliverable lands within hours.
2. This week — **2.1, 2.2, 2.3** (Partner ID confirmation + Azure app registration + keyfile). One-time setup, ~30 minutes.
3. Rolling — **2.4** per client. Send GDAP requests in batches of 5; chase approvals weekly. Each approved client is auto-included in the next monthly pull. Phase 2 deliverable becomes complete client-by-client as approvals come in.

---

## Quick checklist (what to do right now)

- [ ] 1.1  Generate Pax8 API client_id + client_secret
- [ ] 1.2  Create `keys/pax8.md` with creds
- [ ] 1.3  Send Claude the Pax8 MCP server reference (npm name or URL)
- [ ] 1.4  Pick mapping option A (auto-derive) or B (paste CSV)
- [ ] 2.1  Confirm Microsoft Partner ID, send to Claude
- [ ] 2.2  Register `Technijian-Partner-Graph-Read` Azure AD app, grant admin consent
- [ ] 2.3  Create `keys/m365-graph-partner.md` with new app creds
- [ ] 2.4  Send first batch of GDAP requests via Pax8 (start with 5 clients)
- [ ] 2.4  Track approvals in `clients/_m365_gdap_status.csv`

When 1.1–1.4 are done, ping Claude and Phase 1 starts immediately.
