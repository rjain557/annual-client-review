"""Sophos XGS on-box API scanner and config puller.

Reads WAN IPs from the latest daily Sophos pull (clients/<code>/sophos/<date>/firewalls.json),
probes each firewall's admin API on port 4444, and — when credentials are available in
OneDrive keyvault — pulls full configuration (interfaces, firewall rules, NAT, VPN, DHCP).

State file: technijian/sophos-pull/state/firewall-api-inventory.json
  api_status values:
    not_whitelisted   — port 4444 timed out / connection refused
    reachable         — port open, HTTPS responds, but no credentials yet
    configured        — credentials available, config pull succeeded
    auth_failed       — credentials in keyfile but authentication rejected

Keyfile pattern (one per client):
  %USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/sophos-fw-<CODE>.md

  Format (one Firewall section per physical device):
    ## Firewall 1
    - **Hostname:** client-fw-01
    - **WAN IP:** 203.0.113.45
    - **API Port:** 4444
    - **Username:** technijian-api
    - **Password:** <password>
    - **Serial:** F211ABCDEFGH

Usage:
    python scan_sophos_fw_api.py                  # probe all, no config pull
    python scan_sophos_fw_api.py --pull           # probe + pull config where credentials exist
    python scan_sophos_fw_api.py --only BWH,ORX   # limit to specific clients
    python scan_sophos_fw_api.py --timeout 10     # TCP timeout per host (default 5s)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import ssl
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPELINE_ROOT = HERE.parent
REPO = PIPELINE_ROOT.parent.parent
CLIENTS_ROOT = REPO / "clients"
STATE_DIR = PIPELINE_ROOT / "state"
INVENTORY_FILE = STATE_DIR / "firewall-api-inventory.json"

DEFAULT_TIMEOUT = 5
API_PORT = 4444


# ---------------------------------------------------------------------------
# Credential reading
# ---------------------------------------------------------------------------

def _read_keyvault_fw(code: str) -> list[dict]:
    """Read sophos-fw-<CODE>.md from OneDrive keyvault.

    Returns list of dicts: {hostname, wan_ip, port, username, password, serial}
    """
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    path = Path(home) / "OneDrive - Technijian, Inc" / "Documents" / "VSCODE" / "keys" / f"sophos-fw-{code}.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    entries = []
    # Split on ## Firewall N sections
    sections = re.split(r"^##\s+Firewall\s+\d+", text, flags=re.MULTILINE)
    for section in sections[1:]:
        def _field(label: str) -> str:
            m = re.search(rf"\*\*{label}:\*\*\s*(\S+)", section, re.IGNORECASE)
            return m.group(1) if m else ""
        entries.append({
            "hostname": _field("Hostname"),
            "wan_ip": _field("WAN IP"),
            "port": int(_field("API Port") or API_PORT),
            "username": _field("Username"),
            "password": _field("Password"),
            "serial": _field("Serial"),
        })
    return entries


# ---------------------------------------------------------------------------
# Port probe
# ---------------------------------------------------------------------------

def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def probe_port(ip: str, port: int = API_PORT, timeout: int = DEFAULT_TIMEOUT) -> bool:
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def probe_https(ip: str, port: int = API_PORT, timeout: int = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    """Returns (responds, note)."""
    url = f"https://{ip}:{port}/webconsole/APIController"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=timeout) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return True, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, f"URLError: {str(e.reason)[:60]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"


# ---------------------------------------------------------------------------
# Config pull (requires credentials)
# ---------------------------------------------------------------------------

CONFIG_SECTIONS = [
    ("InterfaceList", "interfaces"),
    ("LANInterface", "lan_interfaces"),
    ("WANInterface", "wan_interfaces"),
    ("FirewallRule", "firewall_rules"),
    ("NATRule", "nat_rules"),
    ("IPSecConnection", "ipsec_vpn"),
    ("SSLVPNClientPolicy", "sslvpn"),
    ("DHCPServer", "dhcp_server"),
    ("DNSConfig", "dns"),
    ("StaticRoute", "static_routes"),
]


def _build_login_xml(username: str, password: str) -> bytes:
    return (
        f"<Request>"
        f"<Login><Username>{username}</Username><Password>{password}</Password>"
        f"<ipaddress>ignore</ipaddress></Login>"
        f"</Request>"
    ).encode("utf-8")


def _build_get_xml(username: str, password: str, section_tag: str) -> bytes:
    return (
        f"<Request>"
        f"<Login><Username>{username}</Username><Password>{password}</Password>"
        f"<ipaddress>ignore</ipaddress></Login>"
        f"<Get><{section_tag}/></Get>"
        f"</Request>"
    ).encode("utf-8")


def _post_xml(ip: str, port: int, xml_body: bytes, timeout: int) -> str:
    url = f"https://{ip}:{port}/webconsole/APIController"
    req = urllib.request.Request(url, data=xml_body,
                                  headers={"Content-Type": "application/xml"},
                                  method="POST")
    with urllib.request.urlopen(req, context=_ssl_context(), timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _xml_to_dict(xml_str: str) -> dict:
    """Best-effort XML->dict for config sections."""
    try:
        root = ET.fromstring(xml_str)
        return _elem_to_dict(root)
    except ET.ParseError:
        return {"_raw": xml_str[:500]}


def _elem_to_dict(elem) -> dict | str | list:
    children = list(elem)
    if not children:
        return (elem.text or "").strip()
    result = {}
    for child in children:
        val = _elem_to_dict(child)
        if child.tag in result:
            if not isinstance(result[child.tag], list):
                result[child.tag] = [result[child.tag]]
            result[child.tag].append(val)
        else:
            result[child.tag] = val
    return result


def pull_fw_config(ip: str, port: int, username: str, password: str,
                   timeout: int = 15) -> tuple[bool, str, dict]:
    """Returns (success, note, config_dict)."""
    # 1) Test login
    try:
        resp_xml = _post_xml(ip, port, _build_login_xml(username, password), timeout)
        root = ET.fromstring(resp_xml)
        login_node = root.find(".//Login")
        if login_node is not None:
            status = (login_node.findtext("status") or
                      login_node.findtext("Status") or "").strip()
            if status.lower() not in ("authentication successful", "success", ""):
                return False, f"Auth failed: {status}", {}
    except ET.ParseError as e:
        return False, f"XML parse error on login: {e}", {}
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} on login", {}
    except Exception as e:
        return False, f"Login error: {type(e).__name__}: {str(e)[:80]}", {}

    # 2) Pull each config section
    config: dict = {}
    for section_tag, config_key in CONFIG_SECTIONS:
        try:
            resp_xml = _post_xml(ip, port,
                                  _build_get_xml(username, password, section_tag),
                                  timeout)
            config[config_key] = _xml_to_dict(resp_xml)
        except Exception as e:
            config[config_key] = {"_error": str(e)[:120]}

    return True, "config pulled", config


# ---------------------------------------------------------------------------
# Inventory helpers
# ---------------------------------------------------------------------------

def load_inventory() -> dict:
    if INVENTORY_FILE.exists():
        try:
            return json.loads(INVENTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"clients": {}}


def save_inventory(inv: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    inv["last_scan"] = datetime.now(timezone.utc).isoformat()
    INVENTORY_FILE.write_text(json.dumps(inv, indent=2), encoding="utf-8")


def load_latest_fw_data(code: str) -> list[dict]:
    """Load firewalls from most recent daily pull for this client."""
    sophos_dir = CLIENTS_ROOT / code.lower() / "sophos"
    if not sophos_dir.exists():
        return []
    date_dirs = sorted(p for p in sophos_dir.iterdir()
                       if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}", p.name))
    if not date_dirs:
        return []
    fw_path = date_dirs[-1] / "firewalls.json"
    if not fw_path.exists():
        return []
    try:
        return json.loads(fw_path.read_text(encoding="utf-8"))
    except Exception:
        return []


def get_my_wan_ip() -> str:
    try:
        return urllib.request.urlopen(
            "https://api.ipify.org", timeout=5).read().decode().strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Main scan task
# ---------------------------------------------------------------------------

def scan_client(code: str, do_pull: bool, timeout: int) -> list[dict]:
    fw_data = load_latest_fw_data(code)
    if not fw_data:
        return []

    creds_by_serial = {c["serial"]: c for c in _read_keyvault_fw(code) if c.get("serial")}
    creds_by_ip = {c["wan_ip"]: c for c in _read_keyvault_fw(code) if c.get("wan_ip")}

    rows = []
    for fw in fw_data:
        ips = fw.get("externalIpv4Addresses") or []
        serial = fw.get("serialNumber") or ""
        hostname = fw.get("hostname") or fw.get("name") or "?"
        model = (fw.get("model") or "").split("_SFOS")[0]
        firmware = fw.get("firmwareVersion") or ""

        for ip in ips:
            row = {
                "code": code,
                "hostname": hostname,
                "serial": serial,
                "model": model,
                "firmware": firmware,
                "wan_ip": ip,
                "api_port": API_PORT,
                "api_status": "not_whitelisted",
                "note": "",
                "config_pulled_at": None,
            }

            # Probe port
            port_open = probe_port(ip, API_PORT, timeout)
            if not port_open:
                row["api_status"] = "not_whitelisted"
                row["note"] = "port 4444 closed/filtered"
                rows.append(row)
                continue

            # Probe HTTPS
            https_ok, note = probe_https(ip, API_PORT, timeout)
            if not https_ok:
                row["api_status"] = "port_open_no_https"
                row["note"] = note
                rows.append(row)
                continue

            row["api_status"] = "reachable"
            row["note"] = note

            # Pull config if credentials available
            if do_pull:
                creds = creds_by_serial.get(serial) or creds_by_ip.get(ip)
                if creds:
                    success, pull_note, config = pull_fw_config(
                        ip, API_PORT, creds["username"], creds["password"], timeout=20)
                    if success:
                        row["api_status"] = "configured"
                        row["note"] = pull_note
                        row["config_pulled_at"] = datetime.now(timezone.utc).isoformat()
                        # Save config snapshot
                        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                        out_dir = CLIENTS_ROOT / code.lower() / "sophos" / today
                        out_dir.mkdir(parents=True, exist_ok=True)
                        config_path = out_dir / "config.json"
                        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
                        print(f"  [{code}] {hostname} ({ip}) — config saved to {config_path.relative_to(REPO)}")
                    else:
                        row["api_status"] = "auth_failed"
                        row["note"] = pull_note
                else:
                    row["note"] += " | no keyfile credentials"

            rows.append(row)

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Scan Sophos XGS firewalls for on-box API access.")
    ap.add_argument("--pull", action="store_true",
                    help="Pull config where credentials are available in keyvault")
    ap.add_argument("--only", help="Comma-separated client codes")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help=f"TCP timeout in seconds (default {DEFAULT_TIMEOUT})")
    ap.add_argument("--update-ip", action="store_true",
                    help="Refresh scanner IP from api.ipify.org and save to inventory")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    only = {s.strip().upper() for s in args.only.split(",")} if args.only else None

    inv = load_inventory()

    if args.update_ip or "technijian_scanner_ip" not in inv:
        print("Fetching current WAN IP...")
        inv["technijian_scanner_ip"] = get_my_wan_ip()
        print(f"  Scanner IP: {inv['technijian_scanner_ip']}")
        print(f"  Add this to each XGS: Administration > Device Access > WAN > HTTPS + API > Allowed IPs")
        print()

    # Discover all clients with Sophos data
    # Path shape: clients/<code>/sophos/<date>/firewalls.json
    codes = sorted(set(
        p.parent.parent.parent.name.upper()
        for p in CLIENTS_ROOT.glob("*/sophos/*/firewalls.json")
        if not p.parent.name.startswith("_") and not p.parent.name == "reports"
    ))
    if only:
        codes = [c for c in codes if c in only]

    print(f"[{datetime.now():%H:%M:%S}] Scanning {len(codes)} clients (timeout={args.timeout}s, pull={args.pull})")
    print()

    all_rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(scan_client, c, args.pull, args.timeout): c for c in codes}
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                rows = fut.result()
                all_rows.extend(rows)
            except Exception as e:
                print(f"  ERROR [{code}]: {e}")

    all_rows.sort(key=lambda r: (r["code"], r["wan_ip"]))

    # Print table
    hdr = f"{'CODE':<8} {'HOSTNAME':<25} {'WAN IP':<18} {'STATUS':<18} NOTE"
    print(hdr)
    print("-" * 100)
    for r in all_rows:
        status = r["api_status"].upper()
        print(f"{r['code']:<8} {r['hostname']:<25} {r['wan_ip']:<18} {status:<18} {r['note']}")

    # Update inventory state
    clients_inv: dict[str, list[dict]] = {}
    for r in all_rows:
        clients_inv.setdefault(r["code"], [])
        clients_inv[r["code"]].append(r)
    inv["clients"] = clients_inv
    inv.setdefault("note", (
        "Whitelist the technijian_scanner_ip on each XGS: "
        "Administration -> Device Access -> WAN zone -> HTTPS + API -> Allowed IP addresses. "
        "Then add credentials to OneDrive/keys/sophos-fw-<CODE>.md and run --pull."
    ))
    save_inventory(inv)
    print(f"\nInventory saved to {INVENTORY_FILE.relative_to(REPO)}")

    # Summary
    accessible = [r for r in all_rows if r["api_status"] in ("reachable", "configured")]
    configured = [r for r in all_rows if r["api_status"] == "configured"]
    needs_wl = [r for r in all_rows if r["api_status"] == "not_whitelisted"]
    print(f"\nSUMMARY: {len(all_rows)} firewalls total")
    print(f"  {len(configured):<3} configured (config pulled)")
    print(f"  {len(accessible) - len(configured):<3} reachable (no creds yet)")
    print(f"  {len(needs_wl):<3} need whitelist ({inv.get('technijian_scanner_ip','?')} not allowed on port 4444)")

    if needs_wl:
        print(f"\nTo whitelist, go to each firewall's admin UI and add:")
        print(f"  IP: {inv.get('technijian_scanner_ip','<scanner IP>')}")
        print(f"  Location: Administration -> Device Access -> WAN -> HTTPS + API -> Allowed IP addresses")
        print()
        for r in needs_wl:
            print(f"  {r['code']:<8} {r['hostname']:<28} admin URL: https://{r['wan_ip']}:{r['api_port']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
