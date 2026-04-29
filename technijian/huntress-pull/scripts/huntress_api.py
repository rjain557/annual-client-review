"""Technijian Huntress API helper.

Reusable module for the daily Huntress pull pipeline.

Auth scheme:
    HTTP Basic with the Account API Key ID + Secret. The header value is
    Authorization: Basic base64("<KEY_ID>:<SECRET>").

Pagination:
    All list endpoints take limit + page_token (cursor, not page number).
    The response embeds next_page_token when more pages exist.

Credentials are read in priority order:
  1) env vars HUNTRESS_API_KEY / HUNTRESS_API_SECRET
  2) the keyfile at %USERPROFILE%\\OneDrive - Technijian, Inc\\Documents\\VSCODE\\keys\\huntress.md
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional
from urllib import request as urlrequest
from urllib.error import HTTPError
from urllib.parse import urlencode

BASE_URL = "https://api.huntress.io/v1"
DEFAULT_TIMEOUT = 60
DEFAULT_PAGE_LIMIT = 250
RATE_LIMIT_BACKOFF_SECS = 60


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _read_keyvault_creds() -> Optional[tuple[str, str]]:
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    path = Path(home) / "OneDrive - Technijian, Inc" / "Documents" / "VSCODE" / "keys" / "huntress.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    k = re.search(r"\*\*API Key ID:\*\*\s*(\S+)", text)
    s = re.search(r"\*\*API Secret:\*\*\s*(\S+)", text)
    if not k or not s:
        return None
    secret = s.group(1)
    if secret.startswith("TODO"):
        return None
    return k.group(1), secret


def get_credentials() -> tuple[str, str]:
    k = os.environ.get("HUNTRESS_API_KEY")
    s = os.environ.get("HUNTRESS_API_SECRET")
    if k and s:
        return k, s
    creds = _read_keyvault_creds()
    if creds:
        return creds
    raise RuntimeError(
        "Huntress credentials not found. Set HUNTRESS_API_KEY / HUNTRESS_API_SECRET "
        "env vars OR fill in the **API Secret:** line at "
        "%USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/huntress.md "
        "(replace the TODO_PASTE_SECRET_HERE placeholder)."
    )


def _auth_header() -> dict[str, str]:
    k, s = get_credentials()
    token = base64.b64encode(f"{k}:{s}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


# ---------------------------------------------------------------------------
# Low-level HTTP
# ---------------------------------------------------------------------------

def _http_json(method: str, url: str, *, body: Optional[dict] = None,
               timeout: int = DEFAULT_TIMEOUT, max_retries: int = 2) -> dict:
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
            if e.code == 429 and attempt < max_retries:
                time.sleep(RATE_LIMIT_BACKOFF_SECS)
                last_err = e
                continue
            if e.code in (502, 503, 504) and attempt < max_retries:
                time.sleep(5 * (attempt + 1))
                last_err = e
                continue
            raise RuntimeError(
                f"Huntress {method} {url} -> HTTP {e.code}: {body_text}") from e
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
        # Drop None values; expand sequences as repeated query keys
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
# Public list helpers (cursor pagination)
# ---------------------------------------------------------------------------

# The Huntress envelope for list endpoints is:
#   { "<resource>": [...], "pagination": { "next_page_token": "..." } }
# The resource key matches the path's last segment most of the time.

def _extract_items(payload: dict, resource_keys: Iterable[str]) -> list[dict]:
    for k in resource_keys:
        if k in payload and isinstance(payload[k], list):
            return payload[k]
    # Fallback: first top-level list
    for v in payload.values():
        if isinstance(v, list):
            return v
    return []


def _next_page_token(payload: dict) -> Optional[str]:
    pg = payload.get("pagination") or {}
    return pg.get("next_page_token") or None


def list_paginated(path: str, params: Optional[dict] = None,
                   resource_keys: Optional[Iterable[str]] = None,
                   page_limit: int = DEFAULT_PAGE_LIMIT,
                   max_pages: int = 1000) -> Iterator[dict]:
    """Yield every record across all pages for a Huntress list endpoint."""
    p = dict(params or {})
    p.setdefault("limit", page_limit)
    rk = list(resource_keys or [path.strip("/").split("/")[-1]])
    pages = 0
    while True:
        payload = _http_json("GET", _build_url(path, p))
        for item in _extract_items(payload, rk):
            yield item
        token = _next_page_token(payload)
        pages += 1
        if not token or pages >= max_pages:
            return
        p["page_token"] = token


def get_one(path: str) -> dict:
    return _http_json("GET", _build_url(path))


# ---------------------------------------------------------------------------
# Domain helpers (read-only — match the v1 swagger)
# ---------------------------------------------------------------------------

def get_account() -> dict:
    return get_one("/account")


def list_organizations() -> list[dict]:
    return list(list_paginated("/organizations", resource_keys=["organizations"]))


def list_agents(organization_id: Optional[int] = None,
                platform: Optional[str] = None) -> list[dict]:
    params: dict[str, Any] = {}
    if organization_id is not None:
        params["organization_id"] = organization_id
    if platform:
        params["platform"] = platform
    return list(list_paginated("/agents", params=params, resource_keys=["agents"]))


def list_incident_reports(organization_id: Optional[int] = None,
                          status: Optional[str] = None,
                          severity: Optional[str] = None) -> list[dict]:
    params: dict[str, Any] = {}
    if organization_id is not None:
        params["organization_id"] = organization_id
    if status:
        params["status"] = status
    if severity:
        params["severity"] = severity
    return list(list_paginated("/incident_reports", params=params,
                                resource_keys=["incident_reports"]))


def list_signals(organization_id: Optional[int] = None,
                 investigated_at_min: Optional[str] = None,
                 investigated_at_max: Optional[str] = None) -> list[dict]:
    params: dict[str, Any] = {}
    if organization_id is not None:
        params["organization_id"] = organization_id
    if investigated_at_min:
        params["investigated_at_min"] = investigated_at_min
    if investigated_at_max:
        params["investigated_at_max"] = investigated_at_max
    return list(list_paginated("/signals", params=params, resource_keys=["signals"]))


def list_external_ports(organization_id: Optional[int] = None) -> list[dict]:
    params: dict[str, Any] = {}
    if organization_id is not None:
        params["organization_id"] = organization_id
    return list(list_paginated("/external_ports", params=params,
                                resource_keys=["external_ports"]))


def list_identities(organization_id: Optional[int] = None) -> list[dict]:
    params: dict[str, Any] = {}
    if organization_id is not None:
        params["organization_id"] = organization_id
    return list(list_paginated("/identities", params=params,
                                resource_keys=["identities"]))


def list_reports(organization_id: Optional[int] = None,
                 period_min: Optional[str] = None,
                 period_max: Optional[str] = None,
                 report_type: Optional[str] = None) -> list[dict]:
    params: dict[str, Any] = {}
    if organization_id is not None:
        params["organization_id"] = organization_id
    if period_min:
        params["period_min"] = period_min
    if period_max:
        params["period_max"] = period_max
    if report_type:
        params["type"] = report_type
    return list(list_paginated("/reports", params=params, resource_keys=["reports"]))


def list_reseller_subscriptions(product: Optional[str] = None,
                                status: Optional[str] = None) -> list[dict]:
    params: dict[str, Any] = {}
    if product:
        params["product"] = product
    if status:
        params["status"] = status
    return list(list_paginated("/reseller/subscriptions", params=params,
                                resource_keys=["subscriptions"]))


def list_reseller_invoices(status: Optional[str] = None) -> list[dict]:
    params: dict[str, Any] = {}
    if status:
        params["status"] = status
    return list(list_paginated("/reseller/invoices", params=params,
                                resource_keys=["invoices"]))


def list_reseller_invoice_org_line_items(invoice_id: int | str) -> list[dict]:
    return list(list_paginated(
        f"/reseller/invoices/{invoice_id}/organization_usage_line_items",
        resource_keys=["organization_usage_line_items", "line_items"]))


def list_reseller_invoice_account_line_items(invoice_id: int | str) -> list[dict]:
    return list(list_paginated(
        f"/reseller/invoices/{invoice_id}/account_usage_line_items",
        resource_keys=["account_usage_line_items", "line_items"]))


__all__ = [
    "BASE_URL",
    "get_credentials",
    "get_account",
    "list_organizations",
    "list_agents",
    "list_incident_reports",
    "list_signals",
    "list_external_ports",
    "list_identities",
    "list_reports",
    "list_reseller_subscriptions",
    "list_reseller_invoices",
    "list_reseller_invoice_org_line_items",
    "list_reseller_invoice_account_line_items",
    "list_paginated",
    "get_one",
]
