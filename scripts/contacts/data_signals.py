"""Derive the operational 'active managed-IT client this month' list from
per-client data folders.

Scope rule: this repo is for **managed-IT clients only** - the ones we
provide endpoint security (Huntress/CrowdStrike) or DNS security
(Umbrella) for. Clients that show up in the Client Portal with time
entries but have NO security tooling rolled out are SEO-only or
dev-only relationships managed in different repos. They are NOT
considered active for the purposes of this repo's monthly reports.

Signals we look for under `clients/<code>/`:

  cp           -> monthly/<YYYY-MM>/pull_summary.json with time_entry_count > 0
  huntress     -> huntress/monthly/<YYYY-MM>/ exists with files,
                  OR any huntress/<YYYY-MM>-DD/ folder in the month exists
  crowdstrike  -> same pattern under crowdstrike/
  umbrella     -> same pattern under umbrella/

A client is **active for this repo** if at least one of huntress /
crowdstrike / umbrella is set for the target month. The CP signal alone
is not sufficient - it just confirms there were tickets/time entries,
which is true even for SEO/dev-only relationships.

The monthly-pull cadence runs on the 1st covering the prior calendar
month, so the natural target month for a 'who do we send reports to' query
is one month before today.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DEFAULT_REPO = Path(__file__).resolve().parent.parent.parent
CLIENTS_DIRNAME = "clients"


@dataclass
class DataSignals:
    code: str
    cp: bool = False
    cp_time_entries: int = 0
    huntress: bool = False
    crowdstrike: bool = False
    umbrella: bool = False

    @property
    def has_security(self) -> bool:
        """At least one managed-IT security tooling signal."""
        return self.huntress or self.crowdstrike or self.umbrella

    @property
    def active(self) -> bool:
        """Active for this repo = managed-IT client with security tooling
        observed this month. CP-only clients (SEO/dev-only relationships)
        are not active here."""
        return self.has_security

    @property
    def cp_only(self) -> bool:
        """Had CP tickets this month but NO security tooling - signals an
        SEO or dev-only relationship that lives in a different repo."""
        return self.cp and not self.has_security

    @property
    def signals(self) -> list[str]:
        out = []
        if self.cp: out.append("cp")
        if self.huntress: out.append("huntress")
        if self.crowdstrike: out.append("crowdstrike")
        if self.umbrella: out.append("umbrella")
        return out


def prior_month(today: date | None = None) -> str:
    """YYYY-MM string for the calendar month BEFORE `today` (default = today)."""
    today = today or date.today()
    y, m = today.year, today.month
    if m == 1:
        return f"{y - 1:04d}-12"
    return f"{y:04d}-{m - 1:02d}"


def _has_cp_activity(client_dir: Path, ym: str) -> tuple[bool, int]:
    summary = client_dir / "monthly" / ym / "pull_summary.json"
    if not summary.exists():
        return False, 0
    try:
        data = json.loads(summary.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, 0
    n = int(data.get("time_entry_count") or 0)
    return n > 0, n


def _has_subdir_activity(client_dir: Path, kind: str, ym: str) -> bool:
    """True if `clients/<code>/<kind>/monthly/<YYYY-MM>/` exists with at least
    one file, OR any `clients/<code>/<kind>/<YYYY-MM>-DD/` per-day folder
    exists with at least one file (covers daily pulls before any monthly
    aggregation runs)."""
    base = client_dir / kind
    if not base.exists():
        return False
    monthly = base / "monthly" / ym
    if monthly.exists() and any(monthly.iterdir()):
        return True
    for d in base.iterdir():
        if not d.is_dir():
            continue
        if d.name.startswith(ym + "-") and any(d.iterdir()):
            return True
    return False


def signals_for_client(client_dir: Path, ym: str) -> DataSignals:
    code = client_dir.name.upper()
    cp_ok, cp_count = _has_cp_activity(client_dir, ym)
    return DataSignals(
        code=code,
        cp=cp_ok, cp_time_entries=cp_count,
        huntress=_has_subdir_activity(client_dir, "huntress", ym),
        crowdstrike=_has_subdir_activity(client_dir, "crowdstrike", ym),
        umbrella=_has_subdir_activity(client_dir, "umbrella", ym),
    )


def signals_for_month(
    repo_root: Path | str | None = None,
    ym: str | None = None,
) -> dict[str, DataSignals]:
    """Walk `clients/<code>/` and return {CODE: DataSignals} for the given
    month. Defaults: repo_root = this repo, ym = prior calendar month."""
    root = Path(repo_root) if repo_root else DEFAULT_REPO
    clients = root / CLIENTS_DIRNAME
    target = ym or prior_month()
    out: dict[str, DataSignals] = {}
    for d in sorted(p for p in clients.iterdir() if p.is_dir()):
        if d.name.startswith(".") or not d.name.replace("_", "").isalnum():
            continue
        sig = signals_for_client(d, target)
        out[sig.code] = sig
    return out


def active_codes(signals: dict[str, DataSignals]) -> list[str]:
    return sorted(code for code, s in signals.items() if s.active)


__all__ = [
    "DataSignals",
    "prior_month",
    "signals_for_client",
    "signals_for_month",
    "active_codes",
]
