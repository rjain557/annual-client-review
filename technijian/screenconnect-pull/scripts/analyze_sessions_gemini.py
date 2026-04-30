"""Analyze ScreenConnect session MP4s using the Gemini Files API.

Scans the OneDrive FileCabinet for converted MP4s, uploads each to Gemini,
asks a structured question about what the technician did, and writes a
per-session JSON summary alongside the existing per-client audit data.

Output:
  clients/<code>/screenconnect/<year>/session_analysis/<stem>.json

State file (skip already-analyzed):
  technijian/screenconnect-pull/state/gemini_analysis_state.json

Usage:
    python analyze_sessions_gemini.py --all
    python analyze_sessions_gemini.py --client BWH
    python analyze_sessions_gemini.py --client BWH --dry-run
    python analyze_sessions_gemini.py --client BWH --reanalyze
    python analyze_sessions_gemini.py --all --limit 50 --year 2026
    python analyze_sessions_gemini.py --all --month 2026-04
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── repo / path constants ──────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parents[3]
KEYS_DIR    = Path(r"C:\Users\rjain\OneDrive - Technijian, Inc\Documents\VSCODE\keys")
CABINET_DIR = Path(r"C:\Users\rjain\OneDrive - Technijian, Inc\Technijian - My Remote - FileCabinet")
STATE_FILE  = REPO_ROOT / "technijian" / "screenconnect-pull" / "state" / "gemini_analysis_state.json"

MODEL = "gemini-2.5-flash"

ANALYSIS_PROMPT = """You are reviewing a ScreenConnect remote support session recording.
A Technijian IT technician connected remotely to a client computer and performed IT support work.

