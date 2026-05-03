"""Pull a year's worth of MailStore SPE activity per instance.

Writes JSON dumps of GetWorkerResults (archive run history) and GetJobResults
(scheduled-job history) for every running instance into:

    clients/<code>/mailstore/<year>/worker-results-<instanceID>.json
    clients/<code>/mailstore/<year>/job-results-<instanceID>.json

Datetime gotcha: SPE expects ISO-8601 *without* the trailing Z (`2026-01-01T00:00:00`)
even though the docs imply UTC. profileID and userName are nullable — passing 0
or "" makes the call error.

Bug workaround: GetWorkerResults sometimes raises "Nullable object must have a
value" when the requested window contains many rows (>~5k). The script
auto-bisects the window by month, then by day, salvaging every retrievable row
and recording any individual days that still fail under `broken_days`.

Usage:
  python pull_year_activity.py                  # current year, all instances
  python pull_year_activity.py --year 2026
  python pull_year_activity.py --instance icmlending --year 2026
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from spe_client import Client, SPEError, client_code_for


def _iso(d: dt.date) -> str:
    return f"{d}T00:00:00"


def _fetch_worker_results_year(c: Client, instance_id: str, year: int) -> tuple[list[dict], list[str]]:
    """Pull GetWorkerResults across the whole year, auto-bisecting on the
    'Nullable object must have a value' bug. Returns (rows, broken_days)."""
    fr_y = _iso(dt.date(year, 1, 1))
    to_y = _iso(dt.date(year + 1, 1, 1))
    try:
        r = c.invoke("GetWorkerResults", instanceID=instance_id,
                     fromIncluding=fr_y, toExcluding=to_y, timeZoneID="$Local")
        return (r if isinstance(r, list) else [], [])
    except SPEError:
        pass

    rows: list[dict] = []
    broken: list[str] = []
    for m in range(1, 13):
        m_start = dt.date(year, m, 1)
        m_end = dt.date(year + 1, 1, 1) if m == 12 else dt.date(year, m + 1, 1)
        try:
            r = c.invoke("GetWorkerResults", instanceID=instance_id,
                         fromIncluding=_iso(m_start), toExcluding=_iso(m_end), timeZoneID="$Local")
            if isinstance(r, list):
                rows.extend(r)
            continue
        except SPEError:
            pass
        d = m_start
        while d < m_end:
            dn = d + dt.timedelta(days=1)
            try:
                r = c.invoke("GetWorkerResults", instanceID=instance_id,
                             fromIncluding=_iso(d), toExcluding=_iso(dn), timeZoneID="$Local")
                if isinstance(r, list):
                    rows.extend(r)
            except SPEError:
                broken.append(str(d))
            d = dn
    return rows, broken


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[3]
    default_out = repo_root / "clients"

    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=dt.date.today().year)
    ap.add_argument("--instance", action="append", default=None)
    ap.add_argument("--out", default=str(default_out))
    args = ap.parse_args(argv)

    fr = f"{args.year}-01-01T00:00:00"
    to = f"{args.year + 1}-01-01T00:00:00"
    out_root = Path(args.out)

    c = Client()
    instances = [i for i in c.list_instances("*") if i.get("status") == "running"]
    if args.instance:
        instances = [i for i in instances if i["instanceID"] in args.instance]
    if not instances:
        print("No running instances matched.", file=sys.stderr)
        return 1

    print(f"Year {args.year} activity for {len(instances)} instance(s):\n")
    for inst in instances:
        iid = inst["instanceID"]
        code = client_code_for(iid) or iid.replace("-", "_")
        out_dir = out_root / code / "mailstore" / str(args.year)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Worker (archiving / export profile run) results — auto-bisect on bug
        rows, broken = _fetch_worker_results_year(c, iid, args.year)
        wpath = out_dir / f"worker-results-{iid}.json"
        payload: dict | list = rows if not broken else {"broken_days": broken, "results": rows}
        wpath.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        msg = f"  [{iid}] worker results -> {wpath} (rows: {len(rows)}"
        if broken:
            msg += f", broken_days: {len(broken)}"
        print(msg + ")")

        # Job (scheduled API jobs) results
        try:
            jr = c.invoke("GetJobResults", instanceID=iid, fromIncluding=fr,
                          toExcluding=to, timeZoneId="$Local")
        except SPEError as e:
            print(f"  [{iid}] job-results FAILED: {e}", file=sys.stderr)
            jr = {"_error": str(e)}
        jpath = out_dir / f"job-results-{iid}.json"
        jpath.write_text(json.dumps(jr, indent=2, default=str), encoding="utf-8")
        jcount = len(jr) if isinstance(jr, list) else (len(jr.get("results", [])) if isinstance(jr, dict) else "?")
        print(f"  [{iid}] job results    -> {jpath} (rows: {jcount})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
