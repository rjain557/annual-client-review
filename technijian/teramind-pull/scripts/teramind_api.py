"""
Teramind on-premise REST API client.

Auth: X-Access-Token header (opaque SHA-1 token).
Base URL: https://<host>/tm-api/

Reads credentials from:
  1. TERAMIND_HOST / TERAMIND_ACCESS_TOKEN env vars (headless / CI)
  2. Fallback: %USERPROFILE%\\OneDrive - Technijian, Inc\\Documents\\VSCODE\\keys\\teramind.md
"""

import os
import re
import json
import time
import urllib.request
import urllib.error
import ssl
from datetime import datetime, timezone

# ── defaults ────────────────────────────────────────────────────────────────

KEYFILE_REL = r"OneDrive - Technijian, Inc\Documents\VSCODE\keys\teramind.md"

# Teramind uses Unix-second timestamps; its ceiling is ~2049
MAX_TS = 2521843200  # 2049-11-12 in seconds


# ── credential loader ────────────────────────────────────────────────────────

def _read_keyfile():
    kf = os.path.join(os.environ.get("USERPROFILE", ""), KEYFILE_REL)
    if not os.path.isfile(kf):
        raise FileNotFoundError(f"Teramind keyfile not found: {kf}")
    text = open(kf, encoding="utf-8").read()
    host  = re.search(r"\*\*Base URL:\*\*\s*`(https?://[^`]+)`", text, re.IGNORECASE)
    token = re.search(r"\*\*Access Token:\*\*\s*`([0-9a-f]{32,64})`", text, re.IGNORECASE)
    if not host:
        raise ValueError("keyfile: **Base URL:** `https://...` not found")
    if not token:
        raise ValueError("keyfile: **Access Token:** `<hex>` not found")
    return host.group(1).rstrip("/"), token.group(1)


def get_credentials():
    host  = os.environ.get("TERAMIND_HOST")
    token = os.environ.get("TERAMIND_ACCESS_TOKEN")
    if host and token:
        return host.rstrip("/"), token
    return _read_keyfile()


# ── SSL context (on-premise self-signed certs are common) ───────────────────

def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


_CTX = _ssl_ctx()


# ── low-level request ────────────────────────────────────────────────────────

def _request(method, url, token, data=None, retries=2):
    headers = {
        "X-Access-Token": token,
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    last_exc = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, context=_CTX, timeout=30) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            body_err = e.read().decode()[:500]
            if e.code == 429:
                wait = 60
                print(f"  [teramind] 429 rate-limit — waiting {wait}s (attempt {attempt+1})")
                time.sleep(wait)
                last_exc = e
                continue
            raise RuntimeError(f"HTTP {e.code} from {url}: {body_err}") from e
        except Exception as e:
            last_exc = e
            if attempt < retries:
                time.sleep(5)
                continue
            raise
    raise last_exc


# ── high-level client class ──────────────────────────────────────────────────

