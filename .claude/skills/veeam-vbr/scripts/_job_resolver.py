"""Resolve a Veeam VBR job (name or id) to a clients/<code>/ folder.

Resolution order:
1. `manual` override in `state/veeam-vbr-job-mapping.json` keyed by job id OR job name.
2. `ignore` list in the same file (returns None and marks ignored).
3. Regex-extracted leading uppercase token from the job name, lowercased,
   matched against the live `clients/<code>/` directory list (skipping
   `_`-prefixed cross-org folders).
4. None (caller routes to `unmapped.json`).

Mirrors the Meraki `_org_mapping.py` + Huntress JSON-state pattern.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, Tuple

# ----------------------------------------------------------------------
# repo paths
THIS_FILE = Path(__file__).resolve()
SKILL_ROOT = THIS_FILE.parents[1]                       # .../skills/veeam-vbr
MAPPING_PATH = SKILL_ROOT / "state" / "veeam-vbr-job-mapping.json"

# .../skills/veeam-vbr/scripts/_job_resolver.py
# parents: 0=scripts, 1=veeam-vbr, 2=skills, 3=.claude, 4=annual-client-review-1
REPO_ROOT = THIS_FILE.parents[4]
CLIENTS_DIR = REPO_ROOT / "clients"

LEADING_TOKEN_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]+)")
# Split on whitespace, `-`, `_` to enumerate candidate code tokens.
TOKEN_SPLIT_RE = re.compile(r"[\s_\-]+")


def _load_mapping(path: Path = MAPPING_PATH) -> dict:
    if not path.exists():
        return {"manual": {}, "ignore": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _active_client_codes(clients_dir: Path = CLIENTS_DIR) -> set[str]:
    """Lowercase set of active client folder names (skip `_*` cross-org dirs)."""
    if not clients_dir.exists():
        return set()
    return {
        p.name.lower()
        for p in clients_dir.iterdir()
        if p.is_dir() and not p.name.startswith("_")
    }


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def resolve_client(
    job_name: str,
    job_id: Optional[str] = None,
    *,
    mapping: Optional[dict] = None,
    clients_dir: Path = CLIENTS_DIR,
) -> Tuple[Optional[str], str]:
    """Return (client_code_or_None, resolution_reason).

    `resolution_reason` is one of:
        "manual:<key>"  — matched a manual override
        "ignore:<key>"  — explicitly ignored
        "prefix:<TOKEN>"— matched leading uppercase token
        "unmapped"      — no rule matched
    """
    m = mapping if mapping is not None else _load_mapping()
    manual = {_norm(k): v for k, v in (m.get("manual") or {}).items()}
    ignore = {_norm(k) for k in (m.get("ignore") or [])}

    # 1. manual by id or full name
    for key in (job_id, job_name):
        if key and _norm(key) in manual:
            return manual[_norm(key)], f"manual:{key}"

    # 2. ignore list
    for key in (job_id, job_name):
        if key and _norm(key) in ignore:
            return None, f"ignore:{key}"

    # 3. tokens vs active clients - bias toward leading token, then any token.
    # Non-leading tokens must be ALL-CAPS (optionally with digits) to count -
    # this avoids English words like "for", "the", "Linux" colliding with real
    # client codes. The leading token is allowed to be mixed-case ("Technijian").
    if job_name:
        actives = _active_client_codes(clients_dir)
        tokens = [t for t in TOKEN_SPLIT_RE.split(job_name.strip()) if t]
        for idx, raw in enumerate(tokens):
            is_leading = idx == 0
            if not is_leading:
                # require all-caps (digits + _ allowed); skip mixed-case words
                core = raw.replace("_", "")
                if not core or not core.isupper() or not core[0].isalpha():
                    continue
            code = raw.lower().rstrip("-_")
            if code in actives:
                tag = "prefix" if is_leading else "token"
                return code, f"{tag}:{raw}"
            for n in range(min(12, len(code)), 1, -1):
                cand = code[:n]
                if cand in actives:
                    tag = "prefix" if is_leading else "token"
                    return cand, f"{tag}:{cand.upper()}"

    return None, "unmapped"


# ---- CLI: dry-run a list of job names from stdin or args -----------------
if __name__ == "__main__":
    import sys

    names = sys.argv[1:] or [line.strip() for line in sys.stdin if line.strip()]
    if not names:
        print("usage: python _job_resolver.py 'Backup Job - BWH-DC01' ['VAF-Hyper-V' ...]", file=sys.stderr)
        sys.exit(2)
    for n in names:
        code, reason = resolve_client(n)
        print(f"{n!r:50}  ->  {code or '<unmapped>':12}  ({reason})")
