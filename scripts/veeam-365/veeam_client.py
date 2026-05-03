"""
Veeam Backup for Microsoft 365 (VB365) REST API client.

Reads credentials from the keys vault:
  %USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/veeam-365.md

The server uses a self-signed cert, so verify=False is hard-wired and the
urllib3 InsecureRequestWarning is suppressed at import time.

Auth uses OAuth2 Resource Owner Password Grant against /<ver>/token. The
client probes /v8 -> /v7 -> /v6 -> /v5 on first call and caches the
working version. Token is refreshed proactively at 90% of expires_in.

Generic surface:
    c = VeeamClient()                    # auth lazily on first call
    c.get('/Organizations')              # leading-slash path under /<ver>
    c.get_paginated('/Organizations')    # iterates limit/offset until done
    c.post('/Some/Action', json={...})

Convenience helpers wrap the most common reads (organizations, repos,
usage data, protected entities). See pull_tenant_summary.py for the first
concrete pipeline.
"""
from __future__ import annotations

import os
import re
import sys
import time
import json
import urllib3
import requests
from pathlib import Path
from typing import Any, Iterable, Iterator

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

KEYFILE = (
    Path(os.environ["USERPROFILE"])
    / "OneDrive - Technijian, Inc"
    / "Documents"
    / "VSCODE"
    / "keys"
    / "veeam-365.md"
)

DEFAULT_HOST = "10.7.9.227"
DEFAULT_PORT = 4443
VERSION_PROBE_ORDER = ("v8", "v7", "v6", "v5")
DEFAULT_PAGE_LIMIT = 100
REQUEST_TIMEOUT = 60
TOKEN_REFRESH_AT = 0.90  # refresh when 90% of lifetime has elapsed


def _read_keyfile() -> dict[str, str]:
    """Parse Host/Username/Password out of the markdown keys file."""
    if not KEYFILE.exists():
        raise FileNotFoundError(f"Veeam 365 keys file missing: {KEYFILE}")
    text = KEYFILE.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for key, pat in (
        ("host", r"\*\*Host:\*\*\s*([^\s]+)"),
        ("username", r"\*\*Username:\*\*\s*`?([^`\n]+?)`?\s*$"),
        ("password", r"\*\*Password:\*\*\s*([^\s].*?)\s*$"),
    ):
        m = re.search(pat, text, flags=re.MULTILINE)
        if m:
            out[key] = m.group(1).strip()
    if not all(k in out for k in ("host", "username", "password")):
        raise RuntimeError(
            f"Could not parse host/username/password from {KEYFILE}; "
            f"got keys: {sorted(out)}"
        )
    return out


