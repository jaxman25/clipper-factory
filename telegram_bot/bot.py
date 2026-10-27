#!/usr/bin/env python3
"""Telegram control bot for Clipper Factory.

Commands
--------
/start     welcome + chat id
/clip URL  generate shorts from a YouTube link (raw links work too)
/queue     list queued clips and pin the list
/postnow   post the oldest queued clip immediately
/settings  show slots, tokens and queue health
/cancel    stop the running generation job
/clearlogs wipe the activity log tail and the job log files

On Render the bot is started by ``npm run start:render`` alongside Next.js. Set
ACF_ENABLE_SCHEDULER=1 to run the 19:00/21:00 EAT poster inside this process
(the free-plan alternative to Render Cron Jobs).
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Python 3.14 compatibility: asyncio.get_event_loop() no longer creates a loop
# implicitly and raises RuntimeError when none is set, which breaks third-party
# imports that still call it at startup. Create and install one up front.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram import BotCommand, Update  # noqa: E402
from telegram import __version__ as PTB_VERSION  # noqa: E402
from telegram.constants import ParseMode  # noqa: E402
from telegram.error import TelegramError  # noqa: E402
from telegram.ext import (  # noqa: E402
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from backend import common, paths, scheduling  # noqa: E402

PYTHON_BIN = os.getenv("PYTHON_BIN", sys.executable or "python3")
URL_RE = re.compile(r"https?://\S+")
RUNNING: dict[int, dict[str, Any]] = {}
TG_LIMIT = 3800


# ------------------------------------------------------------------ helpers
def job_file(job_id: str) -> Path:
    return paths.JOBS / f"{job_id}.json"


def read_job(job_id: str) -> dict[str, Any]:
    try:
        with open(job_file(job_id), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def queue_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for meta in sorted(paths.QUEUE.glob("*.json")):
        try:
            with open(meta, "r", encoding="utf-8") as fh:
                item = json.load(fh)
        except (OSError, ValueError):
            continue
        if (paths.QUEUE / str(item.get("file") or f"{item.get('id')}.mp4")).exists():
            items.append(item)

    def sort_key(item: dict[str, Any]):
        when = scheduling.parse_iso(item.get("scheduled_for"))
        return (when.timestamp() if when else float("inf"), item.get("created_at") or "")

    items.sort(key=sort_key)
    return items


def queue_text(items: list[dict[str, Any]]) -> str:
    if not items:
        return "📭 Queue empty! Add videos via /clip"
    lines = [f"📋 Queue ({len(items)} clip{'s' if len(items) != 1 else ''})"]
    for index, item in enumerate(items[:20], start=1):
        when = item.get("scheduled_for") or "unscheduled"
        try:
            when = datetime.fromisoformat(when).strftime("%a %d %b %H:%M")
        except (ValueError, TypeError):
            pass
        score = item.get("viral_score")
        score_txt = f" · 🔥{float(score):.0f}" if isinstance(score, (int, float)) else ""
        title = str(item.get("title") or item.get("id"))[:60]
        lines.append(f"{index:02d}. {when}{score_txt}\n    {title}")
    if len(items) > 20:
        lines.append(f"…and {len(items) - 20} more on the dashboard.")
    return "\n".join(lines)


def load_scheduler_module():
    """Load scheduler/scheduler.py without clashing with backend.scheduling."""
    path = ROOT / "scheduler" / "scheduler.py"
    spec = importlib.util.spec_from_file_location("acf_scheduler", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["acf_scheduler"] = module
    if spec and spec.loader:
        spec.loader.exec_module(module)
    return module


def youtube_url(text: str) -> str | None:
    match = URL_RE.search(text or "")
    return match.group(0).rstrip(").,") if match else None


def chat_target(update: Update) -> str:
    return str(update.effective_chat.id) if update.effective_chat else ""


async def reply(update: Update, text: str, markdown: bool = False) -> None:
    if not update.message:
        return
    try:
        await update.message.reply_text(
            text[:TG_LIMIT],
            parse_mode=ParseMode.MARKDOWN if markdown else None,
            disable_web_page_preview=True,
        )
    except TelegramError as exc:
        common.warn(f"Telegram reply failed: {exc}")


# --------------------------------------------------------------- generation
async def start_generation(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else 0
    if chat_id in RUNNING:
        await reply(update, "⏳ A clip job is already running for you. Use /cancel to stop it.")
        return

    cfg = common.load_config()
    num_shorts = int(context.args[-1]) if context.args and str(context.args[-1]).isdigit() else int(
        cfg.get("shorts_per_video", 10)
    )
    job_id = paths.safe_id(f"tg-{chat_id}-{int(time.time())}")
    status = await update.message.reply_text(
        f"🎬 Starting job `{job_id}` for {num_shorts} shorts...\n"
        "Download → transcribe → score → render. This takes 5-15 minutes.",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )

    paths.ensure_dirs()
    log_path = paths.STATE / f"{job_id}.log"
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    with open(log_path, "ab") as log_fh:
        proc = await asyncio.create_subprocess_exec(
            PYTHON_BIN, str(ROOT / "backend" / "main.py"),
            "--url", url,
            "--job-id", job_id,
            "--num-shorts", str(num_shorts),
            "--no-notify",
            cwd=str(ROOT),
            env=env,
            stdout=log_fh,
            stderr=log_fh,
        )

    RUNNING[chat_id] = {"job_id": job_id, "proc": proc, "started": time.time()}
    asyncio.create_task(
        watch_generation(context.application, chat_id, job_id, proc, status.message_id, num_shorts)
    )


async def watch_generation(app, chat_id: int, job_id: str, proc, message_id: int,
                           num_shorts: int) -> None:
    last_text = ""
    last_edit = 0.0
    while proc.returncode is None:
        await asyncio.sleep(5)
        data = read_job(job_id)
        progress = int(data.get("progress") or 0)
        text = (
            f"🎬 `{job_id}`\n{data.get('message') or 'Working...'}\n"
            f"{progress}% · stage: {data.get('stage') or 'starting'}"
        )
        now = time.time()
        if text != last_text and (now - last_edit > 12 or progress >= 100):
            try:
                await app.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=text,
                    parse_mode=ParseMode.MARKDOWN,
                )
                last_text, last_edit = text, now
            except TelegramError:
                pass

    data = read_job(job_id)
    RUNNING.pop(chat_id, None)
    if data.get("status") == "done":
        clips = data.get("clips") or []
        summary = (
            f"✅ {len(clips)} shorts ready!\n"
            f"Source: {str(data.get('source_url') or '')[:90]}\n"
            f"Next post: {clips[0].get('scheduled_for') if clips else '—'}\n"
            "Open the dashboard to preview, edit captions, reschedule or post now."
        )
        try:
            await app.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=summary)
        except TelegramError:
            await app.bot.send_message(chat_id, summary)
        if clips:
            video = paths.QUEUE / str(clips[0].get("file") or "")
            if video.exists():
                try:
                    with open(video, "rb") as fh:
                        await app.bot.send_video(
                            chat_id=chat_id, video=fh,
                            caption=f"Preview · {clips[0].get('title', '')}\n🔥 {clips[0].get('viral_score')}",
                            supports_streaming=True,
                        )
                except TelegramError as exc:
                    common.warn(f"Preview upload failed: {exc}")
        return
    if data.get("status") == "cancelled":
        message = "🛑 Job cancelled."
    else:
        message = f"❌ Job failed: {data.get('message') or 'unknown error'}"
    try:
        await app.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=message)
    except TelegramError:
        await app.bot.send_message(chat_id, message)


# ----------------------------------------------------------------- commands
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = chat_target(update)
    text = (
        "🌍 *Clipper Factory*\n"
        "Paste a YouTube link and I turn the best story beats into 10 vertical shorts, "
        "then post two a day at 19:00 and 21:00 EAT.\n\n"
        "*Commands*\n"
        "/clip <youtube url> — generate shorts (or just paste a link)\n"
        "/queue — show and pin the queue\n"
        "/postnow [clip-id] — publish the oldest clip now\n"
        "/settings — slots, tokens and health\n"
        "/cancel — stop the running job\n"
        "/clearlogs — wipe the activity log and job logs\n\n"
        f"Your chat id: `{chat_id}`\n"
        "Set TELEGRAM_CHAT_ID to this value so scheduled posts reach you."
    )
    await reply(update, text, markdown=True)


async def cmd_clip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args) if context.args else ""
    url = youtube_url(text)
    if not url:
        await reply(update, "Usage: /clip https://youtu.be/VIDEO_ID [number_of_shorts]")
        return
    await start_generation(update, context, url)


async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = queue_items()
    message = queue_text(items)
    if not update.message:
        return
    try:
        sent = await update.message.reply_text(message, disable_web_page_preview=True)
        await context.bot.pin_chat_message(
            update.effective_chat.id, sent.message_id, disable_notification=True
        )
    except TelegramError as exc:
        common.info(f"Queue message could not be pinned: {exc}")


async def cmd_postnow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clip_id = context.args[0] if context.args else None
    await reply(update, "📤 Posting now..." + (f" ({clip_id})" if clip_id else ""))
    cmd = [PYTHON_BIN, str(ROOT / "scheduler" / "scheduler.py"),
           "--run-once", "--force", "--quiet", "--time", "manual"]
    if clip_id:
        cmd += ["--clip-id", clip_id]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(ROOT),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=900)
        output = (stdout or b"").decode("utf-8", "replace").strip()
        result = {}
        for line in reversed(output.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    result = json.loads(line)
                    break
                except ValueError:
                    continue
        if result.get("posted"):
            platforms = ", ".join(result.get("platforms", {}).keys()) or "platform"
            await reply(update, f"✅ Posted {result.get('clip')} to {platforms}")
        else:
            reason = result.get("reason") or (stderr or b"").decode("utf-8", "replace")[-400:]
            await reply(update, f"⚠️ Nothing posted: {reason or 'unknown error'}")
    except asyncio.TimeoutError:
        await reply(update, "⌛ Posting timed out after 15 minutes. Check /settings → logs.")
    except Exception as exc:
        await reply(update, f"❌ /postnow failed: {exc}")


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = common.load_config()
    items = queue_items()
    tokens = {
        "Telegram bot": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "Telegram chat": bool(os.getenv("TELEGRAM_CHAT_ID")),
        "Pixabay": bool(os.getenv("PIXABAY_API_KEY")),
        "Instagram": bool(os.getenv("IG_USER_ID") and os.getenv("IG_ACCESS_TOKEN")),
        "TikTok session": bool(
            os.getenv("TIKTOK_AUTH_B64")
            or (paths.STATE / "tiktok_auth.json").exists()
            or (ROOT / "auth.json").exists()
        ),
    }
    token_lines = "\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in tokens.items())
    internal = os.getenv("ACF_ENABLE_SCHEDULER", "0") in ("1", "true", "yes")
    next_slot = scheduling.next_slot(cfg)
    text = (
        "⚙️ *Settings*\n"
        f"Time zone: `{cfg.get('timezone')}`\n"
        f"Slots: {', '.join(scheduling.slots(cfg))}\n"
        f"Next slot: {next_slot.strftime('%a %d %b %H:%M')}\n"
        f"Shorts per video: {cfg.get('shorts_per_video')}\n"
        f"Platforms: Instagram={bool((cfg.get('platforms') or {}).get('instagram', True))}, "
        f"TikTok={bool((cfg.get('platforms') or {}).get('tiktok', True))}\n"
        f"In-process scheduler: {'on' if internal else 'off'}\n"
        f"Queue: {len(items)} clip(s)\n\n"
        f"*Integrations*\n{token_lines}\n\n"
        "Change times and tokens from the web dashboard → Settings."
    )
    await reply(update, text, markdown=True)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else 0
    running = RUNNING.get(chat_id)
    if not running:
        await reply(update, "Nothing is running.")
        return
    proc = running.get("proc")
    job_id = running.get("job_id", "")
    # Mark the document cancelled FIRST: the worker re-checks this state on
    # every write, so a live worker can never overwrite the terminal state
    # with 'running'/'done' while it winds down. Repeats stay idempotent.
    data = read_job(job_id)
    if data and data.get("status") != "cancelled":
        data["status"] = "cancelled"
        data["message"] = "Cancelled by user"
        common.write_json(job_file(job_id), data)
    if proc and proc.returncode is None:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
    RUNNING.pop(chat_id, None)
    # Drop the lock only when it belongs to this job - cancelling one job
    # must never unlock a different, still-running generation.
    if paths.LOCK_FILE.exists() and not common.remove_lock_if_owned(job_id):
        common.warn(f"generate.lock not owned by {job_id}; left untouched")
    await reply(update, "🛑 Generation cancelled.")


async def cmd_clearlogs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if "yes" not in [arg.lower() for arg in context.args]:
        await reply(
            update,
            "🧹 This empties the dashboard's activity log and deletes every job "
            "log file. Reply /clearlogs yes to confirm.",
        )
        return
    result = common.clear_logs()
    await reply(
        update,
        f"🧹 Logs cleared — activity log emptied, "
        f"{result['job_logs']} job log file(s) deleted.",
    )


async def on_plain_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = youtube_url(update.message.text if update.message else "")
    if url:
        await start_generation(update, context, url)
    else:
        await reply(update, "Send a YouTube link to make shorts, or use /queue to see what is ready.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    common.error(f"Telegram handler error: {context.error}")
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                update.effective_chat.id, f"⚠️ Error: {context.error}"
            )
        except TelegramError:
            pass


def startup_chat_id() -> str:
    """TELEGRAM_CHAT_ID from the env (or dashboard settings), trimmed.

    Values saved in the dashboard sometimes arrive quoted or padded, and a
    malformed id makes Telegram answer 400 "chat not found".
    """
    raw = os.getenv("TELEGRAM_CHAT_ID", "")
    return raw.strip().strip('"').strip("'")


def chat_id_valid(chat: str) -> bool:
    """True for a numeric id (optionally negative) or a @username."""
    return bool(re.fullmatch(r"-?\d+|@[A-Za-z][A-Za-z0-9_]{4,}", chat))


async def post_init(app: Application) -> None:
    try:
        await app.bot.set_my_commands([
            BotCommand("clip", "Generate shorts from a YouTube URL"),
            BotCommand("queue", "Show the posting queue"),
            BotCommand("postnow", "Post the oldest clip now"),
            BotCommand("settings", "Show slots and integrations"),
            BotCommand("cancel", "Cancel the running job"),
            BotCommand("clearlogs", "Wipe activity and job logs"),
            BotCommand("start", "Welcome and chat id"),
        ])
    except TelegramError as exc:
        common.warn(f"Could not register commands: {exc}")
    if queue_items():
        return
    chat = startup_chat_id()
    if not chat:
        common.warn("Startup notice skipped: TELEGRAM_CHAT_ID is missing")
        return
    if not chat_id_valid(chat):
        common.warn(
            f"Startup notice skipped: TELEGRAM_CHAT_ID {chat!r} is not a chat id "
            "(use the id @start returns, digits only)"
        )
        return
    try:
        # application.bot in post_init - never the backend.telegram helper,
        # whose send_message is sync and returns bool (not awaitable).
        await app.bot.send_message(
            chat_id=chat, text="📭 Queue empty! Add videos via /clip"
        )
    except TelegramError as exc:
        common.warn(f"Could not send startup notice: {exc}")


MIN_PTB = (21, 0)


def library_version_error(installed: str = PTB_VERSION) -> str | None:
    """Return a hint when python-telegram-bot is older than the bot needs.

    PTB 21 rebuilt ``Updater`` with ``__slots__``; running this bot on a 20.x
    install dies deep inside ``Application.build()`` with an opaque
    ``AttributeError: 'Updater' object has no attribute
    '_Updater__polling_cleanup_cb'``. Catching it up front turns that traceback
    into one actionable line.
    """
    parts: list[int] = []
    for chunk in installed.split(".")[:2]:
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 2:
        parts.append(0)
    if tuple(parts) >= MIN_PTB:
        return None
    return (
        f"python-telegram-bot {installed} is too old for this bot: the updater API "
        f"changed in {MIN_PTB[0]}.{MIN_PTB[1]}. Install the pinned release with\n"
        f"    pip install -r requirements.txt"
    )


def warn_if_legacy_python() -> None:
    """Startup check: the event-loop patch at the top of this file targets 3.14.

    On Python < 3.14 ``asyncio.get_event_loop()`` still auto-creates a loop
    (deprecated), so the patched path never triggers there - flag the version so
    an event-loop problem on an older interpreter is not mistaken for it.
    """
    if sys.version_info < (3, 14):
        common.warn(
            f"Python {sys.version_info[0]}.{sys.version_info[1]} is below 3.14: "
            "the event-loop compatibility patch at the top of this file targets "
            "Python 3.14, where asyncio.get_event_loop() stopped creating a "
            "loop implicitly."
        )


def main() -> int:
    warn_if_legacy_python()
    version_problem = library_version_error()
    if version_problem:
        print(version_problem, file=sys.stderr)
        return 2

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set. Add it to .env (see README-RENDER.md).", file=sys.stderr)
        return 1
    paths.ensure_dirs()
    common.load_config()  # pulls dashboard-saved tokens into os.environ

    if os.getenv("ACF_ENABLE_SCHEDULER", "0").lower() in ("1", "true", "yes"):
        try:
            scheduler = load_scheduler_module()
            scheduler.start_background()
        except Exception as exc:
            common.error(f"Could not start internal scheduler: {exc}")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("clip", cmd_clip))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("postnow", cmd_postnow))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("clearlogs", cmd_clearlogs))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_plain_text))
    app.add_error_handler(on_error)

    common.info("Telegram bot polling started")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
