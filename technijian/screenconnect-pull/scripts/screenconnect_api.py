"""Technijian ScreenConnect (ConnectWise Control) web API helper.

Base URL: https://myremote.technijian.com

Auth:
    Forms-auth via Services/SecurityTokenService.ashx.
    Succeeds silently (302 redirect to /) or returns 200 with error JSON.
    The .ASPXAUTH cookie is stored in an http.cookiejar and sent on every
    subsequent request. Token TTL is ~2h; re-auth is handled automatically.

Session data (two complementary sources):
    /Api/v1/Host   — REST API (ConnectWise Control 19+). Returns sessions
                     with rich metadata: SubType, CreatedTime, LastActivityTime,
                     GuestConnected, RecordingRequested, RecordingEnabled, etc.
    Services/PageService.ashx/GetSessionDetails
                   — Internal WebMethod, works on older versions.

Recordings:
    The Recording extension (if installed) exposes:
      GET /App_Extensions/{ext-guid}/Service.ashx/GetSessionRecordings
          ?SessionID={session-guid}
    and a download URL:
      GET /App_Extensions/{ext-guid}/Service.ashx/GetRecording
          ?SessionID={session-guid}&Index=0
    The extension GUID is discovered via /App_Extensions (see below).

    If the Recording extension is not installed, .crv files are on the
    filesystem at App_Data/Session Recordings/<YYYY>/<MM>/<guid>.crv — use
    the SQL-based pull to get the physical path and copy via UNC share.

Pagination:
    /Api/v1/Host supports ?offset=N&limit=M (max 200 per page).

Credentials:
    Resolution order: env vars SC_WEB_URL / SC_WEB_USER / SC_WEB_PASSWORD,
    then keyfile at %USERPROFILE%\\OneDrive - Technijian, Inc\\Documents\\
    VSCODE\\keys\\screenconnect-web.md.

Usage:
    from screenconnect_api import get_account, list_sessions, download_crv
    print(get_account())                    # smoke-test auth
    sessions = list_sessions(since="24h")
    for s in sessions:
        for rec in get_recordings(s["SessionID"]):
            download_crv(rec["DownloadUrl"], Path("C:/converted") / f"{s['SessionID']}.crv")
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import ssl
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin, quote
from urllib.request import (Request, OpenerDirector, HTTPCookieProcessor,
                             HTTPSHandler, HTTPRedirectHandler, build_opener,
                             urlopen)

# Allow self-signed/IP-based SSL for internal SC server. The cert is issued for
# myremote.technijian.com; when accessing via IP (10.100.14.10) hostname check fails.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# Put scripts dir on path so _sc_secrets resolves
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sc_secrets import get_sc_web_credentials  # noqa: E402

DEFAULT_TIMEOUT = 60
DOWNLOAD_CHUNK = 1024 * 1024  # 1 MiB chunks for .crv streaming
API_PAGE_LIMIT = 200

# ---------------------------------------------------------------------------
# Internal session state (module-level; one auth cookie per process)
# ---------------------------------------------------------------------------

_opener: Optional[OpenerDirector] = None
_base_url: str = ""
_auth_expires: float = 0.0
_AUTH_TTL = 90 * 60  # 90 minutes — SC sessions are 2h, renew with margin


def _get_opener() -> tuple[OpenerDirector, str]:
    """Return (opener, base_url), authenticating if needed."""
    global _opener, _base_url, _auth_expires
    base_url, username, password = get_sc_web_credentials()
    if _opener is None or base_url != _base_url or time.time() > _auth_expires:
        _opener = _build_opener(base_url, username, password)
        _base_url = base_url
        _auth_expires = time.time() + _AUTH_TTL
    return _opener, _base_url


class _NoRedirect(HTTPRedirectHandler):
    """Don't follow redirects — we want the 302 status code from login."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _build_opener(base_url: str, username: str, password: str) -> OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar), HTTPSHandler(context=_SSL_CTX), _NoRedirect())
    body = urlencode({
        "CredentialType": "Password",
        "Email": username,
        "Password": password,
        "SessionType": "8",
        "Redirect": "",
    }).encode()
    req = Request(
        f"{base_url}/Services/SecurityTokenService.ashx",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Technijian-SCPull/1.0",
            "Host": "myremote.technijian.com",
        },
    )
    try:
        with opener.open(req, timeout=DEFAULT_TIMEOUT) as resp:
            body_text = resp.read().decode("utf-8", errors="replace")
            if '"Success":false' in body_text or '"success":false' in body_text:
                raise RuntimeError(
                    f"ScreenConnect login failed. Check credentials in "
                    f"screenconnect-web.md. Response: {body_text[:200]}"
                )
    except HTTPError as e:
        if e.code in (302, 303):
            pass  # expected: redirect after successful login
        else:
            raise RuntimeError(
                f"ScreenConnect auth HTTP {e.code}: {e.read()[:200]!r}"
            ) from e
    return opener


