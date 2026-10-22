#!/usr/bin/env python3
"""Generate the royalty-free audio beds used by the renderer.

The project ships no copyrighted samples. Two beds are synthesized locally with
the Python standard library so a fresh clone (or a Render container) has usable
assets without any download or license risk:

  assets/drum_loop.wav      - 8 second afrobeat-style percussion loop (120 BPM)
  assets/night_ambience.wav - 16 second night-cricket / wind ambience bed
  assets/gradient.png       - 1080x1920 cinematic dark gradient (via ffmpeg)

Re-running the script is safe; existing files are kept unless --force is passed.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import shutil
import struct
import subprocess
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
SR = 44100


def _write_wav(path: str, samples: list[float]) -> None:
    peak = max(1e-9, max(abs(s) for s in samples))
    scale = 0.89 / peak
    frames = bytearray()
    for s in samples:
        v = int(max(-1.0, min(1.0, s * scale)) * 32767)
        frames += struct.pack("<hh", v, v)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(bytes(frames))


def _kick(t: float, dur: float = 0.35) -> float:
    if t >= dur:
        return 0.0
    env = math.exp(-t * 16)
    pitch = 120 * math.exp(-t * 28) + 42
    return math.sin(2 * math.pi * pitch * t) * env * 0.95


def _snare(t: float, dur: float = 0.18) -> float:
    if t >= dur:
        return 0.0
    env = math.exp(-t * 28)
    noise = random.uniform(-1, 1)
    tone = math.sin(2 * math.pi * 190 * t)
    return (0.75 * noise + 0.35 * tone) * env * 0.6


def _hat(t: float, dur: float = 0.05) -> float:
    if t >= dur:
        return 0.0
    env = math.exp(-t * 90)
    # crude high-pass: difference of successive noise samples
    return (random.uniform(-1, 1) - random.uniform(-1, 1)) * env * 0.28


def _shaker(t: float, dur: float = 0.09) -> float:
    if t >= dur:
        return 0.0
    env = math.sin(math.pi * (t / dur)) ** 2
    return random.uniform(-1, 1) * env * 0.18


def make_drum_loop(path: str) -> None:
    random.seed(7)
    bpm = 120
    beat = 60.0 / bpm          # 0.5 s
    bars = 4                   # 4 bars = 16 beats = 8 s
    total = int(beat * 4 * bars * SR)
    out = [0.0] * total

    def add(fn, start_beat: float, gain: float = 1.0) -> None:
        start = int(start_beat * beat * SR)
        for i in range(total - start):
            t = i / SR
            if t > 0.6:
                break
            out[start + i] += fn(t) * gain

    for bar in range(bars):
        base = bar * 4
        for b in (0, 2):
            add(_kick, base + b, 1.0)
        add(_kick, base + 2.75, 0.55)         # syncopated pickup
        add(_snare, base + 1, 0.85)
        add(_snare, base + 3, 0.85)
        for step in range(8):
            add(_hat, base + step * 0.5, 0.9 if step % 2 == 0 else 0.55)
        for step in range(4):
            add(_shaker, base + step + 0.5, 0.8)

    # soft low bass drone for warmth
    for i in range(total):
        t = i / SR
        out[i] += math.sin(2 * math.pi * 55 * t) * 0.06

    _write_wav(path, out)


def make_night_ambience(path: str) -> None:
    random.seed(11)
    seconds = 16
    total = seconds * SR
    out = [0.0] * total
    low = 0.0
    for i in range(total):
        t = i / SR
        low = low * 0.995 + random.uniform(-1, 1) * 0.005
        wind = low * 3.2 + math.sin(2 * math.pi * 0.11 * t) * 0.05
        # sparse cricket chirps
        chirp = 0.0
        for freq, phase, rate in ((4100, 0.0, 2.1), (4600, 1.3, 1.6), (3600, 2.7, 1.1)):
            local = (t + phase) % (1.0 / rate)
            if local < 0.045:
                env = math.sin(math.pi * (local / 0.045)) ** 2
                chirp += math.sin(2 * math.pi * freq * t) * env * 0.10
        out[i] = wind * 0.6 + chirp

    # crossfade the tail into the head so the loop is seamless
    fade = int(0.75 * SR)
    for i in range(fade):
        k = i / fade
        out[i] = out[i] * k + out[total - fade + i] * (1 - k)
    _write_wav(path, out[: total - fade])


def make_gradient(path: str) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("[assets] ffmpeg not found - skipping gradient card", file=sys.stderr)
        return False
    cmd = [
        ffmpeg, "-y", "-v", "error",
        "-f", "lavfi",
        "-i", "gradients=s=1080x1920:c0=0x07070c:c1=0x2b1508:x0=540:y0=0:x1=540:y1=1920",
        "-frames:v", "1", path,
    ]
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as exc:
        print(f"[assets] gradient generation failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite existing assets")
    args = parser.parse_args()

    os.makedirs(ASSETS, exist_ok=True)
    drum = os.path.join(ASSETS, "drum_loop.wav")
    night = os.path.join(ASSETS, "night_ambience.wav")
    gradient = os.path.join(ASSETS, "gradient.png")

    if args.force or not os.path.exists(drum):
        print("[assets] synthesizing drum_loop.wav")
        make_drum_loop(drum)
    if args.force or not os.path.exists(night):
        print("[assets] synthesizing night_ambience.wav")
        make_night_ambience(night)
    if args.force or not os.path.exists(gradient):
        print("[assets] rendering gradient.png")
        make_gradient(gradient)

    for p in (drum, night, gradient):
        state = "ok" if os.path.exists(p) else "missing"
        print(f"[assets] {os.path.relpath(p, ROOT)}: {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
