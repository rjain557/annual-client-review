"""Print DirID + ContractID + LocationTopFilter for a list of client codes."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2] / "clients"
for c in sys.argv[1:]:
    f = ROOT / c / "_meta.json"
    if not f.exists():
        print(f"{c}: MISSING {f}")
        continue
    d = json.loads(f.read_text(encoding="utf-8"))
    ac = d.get("ActiveContract") or {}
    print(f"{c}: DirID={d.get('DirID')} ContractID={ac.get('ContractID')} Location={d.get('LocationTopFilter')!r}")
