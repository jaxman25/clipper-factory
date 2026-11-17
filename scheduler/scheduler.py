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
# Slot records are written before publishing and updated per platform:
#   pending -> posted | partial | failed
# A version-2 claim writes `publishing_started` immediately before the first
# platform call, so `pending` without it proves no platform was ever contacted.
# Only such a claim, from an earlier day, may become 'abandoned' (retryable).
# pending/posted/partial block any further handling of that slot; only a
# recorded failure may be retried and an abandoned claim never blocks.
#   pending -> abandoned   (version 2, previous day, no marker, no results)
BLOCKING_SLOT_STATUSES = {"pending", "posted", "partial"}
TERMINAL_SLOT_STATUSES = {"posted", "partial", "failed", "abandoned"}
CLAIM_VERSION = 2
LOCKED_SLOTS = {"evening", "night", "catch-up"}


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


def _update_slot(key: str, now: datetime, **fields: Any) -> dict[str, Any]:
    """Atomically merge fields into one slot record and return it.

    The record is written *before* publishing (status 'pending') and updated
    after each platform, so a crash leaves evidence instead of an unreported
    post. States: pending, posted, partial, failed, abandoned. Pruning only
    ever drops terminal records: a pending or uncertain claim is evidence and
    must never disappear silently.
    """
    data = _load_slots()
    record = data.get(key)
    if not isinstance(record, dict):
        record = {}
    record.update(fields)
    record["updated_at"] = scheduling.to_iso(now)
    data[key] = record
    # Keep the state file small without ever forgetting an unresolved claim:
    # only terminal records are pruned, and never the one just written.
    if len(data) > 60:
        for old in sorted(data):
            if len(data) <= 60:
                break
            if old == key:
                continue
            record_old = data.get(old)
            if (
                isinstance(record_old, dict)
                and record_old.get("status") in TERMINAL_SLOT_STATUSES
            ):
                data.pop(old, None)
    common.write_json(SLOT_STATE, data)
    return record


def _claimed_slot_for_clip(clip_id: Any) -> tuple[str | None, dict[str, Any]]:
    """Find a blocking claim (pending/posted/partial) for a clip, if any."""
    for key, record in _load_slots().items():
        if not isinstance(record, dict):
            continue
        if str(record.get("clip")) != str(clip_id):
            continue
        if record.get("status") in BLOCKING_SLOT_STATUSES or "status" not in record:
            return key, record
    return None, {}


