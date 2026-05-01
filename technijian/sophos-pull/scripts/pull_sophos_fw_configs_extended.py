"""
Pull extended on-box configuration from all Sophos XGS firewalls with keyfiles.

Unlike scan_sophos_fw_api.py this script does NOT require a prior Central API
daily pull (no firewalls.json dependency). It reads directly from OneDrive
keyfiles and pulls a comprehensive configuration snapshot.

Tag names validated against Sophos XGS API (form-encoded reqxml= format):
  Core:      Interface, VLAN, Zone, UnicastRoute, DHCPServer, DNS
  Policy:    FirewallRule, NATRule, IPSPolicy, WebFilterPolicy,
             SSLTLSInspectionRule, ApplicationFilter
  VPN:       IPSecConnection, SSLVPNClientPolicy (optional)
  Objects:   IPHost, IPHostGroup, Services, ServiceGroup
  Users:     User, UserGroup
  QoS:       QoSPolicy
  Alerts:    Notification, NotificationList

Output: clients/<code>/sophos/<YYYY-MM-DD>/config_extended_<ip>.json

Usage:
    python pull_sophos_fw_configs_extended.py
    python pull_sophos_fw_configs_extended.py --only ani,bwh,vaf
    python pull_sophos_fw_configs_extended.py --timeout 30
"""
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
CLIENTS_ROOT = REPO / "clients"

KEYS_ROOT = (Path(os.environ.get("USERPROFILE", "~")).expanduser()
             / "OneDrive - Technijian, Inc" / "Documents" / "VSCODE" / "keys")

DEFAULT_TIMEOUT = 20

# ---------------------------------------------------------------------------
# All section tags to pull — (xml_tag, output_key, description)
# Tag names validated against Sophos XGS on-box API via probing.
# ---------------------------------------------------------------------------
CONFIG_SECTIONS = [
    # Core network
    ("Interface",            "interfaces",         "Physical + virtual interfaces"),
    ("VLAN",                 "vlans",              "VLAN sub-interfaces"),
    ("Zone",                 "zones",              "Zone definitions"),
    ("UnicastRoute",         "static_routes",      "Static/unicast routing table"),
    ("DHCPServer",           "dhcp_server",        "DHCP scopes"),
    ("DNS",                  "dns",                "DNS resolver settings"),
    # Firewall policy
    ("FirewallRule",         "firewall_rules",     "Firewall rules (allow/drop/reject)"),
    ("NATRule",              "nat_rules",          "NAT rules (SNAT/DNAT/masquerade)"),
    # IPS / IDS
    ("IPSPolicy",            "ips_policy",         "IPS/IDS policies and rule sets"),
    # Application + web + SSL filtering
    ("ApplicationFilter",    "application_filter", "Application control policies"),
    ("WebFilterPolicy",      "web_filter",         "Web filter policies and categories"),
    ("SSLTLSInspectionRule", "ssl_tls_inspection", "SSL/TLS inspection rules"),
    # VPN (may be unlicensed/unconfigured on some devices)
    ("IPSecConnection",      "ipsec_vpn",          "IPSec VPN connections"),
    ("SSLVPNClientPolicy",   "sslvpn_client",      "SSL VPN client access policies"),
    # Network objects
    ("IPHost",               "network_objects",    "Host/network address objects"),
    ("IPHostGroup",          "host_groups",        "Host/network group objects"),
    ("Services",             "service_objects",    "TCP/UDP/ICMP service objects"),
    ("ServiceGroup",         "service_groups",     "Service group objects"),
    # Users
    ("User",                 "users",              "Local admin/user accounts"),
    ("UserGroup",            "user_groups",        "User groups"),
    # QoS
    ("QoSPolicy",            "qos_policy",         "QoS / bandwidth policies"),
    # Notifications
    ("Notification",         "notifications",      "Alert notification settings"),
    ("NotificationList",     "notification_list",  "Notification contact list"),
]

