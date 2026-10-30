"""Minimal Telegram Bot API client used by the generator and scheduler.

The interactive bot uses python-telegram-bot; this helper exists so the worker
scripts can notify without importing the full framework.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from . import common
except ImportError:  # pragma: no cover
    import common  # type: ignore

API_BASE = "https://api.telegram.org/bot{token}/{method}"
MAX_TEXT = 3800


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def chat_id(explicit: str | None = None) -> str:
    return (explicit or os.getenv("TELEGRAM_CHAT_ID", "")).strip()


def enabled() -> bool:
    return bool(_token() and chat_id())


def _post(method: str, data: dict, files: dict | None = None, timeout: int = 45) -> bool:
    token = _token()
    if not token:
        common.warn(f"Telegram {method} skipped: TELEGRAM_BOT_TOKEN missing")
        return False
    try:
        import requests
    except ImportError:
        common.warn("requests missing - cannot reach Telegram")
        return False
    try:
        response = requests.post(
            API_BASE.format(token=token, method=method),
            data=data,
            files=files,
            timeout=timeout,
        )
        if response.status_code >= 400:
            common.warn(f"Telegram {method} failed: {response.status_code} {response.text[:200]}")
            return False
        return True
    except Exception as exc:
        common.warn(f"Telegram {method} error: {exc}")
        return False


def send_message(text: str, chat: str | None = None, parse_mode: str | None = None) -> bool:
    target = chat_id(chat)
    if not target:
        common.warn("Telegram message skipped: TELEGRAM_CHAT_ID missing")
        return False
    data = {"chat_id": target, "text": text[:MAX_TEXT], "disable_web_page_preview": "true"}
    if parse_mode:
        data["parse_mode"] = parse_mode
    return _post("sendMessage", data)


def send_video(path: Path | str, caption: str = "", chat: str | None = None) -> bool:
    target = chat_id(chat)
    video = Path(path)
    if not target or not video.exists():
        return False
    if video.stat().st_size > 49 * 1024 * 1024:
        return send_document(video, caption, chat)
    with open(video, "rb") as fh:
        ok = _post(
            "sendVideo",
            {"chat_id": target, "caption": caption[:900], "supports_streaming": "true"},
            files={"video": (video.name, fh, "video/mp4")},
            timeout=180,
        )
    return ok


def send_document(path: Path | str, caption: str = "", chat: str | None = None) -> bool:
    target = chat_id(chat)
    doc = Path(path)
    if not target or not doc.exists():
        return False
    with open(doc, "rb") as fh:
        return _post(
            "sendDocument",
            {"chat_id": target, "caption": caption[:900]},
            files={"document": (doc.name, fh, "application/octet-stream")},
            timeout=300,
        )