def _recover_abandoned_claims(now: datetime) -> list[str]:
    """Retire slot claims that provably never reached a platform.

    A version-2 claim writes ``publishing_started`` before the first platform
    call, so a pending claim without that marker (and without any platform
    result) cannot have published anything. Only such a claim, from an earlier
    day, is safe to mark 'abandoned' and let the clip publish later. Legacy
    claims and interrupted attempts stay pending and keep blocking.
    """
    data = _load_slots()
    today = now.date().isoformat()
    recovered: list[str] = []
    for key, record in data.items():
        if not isinstance(record, dict) or record.get("status") != "pending":
            continue
        if record.get("publishing_started") or record.get("platforms"):
            continue
        try:
            version = int(record.get("claim_version") or 0)
        except (TypeError, ValueError):
            version = 0
        if version < CLAIM_VERSION:
            continue
        # Same-day claims may still be in flight in another process.
        if key.split(":", 1)[0] >= today:
            continue
        record["status"] = "abandoned"
        record["abandoned_at"] = scheduling.to_iso(now)
        record["error"] = "claim abandoned before any platform call"
        recovered.append(key)
    if recovered:
        common.write_json(SLOT_STATE, data)
        common.warn(
            f"Recovered {len(recovered)} abandoned slot claim(s): "
            f"{', '.join(recovered)}"
        )
    return recovered


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
    now: datetime | None = None,
) -> dict[str, Any]:
    """Post at most one clip. Returns a structured result.

    ``slot`` names the schedule slot ('evening', 'night', 'catch-up'); a slot
    that already carries a blocking record is never handled twice. ``now`` is
    injectable so tests can pin the clock.
    """
    paths.ensure_dirs()
    cfg = common.load_config()
    now = now or datetime.now(scheduling.zone(cfg))
    # Retire claims that provably never contacted a platform. Read-only in
    # dry-run mode: a preview must not change scheduling state.
    if not dry_run:
        _recover_abandoned_claims(now)
    key = _slot_key(slot, now) if slot else None
    items = load_queue()

    # Durable, pre-publish slot claim. Written before the first platform call,
    # so a crash between publishing and recording leaves 'pending' behind and
    # the slot (or clip) is not published again.
    if key and slot in LOCKED_SLOTS and not clip_id:
        existing = _load_slots().get(key)
        # A record written before statuses existed still means "handled today".
        if isinstance(existing, dict) and (
            existing.get("status") in BLOCKING_SLOT_STATUSES
            or "status" not in existing
        ):
            common.info(
                f"Slot {slot} already {existing.get('status')} "
                f"({existing.get('clip')}) - skipping"
            )
            return {
                "posted": False,
                "reason": f"slot already {existing.get('status')}",
                "clip": existing.get("clip"),
                "status": existing.get("status"),
            }

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

    # A clip already claimed by any slot must never be published again, even
    # from the same key: the crash may have happened after the platform accepted
    # the post but before the queue file was moved. (Abandoned claims are not
    # blocking, so genuinely pre-publish crashes still recover.)
    claimed_key, claimed = _claimed_slot_for_clip(item.get("id"))
    if claimed_key:
        common.warn(
            f"Clip {item.get('id')} already {claimed.get('status')} in "
            f"{claimed_key} - not publishing again"
        )
        return {
            "posted": False,
            "reason": f"clip already {claimed.get('status')} in {claimed_key}",
            "clip": item.get("id"),
            "status": claimed.get("status"),
        }

    caption = str(item.get("caption") or item.get("title") or "").strip()
    platforms = cfg.get("platforms") or {}
    results: dict[str, Any] = {}

    # Claim the slot before any platform is contacted. Two durable writes, in
    # order: the claim, then the publishing marker that separates an abandoned
    # claim from an interrupted attempt. If either write fails, publish nothing.
    if key:
        try:
            _update_slot(
                key,
                now,
                slot=slot,
                clip=item.get("id"),
                status="pending",
                claim_version=CLAIM_VERSION,
                claimed_at=scheduling.to_iso(now),
                platforms={},
                error=None,
            )
            _update_slot(key, now, publishing_started=scheduling.to_iso(now))
        except Exception as exc:
            common.error(
                f"Could not persist slot claim for {item.get('id')}: {exc}"
            )
            return {
                "posted": False,
                "reason": f"could not persist slot claim: {exc}",
                "clip": item.get("id"),
                "slot": slot,
            }

    if platforms.get("instagram", True):
        common.info(f"Posting {item.get('id')} to Instagram")
        results["instagram"] = post_instagram(item, caption)
        common.info(f"Instagram result: {results['instagram'].get('ok')} "
                    f"{results['instagram'].get('error') or results['instagram'].get('reason') or ''}")
        if key:
            # Per-platform durability: a crash from here on knows Instagram's
            # outcome instead of guessing.
            _update_slot(key, now, platforms=dict(results))
    else:
        results["instagram"] = {"ok": False, "skipped": True, "reason": "disabled in config.json"}

    if platforms.get("tiktok", True):
        common.info(f"Posting {item.get('id')} to TikTok")
        results["tiktok"] = post_tiktok(item, caption)
        common.info(f"TikTok result: {results['tiktok'].get('ok')} "
                    f"{results['tiktok'].get('error') or results['tiktok'].get('reason') or ''}")
        if key:
            _update_slot(key, now, platforms=dict(results))
    else:
        results["tiktok"] = {"ok": False, "skipped": True, "reason": "disabled in config.json"}

    successes = [name for name, res in results.items() if res.get("ok")]
    skipped = [name for name, res in results.items() if res.get("skipped")]
    failed = [
        name
        for name, res in results.items()
        if not res.get("ok") and not res.get("skipped")
    ]
    attempts = int(item.get("attempts") or 0) + (0 if successes else 1)

    if successes:
        item["posted_at"] = scheduling.to_iso(now)
        item["platforms"] = results
        item["attempts"] = attempts
        item["slot"] = slot
        if failed:
            # Per-platform truth: Instagram succeeding while TikTok failed is
            # 'partial', never a full success, and the clip is not republished
            # automatically (that would duplicate the successful platform).
            item["partial"] = True
            item["failed_platforms"] = failed
        common.write_json(paths.QUEUE / f"{item['id']}.json", item)
        status = "partial" if failed else "posted"
        if key:
            _update_slot(
                key,
                now,
                status=status,
                platforms=dict(results),
                posted_at=item["posted_at"],
                failed_platforms=failed,
                error=None,
            )
        _move_to_posted(item)
        # Seed the dashboard chart with today's posting date. Views stay 0
        # until a real view-count source exists; best effort, never fails a post.
        common.record_analytics_point(now.date().isoformat())
        if notify:
            partial_note = (
                f"\nPartial: {', '.join(failed)} failed - post manually if needed."
                if failed
                else ""
            )
            telegram.send_message(
                f"✅ Posted “{item.get('title') or item.get('id')}”\n"
                f"Platforms: {', '.join(successes)}\n"
                f"Slot: {slot or 'manual'} · {now.strftime('%Y-%m-%d %H:%M %Z')}"
                f"{partial_note}"
            )
        return {
            "posted": True,
            "clip": item.get("id"),
            "platforms": results,
            "slot": slot,
            "status": status,
        }

    # Nothing succeeded. After three tries the clip is parked in /posted for manual work.
    item["platforms"] = results
    item["attempts"] = attempts
    reason = "; ".join(
        f"{name}: {res.get('reason') or res.get('error') or 'failed'}" for name, res in results.items()
    )
    if key:
        # A recorded failure is retryable (unlike pending/posted/partial).
        _update_slot(
            key,
            now,
            status="failed",
            platforms=dict(results),
            attempts=attempts,
            error=reason,
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


def catch_up(now: datetime | None = None) -> None:
    """Post one overdue clip after a restart (free instances spin down)."""
    try:
        cfg = common.load_config()
        now = now or datetime.now(scheduling.zone(cfg))
        due = [item for item in load_queue() if _due(item, now, False)]
        if not due:
            return
        # One catch-up per calendar day, including a pending claim: a crash
        # mid-publish must not be replayed as a duplicate post.
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
        if isinstance(guard, dict) and (
            guard.get("status") in BLOCKING_SLOT_STATUSES
            or "status" not in guard
        ):
            common.info(
                f"Slot {slot} already {guard.get('status')} "
                f"({guard.get('clip')}) today - exiting"
            )
            print(json.dumps({"posted": False, "reason": "slot already handled",
                              "clip": guard.get("clip"),
                              "status": guard.get("status")}))
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
