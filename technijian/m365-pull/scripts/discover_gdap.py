"""Discover all active GDAP relationships and populate gdap_status.csv.

Calls GET /tenantRelationships/delegatedAdminRelationships on Technijian's
own tenant (partner tenant), extracts every active customer, tries to match
each one against the known CP client list, then writes to gdap_status.csv.

Matching:
  1) Normalize both sides: lowercase, strip punctuation/suffixes.
  2) Exact match, then substring match.
  3) Unmatched get a tentative code derived from initials; user can edit.

Usage:
    python discover_gdap.py               # discover + update gdap_status.csv
    python discover_gdap.py --dry-run     # print table, no writes
    python discover_gdap.py --status all  # include non-active statuses too
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPELINE_ROOT = HERE.parent
REPO = PIPELINE_ROOT.parent.parent
STATE_DIR = PIPELINE_ROOT / "state"
GDAP_CSV = STATE_DIR / "gdap_status.csv"
CLIENTS_ROOT = REPO / "clients"

TECHNIJIAN_TENANT = "cab8077a-3f42-4277-b7bd-5c9023e826d8"

sys.path.insert(0, str(HERE))
import m365_api as mapi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STRIP_SUFFIXES = re.compile(
    r"\b(inc|llc|ltd|corp|co|company|group|solutions|technologies|tech|"
    r"services|consulting|associates|partners|international|intl|the)\b",
    re.I
)
_NON_ALPHA = re.compile(r"[^a-z0-9 ]")


def _norm(name: str) -> str:
    s = name.lower()
    s = _NON_ALPHA.sub(" ", s)
    s = _STRIP_SUFFIXES.sub(" ", s)
    return " ".join(s.split())


def _initials(name: str) -> str:
    """'Brandywine Homes' -> 'BH', 'Core Benefits' -> 'CB'."""
    words = [w for w in name.split() if len(w) > 1]
    return "".join(w[0].upper() for w in words[:6]) or name[:4].upper()


def load_cp_clients() -> list[dict]:
    """Load client list from the most recent monthly state file."""
    state_files = sorted(STATE_DIR.glob("2026-*.json"))
    for f in reversed(state_files):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results = data.get("results", [])
            if results:
                return [{"code": r["LocationCode"], "name": r.get("Location_Name", r["LocationCode"])}
                        for r in results if r.get("LocationCode")]
        except Exception:
            continue
    # fallback: enumerate clients/ folders
    return [{"code": p.name.upper(), "name": p.name}
            for p in CLIENTS_ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")]


def load_existing_gdap() -> dict[str, dict]:
    """Return {tenant_id: row} for rows already in gdap_status.csv."""
    if not GDAP_CSV.exists():
        return {}
    existing: dict[str, dict] = {}
    with open(GDAP_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tid = row.get("tenant_id", "").strip()
            if tid:
                existing[tid] = row
    return existing


def match_client(customer_name: str, cp_clients: list[dict]) -> dict | None:
    """Try to match a GDAP customer display name to a CP client entry."""
    norm_customer = _norm(customer_name)
    # Pass 1: exact normalized match
    for c in cp_clients:
        if _norm(c["name"]) == norm_customer:
            return c
    # Pass 2: one side contains the other
    for c in cp_clients:
        cn = _norm(c["name"])
        if cn and (cn in norm_customer or norm_customer in cn):
            return c
    return None


def generate_code(name: str, existing_codes: set[str]) -> str:
    base = _initials(name)
    if base not in existing_codes:
        return base
    for i in range(2, 20):
        candidate = f"{base}{i}"
        if candidate not in existing_codes:
            return candidate
    return name[:8].upper().replace(" ", "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Discover GDAP relationships")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", default="active",
                    help="GDAP status filter: active (default) | approved | all")
    args = ap.parse_args()

    status_filter = None if args.status == "all" else args.status

    print(f"Querying GDAP relationships (status={args.status}) on tenant {TECHNIJIAN_TENANT}...")
    try:
        relationships = mapi.get_gdap_relationships(TECHNIJIAN_TENANT, status_filter)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    if not relationships:
        print("No relationships returned. Check that DelegatedAdminRelationship.Read.All "
              "is granted in the Azure app.")
        sys.exit(0)

    cp_clients = load_cp_clients()
    existing_gdap = load_existing_gdap()
    existing_codes = {r["client_code"] for r in existing_gdap.values()}

    rows_to_add: list[dict] = []
    already_have: list[dict] = []
    matched: list[tuple] = []
    unmatched: list[tuple] = []

    for rel in relationships:
        tid = rel["customerTenantId"]
        cname = rel["customerDisplayName"] or rel["displayName"]

        if tid in existing_gdap:
            already_have.append(existing_gdap[tid])
            continue

        cp_match = match_client(cname, cp_clients)
        if cp_match:
            code = cp_match["code"]
            matched.append((cname, code, cp_match["name"]))
        else:
            code = generate_code(cname, existing_codes)
            unmatched.append((cname, code))

        existing_codes.add(code)
        rows_to_add.append({
            "client_code": code,
            "client_name": cname,
            "tenant_id": tid,
            "gdap_requested": rel.get("createdDateTime", "")[:10],
            "gdap_approved": rel.get("activatedDateTime", "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "status": "approved",
            "notes": f"GDAP expires {rel.get('endDateTime','')[:10]}  rel_id={rel['id'][:8]}",
        })

    # ---- Report ----
    print(f"\nFound {len(relationships)} relationship(s).  "
          f"Already in CSV: {len(already_have)}  "
          f"New: {len(rows_to_add)}\n")

    if already_have:
        print("-- Already tracked --")
        for r in already_have:
            print(f"  {r['client_code']:<12} {r['client_name']}")

    if matched:
        print("\n-- Matched to CP client --")
        for gdap_name, code, cp_name in matched:
            print(f"  {code:<12} GDAP='{gdap_name}'  CP='{cp_name}'")

    if unmatched:
        print("\n-- NEW (no CP match, auto-code assigned) --")
        for gdap_name, code in unmatched:
            print(f"  {code:<12} '{gdap_name}'")

    if not rows_to_add:
        print("\nNothing new to add.")
        return

    if args.dry_run:
        print("\n[dry-run] No changes written.")
        return

    # ---- Write ----
    # Preserve existing rows + append new
    all_existing_rows: list[dict] = []
    if GDAP_CSV.exists():
        with open(GDAP_CSV, newline="", encoding="utf-8") as f:
            all_existing_rows = list(csv.DictReader(f))

    GDAP_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["client_code", "client_name", "tenant_id",
                  "gdap_requested", "gdap_approved", "status", "notes"]
    with open(GDAP_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in all_existing_rows:
            w.writerow(row)
        for row in rows_to_add:
            w.writerow(row)

    print(f"\nWrote {len(rows_to_add)} new row(s) to {GDAP_CSV}")
    print("\nAll tenants are now set to status=approved.")
    print("Review the CSV and delete or change status for any you don't want.")


if __name__ == "__main__":
    main()
