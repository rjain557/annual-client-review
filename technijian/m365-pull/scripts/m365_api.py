"""Technijian Microsoft Graph API helper — multi-tenant GDAP client.

Auth flow:
    POST https://login.microsoftonline.com/{client_tenant_id}/oauth2/v2.0/token
    grant_type=client_credentials
    client_id={app_id}          # Technijian's multi-tenant app
    client_secret={secret}
    scope=https://graph.microsoft.com/.default

    {client_tenant_id} is the CLIENT's tenant ID (not Technijian's).
    The app must be admin-consented in that tenant via the GDAP onboarding flow.

Credentials read in priority order:
  1) M365_APP_ID / M365_APP_SECRET env vars
  2) keyfile: %USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/m365-partner-graph.md
"""
from __future__ import annotations

import csv as csvmod
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib import request as urlrequest
from urllib.error import HTTPError
from urllib.parse import urlencode

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_BASE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
SCOPE = "https://graph.microsoft.com/.default"
DEFAULT_TIMEOUT = 60
SIGNIN_TIMEOUT = 300
RATE_LIMIT_BACKOFF = 60


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _read_keyvault_creds() -> Optional[tuple[str, str]]:
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    path = (Path(home) / "OneDrive - Technijian, Inc" / "Documents"
            / "VSCODE" / "keys" / "m365-partner-graph.md")
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    app_m = re.search(r"\*\*App \(Client\) ID:\*\*\s*(\S+)", text)
    sec_m = re.search(r"\*\*Client Secret:\*\*\s*(\S+)", text)
    if not app_m or not sec_m:
        return None
    secret = sec_m.group(1)
    if secret.startswith("<") or secret.startswith("TODO"):
        return None
    return app_m.group(1), secret


def get_credentials() -> tuple[str, str]:
    app_id = os.environ.get("M365_APP_ID")
    secret = os.environ.get("M365_APP_SECRET")
    if app_id and secret:
        return app_id, secret
    creds = _read_keyvault_creds()
    if creds:
        return creds
    raise RuntimeError(
        "M365 credentials not found. Set M365_APP_ID / M365_APP_SECRET env vars "
        "OR fill in keys/m365-partner-graph.md (replace the <paste...> placeholder)."
    )


# ---------------------------------------------------------------------------
# Token cache (in-process; one token per tenant)
# ---------------------------------------------------------------------------

_token_cache: dict[str, tuple[str, float]] = {}  # tenant_id -> (token, expires_at)


def _get_token(tenant_id: str) -> str:
    now = time.time()
    cached = _token_cache.get(tenant_id)
    if cached and now < cached[1] - 60:
        return cached[0]

    app_id, secret = get_credentials()
    url = TOKEN_BASE.format(tenant_id=tenant_id)
    body = urlencode({
        "grant_type": "client_credentials",
        "client_id": app_id,
        "client_secret": secret,
        "scope": SCOPE,
    }).encode("utf-8")
    req = urlrequest.Request(url, data=body, method="POST",
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except HTTPError as exc:
        raise RuntimeError(f"Token request failed for tenant {tenant_id}: {exc.code} {exc.read()[:200]}") from exc

    token = data["access_token"]
    expires_in = int(data.get("expires_in", 3600))
    _token_cache[tenant_id] = (token, now + expires_in)
    return token


# ---------------------------------------------------------------------------
# Low-level HTTP
# ---------------------------------------------------------------------------

def _headers(tenant_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_token(tenant_id)}",
        "Accept": "application/json",
        "ConsistencyLevel": "eventual",
    }


def _get(url: str, tenant_id: str, params: dict | None = None,
         timeout: int = DEFAULT_TIMEOUT) -> dict:
    if params:
        url = url + ("&" if "?" in url else "?") + urlencode(params)
    for attempt in range(3):
        req = urlrequest.Request(url, headers=_headers(tenant_id))
        try:
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except HTTPError as exc:
            if exc.code == 429:
                retry_after = int(exc.headers.get("Retry-After", RATE_LIMIT_BACKOFF))
                time.sleep(retry_after)
                continue
            if exc.code == 401 and attempt == 0:
                _token_cache.pop(tenant_id, None)
                continue
            body = exc.read()[:300].decode("utf-8", "replace")
            raise RuntimeError(f"Graph GET {url} => {exc.code}: {body}") from exc
    raise RuntimeError(f"Graph GET {url} failed after retries")


