# Client Portal API — Delete Time Entry Endpoint Spec

This document specifies the new server-side capability required for the weekly
time-entry audit skill to enforce the 48-hour adjustment window by physically
removing entries from the time-entry ledger.

The existing client-portal API surface (see `scripts/clientportal/cp_api.py`)
is **read-only** for time entries (`stp_xml_TktEntry_List_Get`). To enforce
deletion, the following additions are required.

---

## 1. Stored procedure — `[timeentry].[stp_TktEntry_Delete]`

### Signature

```sql
CREATE OR ALTER PROCEDURE [timeentry].[stp_TktEntry_Delete]
    @InvDetID            BIGINT,        -- the entry to remove (PK)
    @ActorUserID         INT,           -- who is performing the delete (audit trail)
    @ActorSystem         NVARCHAR(64),  -- e.g. 'WEEKLY-AUDIT-SKILL'
    @Reason              NVARCHAR(512), -- e.g. 'Flagged 2026-04-22 — not adjusted within 48h'
    @CycleID             NVARCHAR(32),  -- e.g. '2026-W18'
    @SoftDelete          BIT = 1,       -- default soft-delete; pass 0 for hard-delete (NOT recommended)
    @AllowAfterInvoiced  BIT = 0,       -- safety: refuse if entry is already on a committed invoice
    @ResultStatus        NVARCHAR(32) OUTPUT,
    @ResultMessage       NVARCHAR(512) OUTPUT
AS
```

### Behavior contract

1. **Look up entry** by `InvDetID`. If not found → set `@ResultStatus = 'NOT_FOUND'` and return.

2. **Refuse if already invoiced** (unless `@AllowAfterInvoiced = 1`):
   - Join to `Inv_Header` (or your invoice-locking flag). If the entry is on an
     invoice with status `Posted`/`Sent`/`Paid` → set `@ResultStatus = 'LOCKED_BY_INVOICE'`,
     populate `@ResultMessage` with the InvoiceID + status, return without modifying.
   - This guard matters because once we send an invoice to a client, you cannot
     silently remove a line item from the source data.

3. **Soft-delete path** (`@SoftDelete = 1`, default and recommended):
   - Set `IsDeleted = 1`, `DeletedAt = SYSUTCDATETIME()`, `DeletedByUserID = @ActorUserID`,
     `DeletedReason = @Reason`, `DeletedBySystem = @ActorSystem`, `DeletedCycleID = @CycleID`.
   - Entry stays in the table but is excluded from `stp_xml_TktEntry_List_Get`
     (existing reporting SP needs `WHERE ISNULL(IsDeleted, 0) = 0` predicate).
   - Soft-deleted rows can be undeleted; pay calculations exclude them.

4. **Hard-delete path** (`@SoftDelete = 0`):
   - Copy the row to `[audit].[TktEntry_Deleted]` with all original fields plus
     audit metadata (actor, reason, cycle, deleted-at).
   - Then `DELETE FROM [timeentry].[TktEntry] WHERE InvDetID = @InvDetID`.
   - **Only use hard-delete after a soft-delete period has expired** (e.g. 90 days).

5. **Set output**:
   - `@ResultStatus IN ('OK','NOT_FOUND','LOCKED_BY_INVOICE','REFUSED','ERROR')`
   - `@ResultMessage` = human-readable detail.

6. **Wrap in `BEGIN TRY / BEGIN CATCH`** and rollback any partial work on error.

### Required schema additions to `[timeentry].[TktEntry]`

If they don't exist already, add the soft-delete columns:

```sql
ALTER TABLE [timeentry].[TktEntry] ADD
    IsDeleted        BIT           NOT NULL DEFAULT 0,
    DeletedAt        DATETIME2     NULL,
    DeletedByUserID  INT           NULL,
    DeletedReason    NVARCHAR(512) NULL,
    DeletedBySystem  NVARCHAR(64)  NULL,
    DeletedCycleID   NVARCHAR(32)  NULL;

CREATE NONCLUSTERED INDEX IX_TktEntry_IsDeleted
    ON [timeentry].[TktEntry] (IsDeleted, TimeEntryDate)
    INCLUDE (InvDetID, AssignedNameID);
```

And update `stp_xml_TktEntry_List_Get` to filter out soft-deleted rows by default:

```sql
-- in stp_xml_TktEntry_List_Get, add to WHERE clause:
AND ISNULL(te.IsDeleted, 0) = 0
```

### Audit table

