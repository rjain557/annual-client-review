"""Per-category coaching templates and personalized rewrite generator.

For each work category, defines:
  - Expected_hours_max:  the cap (mirrors CATEGORY_CAP)
  - title_must_include:  what details are required to justify above-cap time
  - example_at_cap:      a model title that fits within the cap
  - example_above_cap:   a model title that justifies double the cap

For each flagged entry, build_coaching() emits:
  - bad         (their actual title)
  - good_at_cap (rewrite at the cap)
  - good_above  (rewrite that justifies their actual hours)
  - rule_text   (one-line reason)
"""
from __future__ import annotations
import re

# Order doesn't matter here — looked up by category name string.
COACHING: dict[str, dict] = {
    "Routine: Patch management / Windows Update": {
        "cap": 1.5,
        "must_include": "machine count, which patches failed, manual reinstall steps",
        "at_cap": "Monthly patch run — 28 endpoints all green, no manual intervention needed",
        "above_cap": "Patched 42 machines — 6 required manual WU service restart and reinstall of KB5034441; verified compliance in N-able dashboard before close (~2.5h)",
    },
    "Routine: Monitoring alert — CPU / memory / disk": {
        "cap": 0.75,
        "must_include": "process or workload identified as the cause and what action you took",
        "at_cap": "CPU alert on BWWS012 — checked task manager, transient AV scan, cleared",
        "above_cap": "Critical CPU on BWH-HQ-VBR-01 — investigated runaway veeam.backup.shell process, restarted VBR services, opened Veeam ticket #4421, monitored 30 min for recurrence (~1.5h)",
    },
    "Routine: Monitoring alert — device down / offline": {
        "cap": 0.75,
        "must_include": "what diagnosis was performed (ping, console, UPS, WAN check) and resolution",
        "at_cap": "Device down alert on RA01 — verified ping, agent reconnected after reboot",
        "above_cap": "RA01 down — pinged offline 20 min, attempted IPMI console (no response), drove user through power-cycle, agent reconnected, ran Veeam re-test (~1.5h)",
    },
    "Routine: Monitoring alert — generic critical / MonitorField": {
        "cap": 0.75,
        "must_include": "the specific monitor that fired and the resolution (do not just paste the alert title)",
        "at_cap": "Critical alert on BWH-HQ-IIS-01 — IIS app pool restarted, site healthy",
        "above_cap": "Critical on BWH-HQ-IIS-01 (w3wp.exe memory leak) — recycled app pool, applied .NET hotfix KB5034567, monitored 1h for recurrence (~1.5h)",
    },
    "Routine: Backup job / Veeam alert": {
        "cap": 1.5,
        "must_include": "which job failed, root cause, and verification it now succeeds",
        "at_cap": "Veeam BWH-HQ-Daily failed (snapshot timeout) — restarted job, completed clean",
        "above_cap": "Veeam BWH-HQ-Daily failing 3 days — root cause: VSS writer NtmsSvc; restarted services, ran chkdsk on volume B, kicked off full active backup, verified success (~3h)",
    },
    "Routine: ScreenConnect / MyRemote updates": {
        "cap": 1.0,
        "must_include": "machine count and any failed deployments",
        "at_cap": "ScreenConnect 24.5 push — 14 endpoints, all current",
        "above_cap": "ScreenConnect 24.5 push — 22 endpoints; 4 required service-stop and manual reinstall after upgrade hang; verified version on dashboard (~2h)",
    },
    "Routine: CrowdStrike / EDR agent updates": {
        "cap": 1.5,
        "must_include": "version installed, machine count, any prevention-policy issues",
        "at_cap": "CrowdStrike 7.18 deployed to 18 machines — sensors green",
        "above_cap": "CrowdStrike 7.18 deploy — 35 machines; 5 hung at install due to legacy McAfee remnants, ran McAfee removal tool then re-pushed; sensors all reporting (~3h)",
    },
    "Routine: MyRMM / ManageEngine agent updates": {
        "cap": 1.5,
        "must_include": "version, machine count, any not-syncing follow-ups",
        "at_cap": "ManageEngine 11.3.4.W push — 12 endpoints synced",
        "above_cap": "ManageEngine 11.3.4.W push — 28 endpoints; 6 stuck not-syncing, manually re-registered, validated check-in on portal (~3h)",
    },
    "Routine: Antivirus / Malware scan": {
        "cap": 1.5,
        "must_include": "what was scanned, what was found, what was quarantined or remediated",
        "at_cap": "Malwarebytes scan on BWLAP-09 — clean",
        "above_cap": "Malwarebytes deep scan on BWLAP-09 (suspected PUP) — found and quarantined 14 PUP.Optional.OpenCandy entries, verified clean rerun, applied browser reset (~3h)",
    },
    "Routine: Weekly Maintenance Window": {
        "cap": 2.0,
        "must_include": "must split across covered clients — log only the time spent on this client",
        "at_cap": "Maintenance window for BWH — patch reboots and verification (~1.5h portion of shared 6h window)",
        "above_cap": "Maintenance window — BWH portion (~3h of shared window): pre-patch snapshots (4 VMs), staged rolling reboots, post-reboot service verification, Veeam test backup",
    },
    "Routine: User login / password / account lockout": {
        "cap": 1.0,
        "must_include": "what specifically required investigation (AAD sync, MFA, conditional access)",
        "at_cap": "Reset password for J. Smith — verified login",
        "above_cap": "J. Smith locked out — found AAD sync delay (45 min), forced delta sync via PS, verified MFA prompt and login (~1.5h)",
    },
    "Routine: Email / Outlook / spam": {
        "cap": 1.5,
        "must_include": "what specific Outlook / Exchange action (profile rebuild, OST recreate, mail flow trace)",
        "at_cap": "Outlook prompting for credentials — cleared cached creds, profile reconnected",
        "above_cap": "Outlook profile broken on K. Lee — rebuilt MAPI profile, OST recreate (8GB resync), validated PSTs imported, calendar permissions restored (~3h)",
    },
    "Routine: File access / Shared drive / permissions": {
        "cap": 1.5,
        "must_include": "what NTFS / share / GPO change you made, and verification that user now has access",
        "at_cap": "Mapped Z: drive for new hire — verified read/write",
        "above_cap": "Permission audit for Marketing — reviewed NTFS, removed inherited Everyone, applied AGDLP groups, validated 6 users have correct access (~3h)",
    },
    "Routine: Printer / Scanner": {
        "cap": 1.5,
        "must_include": "make/model, what driver/queue/hardware action was taken",
        "at_cap": "Restarted print spooler on BWWS018, queue cleared",
        "above_cap": "HP M404 printer — driver reinstall x4 stations, replaced bad USB cable, calibrated tray; tested duplex, scanned to OneDrive (~3h)",
    },
    "Routine: Phone / Voice / Teams": {
        "cap": 1.5,
        "must_include": "platform (RingCentral / Teams / 3CX), action (extension move, DID provision, license)",
        "at_cap": "RingCentral extension move for new hire, voicemail verified",
        "above_cap": "RingCentral migration for 3 users — re-provisioned extensions, ported DIDs, configured call queue, end-user training session (~3h)",
    },
    "Routine: VPN troubleshoot": {
        "cap": 1.5,
        "must_include": "client (NetExtender / Cisco AnyConnect / FortiClient), root cause, verification",
        "at_cap": "VPN reset on N. Patel laptop — reinstalled NetExtender, connected",
        "above_cap": "VPN failure for N. Patel — bad cert chain (expired root); reinstalled root CA cert, rebuilt VPN profile, validated split-tunnel routes (~3h)",
    },
    "Routine: Hardware troubleshoot (slow, freeze, bsod, boot)": {
        "cap": 2.5,
        "must_include": "what diagnostic ran (memtest, sfc, chkdsk, hardware swap), what fixed it",
        "at_cap": "Slow boot on BWLAP-12 — disabled startup items, cleared temp, normal",
        "above_cap": "Recurring BSOD on BWLAP-12 — ran memtest (clean), driver verifier flagged Wi-Fi NIC; updated Intel driver, monitored 24h, no further crash (~5h spread)",
    },
    "Routine: Onboarding / Offboarding user": {
        "cap": 3.0,
        "must_include": "AD account, mailbox/license, device prep, app provisioning, training",
        "at_cap": "Onboarded new hire J. Lopez — AD account, M365 license, laptop staged",
        "above_cap": "Full onboarding for J. Lopez (3 systems) — AD/M365/MFA setup, laptop image, app installs (Office, NewStar, Bluebeam), training session (~6h)",
    },
    "Routine: Network / Internet / Wi-Fi": {
        "cap": 2.0,
        "must_include": "what was tested (ping, traceroute, AP placement, ISP), and resolution",
        "at_cap": "Wi-Fi outage on 2nd floor — UAP-AC reboot, RSSI verified",
        "above_cap": "Wi-Fi outages 2nd floor — AP firmware mismatch caused channel conflicts; updated 4 APs, re-meshed controller, ran site survey (~4h)",
    },
    "Routine: Admin / meetings / approvals": {
        "cap": 1.0,
        "must_include": "meeting subject, decisions made, action items assigned",
        "at_cap": "Weekly client standup with K. Stickel — 30 min, agenda + action items",
        "above_cap": "Quarterly review — ran agenda, captured 8 decisions, drafted next-quarter plan (~2h)",
    },
    "Routine: Server/DC issue": {
        "cap": 3.0,
        "must_include": "what specifically broke (services, AD replication, GPO), root cause, verification",
        "at_cap": "RA01 DC issue — restarted Netlogon service, replication healthy",
        "above_cap": "RA01 DC issue — AD replication broken (USN rollback), seized FSMO to RA02, demoted/repromoted RA01, verified replication for 2h (~5h)",
    },
    "Routine: Individual user / PC / laptop (named)": {
        "cap": 3.0,
        "must_include": "user name + what specifically was done (image, app installs, data migration)",
        "at_cap": "Set up Nancy's new laptop — image, M365 sign-in, data migrated",
        "above_cap": "Nancy laptop refresh — full image, NewStar + Bluebeam install, profile migration (12GB), 1:1 walkthrough; resolved Outlook re-sync issue post-migration (~6h)",
    },
    "Routine: Web / app 404 / site down": {
        "cap": 2.0,
        "must_include": "what diagnosis (DNS, IIS, cert, app pool, DB) and resolution",
        "at_cap": "apps.brandywine-homes.com 404 — recycled IIS app pool, site healthy",
        "above_cap": "apps.brandywine-homes.com down — expired SSL cert, generated CSR + installed new cert, configured TLS 1.2 only, validated all pages (~3h)",
    },
    "Routine: Generic help / support": {
        "cap": 1.5,
        "must_include": "must be replaced — \"Help\" / \"Support\" alone is never acceptable on entries > 0.5h. Title must say WHO you helped and WHAT was done.",
        "at_cap": "Help — walked S. Adams through Outlook calendar share, ~30 min",
        "above_cap": "Help — investigated J. Lee's stuck OneDrive sync, rebuilt local cache, re-authenticated account, resynced 18GB folder structure, verified files (~2h)",
    },

    # Project categories (looser caps; coaching focuses on completeness of deliverable)
    "Project: ERP / app upgrade": {
        "cap": 4.0,
        "must_include": "version delivered, environments touched (prod/test), validation steps",
        "at_cap": "NewStar 2024 batch upgrade on test env — validated 3 sample workflows",
        "above_cap": "NewStar 2024 upgrade prod cutover — pre-snapshot, batch run, post-validation with 3 users, rollback plan documented (~6h)",
    },
    "Project: RMM / tooling install": {
        "cap": 3.0,
        "must_include": "machine count, tools installed, validation in dashboard",
        "at_cap": "MyRMM tools install on 4 new machines, all reporting in portal",
        "above_cap": "MyRMM tools rollout — 12 new machines; 3 required service-account fix, validated check-in + heartbeat on portal (~5h)",
    },
    "Project: Server / VM / ESXi upgrade or rebuild": {
        "cap": 4.0,
        "must_include": "host(s) touched, before/after state, downtime window",
        "at_cap": "ESXi-01 patch and reboot — 30 min downtime window, all VMs back up",
        "above_cap": "BWH-HQ-ESXI-01 firmware + ESXi 8 upgrade — 4h maintenance window, evacuated VMs to ESXi-02, applied updates, validated HA failback (~6h)",
    },
    "Project: Windows refresh / PC deploy": {
        "cap": 4.0,
        "must_include": "user(s), apps deployed, profile migration scope",
        "at_cap": "New PC build for K. Lee — image, M365, NewStar, profile migration",
        "above_cap": "Windows 11 refresh wave — 4 PCs (Brett, Nancy, Chris, Joe); imaged, profile migration via USMT, app installs, training (~8h spread)",
    },
    "Project: OneDrive / SharePoint data migration": {
        "cap": 4.0,
        "must_include": "data volume, source/destination, post-migration verification",
        "at_cap": "Projects folder migration to OneDrive — 18 GB, verified file counts match",
        "above_cap": "Share folder migration to OneDrive — 60GB across 3 departments, ran ShareGate, validated permissions and version history retained (~6h)",
    },
    "Project: Backup / Veeam / Replication": {
        "cap": 4.0,
        "must_include": "what was rebuilt/configured, retention, test restore performed",
        "at_cap": "Veeam job rebuild for BWH-HQ-DC — daily incremental, monthly full",
        "above_cap": "Veeam V12 upgrade + repository migration — moved 4TB to new QNAP, reconfigured 8 jobs, ran test restore on key VMs (~6h)",
    },
    "Project: Firewall / VPN / Network buildout": {
        "cap": 4.0,
        "must_include": "device, config scope (rules, VPN, routing), validation",
        "at_cap": "New firewall install at BWH-HQ — base config, 6 rules, VPN tested",
        "above_cap": "Sophos XGS upgrade — replaced TZ300; migrated 20 rules, 2 site-to-site VPNs, SD-WAN policy, validated failover (~8h)",
    },
    "Project: File server / data migration": {
        "cap": 4.0,
        "must_include": "volume, source/destination, downtime, validation",
        "at_cap": "File server migration — 200GB to new VM, permissions retained",
        "above_cap": "BWH file server migration — 1.2TB Robocopy + ACL migration, DFS namespace cutover, validated 12 user mappings (~6h)",
    },
    "Project: Security / EDR / SSL rollout": {
        "cap": 3.0,
        "must_include": "scope (endpoints, certs, MFA users), validation",
        "at_cap": "SSL cert renewal on apps.brandywine-homes.com — installed, TLS 1.2 only",
        "above_cap": "Wildcard SSL renewal — generated CSR, installed on 3 IIS sites + 2 Exchange CAS, validated chain in Qualys SSL Labs (~4h)",
    },
    "Project: M365 / Exchange / Intune / Entra": {
        "cap": 4.0,
        "must_include": "user/mailbox count, what configured, validation",
        "at_cap": "Intune deployment for 3 new mobile devices, MAM policies applied",
        "above_cap": "Intune rollout — 22 mobile devices; configured MAM, conditional access, app config policies; validated enrollment (~6h)",
    },
    "Uncategorized": {
        "cap": 2.5,
        "must_include": "any details about what work was actually done",
        "at_cap": "Site visit to BWH-HQ — 2h walkthrough with K. Stickel",
        "above_cap": "BWH-HQ visit — diagnosed switch issue in Equipment closet 2, replaced bad SFP, validated link on 4 APs (~3h)",
    },
}


def build_coaching(actual_title: str, category: str, actual_hours: float) -> dict:
    """Return per-entry coaching: bad title, two model rewrites, one-line rule."""
    info = COACHING.get(category, COACHING["Uncategorized"])
    cap = info["cap"]
    if actual_hours > cap * 1.5:
        priority = f"Your {actual_hours:.2f}h is well above the {cap:.1f}h normal — title MUST justify the extra time."
    elif actual_hours > cap:
        priority = f"Your {actual_hours:.2f}h is above the {cap:.1f}h normal cap for this category — title needs more detail."
    else:
        priority = f"Hours are within range; title quality could improve."
    return {
        "ExpectedHours": cap,
        "WhyFlagged": priority,
        "MustInclude": info["must_include"],
        "GoodExample_AtCap": info["at_cap"],
        "GoodExample_Justified": info["above_cap"],
        "BadExample": actual_title or "(blank)",
    }
