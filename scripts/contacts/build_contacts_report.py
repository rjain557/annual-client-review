"""Build a contacts coverage report by cross-referencing tech-legal CONTACTS.md
files against the live Client Portal active-client list.

Outputs into technijian/contacts/:
  COVERAGE.md                       human-readable rollup
  active_client_contacts.csv        flat per-recipient CSV (one row per email)
  active_client_recipients.csv      one row per active client with derived
                                    "send-to" email list (Primary > Invoice >
                                    Contract Signer; falls back to all C1 users)
  missing_legal.csv                 active CP clients with NO tech-legal CONTACTS.md
  no_designated_recipient.csv       active clients whose CONTACTS.md exists but
                                    has no Contract Signer / Invoice Recipient /
                                    Primary Contact set in the portal
  stale_legal.csv                   tech-legal entries whose DirID/Code is no
                                    longer in the active CP client list
                                    (probably terminated)

Run:
    python scripts\\contacts\\build_contacts_report.py
    python scripts\\contacts\\build_contacts_report.py --tech-legal C:\\path\\to\\tech-legal
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CLIENTPORTAL = REPO / "scripts" / "clientportal"
OUT_DIR = REPO / "technijian" / "contacts"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(CLIENTPORTAL))

from contacts_lib import (  # noqa: E402
    DEFAULT_TECH_LEGAL_ROOT,
    cross_reference,
    is_generic_email,
    likely_signers,
    load_all_tech_legal_contacts,
    report_recipients,
    stale_legal,
)
from data_signals import prior_month, signals_for_month  # noqa: E402
import cp_api  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tech-legal", default=str(DEFAULT_TECH_LEGAL_ROOT),
                     help="path to tech-legal repo (default: %(default)s)")
    ap.add_argument("--no-cp", action="store_true",
                     help="skip Client Portal API; just dump the tech-legal "
                          "view of contacts (no active-client cross-ref)")
    ap.add_argument("--month", help="target YYYY-MM for data-active scan "
                                     "(default: prior calendar month)")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[{datetime.now():%H:%M:%S}] loading tech-legal CONTACTS.md from {args.tech_legal}")
    tech_legal = load_all_tech_legal_contacts(args.tech_legal)
    print(f"  parsed {len(tech_legal)} CONTACTS.md files")

    if args.no_cp:
        active = []
    else:
        print(f"[{datetime.now():%H:%M:%S}] fetching active CP clients...")
        active = cp_api.get_active_clients()
        print(f"  got {len(active)} active clients")

    matches = cross_reference(tech_legal, active) if active else []
    stales = stale_legal(tech_legal, active) if active else []

    target_month = args.month or prior_month()
    print(f"[{datetime.now():%H:%M:%S}] scanning per-client data for {target_month}...")
    signals = signals_for_month(ym=target_month)
    n_active = sum(1 for s in signals.values() if s.active)
    n_cp_only = sum(1 for s in signals.values() if s.cp_only)
    print(f"  {n_active} managed-IT active (security tooling observed)")
    print(f"  {n_cp_only} cp-only this month (SEO or dev-only - not in scope here)")

    # ---------- per-recipient CSV (one row per email) ----------
    flat_path = OUT_DIR / "active_client_contacts.csv"
    with flat_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["LocationCode", "Client_Name", "DirID", "Match_Method",
                    "Contact_Name", "Email", "Phone", "Role"])
        for m in matches:
            if not m.legal:
                continue
            for u in m.legal.users:
                w.writerow([m.code, m.cp_name, m.cp_dir_id, m.match_method,
                            u.name, u.email or "", u.phone or "", u.role or ""])
    print(f"  wrote {flat_path}")

    # ---------- per-client recipient CSV (one row per active client) ----------
    # Resolution policy: ONLY emails parsed out of the portal-designated
    # Primary Contact / Invoice Recipient / Contract Signer. No fallback to
    # the broader user list - "C1" is "portal user", not "signer".
    rec_path = OUT_DIR / "active_client_recipients.csv"
    no_designated = []
    missing_legal = []
    send_list_rows = []
    cp_only_rows = []
    with rec_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["LocationCode", "Client_Name", "DirID",
                    "Active", "CP_Only", "Data_Signals", "Time_Entries_This_Month",
                    "Has_Legal_File", "Has_Designated_Recipient",
                    "Contract_Signer", "Invoice_Recipient", "Primary_Contact",
                    "Total_Active_Users", "Recipient_Emails", "Send_Ready"])
        for m in matches:
            sig = signals.get(m.code)
            active = bool(sig and sig.active)
            cp_only = bool(sig and sig.cp_only)
            data_signals_str = ",".join(sig.signals) if sig else ""
            te_count = sig.cp_time_entries if sig else 0
            if cp_only:
                cp_only_rows.append({"LocationCode": m.code,
                                      "Client_Name": m.cp_name,
                                      "DirID": m.cp_dir_id,
                                      "Time_Entries_This_Month": te_count})
            if not m.legal:
                missing_legal.append(m)
                w.writerow([m.code, m.cp_name, m.cp_dir_id,
                            active, cp_only, data_signals_str, te_count,
                            False, False, "", "", "", 0, "", False])
                continue
            recipients = report_recipients(m.legal)
            # only count "needs designation" for clients that ARE active here
            if not recipients and active:
                no_designated.append(m)
            user_count = len(m.legal.users)
            send_ready = bool(recipients)
            w.writerow([
                m.code, m.cp_name, m.cp_dir_id,
                active, cp_only, data_signals_str, te_count,
                True, m.legal.has_designated_recipient,
                m.legal.contract_signer or "",
                m.legal.invoice_recipient or "",
                m.legal.primary_contact or "",
                user_count,
                "; ".join(recipients),
                send_ready,
            ])
            # send_list = active for this repo AND send-ready
            if active and send_ready:
                send_list_rows.append({
                    "LocationCode": m.code,
                    "Client_Name": m.cp_name,
                    "DirID": m.cp_dir_id,
                    "Data_Signals": data_signals_str,
                    "Time_Entries_This_Month": te_count,
                    "Recipient_Emails": "; ".join(recipients),
                })
    print(f"  wrote {rec_path}")

    # ---------- cp_only_<YYYY-MM>.csv: SEO or dev-only relationships ----------
    cp_only_path = OUT_DIR / f"cp_only_{target_month}.csv"
    with cp_only_path.open("w", encoding="utf-8", newline="") as f:
        cols = ["LocationCode", "Client_Name", "DirID", "Time_Entries_This_Month"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in sorted(cp_only_rows, key=lambda r: -int(r["Time_Entries_This_Month"] or 0)):
            w.writerow(row)
    print(f"  wrote {cp_only_path}  ({len(cp_only_rows)} cp-only clients - SEO/dev, not in scope)")

    # ---------- send_list_<YYYY-MM>.csv: the operational who-to-email set ----
    send_list_path = OUT_DIR / f"send_list_{target_month}.csv"
    with send_list_path.open("w", encoding="utf-8", newline="") as f:
        cols = ["LocationCode", "Client_Name", "DirID", "Data_Signals",
                "Time_Entries_This_Month", "Recipient_Emails"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in sorted(send_list_rows, key=lambda r: r["LocationCode"]):
            w.writerow(row)
    print(f"  wrote {send_list_path}  ({len(send_list_rows)} clients in send list)")

    # ---------- missing-legal list ----------
    miss_path = OUT_DIR / "missing_legal.csv"
    with miss_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["LocationCode", "Client_Name", "DirID"])
        for m in missing_legal:
            w.writerow([m.code, m.cp_name, m.cp_dir_id])
    print(f"  wrote {miss_path}  ({len(missing_legal)} clients)")

    # ---------- needs-designation-set worklist ----------
    # Active clients with no Primary Contact / Invoice Recipient / Contract
    # Signer set in the portal. For each, suggest the top likely signers
    # from the user list (heuristic: real-name emails, role weight, title
    # keywords) so a portal admin can pick one and set it.
    needs_path = OUT_DIR / "needs_designation_set.csv"
    with needs_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["LocationCode", "Client_Name", "DirID",
                    "Total_Active_Users", "Suggested_Signer_1",
                    "Suggested_Signer_1_Email", "Suggested_Signer_1_Role",
                    "Suggested_Signer_2", "Suggested_Signer_2_Email",
                    "Suggested_Signer_2_Role",
                    "Suggested_Signer_3", "Suggested_Signer_3_Email",
                    "Suggested_Signer_3_Role"])
        for m in no_designated:
            cands = likely_signers(m.legal)[:3]
            row = [m.code, m.cp_name, m.cp_dir_id, len(m.legal.users)]
            for i in range(3):
                if i < len(cands):
                    c = cands[i]
                    row.extend([c.name, c.email or "", c.role or ""])
                else:
                    row.extend(["", "", ""])
            w.writerow(row)
    print(f"  wrote {needs_path}  ({len(no_designated)} clients need designation)")

    # ---------- stale-legal list ----------
    stale_path = OUT_DIR / "stale_legal.csv"
    with stale_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["LegalCode", "Legal_Name", "Legal_DirID", "User_Count"])
        for c in stales:
            w.writerow([c.code, c.name, c.dir_id or "", len(c.users)])
    print(f"  wrote {stale_path}  ({len(stales)} stale entries)")

    # ---------- coverage markdown ----------
    cov_path = OUT_DIR / "COVERAGE.md"
    with cov_path.open("w", encoding="utf-8") as f:
        f.write("# Active Client Contact Coverage\n\n")
        f.write(f"**Generated:** {datetime.now().isoformat(timespec='seconds')}  \n")
        f.write(f"**Source:** `tech-legal/clients/<CODE>/CONTACTS.md` (read-only)\n\n")
        f.write(f"## Resolution policy\n\n")
        f.write(f"Recipients are **only** the emails parsed from the portal-designated "
                f"`Primary Contact`, `Invoice Recipient`, or `Contract Signer` sections of "
                f"each client's `CONTACTS.md`. The C1/C2/C3 roles in the user list are portal "
                f"user types, **not** authority to sign contracts/proposals/estimates - they "
                f"are NOT used as a fallback. If no designation is set in the portal, the "
                f"client appears in `needs_designation_set.csv` with suggested signer "
                f"candidates rather than getting auto-CC'd to the whole directory.\n\n")
        f.write(f"## Active-client definition\n\n")
        f.write(f"This repo is for **managed-IT clients** - those with endpoint or DNS "
                f"security tooling rolled out (Huntress, CrowdStrike, or Umbrella). A "
                f"client showing CP tickets only with no security signal in {target_month} "
                f"is an SEO-only or dev-only relationship managed in a different repo and "
                f"is **not** considered active here.\n\n"
                f"**Active for this repo** = at least one of `huntress` / `crowdstrike` / "
                f"`umbrella` signals observed for {target_month}.\n\n")
        f.write(f"## Roll-up\n\n")
        f.write(f"- Universe: **{len(matches)}** clients in `GET /api/clients/active`\n")
        f.write(f"- tech-legal CONTACTS.md files parsed: **{len(tech_legal)}**\n")
        n_active_total = sum(1 for s in signals.values() if s.active)
        n_cp_only = sum(1 for s in signals.values() if s.cp_only)
        f.write(f"- **Managed-IT active for {target_month}: {n_active_total}** "
                f"(huntress/crowdstrike/umbrella signal)\n")
        f.write(f"- CP-only this month (SEO/dev - not in scope): **{n_cp_only}** "
                f"(see `cp_only_{target_month}.csv`)\n")
        if matches:
            n_with_legal = sum(1 for m in matches if m.legal)
            n_send_list = sum(1 for m in matches if m.legal and report_recipients(m.legal)
                                and signals.get(m.code) and signals[m.code].active)
            f.write(f"- Active clients with a tech-legal file: **{n_with_legal} / {len(matches)}**\n")
            f.write(f"- **Operational send list ({target_month})**: managed-IT-active AND "
                    f"send-ready = **{n_send_list}** clients "
                    f"(see `send_list_{target_month}.csv`)\n")
            f.write(f"- Active but not send-ready (need portal designation): "
                    f"**{n_active_total - n_send_list}** "
                    f"(see `needs_designation_set.csv`)\n")
            f.write(f"- Active clients with NO tech-legal file: **{len(missing_legal)}** "
                    f"(see `missing_legal.csv`)\n")
        f.write(f"- tech-legal entries with no active CP match: **{len(stales)}** "
                f"(see `stale_legal.csv` - likely terminated)\n\n")

        f.write("## Match table\n\n")
        f.write(f"| Code | Client | DirID | Status ({target_month}) | Send-ready | "
                f"Designated | Users |\n")
        f.write("|---|---|---:|---|---|---|---:|\n")
        for m in sorted(matches, key=lambda x: x.code):
            sig = signals.get(m.code)
            if sig and sig.active:
                status = ",".join(sig.signals)
            elif sig and sig.cp_only:
                status = "_cp-only_"
            else:
                status = "**none**"
            if m.legal:
                designated = "yes" if m.legal.has_designated_recipient else "—"
                send_ready = "yes" if report_recipients(m.legal) else "**no**"
                users = len(m.legal.users)
            else:
                designated = "—"
                send_ready = "**no**"
                users = 0
            f.write(f"| {m.code} | {m.cp_name} | {m.cp_dir_id} | {status} | "
                    f"{send_ready} | {designated} | {users} |\n")

        if stales:
            f.write("\n## Stale tech-legal entries\n\n")
            f.write("These have CONTACTS.md files in tech-legal but no matching active CP client. "
                    "Likely terminated or renamed.\n\n")
            f.write("| Code | Name | DirID | Users |\n|---|---|---:|---:|\n")
            for c in sorted(stales, key=lambda x: x.code):
                f.write(f"| {c.code} | {c.name} | {c.dir_id or '—'} | {len(c.users)} |\n")

    print(f"  wrote {cov_path}")
    print(f"\n[{datetime.now():%H:%M:%S}] DONE  outputs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
