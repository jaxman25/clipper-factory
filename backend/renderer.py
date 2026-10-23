"""FFmpeg rendering engine: cut, reframe 9:16, mix beds, burn captions.

Pipeline per clip
-----------------
1. Trim the segment (silence already removed by trimming to transcript word
   boundaries in ``main.py``) and speed it up 1.1x (video + audio in sync).
2. Reframe to 1080x1920:
   * face detected -> smart crop centred on the speaker's face
   * no face       -> cinematic fallback: blurred fill, centred footage,
                      dark gradient card and optional Pixabay B-roll bed
3. Mix the drum loop at -22 dB (plus optional night ambience at -30 dB).
4. Burn word-pop captions, hook (0-2 s) and outro (last 2 s) from ASS.
5. Stamp the white brand watermark in the bottom-right corner.
6. Encode H.264/AAC, 1080x1920, faststart, plus a JPEG thumbnail.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

try:
    from . import captions, common, paths
except ImportError:  # pragma: no cover
    import captions  # type: ignore
    import common  # type: ignore
    import paths  # type: ignore

TARGET_W, TARGET_H = 1080, 1920
WATERMARK_MARGIN = 52  # px from the bottom/right edge


class RenderError(RuntimeError):
    pass


def which_ffmpeg() -> str:
    exe = os.getenv("FFMPEG_BIN") or shutil.which("ffmpeg")
    if not exe:
        raise RenderError("ffmpeg not found on PATH (install ffmpeg or set FFMPEG_BIN)")
    return exe


def which_ffprobe() -> str:
    exe = os.getenv("FFPROBE_BIN") or shutil.which("ffprobe")
    if not exe:
        raise RenderError("ffprobe not found on PATH (install ffmpeg)")
    return exe


def probe(path: Path) -> dict:
    cmd = [
        which_ffprobe(), "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RenderError(f"ffprobe failed for {path}: {result.stderr[-400:]}")
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(video.get("duration") or data.get("format", {}).get("duration") or 0.0)
    return {
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "duration": duration,
        "has_audio": audio is not None,
        "fps": video.get("r_frame_rate") or "30/1",
    }


def _even(value: float) -> int:
    return max(2, int(round(value / 2.0)) * 2)


def _filter_path(path: Path) -> str:
    """Escape a path for use inside an ffmpeg filter argument."""
    text = str(path).replace("\\", "/")
    text = text.replace("'", "\\'").replace(":", "\\:")
    return text


def _fonts_dir() -> Path | None:
    explicit = os.getenv("ACF_FONTS_DIR")
    if explicit and Path(explicit).exists():
        return Path(explicit)
    for candidate in ("/usr/share/fonts", "/usr/local/share/fonts"):
        if Path(candidate).exists():
            return Path(candidate)
    if sys.platform == "win32":
        win_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        if win_fonts.exists():
            return win_fonts
    return None


def detect_face_center(video: Path, start: float, end: float) -> tuple[float, float] | None:
    """Median face centre (x, y as 0..1 fractions) across sampled frames."""
    try:
        import cv2  # type: ignore
        import mediapipe as mp  # type: ignore
    except Exception as exc:  # dependency missing / unsupported platform
        common.info(f"face detection unavailable ({exc}); using cinematic fallback")
        return None

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return None

    xs: list[float] = []
    ys: list[float] = []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        with mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.4
        ) as detector:
            span = max(0.5, end - start)
            for fraction in (0.08, 0.3, 0.55, 0.8):
                frame_index = int((start + span * fraction) * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_index))
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = detector.process(rgb)
                if not results.detections:
                    continue
                box = results.detections[0].location_data.relative_bounding_box
                xs.append(box.xmin + box.width / 2)
                ys.append(box.ymin + box.height / 2)
    finally:
        cap.release()

    if not xs:
        return None
    xs.sort()
    ys.sort()
    return (xs[len(xs) // 2], ys[len(ys) // 2])


def _crop_geometry(width: int, height: int, face: tuple[float, float] | None) -> tuple[int, int, int, int]:
    """Return crop w, h, x, y that produce the closest 9:16 window."""
    ratio = 9 / 16
    if width / height > ratio:
        crop_h = height
        crop_w = _even(height * ratio)
        centre_x = (face[0] if face else 0.5) * width
        x = int(max(0, min(width - crop_w, centre_x - crop_w / 2)))
        y = 0
    else:
        crop_w = width
        crop_h = _even(width / ratio)
        if crop_h > height:
            crop_h = _even(height)
            crop_w = _even(height * ratio)
        centre_y = (face[1] if face else 0.45) * height
        y = int(max(0, min(height - crop_h, centre_y - crop_h / 2)))
        x = 0
    return crop_w, crop_h, x, y


def _run_ffmpeg(args: list[str], timeout: float) -> None:
    ffmpeg = which_ffmpeg()
    cmd = [ffmpeg, "-y", "-hide_banner", "-nostdin", *args]
    common.info("ffmpeg " + " ".join(cmd[1:6]) + " ...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"ffmpeg timed out after {timeout:.0f}s") from exc
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-12:]
        raise RenderError("ffmpeg failed: " + " | ".join(tail))


def ensure_gradient() -> Path | None:
    """Generate the dark gradient card if setup did not create it."""
    if paths.GRADIENT.exists():
        return paths.GRADIENT
    try:
        paths.ASSETS.mkdir(parents=True, exist_ok=True)
        cmd = [
            which_ffmpeg(), "-y", "-v", "error", "-f", "lavfi",
            "-i", "gradients=s=1080x1920:c0=0x07070c:c1=0x2b1508:x0=540:y0=0:x1=540:y1=1920",
            "-frames:v", "1", str(paths.GRADIENT),
        ]
        subprocess.run(cmd, capture_output=True, timeout=90, check=True)
        return paths.GRADIENT
    except Exception as exc:
        common.warn(f"gradient card unavailable: {exc}")
        return None


def make_thumbnail(video: Path, out: Path, at: float = 1.0) -> None:
    tmp = out.with_suffix(".tmp.jpg")
    try:
        _run_ffmpeg(
            ["-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1",
             "-vf", "scale=540:-2", "-q:v", "4", str(tmp)],
            timeout=120,
        )
        os.replace(tmp, out)
    except RenderError as exc:
        common.warn(f"thumbnail failed: {exc}")
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def render_clip(
    source: Path,
    out_path: Path,
    start: float,
    end: float,
    words: Sequence[captions.CaptionWord],
    cfg: dict,
    *,
    hook: str = "",
    transcript: str = "",
    broll: Path | None = None,
    label: str = "",
    thumb_path: Path | None = None,
    info: dict | None = None,
) -> dict:
    """Render one vertical short. Returns render metadata."""
    info = info or probe(source)
    speed = float(cfg.get("playback_speed", 1.1) or 1.0)
    speed = max(1.0, min(1.5, speed))
    raw_duration = max(1.0, end - start)
    out_duration = raw_duration / speed

    face = detect_face_center(source, start, end) if info.get("height") else None
    width = info.get("width") or 0
    height = info.get("height") or 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path = out_path.with_suffix(".ass")
    ass_doc = captions.build_ass(
        words,
        duration=out_duration,
        speed=speed,
        primary_color=str(cfg.get("caption_color", "#FFD700")),
        words_per_card=int(cfg.get("caption_words_per_card", 3) or 3),
        hook=hook,
        hook_seconds=float(cfg.get("hook_seconds", 2) or 2),
        outro_text=str(cfg.get("outro_text", "") or ""),
        outro_seconds=float(cfg.get("outro_seconds", 2) or 2),
        transcript=transcript,
        label=label,
    )
    ass_path.write_text(ass_doc, encoding="utf-8")

    inputs: list[list[str]] = []
    index: dict[str, int] = {}

    inputs.append(["-ss", f"{start:.3f}", "-t", f"{raw_duration:.3f}", "-i", str(source)])
    index["src"] = 0

    def add_input(role: str, args: list[str]) -> None:
        index[role] = len(inputs)
        inputs.append(args)

    drum = paths.DRUM_LOOP if paths.DRUM_LOOP.exists() else None
    ambience = paths.NIGHT_AMBIENCE if paths.NIGHT_AMBIENCE.exists() else None
    gradient = ensure_gradient()
    broll = broll if broll and Path(broll).exists() else None

    if drum:
        add_input("drum", ["-stream_loop", "-1", "-i", str(drum)])
    if ambience:
        add_input("amb", ["-stream_loop", "-1", "-i", str(ambience)])
    if gradient:
        add_input("grad", ["-loop", "1", "-i", str(gradient)])
    if broll:
        add_input("broll", ["-stream_loop", "-1", "-i", str(broll)])
    watermark = paths.WATERMARK if paths.WATERMARK.exists() else None
    if watermark:
        add_input("wm", ["-loop", "1", "-i", str(watermark)])
    if not info.get("has_audio"):
        add_input(
            "silence",
            ["-f", "lavfi", "-t", f"{out_duration:.3f}",
             "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"],
        )

    filters: list[str] = []
    use_face = bool(face and width and height)
    if use_face:
        cw, ch, cx, cy = _crop_geometry(width, height, face)
        cw, ch = min(cw, width), min(ch, height)
        cx = int(max(0, min(width - cw, cx)))
        cy = int(max(0, min(height - ch, cy)))
        filters.append(
            f"[0:v]setpts=PTS/{speed:.4f},crop={cw}:{ch}:{cx}:{cy},"
            f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},setsar=1,fps=30[base]"
        )
    else:
        if broll:
            filters.append(
                f"[{index['broll']}:v]setpts=PTS-STARTPTS,"
                f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
                f"crop={TARGET_W}:{TARGET_H},eq=brightness=-0.22:saturation=0.85,setsar=1,fps=30[bg]"
            )
            filters.append(
                f"[0:v]setpts=PTS/{speed:.4f},scale={TARGET_W}:-2:flags=lanczos,fps=30[fg]"
            )
        else:
            filters.append(
                f"[0:v]setpts=PTS/{speed:.4f},split=2[vb][vf]"
            )
            # Blur at 1/4 resolution: same look, ~16x cheaper on a free CPU.
            filters.append(
                f"[vb]scale=270:480:force_original_aspect_ratio=increase,"
                f"crop=270:480,boxblur=luma_radius=8:luma_power=2,"
                f"eq=brightness=-0.20:saturation=0.72,"
                f"scale={TARGET_W}:{TARGET_H},setsar=1,fps=30[bg]"
            )
            filters.append(f"[vf]scale={TARGET_W}:-2:flags=lanczos,fps=30[fg]")
        filters.append(f"[bg][fg]overlay=(W-w)/2:(H-h)/2[stack]")

        current = "stack"
        if gradient:
            filters.append(
                f"[{index['grad']}:v]format=rgba,colorchannelmixer=aa=0.58[grad]"
            )
            filters.append(f"[{current}][grad]overlay=0:0[graded]")
            current = "graded"

        filters.append(
            f"[{current}]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},setsar=1[base]"
        )

    fonts = _fonts_dir()
    ass_filter = f"ass=filename='{_filter_path(ass_path)}'"
    if fonts:
        ass_filter += f":fontsdir='{_filter_path(fonts)}'"
    filters.append(f"[base]{ass_filter}[captioned]")

    video_out = "captioned"
    if watermark:
        # 100x100 PNG that already carries its own 50% alpha.
        filters.append(f"[{index['wm']}:v]format=rgba[wmlogo]")
        filters.append(
            f"[captioned][wmlogo]overlay="
            f"{TARGET_W}-w-{WATERMARK_MARGIN}:{TARGET_H}-h-{WATERMARK_MARGIN}:format=auto[branded]"
        )
        video_out = "branded"

    mix_inputs: list[str] = []
    if info.get("has_audio"):
        audio_chain = f"[0:a]atempo={speed:.4f}"
        if out_duration > 0.6:
            audio_chain += (
                f",afade=t=in:st=0:d=0.12"
                f",afade=t=out:st={max(0.0, out_duration - 0.25):.3f}:d=0.25"
            )
        audio_chain += "[voice]"
        filters.append(audio_chain)
        mix_inputs.append("voice")
    if drum:
        db = float(cfg.get("drum_volume_db", -22) or -22)
        filters.append(
            f"[{index['drum']}:a]volume={db}dB,atrim=0:{out_duration:.3f},"
            f"asetpts=PTS-STARTPTS[bed]"
        )
        mix_inputs.append("bed")
    if ambience:
        adb = float(cfg.get("ambience_volume_db", -30) or -30)
        filters.append(
            f"[{index['amb']}:a]volume={adb}dB,atrim=0:{out_duration:.3f},"
            f"asetpts=PTS-STARTPTS[amb]"
        )
        mix_inputs.append("amb")
    if not info.get("has_audio"):
        filters.append(
            f"[{index['silence']}:a]atrim=0:{out_duration:.3f},asetpts=PTS-STARTPTS[voice]"
        )
        mix_inputs.insert(0, "voice")

    if len(mix_inputs) > 1:
        joined = "".join(f"[{name}]" for name in mix_inputs)
        filters.append(
            f"{joined}amix=inputs={len(mix_inputs)}:duration=first:"
            f"dropout_transition=0:normalize=0,alimiter=limit=0.95[aout]"
        )
    else:
        filters.append("[voice]alimiter=limit=0.95[aout]")

    args: list[str] = []
    for segment in inputs:
        args.extend(segment)
    args.extend(["-filter_complex", ";".join(filters)])
    args.extend([
        "-map", f"[{video_out}]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
        "-r", "30", "-g", "60",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart", "-t", f"{out_duration:.3f}",
        str(out_path),
    ])

    timeout = 240 + raw_duration * 20
    _run_ffmpeg(args, timeout)

    if not out_path.exists() or out_path.stat().st_size < 20_000:
        raise RenderError(f"render produced an empty file: {out_path}")
    if thumb_path:
        make_thumbnail(out_path, thumb_path, at=min(1.2, max(0.2, out_duration / 3)))

    return {
        "output": str(out_path),
        "duration": round(out_duration, 2),
        "width": TARGET_W,
        "height": TARGET_H,
        "face_detected": bool(face),
        "broll": str(broll) if broll else None,
        "size_bytes": out_path.stat().st_size,
    }
