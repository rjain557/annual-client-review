"""Categorize BWH tickets by theme to explain where the 4,050 hours went.

Reads ticket-by-ticket.csv, bucket-tags each ticket into a work-type category,
then emits:
  - work-categories-by-month.csv   (month x category pivot)
  - work-categories-summary.csv    (category totals)
  - project-candidate-tickets.csv  (project-style work that may have been bundled into monthly support)
"""
import csv
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # clients/BWH/
HERE = ROOT / "03_Accounting"
SRC = HERE / "ticket-by-ticket.csv"

# Order matters — first match wins. Categories prefixed "Project:" are
# candidates for separately-quoted SOW work that may have been absorbed into
# monthly support hours.
CATEGORIES = [
    # ===== PROJECT-STYLE THREADS IDENTIFIED IN BWH DATA =====
    ("Project: NewStar ERP upgrade / updates / support",
     re.compile(r"\bnewstar\b", re.I)),
    ("Project: OneDrive / SharePoint data migration",
     re.compile(r"\b(folder|file\s*share|shared\s*drive|shares?)\b.*\b(migrat|move|copy|transition)\b.*\bone\s*drive\b"
                r"|\bone\s*drive\b.*\b(migrat|setup|rollout|sync|onboard)\b"
                r"|\bmigration\s*to\s*one\s*drive\b"
                r"|\bsharepoint\b.*\b(migrat|setup|rollout|provision)\b", re.I)),
    ("Project: Windows 11 / PC refresh / laptop deploy",
     re.compile(r"\bwindows\s*11\s*(upgrade|rollout|deploy|readiness|refresh)\b"
                r"|\b(pc|laptop|workstation|hardware|hp\s*server)\s*refresh\b"
                r"|\b(laptop|pc|workstation)\s*(setup|deploy|image|onboard|new)\b"
                r"|\bsetup\s*(new\s*)?(laptop|pc|workstation|user|computer)\b"
                r"|\bimaging\b|\bonboard(ing)?\b", re.I)),
    ("Project: Server / VM / ESXi / VMware upgrade or rebuild",
     re.compile(r"\b(esxi|vmware|vsphere|vcenter|hyper-?v|vm|host)\b.*\b(upgrade|install|build|rebuild|migrat|patch|refresh|reboot|decom)\b"
                r"|\b(upgrade|install|build|rebuild|migrat|refresh|decom)\b.*\b(esxi|vmware|vsphere|host|vm|server)\b"
                r"|\bwindows\s*server\s*(2016|2019|2022)\b"
                r"|\bdomain\s*controller\b.*\b(upgrade|rebuild|install|promote|demote)\b"
                r"|\bhp\s*server\s*refresh(ing)?\b"
                r"|\bvirtual\s*disk\s*consolidation\b|\bsnapshot\s*consolidation\b", re.I)),
    ("Project: Firewall / VPN / Network buildout",
     re.compile(r"\bnew\s*firewall\b|\bfirewall\s*(install|replac|upgrade|deploy|migrat|setup)\b"
                r"|\b(install|replac|upgrade|deploy|setup)\b.*\b(firewall|sonicwall|fortigate|meraki|cisco\s*asa)\b"
                r"|\bvpn\s*(setup|install|deploy|config|client)\b"
                r"|\b(switch|access\s*point|unifi|ubiquiti|aruba|meraki)\b.*\b(install|upgrade|deploy|setup|replace|config)\b", re.I)),
    ("Project: Backup / Veeam / Replication setup or rebuild",
     re.compile(r"\b(veeam|vbr|backup|replication)\b.*\b(install|setup|implement|deploy|migrat|rebuild|replace|upgrade|config|job\s*create|new\s*job)\b"
                r"|\b(install|setup|implement|deploy|migrat|rebuild|upgrade)\b.*\b(veeam|vbr|replication|backup\s*server)\b"
                r"|\bqnap\s*(firmware|upgrade|replace|rebuild|setup|deploy|migrat)\b", re.I)),
    ("Project: Microsoft 365 / Exchange / Intune / Entra",
     re.compile(r"\b(m365|o365|office\s*365|microsoft\s*365|exchange\s*online|tenant|intune|azure\s*ad|entra)\b.*\b(migrat|setup|deploy|implement|config|onboard|tenant|rollout)\b"
                r"|\bmailbox\s*(migrat|move)\b", re.I)),
    ("Project: Security / EDR / CrowdStrike / Umbrella / SSL / MFA rollout",
     re.compile(r"\b(crowdstrike|sentinelone|defender\s*(for|atp)|huntress|todyl|threatlocker|umbrella)\b.*\b(deploy|rollout|setup|implement|onboard|config|install)\b"
                r"|\b(mfa|okta|duo|dmarc|dkim|spf)\b.*\b(deploy|rollout|setup|implement|config)\b"
                r"|\bssl\s*certificate\s*(update|renew|install)\b", re.I)),

    # ===== ROUTINE RECURRING OPERATIONS =====
    ("Routine: Weekly Maintenance Window",
     re.compile(r"\bweekly\s*maintenance\s*window\b|\bmaintenance\s*window\b", re.I)),
    ("Routine: CrowdStrike / EDR agent version updates",
     re.compile(r"\bcrowdstrike\b|\bsentinelone\b|\bdefender\b|\bhuntress\b", re.I)),
    ("Routine: MyRMM / ManageEngine / N-able / RMM agent version updates",
     re.compile(r"\b(myrmm|manage\s*engine|manageengine|n-?able|n-?central|rmm\s*agent|tools\s*install|agent\s*(update|upgrade|version|not\s*sync|not\s*responding|install))\b", re.I)),
    ("Routine: ScreenConnect / MyRemote agent updates",
     re.compile(r"\b(screenconnect|myremote|my\s*remote)\b", re.I)),
    ("Routine: Patch management / Windows Update / missing patches",
     re.compile(r"\bpatch(ed|es|ing)?\b|\bwindows\s*update\b|\bmissing\s*update\b|\bnon-?compliant\b|\bfailed\s*(patch|installation)\b|\bapd\b|\bautomate\s*patch\b", re.I)),
    ("Routine: Monitoring alert — device down / not responding / agent offline",
     re.compile(r"\bdevice\s*(not\s*responding|down)\b|\bnot\s*contact(ed)?\s*agent\b|\bprobably\s*down\b|\bno\s*response\s*from\s*device\b|\boffline\b|\bping\s*(jitter|latency|down)\b", re.I)),
    ("Routine: Monitoring alert — CPU / memory / disk utilization",
     re.compile(r"\b(cpu|memory|disk|bandwidth|drive\s*space)\s*utilization\b|\bthreshold\b|\bhigh\s*(cpu|memory|disk)\b|\bserver\s*reboot\b|\bpending\s*for\s*reboot\b", re.I)),
    ("Routine: VMware / ESXi maintenance (snapshot, consolidation, reboot)",
     re.compile(r"\bsnapshot\s*consolidation\b|\bvirtual\s*disk\s*consolidation\b|\besxi\s*host\s*reboot\b|\bhost\s*reboot\b", re.I)),
    ("Routine: Backup job / Veeam alert / failure",
     re.compile(r"\bbackup\s*(fail|error|alert|monitor|job|issue|pending|not\s*running)\b|\bveeam\s*(alert|fail|error|issue|backup)\b|\bweekly\s*firewall\s*backup\b", re.I)),
    ("Routine: Antivirus / Malware scan",
     re.compile(r"\b(malwarebytes|antivirus|\bav\b|virus\s*scan|malware\s*scan|threat\s*detected|quarantin)\b", re.I)),
    ("Routine: User login / password / account lockout",
     re.compile(r"\b(password|lockout|locked\s*out|cannot\s*log\s*in|can't\s*log\s*in|unable\s*to\s*log\s*?in|reset\s*password|account\s*(disabled|locked)|login\s*(issue|problem))\b", re.I)),
    ("Routine: Email / Outlook / spam / phishing",
     re.compile(r"\b(outlook|email|spam|phish|junk|mailbox|mimecast|quarantine)\b", re.I)),
    ("Routine: File access / Shared drive / OneDrive sync / Permissions",
     re.compile(r"\b(permission|access\s*(denied|to\s*(the|shared)|issue)|file\s*share|shared?\s*(drive|folder)|mapped\s*drive|network\s*drive|one\s*drive\s*(sync|file|issue|problem)|file\s*missing|mydisk)\b", re.I)),
    ("Routine: Printer / Scanner / Peripheral",
     re.compile(r"\b(printer|scanner|toner|print\s*queue|jam|copier|mfp)\b", re.I)),
    ("Routine: Phone / Voice / Teams / Conferencing",
     re.compile(r"\b(phone|voice|voip|teams\s*call|ring\s*central|ringcentral|3cx|extension|zoom|conference)\b", re.I)),
    ("Routine: Hardware troubleshoot (slow, freeze, bsod, boot)",
     re.compile(r"\b(screen|monitor|battery|slow|freez|crash|blue\s*screen|bsod|won't\s*boot|will\s*not\s*boot|hardware|dock|keyboard|mouse|usb|bluetooth)\b", re.I)),
    ("Routine: Onboarding / Offboarding user",
     re.compile(r"\bonboard(ing)?\b|\boffboard(ing)?\b|\bterminat|\bnew\s*hire\b|\bseparation\b", re.I)),
    ("Routine: Network / Internet / ISP / Wi-Fi issue",
     re.compile(r"\b(network\s*(issue|down|problem)|internet\s*(down|out|slow)|isp|wi-?fi\s*(issue|down|slow)|no\s*internet|cisco|umbrella|dns\s*issue|dhcp)\b", re.I)),
    ("Routine: Weekly firewall / config backup",
     re.compile(r"\bweekly\s*firewall\s*backup\b|\bconfig\s*backup\b|\bsnmp\s*configured\b", re.I)),
    ("Routine: Admin / Approvals / Signatures / Meetings",
     re.compile(r"\b(action\s*required|via-?sign|docusign|approval\s*needed|meeting|standup|status\s*update|weekly\s*review|weekly\s*call)\b", re.I)),
    ("Routine: Server/DC issue (generic)",
     re.compile(r"\b(server\s*(down|issue|problem)|dc\s*(issue|down)|domain\s*controller\s*issue|ra01|hv01|vbr|iis)\b", re.I)),
    ("Routine: Monitoring alert — generic critical / MonitorField",
     re.compile(r"\bmonitorfield\b|\bcritical\s*-\b|\battention\s*-\b|\btrouble\s*-\b|\bwarning\s*-\b|\bdesktop\s*alert\b|\bserver\s*alert\b", re.I)),
    ("Project: File server / data migration",
     re.compile(r"\bfile\s*server\s*(migrat|move|upgrade|rebuild|install|setup)\b|\bdata\s*migration\b|\bserver\s*migration\b|\bdatto\s*(server|workplace)\s*(setup|install|migrat)\b", re.I)),
    ("Project: RMM / tooling install on new machines",
     re.compile(r"\btools?\s*install(ation|ed)?\b|\btechnijian\s*tools\b|\bpasspor?tal\b|\bsnmp\s*(setup|config)\b|\bnetwork\s*detective\s*scan\b", re.I)),
    ("Routine: VPN troubleshoot",
     re.compile(r"\bvpn\s*(issue|problem|not\s*working|update|client\s*issue)\b", re.I)),
    ("Routine: Individual user / PC / laptop issue (named)",
     re.compile(r"\b(chris|nancy|ryan|joseph|liz|aseel|joanne|traci|rick|pon|yenly|kraig|brett|richard)\b.*\b(laptop|pc|computer|machine|docking|login|issue|setup|upgrade)\b"
                r"|\bnew\s*pc\s*config|\bpreconfigure\s*new\b|\b(ipconfig|ping|tracert)\b", re.I)),
    ("Routine: Web / app 404 / site down",
     re.compile(r"\b(404|site\s*(was\s*)?down|apps\.brandywine|brandywine[-.].*\.(com|local)|website|web\s*app)\b.*\b(error|down|not\s*working|issue)\b"
                r"|\bapps\.brandywine-?homes\.com\b", re.I)),
    ("Routine: Generic help / troubleshoot / support",
     re.compile(r"\b(help|support|troubleshoot|question|assistance|fix|resolve|repair)\b", re.I)),
]

