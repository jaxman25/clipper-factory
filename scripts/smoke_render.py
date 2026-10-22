#!/usr/bin/env python3
"""Smoke-test the renderer without downloading or transcribing anything.

    python3 scripts/smoke_render.py

Builds a synthetic 12 s landscape video with ffmpeg, renders one 8 s vertical
short through the real pipeline (captions, drum bed, gradient fallback) and
prints ffprobe output for the result. Useful in CI or after a code change.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import captions  # noqa: E402
import renderer  # noqa: E402

CFG = {
    "playback_speed": 1.1,
    "drum_volume_db": -22,
    "caption_color": "#FFD700",
    "caption_words_per_card": 3,
    "hook_seconds": 2,
    "outro_text": "Follow for more African tales",
    "outro_seconds": 2,
}


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="acf-smoke-"))
    source = work / "source.mp4"
    ffmpeg = renderer.which_ffmpeg()
    subprocess.run(
        [
            ffmpeg, "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
            "-t", "12", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", str(source),
        ],
        check=True,
    )

    words = [
        captions.CaptionWord(0.0, 0.6, "She"),
        captions.CaptionWord(0.65, 1.1, "warned"),
        captions.CaptionWord(1.15, 1.5, "him"),
        captions.CaptionWord(1.9, 2.4, "never"),
        captions.CaptionWord(2.45, 3.0, "go"),
        captions.CaptionWord(3.05, 3.4, "into"),
        captions.CaptionWord(3.45, 4.0, "the"),
        captions.CaptionWord(4.05, 4.7, "forest"),
        captions.CaptionWord(4.8, 5.4, "at"),
        captions.CaptionWord(5.45, 6.2, "midnight"),
    ]
    out = work / "short.mp4"
    meta = renderer.render_clip(
        source, out, 0.0, 8.0, words, CFG,
        hook="SHE WARNED HIM",
        transcript="She warned him never to go into the forest at midnight.",
        thumb_path=work / "thumb.jpg",
    )
    probe = subprocess.run(
        [renderer.which_ffprobe(), "-v", "error", "-show_streams", "-show_format",
         "-print_format", "json", str(out)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(probe.stdout)
    streams = {s["codec_type"]: s for s in data["streams"]}
    video = streams.get("video", {})
    audio = streams.get("audio", {})
    print(json.dumps(meta, indent=2))
    print(f"video: {video.get('codec_name')} {video.get('width')}x{video.get('height')} "
          f"@ {video.get('r_frame_rate')} dur={data['format'].get('duration')}")
    print(f"audio: {audio.get('codec_name')} {audio.get('sample_rate')}Hz")
    print(f"thumbnail: {(work / 'thumb.jpg').exists()} | dir: {work}")
    ok = (
        video.get("width") == 1080
        and video.get("height") == 1920
        and audio.get("codec_name") == "aac"
        and (work / "thumb.jpg").exists()
    )
    print("SMOKE " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
