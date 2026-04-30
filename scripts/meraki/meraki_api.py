"""
Cisco Meraki Dashboard API helpers (multi-org / MSP).

Reusable module for:
  - Auth (Bearer token from the OneDrive key vault)
  - GET with pagination via the `Link: rel=next` header
  - 429 backoff (exponential, up to 4 retries)
  - 403 / 404 tolerance (returns None instead of raising; lets pullers
    skip dormant or feature-disabled networks without crashing the run)

Credentials are read from:
  1) env var MERAKI_API_KEY, else
  2) the key vault file at
     %USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/meraki.md
     (parsed for the first 40-hex-char token after `**API Key:**`)

Reference: https://developer.cisco.com/meraki/api-v1/
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

BASE_URL = "https://api.meraki.com/api/v1"
DEFAULT_TIMEOUT = 60
MAX_RETRIES = 4
USER_AGENT = "TechnijianMerakiPull/1.0"


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

_KEY_RE = re.compile(r"\*\*API Key:\*\*\s*([0-9a-fA-F]{40})")


def _read_keyvault_key() -> Optional[str]:
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    path = (Path(home) / "OneDrive - Technijian, Inc" / "Documents"
            / "VSCODE" / "keys" / "meraki.md")
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    m = _KEY_RE.search(text)
    return m.group(1) if m else None


def get_api_key() -> str:
    k = os.environ.get("MERAKI_API_KEY")
    if k:
        return k.strip()
    k = _read_keyvault_key()
    if k:
        return k
    raise RuntimeError(
        "Meraki API key not found. Set MERAKI_API_KEY or add it to "
        "keys/meraki.md under `**API Key:** <40 hex chars>`."
    )


def _auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {get_api_key()}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


# ---------------------------------------------------------------------------
# Low-level HTTP with retry
# ---------------------------------------------------------------------------

class MerakiError(Exception):
    def __init__(self, status: int, url: str, body: str):
        super().__init__(f"HTTP {status} on {url}: {body[:300]}")
        self.status = status
        self.url = url
        self.body = body


def _request(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> tuple[Any, dict]:
    """Single GET with 429/5xx retry. Returns (json_body, response_headers).
    Raises MerakiError on non-2xx after retries."""
    last_err: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        req = urlrequest.Request(url, headers=_auth_headers(), method="GET")
        try:
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                hdrs = dict(resp.headers.items())
                if not raw:
                    return None, hdrs
                return json.loads(raw), hdrs
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            if e.code == 429 and attempt < MAX_RETRIES:
                # Honor Retry-After if present, else exponential backoff.
                retry_after = e.headers.get("Retry-After") if e.headers else None
                delay = float(retry_after) if retry_after else (2 ** attempt)
                time.sleep(min(delay, 30))
                last_err = e
                continue
            if 500 <= e.code < 600 and attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                last_err = e
                continue
            raise MerakiError(e.code, url, body)
        except URLError as e:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                last_err = e
                continue
            raise MerakiError(0, url, str(e))
    if last_err:
        raise MerakiError(0, url, str(last_err))
    raise MerakiError(0, url, "exhausted retries")


def _next_link(headers: dict) -> Optional[str]:
    link = headers.get("Link") or headers.get("link")
    if not link:
        return None
    # Format: <url1>; rel=first, <url2>; rel=next, <url3>; rel=last
    for part in link.split(","):
        part = part.strip()
        if 'rel=next' in part or 'rel="next"' in part:
            m = re.match(r"<([^>]+)>", part)
            if m:
                return m.group(1)
    return None


def get(path: str, params: Optional[dict] = None,
        *, allow_404: bool = True, allow_403: bool = True) -> Any:
    """Single GET (no pagination). Returns parsed JSON, or None on 403/404
    when allowed (default). Raises MerakiError otherwise."""
    url = path if path.startswith("http") else BASE_URL + path
    if params:
        # Drop None values
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url = f"{url}?{urlencode(clean, doseq=True)}"
    try:
        body, _ = _request(url)
        return body
    except MerakiError as e:
        if e.status == 404 and allow_404:
            return None
        if e.status == 403 and allow_403:
            return None
        raise


def get_paginated(path: str, params: Optional[dict] = None,
                  *, allow_404: bool = True, allow_403: bool = True,
                  per_page_default: int = 1000,
                  max_pages: int = 200) -> list:
    """GET that follows Link: rel=next pagination. Aggregates list-typed
    responses into a single list. Returns [] on tolerated 403/404."""
    url = path if path.startswith("http") else BASE_URL + path
    p = dict(params or {})
    p.setdefault("perPage", per_page_default)
    if p:
        clean = {k: v for k, v in p.items() if v is not None}
        if clean:
            url = f"{url}?{urlencode(clean, doseq=True)}"
    out: list = []
    pages = 0
    while url and pages < max_pages:
        try:
            body, hdrs = _request(url)
        except MerakiError as e:
            if e.status == 404 and allow_404:
                return out
            if e.status == 403 and allow_403:
                return out
            raise
        if isinstance(body, list):
            out.extend(body)
        elif body is not None:
            # Non-list response on a pagination-style endpoint — return as-is.
            return body
        url = _next_link(hdrs)
        pages += 1
    return out


# ---------------------------------------------------------------------------
# Domain helpers (thin wrappers — pullers add the workflow on top)
# ---------------------------------------------------------------------------

def whoami() -> dict:
    """GET /administered/identities/me -> {name, email, lastUsedDashboardAt, authentication}"""
    return get("/administered/identities/me")


def list_organizations() -> list[dict]:
    return get_paginated("/organizations") or []


def list_networks(org_id: str) -> list[dict]:
    return get_paginated(f"/organizations/{org_id}/networks") or []


def list_devices(org_id: str) -> list[dict]:
    return get_paginated(f"/organizations/{org_id}/devices") or []


def get_security_events_org(org_id: str, *, t0: Optional[str] = None,
                            t1: Optional[str] = None,
                            timespan: Optional[int] = None,
                            per_page: int = 1000) -> list[dict]:
    """GET /organizations/{id}/appliance/security/events — IDS/IPS + AMP events.

    Provide either (t0,t1) ISO timestamps or `timespan` in seconds (max 31 days).
    """
    params: dict[str, Any] = {"perPage": per_page}
    if timespan is not None:
        params["timespan"] = timespan
    else:
        if t0:
            params["t0"] = t0
        if t1:
            params["t1"] = t1
    return get_paginated(
        f"/organizations/{org_id}/appliance/security/events",
        params,
        per_page_default=per_page,
    ) or []


def get_network_events(network_id: str, *, product_type: str = "appliance",
                       t0: Optional[str] = None, t1: Optional[str] = None,
                       timespan: Optional[int] = None,
                       per_page: int = 1000,
                       max_pages: int = 50) -> list[dict]:
    """GET /networks/{id}/events — firewall / VPN / DHCP activity log.

    NOTE: This endpoint does NOT accept t0/t1/timespan parameters — it
    paginates strictly via the `startingAfter` / `endingBefore` cursors
    in the response's `pageStartAt` / `pageEndAt` timestamps. We walk
    backward from the most recent page using `endingBefore=pageStartAt`
    until we drop out of the requested window.

    If t0/t1 are supplied, the result is filtered client-side to that
    window. If only timespan is given, t1=now and t0=now-timespan.
    """
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    # Resolve window
    now = _dt.now(_tz.utc)
    if timespan is not None and not (t0 or t1):
        t1_dt = now
        t0_dt = now - _td(seconds=timespan)
    else:
        t0_dt = _dt.fromisoformat(t0.replace("Z", "+00:00")) if t0 else None
        t1_dt = _dt.fromisoformat(t1.replace("Z", "+00:00")) if t1 else None

    base_params: dict[str, Any] = {
        "productType": product_type,
        "perPage": per_page,
    }
    out: list[dict] = []
    ending_before: Optional[str] = None  # ISO timestamp cursor
    for _ in range(max_pages):
        params = dict(base_params)
        if ending_before:
            params["endingBefore"] = ending_before
        body = get(f"/networks/{network_id}/events", params)
        if not body:
            break
        events = body.get("events", []) if isinstance(body, dict) else []
        if not events:
            break

        # Filter to window if specified
        if t0_dt or t1_dt:
            kept = []
            for ev in events:
                occ = ev.get("occurredAt")
                if not occ:
                    continue
                try:
                    occ_dt = _dt.fromisoformat(occ.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if t0_dt and occ_dt < t0_dt:
                    continue
                if t1_dt and occ_dt > t1_dt:
                    continue
                kept.append(ev)
            out.extend(kept)
            # If the OLDEST event on this page is already before t0, we've
            # walked past the window — stop.
            if t0_dt:
                oldest = events[-1].get("occurredAt")
                if oldest:
                    try:
                        oldest_dt = _dt.fromisoformat(oldest.replace("Z", "+00:00"))
                        if oldest_dt < t0_dt:
                            break
                    except ValueError:
                        pass
        else:
            out.extend(events)

        next_cursor = body.get("pageStartAt") if isinstance(body, dict) else None
        if not next_cursor or next_cursor == ending_before:
            break
        ending_before = next_cursor
    return out


# ---------------------------------------------------------------------------
# Configuration snapshot helpers
# ---------------------------------------------------------------------------

# (path_template, output_filename, applies_when_predicate)
# predicate takes the network dict; None = always try.
APPLIANCE_CONFIG_ENDPOINTS = [
    ("/networks/{nid}/appliance/firewall/l3FirewallRules",        "firewall_l3.json"),
    ("/networks/{nid}/appliance/firewall/l7FirewallRules",        "firewall_l7.json"),
    ("/networks/{nid}/appliance/firewall/inboundFirewallRules",   "firewall_inbound.json"),
    ("/networks/{nid}/appliance/firewall/cellularFirewallRules",  "firewall_cellular.json"),
    ("/networks/{nid}/appliance/firewall/portForwardingRules",    "firewall_port_forwarding.json"),
    ("/networks/{nid}/appliance/firewall/oneToOneNatRules",       "firewall_1to1_nat.json"),
    ("/networks/{nid}/appliance/firewall/oneToManyNatRules",      "firewall_1tomany_nat.json"),
    ("/networks/{nid}/appliance/security/intrusion",              "security_intrusion.json"),
    ("/networks/{nid}/appliance/security/malware",                "security_malware.json"),
    ("/networks/{nid}/appliance/contentFiltering",                "content_filtering.json"),
    ("/networks/{nid}/appliance/trafficShaping",                  "traffic_shaping.json"),
    ("/networks/{nid}/appliance/trafficShaping/rules",            "traffic_shaping_rules.json"),
    ("/networks/{nid}/appliance/trafficShaping/uplinkBandwidth",  "traffic_shaping_uplink_bw.json"),
    ("/networks/{nid}/appliance/vlans",                           "vlans.json"),
    ("/networks/{nid}/appliance/vpn/siteToSiteVpn",               "vpn_s2s.json"),
    ("/networks/{nid}/appliance/staticRoutes",                    "static_routes.json"),
    ("/networks/{nid}/appliance/ports",                           "appliance_ports.json"),
    ("/networks/{nid}/appliance/settings",                        "appliance_settings.json"),
]

WIRELESS_CONFIG_ENDPOINTS = [
    ("/networks/{nid}/wireless/ssids",                            "wireless_ssids.json"),
    ("/networks/{nid}/wireless/settings",                         "wireless_settings.json"),
    ("/networks/{nid}/wireless/rfProfiles",                       "wireless_rf_profiles.json"),
]

SWITCH_CONFIG_ENDPOINTS = [
    ("/networks/{nid}/switch/accessPolicies",                     "switch_access_policies.json"),
    ("/networks/{nid}/switch/qosRules",                           "switch_qos_rules.json"),
    ("/networks/{nid}/switch/portSchedules",                      "switch_port_schedules.json"),
    ("/networks/{nid}/switch/settings",                           "switch_settings.json"),
]

NETWORK_WIDE_CONFIG_ENDPOINTS = [
    ("/networks/{nid}/syslogServers",                             "syslog_servers.json"),
    ("/networks/{nid}/snmp",                                      "snmp.json"),
    ("/networks/{nid}/alerts/settings",                           "alerts_settings.json"),
    ("/networks/{nid}/groupPolicies",                             "group_policies.json"),
    ("/networks/{nid}/floorPlans",                                "floor_plans.json"),
    ("/networks/{nid}/webhooks/httpServers",                      "webhooks_http_servers.json"),
]


def get_configuration_changes(org_id: str, *, t0: Optional[str] = None,
                              t1: Optional[str] = None,
                              timespan: Optional[int] = None,
                              per_page: int = 1000) -> list[dict]:
    """GET /organizations/{id}/configurationChanges — admin change audit log.

    Returns every configuration change made via Dashboard, API, or mobile app
    within the requested window. Fields per record:
      ts, adminName, adminEmail, networkId, networkName, page, label,
      oldValue, newValue
    """
    params: dict[str, Any] = {"perPage": per_page}
    if timespan is not None:
        params["timespan"] = timespan
    else:
        if t0:
            params["t0"] = t0
        if t1:
            params["t1"] = t1
    return get_paginated(
        f"/organizations/{org_id}/configurationChanges",
        params,
        per_page_default=per_page,
    ) or []


def network_has_product(network: dict, product: str) -> bool:
    pts = network.get("productTypes") or []
    return product in pts


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return s or "unknown"


__all__ = [
    "BASE_URL",
    "MerakiError",
    "get_api_key",
    "get",
    "get_paginated",
    "whoami",
    "list_organizations",
    "list_networks",
    "list_devices",
    "get_security_events_org",
    "get_network_events",
    "get_configuration_changes",
    "APPLIANCE_CONFIG_ENDPOINTS",
    "WIRELESS_CONFIG_ENDPOINTS",
    "SWITCH_CONFIG_ENDPOINTS",
    "NETWORK_WIDE_CONFIG_ENDPOINTS",
    "network_has_product",
    "slugify",
]