ROLE_BUCKET = {
    ("CHD-TS1", "N"):   "India NH",
    ("CHD-TS1", "AH"):  "India AH",
    ("IRV-TS1", "N"):   "USA NH",
    ("IRV-TS1", "AH"):  "USA AH",
}


def classify(title: str) -> str:
    if not title:
        return "Uncategorized"
    for name, pat in CATEGORIES:
        if pat.search(title):
            return name
    return "Uncategorized"


def main() -> None:
    cat_hours = defaultdict(float)
    cat_entries = defaultdict(int)
    cat_tickets = defaultdict(set)
    cat_month = defaultdict(lambda: defaultdict(float))
    role_cat_hours = defaultdict(lambda: defaultdict(float))
    project_rows = []
    sample_tickets = defaultdict(list)

    with SRC.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = (row.get("Ticket") or "").strip()
            try:
                hours = abs(float(row.get("Hours") or 0))
            except ValueError:
                hours = 0.0
            month = (row.get("Date") or "")[:7]
            pod = (row.get("POD") or "").strip()
            shift = (row.get("Shift") or "").strip()
            role = ROLE_BUCKET.get((pod, shift), f"{pod}/{shift}")
            inv = (row.get("InvDescription") or "").strip()

            cat = classify(title)
            cat_hours[cat] += hours
            cat_entries[cat] += 1
            cat_tickets[cat].add(title)
            cat_month[month][cat] += hours
            role_cat_hours[role][cat] += hours

            if cat.startswith("Project:"):
                project_rows.append({
                    "Date": row.get("Date"),
                    "Ticket": title,
                    "Requestor": row.get("Requestor"),
                    "Category": cat,
                    "Role": role,
                    "InvDescription": inv,
                    "Hours": round(hours, 2),
                })

            if len(sample_tickets[cat]) < 12:
                sample_tickets[cat].append((title, hours))

    total_hours = sum(cat_hours.values())

    # summary
    out_summary = HERE / "work-categories-summary.csv"
    with out_summary.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Category", "Hours", "Percent", "Unique_Tickets", "Entries"])
        for cat, hrs in sorted(cat_hours.items(), key=lambda kv: -kv[1]):
            pct = (hrs / total_hours * 100) if total_hours else 0.0
            w.writerow([cat, round(hrs, 2), f"{pct:.1f}%", len(cat_tickets[cat]), cat_entries[cat]])
        w.writerow(["TOTAL", round(total_hours, 2), "100.0%", "", ""])

    # month x category pivot
    months = sorted(cat_month.keys())
    cats = [c for c, _ in sorted(cat_hours.items(), key=lambda kv: -kv[1])]
    out_bymonth = HERE / "work-categories-by-month.csv"
    with out_bymonth.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Month"] + cats + ["TOTAL"])
        for m in months:
            row = [m]
            tot = 0.0
            for c in cats:
                h = cat_month[m].get(c, 0.0)
                row.append(round(h, 2))
                tot += h
            row.append(round(tot, 2))
            w.writerow(row)

    # role x category pivot
    out_rolecat = HERE / "work-categories-by-role.csv"
    with out_rolecat.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        roles = ["India NH", "India AH", "USA NH", "USA AH"]
        w.writerow(["Category"] + roles + ["TOTAL"])
        for c in cats:
            row = [c]
            tot = 0.0
            for r in roles:
                h = role_cat_hours[r].get(c, 0.0)
                row.append(round(h, 2))
                tot += h
            row.append(round(tot, 2))
            w.writerow(row)

    # project-candidate tickets
    out_proj = HERE / "project-candidate-tickets.csv"
    project_rows.sort(key=lambda r: (r["Category"], -r["Hours"]))
    with out_proj.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Date", "Ticket", "Requestor", "Category", "Role", "InvDescription", "Hours"])
        w.writeheader()
        w.writerows(project_rows)

    # samples
    out_samp = HERE / "work-categories-samples.md"
    with out_samp.open("w", encoding="utf-8") as f:
        f.write("# Work-Category Samples (first 12 ticket titles per category)\n\n")
        for cat in cats:
            f.write(f"## {cat} — {round(cat_hours[cat], 1)} hrs ({cat_entries[cat]} entries, {len(cat_tickets[cat])} unique titles)\n\n")
            for title, hrs in sample_tickets[cat]:
                f.write(f"- [{hrs:.2f}h] {title}\n")
            f.write("\n")

    # project totals by category
    proj_cats = {c: h for c, h in cat_hours.items() if c.startswith("Project:")}
    proj_total = sum(proj_cats.values())
    print(f"Total hours categorized: {round(total_hours, 2)}")
    print(f"Project-style hours: {round(proj_total, 2)} ({proj_total/total_hours*100:.1f}%)")
    for c, h in sorted(proj_cats.items(), key=lambda kv: -kv[1]):
        print(f"  {h:7.2f}  {c}")
    print(f"Uncategorized: {round(cat_hours.get('Uncategorized', 0), 2)}")

if __name__ == "__main__":
    main()
