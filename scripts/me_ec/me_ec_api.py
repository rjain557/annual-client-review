"""ManageEngine Endpoint Central MSP 11 - REST API client.

The MSP server exposes two API namespaces with different conventions:

    /api/1.4/desktop/customers          — server-wide customer enumeration
                                          (per-server, no customer scope)
    /dcapi/threats/patches              — applicable-patch catalog per
                                          customer (customername=<NAME>)
    /dcapi/threats/systemreport/patches — per-system patch matrix per
                                          customer (customername=<NAME>)

Auth: bare API key in the ``Authorization`` header (NO scheme prefix —
not ``Bearer ``, not ``Zoho-authtoken ``). Issue / regenerate the key at
``Admin → API Settings → API Key Management → Generate Key``. EC returns
JSON bodies with ``Content-Type: text/plain`` — always parse as JSON.

Reads credentials from ``%USERPROFILE%/OneDrive - Technijian, Inc/Documents/
VSCODE/keys/manageengine-ec.md`` unless ``ME_EC_API_KEY`` is set.
TLS: self-signed cert on the on-prem server, so ``verify=False`` by default.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib3
from pathlib import Path
from typing import Any, Iterable

import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_HOST = "https://myrmm.technijian.com:8041"
DEFAULT_KEYFILE = (
    Path(os.environ.get("USERPROFILE", str(Path.home())))
    / "OneDrive - Technijian, Inc"
    / "Documents"
    / "VSCODE"
    / "keys"
    / "manageengine-ec.md"
)


def _load_api_key() -> str:
    env = os.environ.get("ME_EC_API_KEY")
    if env:
        return env.strip()
    if not DEFAULT_KEYFILE.exists():
        raise RuntimeError(
            f"ME_EC_API_KEY not set and keyfile missing: {DEFAULT_KEYFILE}"
        )
    text = DEFAULT_KEYFILE.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\*\*API Key:\*\*\s*([0-9A-Fa-f-]{20,})", text)
    if not m:
        raise RuntimeError(f"could not parse API Key from {DEFAULT_KEYFILE}")
    return m.group(1).strip()


class MEECClient:
    def __init__(
        self,
        host: str | None = None,
        api_key: str | None = None,
        verify_tls: bool = False,
        timeout: int = 60,
    ) -> None:
        self.host = (host or os.environ.get("ME_EC_HOST") or DEFAULT_HOST).rstrip("/")
        self.api_key = api_key or _load_api_key()
        self.verify_tls = verify_tls
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                # Bare token — NO scheme prefix. EC IAM rejects "Bearer X",
                # "Zoho-authtoken X", etc. with error_code 10002.
                "Authorization": self.api_key,
                "Accept": "application/json",
                "User-Agent": "technijian-acr/me-ec-pull",
            }
        )

    def get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.host}/{path.lstrip('/')}"
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, verify=self.verify_tls, timeout=self.timeout)
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            try:
                # EC returns JSON with Content-Type: text/plain — parse anyway
                return r.json()
            except ValueError:
                return r.text
        raise RuntimeError(f"GET {url} failed after retries")

    def paginated_dcapi(
        self,
        path: str,
        params: dict | None = None,
        page_size: int = 100,
        list_key: str | None = None,
    ) -> Iterable[dict]:
        """Walk all pages of a /dcapi endpoint.

        /dcapi responses use the envelope::

            {
              "metadata": {"page": 1, "totalPages": N, "totalRecords": "...",
                            "links": {"next": "...", "prev": null}},
              "response_code": 200,
              "message_type": "<entity>",
              "message_response": {"<entity>": [...]}
            }

        Pagination params are ``page`` and ``pageLimit`` (note camelCase L).
        """
        params = dict(params or {})
        page = 1
        while True:
            params["page"] = page
            params["pageLimit"] = page_size
            body = self.get(path, params)
            if not isinstance(body, dict):
                return
            envelope = body.get("message_response") or {}
            rows = envelope.get(list_key) if list_key else None
            if rows is None:
                # fall back: first list-typed value
                for v in envelope.values():
                    if isinstance(v, list):
                        rows = v
                        break
            if not rows:
                return
            for row in rows:
                yield row
            meta = body.get("metadata") or {}
            total_pages = int(meta.get("totalPages") or 0)
            if total_pages and page >= total_pages:
                return
            if len(rows) < page_size:
                return
            page += 1


# ----------------------------- helpers ---------------------------------------

def whoami(client: MEECClient | None = None) -> dict:
    """Hit a low-cost server-scope endpoint to confirm auth works."""
    client = client or MEECClient()
    return client.get("api/1.4/desktop/customers")


def list_customers(client: MEECClient | None = None) -> list[dict]:
    """Return every MSP customer (id, name, email, address, ...)."""
    client = client or MEECClient()
    body = client.get("api/1.4/desktop/customers")
    env = body.get("message_response") if isinstance(body, dict) else None
    if not isinstance(env, dict):
        return []
    return env.get("customers") or env.get("customer") or []


def applicable_patches(customer_name: str, client: MEECClient | None = None) -> list[dict]:
    """All patches applicable to a customer's endpoints (catalog view)."""
    client = client or MEECClient()
    return list(
        client.paginated_dcapi(
            "dcapi/threats/patches",
            params={"customername": customer_name},
            list_key="patches",
        )
    )


