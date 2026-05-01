"""Convert ScreenConnect .crv session recordings to web-friendly .mp4.

ScreenConnect (ConnectWise Control) records sessions in a proprietary .crv
container that only the ScreenConnect player can open. To make recordings
viewable in any browser / Teams / VLC / Quicktime, this helper runs a
two-step conversion:

    .crv  --(ScreenConnect.RecordingConverter.exe)-->  .avi (MJPEG)
    .avi  --(ffmpeg, libx264 + aac + faststart)-->     .mp4 (H.264)

The .avi intermediate is deleted after a successful MP4 encode unless
--keep-intermediate is passed.

Usage:
    # single file
    python convert_recording.py "C:\\path\\to\\session.crv"

    # entire directory tree (recursive)
    python convert_recording.py "C:\\path\\to\\App_Data\\Session Recordings" \\
        --output-dir "C:\\converted"

    # dry run - print the chain that would execute, no exec
    python convert_recording.py "<path>" --dry-run

Resolution order for the ScreenConnect converter:
    1) --converter <path>
    2) env var SC_CONVERTER
    3) common install dirs (Program Files (x86)\\ScreenConnect, ProgramData)
    4) error - tell the operator to install ScreenConnect or pass --converter

Resolution order for ffmpeg:
    1) --ffmpeg <path>
    2) env var FFMPEG_PATH
    3) PATH lookup
    4) error - tell the operator to install ffmpeg

Exit codes:
    0  all files converted (or dry-run printed)
    1  bad CLI arg / no inputs found
    2  converter or ffmpeg missing
    3  one or more files failed - see stderr per file
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Tool resolution
# ---------------------------------------------------------------------------

_COMMON_CONVERTER_PATHS = [
    r"C:\Program Files (x86)\ScreenConnect Client\ScreenConnect.RecordingConverter.exe",
    r"C:\Program Files (x86)\ScreenConnect\ScreenConnect.RecordingConverter.exe",
    r"C:\Program Files\ScreenConnect\ScreenConnect.RecordingConverter.exe",
    r"C:\ProgramData\ScreenConnect\ScreenConnect.RecordingConverter.exe",
]


def resolve_converter(override: Optional[str] = None) -> Path:
    if override:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(f"--converter path does not exist: {p}")
        return p
    env = os.environ.get("SC_CONVERTER")
    if env:
        p = Path(env)
        if p.exists():
            return p
    for candidate in _COMMON_CONVERTER_PATHS:
        p = Path(candidate)
        if p.exists():
            return p
    raise FileNotFoundError(
        "ScreenConnect.RecordingConverter.exe not found. "
        "Install ScreenConnect on this host or pass --converter <path>. "
        "See workstation.md §26 (ScreenConnect recording pipeline)."
    )


def resolve_ffmpeg(override: Optional[str] = None) -> Path:
    if override:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(f"--ffmpeg path does not exist: {p}")
        return p
    env = os.environ.get("FFMPEG_PATH")
    if env:
        p = Path(env)
        if p.exists():
            return p
    path = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if path:
        return Path(path)
    raise FileNotFoundError(
        "ffmpeg not found on PATH. Install via 'winget install Gyan.FFmpeg' "
        "or pass --ffmpeg <path>. See workstation.md §26 (ScreenConnect recording pipeline)."
    )


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------

def convert_one(
    crv: Path,
    out_dir: Path,
    *,
    converter: Path,
    ffmpeg: Path,
    crf: int = 23,
    preset: str = "medium",
    keep_intermediate: bool = False,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict:
    """Convert a single .crv file. Returns a metadata dict.

    The MP4 lands at <out_dir>/<crv.stem>.mp4. The .avi intermediate is
    written next to the .crv so the converter can find it (it doesn't take
    an output path argument), then moved into <out_dir> before ffmpeg runs.
    """
    if crv.suffix.lower() != ".crv":
        raise ValueError(f"not a .crv file: {crv}")
    if not crv.exists():
        raise FileNotFoundError(crv)

    out_dir.mkdir(parents=True, exist_ok=True)
    avi = out_dir / f"{crv.stem}.avi"
    mp4 = out_dir / f"{crv.stem}.mp4"

    info = {
        "crv": str(crv),
        "mp4": str(mp4),
        "crv_size_bytes": crv.stat().st_size,
        "ok": False,
        "skipped": False,
        "error": None,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if mp4.exists() and not overwrite:
        info["skipped"] = True
        info["mp4_size_bytes"] = mp4.stat().st_size
        info["note"] = "mp4 already exists; pass --overwrite to redo"
        info["ok"] = True
        return info

    if dry_run:
        info["dry_run"] = True
        info["plan"] = [
            f'{converter} "{crv}"  -> {crv.with_suffix(".avi")}',
            f'move {crv.with_suffix(".avi")} -> {avi}',
            f'{ffmpeg} -i "{avi}" -c:v libx264 -crf {crf} -preset {preset} '
            f'-c:a aac -b:a 128k -movflags +faststart -y "{mp4}"',
            ("delete " + str(avi)) if not keep_intermediate else f"keep {avi}",
        ]
        info["ok"] = True
        return info

    # Step 1: .crv -> .avi (converter writes next to input)
    avi_beside_crv = crv.with_suffix(".avi")
    t0 = time.time()
    proc = subprocess.run(
        [str(converter), str(crv)],
        capture_output=True,
        text=True,
        timeout=60 * 60,  # 1h per session is generous
    )
    if proc.returncode != 0 or not avi_beside_crv.exists():
        info["error"] = (
            f"RecordingConverter exit {proc.returncode}; "
            f"stdout={proc.stdout[:200]!r} stderr={proc.stderr[:200]!r}"
        )
        return info

    # Move the AVI into out_dir (preserves source recording path untouched)
    if avi_beside_crv != avi:
        shutil.move(str(avi_beside_crv), str(avi))
    info["avi_size_bytes"] = avi.stat().st_size
    info["crv_to_avi_seconds"] = round(time.time() - t0, 1)

    # Step 2: .avi -> .mp4 (H.264, web-streamable)
    t1 = time.time()
    ff = subprocess.run(
        [
            str(ffmpeg),
            "-i", str(avi),
            "-c:v", "libx264",
            "-crf", str(crf),
            "-preset", preset,
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-loglevel", "error",
            "-y",
            str(mp4),
        ],
        capture_output=True,
        text=True,
        timeout=60 * 60,
    )
    if ff.returncode != 0 or not mp4.exists():
        info["error"] = (
            f"ffmpeg exit {ff.returncode}; "
            f"stderr={ff.stderr[:300]!r}"
        )
        return info

    info["mp4_size_bytes"] = mp4.stat().st_size
    info["avi_to_mp4_seconds"] = round(time.time() - t1, 1)
    info["total_seconds"] = round(time.time() - t0, 1)
    info["ok"] = True

    if not keep_intermediate:
        try:
            avi.unlink()
        except OSError:
            pass

    return info


def find_crvs(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() != ".crv":
            return []
        return [input_path]
    if input_path.is_dir():
        return sorted(input_path.rglob("*.crv"))
    return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("input", help="Path to a .crv file OR a directory containing .crv files")
    p.add_argument("--output-dir",
                   help="Directory to write .mp4 (default: same as input file's parent)")
    p.add_argument("--converter", help="Override path to ScreenConnect.RecordingConverter.exe")
    p.add_argument("--ffmpeg", help="Override path to ffmpeg")
    p.add_argument("--crf", type=int, default=23,
                   help="x264 CRF (lower = bigger+higher-quality). Default 23.")
    p.add_argument("--preset", default="medium",
                   choices=["ultrafast", "veryfast", "faster", "fast",
                            "medium", "slow", "slower", "veryslow"],
                   help="x264 preset. Default medium.")
    p.add_argument("--keep-intermediate", action="store_true",
                   help="Don't delete the .avi after MP4 succeeds.")
    p.add_argument("--overwrite", action="store_true",
                   help="Re-encode even if MP4 already exists.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the conversion plan without running anything.")
    p.add_argument("--manifest",
                   help="Write a JSON manifest of all conversions to this path.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    src = Path(args.input)

    crvs = find_crvs(src)
    if not crvs:
        print(f"No .crv files found at {src}", file=sys.stderr)
        return 1

    try:
        converter = resolve_converter(args.converter)
        ffmpeg = resolve_ffmpeg(args.ffmpeg)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(f"converter: {converter}")
    print(f"ffmpeg:    {ffmpeg}")
    print(f"inputs:    {len(crvs)} .crv file(s)")
    print()

    results: list[dict] = []
    failures = 0
    for crv in crvs:
        out_dir = Path(args.output_dir) if args.output_dir else crv.parent
        try:
            r = convert_one(
                crv, out_dir,
                converter=converter, ffmpeg=ffmpeg,
                crf=args.crf, preset=args.preset,
                keep_intermediate=args.keep_intermediate,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
            )
        except Exception as e:
            r = {"crv": str(crv), "ok": False, "error": f"unexpected: {e}"}

        results.append(r)
        if r.get("dry_run"):
            print(f"[DRY-RUN] {crv.name}")
            for step in r.get("plan", []):
                print(f"   {step}")
        elif r.get("skipped"):
            print(f"[SKIP] {crv.name}  ({r.get('note')})")
        elif r.get("ok"):
            mp4_mb = r.get("mp4_size_bytes", 0) / (1024 * 1024)
            crv_mb = r.get("crv_size_bytes", 0) / (1024 * 1024)
            print(f"[OK]   {crv.name}  "
                  f"{crv_mb:.1f} MB crv -> {mp4_mb:.1f} MB mp4  "
                  f"({r.get('total_seconds', 0):.1f}s)")
        else:
            failures += 1
            print(f"[FAIL] {crv.name}  {r.get('error')}", file=sys.stderr)

    if args.manifest:
        Path(args.manifest).parent.mkdir(parents=True, exist_ok=True)
        Path(args.manifest).write_text(json.dumps(results, indent=2),
                                       encoding="utf-8")
        print(f"\nmanifest: {args.manifest}")

    print()
    print(f"summary: {len(crvs) - failures}/{len(crvs)} succeeded")
    return 3 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
