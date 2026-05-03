"""Print actionable MailStore SPE alerts.

Combines two sources:
  1. GetServiceStatus.messages — system-wide warnings/errors as the management
     console shows them ("a new SPE version is available", "search indexes
     need rebuild", "SMTP unencrypted", etc.)
  2. Per-instance store health — surfaces stores where searchIndexesNeedRebuild,
     needsUpgrade, or error != null.

Exit code:
  0  — no errors
  1  — at least one error-level message or store-health failure
  2  — connection / auth failure

Usage:
  python show_alerts.py
  python show_alerts.py --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys

from spe_client import Client, SPEError

SEV_RANK = {"information": 0, "warning": 1, "error": 2}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        c = Client()
        svc = c.service_status()
        instances = c.list_instances("*")
    except SPEError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    alerts = []
    for m in svc.get("messages") or []:
        alerts.append({
            "source": "service_status",
            "severity": m.get("type"),
            "text": m.get("text"),
            "instance": None,
            "tag": m.get("tag"),
        })

    for inst in instances:
        if inst.get("status") != "running":
            alerts.append({
                "source": "instance",
                "severity": "warning",
                "text": f"Instance {inst['instanceID']} is {inst.get('status')}"
                        + (f" (startStopError: {inst['startStopError']})" if inst.get("startStopError") else ""),
                "instance": inst["instanceID"],
                "tag": None,
            })
            continue
        iid = inst["instanceID"]
        try:
            stores = c.stores(iid, include_size=False)
        except SPEError as e:
            alerts.append({"source": "instance", "severity": "warning", "text": f"GetStores failed: {e}", "instance": iid, "tag": None})
            continue
        for s in stores:
            if s.get("error"):
                alerts.append({"source": "store", "severity": "error",
                               "text": f"Store {s.get('name')!r} error: {s['error']}", "instance": iid, "tag": s.get("id")})
            if s.get("searchIndexesNeedRebuild"):
                alerts.append({"source": "store", "severity": "error",
                               "text": f"Store {s.get('name')!r} search indexes need rebuild", "instance": iid, "tag": s.get("id")})
            if s.get("needsUpgrade"):
                alerts.append({"source": "store", "severity": "warning",
                               "text": f"Store {s.get('name')!r} needs upgrade", "instance": iid, "tag": s.get("id")})

    alerts.sort(key=lambda a: (-SEV_RANK.get(a["severity"], 0), a["instance"] or "", a["text"]))

    if args.json:
        print(json.dumps(alerts, indent=2))
    else:
        env = svc.get("environmentInfo", {})
        print(f"MailStore SPE {env.get('version')} on {env.get('serverName')} — {env.get('licenseeName')}")
        if not alerts:
            print("\nNo active alerts.")
        else:
            print(f"\n{len(alerts)} alert(s):\n")
            for a in alerts:
                marker = {"error": "[ERR]", "warning": "[WARN]", "information": "[INFO]"}.get(a["severity"], "[?]")
                where = f" ({a['instance']})" if a["instance"] else ""
                print(f"  {marker:6s}{where}  {a['text']}")

    has_error = any(a["severity"] == "error" for a in alerts)
    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