```sql
CREATE TABLE [audit].[TktEntry_DeleteLog] (
    DeleteLogID      BIGINT IDENTITY(1,1) PRIMARY KEY,
    InvDetID         BIGINT       NOT NULL,
    DeletedAt        DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME(),
    ActorUserID      INT          NOT NULL,
    ActorSystem      NVARCHAR(64) NOT NULL,
    Reason           NVARCHAR(512) NOT NULL,
    CycleID          NVARCHAR(32) NULL,
    WasSoftDelete    BIT          NOT NULL,
    OriginalPayload  NVARCHAR(MAX) NULL,  -- JSON snapshot of the row before deletion
    Tech_AssignedName NVARCHAR(128) NULL,
    Hours            DECIMAL(8,2) NULL,
    Title            NVARCHAR(256) NULL,
    INDEX IX_DeleteLog_Cycle (CycleID),
    INDEX IX_DeleteLog_Tech (Tech_AssignedName, DeletedAt)
);
```

The SP writes one row to this table on every successful delete (soft or hard).

---

## 2. REST endpoint exposure

The client-portal API uses a generic SP-execute pattern:

```
POST /api/modules/{module}/stored-procedures/{db}/{schema}/{name}/execute
```

So no controller code is needed — the SP becomes callable as:

```
POST /api/modules/timeentry/stored-procedures/client-portal/timeentry/stp_TktEntry_Delete/execute
```

with body:

```json
{
  "Parameters": {
    "InvDetID": 1234567,
    "ActorUserID": 412,
    "ActorSystem": "WEEKLY-AUDIT-SKILL",
    "Reason": "Flagged in 2026-W18 audit; not adjusted within 48h window.",
    "CycleID": "2026-W18",
    "SoftDelete": 1,
    "AllowAfterInvoiced": 0
  }
}
```

### Authorization

The existing token middleware (bearer-token via `/api/auth/token`) must enforce:

- The authenticated user has role `TimeEntryAdmin` (new role) **OR** is in the
  hard-coded actor allow-list for the audit skill.
- Recommended: create a service account `svc-weekly-audit@technijian.com` with
  only `TimeEntryAdmin` role; the skill authenticates as this service account.

### Rate limit

10 deletes/minute per actor. The audit skill batches its weekly cycle anyway,
so this is just a safety governor.

### Logging

Every call (success and failure) must write to the API request log with:
- Actor user
- InvDetID requested
- Result status
- Cycle ID

---

## 3. Companion SP — `stp_TktEntry_Get_ByID`

The audit skill needs to re-fetch a single entry by `InvDetID` to verify
"unchanged since flagging" before issuing a delete. The current bulk SP doesn't
support this efficiently. Add:

```sql
CREATE OR ALTER PROCEDURE [timeentry].[stp_TktEntry_Get_ByID]
    @InvDetID BIGINT,
    @XML_OUT  NVARCHAR(MAX) OUTPUT
AS
-- Returns a one-element <Root><TimeEntry>...</TimeEntry></Root> XML
-- with the same field shape as stp_xml_TktEntry_List_Get
```

Exposed as:

```
POST /api/modules/timeentry/stored-procedures/client-portal/timeentry/stp_TktEntry_Get_ByID/execute
```

---

## 4. Companion SP — `stp_TktEntry_Update_TitleHours`

Optional. The audit skill primarily needs *delete*, not *modify* — techs will
adjust their own entries through the Client Portal UI. But if you want the
skill to also be able to **auto-rewrite a title to a coaching suggestion** when
a tech approves it inline, add:

```sql
CREATE OR ALTER PROCEDURE [timeentry].[stp_TktEntry_Update_TitleHours]
    @InvDetID      BIGINT,
    @ActorUserID   INT,
    @NewTitle      NVARCHAR(256) = NULL,  -- NULL = leave unchanged
    @NewHours      DECIMAL(8,2)  = NULL,  -- NULL = leave unchanged
    @Reason        NVARCHAR(512),
    @CycleID       NVARCHAR(32),
    @ResultStatus  NVARCHAR(32) OUTPUT,
    @ResultMessage NVARCHAR(512) OUTPUT
```

Same invoice-lock guard as the delete SP.

---

## 5. Python client surface to add to `cp_api.py`

Once the SPs above are deployed, append this to `scripts/clientportal/cp_api.py`:

