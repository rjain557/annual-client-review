"""MailStore SPE Management API client.

Reusable module for the MailStore Service Provider Edition pipeline.

Auth scheme:
    HTTP Basic against https://archive.technijian.com:8474/api/invoke/<Function>.
    All calls are POST. Body is application/x-www-form-urlencoded (never JSON).
    Empty bodies still require Content-Length: 0 — Microsoft-HTTPAPI/2.0 returns
    HTTP 411 otherwise.

Long-running operations:
    Functions like CompactStore / VerifyStores / RebuildSelectedStoreIndexes
    return statusCode='running' and a token. Poll /api/get-status?id=<token> until
    statusCode != 'running'. Use Client.invoke_long_running().

Credentials are read in priority order:
  1) env vars MAILSTORE_SPE_USER / MAILSTORE_SPE_PASSWORD
  2) the keyfile at %USERPROFILE%\\OneDrive - Technijian, Inc\\Documents\\VSCODE\\keys\\mailstore-spe.md

Self-signed cert on 8474 — TLS verification is disabled by default.
"""
from __future__ import annotations

import base64
import json
import os
import re
import ssl
import time
from pathlib import Path
from typing import Any, Optional
from urllib import request as urlrequest
from urllib.error import HTTPError
from urllib.parse import urlencode

DEFAULT_BASE_URL = "https://archive.technijian.com:8474"
DEFAULT_TIMEOUT = 120
LONG_RUNNING_POLL_SECS = 2
LONG_RUNNING_MAX_WAIT = 1800  # 30 min


def _read_keyvault_creds() -> Optional[tuple[str, str, str]]:
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    path = Path(home) / "OneDrive - Technijian, Inc" / "Documents" / "VSCODE" / "keys" / "mailstore-spe.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    u = re.search(r"\*\*Username:\*\*\s*(\S+)", text)
    p = re.search(r"\*\*Password:\*\*\s*(\S+)", text)
    base = re.search(r"\*\*Management API base:\*\*\s*(\S+)", text)
    if not u or not p:
        return None
    pwd = p.group(1)
    if pwd.startswith("TODO"):
        return None
    base_url = base.group(1).rstrip("/") if base else DEFAULT_BASE_URL
    if base_url.endswith("/api/invoke") or base_url.endswith("/api/invoke/"):
        base_url = base_url.rsplit("/api/invoke", 1)[0]
    return u.group(1), pwd, base_url


def get_credentials() -> tuple[str, str, str]:
    u = os.environ.get("MAILSTORE_SPE_USER")
    p = os.environ.get("MAILSTORE_SPE_PASSWORD")
    base_url = os.environ.get("MAILSTORE_SPE_URL", DEFAULT_BASE_URL).rstrip("/")
    if u and p:
        return u, p, base_url
    creds = _read_keyvault_creds()
    if creds:
        return creds
    raise RuntimeError(
        "MailStore SPE credentials not found. Set MAILSTORE_SPE_USER / MAILSTORE_SPE_PASSWORD "
        "env vars OR fill the **Username:** / **Password:** lines in "
        "%USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/mailstore-spe.md"
    )


class SPEError(RuntimeError):
    """Raised when the API returns a structured error or a long-running op fails."""


