"""
Pull alarm definitions (templates) from Veeam ONE.

Active/triggered alarms are NOT exposed as a list endpoint in Veeam ONE 13's
REST surface (we probed; /alarms/triggered and friends all 404). Triggered
alarms must be fetched via POST /reports with a specific alarm-history report
template. That requires UI-discovered template IDs; documented in SKILL.md.

This script captures the alarm catalog (all 524+ definitions: severity, scope,
knowledge base, assignments) which is what the annual review needs for the
'alerting posture' section.

Output:
  clients/_veeam_one/<YYYY-MM-DD>/
    alarm_templates.json
    alarm_summary.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import veeam_one_api as v

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    print(f"  wrote {p.relative_to(REPO_ROOT)}  ({p.stat().st_size} bytes)")


def _summarize(templates: list[dict]) -> dict:
    by_type   = Counter(t.get("type") for t in templates)
    by_status = Counter("enabled" if t.get("isEnabled") else "disabled" for t in templates)
    predef    = sum(1 for t in templates if t.get("isPredefined"))
    custom    = len(templates) - predef
    return {
        "total":        len(templates),
        "predefined":   predef,
        "custom":       custom,
        "enabled":      by_status.get("enabled", 0),
        "disabled":     by_status.get("disabled", 0),
        "by_object_type": dict(by_type.most_common()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else \
              REPO_ROOT / "clients" / "_veeam_one" / args.date
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[veeam-one alarms] target: {out_dir}")

    print("[veeam-one] GET alarms/templates …")
    templates = v.list_alarm_templates()
    _write(out_dir / "alarm_templates.json", templates)

    summary = _summarize(templates)
    _write(out_dir / "alarm_summary.json", summary)

    print("\n[veeam-one alarms] summary")
    print(f"  total       : {summary['total']}")
    print(f"  predefined  : {summary['predefined']}")
    print(f"  custom      : {summary['custom']}")
    print(f"  enabled     : {summary['enabled']}")
    print(f"  disabled    : {summary['disabled']}")
    print("  top 5 by object type:")
    for k, n in list(summary["by_object_type"].items())[:5]:
        print(f"    {k}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