```python
def get_time_entry_by_id_xml(inv_det_id: int) -> str:
    r = execute_sp("timeentry", "timeentry", "stp_TktEntry_Get_ByID",
                   {"InvDetID": inv_det_id})
    return sp_xml_out(r)


def delete_time_entry(inv_det_id: int, actor_user_id: int, reason: str,
                      cycle_id: str, soft: bool = True,
                      allow_after_invoiced: bool = False) -> dict:
    r = execute_sp("timeentry", "timeentry", "stp_TktEntry_Delete", {
        "InvDetID": inv_det_id,
        "ActorUserID": actor_user_id,
        "ActorSystem": "WEEKLY-AUDIT-SKILL",
        "Reason": reason,
        "CycleID": cycle_id,
        "SoftDelete": 1 if soft else 0,
        "AllowAfterInvoiced": 1 if allow_after_invoiced else 0,
    })
    op = r.get("outputParameters") or r.get("OutputParameters") or {}
    return {
        "status": next((v for k, v in op.items() if k.lower() == "resultstatus"), None),
        "message": next((v for k, v in op.items() if k.lower() == "resultmessage"), None),
        "raw": r,
    }


def update_time_entry(inv_det_id: int, actor_user_id: int,
                      cycle_id: str, reason: str,
                      new_title: str | None = None,
                      new_hours: float | None = None) -> dict:
    r = execute_sp("timeentry", "timeentry", "stp_TktEntry_Update_TitleHours", {
        "InvDetID": inv_det_id,
        "ActorUserID": actor_user_id,
        "NewTitle": new_title,
        "NewHours": new_hours,
        "Reason": reason,
        "CycleID": cycle_id,
    })
    op = r.get("outputParameters") or r.get("OutputParameters") or {}
    return {
        "status": next((v for k, v in op.items() if k.lower() == "resultstatus"), None),
        "message": next((v for k, v in op.items() if k.lower() == "resultmessage"), None),
        "raw": r,
    }
```

The audit skill's `5_enforce_48h.py` will call `delete_time_entry()` once these
functions are available. Until then, the script writes a `deletion-candidates.csv`
that accounting / dispatch can act on manually.

---

## 6. Deployment checklist

- [ ] Add soft-delete columns to `[timeentry].[TktEntry]`.
- [ ] Add `IX_TktEntry_IsDeleted` index.
- [ ] Update `stp_xml_TktEntry_List_Get` to filter out soft-deleted rows.
- [ ] Create `[audit].[TktEntry_DeleteLog]` table.
- [ ] Create `[timeentry].[stp_TktEntry_Delete]` SP with the contract above.
- [ ] Create `[timeentry].[stp_TktEntry_Get_ByID]` SP.
- [ ] (Optional) Create `[timeentry].[stp_TktEntry_Update_TitleHours]` SP.
- [ ] Create `TimeEntryAdmin` role; assign to `svc-weekly-audit@technijian.com`.
- [ ] Set `CP_USERNAME` / `CP_PASSWORD` env vars (or update keys/client-portal.md)
      for the service account on the box that runs the skill.
- [ ] Append the helper functions above to `scripts/clientportal/cp_api.py`.
- [ ] Set env var `WEEKLY_AUDIT_DELETE_ENABLED=1` to flip the skill from
      report-only mode to commit mode.
- [ ] Smoke test: pick one safe-to-delete entry, run
      `python 5_enforce_48h.py --commit --only-fingerprint <fp>` and verify the
      audit row appears in `[audit].[TktEntry_DeleteLog]`.
- [ ] Verify the entry no longer appears in `stp_xml_TktEntry_List_Get`.
- [ ] Verify pay calculation excludes the soft-deleted row.

---

## 7. Operational rules the skill enforces

These are independent of the SP contract but the skill is configured to honor
them — keeping the SP defensive is still the right call:

1. **Never delete an entry that has been invoiced.** Skill checks the invoice
   list before issuing the delete, and the SP refuses it as a backstop.
2. **Never delete an entry within 48 hours of its creation** unless the tech
   was emailed a flag for it. The skill only deletes entries that were on the
   prior Wednesday's flagged list and were not adjusted by Friday.
3. **Always notify the tech and accounting** before issuing a delete. Email
   templates are in the audit skill.
4. **Soft-delete is the default.** Hard-delete is reserved for an explicit
   admin operation (a separate command, not the weekly cycle).
5. **No deletion runs during the 48 hours after a corporate holiday or PTO
   block** for the affected tech — to be implemented in the skill once HR
   integration exists.
