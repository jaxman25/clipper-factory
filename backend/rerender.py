#!/usr/bin/env python3
"""Re-cut a clip with FFmpeg using new start/end times (manual editor).

    python backend/rerender.py --source in.mp4 --start 12.5 --end 48.0 --out out.mp4 \\
        --thumb out.jpg

``rerender_clip`` is the reusable function: it accepts the source video path,
the start time and the end time, runs FFmpeg, and atomically replaces the
output file (the queued .mp4) only once the render fully succeeded. When a
thumbnail path is given it is regenerated from the *new* cut as well, so the
queue preview matches the edited clip.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def rerender_clip(
    source: str | Path,
    start: float,
    end: float,
    out: str | Path,
    thumb: str | Path | None = None,
) -> Path:
    """Cut ``[start, end]`` seconds out of ``source`` into ``out``.

    The render goes to a uniquely named temporary file next to ``out`` and is
    swapped in with ``os.replace``, so readers (the dashboard's video player)
    never see a half-written file and concurrent renders cannot share a temp
    name - the same Windows-safe pattern the rest of the project uses.

    When ``thumb`` is provided a fresh thumbnail is generated from the new cut
    (cosmetic: a thumbnail failure never fails the re-render).
    """
    source = Path(source)
    out = Path(out)
    if not source.exists():
        raise FileNotFoundError(f"Source video not found: {source}")
    try:
        start = float(start)
        end = float(end)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"start/end must be numbers, got {start!r}/{end!r}") from exc
    if start < 0:
        raise ValueError(f"start must be >= 0, got {start}")
    if end <= start:
        raise ValueError(f"end ({end}) must be greater than start ({start})")

    ffmpeg = os.getenv("FFMPEG_BIN") or shutil.which("ffmpeg") or ""
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH (install ffmpeg or set FFMPEG_BIN)")

    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{out.stem}.", suffix=".mp4", dir=str(out.parent))
    os.close(fd)
    tmp = Path(tmp_name)

    duration = end - start
    cmd = [
        ffmpeg,
        "-y",
        "-ss", f"{start:.3f}",
        "-i", str(source),
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "21",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-g", "60",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-ac", "2",
        "-movflags", "+faststart",
        str(tmp),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            raise RuntimeError(
                f"FFmpeg failed (exit {result.returncode}): {(stderr or stdout)[-600:]}"
            )
        os.replace(tmp, out)
    except BaseException:
        # Only this call's own temporary file is ever removed.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    if thumb is not None:
        try:
            _make_thumbnail(out, Path(thumb), at=min(0.5, max(0.0, duration / 2)))
        except Exception as exc:  # cosmetic - keep the previous thumbnail
            print(f"warning: thumbnail not regenerated: {exc}", file=sys.stderr, flush=True)
    return out


def _make_thumbnail(video: Path, thumb: Path, at: float) -> None:
    """Grab a single frame from ``video`` into ``thumb`` (atomic replace)."""
    thumb.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{thumb.stem}.", suffix=".jpg", dir=str(thumb.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    cmd = [
        os.getenv("FFMPEG_BIN") or shutil.which("ffmpeg") or "ffmpeg",
        "-y",
        "-ss", f"{at:.2f}",
        "-i", str(video),
        "-frames:v", "1",
        "-vf", "scale=540:-2",
        "-q:v", "4",
        str(tmp),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(f"thumbnail FFmpeg failed (exit {result.returncode}): {stderr[-400:]}")
        os.replace(tmp, thumb)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-cut a clip with FFmpeg")
    parser.add_argument("--source", required=True, help="Path to the source video")
    parser.add_argument("--start", type=float, required=True, help="Start time in seconds")
    parser.add_argument("--end", type=float, required=True, help="End time in seconds")
    parser.add_argument("--out", required=True, help="Path of the video to write")
    parser.add_argument(
        "--thumb", default=None, help="Optional path for a thumbnail of the new cut"
    )
    args = parser.parse_args()
    try:
        out = rerender_clip(args.source, args.start, args.end, args.out, thumb=args.thumb)
    except Exception as exc:  # surface the reason to the API route
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
