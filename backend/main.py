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
from typing import Any, Iterable, Sequence

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

try:
    from backend import broll as broll_mod
    from backend import captions, common, paths, quality, renderer, scheduling, selection, telegram, transform, transcript_boundaries, transcript_quality, viral
except ImportError:  # pragma: no cover - fallback for direct execution
    import broll as broll_mod  # type: ignore
    import captions  # type: ignore
    import common  # type: ignore
    import paths  # type: ignore
    import quality  # type: ignore
    import renderer  # type: ignore
    import scheduling  # type: ignore
    import selection  # type: ignore
    import telegram  # type: ignore
    import transform  # type: ignore
    import transcript_boundaries  # type: ignore
    import transcript_quality  # type: ignore
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
            "requested_count": num_shorts,
            "selected_count": 0,
            "rendered_count": 0,
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
        """Write the terminal document with requested/selected/rendered counts.

        The message never claims the requested number when selection or
        rendering produced fewer clips: the dashboard shows this sentence, so
        it has to be truthful on its own.
        """
        payload = dict(extra)
        requested = int(
            payload.pop("requested_count", None)
            or self.data.get("requested_count")
            or self.data.get("num_shorts")
            or 0
        )
        rendered = len(clips)
        pieces = payload.get("pieces_rendered")
        if pieces is not None and requested:
            message = (
                f"{pieces}/{requested} transformed pieces ready "
                f"({rendered} platform files)"
            )
        elif requested and rendered < requested:
            message = f"{rendered} of {requested} shorts ready (shortfall)"
        else:
            message = f"{rendered} shorts ready"
        payload.setdefault("requested_count", requested)
        # Transform renders `pieces` source segments into `files` platform
        # videos. Report pieces as the rendered count so "10 requested" reads
        # against 10 pieces, with the file count kept separately.
        payload["rendered_count"] = pieces if pieces is not None else rendered
        if pieces is not None:
            payload["rendered_files"] = rendered
        self.data.update(
            status="done",
            stage="complete",
            progress=100,
            message=message,
            clips=clips,
            **payload,
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


def _resolve_whisper_language(args: argparse.Namespace, cfg: dict) -> str | None:
    """Resolve an optional explicit language; return None for auto-detect.

    Precedence is per-job CLI/API, then env, then saved config. "auto" is the
    default and deliberately passes no language to faster-whisper.
    """
    raw = (
        getattr(args, "language", None)
        or os.getenv("WHISPER_LANGUAGE")
        or cfg.get("language")
        or "auto"
    )
    value = str(raw).strip()
    if not value or value.lower() == "auto":
        return None
    return value


def _safe_tokens(value: Any) -> list[int] | None:
    """Keep decoded token ids when present; never manufacture missing ids."""
    if value is None:
        return None
    try:
        raw_tokens = list(value)
    except TypeError:
        return None
    tokens: list[int] = []
    for item in raw_tokens:
        token = transcript_quality.optional_int(item)
        if token is not None:
            tokens.append(token)
    return tokens


def _all_language_probabilities(value: Any) -> list[list[Any]] | None:
    """Normalise ``info.all_language_probs`` into JSON-safe pairs."""
    if value is None:
        return None
    try:
        entries = list(value)
    except TypeError:
        return None
    result: list[list[Any]] = []
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        result.append([str(entry[0]), transcript_quality.finite_float(entry[1])])
    return result


def _word_evidence(word: Any) -> dict[str, Any]:
    """Preserve a word's timing, text and probability without inventing data."""
    return {
        "start": transcript_quality.finite_float(getattr(word, "start", None)),
        "end": transcript_quality.finite_float(getattr(word, "end", None)),
        "word": str(getattr(word, "word", "") or "").strip(),
        "probability": transcript_quality.finite_float(
            getattr(word, "probability", None)
        ),
    }


def _segment_evidence(segment: Any) -> dict[str, Any]:
    """Preserve the segment fields faster-whisper exposes, including quality."""
    words = [
        _word_evidence(word)
        for word in (getattr(segment, "words", None) or [])
        if getattr(word, "word", None)
    ]
    return {
        "id": transcript_quality.optional_int(getattr(segment, "id", None)),
        "seek": transcript_quality.optional_int(getattr(segment, "seek", None)),
        "start": transcript_quality.finite_float(getattr(segment, "start", None)),
        "end": transcript_quality.finite_float(getattr(segment, "end", None)),
        "text": str(getattr(segment, "text", "") or "").strip(),
        "avg_logprob": transcript_quality.finite_float(
            getattr(segment, "avg_logprob", None)
        ),
        "no_speech_prob": transcript_quality.finite_float(
            getattr(segment, "no_speech_prob", None)
        ),
        "compression_ratio": transcript_quality.finite_float(
            getattr(segment, "compression_ratio", None)
        ),
        "temperature": transcript_quality.finite_float(
            getattr(segment, "temperature", None)
        ),
        "tokens": _safe_tokens(getattr(segment, "tokens", None)),
        "words": words,
    }


def _write_transcript_evidence(
    job: Job,
    segments: list[dict[str, Any]],
    info: Any,
    *,
    requested_language: str,
    detected_language: str,
    language_probability: float | None,
    total_duration: float,
) -> Path | None:
    """Write the raw transcript and its metrics under ``exports/<job_id>``.

    The sidecar is deliberately separate from the job document: segments can
    be large, and the job/manifest only need the small quality summary and the
    relative sidecar name.  The source URL and environment are never copied
    into this file.
    """
    job_id = getattr(job, "id", None)
    if not isinstance(job_id, str) or not job_id:
        return None

    quality = transcript_quality.summarize_transcript(
        segments,
        duration=total_duration,
        duration_after_vad=getattr(info, "duration_after_vad", None),
        language_probability=language_probability,
        all_language_probs=getattr(info, "all_language_probs", None),
    )
    payload = {
        "version": 1,
        "job_id": job_id,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "language": detected_language,
        "language_probability": language_probability,
        "language_requested": requested_language or "auto",
        "duration": transcript_quality.finite_float(total_duration),
        "duration_after_vad": transcript_quality.finite_float(
            getattr(info, "duration_after_vad", None)
        ),
        "all_language_probs": _all_language_probabilities(
            getattr(info, "all_language_probs", None)
        ),
        "segment_count": len(segments),
        "text": " ".join(
            str(segment.get("text") or "").strip() for segment in segments
        ).strip(),
        "segments": segments,
        "quality": quality,
    }

    sidecar = paths.EXPORTS / job_id / "transcript.json"
    try:
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        common.write_json(sidecar, payload)
    except (OSError, TypeError, ValueError) as exc:
        common.warn(
            "Could not write transcript sidecar "
            f"({common.redact_secrets(str(exc))[:200]})"
        )
        job.update(transcript_quality=quality, transcript_sidecar=None)
        return None

    job.update(
        transcript_quality=quality,
        transcript_sidecar="transcript.json",
    )
    return sidecar


def transcribe(
    audio: Path, job: Job, language: str | None = None
) -> tuple[list[dict], str, float]:
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
    requested_language = (language or "").strip()
    try:
        transcribe_options = {
            "word_timestamps": True,
            # Chunked decoding: the audio is processed in 30-second segments
            # instead of one giant (1, samples, n_mels) array, which is what
            # blew past the memory limit (~950 MiB) on long sources.
            "chunk_length": 30,
            # Greedy decoding keeps only one hypothesis alive (no beam search
            # scratch space) - much lighter on a 512 MB box.
            "beam_size": 1,
            # VAD filter enabled: silent stretches are skipped entirely, so
            # they never reach the feature extractor and peak RAM stays down.
            "vad_filter": True,
            "condition_on_previous_text": False,
        }
        if requested_language and requested_language.lower() != "auto":
            transcribe_options["language"] = requested_language
        segment_iter, info = model.transcribe(str(audio), **transcribe_options)
    except Exception as exc:
        raise JobError(f"Transcription failed: {exc}") from exc

    total = float(getattr(info, "duration", 0.0) or 0.0)
    segments: list[dict] = []
    for seg in segment_iter:
        # Keep every available Whisper field here. Selection still consumes only
        # the fields it understood before; this evidence is for the sidecar and
        # quality summary, not for changing selection behavior.
        segments.append(_segment_evidence(seg))
        if total:
            pct = 22 + int(min(1.0, float(seg.end) / total) * 20)
            job.update(progress=pct, message=f"Transcribing audio ({pct}%)")

    detected_language = getattr(info, "language", requested_language or "en") or "en"
    raw_probability = getattr(info, "language_probability", None)
    try:
        language_probability = (
            round(float(raw_probability), 4) if raw_probability is not None else None
        )
    except (TypeError, ValueError):
        language_probability = None
    job.update(
        language=detected_language,
        language_probability=language_probability,
        language_requested=requested_language or "auto",
    )
    _write_transcript_evidence(
        job,
        segments,
        info,
        requested_language=requested_language,
        detected_language=detected_language,
        language_probability=language_probability,
        total_duration=total,
    )
    if not segments:
        common.warn("Whisper returned no speech; clips will use visual-only mode")
    common.info(
        f"Whisper language: {detected_language} "
        f"(requested={requested_language or 'auto'}, "
        f"confidence={language_probability if language_probability is not None else 'n/a'})"
    )
    return segments, detected_language, total


def _trim_to_words(
    candidate: viral.Candidate,
    video_duration: float,
    min_seconds: float = 5.0,
    max_seconds: float | None = None,
    language: str | None = None,
) -> tuple[float, float]:
    """Return word-refined clip bounds, or the original segment bounds."""
    if isinstance(candidate.boundary, dict) and candidate.boundary.get("applied"):
        return round(candidate.start, 3), round(candidate.end, 3)
    allowed_end = float(video_duration or candidate.end)
    limit = float(max_seconds or allowed_end)
    result = transcript_boundaries.refine_candidate(
        candidate,
        0.0,
        allowed_end,
        min_seconds,
        limit,
        language=language,
    )
    if result.get("within_limits"):
        return round(float(result["start"]), 3), round(float(result["end"]), 3)
    return round(candidate.start, 3), round(candidate.end, 3)


def _relative_words(
    candidate: viral.Candidate,
    clip_start: float,
    clip_end: float | None = None,
) -> list[captions.CaptionWord]:
    """Caption words intersecting the final clip, relative to its start."""
    start = transcript_boundaries.finite_time(clip_start)
    end = transcript_boundaries.finite_time(
        candidate.end if clip_end is None else clip_end
    )
    if start is None or end is None or end <= start:
        return []
    duration = end - start
    out: list[captions.CaptionWord] = []
    for word in candidate.words:
        word_start = transcript_boundaries.finite_time(getattr(word, "start", None))
        word_end = transcript_boundaries.finite_time(getattr(word, "end", None))
        if word_start is None or word_end is None or word_end <= word_start:
            continue
        if word_end <= start or word_start >= end:
            continue
        rel_start = max(0.0, word_start - start)
        rel_end = min(duration, word_end - start)
        if rel_end <= rel_start:
            continue
        out.append(
            captions.CaptionWord(
                start=rel_start,
                end=rel_end,
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


def _trim_piece_variants(
    job_id: str, piece_index: int, rendered_tags: Sequence[str]
) -> None:
    """Rewrite a piece's queue items so ``variants`` lists only real files."""
    prefix = f"{job_id}-{piece_index:02d}-"
    keep = set(rendered_tags)
    for path in sorted(paths.QUEUE.glob(f"{prefix}*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        variants = [
            variant
            for variant in item.get("variants") or []
            if str(variant.get("id", "")).rsplit("-", 1)[-1] in keep
        ]
        if variants != item.get("variants"):
            item["variants"] = variants
            common.write_json(path, item)


def _segments_text(
    segments: Iterable[viral.Segment], start: float, end: float
) -> str:
    """Transcript text that overlaps a source window."""
    return " ".join(
        segment.text.strip()
        for segment in segments
        if segment.start < end and segment.end > start
    ).strip()


def _discard_failed_voiceover(path: Path, label: str) -> None:
    """Delete the MP3 a failed TTS attempt created - and only that file.

    edge-tts opens the destination before audio arrives, so a failed attempt
    leaves a zero-byte or truncated file in the job directory. The caller skips
    the variant, which makes the leftover an orphan: it is never queued or
    referenced. Cleanup is path-exact (no globbing) so another piece's, job's
    or process's audio can never be removed, and a cleanup failure is logged
    on its own line so the original TTS error stays the reported one.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        common.warn(f"Transform {label} cleanup failed for {path.name}: {exc}")


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
    count: int,
    channel: str = "",
    mode: str,
) -> tuple[list[dict], int]:
    """Rewrite and voice N distinct source segments into platform variants.

    Selection is deliberately different from Viral Moments: each piece is a
    60-110 s source window, long enough to narrate the longest target, chosen
    best-first with overlap rejection so no two pieces reuse the same footage.
    Each piece then gets its own rewritten narration, and each platform target
    (21/30/59 s) gets its own complete-thought edit of that narration and its
    own edge-tts voiceover. A variant is therefore never the same audio
    truncated at a different length.

    Pixabay B-roll is fetched per piece from a query derived from that piece's
    narration (not one fixed search term) and is used as the visual bed.
    Returns ``(queue_items, pieces_rendered)``.
    """
    segments = viral.build_segments(segments_raw)
    rms = viral.compute_rms(str(audio))
    keywords = cfg.get("viral_keywords") or viral.DEFAULT_KEYWORDS
    pieces, piece_report = selection.select_transform(
        segments, rms, keywords, duration, count, language
    )
    if not pieces:
        raise JobError("Transform mode found no usable source segment")

    footage_speed = max(
        1.1, min(1.2, float(cfg.get("transform_speed", 1.15) or 1.15))
    )
    handle = (
        os.getenv("WATERMARK_HANDLE", "").strip()
        or str(cfg.get("handle", "") or "").strip()
    )
    pixabay_key = os.getenv("PIXABAY_API_KEY", "").strip()
    total_variants = len(pieces) * len(TRANSFORM_FORMATS)
    occupied = scheduling.occupied_queue_slots(paths.QUEUE, cfg)
    slots = scheduling.next_available_slots(
        cfg, total_variants, occupied=occupied
    )
    queue_items: list[dict] = []
    errors: list[str] = []
    narration_sources: list[str] = []
    pieces_rendered = 0
    rendered_variants = 0

    job.update(
        stage="analyze",
        progress=44,
        message=(
            f"Rewriting {len(pieces)} of {count} source segments "
            f"(each into up to {len(TRANSFORM_FORMATS)} platform versions)"
        ),
        language=language,
        selected_count=len(pieces),
        fallback_count=piece_report.get("fallback", 0),
        selection_quality={
            key: piece_report.get(key)
            for key in ("quality", "quality_rejected", "quality_rejections")
            if key in piece_report
        },
    )

    for piece_index, piece in enumerate(pieces, start=1):
        piece_text = (piece.candidate.text or "").strip() or _segments_text(
            segments, piece.start, piece.end
        )
        if not piece_text:
            errors.append(f"piece {piece_index}: no transcript")
            common.warn(f"Transform piece {piece_index} has no transcript - skipped")
            continue
        assessment = piece.candidate.quality
        if isinstance(assessment, dict) and assessment.get("status") == "poor":
            reason = "; ".join(assessment.get("reasons") or [])[:240]
            errors.append(
                f"piece {piece_index}: rejected poor transcript quality"
                + (f" ({reason})" if reason else "")
            )
            common.warn(
                f"Transform piece {piece_index} was not rewritten: poor transcript quality"
            )
            continue

        job.update(
            progress=44 + int((piece_index - 1) / max(1, len(pieces)) * 8),
            message=f"Rewriting source segment {piece_index}/{len(pieces)}",
        )
        script, llm_source = transform.rewrite_script(
            piece_text,
            max_words=transform.words_for_seconds(TRANSFORM_FORMATS[-1][0]),
        )
        narration_sources.append(llm_source)
        if not script:
            errors.append(f"piece {piece_index}: empty rewrite")
            continue
        meta, meta_source = transform.generate_metadata(script, channel)
        job.update(
            llm_model=transform.LAST_MODEL or None,
            llm_fallback_reason=transform.LAST_FALLBACK_REASON or None,
        )

        piece_broll = broll_path
        if pixabay_key:
            try:
                piece_broll = (
                    broll_mod.fetch(transform.broll_query(script, keywords))
                    or broll_path
                )
            except Exception as exc:  # B-roll is cosmetic - never fail a piece
                common.warn(f"Per-piece B-roll unavailable: {exc}")

        # Every sibling render carries the full manifest so the dashboard can
        # offer this piece's platform versions on one clip card.
        variants = [
            {
                "id": f"{job_id}-{piece_index:02d}-{tag}",
                "platform": tag,
                "label": label,
                "seconds": secs,
            }
            for secs, label, tag in TRANSFORM_FORMATS
        ]
        hook = script.split(". ")[0].strip().rstrip(".") or "Transformed Story"
        base_title = hook.title() if hook else "Transformed Story"
        piece_rendered = False
        rendered_tags: list[str] = []

        for seconds, platform, tag in TRANSFORM_FORMATS:
            target_words = transform.words_for_seconds(seconds)
            variant_script = transform.fit_script(script, target_words)
            # A short rewrite/fallback (especially when the provider failed)
            # must not become a mostly-silent 21/30/59 s video. Extend it from
            # the source transcript first; the duration check after TTS is the
            # final guard when the source simply has no more speech.
            if len(variant_script.split()) < int(target_words * 0.65):
                variant_script = transform.extend_script(
                    variant_script, piece_text, target_words
                )
            if not variant_script:
                errors.append(f"piece {piece_index} {tag}: empty script")
                continue
            clip_id = f"{job_id}-{piece_index:02d}-{tag}"
            job.update(
                stage="render",
                progress=50 + int(rendered_variants / max(1, total_variants) * 44),
                message=(
                    f"Rendering segment {piece_index}/{len(pieces)} - "
                    f"{seconds}s {platform}"
                ),
            )

            vo_path = job_dir / f"{clip_id}.mp3"
            try:
                _, vo_words = transform.synthesize_voiceover(
                    variant_script, vo_path
                )
                vo_info = renderer.probe(vo_path)
                if float(vo_info.get("duration") or 0.0) <= 0.5:
                    raise RuntimeError("voiceover is too short")
            except Exception as exc:
                # A missing edge-tts (package, network) must not lose the other
                # pieces: record the limitation and keep going.
                errors.append(
                    f"piece {piece_index} {tag}: voiceover unavailable ({exc})"
                )
                common.warn(f"Transform {clip_id} skipped: {exc}")
                # Only this attempt's own output is removed; the TTS error above
                # was already recorded and is never replaced by a cleanup error.
                _discard_failed_voiceover(vo_path, clip_id)
                continue

            target = float(seconds)
            voiceover_seconds = float(vo_info.get("duration") or 0.0)
            if voiceover_seconds < target * transform.MIN_NARRATION_RATIO:
                errors.append(
                    f"piece {piece_index} {tag}: narration incomplete "
                    f"({voiceover_seconds:.1f}s of {target:.0f}s; "
                    f"minimum {transform.MIN_NARRATION_RATIO:.0%})"
                )
                common.warn(
                    f"Transform {clip_id} skipped: narration is only "
                    f"{voiceover_seconds:.1f}s for a {target:.0f}s target"
                )
                _discard_failed_voiceover(vo_path, clip_id)
                continue
            caption_words = [
                captions.CaptionWord(
                    start=float(word["start"]),
                    end=float(word["end"]),
                    text=str(word["text"]),
                )
                for word in vo_words
                if float(word["start"]) < target
            ]

            piece_start = max(0.0, piece.start)
            piece_end = min(duration, piece.end)
            window = min(piece_end - piece_start, target * footage_speed)
            if window <= 0.5:
                errors.append(
                    f"piece {piece_index} {tag}: source window too short"
                )
                continue
            bed_start = min(piece_start, max(0.0, duration - window))
            win_end = min(duration, bed_start + window)
            clip_path = job_dir / f"{clip_id}.mp4"
            thumb_path = job_dir / f"{clip_id}.jpg"
            try:
                render_meta = renderer.render_clip(
                    source,
                    clip_path,
                    bed_start,
                    win_end,
                    caption_words,
                    cfg,
                    hook=hook,
                    transcript=variant_script,
                    broll=piece_broll,
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
                    force_broll=True,
                    captions_during_hook=True,
                )
            except Exception as exc:  # one bad variant must not sink the job
                detail = common.redact_secrets(str(exc))[:300]
                errors.append(f"piece {piece_index} {tag}: render failed ({detail})")
                common.warn(f"Transform {clip_id} render failed: {detail}")
                # The renderer drops its own output; the ASS sidecar and any
                # thumbnail are this loop's to clean up.
                for leftover in (clip_path, thumb_path, clip_path.with_suffix(".ass")):
                    try:
                        leftover.unlink(missing_ok=True)
                    except OSError:
                        pass
                continue
            slot = (
                slots[rendered_variants]
                if rendered_variants < len(slots)
                else scheduling.next_available_slots(
                    cfg, 1, occupied=occupied | set(slots)
                )[0]
            )
            item = _build_queue_item(
                clip_id=clip_id,
                job_id=job_id,
                source_url=source_url,
                source_title=base_title,
                title=f"{base_title} ({seconds}s {platform})",
                hook=hook,
                caption=f"{hook} {hashtags}".strip(),
                transcript=variant_script,
                viral_score=None,
                reasons=[
                    f"transform:{llm_source}",
                    f"voiceover:{seconds}s",
                    f"source:{piece.start:.1f}-{piece.end:.1f}s",
                ],
                start=bed_start,
                end=win_end,
                mode=mode,
                scheduled=scheduling.queue_slot(slot, cfg),
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
                    "piece": piece_index,
                    "variants": variants,
                    "fallback": bool(piece.fallback),
                    "broll": render_meta.get("broll"),
                    "quality": quality.compact(piece.candidate.quality),
                },
            )
            _persist_queue_item(item, clip_path, thumb_path)
            queue_items.append(item)
            rendered_variants += 1
            rendered_tags.append(tag)
            piece_rendered = True

        if piece_rendered:
            pieces_rendered += 1
            # The manifest was built before rendering, so drop the platform
            # versions that never produced a file instead of advertising a
            # download that 404s.
            _trim_piece_variants(job_id, piece_index, rendered_tags)

    llm_counts: dict[str, int] = {}
    for source_name in narration_sources:
        llm_counts[source_name] = llm_counts.get(source_name, 0) + 1
    llm_source = "none"
    if len(llm_counts) == 1:
        llm_source = next(iter(llm_counts))
    elif llm_counts:
        llm_source = "mixed"
    job.update(
        stage="render",
        progress=94,
        message=(
            f"{pieces_rendered}/{len(pieces)} transformed segments rendered "
            f"({len(queue_items)} platform files)"
        ),
        rendered_count=pieces_rendered,
        rendered_files=len(queue_items),
        transform_errors=errors[-10:],
        selection_quality={
            key: piece_report.get(key)
            for key in ("quality", "quality_rejected", "quality_rejections")
            if key in piece_report
        },
        # Real Gemini narration vs template fallback is a fact about the job,
        # not just a per-clip reason string. Template output is what keeps a
        # job alive when the provider is down, so it must stay visible.
        llm_source=llm_source,
        llm_sources=llm_counts,
        llm_fallback=llm_counts.get("template", 0) > 0,
        llm_fallback_count=llm_counts.get("template", 0),
    )
    if not queue_items:
        detail = errors[0] if errors else "voiceover dependency unavailable"
        raise JobError(f"Transform produced no outputs: {detail}")
    return queue_items, pieces_rendered


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
    # Saved browser preferences arrive as one JSON blob. They are applied first
    # so every explicit per-job flag below still wins over a stored value.
    if getattr(args, "user_config_json", None):
        try:
            user_prefs = json.loads(args.user_config_json)
        except (TypeError, ValueError):
            user_prefs = None
        if isinstance(user_prefs, dict):
            selection.apply_user_config(cfg, user_prefs)
    if getattr(args, "youtube_auto_post", None):
        cfg["youtube_auto_post"] = args.youtube_auto_post == "true"
    if getattr(args, "transform_speed", None):
        cfg["transform_speed"] = args.transform_speed
    if getattr(args, "clip_max_seconds", None) is not None:
        try:
            requested_max = float(args.clip_max_seconds)
        except (TypeError, ValueError):
            requested_max = 0.0
        if requested_max > 0:
            cfg["clip_max_seconds"] = requested_max

    # Per-job user-config overrides (from the browser localStorage Preferences).
    # These only touch the fields the settings UI lets the user personalise and
    # only for this run; the committed config.json is untouched.
    if getattr(args, "user_timezone", None):
        cfg["timezone"] = args.user_timezone
    if getattr(args, "user_posting_times", None):
        try:
            parsed = json.loads(args.user_posting_times)
            if isinstance(parsed, list) and parsed:
                cfg["posting_times"] = [str(t).strip() for t in parsed if str(t).strip()]
        except (TypeError, ValueError):
            pass
    for key, attr in [
        ("shorts_per_video", "user_shorts_per_video"),
        ("clip_min_seconds", "user_clip_min_seconds"),
        ("clip_max_seconds", "user_clip_max_seconds"),
        ("playback_speed", "user_playback_speed"),
        ("drum_volume_db", "user_drum_volume_db"),
        ("caption_words_per_card", "user_caption_words_per_card"),
        ("hook_seconds", "user_hook_seconds"),
        ("outro_seconds", "user_outro_seconds"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            try:
                cfg[key] = float(val)
            except (TypeError, ValueError):
                pass
    if getattr(args, "user_outro_text", None):
        cfg["outro_text"] = str(args.user_outro_text)
    if getattr(args, "user_hashtags", None):
        cfg["hashtags"] = str(args.user_hashtags)
    if getattr(args, "user_caption_color", None):
        cfg["caption_color"] = str(args.user_caption_color)
    if getattr(args, "user_instagram", None):
        cfg["platforms"]["instagram"] = args.user_instagram == "true"
    if getattr(args, "user_tiktok", None):
        cfg["platforms"]["tiktok"] = args.user_tiktok == "true"
    if getattr(args, "timezone", None):
        cfg["timezone"] = args.timezone
    if getattr(args, "posting_times", None):
        try:
            parsed = json.loads(args.posting_times)
            if isinstance(parsed, list) and parsed:
                cfg["posting_times"] = [str(t).strip() for t in parsed if str(t).strip()]
        except (TypeError, ValueError):
            pass
    for key, attr in [
        ("shorts_per_video", "shorts_per_video"),
        ("clip_min_seconds", "clip_min_seconds"),
        ("clip_max_seconds", "clip_max_seconds"),
        ("playback_speed", "playback_speed"),
        ("drum_volume_db", "drum_volume_db"),
        ("caption_words_per_card", "caption_words_per_card"),
        ("hook_seconds", "hook_seconds"),
        ("outro_seconds", "outro_seconds"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            try:
                cfg[key] = float(val)
            except (TypeError, ValueError):
                pass
    transcribe_language = _resolve_whisper_language(args, cfg)
    min_s, max_s = selection.duration_bounds(cfg)
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
            # Equal-slices mode: transcribe so each interval can be matched to
            # a complete spoken thought, then pick one segment per interval.
            # The D/N intervals are search regions, never clip lengths.
            segments_raw, language, _ = transcribe(audio, job, language=transcribe_language)
            job.update(
                stage="analyze",
                progress=44,
                message=f"Finding a complete segment in each of {num_shorts} equal intervals",
                language=language,
            )
            segments = viral.build_segments(segments_raw)
            keywords = cfg.get("viral_keywords") or viral.DEFAULT_KEYWORDS
            selected, equal_report = selection.select_equal(
                segments, duration, num_shorts, min_s, max_s, keywords, language
            )
            empty_intervals = [
                row for row in equal_report["intervals"] if not row["selected"]
            ]
            job.update(
                stage="render",
                progress=46,
                message=(
                    f"Rendering {len(selected)} of {num_shorts} equal-slice clips"
                    + (
                        f" ({len(empty_intervals)} intervals had no usable speech)"
                        if empty_intervals
                        else ""
                    )
                ),
                candidates=equal_report.get("selected", len(selected)),
                selected_count=len(selected),
                empty_intervals=len(empty_intervals),
                selection_quality={
                    key: equal_report.get(key)
                    for key in ("quality", "quality_rejected")
                    if key in equal_report
                },
            )
            if empty_intervals:
                common.warn(
                    f"Equal Slices: {len(empty_intervals)} of {num_shorts} intervals "
                    "had no complete speech segment within the duration limits"
                )
            if not selected:
                raise JobError("Equal Slices found no usable speech in any interval")
        elif mode == "viral":
            # Viral mode: score the transcript, then keep the strongest
            # distinct moments. A transcript-less source gets evenly spaced
            # visual windows, flagged as fallbacks with no viral score.
            segments_raw, language, _ = transcribe(audio, job, language=transcribe_language)
            job.update(
                stage="analyze",
                progress=44,
                message=f"Scoring {len(segments_raw)} transcript segments for viral moments",
                language=language,
            )

            rms = viral.compute_rms(str(audio))
            segments = viral.build_segments(segments_raw)
            keywords = cfg.get("viral_keywords") or viral.DEFAULT_KEYWORDS
            selected, viral_report = selection.select_viral(
                segments, rms, keywords, num_shorts, min_s, max_s, duration, language
            )
            if not selected:
                raise JobError(
                    "No usable segments found in this video"
                    + (
                        f" (no transcript window inside {min_s:g}-{max_s:g}s)"
                        if segments
                        else " (no transcript)"
                    )
                )
            shortfall = viral_report["shortfall"]
            job.update(
                stage="render",
                progress=46,
                message=(
                    f"Rendering {len(selected)} of {num_shorts} vertical shorts"
                    + (f" ({shortfall} fewer than requested)" if shortfall else "")
                ),
                candidates=viral_report["candidates"],
                selected_count=len(selected),
                fallback_count=viral_report["fallback"],
                selection_quality={
                    key: viral_report.get(key)
                    for key in ("quality", "quality_rejected")
                    if key in viral_report
                },
            )
        else:
            # Transform mode: transcribe, then rewrite N distinct source
            # segments into N transformed pieces (each with platform variants).
            segments_raw, language, _ = transcribe(audio, job, language=transcribe_language)
            selected = []

            if not segments_raw:
                raise JobError("Transform mode needs a transcript - no speech found")
            job.update(selected_count=0)

        broll_path = None
        if os.getenv("PIXABAY_API_KEY", "").strip():
            broll_path = broll_mod.fetch()
            if broll_path:
                job.update(message="Pixabay B-roll cached for face-less fallbacks")

        job_dir = _next_job_dir(job_id)
        queue_items: list[dict[str, Any]] = []
        pieces_rendered: int | None = None
        occupied = scheduling.occupied_queue_slots(paths.QUEUE, cfg)
        slots = scheduling.next_available_slots(
            cfg, len(selected), occupied=occupied
        )
        hashtags = str(cfg.get("hashtags", ""))

        if mode == "transform":
            queue_items, pieces_rendered = _render_transform(
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
                count=num_shorts,
                channel=channel,
                mode=mode,
            )

        for index, selected_item in enumerate(selected, start=1):
            # Phase 6 defect A: selection returns ``Selected`` wrappers around
            # a ``viral.Candidate``, but the render loop was reading ``.score``,
            # ``.words`` and ``.text`` off the wrapper itself - which raised
            # AttributeError on the first clip of every Viral/Equal job.
            # Unwrap once here; the fallback flag drives the queue metadata
            # below so a fallback window is never presented as a scored moment.
            candidate = selected_item.candidate
            is_fallback = selected_item.fallback
            clip_id = f"{job_id}-{index:02d}"
            base_pct = 46 + int((index - 1) / max(1, len(selected)) * 48)
            title = None
            if mode == "equal":
                # The interval selector already returns word-bounded segments,
                # so the cut keeps the chosen speech intact and never crosses
                # the interval boundary (no overlap with the next slice).
                clip_start = round(candidate.start, 3)
                clip_end = round(candidate.end, 3)
                title = f"Equal Slice {index}"
                job.update(
                    stage="render",
                    progress=base_pct,
                    message=f"Rendering equal slice {index}/{len(selected)}",
                )
            else:
                clip_start, clip_end = _trim_to_words(
                    candidate, duration, min_s, max_s, language
                )
                # A fallback window carries no score (``None``), so the message
                # must not format it as a number.
                score_label = (
                    "-" if candidate.score is None else f"{candidate.score:.0f}"
                )
                job.update(
                    stage="render",
                    progress=base_pct,
                    message=f"Rendering clip {index}/{len(selected)} (score {score_label})",
                )
            words = _relative_words(candidate, clip_start, clip_end)
            hook = viral.hook_text(candidate)
            transcript = candidate.text.strip()
            if title is None:
                title = hook.title() if hook else f"African Tale #{index}"

            clip_path = job_dir / f"{clip_id}.mp4"
            thumb_path = job_dir / f"{clip_id}.jpg"

            # Load the highlight keywords list from config (defaults to
            # DEFAULT_HIGHLIGHT_WORDS in captions.py when not configured).
            highlight_words = cfg.get("highlight_words", captions.DEFAULT_HIGHLIGHT_WORDS)

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
                max_duration=max_s,
            )

            # Queue this clip right away so EVERY rendered clip lands in the
            # queue. This block used to sit outside the loop, which meant only
            # the last clip of a job was ever queued.
            seed_text = (transcript or hook or title or "").strip()
            meta, meta_source = transform.generate_metadata(seed_text, channel)
            slot = (
                slots[index - 1]
                if index - 1 < len(slots)
                else scheduling.next_available_slots(
                    cfg, 1, occupied=occupied | set(slots)
                )[0]
            )
            scheduled = scheduling.queue_slot(slot, cfg)
            queue_reasons = list(candidate.reasons)
            if is_fallback:
                queue_reasons.insert(0, "fallback: evenly spaced visual window")
            queue_reasons.append(f"quality:{quality.status_of(candidate)}")
            item = _build_queue_item(
                clip_id=clip_id,
                job_id=job_id,
                source_url=args.url or str(source),
                source_title=title,
                title=title,
                hook=hook,
                caption=viral.social_caption(candidate, hashtags),
                transcript=transcript,
                # A fallback window is never presented as a scored moment.
                viral_score=(
                    round(candidate.score, 1)
                    if mode == "viral" and not is_fallback
                    else None
                ),
                reasons=queue_reasons,
                start=clip_start,
                end=clip_end,
                mode=mode,
                scheduled=scheduled,
                clip_path=clip_path,
                render_meta=render_meta,
                meta=meta,
                meta_source=meta_source,
                channel=channel,
                extras={
                    **({
                        "fallback": True,
                        "fallback_reason": "no transcript available",
                    } if is_fallback else {}),
                    "quality": quality.compact(candidate.quality),
                },
            )
            _persist_queue_item(item, clip_path, thumb_path)
            queue_items.append(item)

        # Free disk on /tmp: drop the source once it is no longer needed.
        manifest = {
            "job_id": job_id,
            "source_url": args.url or str(source),
            "source_title": title,
            "language": language,
            "language_probability": job.data.get("language_probability"),
            "language_requested": job.data.get("language_requested", "auto"),
            # Additive fields: old jobs/manifests simply lack them and continue
            # to load; the full evidence lives in the relative sidecar.
            "transcript_sidecar": job.data.get("transcript_sidecar"),
            "transcript_quality": job.data.get("transcript_quality"),
            # Additive Stage 3B diagnostic: quality counts and rejected windows
            # used by this run's selection. Old manifests simply lack it.
            "selection_quality": job.data.get("selection_quality"),
            "duration": round(duration, 2),
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "requested_count": num_shorts,
            "selected_count": int(job.data.get("selected_count") or 0),
            "rendered_count": int(
                job.data.get("rendered_count") or len(queue_items)
            ),
            "rendered_files": len(queue_items),
            "clip_count": len(queue_items),
            # Whether narration was really written by the provider or fell back
            # to the template is part of the run's record, not only a log line.
            "llm_source": job.data.get("llm_source"),
            "llm_sources": job.data.get("llm_sources"),
            "llm_model": job.data.get("llm_model"),
            "llm_fallback_reason": job.data.get("llm_fallback_reason"),
            "llm_fallback_count": job.data.get("llm_fallback_count", 0),
            "pieces_rendered": pieces_rendered,
            "clips": queue_items,
        }
        common.write_json(job_dir / "metadata.json", manifest)
        job.finish(
            queue_items,
            export_dir=str(job_dir),
            requested_count=num_shorts,
            **(
                {"pieces_rendered": pieces_rendered}
                if pieces_rendered is not None
                else {}
            ),
        )

        # Auto-post to YouTube Shorts if the user enabled it. The uploader
        # reads its credentials from the environment (YOUTUBE_* variables),
        # the same way every other integration reads its token.
        if cfg.get("youtube_auto_post"):
            from backend import youtube_uploader

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
        # Free disk on /tmp - but ONLY when the source was actually ours to
        # delete. The stray glob below used to run unconditionally, so it
        # re-deleted the very file the ``--keep-source`` branch above had
        # deliberately preserved (defect C in the Phase 6 acceptance run).
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
    parser.add_argument("--language", help="Whisper language code (for example 'en'); default is automatic detection")
    parser.add_argument("--keep-source", action="store_true", help="Keep the downloaded source file")
    parser.add_argument("--no-notify", action="store_true", help="Do not send Telegram messages")
    parser.add_argument("--clip-max-seconds", type=float, default=None, help="Max clip length in seconds (default: config.json clip_max_seconds)")
    parser.add_argument("--user-config-json", help="Saved user preferences as JSON (lowest-priority per-job overrides)")
    parser.add_argument("--original-channel", help="Original creator handle for the attribution line")
    parser.add_argument(
        "--youtube-auto-post",
        choices=["true", "false"],
        dest="youtube_auto_post",
        help="Override the dashboard default for YouTube auto-post this run",
    )
    parser.add_argument("--transform-speed", type=float, help="Footage speed for transform mode (1.1-1.2)")
    parser.add_argument("--timezone", help="User preference: posting timezone for this run")
    parser.add_argument("--posting-times", help="User preference: JSON array of posting times for this run")
    parser.add_argument("--shorts-per-video", type=float, help="User preference: shorts per video for this run")
    parser.add_argument("--clip-min-seconds", type=float, help="User preference: min clip length for this run")
    parser.add_argument("--playback-speed", type=float, help="User preference: playback speed for this run")
    parser.add_argument("--drum-volume-db", type=float, help="User preference: drum volume dB for this run")
    parser.add_argument("--caption-words-per-card", type=float, help="User preference: caption words per card for this run")
    parser.add_argument("--caption-color", help="User preference: caption color hex for this run")
    parser.add_argument("--hook-seconds", type=float, help="User preference: hook seconds for this run")
    parser.add_argument("--outro-seconds", type=float, help="User preference: outro seconds for this run")
    parser.add_argument("--user-timezone", help="User preference: posting timezone for this run")
    parser.add_argument("--user-posting-times", help="User preference: JSON array of posting times for this run")
    parser.add_argument("--user-shorts-per-video", type=float, help="User preference: shorts per video for this run")
    parser.add_argument("--user-clip-min-seconds", type=float, help="User preference: min clip length for this run")
    parser.add_argument("--user-clip-max-seconds", type=float, help="User preference: max clip length for this run")
    parser.add_argument("--user-playback-speed", type=float, help="User preference: playback speed for this run")
    parser.add_argument("--user-drum-volume-db", type=float, help="User preference: drum volume dB for this run")
    parser.add_argument("--user-caption-words-per-card", type=float, help="User preference: caption words per card for this run")
    parser.add_argument("--user-outro-text", help="User preference: outro text for this run")
    parser.add_argument("--user-hashtags", help="User preference: hashtags for this run")
    parser.add_argument("--user-caption-color", help="User preference: caption color hex for this run")
    parser.add_argument("--user-hook-seconds", type=float, help="User preference: hook seconds for this run")
    parser.add_argument("--user-outro-seconds", type=float, help="User preference: outro seconds for this run")
    parser.add_argument("--user-instagram", choices=["true", "false"], help="User preference: enable Instagram for this run")
    parser.add_argument("--user-tiktok", choices=["true", "false"], help="User preference: enable TikTok for this run")
    return parser


if __name__ == "__main__":
    sys.exit(run(build_parser().parse_args()))
