#!/usr/bin/env python3
"""Posting scheduler.

    python3 scheduler/scheduler.py                 # long-running (local / worker)
    python3 scheduler/scheduler.py --run-once      # one clip then exit (Render Cron)
    python3 scheduler/scheduler.py --run-once --time=evening
    python3 scheduler/scheduler.py --run-once --clip-id demo-1 --force

At each configured slot (default 19:00 and 21:00 Africa/Nairobi) the oldest due
clip in ``/tmp/queue`` is pushed to Instagram and TikTok, moved to
``/tmp/posted`` and confirmed on Telegram. If the queue is empty the bot chat
receives "Queue empty! Add videos via /clip".
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import common, paths, scheduling, telegram  # noqa: E402

NODE_BIN = os.getenv("NODE_BIN", "node")
PYTHON_BIN = os.getenv("PYTHON_BIN", sys.executable or "python3")
SLOT_STATE = paths.STATE / "slots.json"
GRACE = timedelta(minutes=10)


# --------------------------------------------------------------------- queue
def load_queue() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for meta_path in sorted(paths.QUEUE.glob("*.json")):
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                item = json.load(fh)
        except (OSError, ValueError):
            continue
        video = paths.QUEUE / str(item.get("file") or f"{item.get('id')}.mp4")
        if not video.exists():
            video = meta_path.with_suffix(".mp4")
        if not video.exists():
            continue
        item["_video"] = str(video)
        items.append(item)
    def sort_key(item: dict[str, Any]):
        when = scheduling.parse_iso(item.get("scheduled_for"))
        return (
            when.timestamp() if when else float("inf"),
            item.get("created_at") or "",
        )

    items.sort(key=sort_key)
    return items


def _due(item: dict[str, Any], now: datetime, force: bool) -> bool:
    if force:
        return True
    when = scheduling.parse_iso(item.get("scheduled_for"))
    return when is None or when <= now + GRACE


def _load_slots() -> dict[str, Any]:
    try:
        with open(SLOT_STATE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _slot_key(slot: str | None, now: datetime) -> str:
    label = slot or "manual"
    return f"{now.date().isoformat()}:{label}"


def _mark_slot(slot: str | None, clip_id: str) -> None:
    data = _load_slots()
    now = datetime.now(scheduling.zone(common.load_config()))
    data[_slot_key(slot, now)] = {"clip": clip_id, "at": scheduling.to_iso(now)}
    # keep the state file small
    for key in sorted(data)[:-30]:
        data.pop(key, None)
    common.write_json(SLOT_STATE, data)


# ------------------------------------------------------------------ posting
def _result_from_stdout(stdout: str) -> dict[str, Any]:
    for line in reversed((stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return {"ok": False, "error": (stdout or "").strip()[-400:] or "no output"}


def post_instagram(item: dict[str, Any], caption: str) -> dict[str, Any]:
    script = ROOT / "auto-post" / "instagram.js"
    cmd = [
        NODE_BIN, str(script),
        "--file", item["_video"],
        "--id", str(item.get("id", "")),
        "--caption", caption,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(ROOT))
    except Exception as exc:
        return {"ok": False, "error": f"instagram.js failed to start: {exc}"}
    result = _result_from_stdout(proc.stdout)
    if proc.returncode != 0 and result.get("ok"):
        result["ok"] = False
    result.setdefault("platform", "instagram")
    result["exit_code"] = proc.returncode
    if proc.stderr.strip():
        result["stderr"] = proc.stderr.strip()[-400:]
    return result


def post_tiktok(item: dict[str, Any], caption: str) -> dict[str, Any]:
    script = ROOT / "auto-post" / "tiktok_auto.py"
    cmd = [
        PYTHON_BIN, str(script),
        "--file", item["_video"],
        "--caption", caption,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, cwd=str(ROOT))
    except Exception as exc:
        return {"ok": False, "error": f"tiktok_auto.py failed to start: {exc}"}
    result = _result_from_stdout(proc.stdout)
    result.setdefault("platform", "tiktok")
    result["exit_code"] = proc.returncode
    if proc.stderr.strip():
        result["stderr"] = proc.stderr.strip()[-400:]
    return result


def _move_to_posted(item: dict[str, Any]) -> None:
    clip_id = str(item.get("id"))
    paths.POSTED.mkdir(parents=True, exist_ok=True)
    for suffix in (".mp4", ".jpg", ".json"):
        src = paths.QUEUE / f"{clip_id}{suffix}"
        if src.exists():
            shutil.move(str(src), str(paths.POSTED / src.name))


def _notify_with_file(item: dict[str, Any], reason: str) -> None:
    caption = (
        f"⚠️ Auto-posting failed for “{item.get('title') or item.get('id')}”.\n"
        f"{reason[:600]}\n\nDownload the clip below and post it manually."
    )
    video = item.get("_video")
    if video and Path(video).exists():
        if not telegram.send_video(video, caption):
            telegram.send_document(video, caption)
    else:
        telegram.send_message(caption)


def run_slot(
    slot: str | None = None,
    *,
    force: bool = False,
    clip_id: str | None = None,
    notify: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Post at most one clip. Returns a structured result."""
    paths.ensure_dirs()
    cfg = common.load_config()
    now = datetime.now(scheduling.zone(cfg))
    items = load_queue()

    if clip_id:
        match = [i for i in items if str(i.get("id")) == clip_id]
        if not match:
            return {"posted": False, "reason": f"clip {clip_id} is not in the queue"}
        item = match[0]
    else:
        due = [i for i in items if _due(i, now, force)]
        if not due:
            if items:
                nxt = items[0].get("scheduled_for") or "unknown"
                common.info(f"Nothing due yet; next clip scheduled for {nxt}")
                return {"posted": False, "reason": "nothing due", "next": nxt, "queue": len(items)}
            message = (
                "📭 Queue empty! Add videos via /clip\n"
                "Example: /clip https://youtu.be/VIDEO_ID"
            )
            common.warn("Queue empty at posting time")
            if notify and not dry_run:
                telegram.send_message(message)
            return {"posted": False, "reason": "queue empty", "queue": 0}
        item = due[0]

    if dry_run:
        return {"posted": False, "dry_run": True, "clip": item.get("id"), "title": item.get("title")}

    caption = str(item.get("caption") or item.get("title") or "").strip()
    platforms = cfg.get("platforms") or {}
    results: dict[str, Any] = {}

    if platforms.get("instagram", True):
        common.info(f"Posting {item.get('id')} to Instagram")
        results["instagram"] = post_instagram(item, caption)
        common.info(f"Instagram result: {results['instagram'].get('ok')} "
                    f"{results['instagram'].get('error') or results['instagram'].get('reason') or ''}")
    else:
        results["instagram"] = {"ok": False, "skipped": True, "reason": "disabled in config.json"}

    if platforms.get("tiktok", True):
        common.info(f"Posting {item.get('id')} to TikTok")
        results["tiktok"] = post_tiktok(item, caption)
        common.info(f"TikTok result: {results['tiktok'].get('ok')} "
                    f"{results['tiktok'].get('error') or results['tiktok'].get('reason') or ''}")
    else:
        results["tiktok"] = {"ok": False, "skipped": True, "reason": "disabled in config.json"}

    successes = [name for name, res in results.items() if res.get("ok")]
    skipped = [name for name, res in results.items() if res.get("skipped")]
    attempts = int(item.get("attempts") or 0) + (0 if successes else 1)

    if successes:
        item["posted_at"] = scheduling.to_iso(now)
        item["platforms"] = results
        item["attempts"] = attempts
        item["slot"] = slot
        common.write_json(paths.QUEUE / f"{item['id']}.json", item)
        _move_to_posted(item)
        _mark_slot(slot, str(item.get("id")))
        # Seed the dashboard chart with today's posting date. Views stay 0
        # until a real view-count source exists; best effort, never fails a post.
        common.record_analytics_point(now.date().isoformat())
        if notify:
            telegram.send_message(
                f"✅ Posted “{item.get('title') or item.get('id')}”\n"
                f"Platforms: {', '.join(successes)}\n"
                f"Slot: {slot or 'manual'} · {now.strftime('%Y-%m-%d %H:%M %Z')}"
            )
        return {"posted": True, "clip": item.get("id"), "platforms": results, "slot": slot}

    # Nothing succeeded. After three tries the clip is parked in /posted for manual work.
    item["platforms"] = results
    item["attempts"] = attempts
    reason = "; ".join(
        f"{name}: {res.get('reason') or res.get('error') or 'failed'}" for name, res in results.items()
    )
    if attempts >= 3 or (skipped and len(skipped) == len(results)):
        item["manual_required"] = True
        common.write_json(paths.QUEUE / f"{item['id']}.json", item)
        _move_to_posted(item)
        if notify:
            _notify_with_file(item, reason)
        return {"posted": False, "clip": item.get("id"), "platforms": results, "reason": reason,
                "manual_required": True}

    common.write_json(paths.QUEUE / f"{item['id']}.json", item)
    if notify:
        _notify_with_file(item, reason)
    return {"posted": False, "clip": item.get("id"), "platforms": results, "reason": reason,
            "attempts": attempts}