class TeramindClient:
    """Stateless wrapper around the Teramind on-premise REST API."""

    def __init__(self, host=None, token=None):
        if host and token:
            self.host, self.token = host.rstrip("/"), token
        else:
            self.host, self.token = get_credentials()
        self._base = self.host + "/tm-api"

    def _get(self, path, params=None):
        url = self._base + path
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            url += ("?" if "?" not in url else "&") + qs
        return _request("GET", url, self.token)

    def _post(self, path, data):
        return _request("POST", self._base + path, self.token, data=data)

    # ── account / org ────────────────────────────────────────────────────────

    def get_account(self):
        return self._get("/account/")

    # ── agents (employees / monitored users) ────────────────────────────────

    def list_agents(self, include_deleted=False):
        agents = self._get("/agent/")
        if not include_deleted:
            agents = [a for a in agents if not a.get("deleted")]
        return agents

    def get_agent(self, agent_id):
        return self._get(f"/agent/{agent_id}")

    # ── computers ────────────────────────────────────────────────────────────

    def list_computers(self, include_deleted=False):
        computers = self._get("/computer/")
        if not include_deleted:
            computers = [c for c in computers if not c.get("is_deleted")]
        return computers

    # ── departments / groups ─────────────────────────────────────────────────

    def list_departments(self):
        return self._get("/department/")

    def list_groups(self):
        return self._get("/group/")

    # ── DLP / behavior ───────────────────────────────────────────────────────

    def list_behavior_groups(self):
        return self._get("/behavior-group/")

    def list_behavior_policies(self):
        return self._get("/behavior-policy/")

    # ── roles ────────────────────────────────────────────────────────────────

    def list_roles(self):
        return self._get("/access-control/roles/")

    # ── per-agent insider-threat / risk score ────────────────────────────────

    def get_risk_score(self, agent_id, start_ts, end_ts):
        """start_ts / end_ts: Unix seconds (≤ MAX_TS)."""
        return self._get("/persona/insider-threat/risk-score", {
            "start": int(start_ts), "end": int(end_ts), "agentId": agent_id,
        })

    def get_agent_details(self, agent_id, start_ts, end_ts):
        return self._get("/persona/insider-threat/details", {
            "start": int(start_ts), "end": int(end_ts), "agentId": agent_id,
        })

    def get_last_devices(self, agent_id, start_ts, end_ts):
        return self._get("/persona/insider-threat/last-devices", {
            "start": int(start_ts), "end": int(end_ts), "agentId": agent_id,
        })

    def get_last_locations(self, agent_id, start_ts, end_ts):
        return self._get("/persona/insider-threat/last-locations", {
            "start": int(start_ts), "end": int(end_ts), "agentId": agent_id,
        })

    # ── activity cube query ──────────────────────────────────────────────────
    # Valid cube names: activity, alerts, cli, file_transfers, keystrokes,
    #                   sessions, emails, sm, searches, printing
    # time dimension: [{"dimension": "time", "dateRange": [iso_start, iso_end]}]

    # Verified valid cube names for this on-premise installation (2026-04-29).
    # Other cubes from the SaaS docs (sessions, alerts, file_transfers, emails,
    # cli, printing, searches) return "unknown cube" on this server — either not
    # licensed or not yet configured. Expand this list when new modules are
    # activated; probe with query_cube() and check for a non-"unknown" response.
    CUBE_NAMES = [
        "activity",       # general app + productivity activity
        "keystrokes",     # keystroke log
        "web_search",     # web search queries
        "social_media",   # social media activity
    ]

    def query_cube(self, cube_name, start_ts, end_ts, dims=None, measures=None,
                   dim_filters=None, offset=0, limit=500):
        """Query a Teramind BI cube.

        start_ts / end_ts: Unix seconds.
        Returns the raw list of result rows.
        """
        from datetime import datetime, timezone

        def to_iso(ts):
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.000Z"
            )

        payload = {
            "cube": [cube_name],
            "timezone": "America/Los_Angeles",
            "time_format": 0,
            "aggregate": True,
            "dims": dims or [],
            "measures": measures or ["count"],
            "data_filters": {
                "time": [{"dimension": "time",
                          "dateRange": [to_iso(start_ts), to_iso(end_ts)]}]
            },
            "dim_filters": dim_filters or {},
            "offset": offset,
            "limit": limit,
            "meta": {},
        }
        return self._post("/wip/tma-query", payload)

    def query_cube_all(self, cube_name, start_ts, end_ts, dims=None, page=500):
        """Paginate through all rows of a cube query."""
        results = []
        offset = 0
        while True:
            batch = self.query_cube(
                cube_name, start_ts, end_ts,
                dims=dims, offset=offset, limit=page,
            )
            if not isinstance(batch, list) or not batch:
                break
            results.extend(batch)
            if len(batch) < page:
                break
            offset += page
        return results


# ── module-level convenience (reads credentials once) ───────────────────────

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = TeramindClient()
    return _client


def get_account():
    return _get_client().get_account()


def list_agents(**kw):
    return _get_client().list_agents(**kw)