def _request(path: str, *, method: str = "GET",
              params: Optional[dict] = None,
              json_body: Any = None,
              stream: bool = False) -> Any:
    """Make an authenticated request; return parsed JSON or raw response."""
    opener, base_url = _get_opener()
    url = f"{base_url}/{path.lstrip('/')}"
    if params:
        url = f"{url}?{urlencode(params)}"
    data = None
    headers: dict[str, str] = {
        "User-Agent": "Technijian-SCPull/1.0",
        "Host": "myremote.technijian.com",
    }
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json; charset=utf-8"
        method = "POST"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        resp = opener.open(req, timeout=DEFAULT_TIMEOUT)
        if stream:
            return resp  # caller must close
        raw = resp.read()
        ct = resp.headers.get("Content-Type", "")
        if "json" in ct or raw.lstrip()[:1] in (b"{", b"["):
            return json.loads(raw)
        return raw.decode("utf-8", errors="replace")
    except HTTPError as e:
        body = e.read()[:300]
        raise RuntimeError(f"SC API {e.code} {url}: {body!r}") from e


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_account() -> dict:
    """Smoke-test: return basic info about this ScreenConnect instance."""
    try:
        result = _request("Api/v1/Host", params={"limit": 1})
        return {"ok": True, "api_version": "v1",
                "sample_count": len(result) if isinstance(result, list) else 1}
    except Exception:
        pass
    # Fallback: check the root page returns 200
    try:
        _request("")
        return {"ok": True, "api_version": "legacy"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def list_sessions(
    since: Optional[str | datetime] = None,
    session_type: Optional[int] = None,
    limit: int = 5000,
) -> list[dict]:
    """Return sessions from /Api/v1/Host.

    since: ISO datetime string, "24h", "7d", etc., or datetime object.
    session_type: 2 = Support, 1 = Access, 4 = Meeting (None = all).
    """
    since_dt = _parse_since(since)
    results: list[dict] = []
    offset = 0
    filters = []
    if session_type is not None:
        filters.append(f"SessionType+eq+{session_type}")
    if since_dt:
        ts = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        filters.append(f"LastActivityTime+gt+{quote(ts)}")
    filter_str = "+and+".join(filters) if filters else None

    while len(results) < limit:
        params: dict = {"offset": offset, "limit": min(API_PAGE_LIMIT, limit - len(results))}
        if filter_str:
            params["filter"] = filter_str
        try:
            page = _request("Api/v1/Host", params=params)
        except RuntimeError:
            break
        if not page:
            break
        results.extend(page if isinstance(page, list) else [page])
        if len(page) < API_PAGE_LIMIT:
            break
        offset += len(page)

    return results


def get_session(session_id: str) -> dict:
    """Return metadata for a single session."""
    result = _request(f"Api/v1/Host/{session_id}")
    return result if isinstance(result, dict) else result[0]


def get_session_events(session_id: str,
                       event_types: Optional[list[int]] = None) -> list[dict]:
    """Return events for a session from /Api/v1/HostSessionEvent.

    Common event type codes:
        1 = Connected, 2 = Disconnected, 3 = QueuedForAssignment,
        4 = End, 11 = ChatMessage, 14 = FileTransfer, 33 = RecordingStart,
        34 = RecordingEnd, 40 = RanCommand, 41 = ViewedFile.
    """
    params: dict = {"sessionFilter": f"SessionID+eq+{session_id}",
                    "limit": 5000}
    if event_types:
        params["eventTypeFilter"] = ",".join(str(e) for e in event_types)
    result = _request("Api/v1/HostSessionEvent", params=params)
    return result if isinstance(result, list) else []


# ---------------------------------------------------------------------------
# Recordings
# ---------------------------------------------------------------------------

_recording_ext_guid: Optional[str] = None


def _find_recording_extension() -> Optional[str]:
    """Return the Recording extension GUID or None if not installed."""
    global _recording_ext_guid
    if _recording_ext_guid is not None:
        return _recording_ext_guid
    try:
        exts = _request("App_Extensions")
        if isinstance(exts, str):
            import re
            match = re.search(
                r'"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"'
                r'[^}]*"[Rr]ecord', exts)
            if match:
                _recording_ext_guid = match.group(1)
                return _recording_ext_guid
    except Exception:
        pass

    # Try the known extension listing endpoint
    try:
        ext_list = _request("App_Extensions/list.ashx")
        if isinstance(ext_list, list):
            for ext in ext_list:
                if "record" in str(ext.get("Name", "")).lower():
                    _recording_ext_guid = ext.get("ID") or ext.get("GUID")
                    return _recording_ext_guid
    except Exception:
        pass
    return None


def get_recordings(session_id: str) -> list[dict]:
    """Return recording metadata for a session.

    Each item has at minimum: Index, FileName, FileSize, StartTime, EndTime,
    DownloadUrl (ready to pass to download_crv).
    """
    guid = _find_recording_extension()
    if not guid:
        return []
    try:
        result = _request(
            f"App_Extensions/{guid}/Service.ashx/GetSessionRecordings",
            params={"SessionID": session_id},
        )
        recordings = result if isinstance(result, list) else (result or [])
        for i, rec in enumerate(recordings):
            if "DownloadUrl" not in rec:
                rec["DownloadUrl"] = (
                    f"App_Extensions/{guid}/Service.ashx/GetRecording"
                    f"?SessionID={session_id}&Index={rec.get('Index', i)}"
                )
        return recordings
    except Exception:
        return []


def download_crv(url_or_path: str, dest: Path, *,
                 overwrite: bool = False) -> dict:
    """Stream a .crv recording to dest.

    url_or_path: relative path like 'App_Extensions/.../GetRecording?...'
                 or absolute https:// URL.
    Returns: {ok, dest, size_bytes, elapsed_seconds, error}
    """
    dest = Path(dest)
    if dest.exists() and not overwrite:
        return {"ok": True, "dest": str(dest),
                "size_bytes": dest.stat().st_size, "skipped": True}
    dest.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        resp = _request(url_or_path, stream=True)
        total = 0
        tmp = dest.with_suffix(".crv.tmp")
        with open(tmp, "wb") as f:
            while True:
                chunk = resp.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
        resp.close()
        tmp.rename(dest)
        return {"ok": True, "dest": str(dest),
                "size_bytes": total, "elapsed_seconds": round(time.time() - t0, 1)}
    except Exception as e:
        return {"ok": False, "dest": str(dest), "error": str(e)}


# ---------------------------------------------------------------------------
# Convenience: sessions-with-recordings (combines list_sessions + get_recordings)
# ---------------------------------------------------------------------------

def list_sessions_with_recordings(since: Optional[str | datetime] = None,
                                  session_type: Optional[int] = None) -> list[dict]:
    """Return sessions that have at least one recording.

    Each item is the session dict with an added 'Recordings' list.
    """
    sessions = list_sessions(since=since, session_type=session_type)
    result = []
    for s in sessions:
        sid = s.get("SessionID") or s.get("Code")
        if not sid:
            continue
        recs = get_recordings(sid)
        if recs:
            s["Recordings"] = recs
            result.append(s)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_since(since: Optional[str | datetime]) -> Optional[datetime]:
    if since is None:
        return None
    if isinstance(since, datetime):
        return since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    s = since.strip().lower()
    now = datetime.now(timezone.utc)
    if s.endswith("h"):
        return now - timedelta(hours=float(s[:-1]))
    if s.endswith("d"):
        return now - timedelta(days=float(s[:-1]))
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Authenticating to", get_sc_web_credentials()[0], "...")
    info = get_account()
    print("Account:", info)
    if not info.get("ok"):
        sys.exit(1)
    rec_guid = _find_recording_extension()
    print("Recording extension GUID:", rec_guid or "not found")
    sessions = list_sessions(since="24h")
    print(f"Sessions in last 24h: {len(sessions)}")
    sessions_with_recs = list_sessions_with_recordings(since="24h")
    print(f"Sessions with recordings: {len(sessions_with_recs)}")
    for s in sessions_with_recs[:3]:
        sid = s.get("SessionID") or s.get("Code")
        print(f"  {sid}  recs={len(s['Recordings'])}  "
              f"host={s.get('Host', {}).get('Name', '?')}")
