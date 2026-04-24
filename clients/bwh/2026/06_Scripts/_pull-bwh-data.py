#!/usr/bin/env python3
"""Pull complete BWH life-of-contract time entries + tickets from Client Portal.

Output:
  time-entries-raw/YYYY-MM.xml   -- raw XML_OUT per month
  tickets-raw/YYYY-MM.json       -- raw ticket JSON per month
  time-entries.csv               -- normalized time entries
  tickets.csv                    -- normalized tickets
  monthly-summary.csv            -- hours by month / POD / role / shift
"""

import csv
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent                             # clients/BWH/
DATA = ROOT / "03_Accounting"
RAW = ROOT / "04_Raw_Data"
# client-portal API lives in tech-legal (platform dependency):
API = Path(r"C:\VSCode\tech-legal\tech-legal\.codex\skills\client-portal-core\scripts\client_portal_api.py")

BWH_DIR_ID = 6245
BWH_CLIENT_CODE = "BWH"

START = date(2023, 1, 1)
END = date(2026, 4, 30)

OUT_TE_XML = RAW / "time-entries-raw"
OUT_TKT_JSON = RAW / "tickets-raw"
OUT_TE_XML.mkdir(parents=True, exist_ok=True)
OUT_TKT_JSON.mkdir(parents=True, exist_ok=True)
DATA.mkdir(parents=True, exist_ok=True)


def month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        first = date(y, m, 1)
        if m == 12:
            last = date(y, 12, 31)
            ny, nm = y + 1, 1
        else:
            last = date(y, m + 1, 1).fromordinal(date(y, m + 1, 1).toordinal() - 1)
            ny, nm = y, m + 1
        yield first, last
        y, m = ny, nm


