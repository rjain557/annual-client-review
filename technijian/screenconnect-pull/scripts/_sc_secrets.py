"""Secrets loader for the ScreenConnect pull pipeline.

Teams / SharePoint uploads use the Teams-Connector Azure AD app
(app reg: 'Teams-Connector'), which has Files.ReadWrite.All,
Sites.ReadWrite.All, Group.Read.All, TeamMember.Read.All.

The SQL Server connection string for the ScreenConnect database is read
from a separate keyfile and exposed as MSSQL_CONNECTION_STRING for the
mssql MCP server, or used directly by any script that needs a raw connection.

Resolution order for both sets of credentials:
  1) environment variables
  2) keyfile in OneDrive vault
  3) RuntimeError with a clear message

This module is safe to commit — it contains no secrets.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_KEYS_DIR = Path(r"C:\Users\rjain\OneDrive - Technijian, Inc\Documents\VSCODE\keys")


# ---------------------------------------------------------------------------
# Teams-Connector (for Graph / Teams file uploads)
# ---------------------------------------------------------------------------

def get_teams_credentials() -> tuple[str, str, str]:
    """Return (tenant_id, client_id, client_secret) for the Teams-Connector app."""
    tenant = os.environ.get("TEAMS_TENANT_ID")
    cid    = os.environ.get("TEAMS_CLIENT_ID")
    secret = os.environ.get("TEAMS_CLIENT_SECRET")

    if not all([tenant, cid, secret]):
        kf = _KEYS_DIR / "teams-connector.md"
        if kf.exists():
            text = kf.read_text(encoding="utf-8")
            tenant = tenant or _parse(text, "Tenant ID")
            cid    = cid    or _parse(text, "App Client ID")
            secret = secret or _parse(text, "Client Secret")

    missing = [k for k, v in
               [("TEAMS_TENANT_ID", tenant), ("TEAMS_CLIENT_ID", cid),
                ("TEAMS_CLIENT_SECRET", secret)] if not v]
    if missing:
        raise RuntimeError(
            f"Teams-Connector credentials missing: {missing}. "
            f"Set env vars or ensure {_KEYS_DIR / 'teams-connector.md'} exists."
        )
    return str(tenant), str(cid), str(secret)


# ---------------------------------------------------------------------------
# ScreenConnect Web (myremote.technijian.com)
# ---------------------------------------------------------------------------

def get_sc_web_credentials() -> tuple[str, str, str]:
    """Return (base_url, username, password) for the ScreenConnect web interface."""
    url  = os.environ.get("SC_WEB_URL")
    user = os.environ.get("SC_WEB_USER")
    pw   = os.environ.get("SC_WEB_PASSWORD")

    if not all([url, user, pw]):
        kf = _KEYS_DIR / "screenconnect-web.md"
        if kf.exists():
            text = kf.read_text(encoding="utf-8")
            url  = url  or _parse(text, "URL")
            user = user or _parse(text, "Username")
            pw   = pw   or _parse(text, "Password")

    missing = [k for k, v in
               [("SC_WEB_URL", url), ("SC_WEB_USER", user),
                ("SC_WEB_PASSWORD", pw)] if not v or str(v).startswith("TODO")]
    if missing:
        raise RuntimeError(
            f"ScreenConnect web credentials missing: {missing}. "
            f"Set env vars or fill in {_KEYS_DIR / 'screenconnect-web.md'}."
        )
    return str(url).rstrip("/"), str(user), str(pw)


# ---------------------------------------------------------------------------
# ScreenConnect SQLite database path
# ---------------------------------------------------------------------------

def get_sc_db_path() -> str:
    """Return the file path to the ScreenConnect SQLite database.

    ScreenConnect stores all data in a single SQLite file (ScreenConnect.db),
    not a SQL Server instance. Resolution order:
      1) SC_DB_PATH env var
      2) **DB Path:** line in screenconnect-sql.md
      3) RuntimeError

    The path may be a local path (if running on TE-DC-MYRMT-01) or a UNC
    share path (e.g. \\\\10.100.14.10\\SCAppData\\ScreenConnect.db).
    """
    path = os.environ.get("SC_DB_PATH")
    if path:
        return path

    kf = _KEYS_DIR / "screenconnect-sql.md"
    if kf.exists():
        text = kf.read_text(encoding="utf-8")
        path = _parse(text, "DB Path")
        if path:
            return path

    raise RuntimeError(
        "ScreenConnect SQLite DB path not found. "
        "Set env var SC_DB_PATH, or add a '**DB Path:** ...' line to "
        f"{kf}. See technijian/screenconnect-pull/workstation.md."
    )


# ---------------------------------------------------------------------------
# Gemini API (for session video analysis)
# ---------------------------------------------------------------------------

def get_gemini_api_key() -> str | None:
    """Return the Gemini API key, or None if ADC should be used instead.

    Resolution order:
      1) GEMINI_API_KEY env var
      2) **API Key:** line in keys/gemini.md
      3) None → caller falls back to Application Default Credentials
    """
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    kf = _KEYS_DIR / "gemini.md"
    if kf.exists():
        text = kf.read_text(encoding="utf-8")
        val = _parse(text, "API Key")
        if val and not val.startswith("TODO"):
            return val
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse(text: str, label: str) -> str:
    m = re.search(rf"\*\*{re.escape(label)}:\*\*\s*([^\s\r\n]+)", text)
    return m.group(1).strip() if m else ""