# Sections that may be unsupported or unlicensed — don't flag as errors
OPTIONAL_SECTIONS = {
    "IPSecConnection", "SSLVPNClientPolicy",
    "ApplicationFilter", "SSLTLSInspectionRule", "QoSPolicy",
    "VLAN", "UserGroup",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _post_xml(ip: str, port: int, xml_str: str, timeout: int) -> str:
    """POST as form-encoded reqxml= (Sophos XGS API requires this format)."""
    url = f"https://{ip}:{port}/webconsole/APIController"
    body = urllib.parse.urlencode({"reqxml": xml_str}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _build_get(user: str, pw: str, tag: str) -> str:
    pw_escaped = (pw.replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;").replace('"', "&quot;"))
    return (
        f"<Request>"
        f"<Login><Username>{user}</Username><Password>{pw_escaped}</Password>"
        f"<ipaddress>ignore</ipaddress></Login>"
        f"<Get><{tag}/></Get>"
        f"</Request>"
    )


def _build_login(user: str, pw: str) -> str:
    pw_escaped = (pw.replace("&", "&amp;").replace("<", "&lt;")
                    .replace(">", "&gt;").replace('"', "&quot;"))
    return (
        f"<Request>"
        f"<Login><Username>{user}</Username><Password>{pw_escaped}</Password>"
        f"<ipaddress>ignore</ipaddress></Login>"
        f"</Request>"
    )


def _elem_to_dict(elem) -> dict | str | list:
    children = list(elem)
    if not children:
        return (elem.text or "").strip()
    result: dict = {}
    for child in children:
        val = _elem_to_dict(child)
        key = child.tag
        if key in result:
            if not isinstance(result[key], list):
                result[key] = [result[key]]
            result[key].append(val)
        else:
            result[key] = val
    return result


def _xml_to_dict(xml_str: str) -> dict:
    try:
        root = ET.fromstring(xml_str)
        return _elem_to_dict(root)
    except ET.ParseError:
        return {"_raw": xml_str[:800]}


def _is_unsupported(xml_str: str) -> bool:
    """True if the API says the entity is invalid / unsupported / empty."""
    return any(phrase in xml_str for phrase in (
        "Invalid entity", "not supported", "No entity found",
        "Input request module is Invalid", "404", "No records",
    ))


# ---------------------------------------------------------------------------
# Keyfile reader
# ---------------------------------------------------------------------------

def read_keyfile(code: str) -> list[dict]:
    """Return list of {hostname, wan_ip, port, username, password, serial}."""
    path = KEYS_ROOT / f"sophos-fw-{code.lower()}.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    entries = []
    for section in re.split(r"^##\s+Firewall\s+\d+", text, flags=re.MULTILINE)[1:]:
        def _f(label: str) -> str:
            m = re.search(rf"\*\*{label}:\*\*\s*(.+)", section, re.IGNORECASE)
            return m.group(1).strip() if m else ""
        port_raw = _f("API Port")
        entries.append({
            "hostname": _f("Hostname") or f"{code.upper()}-FW",
            "wan_ip":   _f("WAN IP"),
            "port":     int(port_raw) if port_raw.isdigit() else 4444,
            "username": _f("Username"),
            "password": _f("Password"),
            "serial":   _f("Serial"),
        })
    return [e for e in entries if e["wan_ip"] and e["username"]]


def discover_codes() -> list[str]:
    """Return all codes that have a sophos-fw-*.md keyfile."""
    codes = []
    for p in sorted(KEYS_ROOT.glob("sophos-fw-*.md")):
        stem = p.stem                    # sophos-fw-ani
        code = stem[len("sophos-fw-"):]  # ani
        codes.append(code)
    return codes


# ---------------------------------------------------------------------------
# Config pull for one firewall
# ---------------------------------------------------------------------------

def pull_one(code: str, cred: dict, timeout: int) -> dict:
    ip, port = cred["wan_ip"], cred["port"]
    user, pw  = cred["username"], cred["password"]
    hostname  = cred["hostname"]
    result: dict = {
        "code":      code,
        "hostname":  hostname,
        "wan_ip":    ip,
        "port":      port,
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "sections":  {},
        "errors":    [],
        "unsupported": [],
    }

    # Login check
    try:
        login_resp = _post_xml(ip, port, _build_login(user, pw), timeout)
        root = ET.fromstring(login_resp)
        code_node = root.find(".//Status")
        status_code = (code_node.get("code") or "") if code_node is not None else ""
        if status_code == "534":
            result["errors"].append("Auth blocked: scanner IP not whitelisted on this firewall")
            return result
        login_status = root.findtext(".//Login/status") or root.findtext(".//status") or ""
        if "failure" in login_status.lower() or "invalid" in login_status.lower():
            result["errors"].append(f"Authentication failed: {login_status}")
            return result
    except Exception as e:
        result["errors"].append(f"Login failed: {e}")
        return result

    # Pull each section
    ok = 0
    for tag, key, desc in CONFIG_SECTIONS:
        try:
            raw = _post_xml(ip, port, _build_get(user, pw, tag), timeout)
            if _is_unsupported(raw):
                result["unsupported"].append(tag)
            else:
                data = _xml_to_dict(raw)
                result["sections"][key] = data
                ok += 1
        except urllib.error.URLError as e:
            if tag not in OPTIONAL_SECTIONS:
                result["errors"].append(f"{tag}: {e}")
        except Exception as e:
            if tag not in OPTIONAL_SECTIONS:
                result["errors"].append(f"{tag}: {e}")

    result["sections_ok"] = ok
    result["sections_total"] = len(CONFIG_SECTIONS)
    print(f"    [{code}] {hostname} ({ip}:{port}) - {ok}/{len(CONFIG_SECTIONS)} sections pulled")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only",    help="Comma-separated codes, e.g. ani,bwh,vaf")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help=f"Per-request timeout in seconds (default {DEFAULT_TIMEOUT})")
    ap.add_argument("--workers", type=int, default=4,
                    help="Parallel worker count (default 4)")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    only = {s.strip().lower() for s in (args.only or "").split(",") if s.strip()}

    codes = discover_codes()
    if only:
        codes = [c for c in codes if c in only]

    if not codes:
        print("No keyfiles found. Create keys/sophos-fw-<code>.md first.")
        return 1

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"Extended config pull - {len(codes)} codes - date tag {today}")
    print(f"Sections: {len(CONFIG_SECTIONS)} total\n")

    tasks: list[tuple[str, dict]] = []
    for code in codes:
        for cred in read_keyfile(code):
            if cred["wan_ip"]:
                tasks.append((code, cred))

    print(f"Firewalls to pull: {len(tasks)}\n")
    all_results: list[dict] = []

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(pull_one, code, cred, args.timeout): (code, cred)
                for code, cred in tasks}
        for fut in as_completed(futs):
            code, cred = futs[fut]
            try:
                res = fut.result()
                all_results.append(res)
                out_dir = CLIENTS_ROOT / code.lower() / "sophos" / today
                out_dir.mkdir(parents=True, exist_ok=True)
                ip_slug = cred["wan_ip"].replace(".", "_")
                out_file = out_dir / f"config_extended_{ip_slug}.json"
                out_file.write_text(json.dumps(res, indent=2), encoding="utf-8")
            except Exception as e:
                print(f"  ERROR [{code} {cred['wan_ip']}]: {e}")

    # Summary
    print(f"\n{'Code':<20} {'IP':<20} {'Sections':<12} Errors")
    print("-" * 75)
    for r in sorted(all_results, key=lambda x: x["code"]):
        ok    = r.get("sections_ok", 0)
        total = r.get("sections_total", len(CONFIG_SECTIONS))
        errs  = len(r.get("errors", []))
        flag  = "! " if errs else "  "
        print(f"{flag}{r['code']:<18} {r['wan_ip']:<20} {ok}/{total:<10} "
              + (", ".join(r["errors"])[:60] if errs else "clean"))

    configured = sum(1 for r in all_results if r.get("sections_ok", 0) > 0)
    print(f"\nDone: {configured}/{len(all_results)} firewalls successfully pulled.")
    print(f"Output: clients/<code>/sophos/{today}/config_extended_<ip>.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
