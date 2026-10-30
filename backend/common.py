"""Configuration loading (config.json + dashboard overrides) and logging."""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # works both as ``python backend/main.py`` and ``python -m backend.main``
    from backend import paths
except ImportError:  # pragma: no cover
    import paths  # type: ignore

_lock = threading.Lock()

# Load .env for local runs; Render injects real env vars directly.
try:
    from dotenv import load_dotenv

    load_dotenv(paths.ROOT / ".env")
except ImportError:  # pragma: no cover
    pass

DEFAULTS: dict[str, Any] = {
    "timezone": "Africa/Nairobi",
    "posting_times": ["19:00", "21:00"],
    "shorts_per_video": 10,
    "clip_min_seconds": 30,
    "clip_max_seconds": 45,
    "playback_speed": 1.1,
    "drum_volume_db": -22,
    "caption_color": "#FFD700",
    "caption_words_per_card": 3,
    "hook_seconds": 2,
    "outro_seconds": 2,
    "outro_text": "Follow for more African tales",
    "hashtags": "#AfricanTales #AfricanFolklore #Storytime #Shorts",
    "platforms": {"instagram": True, "tiktok": True},
    "youtube_auto_post": False,
    "viral_keywords": [],
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _replace_with_retry(src: Path, dst: Path) -> None:
    """``os.replace`` with bounded retries for Windows sharing violations.

    On Windows the rename fails with ``WinError 32`` (or EACCES) while another
    process briefly holds the destination open for reading. The readers here
    are millisecond-long JSON parses, so a few short retries clear the window;
    the original error is re-raised if the retries are exhausted.
    """
    delay = 0.02
    for attempt in range(8):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.5)


def write_json(path: Path, data: Any) -> None:
    """Atomically write JSON so readers never see a half-written file.

    The temporary file lives next to the destination with a unique name from
    ``mkstemp`` (exclusive creation), so concurrent writers - the Python
    worker, the Telegram bot, the Node dashboard - can never open the same
    ``.tmp`` file. Sharing one fixed name is what raised ``WinError 32``
    ("file is being used by another process") when renaming it away.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        # mkstemp creates the file 0600; keep the historical 0644 so other
        # local processes (Node, the bot) keep reading it exactly as before.
        try:
            os.chmod(tmp, 0o644)
        except OSError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        _replace_with_retry(tmp, path)
    except BaseException:
        # Only this call's uniquely named temporary file is ever removed, so
        # another writer's temporary file can never be deleted by mistake.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def read_lock() -> dict[str, Any]:
    """Read ``generate.lock`` as ``{"job_id", "pid", "created_at"}``.

    Locks written before the ownership fix are a bare job id; those still
    parse to ``{"job_id": ...}`` so ownership can be checked against them.
    Returns ``{}`` when the lock is missing or unreadable (an unreadable lock
    is treated as *owned by nobody*, never as free to delete).
    """
    try:
        raw = paths.LOCK_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    if not raw:
        return {}
    try:
        info = json.loads(raw)
        if isinstance(info, dict) and info:
            return info
    except ValueError:
        pass
    return {"job_id": raw}


def remove_lock_if_owned(
    job_id: str | None = None, pid: int | None = None
) -> bool:
    """Delete ``generate.lock`` only when it belongs to this job/worker.

    A cancellation, an exit handler or a signal must never drop a lock that a
    *different* generation job is holding - that would let a second worker
    start next to a live one. When ``job_id`` is given it must match the lock
    exactly (a recycled PID can then never free a foreign job's lock); the
    ``pid`` match is only used by callers that pass no ``job_id``.
    Returns True only when the lock existed, matched, and was removed.
    """
    info = read_lock()
    if not info:
        return False
    if job_id is not None:
        owned = str(info.get("job_id", "")) == str(job_id)
    elif pid is not None and info.get("pid") is not None:
        try:
            owned = int(info["pid"]) == int(pid)
        except (TypeError, ValueError):
            owned = False
    else:
        owned = False
    if not owned:
        return False
    try:
        paths.LOCK_FILE.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def load_config() -> dict[str, Any]:
    """Non-secret configuration: committed defaults overridden by config.json.

    Credentials never come from a file. Render's disk is wiped on every deploy,
    so every consumer reads its tokens straight from the environment
    (``os.getenv``) - there is no settings.json override any more.
    """
    cfg = dict(DEFAULTS)
    cfg.update(_read_json(paths.CONFIG_FILE))
    if not cfg.get("posting_times"):
        cfg["posting_times"] = DEFAULTS["posting_times"]
    return cfg


def log(level: str, message: str, **fields: Any) -> None:
    entry = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "level": level,
        "message": message,
    }
    if fields:
        entry.update(fields)
    line = f"[{entry['ts']}] {level.upper():<7} {message}"
    with _lock:
        print(line, file=sys.stderr, flush=True)
        try:
            paths.STATE.mkdir(parents=True, exist_ok=True)
            with open(paths.LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass


def info(message: str, **fields: Any) -> None:
    log("info", message, **fields)


def warn(message: str, **fields: Any) -> None:
    log("warn", message, **fields)


def error(message: str, **fields: Any) -> None:
    log("error", message, **fields)


def record_analytics_point(date: str, views: int = 0) -> bool:
    """Best-effort: record one day's point on ``POST /api/analytics``.

    The dashboard chart reads ``state/analytics.json``, which only the Next.js
    route writes, so the posting code has to hand its point over HTTP once a
    day after a successful post. Same rule as logging: analytics must never
    break a post, so every failure is swallowed and reported as a warning.
    """
    base = (
        os.getenv("PUBLIC_BASE_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or "http://localhost:3000"
    ).rstrip("/")
    headers = {"Content-Type": "application/json"}
    user = os.getenv("DASHBOARD_USER")
    password = os.getenv("DASHBOARD_PASSWORD")
    if user and password:
        # The middleware challenges every route except health/auth/media/thumb,
        # so a server-to-server call has to present the dashboard credentials.
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    try:
        import requests

        response = requests.post(
            f"{base}/api/analytics",
            json={"date": date, "views": int(views or 0)},
            headers=headers,
            timeout=5,
        )
        if response.status_code >= 400:
            warn(f"Analytics point for {date} rejected: HTTP {response.status_code}")
            return False
        info(f"Analytics point recorded for {date}")
        return True
    except Exception as exc:  # never let analytics break the posting flow
        warn(f"Analytics point for {date} not recorded: {exc}")
        return False


def clear_logs() -> dict[str, int]:
    """Empty the activity tail and delete the per-job ``.log`` files.

    Mirrors ``DELETE /api/logs`` in the dashboard so both entry points behave
    the same: the tail is truncated (never unlinked) because workers append to
    it with ``O_APPEND``, and job logs that are still held open by a running
    job are skipped instead of raising.
    """
    paths.STATE.mkdir(parents=True, exist_ok=True)
    activity = 0
    try:
        paths.LOG_FILE.write_text("", encoding="utf-8")
        activity = 1
    except OSError:
        pass
    job_logs = 0
    for directory in (paths.STATE, paths.JOBS, paths.LOGS):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.log")):
            try:
                path.unlink()
                job_logs += 1
            except OSError:
                continue  # a running job still has the file open
    return {"activity": activity, "job_logs": job_logs}