def call_sp(schema: str, proc: str, params: dict) -> dict:
    cmd = [
        "python3", str(API), "execute", "client-portal", schema, proc,
        "--params", json.dumps(params),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        sys.stderr.write(f"ERR {proc} {params}: {result.stderr[:500]}\n")
        return {}
    return json.loads(result.stdout)


def pull_time_entries():
    print("=== Time Entries ===")
    for first, last in month_iter(START, END):
        tag = first.strftime("%Y-%m")
        xml_path = OUT_TE_XML / f"{tag}.xml"
        if xml_path.exists() and xml_path.stat().st_size > 100:
            print(f"  {tag}: cached")
            continue
        print(f"  {tag}: pulling {first} to {last}...", end=" ", flush=True)
        data = call_sp("Reporting", "stp_xml_TktEntry_List_Get", {
            "ClientID": BWH_DIR_ID,
            "StartDate": first.isoformat(),
            "EndDate": last.isoformat(),
        })
        xml = (data.get("outputParameters") or {}).get("XML_OUT")
        if xml:
            xml_path.write_text(xml, encoding="utf-8")
            count = xml.count("<TimeEntry>")
            print(f"{count} entries")
        else:
            xml_path.write_text("<Root/>", encoding="utf-8")
            print("0")


def pull_tickets():
    print("=== Tickets ===")
    for first, last in month_iter(START, END):
        tag = first.strftime("%Y-%m")
        json_path = OUT_TKT_JSON / f"{tag}.json"
        if json_path.exists() and json_path.stat().st_size > 10:
            print(f"  {tag}: cached")
            continue
        print(f"  {tag}: pulling {first} to {last}...", end=" ", flush=True)
        data = call_sp("Reporting", "stp_xml_ClientTkt_List_Get_New1", {
            "StartDate": first.isoformat(),
            "EndDate": last.isoformat(),
            "ClientCode": BWH_CLIENT_CODE,
        })
        json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        rs = data.get("resultSets") or []
        rows = sum(r.get("rowCount", 0) for r in rs)
        xml_out = (data.get("outputParameters") or {}).get("XML_OUT") or ""
        xml_count = xml_out.count("<Ticket>") if xml_out else 0
        print(f"rs={rows} xml_tickets={xml_count}")


TIME_ENTRY_FIELDS = [
    "ConName", "TimeEntryDate", "Title", "TimeDiff", "Resource",
    "Requestor", "HourType", "BillRate", "PODDet", "InvDescription",
    "InvDetID", "StartDateTime", "EndDateTime", "Office-POD",
    "RoleType", "WorkType", "AssignedName", "AH_Rate", "NH_Rate",
]


def _text(el):
    if el is None:
        return ""
    return (el.text or "").strip() if isinstance(el.text, str) else ""


def normalize_time_entries():
    print("=== Normalize time entries ===")
    csv_path = DATA / "time-entries.csv"
    all_rows = []
    for xml_file in sorted(OUT_TE_XML.glob("*.xml")):
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError as e:
            print(f"  {xml_file.name}: parse err {e}")
            continue
        for te in root.findall("TimeEntry"):
            row = {f: _text(te.find(f)) for f in TIME_ENTRY_FIELDS}
            # parse TimeDiff like " - \r\n1.00 hrs"
            hrs = 0.0
            m = re.search(r"(-?\d+(?:\.\d+)?)\s*hrs", row["TimeDiff"])
            if m:
                hrs = float(m.group(1))
            row["Hours"] = hrs
            # signed sign
            sign_match = re.search(r"([+-])\s*\n?\s*\d", row["TimeDiff"])
            if sign_match and sign_match.group(1) == "-":
                row["Hours"] = -abs(hrs)
            row["SourceMonth"] = xml_file.stem
            all_rows.append(row)

    fieldnames = ["SourceMonth"] + TIME_ENTRY_FIELDS + ["Hours"]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    print(f"  wrote {csv_path} ({len(all_rows)} rows)")
    return all_rows


def summarize_monthly(rows):
    print("=== Monthly summary ===")
    agg = {}
    for r in rows:
        te_date = r.get("TimeEntryDate", "")
        if len(te_date) < 7:
            continue
        ym = te_date[:7]
        pod = r.get("Office-POD", "")
        role = r.get("RoleType", "")
        shift = r.get("HourType", "")
        inv_desc = r.get("InvDescription", "").replace("\r\n", " / ").replace("\n", " / ")
        key = (ym, pod, role, shift, inv_desc)
        agg.setdefault(key, 0.0)
        agg[key] += r.get("Hours", 0.0)

    csv_path = DATA / "monthly-summary.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Month", "POD", "Role", "Shift", "InvDescription", "Hours"])
        for (ym, pod, role, shift, desc), hrs in sorted(agg.items()):
            w.writerow([ym, pod, role, shift, desc, round(hrs, 2)])
    print(f"  wrote {csv_path}")


def normalize_tickets():
    print("=== Normalize tickets ===")
    all_rows = []
    for jp in sorted(OUT_TKT_JSON.glob("*.json")):
        data = json.loads(jp.read_text(encoding="utf-8"))
        xml = (data.get("outputParameters") or {}).get("XML_OUT") or ""
        if xml:
            try:
                root = ET.fromstring(f"<Root>{xml}</Root>" if not xml.startswith("<Root") else xml)
            except ET.ParseError:
                continue
            for tk in root.iter("Ticket"):
                row = {el.tag: (el.text or "").strip() for el in tk}
                row["SourceMonth"] = jp.stem
                all_rows.append(row)
        # also try resultSets[0]
        for rs in data.get("resultSets", []):
            for rw in rs.get("rows", []):
                rw = dict(rw)
                rw["SourceMonth"] = jp.stem
                rw.setdefault("_source", "resultSet")
                all_rows.append(rw)

    if not all_rows:
        print("  no ticket rows")
        return

    # collect superset of fields
    fields = []
    seen = set()
    for r in all_rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                fields.append(k)

    csv_path = HERE / "tickets.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    print(f"  wrote {csv_path} ({len(all_rows)} rows)")


if __name__ == "__main__":
    pull_time_entries()
    pull_tickets()
    rows = normalize_time_entries()
    summarize_monthly(rows)
    normalize_tickets()
