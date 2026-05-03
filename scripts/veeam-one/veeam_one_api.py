"""
Veeam ONE 13 Reporting Service REST API client.

Reads credentials from env (preferred for headless) or from the OneDrive
keyfile at keys/veeam-one.md. Handles token acquisition, refresh, paged
GETs, and tolerant error handling.

Usage:
    import veeam_one_api as v
    me = v.about()                              # health check (no auth needed)
    repos = v.list_paged("vbr/repositories")    # auto-paged
    one = v.get("vbr/backupServers")            # single page

Env vars (override keyfile):
    VONE_HOST       e.g. 10.7.9.135 (no scheme)
    VONE_PORT       default 1239
    VONE_USERNAME   e.g. TE-DC-VONE-01\\Administrator   (DOMAIN\\User REQUIRED)
    VONE_PASSWORD
    VONE_API_VER    default 2.2
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib3
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urlencode

import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

KEYFILE = Path(os.path.expandvars(
    r"%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\veeam-one.md"
))

_state: dict[str, Any] = {
    "host": None, "port": None, "user": None, "pwd": None, "api_ver": None,
    "access_token": None, "refresh_token": None, "expires_at": 0.0,
    "session": None,
}


def _read_keyfile() -> dict[str, str]:
    if not KEYFILE.exists():
        return {}
    txt = KEYFILE.read_text(encoding="utf-8", errors="replace")
    out: dict[str, str] = {}
    m = re.search(r"\*\*Host:\*\*\s*([0-9.]+)", txt)
    if m: out["host"] = m.group(1)
    m = re.search(r":(\d{3,5})\b", txt)
    if m: out["port"] = m.group(1)
    m = re.search(r"\*\*Username:\*\*\s*`?([^\s`]+(?:\\\\?[^\s`]+)?)`?", txt)
    if m:
        u = m.group(1)
        # markdown escapes \\ → keep one backslash
        out["user"] = u.replace("\\\\", "\\")
    m = re.search(r"\*\*Password:\*\*\s*([^\s\n]+)", txt)
    if m: out["pwd"] = m.group(1)
    m = re.search(r"x-api-version[:`\s]+([0-9.]+)", txt)
    if m: out["api_ver"] = m.group(1)
    return out


def _config() -> None:
    if _state["host"]:
        return
    kf = _read_keyfile()
    _state["host"] = os.environ.get("VONE_HOST", kf.get("host", "10.7.9.135"))
    _state["port"] = os.environ.get("VONE_PORT", kf.get("port", "1239"))
    _state["user"] = os.environ.get("VONE_USERNAME", kf.get("user", ""))
    _state["pwd"]  = os.environ.get("VONE_PASSWORD", kf.get("pwd", ""))
    _state["api_ver"] = os.environ.get("VONE_API_VER", kf.get("api_ver", "2.2"))
    if not _state["user"] or not _state["pwd"]:
        raise RuntimeError(
            "Veeam ONE credentials missing — set VONE_USERNAME/VONE_PASSWORD "
            f"or populate keyfile {KEYFILE}"
        )
    s = requests.Session()
    s.verify = False
    _state["session"] = s


def base_url() -> str:
    _config()
    return f"https://{_state['host']}:{_state['port']}"


def _token_url() -> str:
    return f"{base_url()}/api/token"


def _api_url(path: str) -> str:
    p = path.lstrip("/")
    if p.startswith("api/"):
        return f"{base_url()}/{p}"
    return f"{base_url()}/api/v{_state['api_ver']}/{p}"


def _login() -> None:
    _config()
    s: requests.Session = _state["session"]
    body = urlencode({
        "grant_type": "password",
        "username": _state["user"],
        "password": _state["pwd"],
    })
    r = s.post(_token_url(),
               data=body,
               headers={
                   "Content-Type": "application/x-www-form-urlencoded",
                   "accept": "application/json",
                   "x-api-version": _state["api_ver"],
               },
               timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Veeam ONE auth failed: {r.status_code} {r.text}")
    j = r.json()
    _state["access_token"]  = j["access_token"]
    _state["refresh_token"] = j.get("refresh_token")
    _state["expires_at"]    = time.time() + int(j.get("expires_in", 900)) - 30


def _refresh() -> None:
    if not _state.get("refresh_token"):
        return _login()
    s: requests.Session = _state["session"]
    body = urlencode({
        "grant_type": "refresh_token",
        "refresh_token": _state["refresh_token"],
    })
    r = s.post(_token_url(),
               data=body,
               headers={
                   "Content-Type": "application/x-www-form-urlencoded",
                   "accept": "application/json",
                   "x-api-version": _state["api_ver"],
               },
               timeout=30)
    if r.status_code != 200:
        # refresh expired → full login
        return _login()
    j = r.json()
    _state["access_token"]  = j["access_token"]
    _state["refresh_token"] = j.get("refresh_token", _state["refresh_token"])
    _state["expires_at"]    = time.time() + int(j.get("expires_in", 900)) - 30


def _ensure_token() -> None:
    if not _state.get("access_token") or time.time() >= _state["expires_at"]:
        if _state.get("refresh_token"):
            _refresh()
        else:
            _login()


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    _ensure_token()
    h = {
        "Authorization": f"Bearer {_state['access_token']}",
        "x-api-version": _state["api_ver"],
        "accept": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def about() -> dict[str, Any]:
    """Service identity (name, version, machine). Auth required."""
    _config()
    s: requests.Session = _state["session"]
    r = s.get(_api_url("about"), headers=_headers(), timeout=20)
    r.raise_for_status()
    return r.json() if r.text else {}


def get(path: str,
        params: dict[str, Any] | None = None,
        allow_404: bool = False,
        allow_403: bool = False,
        retries: int = 3) -> Any:
    """GET a single resource or page."""
    _config()
    s: requests.Session = _state["session"]
    url = _api_url(path)
    for attempt in range(retries):
        r = s.get(url, headers=_headers(), params=params, timeout=60)
        if r.status_code == 401:
            # token rotated under us
            _login()
            continue
        if r.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (404,) and allow_404:
            return None
        if r.status_code in (403,) and allow_403:
            return None
        if 500 <= r.status_code < 600 and attempt < retries - 1:
            time.sleep(2 ** attempt)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"GET {path} → {r.status_code}: {r.text[:500]}")
        if not r.text:
            return None
        return r.json()
    raise RuntimeError(f"GET {path} retries exhausted")


def post(path: str, body: Any, params: dict[str, Any] | None = None,
         allow_404: bool = False) -> Any:
    """POST JSON body."""
    _config()
    s: requests.Session = _state["session"]
    url = _api_url(path)
    r = s.post(url, headers=_headers({"Content-Type": "application/json"}),
               params=params, data=json.dumps(body), timeout=120)
    if r.status_code == 401:
        _login()
        r = s.post(url, headers=_headers({"Content-Type": "application/json"}),
                   params=params, data=json.dumps(body), timeout=120)
    if r.status_code == 404 and allow_404:
        return None
    if r.status_code >= 400:
        raise RuntimeError(f"POST {path} → {r.status_code}: {r.text[:1000]}")
    if not r.text:
        return None
    return r.json()


def list_paged(path: str, params: dict[str, Any] | None = None,
               page_size: int = 200, max_items: int | None = None,
               allow_404: bool = False) -> list[dict[str, Any]]:
    """Iterate a Limit/Offset paged list endpoint and return all items."""
    out: list[dict[str, Any]] = []
    offset = 0
    base = dict(params or {})
    while True:
        q = dict(base, Limit=page_size, Offset=offset)
        page = get(path, params=q, allow_404=allow_404)
        if page is None:
            return out
        items = page.get("items", []) if isinstance(page, dict) else page
        if not items:
            break
        out.extend(items)
        if max_items and len(out) >= max_items:
            return out[:max_items]
        total = page.get("totalCount") if isinstance(page, dict) else None
        if total is not None and offset + len(items) >= total:
            break
        if len(items) < page_size:
            break
        offset += len(items)
    return out


# -- typed helpers (one per confirmed surface) --
def license_info() -> dict:
    return get("license")


def list_agents() -> list[dict]:
    return list_paged("agents")


def list_alarm_templates() -> list[dict]:
    return list_paged("alarms/templates")


def list_business_view_categories() -> list[dict]:
    return list_paged("businessView/categories")


def list_business_view_groups() -> list[dict]:
    return list_paged("businessView/groups")


def list_backup_servers() -> list[dict]:
    return list_paged("vbr/backupServers")


def list_repositories() -> list[dict]:
    return list_paged("vbr/repositories")


def list_scaleout_repositories() -> list[dict]:
    return list_paged("vbr/scaleOutRepositories", allow_404=True) or []


# -- diagnostics --
def whoami() -> dict[str, Any]:
    """Return service info + token expiry summary."""
    a = about()
    return {
        "service":  a.get("name"),
        "version":  a.get("version"),
        "machine":  a.get("machine"),
        "api_url":  base_url(),
        "api_ver":  _state["api_ver"],
        "user":     _state["user"],
        "token_expires_in_s": max(0, int(_state["expires_at"] - time.time())),
    }


if __name__ == "__main__":
    # Quick smoke test
    print(json.dumps(whoami(), indent=2))
    print(f"agents: {len(list_agents())}")
    print(f"alarm templates: {len(list_alarm_templates())}")
    print(f"backup servers: {len(list_backup_servers())}")
    print(f"repositories: {len(list_repositories())}")
    print(f"sobr: {len(list_scaleout_repositories())}")
