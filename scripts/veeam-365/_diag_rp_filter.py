"""Probe whether /RestorePoints accepts server-side date filtering or sort."""
from veeam_client import VeeamClient
c = VeeamClient(); c._login()
queries = [
    "?backupTimeFrom=2026-04-01",
    "?dateAfter=2026-04-01T00:00:00Z",
    "?from=2026-04-01",
    "?orderBy=backupTime%20desc&limit=5",
    "?orderBy=backupTime+desc&limit=5",
    "?sort=-backupTime&limit=5",
    "?limit=5",
]
for q in queries:
    r = c.session.get(
        f"{c.base}/v8/RestorePoints{q}",
        headers={"Authorization": f"Bearer {c._access_token}", "Accept": "application/json"},
        timeout=30,
    )
    if r.status_code == 200:
        results = r.json().get("results") or []
        bts = [x.get("backupTime") for x in results[:5]]
        print(f"OK    {q:50}  first5={bts}")
    else:
        print(f"{r.status_code}   {q:50}  body={r.text[:120]}")
