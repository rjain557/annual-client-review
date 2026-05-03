"""
Probe a list of candidate VB365 endpoints to learn which exist on the
target server and what they return. Outputs a markdown summary to stdout
plus a json dump of one full sample per endpoint.
"""
from __future__ import annotations
import json, sys, requests
from veeam_client import VeeamClient

c = VeeamClient()
c._login()

# Pick the first org for per-org probes
orgs = c.list_organizations()
o = next((x for x in orgs if x.get("name") in ("BWH", "JDH")), orgs[0])
oid = o["id"]
print(f"# Probing using org {o.get('name')} ({oid})\n", file=sys.stderr)

# Get one user, one job, one repo to drill into
users_first = next(iter(c.get_paginated(f"/Organizations/{oid}/users", limit=1)), None)
uid = users_first["id"] if users_first else None
jobs = c.list_jobs()
job_for_org = next((j for j in jobs if j.get("organizationId") == oid), None)
jid = job_for_org["id"] if job_for_org else None
repos = c.list_backup_repositories()
rid = repos[0]["id"] if repos else None

PATHS = [
    # tenant-scoped collections
    f"/Organizations/{oid}/Mailboxes",
    f"/Organizations/{oid}/OneDrives",
    f"/Organizations/{oid}/Teams",
    f"/Organizations/{oid}/Sites",
    f"/Organizations/{oid}/Groups",
    f"/Organizations/{oid}/Statistics",
    f"/Organizations/{oid}/Backups",
    f"/Organizations/{oid}/UsersAndGroups",
    f"/Organizations/{oid}/exploreVbo",
    # per-user sub-resources (drill into one user)
    f"/Organizations/{oid}/users/{uid}/mailbox" if uid else None,
    f"/Organizations/{oid}/users/{uid}/archiveMailbox" if uid else None,
    f"/Organizations/{oid}/users/{uid}/onedrives" if uid else None,
    f"/Organizations/{oid}/users/{uid}/sites" if uid else None,
    # job-level
    f"/Jobs/{jid}/Statistics" if jid else None,
    f"/Jobs/{jid}/jobsessions" if jid else None,
    f"/Jobs/{jid}/jobsessions?limit=1" if jid else None,
    # repo-level
    f"/BackupRepositories/{rid}/OrganizationUsers?organizationId={oid}" if rid else None,
    f"/BackupRepositories/{rid}/OrganizationGroups" if rid else None,
    f"/BackupRepositories/{rid}/OrganizationSites" if rid else None,
    f"/BackupRepositories/{rid}/OrganizationTeams" if rid else None,
    f"/BackupRepositories/{rid}/Statistics" if rid else None,
    # global
    "/RestorePoints",
    "/RestorePoints?limit=1",
    "/Backups",
    "/Explorers",
    "/RestoreSessions?limit=1",
    "/JobSessions?limit=1",
    "/License",
    "/ServerSettings",
]

out = {}
for p in PATHS:
    if p is None:
        continue
    try:
        url = c._full_url(p)
        r = c.session.get(
            url,
            headers={"Authorization": f"Bearer {c._access_token}", "Accept": "application/json"},
            timeout=30,
        )
    except requests.RequestException as e:
        out[p] = {"error": str(e)}
        continue
    status = r.status_code
    body = None
    try:
        body = r.json()
    except ValueError:
        body = (r.text[:200] if r.text else None)
    sample = None
    if isinstance(body, dict) and isinstance(body.get("results"), list) and body["results"]:
        sample = body["results"][0]
        keys = sorted(sample.keys()) if isinstance(sample, dict) else []
    elif isinstance(body, list) and body:
        sample = body[0]
        keys = sorted(sample.keys()) if isinstance(sample, dict) else []
    elif isinstance(body, dict):
        sample = body
        keys = sorted(body.keys())
    else:
        keys = []
    out[p] = {
        "status": status,
        "type": type(body).__name__,
        "keys": keys[:20],
        "sample": sample if isinstance(sample, dict) else None,
    }
    flag = "OK " if status == 200 else f"{status}"
    print(f"{flag}  {p}  keys={keys[:8]}", file=sys.stderr)

print(json.dumps(out, indent=2, default=str))
