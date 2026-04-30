"""Sophos Central Partner API client.

Reads credentials from env vars first, then the OneDrive keyfile at
%USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/sophos.md.

Auth is OAuth2 client_credentials. Two-stage call pattern:
  1. /whoami/v1 (global host) -> partner id
  2. /partner/v1/tenants (global host, X-Partner-ID header) -> per-tenant apiHost
  3. tenant-scoped calls go to that apiHost with X-Tenant-ID

Read-only. No write endpoints exposed here.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

IDENTITY_URL = "https://id.sophos.com/api/v2/oauth2/token"
GLOBAL_HOST = "https://api.central.sophos.com"
KEYFILE = (
    Path(os.environ.get("USERPROFILE", str(Path.home())))
    / "OneDrive - Technijian, Inc"
    / "Documents"
    / "VSCODE"
    / "keys"
    / "sophos.md"
)

_token: dict[str, Any] = {"value": None, "expires_at": 0.0}


def _read_keyfile() -> tuple[str, str]:
    if not KEYFILE.exists():
        raise RuntimeError(f"Sophos keyfile not found: {KEYFILE}")
    text = KEYFILE.read_text(encoding="utf-8")
    cid = sec = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- **Client ID:**"):
            cid = line.split(":**", 1)[1].strip()
        elif line.startswith("- **Client Secret:**"):
            sec = line.split(":**", 1)[1].strip()
    if not cid or not sec:
        raise RuntimeError(f"Could not parse Client ID / Client Secret from {KEYFILE}")
    return cid, sec


def _credentials() -> tuple[str, str]:
    cid = os.environ.get("SOPHOS_CLIENT_ID")
    sec = os.environ.get("SOPHOS_CLIENT_SECRET")
    if cid and sec:
        return cid, sec
    return _read_keyfile()


def _post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET", headers={**headers, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {url}\n{body}") from None


def get_token() -> str:
    if _token["value"] and _token["expires_at"] - time.time() > 60:
        return _token["value"]  # type: ignore[return-value]
    cid, sec = _credentials()
    payload = {
        "grant_type": "client_credentials",
        "client_id": cid,
        "client_secret": sec,
        "scope": "token",
    }
    resp = _post_form(IDENTITY_URL, payload)
    _token["value"] = resp["access_token"]
    _token["expires_at"] = time.time() + float(resp.get("expires_in", 3600))
    return resp["access_token"]


def _bearer_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {get_token()}"}
    if extra:
        h.update(extra)
    return h


def whoami() -> dict[str, Any]:
    return _get_json(f"{GLOBAL_HOST}/whoami/v1", _bearer_headers())


def list_tenants() -> list[dict[str, Any]]:
    me = whoami()
    if me.get("idType") != "partner":
        raise RuntimeError(f"whoami idType is {me.get('idType')!r}; expected 'partner'.")
    partner_id = me["id"]
    headers = _bearer_headers({"X-Partner-ID": partner_id})
    tenants: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"{GLOBAL_HOST}/partner/v1/tenants?pageTotal=true&page={page}&pageSize=100"
        resp = _get_json(url, headers)
        items = resp.get("items", [])
        tenants.extend(items)
        pages = resp.get("pages", {})
        total_pages = int(pages.get("total") or pages.get("totalPages") or 1)
        if page >= total_pages or not items:
            break
        page += 1
    return tenants


def list_firewalls(tenant: dict[str, Any]) -> list[dict[str, Any]]:
    api_host = tenant["apiHost"]
    tenant_id = tenant["id"]
    headers = _bearer_headers({"X-Tenant-ID": tenant_id})
    url = f"{api_host}/firewall/v1/firewalls"
    resp = _get_json(url, headers)
    return resp.get("items", []) if isinstance(resp, dict) else []


def tenant_get(tenant: dict[str, Any], path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
    """Generic tenant-scoped GET. Returns {status, body, error} so callers can probe."""
    api_host = tenant["apiHost"]
    tenant_id = tenant["id"]
    headers = _bearer_headers({"X-Tenant-ID": tenant_id})
    url = f"{api_host}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, method="GET", headers={**headers, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
            return {"status": r.status, "body": body}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": e.read().decode("utf-8", errors="replace")[:300]}
    except Exception as e:
        return {"status": "ERR", "body": str(e)[:300]}


def partner_get(path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
    """Generic partner-scoped GET against the global host."""
    me = whoami()
    headers = _bearer_headers({"X-Partner-ID": me["id"]})
    url = f"{GLOBAL_HOST}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, method="GET", headers={**headers, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
            return {"status": r.status, "body": body}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": e.read().decode("utf-8", errors="replace")[:300]}
    except Exception as e:
        return {"status": "ERR", "body": str(e)[:300]}


def partner_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """Partner-scoped POST. Used for admin role assignments. Caller must
    confirm the operation is approved — this is a write API."""
    me = whoami()
    headers = _bearer_headers({"X-Partner-ID": me["id"], "Content-Type": "application/json"})
    url = f"{GLOBAL_HOST}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={**headers, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8")
            return {"status": r.status, "body": json.loads(text) if text else {}}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": e.read().decode("utf-8", errors="replace")[:500]}
    except Exception as e:
        return {"status": "ERR", "body": str(e)[:500]}


def partner_delete(path: str) -> dict[str, Any]:
    """Partner-scoped DELETE. Used to remove admin role assignments."""
    me = whoami()
    headers = _bearer_headers({"X-Partner-ID": me["id"]})
    url = f"{GLOBAL_HOST}{path}"
    req = urllib.request.Request(url, method="DELETE",
                                 headers={**headers, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8")
            return {"status": r.status, "body": json.loads(text) if text else {}}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": e.read().decode("utf-8", errors="replace")[:500]}
    except Exception as e:
        return {"status": "ERR", "body": str(e)[:500]}


if __name__ == "__main__":
    me = whoami()
    print("[whoami]", json.dumps(me, indent=2))
    tenants = list_tenants()
    print(f"[tenants] {len(tenants)} tenant(s):")
    for t in tenants:
        print(f"  - {t.get('name'):40s}  region={t.get('dataRegion')}  id={t.get('id')}  apiHost={t.get('apiHost')}")
    if "--firewalls" in sys.argv:
        for t in tenants:
            try:
                fws = list_firewalls(t)
            except Exception as e:
                print(f"  [firewalls] {t.get('name')}: ERROR {e}")
                continue
            if fws:
                print(f"  [firewalls] {t.get('name')}: {len(fws)} firewall(s)")
                for fw in fws:
                    print(f"      - {fw.get('name')}  serial={fw.get('serialNumber')}  model={fw.get('model')}  fw={fw.get('firmwareVersion')}")
