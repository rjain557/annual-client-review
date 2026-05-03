"""Veeam Backup & Replication REST API client.

Reads credentials from the keys vault at:
    %OneDrive%/Documents/VSCODE/keys/veeam-vbr.md

Usage:
    from veeam_client import VeeamClient
    c = VeeamClient()                 # default vault path + 10.7.9.227
    c.login()
    print(c.get('/serverInfo'))

CLI:
    python veeam_client.py serverInfo
    python veeam_client.py jobs
    python veeam_client.py raw /backupInfrastructure/repositories
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.retry import Retry

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

DEFAULT_HOST = "10.7.9.220"
DEFAULT_PORT = 9419
DEFAULT_API_VERSION = "1.2-rev0"
DEFAULT_PAGE_LIMIT = 200


def _onedrive_root() -> Path:
    od = os.environ.get("OneDrive") or os.environ.get("OneDriveCommercial")
    if not od:
        # Fallback: well-known path on this workstation.
        od = r"C:\Users\rjain\OneDrive - Technijian, Inc"
    return Path(od)


def _default_keyfile() -> Path:
    return _onedrive_root() / "Documents" / "VSCODE" / "keys" / "veeam-vbr.md"


def parse_keyfile(path: Path) -> Dict[str, str]:
    """Extract key/value pairs from the markdown keyfile.

    Looks for bullets like '- **Username:** foo' or '**Password:** bar' and
    returns a flat dict. Tolerant of bold markers and stray whitespace.
    """
    txt = path.read_text(encoding="utf-8", errors="replace")
    out: Dict[str, str] = {}
    pat = re.compile(r"\*\*([^*]+?):\*\*\s*([^\n]+)")
    for k, v in pat.findall(txt):
        out[k.strip().lower()] = v.strip().strip("`").strip()
    return out


class VeeamAuthError(RuntimeError):
    pass


class VeeamApiError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"{status} {url}: {body[:400]}")
        self.status = status
        self.body = body
        self.url = url


class VeeamClient:
    def __init__(
        self,
        host: Optional[str] = None,
        port: int = DEFAULT_PORT,
        api_version: str = DEFAULT_API_VERSION,
        keyfile: Optional[Path] = None,
        verify_tls: bool = False,
        timeout: int = 60,
    ):
        kf = Path(keyfile) if keyfile else _default_keyfile()
        creds = parse_keyfile(kf) if kf.exists() else {}
        self.host = host or creds.get("ip") or creds.get("host") or DEFAULT_HOST
        # Strip everything after the IP token if the value was 'TE-DC... 10.7.9.227'
        m = re.search(r"\d{1,3}(?:\.\d{1,3}){3}", self.host)
        if m:
            self.host = m.group(0)
        self.port = port
        self.api_version = api_version
        self.username = creds.get("username")
        self.password = creds.get("password")
        if not self.username or not self.password:
            raise VeeamAuthError(
                f"Could not parse Username/Password from {kf}. "
                "Expected '- **Username:** ...' / '- **Password:** ...' lines."
            )
        self.base = f"https://{self.host}:{self.port}/api"
        self.session = requests.Session()
        self.session.verify = verify_tls
        self.session.timeout = timeout
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._access_expires_at: float = 0.0
        self.timeout = timeout

    # ---- auth -----------------------------------------------------------
    def login(self) -> None:
        url = f"{self.base}/oauth2/token"
        headers = {
            "x-api-version": self.api_version,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        body = urlencode(
            {
                "grant_type": "password",
                "username": self.username,
                "password": self.password,
            }
        )
        r = self.session.post(url, data=body, headers=headers, timeout=self.timeout)
        if r.status_code >= 400:
            raise VeeamAuthError(f"login {r.status_code}: {r.text[:400]}")
        j = r.json()
        self._access_token = j["access_token"]
        self._refresh_token = j.get("refresh_token")
        ttl = int(j.get("expires_in", 86_400))
        self._access_expires_at = time.time() + ttl - 60

    def _ensure_token(self) -> None:
        if not self._access_token or time.time() >= self._access_expires_at:
            self.login()

    # ---- core HTTP ------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        self._ensure_token()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "x-api-version": self.api_version,
            "Accept": "application/json",
        }

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base}/v1{path}" if not path.startswith("http") else path
        r = self.session.get(url, headers=self._headers(), params=params, timeout=self.timeout)
        if r.status_code >= 400:
            raise VeeamApiError(r.status_code, r.text, url)
        if not r.content:
            return None
        return r.json()

    def post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base}/v1{path}" if not path.startswith("http") else path
        h = self._headers()
        h["Content-Type"] = "application/json"
        r = self.session.post(url, headers=h, json=body, timeout=self.timeout)
        if r.status_code >= 400:
            raise VeeamApiError(r.status_code, r.text, url)
        if not r.content:
            return None
        return r.json()

    # ---- pagination -----------------------------------------------------
    def get_paged(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        max_pages: int = 1000,
    ) -> Iterable[Dict[str, Any]]:
        """Iterate `data` items across paged Veeam responses.

        Veeam paging convention: query params `skip` and `limit`; response shape
        `{ "data": [...], "pagination": {"total": N, "count": M, "skip": S, "limit": L} }`.
        """
        skip = 0
        params = dict(params or {})
        for _ in range(max_pages):
            params["skip"] = skip
            params["limit"] = limit
            page = self.get(path, params=params)
            if not isinstance(page, dict):
                if isinstance(page, list):
                    yield from page
                return
            data = page.get("data") or []
            for item in data:
                yield item
            pag = page.get("pagination") or {}
            total = pag.get("total")
            count = pag.get("count", len(data))
            if not data or count == 0:
                return
            skip += count
            if total is not None and skip >= total:
                return


# ---------------------------------------------------------------- CLI ----
def _cli() -> int:
    ap = argparse.ArgumentParser(description="Veeam VBR REST quick CLI")
    ap.add_argument("command", help="serverInfo | jobs | raw")
    ap.add_argument("path", nargs="?", default=None, help="API path for 'raw'")
    ap.add_argument("--host", default=None)
    ap.add_argument("--keyfile", default=None)
    ap.add_argument("--api-version", default=DEFAULT_API_VERSION)
    args = ap.parse_args()

    c = VeeamClient(host=args.host, keyfile=args.keyfile, api_version=args.api_version)
    c.login()

    if args.command == "serverInfo":
        print(json.dumps(c.get("/serverInfo"), indent=2, default=str))
    elif args.command == "jobs":
        print(json.dumps(list(c.get_paged("/jobs")), indent=2, default=str))
    elif args.command == "raw":
        if not args.path:
            print("raw requires a path, e.g. /backupInfrastructure/repositories", file=sys.stderr)
            return 2
        print(json.dumps(c.get(args.path), indent=2, default=str))
    else:
        ap.error(f"unknown command {args.command!r}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
