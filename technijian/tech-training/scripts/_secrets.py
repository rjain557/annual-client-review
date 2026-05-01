"""Load Microsoft Graph credentials without hard-coding the secret.

Resolution order:
  1. Environment variables: M365_TENANT_ID, M365_CLIENT_ID, M365_CLIENT_SECRET
  2. The user's key vault at:
     %USERPROFILE%\\OneDrive - Technijian, Inc\\Documents\\VSCODE\\keys\\m365-graph.md
     (parsed for `**App Client ID:**`, `**Tenant ID:**`, `**Client Secret:**`)
  3. ImportError if neither is available (do NOT fall back to a baked-in value)

This module is safe to commit. It contains no secrets.
"""
from __future__ import annotations
import os
import re
from pathlib import Path

KEY_FILE = Path(os.path.expandvars(r"%USERPROFILE%\OneDrive - Technijian, Inc\Documents\VSCODE\keys\m365-graph.md"))
DEFAULT_MAILBOX = "RJain@technijian.com"


def _from_keyfile() -> dict[str, str]:
    if not KEY_FILE.exists():
        return {}
    text = KEY_FILE.read_text(encoding="utf-8")
    out = {}
    for label, key in (("App Client ID", "client_id"),
                       ("Tenant ID", "tenant_id"),
                       ("Client Secret", "client_secret")):
        m = re.search(rf"\*\*{re.escape(label)}:\*\*\s*([^\s\r\n]+)", text)
        if m:
            out[key] = m.group(1).strip()
    return out


def get_m365_credentials() -> tuple[str, str, str, str]:
    """Return (tenant_id, client_id, client_secret, mailbox)."""
    env = {
        "tenant_id": os.environ.get("M365_TENANT_ID"),
        "client_id": os.environ.get("M365_CLIENT_ID"),
        "client_secret": os.environ.get("M365_CLIENT_SECRET"),
    }
    if all(env.values()):
        creds = env
    else:
        kf = _from_keyfile()
        creds = {k: env.get(k) or kf.get(k) for k in env}
    missing = [k for k, v in creds.items() if not v]
    if missing:
        raise RuntimeError(
            f"Missing M365 credentials: {missing}. "
            f"Set env vars (M365_TENANT_ID/M365_CLIENT_ID/M365_CLIENT_SECRET) "
            f"or ensure the key vault file exists at: {KEY_FILE}"
        )
    mailbox = os.environ.get("M365_MAILBOX") or DEFAULT_MAILBOX
    return creds["tenant_id"], creds["client_id"], creds["client_secret"], mailbox
