"""Configuration loading (config.json + dashboard overrides) and logging."""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # works both as ``python backend/main.py`` and ``python -m backend.main``
    from . import paths
except ImportError:  # pragma: no cover
    import paths  # type: ignore

_lock = threading.Lock()

# Load .env for local runs; Render injects real env vars directly.
try:
    from dotenv import load_dotenv

    load_dotenv(paths.ROOT / ".env")
except ImportError:  # pragma: no cover
    pass

TOKEN_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "PEXELS_API_KEY",
    "IG_USER_ID",
    "IG_ACCESS_TOKEN",
    "TIKTOK_AUTH_B64",
)

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
    "viral_keywords": [],
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path: Path, data: Any) -> None:
    """Atomically write JSON so readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def apply_env_overrides() -> None:
    """Let tokens saved from the dashboard reach this process and its children."""
    tokens = _read_json(paths.SETTINGS_FILE).get("tokens")
    if not isinstance(tokens, dict):
        return
    for key in TOKEN_KEYS:
        value = tokens.get(key)
        if value and not os.environ.get(key):
            os.environ[key] = str(value)


def load_config() -> dict[str, Any]:
    apply_env_overrides()
    cfg = dict(DEFAULTS)
    cfg.update(_read_json(paths.CONFIG_FILE))
    cfg.update(_read_json(paths.SETTINGS_FILE))
    cfg.pop("tokens", None)
    if not cfg.get("posting_times"):
        cfg["posting_times"] = DEFAULTS["posting_times"]
    return cfg


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    current = _read_json(paths.SETTINGS_FILE)
    current.update(updates)
    paths.STATE.mkdir(parents=True, exist_ok=True)
    write_json(paths.SETTINGS_FILE, current)
    return load_config()


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