class Client:
    def __init__(self, base_url: Optional[str] = None, verify_tls: bool = False, timeout: int = DEFAULT_TIMEOUT):
        u, p, k_base = get_credentials()
        self.base_url = (base_url or k_base or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._auth = "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()
        if verify_tls:
            self._ssl = ssl.create_default_context()
        else:
            self._ssl = ssl.create_default_context()
            self._ssl.check_hostname = False
            self._ssl.verify_mode = ssl.CERT_NONE
        self._metadata: Optional[dict[str, dict[str, Any]]] = None

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------
    def _request(self, path: str, body: str = "", method: str = "POST") -> Any:
        url = f"{self.base_url}{path}"
        data = body.encode("utf-8")
        req = urlrequest.Request(
            url,
            data=data if method == "POST" else None,
            method=method,
            headers={
                "Authorization": self._auth,
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(data)),
            },
        )
        try:
            with urlrequest.urlopen(req, context=self._ssl, timeout=self.timeout) as r:
                return json.loads(r.read())
        except HTTPError as e:
            payload = e.read().decode(errors="replace")
            raise SPEError(f"HTTP {e.code} {path}: {payload[:300]}") from e

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def metadata(self) -> dict[str, dict[str, Any]]:
        """Return {functionName: {name, args:[{name,type,nullable}, ...]}}."""
        if self._metadata is None:
            data = self._request("/api/get-metadata", method="GET")
            self._metadata = {f["name"]: f for f in data} if isinstance(data, list) else {}
        return self._metadata

    def invoke(self, function: str, **params: Any) -> Any:
        """Invoke a Management API function. Returns the unwrapped `result`.

        If the function starts a long-running operation (statusCode == 'running'),
        this polls /api/get-status until completion and returns the final result.
        Raises SPEError on any non-null `error`.
        """
        body_pairs = []
        for k, v in params.items():
            if v is None:
                continue
            if isinstance(v, bool):
                v = "true" if v else "false"
            body_pairs.append((k, str(v)))
        body = urlencode(body_pairs)
        resp = self._request(f"/api/invoke/{function}", body=body)
        return self._handle_response(resp, function)

    def invoke_raw(self, function: str, **params: Any) -> dict:
        """Invoke and return the full envelope (error/statusCode/result/...)
        without raising on `running` or surfacing errors. Used by run_function."""
        body_pairs = [(k, ("true" if v is True else "false" if v is False else str(v))) for k, v in params.items() if v is not None]
        return self._request(f"/api/invoke/{function}", body=urlencode(body_pairs))

    def _handle_response(self, resp: dict, function: str) -> Any:
        if resp.get("error"):
            err = resp["error"]
            raise SPEError(f"{function}: {err.get('message','?')} :: {err.get('details','')[:300]}")
        status = resp.get("statusCode")
        if status == "running" and resp.get("token"):
            return self._poll_status(resp["token"], function)
        return resp.get("result")

    def _poll_status(self, token: str, function: str) -> Any:
        deadline = time.time() + LONG_RUNNING_MAX_WAIT
        last_version = -1
        while time.time() < deadline:
            time.sleep(LONG_RUNNING_POLL_SECS)
            body = urlencode([("token", token), ("lastKnownStatusVersion", str(last_version))])
            resp = self._request("/api/get-status", body=body)
            status = resp.get("statusCode")
            last_version = resp.get("statusVersion", last_version)
            if status != "running":
                if resp.get("error"):
                    err = resp["error"]
                    raise SPEError(f"{function} (long-running): {err.get('message','?')}")
                return resp.get("result")
        raise SPEError(f"{function}: long-running op exceeded {LONG_RUNNING_MAX_WAIT}s")

    # ------------------------------------------------------------------
    # Convenience wrappers (typed where useful)
    # ------------------------------------------------------------------
    def env_info(self) -> dict:
        return self.invoke("GetEnvironmentInfo")

    def service_status(self) -> dict:
        return self.invoke("GetServiceStatus")

    def list_instances(self, instance_filter: str = "*") -> list[dict]:
        return self.invoke("GetInstances", instanceFilter=instance_filter) or []

    def instance_statistics(self, instance_id: str) -> dict:
        return self.invoke("GetInstanceStatistics", instanceID=instance_id) or {}

    def instance_live(self, instance_id: str) -> dict:
        return self.invoke("GetInstanceProcessLiveStatistics", instanceID=instance_id) or {}

    def stores(self, instance_id: str, include_size: bool = True) -> list[dict]:
        return self.invoke("GetStores", instanceID=instance_id, includeSize=include_size) or []

    def users(self, instance_id: str) -> list[dict]:
        return self.invoke("GetUsers", instanceID=instance_id) or []

    def user_info(self, instance_id: str, user_name: str) -> dict:
        return self.invoke("GetUserInfo", instanceID=instance_id, userName=user_name) or {}

    def folder_statistics(self, instance_id: str) -> list[dict]:
        return self.invoke("GetFolderStatistics", instanceID=instance_id) or []

    def jobs(self, instance_id: str) -> list[dict]:
        return self.invoke("GetJobs", instanceID=instance_id) or []

    def profiles(self, instance_id: str, raw: bool = False) -> list[dict]:
        return self.invoke("GetProfiles", instanceID=instance_id, raw=raw) or []

    def credentials_list(self, instance_id: str) -> list[dict]:
        return self.invoke("GetCredentials", instanceID=instance_id) or []

    def index_config(self, instance_id: str) -> dict:
        return self.invoke("GetIndexConfiguration", instanceID=instance_id) or {}

    def compliance_config(self, instance_id: str) -> dict:
        return self.invoke("GetComplianceConfiguration", instanceID=instance_id) or {}

    def directory_services_config(self, instance_id: str) -> dict:
        return self.invoke("GetDirectoryServicesConfiguration", instanceID=instance_id) or {}

    def instance_configuration(self, instance_id: str) -> dict:
        return self.invoke("GetInstanceConfiguration", instanceID=instance_id) or {}


# Mapping from MailStore instanceID -> annual-client-review client folder code.
# Edit this when a new client archive is provisioned.
INSTANCE_TO_CLIENT_CODE = {
    "icmlending": "icml",
    "icm-realestate": "icml",   # same client family; per-instance file suffix keeps them separate
    "orthoxpress": "orx",
}


def client_code_for(instance_id: str) -> Optional[str]:
    return INSTANCE_TO_CLIENT_CODE.get(instance_id)


def fmt_bytes(n: Optional[int]) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_mb(mb: Optional[int]) -> str:
    if mb is None:
        return "?"
    return f"{mb/1024:.1f} GB" if mb >= 1024 else f"{mb} MB"
