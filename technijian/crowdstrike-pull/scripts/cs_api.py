"""Technijian CrowdStrike Falcon API helper.

Reusable module for the daily CrowdStrike pull pipeline. Mirrors the shape of
huntress_api.py (per-skill helper next to its pull script) and umbrella_api.py
(OAuth2 client_credentials with token caching).

Auth scheme:
    OAuth2 client_credentials.
        POST <BASE_URL>/oauth2/token
            Content-Type: application/x-www-form-urlencoded
            body: client_id=<CID>&client_secret=<SECRET>
        -> { access_token, token_type, expires_in (~1799s) }
    All subsequent requests carry Authorization: Bearer <access_token>.
    Token TTL is short (~30 min). We cache and refresh a few seconds before
    expiry; on 401 we force-refresh and retry once.

Pagination:
    Most resources use a 2-step pattern:
        1. GET /<service>/queries/<resource>/v1?offset=&limit=&filter=&sort=
           -> { resources: ["<id>", ...], meta: { pagination: {offset, limit, total} } }
        2. GET /<service>/entities/<resource>/v2?ids=<id1>&ids=<id2>...
           OR POST /<service>/entities/<resource>/v2 { ids: [...] } for many ids.
    list_all_ids() handles offset paging on /queries/.
    fetch_entities() chunks ids into ?ids= batches up to MAX_IDS_PER_BATCH and
    merges responses.

Region:
    BASE_URL is region-specific. Technijian is on US-2:
        https://api.us-2.crowdstrike.com
    Override with env CROWDSTRIKE_BASE_URL or by editing the keyfile entry
    `**Base URL:**`.

Credentials are read in priority order:
    1) env vars CROWDSTRIKE_CLIENT_ID / CROWDSTRIKE_CLIENT_SECRET
    2) the keyfile at
       %USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/crowdstrike.md
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional
from urllib import request as urlrequest
from urllib.error import HTTPError
from urllib.parse import urlencode

DEFAULT_BASE_URL = "https://api.us-2.crowdstrike.com"
TOKEN_PATH = "/oauth2/token"
DEFAULT_TIMEOUT = 60
DEFAULT_QUERY_LIMIT = 500          # /queries/ pages
MAX_IDS_PER_BATCH = 500            # /entities/?ids=... batch size
RATE_LIMIT_BACKOFF_SECS = 60


def _base_url() -> str:
    return os.environ.get("CROWDSTRIKE_BASE_URL") or DEFAULT_BASE_URL


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _read_keyvault_creds() -> Optional[tuple[str, str, Optional[str]]]:
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    path = Path(home) / "OneDrive - Technijian, Inc" / "Documents" / "VSCODE" / "keys" / "crowdstrike.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    cid = re.search(r"\*\*Client ID:\*\*\s*(\S+)", text)
    sec = re.search(r"\*\*Client Secret:\*\*\s*(\S+)", text)
    base = re.search(r"\*\*Base URL:\*\*\s*(\S+)", text)
    if not cid or not sec:
        return None
    secret = sec.group(1)
    if secret.startswith("TODO"):
        return None
    base_url = base.group(1) if base else None
    return cid.group(1), secret, base_url


def get_credentials() -> tuple[str, str]:
    cid = os.environ.get("CROWDSTRIKE_CLIENT_ID")
    sec = os.environ.get("CROWDSTRIKE_CLIENT_SECRET")
    if cid and sec:
        return cid, sec
    creds = _read_keyvault_creds()
    if creds:
        cid, sec, base_url = creds
        if base_url and "CROWDSTRIKE_BASE_URL" not in os.environ:
            os.environ["CROWDSTRIKE_BASE_URL"] = base_url
        return cid, sec
    raise RuntimeError(
        "CrowdStrike credentials not found. Set CROWDSTRIKE_CLIENT_ID / "
        "CROWDSTRIKE_CLIENT_SECRET env vars OR fill in the **Client ID:** / "
        "**Client Secret:** lines at "
        "%USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/crowdstrike.md "
        "(replace the TODO_PASTE_SECRET_HERE placeholder)."
    )


# ---------------------------------------------------------------------------
# Bearer token caching
# ---------------------------------------------------------------------------

_TOKEN_CACHE: dict[str, Any] = {"token": None, "expires_at": 0}
_REFRESH_SLACK_SECS = 30


def _fetch_token() -> tuple[str, int]:
    cid, sec = get_credentials()
    body = urlencode({"client_id": cid, "client_secret": sec}).encode("utf-8")
    req = urlrequest.Request(
        _base_url() + TOKEN_PATH,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
        payload = json.loads(resp.read())
    token = payload.get("access_token")
    expires_in = int(payload.get("expires_in") or 1799)
    if not token:
        raise RuntimeError(f"CrowdStrike token endpoint returned no access_token: {payload}")
    return token, expires_in


def get_token(force: bool = False) -> str:
    now = int(time.time())
    if not force and _TOKEN_CACHE["token"] and now < int(_TOKEN_CACHE["expires_at"]) - _REFRESH_SLACK_SECS:
        return _TOKEN_CACHE["token"]
    token, ttl = _fetch_token()
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = now + ttl
    return token


def revoke_token() -> None:
    """POST /oauth2/revoke to invalidate the cached token explicitly."""
    if not _TOKEN_CACHE["token"]:
        return
    cid, sec = get_credentials()
    basic = (cid + ":" + sec)
    import base64 as _b64
    auth = "Basic " + _b64.b64encode(basic.encode("utf-8")).decode("ascii")
    body = urlencode({"token": _TOKEN_CACHE["token"]}).encode("utf-8")
    try:
        req = urlrequest.Request(
            _base_url() + "/oauth2/revoke",
            data=body,
            headers={
                "Authorization": auth,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT).read()
    except Exception:
        pass
    _TOKEN_CACHE["token"] = None
    _TOKEN_CACHE["expires_at"] = 0


# ---------------------------------------------------------------------------
# Low-level HTTP
# ---------------------------------------------------------------------------

def _http(method: str, path: str, *, params: Optional[dict] = None,
          body: Optional[dict] = None, timeout: int = DEFAULT_TIMEOUT,
          max_retries: int = 2) -> dict:
    url = _build_url(path, params)
    hdrs = {
        "Authorization": f"Bearer {get_token()}",
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"

    last_err: Optional[Exception] = None
    refreshed = False
    for attempt in range(max_retries + 1):
        req = urlrequest.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw)
        except HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="replace")[:600]
            except Exception:
                pass
            if e.code == 401 and not refreshed:
                hdrs["Authorization"] = f"Bearer {get_token(force=True)}"
                refreshed = True
                last_err = e
                continue
            if e.code == 429 and attempt < max_retries:
                time.sleep(RATE_LIMIT_BACKOFF_SECS)
                last_err = e
                continue
            if e.code in (502, 503, 504) and attempt < max_retries:
                time.sleep(5 * (attempt + 1))
                last_err = e
                continue
            raise RuntimeError(
                f"CrowdStrike {method} {path} -> HTTP {e.code}: {body_text}") from e
        except Exception as e:
            if attempt < max_retries:
                time.sleep(2 * (attempt + 1))
                last_err = e
                continue
            raise
    raise last_err  # type: ignore[misc]


def _build_url(path: str, params: Optional[dict] = None) -> str:
    if not path.startswith("/"):
        path = "/" + path
    url = _base_url() + path
    if params:
        cleaned: list[tuple[str, str]] = []
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, (list, tuple)):
                for item in v:
                    cleaned.append((k, str(item)))
            else:
                cleaned.append((k, str(v)))
        if cleaned:
            url = url + "?" + urlencode(cleaned)
    return url


# ---------------------------------------------------------------------------
# Generic two-step list helpers
# ---------------------------------------------------------------------------

def list_all_ids(query_path: str, *, params: Optional[dict] = None,
                 limit: int = DEFAULT_QUERY_LIMIT,
                 max_pages: int = 1000) -> list[str]:
    """Iterate offset-paginated /queries/.../v1 endpoints, returning all ids."""
    p = dict(params or {})
    p.setdefault("limit", limit)
    p.setdefault("offset", 0)
    out: list[str] = []
    pages = 0
    while True:
        payload = _http("GET", query_path, params=p)
        ids = payload.get("resources") or []
        out.extend(ids)
        meta = (payload.get("meta") or {}).get("pagination") or {}
        total = int(meta.get("total") or 0)
        offset = int(meta.get("offset") or 0)
        page_limit = int(meta.get("limit") or limit)
        pages += 1
        next_offset = offset + len(ids) if ids else offset + page_limit
        if not ids or next_offset >= total or pages >= max_pages:
            return out
        p["offset"] = next_offset


def fetch_entities(entity_path: str, ids: list[str], *,
                   batch_size: int = MAX_IDS_PER_BATCH,
                   method: str = "GET") -> list[dict]:
    """Fetch entity bodies in chunks of ?ids= (GET) or POST {ids:[...]}.
    Returns the merged `resources` list across batches.
    """
    out: list[dict] = []
    if not ids:
        return out
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        if method.upper() == "POST":
            payload = _http("POST", entity_path, body={"ids": batch})
        else:
            payload = _http("GET", entity_path, params={"ids": batch})
        rs = payload.get("resources") or []
        out.extend(rs)
    return out


def list_combined(combined_path: str, *, params: Optional[dict] = None,
                  limit: int = DEFAULT_QUERY_LIMIT,
                  max_pages: int = 1000,
                  use_after: bool = False) -> list[dict]:
    """Iterate offset- or after-cursor paginated /combined/.../v1 endpoints.
    Some services (Spotlight, Identity Protection) use `after` cursor instead
    of numeric offset; pass use_after=True for those.
    """
    p = dict(params or {})
    p.setdefault("limit", limit)
    if not use_after:
        p.setdefault("offset", 0)
    out: list[dict] = []
    pages = 0
    while True:
        payload = _http("GET", combined_path, params=p)
        rs = payload.get("resources") or []
        out.extend(rs)
        pages += 1
        meta = (payload.get("meta") or {}).get("pagination") or {}
        if use_after:
            after = meta.get("after")
            if not after or not rs or pages >= max_pages:
                return out
            p["after"] = after
        else:
            total = int(meta.get("total") or 0)
            offset = int(meta.get("offset") or 0)
            page_limit = int(meta.get("limit") or limit)
            next_offset = offset + len(rs) if rs else offset + page_limit
            if not rs or next_offset >= total or pages >= max_pages:
                return out
            p["offset"] = next_offset


# ---------------------------------------------------------------------------
# Domain helpers - Hosts (Sensor inventory)
#   Falcon Console -> Host management -> Hosts
# ---------------------------------------------------------------------------

def list_host_ids(filter_str: Optional[str] = None,
                  sort: Optional[str] = None,
                  member_cid: Optional[str] = None) -> list[str]:
    """GET /devices/queries/devices/v1 - non-hidden hosts."""
    params: dict[str, Any] = {}
    if filter_str:
        params["filter"] = filter_str
    if sort:
        params["sort"] = sort
    if member_cid:
        params["member_cid"] = member_cid
    return list_all_ids("/devices/queries/devices/v1", params=params)


def list_hidden_host_ids(filter_str: Optional[str] = None,
                         member_cid: Optional[str] = None) -> list[str]:
    """GET /devices/queries/devices-hidden/v1 - hidden / decommissioned hosts."""
    params: dict[str, Any] = {}
    if filter_str:
        params["filter"] = filter_str
    if member_cid:
        params["member_cid"] = member_cid
    return list_all_ids("/devices/queries/devices-hidden/v1", params=params)


def get_hosts(ids: list[str], member_cid: Optional[str] = None) -> list[dict]:
    """GET /devices/entities/devices/v2?ids=..."""
    if not ids:
        return []
    params: dict[str, Any] = {}
    if member_cid:
        params["member_cid"] = member_cid
    out: list[dict] = []
    for i in range(0, len(ids), MAX_IDS_PER_BATCH):
        batch = ids[i:i + MAX_IDS_PER_BATCH]
        p = dict(params)
        p["ids"] = batch
        payload = _http("GET", "/devices/entities/devices/v2", params=p)
        out.extend(payload.get("resources") or [])
    return out


def get_host_login_history(ids: list[str]) -> list[dict]:
    """POST /devices/combined/devices/login-history/v1 - last 10 logins per host."""
    if not ids:
        return []
    return fetch_entities("/devices/combined/devices/login-history/v1", ids,
                          method="POST")


def get_host_network_history(ids: list[str]) -> list[dict]:
    """POST /devices/combined/devices/network-address-history/v1."""
    if not ids:
        return []
    return fetch_entities("/devices/combined/devices/network-address-history/v1",
                          ids, method="POST")


# ---------------------------------------------------------------------------
# Host Groups
# ---------------------------------------------------------------------------

def list_host_group_ids() -> list[str]:
    return list_all_ids("/devices/queries/host-groups/v1")


def get_host_groups(ids: list[str]) -> list[dict]:
    return fetch_entities("/devices/entities/host-groups/v1", ids)


def list_host_group_members(group_id: str) -> list[str]:
    return list_all_ids("/devices/queries/host-group-members/v1",
                        params={"id": group_id})


# ---------------------------------------------------------------------------
# Detections (legacy) and Alerts (unified)
# ---------------------------------------------------------------------------

def list_detect_ids(filter_str: Optional[str] = None,
                    sort: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {}
    if filter_str:
        params["filter"] = filter_str
    if sort:
        params["sort"] = sort
    return list_all_ids("/detects/queries/detects/v1", params=params)


def get_detects(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    out: list[dict] = []
    for i in range(0, len(ids), MAX_IDS_PER_BATCH):
        batch = ids[i:i + MAX_IDS_PER_BATCH]
        payload = _http("POST", "/detects/entities/summaries/GET/v1",
                        body={"ids": batch})
        out.extend(payload.get("resources") or [])
    return out


def list_alert_ids(filter_str: Optional[str] = None,
                   sort: Optional[str] = None) -> list[str]:
    """Unified alerts API (preferred over /detects/)."""
    params: dict[str, Any] = {}
    if filter_str:
        params["filter"] = filter_str
    if sort:
        params["sort"] = sort
    return list_all_ids("/alerts/queries/alerts/v2", params=params)


def get_alerts(ids: list[str]) -> list[dict]:
    """POST /alerts/entities/alerts/v2 with body {composite_ids: [...]}.
    The unified Alerts v2 API uses composite_ids (not ids) - the legacy
    /detects/ API used `ids`."""
    if not ids:
        return []
    out: list[dict] = []
    for i in range(0, len(ids), MAX_IDS_PER_BATCH):
        batch = ids[i:i + MAX_IDS_PER_BATCH]
        payload = _http("POST", "/alerts/entities/alerts/v2",
                        body={"composite_ids": batch})
        out.extend(payload.get("resources") or [])
    return out


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

def list_incident_ids(filter_str: Optional[str] = None,
                      sort: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {}
    if filter_str:
        params["filter"] = filter_str
    if sort:
        params["sort"] = sort
    return list_all_ids("/incidents/queries/incidents/v1", params=params)


def get_incidents(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    out: list[dict] = []
    for i in range(0, len(ids), MAX_IDS_PER_BATCH):
        batch = ids[i:i + MAX_IDS_PER_BATCH]
        payload = _http("POST", "/incidents/entities/incidents/GET/v1",
                        body={"ids": batch})
        out.extend(payload.get("resources") or [])
    return out


def list_behavior_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {}
    if filter_str:
        params["filter"] = filter_str
    return list_all_ids("/incidents/queries/behaviors/v1", params=params)


def get_behaviors(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    out: list[dict] = []
    for i in range(0, len(ids), MAX_IDS_PER_BATCH):
        batch = ids[i:i + MAX_IDS_PER_BATCH]
        payload = _http("POST", "/incidents/entities/behaviors/GET/v1",
                        body={"ids": batch})
        out.extend(payload.get("resources") or [])
    return out


# ---------------------------------------------------------------------------
# Sensor Download / CCID
# ---------------------------------------------------------------------------

def get_ccid() -> dict:
    """GET /sensors/queries/installers/CCID/v1 - parent customer CID."""
    return _http("GET", "/sensors/queries/installers/CCID/v1")


def list_installer_shas() -> list[str]:
    return list_all_ids("/sensors/queries/installers/v1")


def get_installers(ids: list[str]) -> list[dict]:
    return fetch_entities("/sensors/entities/installers/v2", ids)


# ---------------------------------------------------------------------------
# Policies (Sensor Update / Prevention / Device Control / Firewall)
# ---------------------------------------------------------------------------

def list_sensor_update_policy_ids() -> list[str]:
    return list_all_ids("/policy/queries/sensor-update/v1")


def get_sensor_update_policies(ids: list[str]) -> list[dict]:
    return fetch_entities("/policy/entities/sensor-update/v2", ids)


def list_prevention_policy_ids() -> list[str]:
    return list_all_ids("/policy/queries/prevention/v1")


def get_prevention_policies(ids: list[str]) -> list[dict]:
    return fetch_entities("/policy/entities/prevention/v1", ids)


def list_device_control_policy_ids() -> list[str]:
    return list_all_ids("/policy/queries/device-control/v1")


def get_device_control_policies(ids: list[str]) -> list[dict]:
    return fetch_entities("/policy/entities/device-control/v1", ids)


def list_firewall_policy_ids() -> list[str]:
    return list_all_ids("/policy/queries/firewall/v1")


def get_firewall_policies(ids: list[str]) -> list[dict]:
    return fetch_entities("/policy/entities/firewall/v1", ids)


def list_response_policy_ids() -> list[str]:
    return list_all_ids("/policy/queries/response/v1")


def get_response_policies(ids: list[str]) -> list[dict]:
    return fetch_entities("/policy/entities/response/v1", ids)


# ---------------------------------------------------------------------------
# Spotlight (Vulnerabilities)
# ---------------------------------------------------------------------------

def list_vulnerabilities(filter_str: Optional[str] = None,
                         facet: Optional[list[str]] = None) -> list[dict]:
    params: dict[str, Any] = {}
    if filter_str:
        params["filter"] = filter_str
    if facet:
        params["facet"] = facet
    return list_combined("/spotlight/combined/vulnerabilities/v1",
                         params=params, use_after=True)


def list_remediations() -> list[str]:
    return list_all_ids("/spotlight/queries/remediations/v2")


def get_remediations(ids: list[str]) -> list[dict]:
    return fetch_entities("/spotlight/entities/remediations/v2", ids)


# ---------------------------------------------------------------------------
# Falcon Discover (asset/application/account inventory)
# ---------------------------------------------------------------------------

def list_discover_host_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/discover/queries/hosts/v1", params=params)


def get_discover_hosts(ids: list[str]) -> list[dict]:
    return fetch_entities("/discover/entities/hosts/v1", ids)


def list_discover_application_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/discover/queries/applications/v1", params=params)


def get_discover_applications(ids: list[str]) -> list[dict]:
    return fetch_entities("/discover/entities/applications/v1", ids)


def list_discover_account_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/discover/queries/accounts/v1", params=params)


def get_discover_accounts(ids: list[str]) -> list[dict]:
    return fetch_entities("/discover/entities/accounts/v1", ids)


def list_discover_login_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/discover/queries/logins/v1", params=params)


def get_discover_logins(ids: list[str]) -> list[dict]:
    return fetch_entities("/discover/entities/logins/v1", ids)


# ---------------------------------------------------------------------------
# Identity Protection
# ---------------------------------------------------------------------------

def list_identity_entity_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/identity-protection/queries/entities/v1",
                        params=params)


def get_identity_entities(ids: list[str]) -> list[dict]:
    return fetch_entities("/identity-protection/entities/entities/v1", ids)


def list_identity_policy_rules() -> list[str]:
    return list_all_ids("/identity-protection/queries/policy-rules/v1")


def get_identity_policy_rules(ids: list[str]) -> list[dict]:
    return fetch_entities("/identity-protection/entities/policy-rules/v1", ids)


# ---------------------------------------------------------------------------
# Indicators of Compromise (IOCs)
# ---------------------------------------------------------------------------

def list_indicator_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/iocs/queries/indicators/v1", params=params)


def get_indicators(ids: list[str]) -> list[dict]:
    return fetch_entities("/iocs/entities/indicators/v1", ids)


# ---------------------------------------------------------------------------
# Custom IOA Rules
# ---------------------------------------------------------------------------

def list_ioa_rule_group_ids() -> list[str]:
    return list_all_ids("/ioarules/queries/rule-groups-full/v1")


def get_ioa_rule_groups(ids: list[str]) -> list[dict]:
    return fetch_entities("/ioarules/entities/rule-groups/v1", ids)


def list_ioa_rule_ids() -> list[str]:
    return list_all_ids("/ioarules/queries/rules/v1")


def get_ioa_rules(ids: list[str]) -> list[dict]:
    return fetch_entities("/ioarules/entities/rules/v1", ids)


# ---------------------------------------------------------------------------
# Real Time Response (RTR) - read-only history
# ---------------------------------------------------------------------------

def list_rtr_session_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/real-time-response/queries/sessions/v1", params=params)


def get_rtr_sessions(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    out: list[dict] = []
    for i in range(0, len(ids), MAX_IDS_PER_BATCH):
        batch = ids[i:i + MAX_IDS_PER_BATCH]
        payload = _http("POST", "/real-time-response/entities/sessions/GET/v1",
                        body={"ids": batch})
        out.extend(payload.get("resources") or [])
    return out


# ---------------------------------------------------------------------------
# Falcon Sandbox (Falcon X / Falcon Intelligence Sandbox)
# ---------------------------------------------------------------------------

def list_sandbox_submission_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/falconx/queries/submissions/v1", params=params)


def get_sandbox_submissions(ids: list[str]) -> list[dict]:
    return fetch_entities("/falconx/entities/submissions/v1", ids)


def list_sandbox_report_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/falconx/queries/reports/v1", params=params)


def get_sandbox_reports(ids: list[str]) -> list[dict]:
    return fetch_entities("/falconx/entities/reports/v1", ids)


# ---------------------------------------------------------------------------
# Falcon Intel (Threat Intelligence)
# ---------------------------------------------------------------------------

def list_intel_actor_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/intel/queries/actors/v1", params=params)


def get_intel_actors(ids: list[str]) -> list[dict]:
    return fetch_entities("/intel/entities/actors/v1", ids)


def list_intel_indicator_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/intel/queries/indicators/v1", params=params)


def get_intel_indicators(ids: list[str]) -> list[dict]:
    return fetch_entities("/intel/entities/indicators/v1", ids)


def list_intel_report_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/intel/queries/reports/v1", params=params)


def get_intel_reports(ids: list[str]) -> list[dict]:
    return fetch_entities("/intel/entities/reports/v1", ids)


def list_intel_rule_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/intel/queries/rules/v1", params=params)


def list_intel_cve_ids(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/intel/queries/cves/v1", params=params)


def get_intel_cves(ids: list[str]) -> list[dict]:
    return fetch_entities("/intel/entities/cves/v1", ids)


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

def list_user_uuids() -> list[str]:
    return list_all_ids("/user-management/queries/users/v1")


def get_users(ids: list[str]) -> list[dict]:
    return fetch_entities("/user-management/entities/users/v1", ids)


def list_user_roles(user_uuid: str) -> list[dict]:
    payload = _http("GET", "/user-management/entities/users-roles/v1",
                    params={"ids": [user_uuid]})
    return payload.get("resources") or []


# ---------------------------------------------------------------------------
# MSSP / Falcon Flight Control (multi-tenant)
# ---------------------------------------------------------------------------

def list_mssp_children() -> list[str]:
    """GET /mssp/queries/children/v1 - child CIDs visible to this OAuth client.
    Empty if the tenant is not a Flight Control parent."""
    try:
        return list_all_ids("/mssp/queries/children/v1")
    except RuntimeError as e:
        # 403/404 means tenant is single-CID, not parent. Surface as empty.
        msg = str(e)
        if "HTTP 403" in msg or "HTTP 404" in msg:
            return []
        raise


def get_mssp_children(ids: list[str]) -> list[dict]:
    return fetch_entities("/mssp/entities/children/v1", ids)


def list_mssp_cid_groups() -> list[str]:
    return list_all_ids("/mssp/queries/cid-groups/v1")


def get_mssp_cid_groups(ids: list[str]) -> list[dict]:
    return fetch_entities("/mssp/entities/cid-groups/v1", ids)


# ---------------------------------------------------------------------------
# Reports / Scheduled reports
# ---------------------------------------------------------------------------

def list_scheduled_report_ids() -> list[str]:
    return list_all_ids("/reports/queries/scheduled-reports/v1")


def get_scheduled_reports(ids: list[str]) -> list[dict]:
    return fetch_entities("/reports/entities/scheduled-reports/v1", ids)


def list_report_executions(filter_str: Optional[str] = None) -> list[str]:
    params: dict[str, Any] = {"filter": filter_str} if filter_str else {}
    return list_all_ids("/reports/queries/scheduled-reports-executions/v1",
                        params=params)


# ---------------------------------------------------------------------------
# Cloud Connect AWS / CSPM / Container Security (placeholder helpers)
# ---------------------------------------------------------------------------

def list_aws_accounts() -> list[dict]:
    return list_combined("/cloud-connect-aws/combined/accounts/v1")


def list_settings_aws() -> dict:
    return _http("GET", "/cloud-connect-aws/combined/settings/v1")


# ---------------------------------------------------------------------------
# Miscellaneous
# ---------------------------------------------------------------------------

def get_self_user() -> dict:
    """Probe endpoint - returns 401 if token is bad."""
    return _http("GET", "/users/queries/user-uuids-by-cid/v1")


__all__ = [
    "DEFAULT_BASE_URL",
    "get_credentials",
    "get_token",
    "revoke_token",
    # hosts
    "list_host_ids", "list_hidden_host_ids", "get_hosts",
    "get_host_login_history", "get_host_network_history",
    # host groups
    "list_host_group_ids", "get_host_groups", "list_host_group_members",
    # detects + alerts
    "list_detect_ids", "get_detects",
    "list_alert_ids", "get_alerts",
    # incidents
    "list_incident_ids", "get_incidents",
    "list_behavior_ids", "get_behaviors",
    # sensor download
    "get_ccid", "list_installer_shas", "get_installers",
    # policies
    "list_sensor_update_policy_ids", "get_sensor_update_policies",
    "list_prevention_policy_ids", "get_prevention_policies",
    "list_device_control_policy_ids", "get_device_control_policies",
    "list_firewall_policy_ids", "get_firewall_policies",
    "list_response_policy_ids", "get_response_policies",
    # spotlight
    "list_vulnerabilities", "list_remediations", "get_remediations",
    # discover
    "list_discover_host_ids", "get_discover_hosts",
    "list_discover_application_ids", "get_discover_applications",
    "list_discover_account_ids", "get_discover_accounts",
    "list_discover_login_ids", "get_discover_logins",
    # identity protection
    "list_identity_entity_ids", "get_identity_entities",
    "list_identity_policy_rules", "get_identity_policy_rules",
    # IOCs
    "list_indicator_ids", "get_indicators",
    # custom IOA
    "list_ioa_rule_group_ids", "get_ioa_rule_groups",
    "list_ioa_rule_ids", "get_ioa_rules",
    # RTR
    "list_rtr_session_ids", "get_rtr_sessions",
    # sandbox
    "list_sandbox_submission_ids", "get_sandbox_submissions",
    "list_sandbox_report_ids", "get_sandbox_reports",
    # intel
    "list_intel_actor_ids", "get_intel_actors",
    "list_intel_indicator_ids", "get_intel_indicators",
    "list_intel_report_ids", "get_intel_reports",
    "list_intel_rule_ids", "list_intel_cve_ids", "get_intel_cves",
    # users
    "list_user_uuids", "get_users", "list_user_roles",
    # MSSP / Flight Control
    "list_mssp_children", "get_mssp_children",
    "list_mssp_cid_groups", "get_mssp_cid_groups",
    # reports
    "list_scheduled_report_ids", "get_scheduled_reports",
    "list_report_executions",
    # cloud connect
    "list_aws_accounts", "list_settings_aws",
    # generic
    "list_all_ids", "fetch_entities", "list_combined",
]
