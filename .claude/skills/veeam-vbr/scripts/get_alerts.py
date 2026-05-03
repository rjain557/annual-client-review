"""Pull VBR's alert-shaped surfaces.

VBR v13 REST does NOT expose triggered alarms (`/alarms/triggered` is a
Veeam ONE feature, not VBR REST). The two "things that need attention"
surfaces on VBR REST are:

    /malwareDetection/events           — ransomware / suspicious-activity events
    /securityAnalyzer/bestPractices    — security posture findings (CIS-like)
    /securityAnalyzer/lastRun          — last security analyzer run

Output:
    {
      "fetchedAt": "...",
      "malwareEvents": [{...}, ...],
      "securityFindings": [{...}, ...],
      "securityAnalyzerLastRun": {...}
    }

For job-failure / repo-full / system alarms, use the separate Veeam ONE
skill (`veeam-one-pull`) which surfaces VBR's full alarm catalog.

Usage:
    python get_alerts.py
    python get_alerts.py --out alerts.json
    python get_alerts.py --severity High,Critical
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from veeam_client import VeeamApiError, VeeamClient


def _safe_paged(c: VeeamClient, path: str):
    try:
        return list(c.get_paged(path))
    except VeeamApiError as e:
        if e.status in (400, 404):
            return []
        raise


def _safe_get(c: VeeamClient, path: str):
    try:
        return c.get(path)
    except VeeamApiError as e:
        if e.status in (400, 404):
            return None
        raise


def collect(c: VeeamClient, severity_filter=None):
    malware = _safe_paged(c, "/malwareDetection/events")
    findings = _safe_paged(c, "/securityAnalyzer/bestPractices")
    last_run = _safe_get(c, "/securityAnalyzer/lastRun")

    if severity_filter:
        sev = {s.lower() for s in severity_filter}
        findings = [
            f for f in findings
            if (f.get("severity") or f.get("status") or "").lower() in sev
        ]

    return {
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
        "malwareEvents": malware,
        "securityFindings": findings,
        "securityAnalyzerLastRun": last_run,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--severity", help="comma-list, e.g. High,Critical (security findings only)")
    ap.add_argument("--host")
    ap.add_argument("--keyfile")
    args = ap.parse_args()

    sev = args.severity.split(",") if args.severity else None

    c = VeeamClient(host=args.host, keyfile=args.keyfile)
    c.login()
    out = collect(c, severity_filter=sev)

    payload = json.dumps(out, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(
            f"wrote {len(out['malwareEvents'])} malware events + "
            f"{len(out['securityFindings'])} security findings to {args.out}"
        )
    else:
        print(payload)


if __name__ == "__main__":
    main()
