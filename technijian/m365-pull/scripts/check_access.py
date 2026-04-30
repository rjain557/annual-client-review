"""Probe each tenant in gdap_status.csv and report access status.

For each tenant:
  1. Try to acquire an app-only token (tests app admin consent).
  2. If token works, hit /organization to confirm the call succeeds.

Output:
  HAVE_ACCESS / NO_ACCESS table, plus per-tenant error reason.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import m365_api as mapi

GDAP_CSV = HERE.parent / "state" / "gdap_status.csv"


def classify_error(exc: Exception) -> str:
    msg = str(exc)
    if "AADSTS7000229" in msg:
        return "NO_CONSENT (no service principal in tenant)"
    if "AADSTS50020" in msg:
        return "NO_ACCESS (user/app not in directory)"
    if "AADSTS700016" in msg:
        return "NO_CONSENT (app not found in tenant)"
    if "AADSTS90002" in msg:
        return "BAD_TENANT_ID"
    if "AADSTS500011" in msg:
        return "NO_CONSENT (resource principal not found)"
    if "Forbidden" in msg or "403" in msg:
        return "FORBIDDEN (token ok, permission missing)"
    return f"OTHER: {msg[:120]}"


def main() -> None:
    if not GDAP_CSV.exists():
        print(f"[FATAL] {GDAP_CSV} not found")
        sys.exit(1)

    have = []
    missing = []

    with open(GDAP_CSV, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)
                if r.get("status", "").strip() == "approved"
                and r.get("tenant_id", "").strip()]

    print(f"\nProbing {len(rows)} tenants...\n")

    for r in rows:
        code = r["client_code"]
        name = r["client_name"]
        tid = r["tenant_id"]
        label = f"{code:<10} {name[:40]:<40}"

        try:
            mapi._get_token(tid)
        except Exception as exc:
            reason = classify_error(exc)
            print(f"  FAIL  {label}  {reason}")
            missing.append({"code": code, "name": name, "tenant_id": tid, "reason": reason})
            continue

        try:
            mapi.get_subscribed_skus(tid)
        except Exception as exc:
            reason = classify_error(exc)
            print(f"  FAIL  {label}  {reason}")
            missing.append({"code": code, "name": name, "tenant_id": tid, "reason": reason})
            continue

        print(f"  OK    {label}")
        have.append({"code": code, "name": name, "tenant_id": tid})

    print(f"\n=== {len(have)} have access  /  {len(missing)} missing ===\n")

    if have:
        print("HAVE ACCESS:")
        for c in have:
            print(f"  {c['code']:<10} {c['name']}")

    if missing:
        print("\nNO ACCESS (need consent):")
        for c in missing:
            print(f"  {c['code']:<10} {c['name']:<40}  {c['reason']}")


if __name__ == "__main__":
    main()
