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
import json
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
    from . import captions, common, paths, renderer, scheduling, telegram, transform, viral
except ImportError:  # direct execution: python backend/main.py
    import broll as broll_mod  # type: ignore
    import captions  # type: ignore
    import common  # type: ignore
    import paths  # type: ignore
    import renderer  # type: ignore
    import scheduling  # type: ignore
    import telegram  # type: ignore
    import transform  # type: ignore
    import viral  # type: ignore

WHISPER_DIR = Path(os.getenv("WHISPER_MODEL_DIR", "/tmp/whisper_models"))

# The backend runs inside a virtualenv that does not inherit the system PATH,
# so yt-dlp cannot discover Deno on its own and the YouTube "n" challenge
# solving fails. Pin yt-dlp to the system Deno install explicitly.
DENO_PATH = (
    r"C:\Users\jane\AppData\Local\Microsoft\WinGet\Packages"
    r"\DenoLand.Deno_Microsoft.Winget.Source_8wekyb3d8bbwe\deno.exe"
)


class JobError(RuntimeError):
    pass


class JobCancelled(JobError):
    """The job document was cancelled externally (bot or dashboard)."""


class Job:
    """Progress document polled by the dashboard and Telegram bot.

    The worker owns the normal progress transitions, but a cancellation
    written by the Telegram bot or the dashboard is terminal: once the
    on-disk document says ``cancelled`` this object stops writing, so a live
    worker can never resurrect the job with a misleading ``running``/``done``
    state.
    """

    def __init__(
        self, job_id: str, url: str, num_shorts: int, mode: str = "viral"
    ) -> None:
        self.id = job_id
        self.path = paths.JOBS / f"{job_id}.json"
        self.cancelled = False
        self.data: dict[str, Any] = {
            "id": job_id,
            "pid": os.getpid(),
            "status": "running",
            "stage": "starting",
            "progress": 0,
            "message": "Starting job",
            "source_url": url,
            "num_shorts": num_shorts,
            "mode": mode,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "clips": [],
            "error": None,
        }
        if self._disk_status() == "cancelled":
            # Cancellation landed before (or as) the worker started: the
            # terminal state wins and is never overwritten by a fresh doc.
            self.cancelled = True
            return
        self._write()

    def _disk_status(self) -> str:
        """Status currently on disk ('' when the document is missing)."""
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                status = json.load(fh).get("status")
            return status if isinstance(status, str) else ""
        except (OSError, ValueError):
            return ""

    def _check_not_cancelled(self) -> None:
        if not self.cancelled and self._disk_status() == "cancelled":
            self.cancelled = True
        if self.cancelled:
            raise JobCancelled(f"Job {self.id} was cancelled")

    def _write(self) -> None:
        # Last-moment guard: never overwrite a cancellation written by the
        # bot or the dashboard with a running/done/error state.
        if self.cancelled:
            return
        if self._disk_status() == "cancelled":
            self.cancelled = True
            return
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
        self._check_not_cancelled()
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
        # Record ownership so cancellations, aborts and exit handlers can
        # verify the lock is theirs before deleting it.
        json.dump(
            {
                "job_id": job_id,
                "pid": os.getpid(),
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            fh,
            ensure_ascii=False,
        )
        fh.flush()
        os.fsync(fh.fileno())


def release_lock(job_id: str | None = None) -> None:
    """Release ``generate.lock`` only when it belongs to this job.

    A lock held by a different job - or one we cannot identify - is left
    untouched; see ``common.remove_lock_if_owned``.
    """
    if common.read_lock() and not common.remove_lock_if_owned(job_id, os.getpid()):
        common.warn(f"generate.lock not owned by {job_id!r}; left untouched")


def download_source(url: str, job_id: str, job: Job) -> tuple[Path, str, str]:
    import yt_dlp

    job.update(stage="download", progress=2, message="Downloading source video")
    opts: dict[str, Any] = {
        "outtmpl": str(paths.DOWNLOADS / f"{job_id}.%(ext)s"),
        # Prefer a single merged mp4 so extract_audio gets one readable file.
        # Without bestvideo+bestaudio+merge, YouTube returns separate streams
        # and yt-dlp can leave an mp4 that contains only metadata (0 audio samples),
        # which makes faster-whisper see "no speech" (WAV too short / silent).
        "format": "bv*+ba/b",
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

    # --js-runtimes "deno:<path>" : use the system Deno binary (the venv PATH
    # has no deno), falling back to a PATH lookup when the pinned path is absent.
    if Path(DENO_PATH).exists():
        opts["js_runtimes"] = {"deno": {"path": DENO_PATH}}
    else:
        opts["js_runtimes"] = {"deno": {}}
    # --remote-components ejs:github : allow fetching the n-solver scripts.
    opts["remote_components"] = ["ejs:github"]

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
    # Original creator handle for the anti-flag attribution line; yt-dlp
    # already returned it inside the download metadata (no extra request).
    channel = str(
        (info or {}).get("channel") or (info or {}).get("uploader") or ""
    ).strip()
    candidates = sorted(
        glob.glob(str(paths.DOWNLOADS / f"{job_id}*.mp4"))
        + glob.glob(str(paths.DOWNLOADS / f"{job_id}*.mkv"))
        + glob.glob(str(paths.DOWNLOADS / f"{job_id}*.webm"))
    )
    if not candidates:
        raise JobError("Download finished but no video file was produced")
    return Path(candidates[0]), title, channel


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
            # Chunked decoding: the audio is processed in 30-second segments
            # instead of one giant (1, samples, n_mels) array, which is what
            # blew past the memory limit (~950 MiB) on long sources.
            chunk_length=30,
            # Greedy decoding keeps only one hypothesis alive (no beam search
            # scratch space) - much lighter on a 512 MB box.
            beam_size=1,
            # VAD filter enabled: silent stretches are skipped entirely, so
            # they never reach the feature extractor and peak RAM stays down.
            vad_filter=True,
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


_ACTIVE_JOB_ID = ""  # published by run(); signal handlers cannot see run()'s locals


# (seconds, platform, id tag) - the three transformative outputs per job.
TRANSFORM_FORMATS = ((21, "TikTok", "t21"), (30, "Reels", "t30"), (59, "Shorts", "t59"))


def _build_queue_item(
    *,
    clip_id: str,
    job_id: str,
    source_url: str,
    source_title: str,
    title: str,
    hook: str,
    caption: str,
    transcript: str,
    viral_score: float | None,
    reasons: list[str],
    start: float,
    end: float,
    mode: str,
    scheduled: datetime,
    clip_path: Path,
    render_meta: dict,
    meta: dict,
    meta_source: str,
    channel: str,
    extras: dict | None = None,
) -> dict:
    """Build the queue JSON that every clip is written as.

    The transform path and the viral/equal path used to spell this dict out
    twice (34 and 29 keys). Only the four highlighted fields - title, caption,
    viral_score, reasons - plus the per-job values differ between them, so
    those are parameters and the shared fields are spelled out once here.
    ``extras`` carries the transform-only keys (llm, voiceover, platform,
    seconds, variants) that the viral/equal path does not emit.
    """
    item = {
        "id": clip_id,
        "job_id": job_id,
        "source_url": source_url,
        "source_title": source_title,
        "title": title,
        "hook": hook,
        "caption": caption,
        "transcript": transcript,
        "viral_score": viral_score,
        "reasons": reasons,
        "start": start,
        "end": end,
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
        "mode": mode,
        "metadata_variants": meta,
        "metadata_source": meta_source,
        "original_channel": channel,
        "attribution": transform.attribution_line(channel),
        "speed": render_meta.get("speed"),
    }
    if extras:
        item.update(extras)
    return item


def _persist_queue_item(item: dict, clip_path: Path, thumb_path: Path) -> None:
    """Copy a rendered clip (and its thumbnail) into the queue and write its JSON.

    This tail was spelled out at the end of both render paths; it lives here so
    the queue's three files (mp4, jpg, json) can never drift apart again.
    """
    if thumb_path.exists():
        shutil.copy2(thumb_path, paths.QUEUE / thumb_path.name)
    shutil.copy2(clip_path, paths.QUEUE / f"{item['id']}.mp4")
    common.write_json(paths.QUEUE / f"{item['id']}.json", item)


def _render_transform(
    *,
    source: Path,
    audio: Path,
    info: dict,
    duration: float,
    segments_raw: list,
    language: str,
    job: "Job",
    cfg: dict,
    job_id: str,
    job_dir: Path,
    broll_path: Path | None,
    hashtags: str,
    source_url: str,
    channel: str = "",
    mode: str,
) -> list[dict]:
    """AI script rewrite -> edge-tts voiceover -> 21/30/59 s renders.

    One transformative voiceover is generated per source video, then rendered
    into the three platform lengths. Each output carries the zoompan punch-in,
    the progress bar, the Pixabay B-roll fallback, the music bed at -20 dB and
    the user's handle watermark. Returns the three queue items.
    """
    full_text = " ".join(
        str(seg.get("text", "")).strip() for seg in segments_raw
    ).strip()
    if not full_text:
        raise JobError("Transform mode needs a transcript - no speech found")

    job.update(
        stage="analyze",
        progress=44,
        message="Rewriting transcript into a transformative script (free LLM)",
        language=language,
    )
    script, llm_source = transform.rewrite_script(full_text)
    if not script:
        raise JobError("Script rewriting produced an empty script")

    job.update(
        progress=45,
        message="Generating titles, descriptions and hashtags",
    )
    meta, meta_source = transform.generate_metadata(script, channel)

    job.update(progress=46, message="Generating AI voiceover (edge-tts)")
    vo_path, vo_words = transform.synthesize_voiceover(script, job_dir / "voiceover.mp3")
    vo_info = renderer.probe(vo_path)
    if float(vo_info.get("duration") or 0.0) <= 0.5:
        raise JobError("Voiceover is too short")

    caption_words = [
        captions.CaptionWord(
            start=float(w["start"]), end=float(w["end"]), text=str(w["text"])
        )
        for w in vo_words
    ]

    # Visual bed: score the transcript like viral mode and start at the best
    # window, clamped so a full 59 s render still fits the source.
    bed_start = 0.0
    try:
        rms = viral.compute_rms(str(audio))
        segments = viral.build_segments(segments_raw)
        keywords = cfg.get("viral_keywords") or viral.DEFAULT_KEYWORDS
        cands = viral.find_candidates(segments, rms, keywords, 30, 45)
        best = viral.select_top(cands, 1, 30, 45)
        if best:
            bed_start = float(best[0].start)
    except Exception as exc:  # scoring is cosmetic here - never fail the job
        common.warn(f"transform bed selection fell back to t=0: {exc}")
    # Footage runs 1.1x-1.2x while the voiceover stays at 1.0x: the visual
    # window is sized x footage_speed and the renderer compresses it back to
    # the exact target with setpts (window/target = 1/speed -> 1.1-1.2x).
    footage_speed = max(
        1.1, min(1.2, float(cfg.get("transform_speed", 1.15) or 1.15))
    )
    max_window = min(59.0 * footage_speed, duration)
    bed_start = (
        max(0.0, min(bed_start, duration - max_window))
        if duration > max_window
        else 0.0
    )

    handle = (
        os.getenv("WATERMARK_HANDLE", "").strip()
        or str(cfg.get("handle", "") or "").strip()
    )
    hook = script.split(". ")[0].strip().rstrip(".") if script else ""
    base_title = hook.title() if hook else "Transformed Story"

    queue_items: list[dict] = []
    slots = scheduling.next_slots(cfg, len(TRANSFORM_FORMATS))
    total = len(TRANSFORM_FORMATS)
    # Every sibling render carries the full 21/30/59 s manifest so the
    # dashboard can offer all three versions as tabs on one clip card.
    variants = [
        {
            "id": f"{job_id}-{i + 1:02d}-{tag}",
            "platform": tag,
            "label": label,
            "seconds": secs,
        }
        for i, (secs, label, tag) in enumerate(TRANSFORM_FORMATS)
    ]
    for idx, (seconds, platform, tag) in enumerate(TRANSFORM_FORMATS):
        clip_id = f"{job_id}-{idx + 1:02d}-{tag}"
        job.update(
            stage="render",
            progress=50 + idx * 15,
            message=f"Rendering {seconds}s {platform} version ({idx + 1}/{total})",
        )
        target = float(seconds)
        win_end = min(duration, bed_start + target * footage_speed)
        clip_path = job_dir / f"{clip_id}.mp4"
        thumb_path = job_dir / f"{clip_id}.jpg"
        words_for = [w for w in caption_words if w.start < target]
        render_meta = renderer.render_clip(
            source,
            clip_path,
            bed_start,
            win_end,
            words_for,
            cfg,
            hook=hook,
            transcript=script,
            broll=broll_path,
            thumb_path=thumb_path,
            info=info,
            max_duration=target,
            voiceover=vo_path,
            target_duration=target,
            hook_seconds=3.0,
            zoom_effect=True,
            progress_bar=True,
            handle=handle,
            music_db=-20.0,
        )
        slot = slots[idx] if idx < len(slots) else scheduling.next_slot(cfg)
        scheduled = scheduling.jitter(slot)
        item = _build_queue_item(
            clip_id=clip_id,
            job_id=job_id,
            source_url=source_url,
            source_title=base_title,
            title=f"{base_title} ({seconds}s {platform})",
            hook=hook,
            caption=f"{hook} {hashtags}".strip(),
            transcript=script,
            viral_score=None,
            reasons=[f"transform:{llm_source}", f"voiceover:{seconds}s"],
            start=bed_start,
            end=win_end,
            mode=mode,
            scheduled=scheduled,
            clip_path=clip_path,
            render_meta=render_meta,
            meta=meta,
            meta_source=meta_source,
            channel=channel,
            extras={
                "llm": llm_source,
                "voiceover": "edge-tts",
                "platform": tag,
                "seconds": seconds,
                "variants": variants,
            },
        )
        _persist_queue_item(item, clip_path, thumb_path)
        queue_items.append(item)

    job.update(stage="render", progress=94, message="Transform renders complete")
    return queue_items


def _abort_handler(signum, frame) -> None:
    """Interrupt point: cancel the running job and exit cleanly."""
    active = _ACTIVE_JOB_ID
    common.warn(f"Received signal {signum}; cancelling {active or '<none>'}")
    try:
        if not active:
            return
        # Drop the lock only when this worker actually owns it: a signal
        # arriving before acquire_lock() must not unlock another job's run.
        if common.read_lock() and not common.remove_lock_if_owned(active, os.getpid()):
            common.warn(f"generate.lock is not owned by {active}; left untouched")
        job = read_job(active)
        if job:
            job["status"] = "cancelled"
            job["message"] = "Cancelled by user"
            _write_job(job)
    except Exception as exc:
        common.warn(f"abort cleanup failed: {exc}")
    sys.exit(0)


def read_job(job_id: str) -> dict[str, Any]:
    """Read a job document from the jobs database."""
    try:
        with open(paths.JOBS / f"{job_id}.json", "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _write_job(job: dict[str, Any]) -> None:
    """Atomically write a job document via the shared unique-tmp writer."""
    common.write_json(paths.JOBS / f"{job['id']}.json", job)


def _next_job_dir(job_id: str) -> Path:
    out = paths.EXPORTS / job_id
    out.mkdir(parents=True, exist_ok=True)
    return out


def run(args: argparse.Namespace) -> int:
    global _ACTIVE_JOB_ID
    paths.ensure_dirs()
    cfg = common.load_config()
    if getattr(args, "transform_speed", None):
        cfg["transform_speed"] = args.transform_speed
    if getattr(args, "clip_max_seconds", None):
        cfg["clip_max_seconds"] = float(args.clip_max_seconds)
    num_shorts = int(args.num_shorts or cfg.get("shorts_per_video", 10))
    job_id = paths.safe_id(args.job_id or datetime.now().strftime("job-%Y%m%d-%H%M%S"))
    mode = getattr(args, "mode", "viral")
    job = Job(job_id, args.url or args.local_file or "", num_shorts, mode)
    _ACTIVE_JOB_ID = job_id
    common.info(f"Job {job_id} started (mode={mode})", url=args.url or args.local_file)

    # Abort is signalled by removing this file's lock — the dashboard backend
    # drops generate.lock and writes status='cancelled' to the job doc. The
    # worker exits cleanly so the dashboard sees the real end state.
    try:
        import signal as _signal
        _signal.signal(_signal.SIGTERM, _abort_handler)
        _signal.signal(_signal.SIGINT, _abort_handler)
    except Exception:
        pass

    source: Path | None = None
    locked = False
    try:
        if job.cancelled:
            raise JobCancelled(f"Job {job_id} was cancelled before it started")
        _ensure_tools()
        acquire_lock(job_id)
        locked = True
        channel = ""
        if args.local_file:
            source = Path(args.local_file).expanduser().resolve()
            if not source.exists():
                raise JobError(f"Local file not found: {source}")
            title = source.stem
            job.update(stage="download", progress=15, message="Using local source file")
        else:
            if not args.url:
                raise JobError("A YouTube URL or --local-file is required")
            source, title, channel = download_source(args.url, job_id, job)
        # Local files carry no channel: env/config can still name the original
        # creator so attribution keeps working for re-uploaded sources.
        channel = (
            channel
            or (getattr(args, "original_channel", "") or "").strip()
            or os.getenv("ORIGINAL_CHANNEL", "").strip()
            or str(cfg.get("original_channel") or "").strip()
        )

        info = renderer.probe(source)
        duration = info.get("duration") or 0.0
        if duration < 5:
            raise JobError("Source video is too short to cut shorts from")

        audio = extract_audio(source, job_id)

        if mode == "equal":
            # Equal-slices mode: divide total duration by num_shorts and cut
            # even windows from start to finish. No transcript, no viral score,
            # no caption burn-in (captions need word timestamps).
            segments_raw = []
            language = "en"
            job.update(
                stage="analyze",
                progress=44,
                message="Slicing evenly into equal segments",
                language=language,
            )
            candidates = []
            if duration >= num_shorts * 3:
                step = duration / num_shorts
                for i in range(num_shorts):
                    start = i * step
                    end = min(duration, start + max(3.0, duration / num_shorts))
                    candidates.append(
                        viral.Candidate(
                            start=round(start, 3),
                            end=round(end, 3),
                            text="",
                            words=[],
                            score=round(max(20.0, 60.0 - i * 3.0), 1),
                            reasons=["equal slice - visual highlight"],
                        )
                    )
            else:
                # Very short source: just split at a fixed interval.
                step = max(3.0, duration / num_shorts)
                for i in range(num_shorts):
                    start = i * step
                    end = min(duration, start + step)
                    if end - start < 2.0:
                        break
                    candidates.append(
                        viral.Candidate(
                            start=round(start, 3),
                            end=round(end, 3),
                            text="",
                            words=[],
                            score=round(40.0, 1),
                            reasons=["equal slice - visual highlight"],
                        )
                    )
            selected = candidates[:num_shorts]
            job.update(
                stage="render",
                progress=46,
                message=f"Rendering {len(selected)} vertical shorts (equal slices)",
                candidates=len(selected),
            )
        elif mode == "viral":
            # Viral mode: keep the existing AI-driven transcript logic.
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
        else:
            # Transform mode: transcribe only. The transform renderer below
            # rewrites the script, speaks it with edge-tts and produces the
            # 21/30/59 s outputs, so no per-candidate windows are needed.
            segments_raw, language, _ = transcribe(audio, job)
            candidates = []
            selected = []

            if not segments_raw:
                raise JobError("Transform mode needs a transcript - no speech found")

        broll_path = None
        if os.getenv("PIXABAY_API_KEY", "").strip():
            broll_path = broll_mod.fetch()
            if broll_path:
                job.update(message="Pixabay B-roll cached for face-less fallbacks")

        job_dir = _next_job_dir(job_id)
        queue_items: list[dict[str, Any]] = []
        slots = scheduling.next_slots(cfg, len(selected))
        hashtags = str(cfg.get("hashtags", ""))

        if mode == "transform":
            queue_items = _render_transform(
                source=source,
                audio=audio,
                info=info,
                duration=duration,
                segments_raw=segments_raw,
                language=language,
                job=job,
                cfg=cfg,
                job_id=job_id,
                job_dir=job_dir,
                broll_path=broll_path,
                hashtags=hashtags,
                source_url=args.url or str(source),
                channel=channel,
                mode=mode,
            )

        for index, candidate in enumerate(selected, start=1):
            clip_id = f"{job_id}-{index:02d}"
            base_pct = 46 + int((index - 1) / len(selected) * 48)
            hook = ""
            transcript = ""
            words = []
            title = f"Equal Slice {index}"

            if mode == "equal":
                # Equal mode: no transcript, no captions, no hook text.
                # Just cut the vertical segment and let the renderer handle
                # the cinematic fallback.
                clip_start = round(candidate.start, 3)
                clip_end = round(candidate.end, 3)
                job.update(
                    stage="render",
                    progress=base_pct,
                    message=f"Rendering equal slice {index}/{len(selected)}",
                )
            else:
                clip_start, clip_end = _trim_to_words(candidate, duration)
                words = _relative_words(candidate, clip_start)
                hook = viral.hook_text(candidate)
                transcript = candidate.text.strip()
                title = hook.title() if hook else f"African Tale #{index}"
                job.update(
                    stage="render",
                    progress=base_pct,
                    message=f"Rendering clip {index}/{len(selected)} (score {candidate.score:.0f})",
                )

            clip_path = job_dir / f"{clip_id}.mp4"
            thumb_path = job_dir / f"{clip_id}.jpg"

            # Load the highlight keywords list from config (defaults to
            # DEFAULT_HIGHLIGHT_WORDS in captions.py when not configured).
            highlight_words = cfg.get("highlight_words", captions.DEFAULT_HIGHLIGHT_WORDS)

            if mode == "equal":
                # Equal mode: no transcript, no captions, no hook text.
                # Just cut the vertical segment and let the renderer handle
                # the cinematic fallback.
                clip_start = round(candidate.start, 3)
                clip_end = round(candidate.end, 3)
                job.update(
                    stage="render",
                    progress=base_pct,
                    message=f"Rendering equal slice {index}/{len(selected)}",
                )
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
                    highlight_words=highlight_words,
                    max_duration=cfg.get("clip_max_seconds", 25) or 25,
                )
            else:
                clip_start, clip_end = _trim_to_words(candidate, duration)
                words = _relative_words(candidate, clip_start)
                hook = viral.hook_text(candidate)
                transcript = candidate.text.strip()
                title = hook.title() if hook else f"African Tale #{index}"
                job.update(
                    stage="render",
                    progress=base_pct,
                    message=f"Rendering clip {index}/{len(selected)} (score {candidate.score:.0f})",
                )
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
                    highlight_words=highlight_words,
                    max_duration=cfg.get("clip_max_seconds", 25) or 25,
                )

            # Queue this clip right away so EVERY rendered clip lands in the
            # queue. This block used to sit outside the loop, which meant only
            # the last clip of a job was ever queued.
            seed_text = (transcript or hook or title or "").strip()
            meta, meta_source = transform.generate_metadata(seed_text, channel)
            slot = (
                slots[index - 1]
                if index - 1 < len(slots)
                else scheduling.next_slot(cfg)
            )
            scheduled = scheduling.jitter(slot)
            item = _build_queue_item(
                clip_id=clip_id,
                job_id=job_id,
                source_url=args.url or str(source),
                source_title=title,
                title=title,
                hook=hook,
                caption=viral.social_caption(candidate, hashtags) if mode == "viral" else transcript,
                transcript=transcript,
                viral_score=round(candidate.score, 1) if mode == "viral" else None,
                reasons=candidate.reasons if mode == "viral" else [],
                start=clip_start,
                end=clip_end,
                mode=mode,
                scheduled=scheduled,
                clip_path=clip_path,
                render_meta=render_meta,
                meta=meta,
                meta_source=meta_source,
                channel=channel,
            )
            _persist_queue_item(item, clip_path, thumb_path)
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

        # Auto-post to YouTube Shorts if the user enabled it. The uploader
        # reads its credentials from the environment (YOUTUBE_* variables),
        # the same way every other integration reads its token.
        if cfg.get("youtube_auto_post"):
            from . import youtube_uploader
            try:
                upload_ok = youtube_uploader.upload_short(
                    video_path=str(job_dir / f"{queue_items[0]['id']}.mp4"),
                    title=queue_items[0].get("title", ""),
                    description=queue_items[0].get("caption", ""),
                )
                if upload_ok.get("ok"):
                    common.info(f"YouTube upload succeeded: {upload_ok.get('video_id')}")
                    # Same best-effort chart seed as the scheduler: one point
                    # per posting date, deduped by date on the server.
                    common.record_analytics_point(datetime.now().date().isoformat())
                    # Update the first clip's record so the dashboard can show
                    # the video ID next to it.  We keep it read-only-ish – the
                    # UI never trusts this value, it just displays it.
                    if queue_items and queue_items[0]:
                        common.write_json(
                            paths.QUEUE / f"{queue_items[0]['id']}.json",
                            {**queue_items[0], "youtube_video_id": upload_ok.get("video_id")},
                        )
                else:
                    common.warn(f"YouTube upload failed: {upload_ok.get('error')}")
            except Exception as exc:
                common.warn(f"YouTube auto-post failed: {exc}")

        if not args.no_notify:
            summary = (
                f"✅ {len(queue_items)} shorts ready from “{title}”\n"
                f"Next post: {queue_items[0]['scheduled_for'] if queue_items else '—'}\n"
                f"Use /queue to review them."
            )
            telegram.send_message(summary)
        return 0
    except JobCancelled as exc:
        common.warn(str(exc), job=job_id)
        return 0
    except Exception as exc:
        if job.cancelled:
            # A cancellation won the race: the document already carries the
            # terminal state, so do not append a misleading error or notify.
            common.warn(f"Job {job_id} stopped after cancellation", job=job_id)
            return 0
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
            release_lock(job_id)
        _ACTIVE_JOB_ID = ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate 9:16 shorts from a YouTube video")
    parser.add_argument("--url", help="YouTube (or any yt-dlp supported) URL")
    parser.add_argument("--local-file", help="Use a local video file instead of downloading")
    parser.add_argument("--num-shorts", type=int, default=10, help="How many clips to render (default 10)")
    parser.add_argument("--job-id", help="Stable job id supplied by the dashboard/bot")
    parser.add_argument("--mode", choices=["viral", "equal", "transform"], default="viral", help="Detection mode: 'viral' (best 30-45s clips), 'equal' (evenly sliced) or 'transform' (AI rewrite + voiceover, 21/30/59s outputs)")
    parser.add_argument("--keep-source", action="store_true", help="Keep the downloaded source file")
    parser.add_argument("--no-notify", action="store_true", help="Do not send Telegram messages")
    parser.add_argument("--clip-max-seconds", type=float, default=25.0, help="Max clip length in seconds (default 25)")
    parser.add_argument("--original-channel", help="Original creator handle for the attribution line")
    parser.add_argument("--transform-speed", type=float, help="Footage speed for transform mode (1.1-1.2)")

    return parser


if __name__ == "__main__":
    sys.exit(run(build_parser().parse_args()))
