"""
Technijian Client Portal API helpers.

Reusable module for:
  - Auth (bearer token via username/password)
  - Fetching active clients
  - Fetching contracts and deriving each client's currently-active signed contract
  - Fetching time entries by (ClientID, StartDate, EndDate) -> XML Root/TimeEntry/*
  - Fetching invoices by DirID -> XML Root/Invoice/*
  - Fetching ticket history by TicketID

Credentials are read from:
  1) env vars CP_USERNAME / CP_PASSWORD, else
  2) the key vault file at %USERPROFILE%\\OneDrive - Technijian, Inc\\Documents\\VSCODE\\keys\\client-portal.md

The API is https://api-clientportal.technijian.com .
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib import request as urlrequest
from urllib.error import HTTPError

BASE_URL = "https://api-clientportal.technijian.com"
TOKEN_PATH = "/api/auth/token"
DEFAULT_TIMEOUT = 300


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _read_keyvault_creds() -> Optional[tuple[str, str]]:
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    path = Path(home) / "OneDrive - Technijian, Inc" / "Documents" / "VSCODE" / "keys" / "client-portal.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    u = re.search(r"\*\*UserName:\*\*\s*(\S+)", text)
    p = re.search(r"\*\*Password:\*\*\s*(\S+)", text)
    if u and p:
        return u.group(1), p.group(1)
    return None


def get_credentials() -> tuple[str, str]:
    u = os.environ.get("CP_USERNAME")
    p = os.environ.get("CP_PASSWORD")
    if u and p:
        return u, p
    creds = _read_keyvault_creds()
    if creds:
        return creds
    raise RuntimeError(
        "Client Portal credentials not found. Set CP_USERNAME/CP_PASSWORD env vars "
        "or add them to the keys/client-portal.md file."
    )


# ---------------------------------------------------------------------------
# Low-level HTTP
# ---------------------------------------------------------------------------

def _http_json(method: str, url: str, *, body: Optional[dict] = None,
               headers: Optional[dict] = None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urlrequest.Request(url, data=data, headers=hdrs, method=method)
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if not raw:
        return {}
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@dataclass
class Session:
    token: str
    expires_at: float  # unix seconds

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - 30)


_SESSION: Optional[Session] = None


def login(force: bool = False) -> Session:
    global _SESSION
    if _SESSION and not force and not _SESSION.is_expired:
        return _SESSION
    user, pwd = get_credentials()
    body = {"userName": user, "password": pwd}
    result = _http_json("POST", BASE_URL + TOKEN_PATH, body=body)
    token = result.get("accessToken") or result["AccessToken"]
    expires_in = result.get("expiresIn") or result.get("ExpiresIn") or 3600
    _SESSION = Session(token=token, expires_at=time.time() + float(expires_in))
    return _SESSION


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {login().token}"}


# ---------------------------------------------------------------------------
# Generic SP execution
# ---------------------------------------------------------------------------

def execute_sp(module: str, schema: str, name: str,
               parameters: Optional[dict] = None,
               db_alias: str = "client-portal") -> dict:
    """Call POST /api/modules/{module}/stored-procedures/{db}/{schema}/{name}/execute."""
    url = (f"{BASE_URL}/api/modules/{module}/stored-procedures/"
           f"{db_alias}/{schema}/{name}/execute")
    return _http_json(
        "POST", url,
        body={"Parameters": parameters or {}},
        headers=_auth_headers(),
    )


def sp_rows(result: dict, index: int = 0) -> list[dict]:
    sets = result.get("resultSets") or result.get("ResultSets") or []
    if index >= len(sets):
        return []
    s = sets[index]
    return s.get("rows") or s.get("Rows") or []


def sp_xml_out(result: dict, param_name: str = "XML_OUT") -> str:
    op = result.get("outputParameters") or result.get("OutputParameters") or {}
    # Case-insensitive lookup
    for k, v in op.items():
        if k.lower() == param_name.lower():
            return v or ""
    return ""


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------

def get_active_clients() -> list[dict]:
    """GET /api/clients/active -> list of DirID/LocationCode/Location_Name/..."""
    url = f"{BASE_URL}/api/clients/active"
    r = _http_json("GET", url, headers=_auth_headers())
    return sp_rows(r)


def get_all_contracts() -> list[dict]:
    r = execute_sp("contract", "dbo", "GetAllContracts", {})
    return sp_rows(r)


def find_active_signed_contract(contracts: list[dict], dir_id: int) -> Optional[dict]:
    """Return the currently-active signed contract for a client (by DirID).
    Matches on Client_LocationsID and ContractStatusTxt in {Active, ACTIVE}.
    When multiple match, picks the most recent DateSigned.
    """
    cands = [c for c in contracts
             if c.get("Client_LocationsID") == dir_id
             and (c.get("ContractStatusTxt") or "").strip().lower() == "active"]
    if not cands:
        return None
    def sign_key(c):
        s = c.get("DateSigned") or ""
        return s
    cands.sort(key=sign_key, reverse=True)
    return cands[0]


def get_time_entries_xml(client_dir_id: int, start_date: str, end_date: str) -> str:
    """Return raw XML_OUT from stp_xml_TktEntry_List_Get.

    Dates are ISO strings YYYY-MM-DD.
    """
    r = execute_sp("timeentry", "Reporting", "stp_xml_TktEntry_List_Get",
                   {"ClientID": client_dir_id, "UserID": 0,
                    "StartDate": start_date, "EndDate": end_date})
    return sp_xml_out(r)


def get_invoices_xml(client_dir_id: int) -> str:
    """Return raw XML_OUT from stp_xml_Inv_Org_Loc_Inv_List_Get."""
    r = execute_sp("invoices", "dbo", "stp_xml_Inv_Org_Loc_Inv_List_Get",
                   {"DirID": client_dir_id})
    return sp_xml_out(r)


# ---------------------------------------------------------------------------
# XML parsing (Root/<ChildTag>/* flat-record shape used by the API)
# ---------------------------------------------------------------------------

def parse_flat_xml(xml: str, record_tag: str) -> list[dict]:
    """Parse <Root><record_tag><Field>...</Field>...</record_tag>*</Root> into list of dicts.

    Uses stdlib xml.etree.ElementTree. Ignores namespaces. Null-safe.
    """
    if not xml:
        return []
    # The API occasionally returns HTML-entity-escaped content inside text nodes; ElementTree handles it.
    import xml.etree.ElementTree as ET
    # Some responses may begin with a BOM or leading whitespace
    xml = xml.lstrip("﻿ ").strip()
    if not xml.startswith("<"):
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        # try wrapping in case it's a fragment
        try:
            root = ET.fromstring(f"<Root>{xml}</Root>")
        except ET.ParseError:
            return []
    rows: list[dict] = []
    for rec in root.findall(f".//{record_tag}"):
        row: dict[str, Any] = {}
        for child in rec:
            tag = child.tag
            text = (child.text or "").strip()
            row[tag] = text
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Convenience bulk fetch
# ---------------------------------------------------------------------------

def iso_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return s.split("T")[0][:10]


__all__ = [
    "BASE_URL",
    "Session",
    "login",
    "execute_sp",
    "sp_rows",
    "sp_xml_out",
    "get_active_clients",
    "get_all_contracts",
    "find_active_signed_contract",
    "get_time_entries_xml",
    "get_invoices_xml",
    "parse_flat_xml",
    "iso_date",
]
