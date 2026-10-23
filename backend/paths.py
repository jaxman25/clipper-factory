"""Filesystem layout shared by every Python entry point.

Everything mutable lives under ``ACF_DATA_ROOT`` (``/tmp`` by default) because
Render's free tier has no persistent disk. On a local machine you can point the
same variable at the project root to keep the classic ``downloads/``,
``exports/``, ``queue/`` and ``posted/`` folders.

Assets are read-only and always resolve to the project's ``assets/`` folder.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.getenv("ACF_DATA_ROOT", "/tmp")).expanduser()

DOWNLOADS = DATA_ROOT / "downloads"
EXPORTS = DATA_ROOT / "exports"
QUEUE = DATA_ROOT / "queue"
POSTED = DATA_ROOT / "posted"
STATE = DATA_ROOT / "state"
JOBS = STATE / "jobs"
LOGS = STATE / "logs"

ASSETS = Path(os.getenv("ACF_ASSETS_DIR", str(ROOT / "assets")))
DRUM_LOOP = ASSETS / "drum_loop.wav"
NIGHT_AMBIENCE = ASSETS / "night_ambience.wav"
GRADIENT = ASSETS / "gradient.png"
BROLL_DIR = ASSETS / "broll"
WATERMARK = ASSETS / "logos" / "watermark-100.png"

CONFIG_FILE = ROOT / "config.json"
SETTINGS_FILE = STATE / "settings.json"
SCHEDULE_FILE = STATE / "schedule.json"
LOG_FILE = STATE / "logs.jsonl"
LOCK_FILE = STATE / "generate.lock"

META_NAME = "metadata.json"


def ensure_dirs() -> None:
    for path in (DOWNLOADS, EXPORTS, QUEUE, POSTED, JOBS, LOGS, ASSETS, BROLL_DIR):
        path.mkdir(parents=True, exist_ok=True)


def safe_id(value: str, fallback: str = "clip") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-").lower()
    return cleaned[:60] or fallback


def rel(path: Path) -> str:
    return str(path).replace("\\", "/")
