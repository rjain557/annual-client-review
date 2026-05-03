"""ManageEngine Endpoint Central MSP 11 - SQL backend client.

Covers data the REST API doesn't expose:

    list_customers              - all 32 MSP customers (CustomerInfo)
    list_computers              - per-customer hardware/OS inventory (joins
                                  Resource, InvComputer, InvComputerOSRel,
                                  InvComputerExtn for warranty)
    installed_software          - per-machine software (InvComputerToManagedSWRel
                                  + InvManagedSW + SoftwareDetails)
    missing_patches             - per-machine patches awaiting install
    installed_patches           - per-machine installed patches (with deploy
                                  timestamp + error code)
    superceded_installed        - patches installed but later superseded
    patch_scan_status           - last patch scan per machine
    per_machine_patch_summary   - aggregate counts per machine
    customer_event_log          - EC server events scoped to one customer
    resource_event_log          - EC server events scoped to one machine
    hardware_audit_history      - per-machine hardware add/remove audit
    software_audit_history      - per-machine software install/uninstall audit
    performance_status          - reports whether Endpoint Insight is enabled
                                  (it isn't on this server, so EICpuUsage,
                                  EIMemoryUsage etc. are empty)

Auth: Windows 11 Home (this workstation) can't generate SSPI for cross-domain
SQL Server, so we use ``pymssql`` (FreeTDS) with NTLM via ``host\\user``.

Reads creds from ``%USERPROFILE%/OneDrive - Technijian, Inc/Documents/
VSCODE/keys/myrmm-sql.md``.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pymssql

DEFAULT_HOST = "10.100.13.11"
DEFAULT_DB = "desktopcentral"
DEFAULT_KEYFILE = (
    Path(os.environ.get("USERPROFILE", str(Path.home())))
    / "OneDrive - Technijian, Inc"
    / "Documents"
    / "VSCODE"
    / "keys"
    / "myrmm-sql.md"
)

# Resource types in ME's schema:
#   1   = managed endpoint (workstation/server)
#   2   = ??? (mixed; mostly excluded)
#   5   = mobile device
#   101 = group (e.g. "All Computers Group")
#   121 = ??? probably probe/network/discovered
#   150 = ???
COMPUTER_RESOURCE_TYPES = (1,)


def _load_creds() -> tuple[str, str]:
    env_user = os.environ.get("MYRMM_SQL_USER")
    env_pass = os.environ.get("MYRMM_SQL_PASSWORD")
    if env_user and env_pass:
        return env_user, env_pass
    if not DEFAULT_KEYFILE.exists():
        raise RuntimeError(f"keyfile missing: {DEFAULT_KEYFILE}")
    text = DEFAULT_KEYFILE.read_text(encoding="utf-8", errors="replace")
    user_m = re.search(r"\*\*Username:\*\*\s*(\S+)", text)
    pass_m = re.search(r"\*\*Password:\*\*\s*(\S.*?)\s*$", text, re.MULTILINE)
    if not user_m or not pass_m:
        raise RuntimeError(f"could not parse Username/Password from {DEFAULT_KEYFILE}")
    return user_m.group(1).strip(), pass_m.group(1).strip()


@contextmanager
def connect(host: str = DEFAULT_HOST, database: str = DEFAULT_DB, user_form: str | None = None) -> Iterator[pymssql.Connection]:
    """Connect with NTLM via host\\user — works from non-domain workstations."""
    user, password = _load_creds()
    if user_form is None:
        bare = user.split("\\")[-1]
        user_form = f"TE-DC-MYRMM-SQL\\{bare}"
    conn = pymssql.connect(
        server=host,
        user=user_form,
        password=password,
        database=database,
        login_timeout=10,
        timeout=600,
        as_dict=True,
    )
    try:
        yield conn
    finally:
        conn.close()


# ----------------------------- customers -------------------------------------

def list_customers(conn: pymssql.Connection) -> list[dict]:
    """All MSP customers (32) with id, name, email, timezone."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT CUSTOMER_ID, CUSTOMER_NAME, CUSTOMER_EMAIL, TIMEZONE,
               ACCOUNT_HEAD_NAME, ADDED_TIME, UPDATED_TIME
        FROM CustomerInfo
        ORDER BY CUSTOMER_NAME
        """
    )
    return cur.fetchall()


# ----------------------------- inventory -------------------------------------

def list_computers(conn: pymssql.Connection, customer_id: int) -> list[dict]:
    """Active managed endpoints (workstations/servers) for one customer,
    enriched with hardware (RAM/disk/model), OS, and warranty info."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.RESOURCE_ID,
            r.NAME              AS resource_name,
            r.DOMAIN_NETBIOS_NAME AS domain_or_workgroup,
            r.RESOURCE_TYPE,
            r.DB_ADDED_TIME,
            r.DB_UPDATED_TIME,
            ic.MODEL,
            ic.MANUFACTURER_ID,
            ic.SERVICETAG,
            ic.SYSTEM_TYPE,
            ic.NO_OF_PROCESSORS,
            ic.TOTAL_RAM_MEMORY_GB,
            ic.TOTAL_SIZE_GB     AS disk_total_gb,
            ic.FREE_SPACE_GB     AS disk_free_gb,
            ic.DISK_USED_PERCENTAGE,
            ic.DISK_FREE_PERCENTAGE,
            ic.PRIMARY_OWNER_NAME,
            ic.YEAR_OF_INSTALLATION,
            ic.STATUS            AS computer_status,
            ic.BOOT_UP_STATE,
            ic.DESCRIPTION       AS computer_description,
            ico.OS_VERSION,
            ico.SERVICE_PACK     AS os_caption,
            ico.BUILD_NUMBER,
            ico.INSTALLED_DATE   AS os_installed_date,
            ice.WARRANTY_EXPIRY_DATE,
            ice.WARRANTY_STATUS,
            ice.SHIPPING_DATE
        FROM Resource r
        LEFT JOIN InvComputer        ic  ON ic.COMPUTER_ID  = r.RESOURCE_ID
        LEFT JOIN InvComputerOSRel   ico ON ico.COMPUTER_ID = r.RESOURCE_ID
        LEFT JOIN InvComputerExtn    ice ON ice.COMPUTER_ID = r.RESOURCE_ID
        WHERE r.CUSTOMER_ID = %d
          AND r.IS_INACTIVE = 'False'
          AND r.RESOURCE_TYPE IN (1)
        ORDER BY r.NAME
        """,
        (customer_id,),
    )
    return cur.fetchall()


def installed_software(conn: pymssql.Connection, customer_id: int) -> list[dict]:
    """Per-machine installed software.

    Joins ``InvComputerToManagedSWRel`` (per-machine→sw link, where
    ``MANAGED_SW_ID == SOFTWARE_ID``) to ``InvSW`` (the per-customer
    software catalog with name/version/vendor).
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.RESOURCE_ID,
            r.NAME              AS resource_name,
            isw.SOFTWARE_ID,
            isw.SOFTWARE_NAME,
            isw.SOFTWARE_VERSION,
            isw.DISPLAY_NAME,
            isw.MANUFACTURER_ID,
            isw.SW_TYPE,
            isw.IS_UNINSTALLABLE,
            isw.INSTALLED_FORMAT,
            isw.IS_IN_USE,
            isw.IS_USAGE_PROHIBITED,
            isw.DETECTED_TIME,
            isw.UPDATED_TIME,
            ictm.INSTALLATION_COUNT
        FROM Resource r
        JOIN InvComputerToManagedSWRel ictm ON ictm.COMPUTER_ID = r.RESOURCE_ID
        JOIN InvSW                     isw  ON isw.SOFTWARE_ID  = ictm.MANAGED_SW_ID
        WHERE r.CUSTOMER_ID = %d
          AND r.IS_INACTIVE = 'False'
          AND r.RESOURCE_TYPE IN (1)
        ORDER BY r.NAME, isw.SOFTWARE_NAME
        """,
        (customer_id,),
    )
    return cur.fetchall()


# ----------------------------- patches ---------------------------------------

def missing_patches(conn: pymssql.Connection, customer_id: int) -> list[dict]:
    """Per-machine missing patches with severity + description."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.RESOURCE_ID,
            r.NAME              AS resource_name,
            r.DOMAIN_NETBIOS_NAME AS domain_or_workgroup,
            aps.PATCH_ID,
            p.PATCHNAME,
            p.BULLETINID,
            p.SEVERITYID,
            p.ISSUPERCEDED,
            p.SUPERCEDEDBY,
            p.REBOOT_REQ_STATUS,
            pd.DESCRIPTION,
            pd.RELEASEDTIME,
            aps.STATUS          AS patch_status,
            aps.STATUS_ID       AS patch_status_id,
            aps.UPDATED_TIME    AS status_updated_time,
            aps.REMARKS
        FROM AffectedPatchStatus aps
        JOIN Resource r       ON r.RESOURCE_ID = aps.RESOURCE_ID
        JOIN Patch p          ON p.PATCHID     = aps.PATCH_ID
        LEFT JOIN PatchDetails pd ON pd.PATCHID = aps.PATCH_ID
        WHERE r.CUSTOMER_ID = %d
          AND r.IS_INACTIVE = 'False'
        ORDER BY r.NAME, p.SEVERITYID DESC, p.PATCHNAME
        """,
        (customer_id,),
    )
    return cur.fetchall()


def installed_patches(conn: pymssql.Connection, customer_id: int) -> list[dict]:
    """Per-machine installed patches with deploy timestamp + error code."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.RESOURCE_ID, r.NAME AS resource_name,
            ips.PATCH_ID, p.PATCHNAME, p.BULLETINID, p.SEVERITYID,
            ips.DEPLOY_STATUS, ips.DEPLOY_STATUS_ID,
            ips.INSTALLED_TIME, ips.ERROR_CODE,
            ips.UPDATED_TIME AS status_updated_time, ips.REMARKS
        FROM InstallPatchStatus ips
        JOIN Resource r ON r.RESOURCE_ID = ips.RESOURCE_ID
        JOIN Patch p    ON p.PATCHID     = ips.PATCH_ID
        WHERE r.CUSTOMER_ID = %d
          AND r.IS_INACTIVE = 'False'
        ORDER BY r.NAME, ips.INSTALLED_TIME DESC
        """,
        (customer_id,),
    )
    return cur.fetchall()


def superceded_installed(conn: pymssql.Connection, customer_id: int) -> list[dict]:
    """Patches installed earlier but later superseded by newer patches."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.RESOURCE_ID, r.NAME AS resource_name,
            sips.PATCH_ID, p.PATCHNAME, p.BULLETINID, p.SEVERITYID,
            p.SUPERCEDEDBY, sips.INSTALLED_TIME,
            sips.DEPLOY_STATUS, sips.DEPLOY_STATUS_ID, sips.ERROR_CODE
        FROM SupercededInstallPatchStatus sips
        JOIN Resource r ON r.RESOURCE_ID = sips.RESOURCE_ID
        JOIN Patch p    ON p.PATCHID     = sips.PATCH_ID
        WHERE r.CUSTOMER_ID = %d
          AND r.IS_INACTIVE = 'False'
        ORDER BY r.NAME, sips.INSTALLED_TIME DESC
        """,
        (customer_id,),
    )
    return cur.fetchall()


def patch_scan_status(conn: pymssql.Connection, customer_id: int) -> list[dict]:
    """Last patch scan per machine."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.RESOURCE_ID, r.NAME AS resource_name,
            pcs.LAST_SCAN_TIME, pcs.SCAN_STATUS, pcs.SCAN_STATUS_ID,
            pcs.LAST_SUCCESSFUL_SCAN, pcs.LAST_SCAN_DIFF_TIME,
            pcs.REMARKS, pcs.DB_UPDATED_TIME
        FROM PatchClientScanStatus pcs
        JOIN Resource r ON r.RESOURCE_ID = pcs.RESOURCE_ID
        WHERE r.CUSTOMER_ID = %d
          AND r.IS_INACTIVE = 'False'
        ORDER BY r.NAME
        """,
        (customer_id,),
    )
    return cur.fetchall()


def per_machine_patch_summary(conn: pymssql.Connection, customer_id: int) -> list[dict]:
    """One row per machine with missing/installed/superceded counts + last scan."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.RESOURCE_ID,
            r.NAME AS resource_name,
            r.DOMAIN_NETBIOS_NAME AS domain_or_workgroup,
            (SELECT COUNT(*) FROM AffectedPatchStatus WHERE RESOURCE_ID = r.RESOURCE_ID) AS missing_count,
            (SELECT COUNT(*) FROM InstallPatchStatus  WHERE RESOURCE_ID = r.RESOURCE_ID) AS installed_count,
            (SELECT COUNT(*) FROM SupercededInstallPatchStatus WHERE RESOURCE_ID = r.RESOURCE_ID) AS superceded_count,
            pcs.LAST_SCAN_TIME, pcs.SCAN_STATUS, pcs.LAST_SUCCESSFUL_SCAN
        FROM Resource r
        LEFT JOIN PatchClientScanStatus pcs ON pcs.RESOURCE_ID = r.RESOURCE_ID
        WHERE r.CUSTOMER_ID = %d
          AND r.IS_INACTIVE = 'False'
          AND r.RESOURCE_TYPE IN (1)
        ORDER BY r.NAME
        """,
        (customer_id,),
    )
    return cur.fetchall()


# ----------------------------- patch windows ---------------------------------

# EC's day-of-week numbering: 1=Sun, 2=Mon, 3=Tue, 4=Wed, 5=Thu, 6=Fri, 7=Sat
DOW_NAMES = {1: "Sun", 2: "Mon", 3: "Tue", 4: "Wed", 5: "Thu", 6: "Fri", 7: "Sat"}


def _decode_dow(spec: str | None) -> list[str]:
    """Decode EC ``WINDOW_DAY_OF_WEEK`` like ``"6,7"`` to ``["Fri","Sat"]``."""
    if not spec:
        return []
    out = []
    for tok in str(spec).split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.append(DOW_NAMES.get(int(tok), tok))
    return out


def _decode_wom(spec: str | None) -> list[str]:
    """Decode ``WINDOW_WEEK_OF_MONTH`` like ``"1,2,3,4,5"`` to a label.
    1-5 means every week in the month."""
    if not spec:
        return []
    parts = [p.strip() for p in str(spec).split(",") if p.strip().isdigit()]
    if sorted(parts) == ["1", "2", "3", "4", "5"]:
        return ["every week"]
    week_names = {"1": "1st", "2": "2nd", "3": "3rd", "4": "4th", "5": "5th"}
    return [week_names.get(p, p) for p in parts]


def patch_windows(conn: pymssql.Connection) -> list[dict]:
    """Per-customer patch deployment windows from EC's APD task config.

    Joins APDTasks (per-customer Automated Patch Deployment task) →
    TaskDetails (name + status) → TaskToCustomerRel → CustomerInfo
    → TaskToCollection → CollnToDeployTemplate → DeploymentTemplates
    → DepTemplateToExecWindow (the actual schedule).
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            ci.CUSTOMER_ID, ci.CUSTOMER_NAME, ci.TIMEZONE,
            apd.TASK_ID, apd.PLATFORM_ID,
            td.TASKNAME, td.STATUS AS task_status,
            td.STARTTIME, td.OWNER,
            dt.TEMPLATE_ID, dt.TEMPLATE_NAME, dt.TEMPLATE_DESCRIPTION,
            dt.REBOOT_OPTION, dt.SKIP_DEPLOYMENT, dt.TIMEZONE AS template_timezone,
            ew.TEMP_WINDOW_ID,
            ew.WINDOW_START_TIME, ew.WINDOW_END_TIME,
            ew.WINDOW_DAY_OF_WEEK, ew.WINDOW_WEEK_OF_MONTH,
            ew.WINDOW_MONTHS, ew.WINDOW_DATE, ew.IS_REBOOT_WINDOW
        FROM APDTasks apd
        JOIN TaskDetails td        ON td.TASK_ID = apd.TASK_ID
        JOIN TaskToCustomerRel tcr ON tcr.TASK_ID = apd.TASK_ID
        JOIN CustomerInfo ci       ON ci.CUSTOMER_ID = tcr.CUSTOMER_ID
        JOIN TaskToCollection ttc  ON ttc.TASK_ID = apd.TASK_ID
        JOIN CollnToDeployTemplate ctd ON ctd.COLLECTION_ID = ttc.COLLECTION_ID
        JOIN DeploymentTemplates dt    ON dt.TEMPLATE_ID = ctd.TEMPLATE_ID
        LEFT JOIN DepTemplateToExecWindow ew ON ew.TEMPLATE_ID = dt.TEMPLATE_ID
        ORDER BY ci.CUSTOMER_NAME, apd.TASK_ID, ew.TEMP_WINDOW_ID
        """
    )
    rows = cur.fetchall()
    # Annotate each row with human-readable schedule labels
    for row in rows:
        row["window_days"] = _decode_dow(row.get("WINDOW_DAY_OF_WEEK"))
        row["window_weeks"] = _decode_wom(row.get("WINDOW_WEEK_OF_MONTH"))
        row["window_summary"] = (
            f"{row.get('WINDOW_START_TIME','--')}-{row.get('WINDOW_END_TIME','--')} "
            f"on {','.join(row['window_days']) or '?'} "
            f"({','.join(row['window_weeks']) or '?'})"
        ).strip()
    return rows


# ----------------------------- 2026 patch installs ---------------------------

# Jan 1 2026 00:00:00 UTC in unix-ms
EPOCH_2026_MS = 1735689600000


def installed_patches_2026(conn: pymssql.Connection, customer_id: int) -> list[dict]:
    """Per-machine patches installed during 2026 (INSTALLED_TIME >= 2026-01-01 UTC)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.RESOURCE_ID, r.NAME AS resource_name, r.DOMAIN_NETBIOS_NAME,
            ips.PATCH_ID, p.PATCHNAME, p.BULLETINID, p.SEVERITYID,
            ips.DEPLOY_STATUS, ips.DEPLOY_STATUS_ID,
            ips.INSTALLED_TIME, ips.ERROR_CODE, ips.REMARKS,
            pd.DESCRIPTION AS patch_description, pd.RELEASEDTIME
        FROM InstallPatchStatus ips
        JOIN Resource r       ON r.RESOURCE_ID = ips.RESOURCE_ID
        JOIN Patch p          ON p.PATCHID     = ips.PATCH_ID
        LEFT JOIN PatchDetails pd ON pd.PATCHID = ips.PATCH_ID
        WHERE r.CUSTOMER_ID = %d
          AND r.IS_INACTIVE = 'False'
          AND ips.INSTALLED_TIME >= %d
        ORDER BY r.NAME, ips.INSTALLED_TIME DESC
        """,
        (customer_id, EPOCH_2026_MS),
    )
    return cur.fetchall()


def installed_patches_2026_per_machine_monthly(conn: pymssql.Connection, customer_id: int) -> list[dict]:
    """Per-machine, per-month rollup for 2026 — useful for monthly client reports."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            r.RESOURCE_ID,
            r.NAME AS resource_name,
            DATEPART(YEAR,  DATEADD(SECOND, ips.INSTALLED_TIME/1000, '1970-01-01')) AS install_year,
            DATEPART(MONTH, DATEADD(SECOND, ips.INSTALLED_TIME/1000, '1970-01-01')) AS install_month,
            COUNT(*)                                          AS total_installed,
            SUM(CASE WHEN ips.DEPLOY_STATUS = 2 THEN 1 ELSE 0 END) AS succeeded,
            SUM(CASE WHEN ips.ERROR_CODE > 0    THEN 1 ELSE 0 END) AS errored,
            MIN(ips.INSTALLED_TIME) AS first_install_ms,
            MAX(ips.INSTALLED_TIME) AS last_install_ms
        FROM InstallPatchStatus ips
        JOIN Resource r ON r.RESOURCE_ID = ips.RESOURCE_ID
        WHERE r.CUSTOMER_ID = %d
          AND r.IS_INACTIVE = 'False'
          AND ips.INSTALLED_TIME >= %d
        GROUP BY r.RESOURCE_ID, r.NAME,
                 DATEPART(YEAR,  DATEADD(SECOND, ips.INSTALLED_TIME/1000, '1970-01-01')),
                 DATEPART(MONTH, DATEADD(SECOND, ips.INSTALLED_TIME/1000, '1970-01-01'))
        ORDER BY r.NAME, install_year, install_month
        """,
        (customer_id, EPOCH_2026_MS),
    )
    return cur.fetchall()


# ----------------------------- events ----------------------------------------

def customer_event_log(conn: pymssql.Connection, customer_id: int, since_ms: int | None = None, limit: int = 5000) -> list[dict]:
    """EC server events scoped to one MSP customer.

    These are EC's own audit/operational events (patch summary generated,
    config deployed, scan completed, etc.) — NOT Windows event log data
    from the endpoints. Windows event log shipping isn't enabled on this
    server.
    """
    cur = conn.cursor()
    if since_ms is not None:
        cur.execute(
            """
            SELECT TOP (%d)
                el.EVENT_LOG_ID, el.EVENT_ID, ec.EVENT_TYPE, ec.EVENT_MODULE,
                ec.EVENT_DESCRIPTION,
                el.LOGON_USER_NAME, el.LOGON_USER_EMAIL,
                el.EVENT_TIMESTAMP, el.EVENT_REMARKS_EN,
                el.EVENT_SOURCE_IP
            FROM CustomerEventLog cel
            JOIN EventLog  el ON el.EVENT_LOG_ID = cel.EVENT_LOG_ID
            JOIN EventCode ec ON ec.EVENT_ID     = el.EVENT_ID
            WHERE cel.CUSTOMER_ID = %d
              AND el.EVENT_TIMESTAMP >= %d
            ORDER BY el.EVENT_TIMESTAMP DESC
            """,
            (limit, customer_id, since_ms),
        )
    else:
        cur.execute(
            """
            SELECT TOP (%d)
                el.EVENT_LOG_ID, el.EVENT_ID, ec.EVENT_TYPE, ec.EVENT_MODULE,
                ec.EVENT_DESCRIPTION,
                el.LOGON_USER_NAME, el.LOGON_USER_EMAIL,
                el.EVENT_TIMESTAMP, el.EVENT_REMARKS_EN,
                el.EVENT_SOURCE_IP
            FROM CustomerEventLog cel
            JOIN EventLog  el ON el.EVENT_LOG_ID = cel.EVENT_LOG_ID
            JOIN EventCode ec ON ec.EVENT_ID     = el.EVENT_ID
            WHERE cel.CUSTOMER_ID = %d
            ORDER BY el.EVENT_TIMESTAMP DESC
            """,
            (limit, customer_id),
        )
    return cur.fetchall()


def resource_event_log(conn: pymssql.Connection, resource_id: int, limit: int = 1000) -> list[dict]:
    """EC server events scoped to one resource (machine)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT TOP (%d)
            el.EVENT_LOG_ID, el.EVENT_ID, ec.EVENT_TYPE, ec.EVENT_MODULE,
            ec.EVENT_DESCRIPTION,
            rel.RESOURCE_NAME, rel.DOMAIN_NETBIOS_NAME,
            el.EVENT_TIMESTAMP, el.EVENT_REMARKS_EN,
            el.LOGON_USER_NAME
        FROM ResourceEventLogRel rel
        JOIN EventLog  el ON el.EVENT_LOG_ID = rel.EVENT_LOG_ID
        JOIN EventCode ec ON ec.EVENT_ID     = el.EVENT_ID
        WHERE rel.RESOURCE_ID = %d
        ORDER BY el.EVENT_TIMESTAMP DESC
        """,
        (limit, resource_id),
    )
    return cur.fetchall()


# ----------------------------- audit history ---------------------------------

def hardware_audit_history(conn: pymssql.Connection, customer_id: int, limit: int = 10000) -> list[dict]:
    """Per-machine hardware change history (monitor added, drive replaced, etc.).

    The bridge is ``InvAuditHistory`` (parent: INV_AUDIT_HISTORY_ID +
    COMPUTER_ID + AUDIT_ID + OPERATION_TYPE), to which both ``InvHWAuditHistory``
    and ``InvSWAuditHistory`` join via INV_AUDIT_HISTORY_ID.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT TOP (%d)
            r.RESOURCE_ID, r.NAME AS resource_name,
            iah.OPERATION_TYPE, iah.AUDIT_ID,
            hwh.HARDWARE_TYPE, hwh.HARDWARE_NAME, hwh.HARDWARE_DESC,
            hwh.MANUFACTURER_NAME, hwh.HW_DETAILS, hwh.COMPONENT_ID
        FROM InvAuditHistory iah
        JOIN InvHWAuditHistory hwh ON hwh.INV_AUDIT_HISTORY_ID = iah.INV_AUDIT_HISTORY_ID
        JOIN Resource r            ON r.RESOURCE_ID            = iah.COMPUTER_ID
        WHERE r.CUSTOMER_ID = %d
          AND r.IS_INACTIVE = 'False'
        ORDER BY iah.INV_AUDIT_HISTORY_ID DESC
        """,
        (limit, customer_id),
    )
    return cur.fetchall()


def software_audit_history(conn: pymssql.Connection, customer_id: int, limit: int = 10000) -> list[dict]:
    """Per-machine software install/uninstall audit."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT TOP (%d)
            r.RESOURCE_ID, r.NAME AS resource_name,
            iah.OPERATION_TYPE, iah.AUDIT_ID,
            swh.SOFTWARE_ID, isw.SOFTWARE_NAME, isw.SOFTWARE_VERSION, isw.DISPLAY_NAME,
            swh.SW_USAGE_TYPE, swh.INSTALLED_DATE
        FROM InvAuditHistory iah
        JOIN InvSWAuditHistory swh ON swh.INV_AUDIT_HISTORY_ID = iah.INV_AUDIT_HISTORY_ID
        JOIN Resource r            ON r.RESOURCE_ID            = iah.COMPUTER_ID
        LEFT JOIN InvSW isw        ON isw.SOFTWARE_ID = swh.SOFTWARE_ID
        WHERE r.CUSTOMER_ID = %d
          AND r.IS_INACTIVE = 'False'
        ORDER BY iah.INV_AUDIT_HISTORY_ID DESC
        """,
        (limit, customer_id),
    )
    return cur.fetchall()


# ----------------------------- performance -----------------------------------

def performance_status(conn: pymssql.Connection) -> dict:
    """Report whether Endpoint Insight (EI) — the perf-monitoring component —
    is enabled and collecting data on this server.

    On this MSP build, EI is INSTALLED on 336 endpoints but NOT ENABLED
    (every row has STATUS=0, COMPONENT_STATUS=0,
    REMARKS='ei.agent.component_status.yet_to_enable'). As long as that
    holds, EICpuUsage / EIMemoryUsage / EIDiskSpace / EIBatteryHealth will
    all be empty.

    To get real perf data, EI must be enabled in the EC console under
    Endpoint Insight → Settings → Enable, AND the EI agent component must
    be deployed/started on each endpoint.
    """
    cur = conn.cursor()
    out: dict = {"endpoint_insight": {}, "perf_table_rowcounts": {}}

    cur.execute(
        """
        SELECT STATUS, COMPONENT_STATUS, COUNT(*) AS n
        FROM EIManagedResource
        GROUP BY STATUS, COMPONENT_STATUS
        ORDER BY n DESC
        """
    )
    out["endpoint_insight"]["managed_resource_status_distribution"] = cur.fetchall()

    for tbl in ("EICpuUsage", "EIMemoryUsage", "EIDiskSpace", "EIBatteryHealth"):
        try:
            cur.execute(f"SELECT COUNT(*) AS n FROM {tbl}")
            out["perf_table_rowcounts"][tbl] = cur.fetchall()[0]["n"]
        except Exception as exc:
            out["perf_table_rowcounts"][tbl] = f"ERR {exc}"

    enabled = any(
        row["STATUS"] != 0 or row["COMPONENT_STATUS"] != 0
        for row in out["endpoint_insight"]["managed_resource_status_distribution"]
    )
    out["endpoint_insight"]["any_enabled"] = enabled
    out["endpoint_insight"]["any_data_collected"] = any(
        isinstance(v, int) and v > 0 for v in out["perf_table_rowcounts"].values()
    )
    return out