class VeeamClient:
    """Lazy-auth REST client for Veeam Backup for Microsoft 365."""

    def __init__(
        self,
        host: str | None = None,
        port: int = DEFAULT_PORT,
        username: str | None = None,
        password: str | None = None,
        api_version: str | None = None,
    ) -> None:
        creds = _read_keyfile() if (username is None or password is None or host is None) else {}
        self.host = host or creds["host"]
        self.port = port
        self.username = username or creds["username"]
        self.password = password or creds["password"]
        self.base = f"https://{self.host}:{self.port}"
        self.api_version = api_version  # may be None; resolved by _login
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at: float = 0.0
        self.session = requests.Session()
        self.session.verify = False

    # ---------- auth ----------

    def _token_url(self, version: str) -> str:
        return f"{self.base}/{version}/token"

    def _try_login(self, version: str) -> bool:
        """Return True if password grant succeeds at /<version>/token."""
        body = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
        }
        try:
            r = self.session.post(
                self._token_url(version),
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.RequestException:
            return False
        if r.status_code != 200:
            return False
        try:
            payload = r.json()
        except ValueError:
            return False
        if "access_token" not in payload:
            return False
        self._access_token = payload["access_token"]
        self._refresh_token = payload.get("refresh_token")
        expires_in = int(payload.get("expires_in") or 3600)
        self._token_expires_at = time.time() + (expires_in * TOKEN_REFRESH_AT)
        self.api_version = version
        return True

    def _login(self) -> None:
        """Authenticate; probe API versions if not pinned."""
        if self.api_version:
            if self._try_login(self.api_version):
                return
            raise RuntimeError(
                f"Auth failed against /{self.api_version}/token on {self.base}"
            )
        for v in VERSION_PROBE_ORDER:
            if self._try_login(v):
                return
        raise RuntimeError(
            f"Auth failed on {self.base} for all probed API versions "
            f"({VERSION_PROBE_ORDER})"
        )

    def _refresh(self) -> None:
        if not self._refresh_token:
            self._login()
            return
        body = {"grant_type": "refresh_token", "refresh_token": self._refresh_token}
        r = self.session.post(
            self._token_url(self.api_version),  # type: ignore[arg-type]
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            self._login()
            return
        payload = r.json()
        self._access_token = payload["access_token"]
        self._refresh_token = payload.get("refresh_token", self._refresh_token)
        expires_in = int(payload.get("expires_in") or 3600)
        self._token_expires_at = time.time() + (expires_in * TOKEN_REFRESH_AT)

    def _ensure_auth(self) -> None:
        if not self._access_token:
            self._login()
        elif time.time() >= self._token_expires_at:
            self._refresh()

    # ---------- raw HTTP ----------

    _VERSION_PREFIX = re.compile(r"^/v\d+/", re.IGNORECASE)

    def _full_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        # leave any explicit /vN/ prefix (server returns /v7/ even on v8 sessions)
        if self.api_version and not self._VERSION_PREFIX.match(path):
            path = f"/{self.api_version}{path}"
        return f"{self.base}{path}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: Any = None,
        data: Any = None,
        allow_404: bool = False,
        retries: int = 2,
    ) -> requests.Response | None:
        self._ensure_auth()
        url = self._full_url(path)
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }
        for attempt in range(retries + 1):
            r = self.session.request(
                method,
                url,
                params=params,
                json=json_body,
                data=data,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 401 and attempt == 0:
                self._login()
                headers["Authorization"] = f"Bearer {self._access_token}"
                continue
            if r.status_code == 404 and allow_404:
                return None
            if 500 <= r.status_code < 600 and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        return None  # unreachable

    # ---------- public helpers ----------

    def get(self, path: str, params: dict | None = None, allow_404: bool = False) -> Any:
        r = self._request("GET", path, params=params, allow_404=allow_404)
        if r is None:
            return None
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return r.text

    def post(self, path: str, json_body: Any = None, data: Any = None) -> Any:
        r = self._request("POST", path, json_body=json_body, data=data)
        if r is None or not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return r.text

    def get_paginated(
        self,
        path: str,
        params: dict | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        max_pages: int = 1000,
    ) -> Iterator[dict]:
        """
        Yield every item from a paginated VB365 list endpoint.

        Handles three response shapes seen in the wild:
          1. {"results": [...], "_links": {"next": {"href": "..."}}}  (HAL)
          2. {"results": [...], "totalCount": N}
          3. raw list  [...]
        Falls back to limit/offset when no `next` link is present.
        """
        params = dict(params or {})
        params.setdefault("limit", limit)
        params.setdefault("offset", 0)
        next_url: str | None = None
        for _ in range(max_pages):
            if next_url:
                r = self._request("GET", next_url)
            else:
                r = self._request("GET", path, params=params)
            if r is None:
                return
            try:
                payload = r.json()
            except ValueError:
                return
            if isinstance(payload, list):
                for item in payload:
                    yield item
                return
            if not isinstance(payload, dict):
                return
            results = payload.get("results")
            if results is None:
                # endpoint isn't paginated; treat top-level as the item
                yield payload
                return
            for item in results:
                yield item
            links = payload.get("_links") or {}
            nxt = (links.get("next") or {}).get("href") if isinstance(links, dict) else None
            if nxt:
                next_url = nxt
                params = None  # next link is self-contained
                continue
            # No next link — once we've started following next_url we trust HAL.
            if params is None:
                return
            # Otherwise fall back to offset bumping for non-HAL endpoints.
            if len(results) < params["limit"]:
                return
            params["offset"] += params["limit"]
            next_url = None

    # ---------- domain wrappers ----------

    def server_info(self) -> dict | None:
        """No-auth product/version info. Tries common paths."""
        for ver in VERSION_PROBE_ORDER:
            try:
                r = self.session.get(
                    f"{self.base}/{ver}/ServerInfo", timeout=REQUEST_TIMEOUT
                )
            except requests.exceptions.RequestException:
                continue
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    return None
        return None

    def list_organizations(self) -> list[dict]:
        return list(self.get_paginated("/Organizations"))

    def get_organization(self, org_id: str) -> dict | None:
        return self.get(f"/Organizations/{org_id}", allow_404=True)

    def list_backup_repositories(self) -> list[dict]:
        return list(self.get_paginated("/BackupRepositories"))

    def list_protected_users(self, repo_id: str) -> list[dict]:
        return list(
            self.get_paginated(f"/BackupRepositories/{repo_id}/OrganizationUsers")
        )

    def list_protected_groups(self, repo_id: str) -> list[dict]:
        return list(
            self.get_paginated(f"/BackupRepositories/{repo_id}/OrganizationGroups")
        )

    def list_protected_sites(self, repo_id: str) -> list[dict]:
        return list(
            self.get_paginated(f"/BackupRepositories/{repo_id}/OrganizationSites")
        )

    def list_protected_teams(self, repo_id: str) -> list[dict]:
        return list(
            self.get_paginated(f"/BackupRepositories/{repo_id}/OrganizationTeams")
        )

    def list_jobs(self) -> list[dict]:
        return list(self.get_paginated("/Jobs"))

    def list_proxies(self) -> list[dict]:
        return list(self.get_paginated("/Proxies"))


def _cli() -> None:
    """Quick smoke test:  python veeam_client.py [path]"""
    c = VeeamClient()
    info = c.server_info()
    print("server_info:", json.dumps(info, indent=2) if info else "<none>")
    if len(sys.argv) >= 2:
        path = sys.argv[1]
        try:
            data = c.get(path)
        except requests.HTTPError as e:
            print(f"HTTP {e.response.status_code} for {path}: {e.response.text[:400]}")
            sys.exit(1)
        print(f"--- GET {path} ---")
        print(json.dumps(data, indent=2)[:4000])
    else:
        # default: print the working API version + token state
        try:
            c._login()
        except Exception as e:
            print(f"Auth failed: {e}")
            sys.exit(1)
        print(f"OK  api_version={c.api_version}  base={c.base}")


if __name__ == "__main__":
    _cli()
