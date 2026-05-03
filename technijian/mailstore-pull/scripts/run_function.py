"""Generic invoker for any of the 122 MailStore SPE Management API functions.

Use this as the escape hatch for read or write operations the dedicated scripts
don't already wrap. The script consults /api/get-metadata to validate the
function name and required arguments before sending.

Examples:
  # List metadata for the function
  python run_function.py --describe RebuildSelectedStoreIndexes

  # List all functions matching a substring
  python run_function.py --list user

  # Read-only call
  python run_function.py GetWorkerResults instanceID=icmlending \\
      fromIncluding=2026-04-01T00:00:00Z toExcluding=2026-05-01T00:00:00Z \\
      timeZoneID=$Local profileID=0 userName=

  # Write call (long-running ops auto-poll until complete)
  python run_function.py SelectAllStoreIndexesForRebuild instanceID=orthoxpress

Output is the raw JSON result. Use --raw to also print error/statusCode/token.

Safety: write operations (Create*/Delete*/Set*/Run*/Reset*/Compact*/Verify*/
Rebuild*/Recover*/Repair*/Recreate*/Merge*/Move*/Transfer*/Upgrade*/Maintain*/
Refresh*/Cancel*/Sync*/Initialize*/Disable*/Pair*/Reload*/Send*/Stop*/Start*/
Restart*/Freeze*/Thaw*/Attach*/Detach*/Test*) require --confirm.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from spe_client import Client, SPEError

WRITE_PREFIXES = ("Create","Delete","Set","Run","Reset","Compact","Verify","Rebuild",
                  "Recover","Repair","Recreate","Merge","Move","Transfer","Upgrade",
                  "Maintain","Refresh","Cancel","Sync","Initialize","Disable","Pair",
                  "Reload","Send","Stop","Start","Restart","Freeze","Thaw","Attach",
                  "Detach","Test","Clear","Retry","Rename")


def is_write(fn: str) -> bool:
    return any(fn.startswith(p) for p in WRITE_PREFIXES)


def parse_kv(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"bad arg {item!r} — expected key=value")
        k, v = item.split("=", 1)
        out[k.strip()] = v
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Invoke any MailStore SPE Management API function.")
    ap.add_argument("--list", dest="list_pat", default=None, help="List functions matching this substring (case-insensitive).")
    ap.add_argument("--describe", default=None, help="Print arg list for a single function.")
    ap.add_argument("--confirm", action="store_true", help="Required for write/mutating functions.")
    ap.add_argument("--raw", action="store_true", help="Print full envelope, not just result.")
    ap.add_argument("function", nargs="?", help="Function name, e.g. GetUsers")
    ap.add_argument("kvs", nargs="*", help="Arguments as key=value")
    args = ap.parse_args(argv)

    c = Client()
    md = c.metadata()

    if args.list_pat is not None:
        pat = args.list_pat.lower()
        names = sorted(n for n in md if pat in n.lower())
        for n in names:
            sig = ", ".join(f"{a['name']}:{a.get('type','?')}" for a in md[n].get("args", []))
            print(f"  {n}({sig})")
        print(f"\n{len(names)} match(es). Total functions: {len(md)}")
        return 0

    if args.describe:
        f = md.get(args.describe)
        if not f:
            print(f"Function {args.describe!r} not in metadata. Try --list {args.describe}", file=sys.stderr)
            return 2
        print(json.dumps(f, indent=2))
        return 0

    if not args.function:
        ap.print_usage()
        return 2

    fn = args.function
    f = md.get(fn)
    if not f:
        print(f"Function {fn!r} not in metadata. Try --list <substr>", file=sys.stderr)
        return 2

    params = parse_kv(args.kvs)
    valid = {a["name"] for a in f.get("args", [])}
    extra = set(params) - valid
    if extra:
        print(f"WARN: arguments not in metadata for {fn}: {sorted(extra)}", file=sys.stderr)
    required = [a["name"] for a in f.get("args", []) if not a.get("nullable", False)]
    missing = [a for a in required if a not in params]
    if missing:
        print(f"Missing required arg(s): {missing}", file=sys.stderr)
        print(f"Function signature: {fn}({', '.join(a['name']+':'+a.get('type','?') for a in f.get('args',[]))})")
        return 2

    if is_write(fn) and not args.confirm:
        print(f"REFUSE: {fn} appears to be a write/mutating function. Pass --confirm to proceed.", file=sys.stderr)
        return 3

    try:
        if args.raw:
            envelope = c.invoke_raw(fn, **params)
            print(json.dumps(envelope, indent=2, default=str))
        else:
            result = c.invoke(fn, **params)
            print(json.dumps(result, indent=2, default=str))
    except SPEError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
