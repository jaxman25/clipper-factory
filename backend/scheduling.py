"""Posting-slot maths shared by the generator, scheduler and bot."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_SLOTS = ["19:00", "21:00"]
FALLBACK_OFFSETS = {"africa/nairobi": 3}
# Anti-flag scheduling: slots land somewhere in a +/-2h window so posting
# times never line up across accounts or look bot-driven.
JITTER_SECONDS = 2 * 60 * 60


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