# --------------------------------------------------------------- scheduling
def _job_for_slot(slot: str):
    def job() -> None:
        try:
            result = run_slot(slot)
            common.info(f"Slot {slot} finished: {result}")
        except Exception as exc:  # never kill the scheduler thread
            common.error(f"Slot {slot} crashed: {exc}")
            telegram.send_message(f"❌ Scheduler error in {slot}: {exc}")
    return job


def build_scheduler(cfg: dict[str, Any] | None = None):
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    cfg = cfg or common.load_config()
    tz = scheduling.zone(cfg)
    scheduler = BackgroundScheduler(timezone=tz, job_defaults={"coalesce": True, "max_instances": 1})
    for index, value in enumerate(scheduling.slots(cfg)):
        hour, minute = value.split(":")
        label = "evening" if index == 0 else "night" if index == 1 else f"slot{index + 1}"
        scheduler.add_job(
            _job_for_slot(label),
            CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
            id=f"post-{label}",
            replace_existing=True,
            misfire_grace_time=4 * 3600,
        )
    return scheduler


def catch_up() -> None:
    """Post one overdue clip after a restart (free instances spin down)."""
    try:
        cfg = common.load_config()
        now = datetime.now(scheduling.zone(cfg))
        due = [item for item in load_queue() if _due(item, now, False)]
        if not due:
            return
        if _load_slots().get(_slot_key("catch-up", now)):
            return
        common.info(f"Catch-up: {len(due)} overdue clip(s) found after restart")
        run_slot("catch-up")
    except Exception as exc:
        common.error(f"Catch-up failed: {exc}")


