"""Posting-slot maths shared by the generator, scheduler and bot."""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

DEFAULT_SLOTS = ["19:00", "21:00"]
FALLBACK_OFFSETS = {"africa/nairobi": 3}
# Anti-flag scheduling: slots land somewhere in a +/-2h window so posting
# times never line up across accounts or look bot-driven.
JITTER_SECONDS = 2 * 60 * 60
# Queue scheduling is exact by default: a configured 19:00/21:00 slot stays
# 19:00/21:00 in the configured zone. Anti-flag spacing is opt-in.
DEFAULT_SCHEDULE_JITTER_SECONDS = 0


def schedule_jitter_seconds(cfg: dict[str, Any] | None = None) -> int:
    """Configured queue-spacing jitter in seconds (0 = exact configured slot)."""
    raw = (cfg or {}).get(
        "schedule_jitter_seconds", DEFAULT_SCHEDULE_JITTER_SECONDS
    )
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return DEFAULT_SCHEDULE_JITTER_SECONDS
    return max(0, min(value, JITTER_SECONDS))


def queue_slot(dt: datetime, cfg: dict[str, Any] | None = None) -> datetime:
    """Posting time a queued clip carries.

    Exact slot by default, so a clip scheduled for 19:00 EAT is due at 19:00
    EAT - not somewhere in a +/-2 h window. ``jitter()`` is kept unchanged for
    callers that explicitly want spacing; only ``schedule_jitter_seconds`` > 0
    opts a queue into it.
    """
    seconds = schedule_jitter_seconds(cfg)
    if seconds <= 0:
        return dt
    return jitter(dt, seconds)


def zone(cfg: dict[str, Any] | None = None) -> tzinfo:
    name = (cfg or {}).get("timezone") or "Africa/Nairobi"
    try:
        return ZoneInfo(name)
    except Exception:
        # Windows without the tzdata wheel / slim containers still work.
        offset = FALLBACK_OFFSETS.get(name.lower(), 0)
        return timezone(timedelta(hours=offset), name)


def slots(cfg: dict[str, Any] | None = None) -> list[str]:
    values = list((cfg or {}).get("posting_times") or DEFAULT_SLOTS)
    cleaned: list[str] = []
    for value in values:
        try:
            hour, minute = str(value).strip().split(":")[:2]
            cleaned.append(f"{int(hour):02d}:{int(minute):02d}")
        except (ValueError, TypeError):
            continue
    return sorted(cleaned) or DEFAULT_SLOTS


def parse_iso(value: str | None, cfg: dict[str, Any] | None = None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone(cfg))
    return dt


def to_iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def jitter(
    dt: datetime,
    seconds: int = JITTER_SECONDS,
    rng: Any = None,
) -> datetime:
    """Shift a posting slot by a random +/-``seconds`` window.

    The result is floored at now + 60s so a queue entry can never be
    scheduled in the past. ``rng`` accepts ``random`` or a seeded
    ``random.Random`` for deterministic tests.
    """
    r = rng or random
    out = dt + timedelta(seconds=r.uniform(-seconds, seconds))
    floor = datetime.now().astimezone() + timedelta(seconds=60)
    return out if out >= floor else floor


def _slot_key(dt: datetime, cfg: dict[str, Any] | None = None) -> datetime:
    """Canonical collision key: naive configured-zone wall time, second precision.

    There is exactly one normalisation step. An aware timestamp is converted
    to the configured zone. A naive timestamp is already a canonical key (the
    form returned by ``occupied_queue_slots``) and is never passed through
    ``astimezone`` again: doing that reinterprets it in the host machine's
    local timezone. On a Windows host whose local zone is UTC, that shifted
    every EAT occupied slot by +3 hours and made 19:00/21:00 collisions miss.
    """
    if dt.tzinfo is None:
        return dt.replace(microsecond=0)
    return dt.astimezone(zone(cfg)).replace(microsecond=0, tzinfo=None)


def occupied_queue_slots(
    queue_dir: Path | str, cfg: dict[str, Any] | None = None
) -> set[datetime]:
    """Read scheduled times already claimed by queue JSON records.

    Returns canonical naive configured-zone keys (see ``_slot_key``).
    Read-only and tolerant of a partially-written/corrupt record. Existing
    records are evidence and are never modified here.
    """
    occupied: set[datetime] = set()
    try:
        paths = sorted(Path(queue_dir).glob("*.json"))
    except OSError:
        return occupied
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        when = parse_iso(data.get("scheduled_for"), cfg)
        if when is not None:
            occupied.add(_slot_key(when, cfg))
    return occupied


def next_available_slots(
    cfg: dict[str, Any] | None,
    count: int,
    occupied: Iterable[datetime] | None = None,
    after: datetime | None = None,
) -> list[datetime]:
    """Next posting slots that are not already used by another queue item.

    Unlike ``next_slots`` this checks the queue's existing schedule, so two
    separate generation jobs cannot claim 19:00/21:00 on the same day. It
    still respects the configured timezone and posting times exactly.
    """
    if count <= 0:
        return []
    tz = zone(cfg)
    now = (after or datetime.now(tz)).astimezone(tz)
    times = slots(cfg)
    used = {_slot_key(item, cfg) for item in (occupied or [])}
    out: list[datetime] = []
    for day in range(0, 730):
        base = now.date() + timedelta(days=day)
        for value in times:
            hour, minute = value.split(":")
            candidate = datetime.combine(base, datetime.min.time(), tz).replace(
                hour=int(hour), minute=int(minute)
            )
            if candidate <= now + timedelta(seconds=30):
                continue
            key = _slot_key(candidate, cfg)
            if key in used:
                continue
            out.append(candidate)
            used.add(key)
            if len(out) >= count:
                return out
    return out


def next_slots(cfg: dict[str, Any] | None, count: int, after: datetime | None = None) -> list[datetime]:
    """The next ``count`` posting slots, in chronological order."""
    tz = zone(cfg)
    now = (after or datetime.now(tz)).astimezone(tz)
    times = slots(cfg)
    out: list[datetime] = []
    for day in range(0, 120):
        base = now.date() + timedelta(days=day)
        for value in times:
            hour, minute = value.split(":")
            candidate = datetime.combine(base, datetime.min.time(), tz).replace(
                hour=int(hour), minute=int(minute)
            )
            if candidate <= now + timedelta(seconds=30):
                continue
            out.append(candidate)
            if len(out) >= count:
                return out
    return out


def next_slot(cfg: dict[str, Any] | None, after: datetime | None = None) -> datetime:
    found = next_slots(cfg, 1, after)
    if found:
        return found[0]
    return datetime.now(zone(cfg)) + timedelta(hours=1)
