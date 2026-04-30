#!/usr/bin/env python
"""
Pax8 MCP launcher.

Reads the Pax8 MCP token from the OneDrive keyvault at
`%USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/pax8.md`,
then execs `npx supergateway` with the `x-pax8-mcp-token` header so that
Claude Code (or any other MCP client) can attach over stdio.

Same keyvault-read pattern as `huntress_api.get_credentials()`,
`meraki_api.get_api_key()`, and `cs_api.get_credentials()`. No secret in
this file or in `~/.claude/settings.json` — the secret stays in the
OneDrive vault.

Env-var override: PAX8_MCP_TOKEN.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

NPX_CMD = r"C:\Program Files\nodejs\npx.cmd"
MCP_URL = "https://mcp.pax8.com/v1/mcp"


def _read_keyvault_token() -> str | None:
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    path = Path(home) / "OneDrive - Technijian, Inc" / "Documents" / "VSCODE" / "keys" / "pax8.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"\*\*MCP Token:\*\*\s*(\S+)", text)
    if not m:
        return None
    token = m.group(1)
    if token.startswith("TODO"):
        return None
    return token


def _get_token() -> str:
    env_tok = os.environ.get("PAX8_MCP_TOKEN")
    if env_tok:
        return env_tok
    tok = _read_keyvault_token()
    if tok:
        return tok
    print(
        "[pax8-mcp] Pax8 MCP token not found. Set PAX8_MCP_TOKEN env var OR populate the "
        "**MCP Token:** line in %USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/pax8.md",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> int:
    token = _get_token()
    cmd = [
        NPX_CMD,
        "-y",
        "supergateway",
        "--header",
        f"x-pax8-mcp-token:{token}",
        "--streamableHttp",
        MCP_URL,
    ]
    proc = subprocess.run(cmd, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
