"""Upload converted .mp4 session recordings to a Microsoft Teams channel.

Reads the destination from technijian/screenconnect-pull/state/teams-destination.json:

    {
      "team_id":      "<group GUID, e.g. 11111111-1111-1111-1111-111111111111>",
      "channel_id":   "<channel id, e.g. 19:abc...@thread.tacv2>",
      "subfolder":    "{client_code}/{year}-{month}",   // optional, supports tokens
      "rename":       "{date}_{tech}_{client}_{session_id}.mp4"  // optional rename pattern
    }

Microsoft Graph endpoints used:

    GET  /teams/{team_id}/channels/{channel_id}/filesFolder
        -> resolves the SharePoint drive + folder behind the Teams channel
    POST /drives/{drive_id}/items/{folder_id}:/{name}:/createUploadSession
        -> required for files >4MB (session recordings always are)
    PUT  <upload_url>  Content-Range: bytes ...
        -> chunked upload (10 MiB chunks; multiples of 320 KiB per Graph spec)

Auth uses the same client_credentials flow as _send-drafts.py / _secrets.py
(M365 app registration HiringPipeline-Automation), via tech-training/_secrets.

App registration scopes required (admin-consented):
    - Files.ReadWrite.All  (write to channel files folder)
    - Group.Read.All       (resolve channel filesFolder for the team)

Usage:
    # upload one MP4 (placeholder per-file substitution values via --vars)
    python upload_to_teams.py "C:\\converted\\<sessionid>.mp4" \\
        --vars client_code=BWH date=2026-04-29 tech=jdoe session_id=abc123

    # upload everything in a directory using a manifest from convert_recording.py
    python upload_to_teams.py --from-manifest "C:\\converted\\manifest.json"

    # dry run (print plan, no upload)
    python upload_to_teams.py "<path>" --dry-run

This script is config-driven and will REFUSE to run until
state/teams-destination.json exists with a valid team_id and channel_id.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

# Re-use the existing M365 secrets helper from tech-training
SCRIPTS_DIR = Path(__file__).resolve().parent
REPO = SCRIPTS_DIR.parent.parent.parent
sys.path.insert(0, str(REPO / "technijian" / "tech-training" / "scripts"))
from _secrets import get_m365_credentials  # noqa: E402

GRAPH = "https://graph.microsoft.com/v1.0"
DESTINATION_CONFIG = SCRIPTS_DIR.parent / "state" / "teams-destination.json"

CHUNK_BYTES = 10 * 1024 * 1024  # 10 MiB - must be multiple of 320 KiB
SMALL_FILE_THRESHOLD = 4 * 1024 * 1024  # 4 MiB - Graph small-upload limit


# ---------------------------------------------------------------------------
# Auth + low-level Graph helpers
# ---------------------------------------------------------------------------

def get_token() -> str:
    tenant, cid, sec, _ = get_m365_credentials()
    body = urlencode({
        "client_id": cid,
        "client_secret": sec,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode()
    req = Request(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


def graph_get(token: str, path: str) -> dict:
    req = Request(f"{GRAPH}{path}",
                  headers={"Authorization": f"Bearer {token}"})
    with urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def graph_post(token: str, path: str, body: dict) -> dict:
    req = Request(
        f"{GRAPH}{path}", method="POST",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Destination resolution
# ---------------------------------------------------------------------------

def load_destination() -> dict:
    if not DESTINATION_CONFIG.exists():
        raise FileNotFoundError(
            f"Teams destination config missing: {DESTINATION_CONFIG}\n"
            f"Copy state/teams-destination.json.template, fill in team_id "
            f"and channel_id, and re-run. See workstation.md."
        )
    cfg = json.loads(DESTINATION_CONFIG.read_text(encoding="utf-8"))
    for required in ("team_id", "channel_id"):
        v = cfg.get(required, "")
        if not v or v.startswith("TODO") or v.startswith("<"):
            raise ValueError(
                f"{DESTINATION_CONFIG.name} is missing or has placeholder "
                f"value for '{required}'. Set it to the real Graph id."
            )
    cfg.setdefault("subfolder", "")
    cfg.setdefault("rename", "")
    return cfg


def resolve_channel_drive(token: str, team_id: str, channel_id: str) -> tuple[str, str]:
    """Return (drive_id, root_folder_id) for the Teams channel files folder."""
    info = graph_get(token, f"/teams/{team_id}/channels/{channel_id}/filesFolder")
    pr = info.get("parentReference", {})
    return pr.get("driveId", ""), info.get("id", "")


def ensure_subfolder(token: str, drive_id: str, root_id: str, subpath: str) -> str:
    """Create nested folders under the channel root if needed; return final folder id."""
    if not subpath:
        return root_id
    parent = root_id
    for segment in [s for s in subpath.replace("\\", "/").split("/") if s]:
        seg = sanitize_segment(segment)
        children = graph_get(token, f"/drives/{drive_id}/items/{parent}/children?$top=200")
        match = next((c for c in children.get("value", [])
                      if c.get("name", "").lower() == seg.lower()
                      and "folder" in c), None)
        if match:
            parent = match["id"]
            continue
        created = graph_post(token, f"/drives/{drive_id}/items/{parent}/children", {
            "name": seg,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",
        })
        parent = created["id"]
    return parent


def sanitize_segment(name: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if c in bad else c for c in name).strip(" .")


# ---------------------------------------------------------------------------
# Upload (always uses upload session - recordings are always >4MB)
# ---------------------------------------------------------------------------

def upload_via_session(token: str, drive_id: str, folder_id: str, file_path: Path,
                       remote_name: str) -> dict:
    safe = quote(remote_name)
    create = graph_post(
        token,
        f"/drives/{drive_id}/items/{folder_id}:/{safe}:/createUploadSession",
        {"item": {"@microsoft.graph.conflictBehavior": "replace", "name": remote_name}},
    )
    upload_url = create["uploadUrl"]
    total = file_path.stat().st_size

    with open(file_path, "rb") as f:
        offset = 0
        while offset < total:
            chunk = f.read(CHUNK_BYTES)
            if not chunk:
                break
            end = offset + len(chunk) - 1
            req = Request(
                upload_url, method="PUT", data=chunk,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{total}",
                },
            )
            try:
                with urlopen(req, timeout=300) as resp:
                    body = resp.read()
                    if resp.status in (200, 201):
                        return json.loads(body)  # final chunk returns driveItem
            except HTTPError as e:
                # 416 / 5xx mid-upload -> bail; caller logs the failure
                raise RuntimeError(
                    f"upload chunk {offset}-{end} failed: HTTP {e.code} {e.read()[:200]!r}"
                )
            offset = end + 1
    raise RuntimeError("upload finished without final 200/201 response")


# ---------------------------------------------------------------------------
# Token substitution
# ---------------------------------------------------------------------------

def render_template(template: str, vars: dict[str, str], file_path: Path) -> str:
    if not template:
        return ""
    today = time.strftime("%Y-%m-%d")
    defaults = {
        "year":  time.strftime("%Y"),
        "month": time.strftime("%m"),
        "day":   time.strftime("%d"),
        "date":  today,
        "stem":  file_path.stem,
        "name":  file_path.name,
    }
    merged = {**defaults, **vars}
    out = template
    for k, v in merged.items():
        out = out.replace("{" + k + "}", str(v))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("path", nargs="?",
                   help="Path to a .mp4 file (or directory of .mp4 files)")
    p.add_argument("--from-manifest",
                   help="JSON manifest produced by convert_recording.py "
                        "(uploads every entry where ok=true)")
    p.add_argument("--vars", nargs="*", default=[],
                   help="Token=value pairs to substitute into "
                        "subfolder/rename templates (e.g. client_code=BWH "
                        "tech=jdoe session_id=abc123)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print plan without uploading.")
    return p.parse_args()


def collect_files(args: argparse.Namespace) -> list[Path]:
    files: list[Path] = []
    if args.path:
        p = Path(args.path)
        if p.is_dir():
            files.extend(sorted(p.rglob("*.mp4")))
        elif p.is_file() and p.suffix.lower() == ".mp4":
            files.append(p)
    if args.from_manifest:
        m = json.loads(Path(args.from_manifest).read_text(encoding="utf-8"))
        files.extend(Path(r["mp4"]) for r in m if r.get("ok") and r.get("mp4"))
    return files


def main() -> int:
    args = parse_args()
    files = collect_files(args)
    if not files:
        print("No .mp4 files to upload.", file=sys.stderr)
        return 1

    cfg = load_destination()
    vars_ = dict(v.split("=", 1) for v in args.vars if "=" in v)

    print(f"destination team:     {cfg['team_id']}")
    print(f"destination channel:  {cfg['channel_id']}")
    print(f"subfolder template:   {cfg.get('subfolder') or '(channel root)'}")
    print(f"rename template:      {cfg.get('rename') or '(keep original name)'}")
    print(f"files to upload:      {len(files)}")
    print()

    if args.dry_run:
        for f in files:
            sub = render_template(cfg["subfolder"], vars_, f)
            name = render_template(cfg["rename"], vars_, f) or f.name
            print(f"[DRY-RUN] {f}  ->  Teams:{sub}/{name}  ({f.stat().st_size/1e6:.1f} MB)")
        return 0

    print("Authenticating to Microsoft Graph...")
    token = get_token()
    drive_id, root_id = resolve_channel_drive(token, cfg["team_id"], cfg["channel_id"])
    print(f"resolved channel drive: {drive_id}\n")

    failures = 0
    for f in files:
        sub = render_template(cfg["subfolder"], vars_, f)
        name = render_template(cfg["rename"], vars_, f) or f.name
        try:
            folder_id = ensure_subfolder(token, drive_id, root_id, sub) if sub else root_id
            t0 = time.time()
            item = upload_via_session(token, drive_id, folder_id, f, name)
            took = time.time() - t0
            mb = f.stat().st_size / (1024 * 1024)
            print(f"[OK]   {f.name} -> {sub}/{name}  ({mb:.1f} MB, {took:.1f}s)")
            print(f"       webUrl: {item.get('webUrl')}")
        except Exception as e:
            failures += 1
            print(f"[FAIL] {f.name}: {e}", file=sys.stderr)

    print()
    print(f"summary: {len(files) - failures}/{len(files)} uploaded")
    return 3 if failures else 0


if __name__ == "__main__":
    sys.exit(main())