Analyze this screen recording and return a JSON object — nothing else, no markdown fences:
{
  "summary": "2-3 sentence plain-English summary of what was done",
  "session_type": "one of: maintenance, troubleshooting, installation, configuration, training, monitoring, other",
  "actions_taken": ["specific actions the technician performed, most important first"],
  "applications_used": ["applications or tools opened during the session"],
  "issues_observed": ["problems or error messages visible"],
  "issues_resolved": ["problems that appear to have been fixed"],
  "machines_touched": ["computer names, server names, or IP addresses visible in the recording"],
  "notable_events": ["anything unusual, time-consuming, or worth flagging for the client report"],
  "concerns": ["any security, compliance, or quality concerns — empty array if none"],
  "estimated_productivity": "high | medium | low — based on work accomplished vs time spent",

  "tech_performance": {
    "appeared_stuck": "true | false — tech visibly repeated the same action, searched the same thing multiple times, or showed no clear direction for more than 2 minutes",
    "stuck_details": ["describe each stuck moment: what they were trying, how long, what broke the loop — empty if none"],
    "idle_gaps": ["describe each gap >60 seconds where screen was static or mouse inactive — include approximate timestamp and duration — empty if none"],
    "idle_gap_count": 0,
    "longest_idle_seconds": 0,
    "total_idle_estimate_seconds": 0,
    "efficiency_notes": "brief assessment of whether the tech worked methodically or seemed uncertain — e.g. 'straight to Event Viewer, found root cause in 3 min' vs 'tried 4 different things without a clear plan'",
    "coaching_flags": ["specific behaviors worth reviewing with the tech — e.g. 'did not check Windows Update before manual driver install', 'left RDP session open after work completed' — empty if none"]
  }
}"""


# ── credentials ────────────────────────────────────────────────────────────────

def _load_gemini_api_key() -> str | None:
    # Keyfile takes priority — env var is fallback for headless/CI use only.
    # This avoids stale GEMINI_API_KEY env vars overriding a freshly updated keyfile.
    kf = KEYS_DIR / "gemini.md"
    if kf.exists():
        text = kf.read_text(encoding="utf-8")
        m = re.search(r"\*\*API Key:\*\*\s*([^\s\r\n]+)", text)
        if m:
            val = m.group(1).strip()
            if not val.startswith("TODO") and not val.startswith("PASTE"):
                return val
    return os.environ.get("GEMINI_API_KEY")


def _build_client() -> "genai.Client":  # type: ignore[name-defined]
    try:
        from google import genai  # type: ignore[import-untyped]
    except ImportError:
        print("ERROR: google-genai not installed. Run: pip install google-genai", file=sys.stderr)
        sys.exit(1)

    api_key = _load_gemini_api_key()
    if api_key:
        return genai.Client(api_key=api_key)
    # Fallback: Application Default Credentials (gcloud auth application-default login)
    print("INFO: No Gemini API key found in env/keyfile — trying ADC (Application Default Credentials)")
    return genai.Client()


# ── state tracking ─────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"analyzed": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── OneDrive FileCabinet scanning ──────────────────────────────────────────────

_FOLDER_RE = re.compile(r"^([A-Z][A-Z0-9]+)-(\d{4})-(\d{2})$", re.IGNORECASE)


def _scan_cabinet(
    year: int | None = None,
    month: str | None = None,
    only_clients: list[str] | None = None,
) -> dict[str, list[Path]]:
    """Return {client_code: [mp4_path, ...]} for all matching MP4s in the FileCabinet."""
    result: dict[str, list[Path]] = {}
    if not CABINET_DIR.exists():
        print(f"WARNING: FileCabinet not found at {CABINET_DIR}")
        return result

    for folder in sorted(CABINET_DIR.iterdir()):
        if not folder.is_dir():
            continue
        m = _FOLDER_RE.match(folder.name)
        if not m:
            continue
        code, yr, mo = m.group(1).upper(), int(m.group(2)), m.group(3)
        if year and yr != year:
            continue
        if month and f"{yr}-{mo}" != month:
            continue
        if only_clients and code not in [c.upper() for c in only_clients]:
            continue
        mp4s = sorted(folder.glob("*.mp4"))
        if mp4s:
            result.setdefault(code, []).extend(mp4s)

    return result


# ── Gemini upload + analyze ────────────────────────────────────────────────────

def _upload_and_wait(client, mp4_path: Path) -> object:
    from google.genai import types  # type: ignore[import-untyped]

    print(f"  Uploading {mp4_path.name} ({mp4_path.stat().st_size // 1_048_576} MB)...")
    file_obj = client.files.upload(
        file=str(mp4_path),
        config=types.UploadFileConfig(mime_type="video/mp4", display_name=mp4_path.stem),
    )
    # Poll until ACTIVE (Gemini processes video server-side)
    for _ in range(120):  # max ~10 min
        if file_obj.state.name == "ACTIVE":
            break
        if file_obj.state.name == "FAILED":
            raise RuntimeError(f"Gemini file processing failed for {mp4_path.name}")
        time.sleep(5)
        file_obj = client.files.get(name=file_obj.name)
    else:
        raise TimeoutError(f"Gemini file never became ACTIVE: {mp4_path.name}")
    return file_obj


def _analyze(client, file_obj, mp4_path: Path) -> dict:
    from google.genai import types  # type: ignore[import-untyped]

    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_uri(file_uri=file_obj.uri, mime_type="video/mp4"),
            ANALYSIS_PROMPT,
        ],
    )
    raw = response.text.strip()

    # Strip markdown fences if model added them anyway
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"summary": raw, "parse_error": True}

    return {"raw_response": response.text, "analysis": parsed}


def _delete_file(client, file_obj) -> None:
    try:
        client.files.delete(name=file_obj.name)
    except Exception:
        pass  # auto-expires in 48h regardless


# ── per-session output ─────────────────────────────────────────────────────────

_REC_RE = re.compile(
    r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"-(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})"
    r"-(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})$",
    re.IGNORECASE,
)


def _parse_stem(stem: str) -> dict:
    m = _REC_RE.match(stem)
    if not m:
        return {"filename_stem": stem}
    def _dt(s: str) -> str:
        return datetime(*[int(x) for x in s.split("-")], tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "session_id":   m.group(1),
        "connection_id": m.group(2),
        "recording_start": _dt(m.group(3)),
        "recording_end":   _dt(m.group(4)),
    }


def _write_result(client_code: str, year: int, mp4_path: Path, result: dict) -> Path:
    out_dir = REPO_ROOT / "clients" / client_code.lower() / "screenconnect" / str(year) / "session_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{mp4_path.stem}.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out_path


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze ScreenConnect MP4s with Gemini")
    ap.add_argument("--client", help="Single client code, e.g. BWH")
    ap.add_argument("--all", action="store_true", help="All clients in FileCabinet")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--month", help="Limit to YYYY-MM, e.g. 2026-04")
    ap.add_argument("--limit", type=int, default=0, help="Max sessions to process (0 = unlimited)")
    ap.add_argument("--dry-run", action="store_true", help="Print what would be analyzed, no API calls")
    ap.add_argument("--reanalyze", action="store_true", help="Re-analyze already-processed sessions")
    args = ap.parse_args()

    if not args.client and not args.all:
        ap.error("Specify --client <CODE> or --all")

    only = [args.client.upper()] if args.client else None
    cabinet = _scan_cabinet(year=args.year, month=args.month, only_clients=only)

    if not cabinet:
        print("No MP4s found in FileCabinet. Has pull_screenconnect_2026.py run yet?")
        return

    state = _load_state()
    analyzed_set: set[str] = set(state.get("analyzed", {}).keys())

    # Build work queue
    queue: list[tuple[str, Path]] = []
    for code, paths in sorted(cabinet.items()):
        for mp4 in paths:
            key = f"{code}/{mp4.name}"
            if key in analyzed_set and not args.reanalyze:
                continue
            queue.append((code, mp4))

    print(f"Found {sum(len(v) for v in cabinet.values())} MP4s across {len(cabinet)} clients")
    print(f"Queue: {len(queue)} sessions to analyze (skip already done={not args.reanalyze})")

    if args.dry_run:
        for code, mp4 in queue[:20]:
            print(f"  [{code}] {mp4.name}")
        if len(queue) > 20:
            print(f"  ... and {len(queue) - 20} more")
        return

    if not queue:
        print("Nothing to do.")
        return

    client = _build_client()
    processed = 0
    errors = 0

    for code, mp4 in queue:
        if args.limit and processed >= args.limit:
            print(f"\nReached --limit {args.limit}. Stopping.")
            break

        stem_meta = _parse_stem(mp4.stem)
        # Infer year from folder name (e.g. BWH-2026-04)
        folder_year = int(mp4.parent.name.split("-")[1]) if "-" in mp4.parent.name else args.year

        print(f"\n[{code}] {mp4.name}")
        file_obj = None
        try:
            file_obj = _upload_and_wait(client, mp4)
            print(f"  Analyzing with {MODEL}...")
            result = _analyze(client, file_obj, mp4)

            record = {
                **stem_meta,
                "client_code": code,
                "mp4_path": str(mp4),
                "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "model": MODEL,
                **result,
            }
            out = _write_result(code, folder_year, mp4, record)
            print(f"  -> {out.relative_to(REPO_ROOT)}")
            print(f"  Summary: {result['analysis'].get('summary', '')[:120]}")

            state.setdefault("analyzed", {})[f"{code}/{mp4.name}"] = {
                "analyzed_at": record["analyzed_at"],
                "output_path": str(out),
                "model": MODEL,
            }
            _save_state(state)
            processed += 1

        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            errors += 1
        finally:
            if file_obj:
                _delete_file(client, file_obj)

    print(f"\nDone. Processed={processed}, Errors={errors}")
    print(f"State: {STATE_FILE}")


if __name__ == "__main__":
    main()