def start_background():
    """Start the scheduler in a daemon thread (used by the Telegram bot)."""
    scheduler = build_scheduler()
    scheduler.start()
    common.info(
        "Internal scheduler started: " + ", ".join(scheduling.slots(common.load_config()))
    )
    # Give Next.js + the bot a moment to settle, then recover a missed slot.
    timer = threading.Timer(20.0, catch_up)
    timer.daemon = True
    timer.start()
    return scheduler


def serve() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    cfg = common.load_config()
    tz = scheduling.zone(cfg)
    scheduler = BlockingScheduler(timezone=tz, job_defaults={"coalesce": True, "max_instances": 1})
    for index, value in enumerate(scheduling.slots(cfg)):
        hour, minute = value.split(":")
        label = "evening" if index == 0 else "night" if index == 1 else f"slot{index + 1}"
        scheduler.add_job(
            _job_for_slot(label),
            CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
            id=f"post-{label}",
            replace_existing=True,
            misfire_grace_time=4 * 3600,
        )
        common.info(f"Scheduled {label} post at {value} {getattr(tz, 'key', tz)}")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        common.info("Scheduler stopped")


def main() -> int:
    parser = argparse.ArgumentParser(description="Post queued shorts to Instagram and TikTok")
    parser.add_argument("--run-once", action="store_true", help="Post one clip then exit (Render Cron)")
    parser.add_argument("--time", choices=["evening", "night", "manual"], help="Slot label being run")
    parser.add_argument("--clip-id", help="Post a specific queued clip")
    parser.add_argument("--force", action="store_true", help="Ignore scheduled_for when choosing a clip")
    parser.add_argument("--dry-run", action="store_true", help="Show what would post without posting")
    parser.add_argument("--quiet", action="store_true", help="Do not send Telegram notifications")
    parser.add_argument("--list", action="store_true", help="Print the queue as JSON and exit")
    args = parser.parse_args()

    paths.ensure_dirs()
    if args.list:
        items = load_queue()
        print(json.dumps(items, indent=2, default=str))
        return 0

    if not args.run_once:
        serve()
        return 0

    slot = args.time or "manual"
    cfg = common.load_config()
    now = datetime.now(scheduling.zone(cfg))
    if slot in ("evening", "night") and not args.force and not args.clip_id:
        guard = _load_slots().get(_slot_key(slot, now))
        if guard:
            common.info(f"Slot {slot} already posted {guard.get('clip')} today - exiting")
            print(json.dumps({"posted": False, "reason": "slot already handled",
                              "clip": guard.get("clip")}))
            return 0

    result = run_slot(
        slot,
        force=args.force,
        clip_id=args.clip_id,
        notify=not args.quiet,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, default=str))
    if result.get("posted"):
        return 0
    if result.get("reason") in ("queue empty", "nothing due") or result.get("dry_run"):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
