"""Probe ManageEngine Endpoint Central MSP REST API surface.

EC MSP 11's actual surface is documented in the on-prem API Explorer
(``/APIExplorerServlet?action=showAPIExplorerPage``). This script GETs each
known path and prints a compact one-line summary, so you can quickly see
which endpoints work after an EC upgrade or while expanding the skill.

Usage:
    python probe_endpoints.py                    # curated list
    python probe_endpoints.py --customer AAVA    # also probe customer-scoped
    python probe_endpoints.py --paths a b c      # custom path list

Each line: ``OK / -- / XX  <status>  bytes=  rows=  /<path>``
``--`` means 404/405 (path not on this server). ``XX`` means error
(IAM0028 unsupported param, 10022 unsupported endpoint, etc.).
"""

from __future__ import annotations

import argparse
import sys

import me_ec_api as ec
import requests

# Verified working on EC MSP 11 (2026-05-02):
SERVER_PATHS: list[str] = [
    "api/1.4/desktop/customers",        # MSP customer enumeration
]

CUSTOMER_DCAPI_PATHS: list[str] = [
    "dcapi/threats/patches",            # all applicable patches
    "dcapi/threats/systemreport/patches",  # per-system patch matrix
]

# Paths that ME's general (non-MSP) API docs list but which return
# ``10022 API Endpoint is not supported by current server`` on this build.
# Kept here so the probe can prove they're still unsupported after upgrades.
KNOWN_UNSUPPORTED: list[str] = [
    "api/1.4/inventory/computers",
    "api/1.4/inventory/hardware",
    "api/1.4/inventory/software",
    "api/1.4/som/summary",
    "api/1.4/som/computers",
    "api/1.4/patch/allpatches",
    "api/1.4/patch/missingpatches",
    "api/1.4/patch/installedpatches",
    "api/1.4/patch/supportedpatches",
    "api/1.4/patch/systemreport",
]


def probe(client: ec.MEECClient, path: str, params: dict | None = None) -> None:
    url = f"{client.host}/{path.lstrip('/')}"
    try:
        r = client.session.get(url, params=params, verify=client.verify_tls, timeout=30)
    except requests.RequestException as exc:
        print(f"XX  ---  err={exc}  /{path}")
        return
    rows: int | str = "-"
    body_preview = ""
    try:
        body = r.json() if r.text else None
    except ValueError:
        body = None
    if r.ok and isinstance(body, dict):
        envelope = body.get("message_response") or body
        if isinstance(envelope, dict):
            for v in envelope.values():
                if isinstance(v, list):
                    rows = len(v)
                    break
        meta = body.get("metadata") or {}
        if "totalRecords" in meta:
            rows = f"{rows}/{meta['totalRecords']}"
    if not r.ok and isinstance(body, dict):
        ec_err = body.get("error_code") or body.get("errorCode") or "?"
        body_preview = f"  ec_err={ec_err}"
    flag = "OK" if r.ok else ("--" if r.status_code in (404, 405) else "XX")
    print(f"{flag}  {r.status_code}  bytes={len(r.content)}  rows={rows}  /{path}{body_preview}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--customer", help="Probe customer-scoped /dcapi paths with customername=<NAME>")
    ap.add_argument("--paths", nargs="*", help="Override the default path list")
    ap.add_argument(
        "--include-unsupported",
        action="store_true",
        help="Also probe known-unsupported paths (regression check)",
    )
    args = ap.parse_args(argv)

    client = ec.MEECClient()
    print(f"== probing {client.host} ==")

    if args.paths:
        for p in args.paths:
            probe(client, p)
        return 0

    print("\n-- server-scope --")
    for p in SERVER_PATHS:
        probe(client, p)

    if args.customer:
        print(f"\n-- customer-scope (customername={args.customer}) --")
        for p in CUSTOMER_DCAPI_PATHS:
            probe(client, p, params={"customername": args.customer, "pageLimit": 2})
    else:
        print("\n-- customer-scope (no --customer set, will hit 'Customer ID Mandatory') --")
        for p in CUSTOMER_DCAPI_PATHS:
            probe(client, p, params={"pageLimit": 2})

    if args.include_unsupported:
        print("\n-- known-unsupported (regression check) --")
        for p in KNOWN_UNSUPPORTED:
            probe(client, p)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
