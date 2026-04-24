#!/usr/bin/env python3
"""Pull full BWH weekly + monthly invoice list and per-invoice detail."""
import csv
import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
API = REPO / ".codex/skills/client-portal-core/scripts/client_portal_api.py"

BWH_DIR_ID = 6245
INV_DETAIL_DIR = HERE / "invoice-details-raw"
INV_DETAIL_DIR.mkdir(exist_ok=True)


def call_sp(schema, proc, params):
    cmd = ["python3", str(API), "execute", "client-portal", schema, proc,
           "--params", json.dumps(params)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        sys.stderr.write(f"ERR {proc}: {result.stderr[:400]}\n")
        return {}
    return json.loads(result.stdout)


def pull_weekly_list():
    print("=== Weekly invoice list ===")
    d = call_sp("dbo", "stp_xml_InvWeekly_Org_Loc_Inv_Weekly_List_Get", {"DirID": BWH_DIR_ID})
    xml = (d.get("outputParameters") or {}).get("XML_OUT") or ""
    (HERE / "invoices-weekly-list.xml").write_text(xml, encoding="utf-8")
    invoices = []
    if xml:
        root = ET.fromstring(xml if xml.startswith("<Root") else f"<Root>{xml}</Root>")
        for inv in root.iter("Invoice"):
            invoices.append({
                "Type": "Weekly",
                "ID": (inv.findtext("ID") or "").strip(),
                "InvoiceNo": (inv.findtext("InvoiceNo") or "").strip(),
                "InvoiceDate": (inv.findtext("InvoiceDate") or "").strip(),
            })
    print(f"  {len(invoices)} weekly invoices")
    return invoices


def find_monthly_invoices():
    """Look for monthly invoices — probe multiple endpoints."""
    print("=== Monthly invoice probe ===")
    # Try same proc with a different param shape (some portal SPs reuse for monthly)
    candidates = [
        ("dbo", "stp_xml_Inv_Org_Clt_Inv_Get", {"DirID": BWH_DIR_ID}),
        ("dbo", "stp_xml_Inv_Org_Loc_Inv_Get", {"DirID": BWH_DIR_ID}),
    ]
    invoices = []
    for schema, proc, params in candidates:
        d = call_sp(schema, proc, params)
        xml = (d.get("outputParameters") or {}).get("XML_OUT") or ""
        print(f"  {proc}: {len(xml)} chars")
        if xml and "<Invoice" in xml:
            try:
                root = ET.fromstring(xml if xml.startswith("<Root") else f"<Root>{xml}</Root>")
                for inv in root.iter("Invoice"):
                    invoices.append({
                        "Source": proc,
                        "InvoiceID": (inv.findtext("InvoiceID") or "").strip(),
                        "InvoiceNo": (inv.findtext("InvoiceNo") or "").strip(),
                        "InvoiceDate": (inv.findtext("InvoiceDate") or "").strip(),
                        "Status": (inv.findtext("Status") or "").strip(),
                        "InvoiceType": (inv.findtext("InvoiceType") or "").strip(),
                        "Title": (inv.findtext("Title") or "").strip(),
                    })
            except ET.ParseError as e:
                print(f"    parse err: {e}")
    return invoices


def pull_invoice_detail(invoice_id):
    out_path = INV_DETAIL_DIR / f"{invoice_id}.xml"
    if out_path.exists() and out_path.stat().st_size > 50:
        return out_path.read_text(encoding="utf-8")
    d = call_sp("dbo", "stp_xml_Inv_Org_Loc_Inv_Get", {"InvoiceID": int(invoice_id)})
    xml = (d.get("outputParameters") or {}).get("XML_OUT") or ""
    out_path.write_text(xml, encoding="utf-8")
    return xml


def write_csv(invoices, path):
    if not invoices:
        return
    fields = []
    seen = set()
    for inv in invoices:
        for k in inv:
            if k not in seen:
                seen.add(k)
                fields.append(k)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(invoices)
    print(f"  wrote {path} ({len(invoices)} rows)")


if __name__ == "__main__":
    weekly = pull_weekly_list()
    monthly = find_monthly_invoices()
    all_invoices = weekly + [
        {"Type": "Other", "ID": m.get("InvoiceID"), "InvoiceNo": m.get("InvoiceNo"),
         "InvoiceDate": m.get("InvoiceDate"), "Status": m.get("Status"),
         "InvoiceType": m.get("InvoiceType"), "Title": m.get("Title")}
        for m in monthly
    ]
    # Dedup by ID
    seen = set()
    uniq = []
    for inv in all_invoices:
        k = str(inv.get("ID") or inv.get("InvoiceID") or "")
        if k in seen:
            continue
        seen.add(k)
        uniq.append(inv)

    # Enrich weekly with status/type
    print("=== Enriching with invoice detail ===")
    for i, inv in enumerate(uniq):
        iid = inv.get("ID") or inv.get("InvoiceID")
        if not iid:
            continue
        xml = pull_invoice_detail(iid)
        if xml:
            try:
                root = ET.fromstring(xml if xml.startswith("<Root") else f"<Root>{xml}</Root>")
                inv_el = root.find("Invoice")
                if inv_el is not None:
                    for field in ["DueDate", "Status", "InvoiceType", "Title", "HasAttachment"]:
                        v = inv_el.findtext(field)
                        if v:
                            inv[field] = v.strip()
            except ET.ParseError:
                pass
        if (i + 1) % 25 == 0:
            print(f"  ...{i + 1}/{len(uniq)}")

    write_csv(uniq, HERE / "invoices.csv")