def system_patch_report(customer_name: str, client: MEECClient | None = None) -> list[dict]:
    """Per-system patch report (one row per system, with its patch list)."""
    client = client or MEECClient()
    return list(
        client.paginated_dcapi(
            "dcapi/threats/systemreport/patches",
            params={"customername": customer_name},
            list_key="systemreport",
        )
    )


def missing_patches(customer_name: str, client: MEECClient | None = None) -> list[dict]:
    """Filter applicable patches down to patch_status=Missing."""
    client = client or MEECClient()
    return list(
        client.paginated_dcapi(
            "dcapi/threats/patches",
            params={"customername": customer_name, "patch_status": "Missing"},
            list_key="patches",
        )
    )


def installed_patches(customer_name: str, client: MEECClient | None = None) -> list[dict]:
    client = client or MEECClient()
    return list(
        client.paginated_dcapi(
            "dcapi/threats/patches",
            params={"customername": customer_name, "patch_status": "Installed"},
            list_key="patches",
        )
    )


# ----------------------------- CLI -------------------------------------------

def _cli() -> int:
    if len(sys.argv) < 2:
        print(
            "usage: me_ec_api.py <whoami|customers|patches|patches-missing|"
            "patches-installed|systems-report> [--customer <name>]",
            file=sys.stderr,
        )
        return 2
    cmd = sys.argv[1]
    args = sys.argv[2:]
    customer_name = None
    if "--customer" in args:
        i = args.index("--customer")
        customer_name = args[i + 1]
    client = MEECClient()
    try:
        if cmd == "whoami":
            out = whoami(client)
        elif cmd == "customers":
            out = list_customers(client)
        elif cmd in ("patches", "patches-applicable"):
            if not customer_name:
                print("--customer <name> required", file=sys.stderr)
                return 2
            out = applicable_patches(customer_name, client)
        elif cmd == "patches-missing":
            if not customer_name:
                print("--customer <name> required", file=sys.stderr)
                return 2
            out = missing_patches(customer_name, client)
        elif cmd == "patches-installed":
            if not customer_name:
                print("--customer <name> required", file=sys.stderr)
                return 2
            out = installed_patches(customer_name, client)
        elif cmd == "systems-report":
            if not customer_name:
                print("--customer <name> required", file=sys.stderr)
                return 2
            out = system_patch_report(customer_name, client)
        else:
            print(f"unknown command: {cmd}", file=sys.stderr)
            return 2
    except requests.HTTPError as exc:
        print(f"HTTP {exc.response.status_code}: {exc.response.text[:500]}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
