"""Microsoft Graph helper for the Teams-Connector app.

Resolves teams by display name (= client code), enumerates channels,
finds the SharePoint drive backing a channel, and uploads files into a
folder under that channel.

Reads credentials from
``%USERPROFILE%/OneDrive - Technijian, Inc/Documents/VSCODE/keys/teams-connector.md``.

Permissions in the Teams-Connector app (App Client ID 331ce1b5):
    TeamMember.Read.All, Group.Read.All, Schedule.Read.All,
    Files.ReadWrite.All, Sites.ReadWrite.All

NOTE: Channel.Create is NOT in the current scope. If a "Monthly Reports"
channel doesn't already exist on a client team, this module will report
the gap and skip the upload — it will not create the channel itself.
That's a one-time human action per client team.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import requests

GRAPH = "https://graph.microsoft.com/v1.0"
KEYFILE = (
    Path(os.environ.get("USERPROFILE", str(Path.home())))
    / "OneDrive - Technijian, Inc"
    / "Documents"
    / "VSCODE"
    / "keys"
    / "teams-connector.md"
)


def _load_creds() -> tuple[str, str, str]:
    text = KEYFILE.read_text(encoding="utf-8", errors="replace")
    cid = re.search(r"App Client ID:\*\*\s*(\S+)", text).group(1)
    tid = re.search(r"Tenant ID:\*\*\s*(\S+)", text).group(1)
    sec = re.search(r"Client Secret:\*\*\s*(\S+)", text).group(1)
    return cid, tid, sec


_TOKEN_CACHE: dict = {"token": None, "expires_at": 0}


def get_token() -> str:
    if _TOKEN_CACHE["token"] and _TOKEN_CACHE["expires_at"] > time.time() + 60:
        return _TOKEN_CACHE["token"]
    cid, tid, sec = _load_creds()
    r = requests.post(
        f"https://login.microsoftonline.com/{tid}/oauth2/v2.0/token",
        data={
            "client_id": cid,
            "client_secret": sec,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    _TOKEN_CACHE["token"] = body["access_token"]
    _TOKEN_CACHE["expires_at"] = time.time() + int(body.get("expires_in", 3600))
    return _TOKEN_CACHE["token"]


def _get(url: str, **kw) -> dict:
    r = requests.get(url, headers={"Authorization": f"Bearer {get_token()}"}, timeout=60, **kw)
    r.raise_for_status()
    return r.json()


def _put_bytes(url: str, data: bytes, content_type: str) -> dict:
    r = requests.put(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {get_token()}",
            "Content-Type": content_type,
        },
        timeout=300,
    )
    r.raise_for_status()
    return r.json()


def find_team_by_displayname(name: str) -> dict | None:
    """Return the team (group) whose displayName matches ``name`` (e.g. 'AAVA').

    Matching is case-insensitive. Returns ``None`` if no match. If multiple
    groups match, returns the first one — caller's responsibility to ensure
    client codes are unique.
    """
    # Use the search-by-displayName /groups query (groups whose
    # resourceProvisioningOptions contain 'Team' are M365 Teams)
    body = _get(
        f"{GRAPH}/groups",
        params={
            "$filter": f"displayName eq '{name}'",
            "$select": "id,displayName,description,mail,resourceProvisioningOptions",
        },
    )
    for g in body.get("value", []):
        if "Team" in (g.get("resourceProvisioningOptions") or []):
            return g
    return None


def list_channels(team_id: str) -> list[dict]:
    body = _get(f"{GRAPH}/teams/{team_id}/channels")
    return body.get("value", [])


def find_channel(team_id: str, channel_name: str) -> dict | None:
    for ch in list_channels(team_id):
        if (ch.get("displayName") or "").strip().lower() == channel_name.strip().lower():
            return ch
    return None


def get_channel_folder(team_id: str, channel_id: str) -> dict:
    """Return the SharePoint driveItem that backs the channel's Files tab.

    Channel files live under the Team's SharePoint site, in a top-level
    folder named after the channel.
    """
    body = _get(f"{GRAPH}/teams/{team_id}/channels/{channel_id}/filesFolder")
    return body  # has {parentReference: {driveId,...}, id, name}


def list_drive_children(drive_id: str, item_id: str) -> list[dict]:
    body = _get(f"{GRAPH}/drives/{drive_id}/items/{item_id}/children")
    return body.get("value", [])


def find_or_create_subfolder(drive_id: str, parent_item_id: str, folder_name: str, *, create: bool) -> dict | None:
    """Return the driveItem for the subfolder. Create it under
    ``parent_item_id`` if missing and ``create=True``."""
    for child in list_drive_children(drive_id, parent_item_id):
        if (child.get("name") or "").lower() == folder_name.lower() and "folder" in child:
            return child
    if not create:
        return None
    r = requests.post(
        f"{GRAPH}/drives/{drive_id}/items/{parent_item_id}/children",
        headers={
            "Authorization": f"Bearer {get_token()}",
            "Content-Type": "application/json",
        },
        json={
            "name": folder_name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",
        },
        timeout=60,
    )
    if r.status_code == 409:
        # Race condition, refetch
        for child in list_drive_children(drive_id, parent_item_id):
            if (child.get("name") or "").lower() == folder_name.lower():
                return child
        r.raise_for_status()
    r.raise_for_status()
    return r.json()


def upload_file_to_folder(drive_id: str, folder_item_id: str, local_path: Path, *, overwrite: bool = True) -> dict:
    """Upload ``local_path`` into the folder identified by ``folder_item_id``.

    Uses the simple-upload endpoint (PUT to .../content) for files up to
    ~4 MB — Word reports we generate are well under that.
    """
    name = local_path.name
    behavior = "replace" if overwrite else "rename"
    url = (
        f"{GRAPH}/drives/{drive_id}/items/{folder_item_id}:/{requests.utils.quote(name)}:"
        f"/content?@microsoft.graph.conflictBehavior={behavior}"
    )
    return _put_bytes(url, local_path.read_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def list_team_members(team_id: str) -> list[dict]:
    """Return the team members. Used to confirm that the audience for the
    Monthly Reports channel is what we expect."""
    body = _get(f"{GRAPH}/teams/{team_id}/members")
    return body.get("value", [])