def _paginate(url: str, tenant_id: str, params: dict | None = None,
              timeout: int = DEFAULT_TIMEOUT) -> Iterator[dict]:
    """Yield every item across all @odata.nextLink pages."""
    resp = _get(url, tenant_id, params, timeout=timeout)
    yield from resp.get("value", [])
    while next_url := resp.get("@odata.nextLink"):
        resp = _get(next_url, tenant_id, timeout=timeout)
        yield from resp.get("value", [])


# ---------------------------------------------------------------------------
# Sign-in logs
# ---------------------------------------------------------------------------

def get_signin_logs(tenant_id: str, since_iso: str, until_iso: str,
                    timeout: int = SIGNIN_TIMEOUT) -> list[dict]:
    """All sign-in events in [since, until)."""
    url = f"{GRAPH_BASE}/auditLogs/signIns"
    filt = (f"createdDateTime ge {since_iso} and createdDateTime lt {until_iso}")
    return list(_paginate(url, tenant_id, {"$filter": filt, "$top": "999"},
                          timeout=timeout))


def get_signin_logs_chunked(tenant_id: str, since_iso: str, until_iso: str,
                            chunk_hours: int = 24,
                            timeout: int = SIGNIN_TIMEOUT,
                            on_chunk=None) -> list[dict]:
    """Sign-in events in [since, until), pulled in chunk_hours-sized windows.

    Avoids per-call timeout failures on very large tenants. Each chunk is an
    independent paginated query — if one chunk fails, the others still succeed.

    on_chunk(chunk_start_iso, chunk_end_iso, count, error) is called after each
    chunk attempt for progress reporting.
    """
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    start = _dt.fromisoformat(since_iso.replace("Z", "+00:00"))
    end = _dt.fromisoformat(until_iso.replace("Z", "+00:00"))
    chunk = _td(hours=chunk_hours)
    all_signins: list[dict] = []
    cursor = start
    while cursor < end:
        nxt = min(cursor + chunk, end)
        c_start = cursor.astimezone(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        c_end = nxt.astimezone(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            chunk_signins = get_signin_logs(tenant_id, c_start, c_end, timeout=timeout)
            all_signins.extend(chunk_signins)
            if on_chunk:
                on_chunk(c_start, c_end, len(chunk_signins), None)
        except Exception as exc:
            if on_chunk:
                on_chunk(c_start, c_end, 0, str(exc))
            # Surface the first error reason but keep going on remaining chunks
            # so a transient failure doesn't lose 29 days of data
        cursor = nxt
    return all_signins


def get_risky_signins(tenant_id: str, since_iso: str) -> list[dict]:
    """Risk detections (requires Entra P2)."""
    url = f"{GRAPH_BASE}/identityProtection/riskDetections"
    filt = f"detectedDateTime ge {since_iso} and riskLevel ne 'none'"
    try:
        return list(_paginate(url, tenant_id, {"$filter": filt, "$top": "500"}))
    except RuntimeError as exc:
        if "403" in str(exc) or "401" in str(exc):
            return []  # P2 not licensed
        raise


def get_risky_users(tenant_id: str) -> list[dict]:
    """Currently flagged risky users (requires Entra P2)."""
    url = f"{GRAPH_BASE}/identityProtection/riskyUsers"
    try:
        return list(_paginate(url, tenant_id, {
            "$filter": "riskLevel ne 'none' and riskState ne 'dismissed'",
            "$select": "id,userPrincipalName,riskLevel,riskState,riskLastUpdatedDateTime"
        }))
    except RuntimeError as exc:
        if "403" in str(exc) or "401" in str(exc):
            return []
        raise


# ---------------------------------------------------------------------------
# Compliance / posture
# ---------------------------------------------------------------------------

def get_secure_score(tenant_id: str) -> dict:
    """Latest Secure Score snapshot."""
    url = f"{GRAPH_BASE}/security/secureScores"
    resp = _get(url, tenant_id, {"$top": "1"})
    items = resp.get("value", [])
    return items[0] if items else {}


def get_secure_score_controls(tenant_id: str) -> list[dict]:
    url = f"{GRAPH_BASE}/security/secureScoreControlProfiles"
    return list(_paginate(url, tenant_id))


def get_conditional_access_policies(tenant_id: str) -> list[dict]:
    url = f"{GRAPH_BASE}/identity/conditionalAccess/policies"
    select = "id,displayName,state,conditions,grantControls,sessionControls,createdDateTime,modifiedDateTime"
    return list(_paginate(url, tenant_id, {"$select": select}))


def get_security_defaults(tenant_id: str) -> dict:
    url = f"{GRAPH_BASE}/policies/identitySecurityDefaultsEnforcementPolicy"
    try:
        return _get(url, tenant_id)
    except RuntimeError:
        return {}


def get_mfa_registration(tenant_id: str) -> list[dict]:
    """Per-user MFA registration details (requires UserAuthenticationMethod.Read.All)."""
    url = f"{GRAPH_BASE}/reports/authenticationMethods/userRegistrationDetails"
    select = ("userPrincipalName,isMfaRegistered,isMfaCapable,isPasswordlessCapable,"
              "isSsprRegistered,methodsRegistered")
    try:
        return list(_paginate(url, tenant_id, {"$select": select, "$top": "999"}))
    except RuntimeError as exc:
        if "403" in str(exc):
            return []
        raise


def get_admin_roles(tenant_id: str) -> list[dict]:
    """Global Admin and other privileged role members."""
    PRIVILEGED_ROLES = {
        "Global Administrator",
        "Privileged Role Administrator",
        "Security Administrator",
        "Exchange Administrator",
        "SharePoint Administrator",
        "User Administrator",
    }
    url = f"{GRAPH_BASE}/directoryRoles"
    roles = list(_paginate(url, tenant_id,
                           {"$select": "id,displayName,roleTemplateId"}))
    result = []
    for role in roles:
        if role.get("displayName") not in PRIVILEGED_ROLES:
            continue
        members_url = f"{GRAPH_BASE}/directoryRoles/{role['id']}/members"
        members = list(_paginate(members_url, tenant_id,
                                 {"$select": "id,displayName,userPrincipalName,userType"}))
        result.append({**role, "members": members, "memberCount": len(members)})
    return result


def get_guest_users(tenant_id: str) -> list[dict]:
    url = f"{GRAPH_BASE}/users"
    return list(_paginate(url, tenant_id, {
        "$filter": "userType eq 'Guest'",
        "$select": "id,displayName,mail,userPrincipalName,createdDateTime,externalUserState",
        "$top": "999"
    }))


def get_named_locations(tenant_id: str) -> list[dict]:
    url = f"{GRAPH_BASE}/identity/conditionalAccess/namedLocations"
    return list(_paginate(url, tenant_id))


def get_subscribed_skus(tenant_id: str) -> list[dict]:
    """License SKUs assigned to the tenant."""
    url = f"{GRAPH_BASE}/subscribedSkus"
    return list(_paginate(url, tenant_id,
                          {"$select": "skuId,skuPartNumber,capabilityStatus,consumedUnits,prepaidUnits"}))


# ---------------------------------------------------------------------------
# Storage / usage reports  (requires Reports.Read.All)
# Reports API tries JSON first; falls back to CSV when the tenant has
# report anonymization enabled (displayConcealedNames = true).
# CSV rows use verbose English column names; JSON rows use camelCase.
# ---------------------------------------------------------------------------

def _r(row: dict, json_key: str, csv_key: str | None = None):
    """Return row[json_key] or row[csv_key] — handles JSON and CSV payloads."""
    v = row.get(json_key)
    if v is not None:
        return v
    return row.get(csv_key) if csv_key else None


def _int_val(v) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return 0


def _bool_val(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")

def _get_report(url: str, tenant_id: str) -> list[dict]:
    """Fetch a usage report. Tries JSON first; falls back to CSV if the tenant
    doesn't support JSON format (e.g. when report anonymization is enabled).

    $format must NOT go through urlencode — $ would become %24 and break the API.
    For the CSV fallback, urllib follows the 302 redirect to the CDN automatically.
    """
    sep = "&" if "?" in url else "?"
    json_url = f"{url}{sep}$format=application/json"
    try:
        resp = _get(json_url, tenant_id)
        return resp.get("value", [])
    except RuntimeError as exc:
        if "JSON format is not supported" not in str(exc):
            raise
    # CSV fallback — fetch without $format
    req = urlrequest.Request(url, headers=_headers(tenant_id))
    try:
        with urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            raw = resp.read()
    except HTTPError as exc:
        body = exc.read()[:300].decode("utf-8", "replace")
        raise RuntimeError(f"Report CSV GET {url} => {exc.code}: {body}") from exc
    text = raw.decode("utf-8-sig")   # strip BOM if present
    reader = csvmod.DictReader(io.StringIO(text))
    return list(reader)


def get_mailbox_usage(tenant_id: str, period: str = "D7") -> list[dict]:
    """Per-mailbox storage usage + quota. period = D7|D30|D90|D180."""
    url = f"{GRAPH_BASE}/reports/getMailboxUsageDetail(period='{period}')"
    rows = _get_report(url, tenant_id)
    out = []
    for r in rows:
        if _bool_val(_r(r, "isDeleted", "Is Deleted")):
            continue
        used = _int_val(_r(r, "storageUsedInBytes", "Storage Used (Byte)"))
        quota = (_int_val(_r(r, "prohibitSendReceiveQuotaInBytes", "Prohibit Send/Receive Quota (Byte)"))
                 or _int_val(_r(r, "prohibitSendQuotaInBytes", "Prohibit Send Quota (Byte)")))
        pct = round(used / quota * 100, 1) if quota else None
        out.append({
            "userPrincipalName": _r(r, "userPrincipalName", "User Principal Name") or "",
            "displayName": _r(r, "displayName", "Display Name") or "",
            "storageUsedInBytes": used,
            "storageUsedGB": round(used / 1_073_741_824, 2),
            "quotaInBytes": quota,
            "quotaGB": round(quota / 1_073_741_824, 2) if quota else None,
            "pctUsed": pct,
            "hasArchive": _bool_val(_r(r, "hasArchive", "Has Archive")),
            "archiveUsedInBytes": _int_val(_r(r, "archiveStorageUsedInBytes", "Archive Storage Used (Byte)")),
            "reportRefreshDate": _r(r, "reportRefreshDate", "Report Refresh Date") or "",
        })
    return sorted(out, key=lambda x: -(x["pctUsed"] or 0))


def get_onedrive_usage(tenant_id: str, period: str = "D7") -> list[dict]:
    """Per-user OneDrive storage usage + quota."""
    url = f"{GRAPH_BASE}/reports/getOneDriveUsageAccountDetail(period='{period}')"
    rows = _get_report(url, tenant_id)
    out = []
    for r in rows:
        if _bool_val(_r(r, "isDeleted", "Is Deleted")):
            continue
        used = _int_val(_r(r, "storageUsedInBytes", "Storage Used (Byte)"))
        quota = _int_val(_r(r, "storageAllocatedInBytes", "Storage Allocated (Byte)"))
        pct = round(used / quota * 100, 1) if quota else None
        upn = (_r(r, "ownerPrincipalName", "Owner Principal Name")
               or _r(r, "userPrincipalName", "User Principal Name") or "")
        name = (_r(r, "ownerDisplayName", "Owner Display Name")
                or _r(r, "displayName", "Display Name") or "")
        out.append({
            "userPrincipalName": upn,
            "displayName": name,
            "siteUrl": _r(r, "siteUrl", "Site URL") or "",
            "storageUsedInBytes": used,
            "storageUsedGB": round(used / 1_073_741_824, 2),
            "quotaInBytes": quota,
            "quotaGB": round(quota / 1_073_741_824, 2) if quota else None,
            "pctUsed": pct,
            "reportRefreshDate": _r(r, "reportRefreshDate", "Report Refresh Date") or "",
        })
    return sorted(out, key=lambda x: -(x["pctUsed"] or 0))


def get_sharepoint_usage(tenant_id: str, period: str = "D7") -> list[dict]:
    """Per-site SharePoint + Teams storage usage. Teams channel files live in
    SharePoint team sites — identified by siteType containing 'Team Site'."""
    url = f"{GRAPH_BASE}/reports/getSharePointSiteUsageDetail(period='{period}')"
    rows = _get_report(url, tenant_id)
    out = []
    for r in rows:
        if _bool_val(_r(r, "isDeleted", "Is Deleted")):
            continue
        used = _int_val(_r(r, "storageUsedInBytes", "Storage Used (Byte)"))
        quota = _int_val(_r(r, "storageAllocatedInBytes", "Storage Allocated (Byte)"))
        pct = round(used / quota * 100, 1) if quota else None
        site_url = _r(r, "siteUrl", "Site URL") or ""
        site_type = _r(r, "siteType", "Root Web Template") or ""
        is_teams = "/teams/" in site_url.lower() or "team" in site_type.lower()
        out.append({
            "siteUrl": site_url,
            "ownerDisplayName": _r(r, "ownerDisplayName", "Owner Display Name") or "",
            "siteType": site_type,
            "isTeamsSite": is_teams,
            "storageUsedInBytes": used,
            "storageUsedGB": round(used / 1_073_741_824, 2),
            "quotaInBytes": quota,
            "quotaGB": round(quota / 1_073_741_824, 2) if quota else None,
            "pctUsed": pct,
            "fileCount": _int_val(_r(r, "fileCount", "File Count")),
            "activeFileCount": _int_val(_r(r, "activeFileCount", "Active File Count")),
            "reportRefreshDate": _r(r, "reportRefreshDate", "Report Refresh Date") or "",
        })
    return sorted(out, key=lambda x: -(x["storageUsedInBytes"]))


def get_storage_org_totals(tenant_id: str, period: str = "D7") -> dict:
    """Org-level storage totals for Mailbox, OneDrive, SharePoint."""
    totals: dict[str, Any] = {}

    def _fetch_total(name: str, endpoint: str) -> None:
        try:
            url = f"{GRAPH_BASE}/reports/{endpoint}(period='{period}')"
            rows = _get_report(url, tenant_id)
            if rows:
                latest = max(rows, key=lambda r: r.get("reportDate", ""))
                totals[name] = {
                    "storageUsedInBytes": latest.get("storageUsedInBytes", 0),
                    "storageUsedGB": round((latest.get("storageUsedInBytes") or 0) / 1_073_741_824, 2),
                    "reportDate": latest.get("reportDate", ""),
                }
        except Exception:
            totals[name] = {}

    _fetch_total("mailbox",    "getMailboxUsageStorage")
    _fetch_total("onedrive",   "getOneDriveUsageStorage")
    _fetch_total("sharepoint", "getSharePointSiteUsageStorage")
    return totals


# ---------------------------------------------------------------------------
# Security alerts + incidents  (requires SecurityAlert.Read.All,
#                               SecurityIncident.Read.All)
# ---------------------------------------------------------------------------

def get_security_alerts(tenant_id: str, since_iso: str, severity: str | None = None) -> list[dict]:
    """Microsoft Defender / Sentinel alerts via unified security API."""
    url = f"{GRAPH_BASE}/security/alerts_v2"
    filt = f"createdDateTime ge {since_iso}"
    if severity:
        filt += f" and severity eq '{severity}'"
    try:
        return list(_paginate(url, tenant_id, {
            "$filter": filt,
            "$select": "id,title,severity,status,category,createdDateTime,resolvedDateTime,"
                       "classification,determination,serviceSource,detectionSource,"
                       "actorDisplayName,threatDisplayName,mitreTechniques,"
                       "evidence,recommendedActions",
            "$top": "999",
        }))
    except RuntimeError as exc:
        if "403" in str(exc):
            return []
        raise


def get_security_incidents(tenant_id: str, since_iso: str) -> list[dict]:
    """Correlated incidents (multi-alert) from Microsoft Defender."""
    url = f"{GRAPH_BASE}/security/incidents"
    filt = f"createdDateTime ge {since_iso}"
    try:
        return list(_paginate(url, tenant_id, {
            "$filter": filt,
            "$select": "id,displayName,severity,status,classification,determination,"
                       "createdDateTime,lastUpdateDateTime,alerts",
            "$top": "200",
        }))
    except RuntimeError as exc:
        if "403" in str(exc):
            return []
        raise


def get_mail_forwarding_rules(tenant_id: str) -> list[dict]:
    """Mailboxes with forwarding rules set to external addresses (BEC signal).
    Requires MailboxSettings.Read."""
    url = f"{GRAPH_BASE}/users"
    users = list(_paginate(url, tenant_id, {
        "$select": "id,userPrincipalName,displayName,mail",
        "$filter": "userType eq 'Member'",
        "$top": "999"
    }))
    flagged = []
    for user in users:
        try:
            settings_url = f"{GRAPH_BASE}/users/{user['id']}/mailboxSettings"
            settings = _get(settings_url, tenant_id)
            fwd = settings.get("automaticRepliesSetting") or {}
            # Check forwardingSmtpAddress and forwardingAddress
            fwd_addr = settings.get("forwardingSmtpAddress") or settings.get("forwardingAddress") or ""
            if fwd_addr and not fwd_addr.endswith(
                    tuple(["@" + d for d in _get_tenant_domains(tenant_id)])):
                flagged.append({
                    "userPrincipalName": user.get("userPrincipalName", ""),
                    "displayName": user.get("displayName", ""),
                    "forwardingAddress": fwd_addr,
                })
        except Exception:
            continue
    return flagged


def _get_tenant_domains(tenant_id: str) -> list[str]:
    """Return verified domain names for this tenant (for external-fwd detection)."""
    try:
        url = f"{GRAPH_BASE}/domains"
        rows = _get(url, tenant_id, {"$select": "id,isVerified"})
        return [d["id"] for d in rows.get("value", []) if d.get("isVerified")]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# GDAP relationship discovery  (requires DelegatedAdminRelationship.Read.All)
# Called on the PARTNER tenant (Technijian), not the client tenant.
# ---------------------------------------------------------------------------

def get_gdap_relationships(partner_tenant_id: str,
                           status_filter: str | None = "active") -> list[dict]:
    """List all GDAP delegated admin relationships visible to the partner.

    partner_tenant_id: Technijian's own tenant ID (cab8077a-...)
    status_filter: 'active' | 'approved' | None (return all statuses)

    Returns a list of dicts with keys:
        id, displayName, status, customerTenantId, customerDisplayName,
        createdDateTime, activatedDateTime, endDateTime
    """
    url = f"{GRAPH_BASE}/tenantRelationships/delegatedAdminRelationships"
    params: dict = {
        "$select": "id,displayName,status,customer,createdDateTime,"
                   "activatedDateTime,endDateTime,duration",
        "$top": "300",
    }
    if status_filter:
        params["$filter"] = f"status eq '{status_filter}'"

    raw = list(_paginate(url, partner_tenant_id, params))
    result = []
    for r in raw:
        customer = r.get("customer") or {}
        result.append({
            "id": r.get("id", ""),
            "displayName": r.get("displayName", ""),
            "status": r.get("status", ""),
            "customerTenantId": customer.get("tenantId", ""),
            "customerDisplayName": customer.get("displayName", ""),
            "createdDateTime": r.get("createdDateTime", ""),
            "activatedDateTime": r.get("activatedDateTime", ""),
            "endDateTime": r.get("endDateTime", ""),
        })
    return result


def get_user_licenses(tenant_id: str) -> list[dict]:
    """Per-user license assignments (requires LicenseAssignment.Read.All + User.Read.All)."""
    url = f"{GRAPH_BASE}/users"
    users = list(_paginate(url, tenant_id, {
        "$select": "id,userPrincipalName,displayName,userType,accountEnabled,"
                   "assignedLicenses,assignedPlans",
        "$filter": "userType eq 'Member' and accountEnabled eq true",
        "$top": "999",
    }))
    out = []
    for u in users:
        assigned = u.get("assignedLicenses") or []
        plans = u.get("assignedPlans") or []
        active_services = sorted({
            p.get("service", "")
            for p in plans
            if p.get("capabilityStatus") == "Enabled"
        })
        out.append({
            "userPrincipalName": u.get("userPrincipalName", ""),
            "displayName": u.get("displayName", ""),
            "licenseCount": len(assigned),
            "skuIds": [a.get("skuId", "") for a in assigned],
            "activeServices": active_services,
        })
    return out
