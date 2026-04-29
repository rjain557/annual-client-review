"""Technijian Cisco Umbrella API helper.

Reusable module for the daily Umbrella pull pipeline.

Auth scheme:
    OAuth2 client_credentials. POST to /auth/v2/token with HTTP Basic header
    base64("<KEY>:<SECRET>") and body "grant_type=client_credentials" returns
    a Bearer access token (~1h TTL). Token is cached in-process and refreshed
    a few seconds before expiry.

Pagination:
    The v2 API uses page-based pagination (limit + page=N) - this is different
    from Huntress (cursor pagination). Different families also use different
    response envelopes:
      /deployments/v2/*  -> bare JSON array
      /policies/v2/*     -> {status, meta:{page,limit,total}, data:[...]}
      /reports/v2/*      -> {meta, data:[...]}
    list_paginated() detects the shape and yields records uniformly.

Credentials are read in priority order:
  1) env vars UMBRELLA_API_KEY / UMBRELLA_API_SECRET
  2) the keyfile at %USERPROFILE%\\OneDrive - Technijian, Inc\\Documents\\VSCODE\\keys\\cisco-umbrella.md
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional
from urllib import request as urlrequest
from urllib.error import HTTPError
from urllib.parse import urlencode

BASE_URL = "https://api.umbrella.com"
TOKEN_PATH = "/auth/v2/token"
DEFAULT_TIMEOUT = 60
DEFAULT_PAGE_LIMIT = 100
RATE_LIMIT_BACKOFF_SECS = 60

# /reports/v2/activity hard limits enforced server-side
ACTIVITY_MAX_PAGE_LIMIT = 5000
ACTIVITY_MAX_OFFSET = 10000  # so standard pagination tops out at 10000 records
                              # per (from, to) window - walk smaller windows to
                              # see more events.


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _read_keyvault_creds() -> Optional[tuple[str, str]]:
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    path = Path(home) / "OneDrive - Technijian, Inc" / "Documents" / "VSCODE" / "keys" / "cisco-umbrella.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    k = re.search(r"\*\*API Key:\*\*\s*(\S+)", text)
    s = re.search(r"\*\*API Secret:\*\*\s*(\S+)", text)
    if not k or not s:
        return None
    secret = s.group(1)
    if secret.startswith("TODO"):
        return None
    return k.group(1), secret


def get_credentials() -> tuple[str, str]:
    k = os.environ.get("UMBRELLA_API_KEY")
    s = os.environ.get("UMBRELLA_API_SECRET")
    if k and s:
        return k, s
    creds = _read_keyvault_creds()
    if creds:
        return creds
    raise RuntimeError(
        "Cisco Umbrella credentials not found. Set UMBRELLA_API_KEY / UMBRELLA_API_SECRET "
        "env vars OR fill in the **API Key:** / **API Secret:** lines at "
        "%USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/cisco-umbrella.md."
    )


# ---------------------------------------------------------------------------
# Bearer token caching
# ---------------------------------------------------------------------------

_TOKEN_CACHE: dict[str, Any] = {"token": None, "expires_at": 0}
_REFRESH_SLACK_SECS = 30


def _fetch_token() -> tuple[str, int]:
    k, s = get_credentials()
    basic = base64.b64encode(f"{k}:{s}".encode("utf-8")).decode("ascii")
    body = "grant_type=client_credentials".encode("utf-8")
    req = urlrequest.Request(
        BASE_URL + TOKEN_PATH,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
        payload = json.loads(resp.read())
    token = payload.get("access_token")
    expires_in = int(payload.get("expires_in") or 3600)
    if not token:
        raise RuntimeError(f"Umbrella token endpoint returned no access_token: {payload}")
    return token, expires_in


def get_token() -> str:
    now = int(time.time())
    if _TOKEN_CACHE["token"] and now < int(_TOKEN_CACHE["expires_at"]) - _REFRESH_SLACK_SECS:
        return _TOKEN_CACHE["token"]
    token, ttl = _fetch_token()
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = now + ttl
    return token


def _auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_token()}"}


# ---------------------------------------------------------------------------
# Low-level HTTP
# ---------------------------------------------------------------------------

def _http_json(method: str, url: str, *, body: Optional[dict] = None,
               timeout: int = DEFAULT_TIMEOUT, max_retries: int = 2) -> Any:
    hdrs = {"Accept": "application/json", **_auth_header()}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"

    last_err: Optional[Exception] = None
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
                body_text = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            if e.code == 401 and attempt < max_retries:
                # Force token refresh on 401 - the cached one may have been revoked
                _TOKEN_CACHE["token"] = None
                _TOKEN_CACHE["expires_at"] = 0
                # rebuild auth header for the retry
                hdrs = {"Accept": "application/json", **_auth_header()}
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
                f"Umbrella {method} {url} -> HTTP {e.code}: {body_text}") from e
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
    url = BASE_URL + path
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
# Pagination - handles the three Umbrella envelope shapes
# ---------------------------------------------------------------------------

def _extract_records_and_total(payload: Any) -> tuple[list[dict], Optional[int]]:
    """Return (records, total_or_None) for a single response page."""
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, dict):
        # /policies/v2/* style: {status, meta:{page,limit,total}, data:[...]}
        # /reports/v2/*  style: {meta, data:[...]}
        data = payload.get("data")
        if isinstance(data, list):
            meta = payload.get("meta") or {}
            total = meta.get("total")
            return data, (int(total) if isinstance(total, int) or
                          (isinstance(total, str) and total.isdigit()) else None)
        # First top-level list, fallback
        for v in payload.values():
            if isinstance(v, list):
                return v, None
    return [], None


def list_paginated(path: str, params: Optional[dict] = None,
                   page_limit: int = DEFAULT_PAGE_LIMIT,
                   max_pages: int = 10000) -> Iterator[dict]:
    """Yield every record across all pages for an Umbrella list endpoint.

    Strategy: page=1, page=2, ... until the page returns 0 records OR we have
    yielded `total` records (when the envelope reports it).
    """
    p = dict(params or {})
    p.setdefault("limit", page_limit)
    page = 1
    yielded = 0
    pages = 0
    while pages < max_pages:
        p["page"] = page
        payload = _http_json("GET", _build_url(path, p))
        records, total = _extract_records_and_total(payload)
        if not records:
            return
        for r in records:
            yield r
        yielded += len(records)
        pages += 1
        if total is not None and yielded >= total:
            return
        if len(records) < int(p["limit"]):
            return
        page += 1


def get_one(path: str, params: Optional[dict] = None) -> Any:
    return _http_json("GET", _build_url(path, params))


# ---------------------------------------------------------------------------
# Domain helpers (read-only)
# ---------------------------------------------------------------------------

def list_organizations() -> list[dict]:
    """Managed organizations (returns [] for single-tenant accounts)."""
    return list(list_paginated("/admin/v2/organizations"))


def list_users() -> list[dict]:
    return list(list_paginated("/admin/v2/users"))


def list_sites() -> list[dict]:
    return list(list_paginated("/deployments/v2/sites"))


def list_networks() -> list[dict]:
    return list(list_paginated("/deployments/v2/networks"))


def list_internal_networks() -> list[dict]:
    return list(list_paginated("/deployments/v2/internalnetworks"))


def list_roaming_computers() -> list[dict]:
    return list(list_paginated("/deployments/v2/roamingcomputers"))


def list_network_devices() -> list[dict]:
    return list(list_paginated("/deployments/v2/networkdevices"))


def list_destination_lists() -> list[dict]:
    return list(list_paginated("/policies/v2/destinationlists"))


def _normalize_activity_ts(ts: str | int) -> str:
    """Activity reports expects Unix-millis OR relative time (`-24hours`, `now`).

    ISO timestamps are NOT accepted. This helper converts ISO -> millis and
    passes through anything else (e.g. `-24hours`, `now`, or a millis string).
    """
    if isinstance(ts, int):
        return str(ts)
    s = str(ts).strip()
    if not s:
        return s
    # Already millis?
    if s.isdigit():
        return s
    # Relative form
    if s == "now" or s.startswith("-") or s.startswith("+"):
        return s
    # Try parsing as ISO
    try:
        norm = s
        if norm.endswith("Z"):
            norm = norm[:-1] + "+00:00"
        dt = datetime.fromisoformat(norm)
        return str(int(dt.timestamp() * 1000))
    except Exception:
        return s


def list_activity(from_ts: str, to_ts: str,
                  verdict: Optional[str] = None,
                  identity_id: Optional[int | str] = None,
                  page_limit: int = 200,
                  max_records: int = 5000) -> list[dict]:
    """Pull DNS / proxy / firewall activity records.

    `from_ts` and `to_ts` accept Unix-millis, ISO timestamps (auto-converted
    to millis), or Umbrella's relative format (`-24hours`, `now`).

    Note: the activity endpoint is heavy. We cap at `max_records` per call to
    avoid pulling millions of DNS events for the parent org. Per-identity
    filtering keeps the result small.
    """
    # Activity endpoint enforces page_limit <= 5000 and offset <= 10000.
    # Cap callers' requests rather than ship a guaranteed-400 to the API.
    page_limit = min(int(page_limit), ACTIVITY_MAX_PAGE_LIMIT)
    params: dict[str, Any] = {
        "from": _normalize_activity_ts(from_ts),
        "to": _normalize_activity_ts(to_ts),
        "limit": page_limit,
        "offset": 0,
    }
    if verdict:
        params["verdict"] = verdict
    if identity_id is not None:
        params["identityId"] = identity_id

    out: list[dict] = []
    while True:
        payload = _http_json("GET", _build_url("/reports/v2/activity", params))
        records, _ = _extract_records_and_total(payload)
        if not records:
            break
        out.extend(records)
        if len(out) >= max_records:
            break
        if len(records) < page_limit:
            break
        next_offset = int(params["offset"]) + len(records)
        if next_offset > ACTIVITY_MAX_OFFSET:
            # Hit the offset cap - cannot retrieve more from this window.
            # Caller should walk a smaller (from, to) window if more events
            # are needed.
            break
        params["offset"] = next_offset
    return out[:max_records]


def get_activity_summary(from_ts: str, to_ts: str,
                         identity_ids: Optional[list[int | str]] = None) -> dict:
    """Aggregate activity counts (verdict breakdown) for the window.

    The /reports/v2/activity endpoint is the only one verified on this token,
    so we sample up to 5000 records and roll them up in-process. Good enough
    for daily snapshots; not appropriate for a true full-month aggregation.
    """
    rows = list_activity(from_ts, to_ts, page_limit=200, max_records=5000)
    summary: dict[str, Any] = {
        "from": from_ts, "to": to_ts,
        "sample_size": len(rows),
        "verdicts": {},
        "types": {},
        "identities": {},
        "blocked_threats": [],
    }
    if identity_ids is not None:
        wanted = {str(i) for i in identity_ids}
    else:
        wanted = None
    for r in rows:
        v = r.get("verdict") or "unknown"
        summary["verdicts"][v] = summary["verdicts"].get(v, 0) + 1
        t = r.get("type") or "unknown"
        summary["types"][t] = summary["types"].get(t, 0) + 1
        for ident in r.get("identities") or []:
            label = ident.get("label") or ""
            iid = str(ident.get("id") or "")
            if wanted is not None and iid not in wanted:
                continue
            summary["identities"][label] = summary["identities"].get(label, 0) + 1
        if v == "blocked":
            t_list = r.get("threats") or []
            if t_list:
                summary["blocked_threats"].append({
                    "domain": r.get("domain"),
                    "threats": t_list,
                    "timestamp": r.get("timestamp"),
                    "identities": [i.get("label") for i in (r.get("identities") or [])],
                })
    return summary


# ---------------------------------------------------------------------------
# Reports - aggregations (cheap, ~0.3s each; verified 2026-04-29)
# ---------------------------------------------------------------------------

def report_top_identities(from_ts: str, to_ts: str, limit: int = 1000) -> list[dict]:
    """Top identities by request count for the window. Returns
    [{requests, identity:{id,type,label}, counts:{...}}, ...] sorted desc."""
    params = {
        "from": _normalize_activity_ts(from_ts),
        "to": _normalize_activity_ts(to_ts),
        "limit": limit,
        "offset": 0,
    }
    payload = _http_json("GET", _build_url("/reports/v2/top-identities", params))
    records, _ = _extract_records_and_total(payload)
    return records


def report_top_threats(from_ts: str, to_ts: str, limit: int = 1000) -> list[dict]:
    """Top blocked threats for the window."""
    params = {
        "from": _normalize_activity_ts(from_ts),
        "to": _normalize_activity_ts(to_ts),
        "limit": limit,
    }
    payload = _http_json("GET", _build_url("/reports/v2/top-threats", params))
    records, _ = _extract_records_and_total(payload)
    return records


def report_requests_by_hour(from_ts: str, to_ts: str) -> list[dict]:
    """Org-wide hourly request counts for the window. ~24 entries / 24h."""
    params = {
        "from": _normalize_activity_ts(from_ts),
        "to": _normalize_activity_ts(to_ts),
    }
    payload = _http_json("GET", _build_url("/reports/v2/requests-by-hour", params))
    records, _ = _extract_records_and_total(payload)
    return records


def report_categories_by_hour(from_ts: str, to_ts: str) -> list[dict]:
    """Org-wide hourly category counts for the window."""
    params = {
        "from": _normalize_activity_ts(from_ts),
        "to": _normalize_activity_ts(to_ts),
    }
    payload = _http_json("GET", _build_url("/reports/v2/categories-by-hour", params))
    records, _ = _extract_records_and_total(payload)
    return records


def list_activity_blocked(from_ts: str, to_ts: str,
                          page_limit: int = 5000,
                          max_records: int = 10000) -> list[dict]:
    """Walk activity records with verdict=blocked only - small subset, cheap."""
    return list_activity(from_ts, to_ts, verdict="blocked",
                          page_limit=page_limit, max_records=max_records)


__all__ = [
    "BASE_URL",
    "ACTIVITY_MAX_PAGE_LIMIT",
    "ACTIVITY_MAX_OFFSET",
    "get_credentials",
    "get_token",
    "list_organizations",
    "list_users",
    "list_sites",
    "list_networks",
    "list_internal_networks",
    "list_roaming_computers",
    "list_network_devices",
    "list_destination_lists",
    "list_activity",
    "list_activity_blocked",
    "get_activity_summary",
    "report_top_identities",
    "report_top_threats",
    "report_requests_by_hour",
    "report_categories_by_hour",
    "list_paginated",
    "get_one",
]
