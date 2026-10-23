#!/usr/bin/env python3
"""Clipper Factory - clip generator.

    python3 backend/main.py --url "https://youtu.be/XXXX" --num-shorts 10

Downloads the source, transcribes it with faster-whisper, scores every 30-45 s
window with the viral detector, renders the best non-overlapping clips to
1080x1920 with burned-in word-pop captions, then queues them for the scheduler.

Render-safe paths: all state lives under ``ACF_DATA_ROOT`` (``/tmp``), whisper
models under ``/tmp/whisper_models``.
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

try:
    from . import broll as broll_mod
    from . import captions, common, paths, renderer, scheduling, telegram, viral
except ImportError:  # direct execution: python backend/main.py
    import broll as broll_mod  # type: ignore
    import captions  # type: ignore
    import common  # type: ignore
    import paths  # type: ignore
    import renderer  # type: ignore
    import scheduling  # type: ignore
    import telegram  # type: ignore
    import viral  # type: ignore

WHISPER_DIR = Path(os.getenv("WHISPER_MODEL_DIR", "/tmp/whisper_models"))


class JobError(RuntimeError):
    pass


class Job:
    """Progress document polled by the dashboard and Telegram bot."""

    def __init__(self, job_id: str, url: str, num_shorts: int) -> None:
        self.id = job_id
        self.path = paths.JOBS / f"{job_id}.json"
        self.data: dict[str, Any] = {
            "id": job_id,
            "status": "running",
            "stage": "starting",
            "progress": 0,
            "message": "Starting job",
            "source_url": url,
            "num_shorts": num_shorts,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "clips": [],
            "error": None,
        }
        self._write()

    def _write(self) -> None:
        self.data["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        common.write_json(self.path, self.data)

    def update(
        self,
        *,
        stage: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        **extra: Any,
    ) -> None:
        if stage is not None:
            self.data["stage"] = stage
        if progress is not None:
            self.data["progress"] = max(0, min(100, int(progress)))
        if message is not None:
            self.data["message"] = message
            common.info(message, job=self.id)
        self.data.update(extra)
        self._write()

    def finish(self, clips: list[dict], **extra: Any) -> None:
        self.data.update(
            status="done",
            stage="complete",
            progress=100,
            message=f"{len(clips)} shorts ready",
            clips=clips,
            **extra,
        )
        self._write()

    def fail(self, message: str) -> None:
        self.data.update(status="error", stage="error", message=message, error=message)
        self._write()


def _ensure_tools() -> None:
    missing: list[str] = []
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        missing.append("yt-dlp")
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        missing.append("faster-whisper")
    if missing:
        raise JobError(
            "Missing Python packages: " + ", ".join(missing)
            + ". Run: pip3 install -r requirements.txt"
        )
    renderer.which_ffmpeg()


def acquire_lock(job_id: str) -> None:
    paths.ensure_dirs()
    try:
        fd = os.open(paths.LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        try:
            age = time.time() - paths.LOCK_FILE.stat().st_mtime
        except OSError:
            age = 99_999
        if age > 4 * 3600:
            paths.LOCK_FILE.unlink(missing_ok=True)
            return acquire_lock(job_id)
        raise JobError("Another generation job is already running. Try again when it finishes.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(job_id)
        fh.flush()


def release_lock() -> None:
    paths.LOCK_FILE.unlink(missing_ok=True)


def download_source(url: str, job_id: str, job: Job) -> tuple[Path, str]:
    import yt_dlp

    job.update(stage="download", progress=2, message="Downloading source video")
    opts: dict[str, Any] = {
        "outtmpl": str(paths.DOWNLOADS / f"{job_id}.%(ext)s"),
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 40,
        "concurrent_fragment_downloads": 3,
        "restrictfilenames": True,
    }
    cookies = os.getenv("YTDLP_COOKIES", "").strip()
    if cookies and Path(cookies).exists():
        opts["cookiefile"] = cookies

    def hook(status: dict) -> None:
        if status.get("status") != "downloading":
            return
        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        done = status.get("downloaded_bytes") or 0
        if total:
            pct = 2 + int(min(1.0, done / total) * 13)
            job.update(progress=pct, message=f"Downloading source video ({pct}%)")

    opts["progress_hooks"] = [hook]
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise JobError(
            "yt-dlp failed to download this URL: "
            f"{exc}. If YouTube is blocking the server, set YTDLP_COOKIES to a cookies.txt file."
        ) from exc

    title = (info or {}).get("title") or "African tale"
    candidates = sorted(
        glob.glob(str(paths.DOWNLOADS / f"{job_id}*.mp4"))
        + glob.glob(str(paths.DOWNLOADS / f"{job_id}*.mkv"))
        + glob.glob(str(paths.DOWNLOADS / f"{job_id}*.webm"))
    )
    if not candidates:
        raise JobError("Download finished but no video file was produced")
    return Path(candidates[0]), title


def extract_audio(video: Path, job_id: str) -> Path:
    audio = paths.DOWNLOADS / f"{job_id}.wav"
    cmd = [
        renderer.which_ffmpeg(), "-y", "-v", "error", "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0 or not audio.exists():
        raise JobError("ffmpeg failed to extract audio: " + result.stderr[-300:])
    return audio


def transcribe(audio: Path, job: Job) -> tuple[list[dict], str, float]:
    from faster_whisper import WhisperModel

    model_name = os.getenv("WHISPER_MODEL", "tiny")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    job.update(
        stage="transcribe",
        progress=18,
        message=f"Loading whisper model '{model_name}' (first run downloads ~75 MB)",
    )
    WHISPER_DIR.mkdir(parents=True, exist_ok=True)
    try:
        model = WhisperModel(
            model_name,
            device="cpu",
            compute_type=compute_type,
            download_root=str(WHISPER_DIR),
            cpu_threads=max(1, min(4, (os.cpu_count() or 2))),
        )
    except Exception as exc:
        raise JobError(
            f"Could not load faster-whisper model '{model_name}': {exc}. "
            "On a 512 MB instance keep WHISPER_MODEL=tiny."
        ) from exc

    job.update(progress=22, message="Transcribing audio")
    try:
        segment_iter, info = model.transcribe(
            str(audio),
            word_timestamps=True,
            vad_filter=True,
            beam_size=1,
            condition_on_previous_text=False,
        )
    except Exception as exc:
        raise JobError(f"Transcription failed: {exc}") from exc

    total = float(getattr(info, "duration", 0.0) or 0.0)
    segments: list[dict] = []
    for seg in segment_iter:
        words = []
        for word in getattr(seg, "words", None) or []:
            text = (word.word or "").strip()
            if text:
                words.append({"start": float(word.start), "end": float(word.end), "word": text})
        segments.append(
            {"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip(), "words": words}
        )
        if total:
            pct = 22 + int(min(1.0, float(seg.end) / total) * 20)
            job.update(progress=pct, message=f"Transcribing audio ({pct}%)")

    language = getattr(info, "language", "en") or "en"
    if not segments:
        common.warn("Whisper returned no speech; clips will use visual-only mode")
    return segments, language, total


def _trim_to_words(candidate: viral.Candidate, video_duration: float) -> tuple[float, float]:
    start = max(0.0, candidate.start - 0.12)
    end = min(video_duration, candidate.end + 0.3) if video_duration else candidate.end + 0.3
    if end - start < 5.0:
        end = min(video_duration or (start + 30.0), start + 30.0)
    return round(start, 3), round(end, 3)


def _relative_words(candidate: viral.Candidate, clip_start: float) -> list[captions.CaptionWord]:
    out: list[captions.CaptionWord] = []
    for word in candidate.words:
        if word.end <= clip_start:
            continue
        out.append(
            captions.CaptionWord(
                start=max(0.0, word.start - clip_start),
                end=max(0.05, word.end - clip_start),
                text=word.text,
            )
        )
    return out


def _next_job_dir(job_id: str) -> Path:
    out = paths.EXPORTS / job_id
    out.mkdir(parents=True, exist_ok=True)
    return out


def run(args: argparse.Namespace) -> int:
    paths.ensure_dirs()
    cfg = common.load_config()
    num_shorts = int(args.num_shorts or cfg.get("shorts_per_video", 10))
    job_id = paths.safe_id(args.job_id or datetime.now().strftime("job-%Y%m%d-%H%M%S"))
    job = Job(job_id, args.url or args.local_file or "", num_shorts)
    common.info(f"Job {job_id} started", url=args.url or args.local_file)

    source: Path | None = None
    locked = False
    try:
        _ensure_tools()
        acquire_lock(job_id)
        locked = True
        if args.local_file:
            source = Path(args.local_file).expanduser().resolve()
            if not source.exists():
                raise JobError(f"Local file not found: {source}")
            title = source.stem
            job.update(stage="download", progress=15, message="Using local source file")
        else:
            if not args.url:
                raise JobError("A YouTube URL or --local-file is required")
            source, title = download_source(args.url, job_id, job)

        info = renderer.probe(source)
        duration = info.get("duration") or 0.0
        if duration < 5:
            raise JobError("Source video is too short to cut shorts from")

        audio = extract_audio(source, job_id)
        segments_raw, language, _ = transcribe(audio, job)
        job.update(
            stage="analyze",
            progress=44,
            message=f"Scoring {len(segments_raw)} transcript segments for viral moments",
            language=language,
        )

        rms = viral.compute_rms(str(audio))
        segments = viral.build_segments(segments_raw)
        keywords = cfg.get("viral_keywords") or viral.DEFAULT_KEYWORDS
        min_s = float(cfg.get("clip_min_seconds", 30) or 30)
        max_s = float(cfg.get("clip_max_seconds", 45) or 45)

        candidates = viral.find_candidates(segments, rms, keywords, min_s, max_s)
        selected = viral.select_top(candidates, num_shorts, min_s, max_s)
        if len(selected) < num_shorts:
            extra = viral.fallback_windows(duration, num_shorts, min_s, max_s)
            for cand in extra:
                if len(selected) >= num_shorts:
                    break
                if all(abs(cand.start - s.start) > 1.5 for s in selected):
                    selected.append(cand)
            selected.sort(key=lambda c: c.start)

        if not selected:
            raise JobError("No usable segments found in this video")
        job.update(
            stage="render",
            progress=46,
            message=f"Rendering {len(selected)} vertical shorts",
            candidates=len(candidates),
        )

        broll_path = None
        if os.getenv("PIXABAY_API_KEY", "").strip():
            broll_path = broll_mod.fetch()
            if broll_path:
                job.update(message="Pixabay B-roll cached for face-less fallbacks")

        job_dir = _next_job_dir(job_id)
        queue_items: list[dict[str, Any]] = []
        slots = scheduling.next_slots(cfg, len(selected))
        hashtags = str(cfg.get("hashtags", ""))

        for index, candidate in enumerate(selected, start=1):
            clip_id = f"{job_id}-{index:02d}"
            base_pct = 46 + int((index - 1) / len(selected) * 48)
            job.update(
                stage="render",
                progress=base_pct,
                message=f"Rendering clip {index}/{len(selected)} (score {candidate.score:.0f})",
            )
            clip_start, clip_end = _trim_to_words(candidate, duration)
            words = _relative_words(candidate, clip_start)
            hook = viral.hook_text(candidate)
            transcript = candidate.text.strip()
            clip_path = job_dir / f"{clip_id}.mp4"
            thumb_path = job_dir / f"{clip_id}.jpg"

            render_meta = renderer.render_clip(
                source,
                clip_path,
                clip_start,
                clip_end,
                words,
                cfg,
                hook=hook,
                transcript=transcript,
                broll=broll_path,
                thumb_path=thumb_path,
                info=info,
            )

            scheduled = slots[index - 1] if index - 1 < len(slots) else scheduling.next_slot(cfg)
            item = {
                "id": clip_id,
                "job_id": job_id,
                "source_url": args.url or str(source),
                "source_title": title,
                "title": hook.title() if hook else f"African Tale #{index}",
                "hook": hook,
                "caption": viral.social_caption(candidate, hashtags),
                "transcript": transcript,
                "viral_score": round(candidate.score, 1),
                "reasons": candidate.reasons,
                "start": clip_start,
                "end": clip_end,
                "duration": render_meta["duration"],
                "width": render_meta["width"],
                "height": render_meta["height"],
                "face_detected": render_meta["face_detected"],
                "file": f"{clip_id}.mp4",
                "thumb": f"{clip_id}.jpg",
                "export_path": str(clip_path),
                "scheduled_for": scheduling.to_iso(scheduled),
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "posted_at": None,
                "platforms": {},
            }
            if thumb_path.exists():
                shutil.copy2(thumb_path, paths.QUEUE / thumb_path.name)
            shutil.copy2(clip_path, paths.QUEUE / f"{clip_id}.mp4")
            common.write_json(paths.QUEUE / f"{clip_id}.json", item)
            queue_items.append(item)

            # Free disk on /tmp: drop the source once it is no longer needed.
        manifest = {
            "job_id": job_id,
            "source_url": args.url or str(source),
            "source_title": title,
            "language": language,
            "duration": round(duration, 2),
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "clip_count": len(queue_items),
            "clips": queue_items,
        }
        common.write_json(job_dir / "metadata.json", manifest)
        job.finish(queue_items, export_dir=str(job_dir))

        if not args.no_notify:
            summary = (
                f"✅ {len(queue_items)} shorts ready from “{title}”\n"
                f"Next post: {queue_items[0]['scheduled_for'] if queue_items else '—'}\n"
                f"Use /queue to review them."
            )
            telegram.send_message(summary)
        return 0
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        job.fail(message)
        common.error(message, job=job_id, trace=traceback.format_exc()[-1500:])
        if not args.no_notify:
            telegram.send_message(f"❌ Clip job failed: {message[:500]}")
        return 1
    finally:
        if source and not args.keep_source and not args.local_file:
            for suffix in (".mp4", ".mkv", ".webm", ".wav", ".part"):
                try:
                    (paths.DOWNLOADS / f"{job_id}{suffix}").unlink(missing_ok=True)
                except OSError:
                    pass
        for stray in glob.glob(str(paths.DOWNLOADS / f"{job_id}*")):
            try:
                os.remove(stray)
            except OSError:
                pass
        if locked:
            release_lock()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate 9:16 shorts from a YouTube video")
    parser.add_argument("--url", help="YouTube (or any yt-dlp supported) URL")
    parser.add_argument("--local-file", help="Use a local video file instead of downloading")
    parser.add_argument("--num-shorts", type=int, default=10, help="How many clips to render (default 10)")
    parser.add_argument("--job-id", help="Stable job id supplied by the dashboard/bot")
    parser.add_argument("--keep-source", action="store_true", help="Keep the downloaded source file")
    parser.add_argument("--no-notify", action="store_true", help="Do not send Telegram messages")
    return parser


if __name__ == "__main__":
    sys.exit(run(build_parser().parse_args()))
