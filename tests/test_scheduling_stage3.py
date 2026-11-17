"""Phase 10 Stage 3: exact-time scheduling and durable slot claims.

All state lives in a throwaway temp directory; no real queue, posted records,
slot state, Telegram message or social post is touched.
"""
from __future__ import annotations

import importlib.util
import json
import random
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from backend import scheduling

ROOT = Path(__file__).resolve().parent.parent
EAT = ZoneInfo("Africa/Nairobi")


def load_scheduler():
    """Import scheduler/scheduler.py under a test-only module name."""
    spec = importlib.util.spec_from_file_location(
        "acf_scheduler_stage3", ROOT / "scheduler" / "scheduler.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sched = load_scheduler()

CFG = {
    "timezone": "Africa/Nairobi",
    "posting_times": ["19:00", "21:00"],
    "platforms": {"instagram": True, "tiktok": True},
    "schedule_jitter_seconds": 0,
}

NOW_19 = datetime(2026, 11, 6, 19, 0, tzinfo=EAT)
NOW_21 = datetime(2026, 11, 6, 21, 0, tzinfo=EAT)


def frozen_clock(module, when: datetime):
    """Freeze ``module.datetime.now()`` without changing production code."""

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return when.astimezone(tz) if tz is not None else when

    return mock.patch.object(module, "datetime", FrozenDateTime)


class ExactSlotTests(unittest.TestCase):
    """The configured 19:00/21:00 EAT slots stay exactly there."""

    def test_next_slots_are_exact_local_times(self):
        after = datetime(2026, 11, 6, 9, 0, tzinfo=EAT)
        slots = scheduling.next_slots(CFG, 2, after=after)

        self.assertEqual(
            [slot.strftime("%Y-%m-%d %H:%M %z") for slot in slots],
            ["2026-11-06 19:00 +0300", "2026-11-06 21:00 +0300"],
        )
        self.assertEqual([slot.hour for slot in slots], [19, 21])
        self.assertEqual({slot.utcoffset() for slot in slots}, {timedelta(hours=3)})

    def test_utc_conversion_is_correct(self):
        after = datetime(2026, 11, 6, 9, 0, tzinfo=EAT)
        slots = scheduling.next_slots(CFG, 2, after=after)

        self.assertEqual(
            [slot.astimezone(timezone.utc).strftime("%H:%M UTC") for slot in slots],
            ["16:00 UTC", "18:00 UTC"],
        )
        # Same instants, expressed in UTC.
        self.assertEqual(
            slots[0],
            datetime(2026, 11, 6, 16, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            slots[1],
            datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc),
        )

    def test_queue_slot_is_exact_without_jitter(self):
        after = datetime(2026, 11, 6, 9, 0, tzinfo=EAT)
        slots = scheduling.next_slots(CFG, 2, after=after)

        for slot in slots:
            self.assertEqual(scheduling.queue_slot(slot, CFG), slot)
            self.assertEqual(
                scheduling.queue_slot(slot, {"posting_times": ["19:00", "21:00"]}),
                slot,
            )
            self.assertEqual(
                scheduling.queue_slot(slot, {"schedule_jitter_seconds": 0}), slot
            )
            self.assertEqual(
                scheduling.queue_slot(slot, {"schedule_jitter_seconds": "junk"}), slot
            )

    def test_jitter_remains_available_but_is_opt_in(self):
        after = datetime(2026, 11, 6, 9, 0, tzinfo=EAT)
        slot = scheduling.next_slots(CFG, 1, after=after)[0]

        # Default: no shift at all.
        self.assertEqual(scheduling.schedule_jitter_seconds(CFG), 0)
        self.assertEqual(scheduling.queue_slot(slot, CFG), slot)

        # Explicit opt-in: bounded shift, same zone, same day. Freeze the
        # clock the helper floors against; otherwise this assertion becomes
        # false as soon as the real date passes the hard-coded slot date.
        with frozen_clock(scheduling, datetime(2026, 11, 6, 9, 0, tzinfo=EAT)):
            jittered = scheduling.queue_slot(slot, {"schedule_jitter_seconds": 60})
            self.assertLessEqual(abs((jittered - slot).total_seconds()), 60)
            self.assertEqual(jittered.utcoffset(), slot.utcoffset())

            # The original helper is intact for any other workflow.
            shift = scheduling.jitter(slot, 120, rng=random.Random(3))
            self.assertLessEqual(abs((shift - slot).total_seconds()), 120)


class SlotClaimTests(unittest.TestCase):
    """Durable claims, duplicate prevention and per-platform outcomes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="acf-stage3-"))
        self.queue = self.tmp / "queue"
        self.posted = self.tmp / "posted"
        self.state = self.tmp / "state"
        for directory in (self.queue, self.posted, self.state):
            directory.mkdir(parents=True)

        self.cfg = dict(CFG)
        self.ig = {"ok": True, "platform": "instagram"}
        self.tt = {"ok": True, "platform": "tiktok"}
        self.calls: list[str] = []
        self.observed_status: list[str] = []

        self.patches = [
            mock.patch.object(sched.paths, "QUEUE", self.queue),
            mock.patch.object(sched.paths, "POSTED", self.posted),
            mock.patch.object(sched.paths, "ensure_dirs", lambda: None),
            mock.patch.object(sched, "SLOT_STATE", self.state / "slots.json"),
            mock.patch.object(sched.common, "load_config", side_effect=lambda: dict(self.cfg)),
            mock.patch.object(sched.common, "info", lambda *a, **k: None),
            mock.patch.object(sched.common, "warn", lambda *a, **k: None),
            mock.patch.object(
                sched.common, "record_analytics_point", lambda *a, **k: True
            ),
            mock.patch.object(sched.telegram, "send_message", lambda *a, **k: True),
            mock.patch.object(sched.telegram, "send_video", lambda *a, **k: True),
            mock.patch.object(sched.telegram, "send_document", lambda *a, **k: True),
            mock.patch.object(sched, "post_instagram", side_effect=self._instagram),
            mock.patch.object(sched, "post_tiktok", side_effect=self._tiktok),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------- fixtures
    def _instagram(self, item, caption):
        self.calls.append("instagram")
        self.observed_status.append(self._slot_status("2026-11-06:evening"))
        self.observed_claim = self._slots().get("2026-11-06:evening")
        return dict(self.ig)

    def _tiktok(self, item, caption):
        self.calls.append("tiktok")
        return dict(self.tt)

    def _slot_status(self, key):
        try:
            record = json.loads((self.state / "slots.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "missing"
        entry = record.get(key)
        return entry.get("status") if isinstance(entry, dict) else "missing"

    def _slots(self):
        return json.loads((self.state / "slots.json").read_text(encoding="utf-8"))

    def seed_slots(self, records):
        (self.state / "slots.json").write_text(json.dumps(records), encoding="utf-8")

    def add_item(self, clip_id="clip-a", scheduled=NOW_19, attempts=0):
        (self.queue / f"{clip_id}.mp4").write_bytes(b"0" * 4096)
        (self.queue / f"{clip_id}.json").write_text(
            json.dumps(
                {
                    "id": clip_id,
                    "file": f"{clip_id}.mp4",
                    "title": f"Clip {clip_id}",
                    "caption": "caption",
                    "scheduled_for": scheduled.isoformat(),
                    "attempts": attempts,
                }
            ),
            encoding="utf-8",
        )

    # ---------------------------------------------------------------- tests
    def test_slot_is_claimed_before_the_first_platform_call(self):
        self.add_item()

        result = sched.run_slot("evening", notify=False, now=NOW_19)

        self.assertTrue(result["posted"])
        self.assertEqual(self.observed_status, ["pending"])
        record = self._slots()["2026-11-06:evening"]
        self.assertEqual(record["status"], "posted")
        self.assertEqual(record["clip"], "clip-a")
        self.assertIn("posted_at", record)
        self.assertEqual(record["platforms"]["instagram"]["ok"], True)
        self.assertEqual(record["platforms"]["tiktok"]["ok"], True)

    def test_same_slot_is_never_handled_twice(self):
        self.add_item("clip-a")
        sched.run_slot("evening", notify=False, now=NOW_19)
        self.assertEqual(self.calls, ["instagram", "tiktok"])

        self.add_item("clip-b")
        second = sched.run_slot("evening", notify=False, now=NOW_19)

        self.assertFalse(second["posted"])
        self.assertEqual(second["status"], "posted")
        self.assertIn("already posted", second["reason"])
        self.assertEqual(self.calls, ["instagram", "tiktok"], "no second publish")
        # clip-b is still queued, waiting for the next slot.
        self.assertTrue((self.queue / "clip-b.json").exists())

    def test_pending_claim_from_a_crash_blocks_republishing(self):
        self.add_item("clip-a")
        (self.state / "slots.json").write_text(
            json.dumps(
                {
                    "2026-11-06:evening": {
                        "clip": "clip-a",
                        "status": "pending",
                        "slot": "evening",
                    }
                }
            ),
            encoding="utf-8",
        )

        evening = sched.run_slot("evening", notify=False, now=NOW_19)
        night = sched.run_slot("night", notify=False, now=NOW_21)

        self.assertFalse(evening["posted"])
        self.assertEqual(evening["status"], "pending")
        self.assertFalse(night["posted"])
        self.assertIn("already pending", night["reason"])
        self.assertEqual(self.calls, [], "a claimed clip is never published twice")
        self.assertTrue((self.queue / "clip-a.json").exists())

    def test_legacy_slot_record_without_status_still_blocks(self):
        self.add_item("clip-a")
        (self.state / "slots.json").write_text(
            json.dumps(
                {
                    "2026-11-06:evening": {
                        "clip": "clip-a",
                        "at": "2026-11-06T19:00:00+03:00",
                    }
                }
            ),
            encoding="utf-8",
        )

        result = sched.run_slot("evening", notify=False, now=NOW_19)

        self.assertFalse(result["posted"])
        self.assertEqual(self.calls, [], "pre-status records still mean handled")

    def test_failed_slot_can_be_retried(self):
        self.add_item("clip-a", attempts=1)
        (self.state / "slots.json").write_text(
            json.dumps(
                {
                    "2026-11-06:evening": {
                        "clip": "clip-a",
                        "status": "failed",
                        "attempts": 1,
                        "error": "instagram: network",
                    }
                }
            ),
            encoding="utf-8",
        )

        result = sched.run_slot("night", notify=False, now=NOW_21)

        self.assertTrue(result["posted"])
        self.assertEqual(self._slots()["2026-11-06:night"]["status"], "posted")
        self.assertFalse((self.queue / "clip-a.json").exists())
        moved = json.loads((self.posted / "clip-a.json").read_text(encoding="utf-8"))
        self.assertEqual(moved["attempts"], 1)

    def test_partial_success_is_recorded_per_platform(self):
        self.tt = {"ok": False, "platform": "tiktok", "error": "upload rejected"}
        self.add_item("clip-a")

        result = sched.run_slot("evening", notify=False, now=NOW_19)

        self.assertTrue(result["posted"])
        self.assertEqual(result["status"], "partial")
        record = self._slots()["2026-11-06:evening"]
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["failed_platforms"], ["tiktok"])
        self.assertEqual(record["platforms"]["instagram"]["ok"], True)
        self.assertEqual(record["platforms"]["tiktok"]["ok"], False)

        moved = json.loads((self.posted / "clip-a.json").read_text(encoding="utf-8"))
        self.assertTrue(moved["partial"])
        self.assertEqual(moved["failed_platforms"], ["tiktok"])
        self.assertFalse((self.queue / "clip-a.json").exists())

        # No automatic republish of a partially successful clip.
        self.add_item("clip-b")
        again = sched.run_slot("evening", notify=False, now=NOW_19)
        self.assertFalse(again["posted"])
        self.assertEqual(again["status"], "partial")
        self.assertEqual(len(self.calls), 2)

    def test_disabled_platform_is_skipped_not_failed(self):
        self.cfg["platforms"] = {"instagram": True, "tiktok": False}
        self.add_item("clip-a")

        result = sched.run_slot("evening", notify=False, now=NOW_19)

        self.assertEqual(result["status"], "posted")
        record = self._slots()["2026-11-06:evening"]
        self.assertEqual(record["failed_platforms"], [])
        self.assertTrue(record["platforms"]["tiktok"]["skipped"])
        self.assertEqual(self.calls, ["instagram"])

    def test_three_failures_park_the_clip_for_manual_work(self):
        self.ig = {"ok": False, "platform": "instagram", "error": "token expired"}
        self.tt = {"ok": False, "platform": "tiktok", "error": "no session"}
        self.add_item("clip-a", attempts=2)

        result = sched.run_slot("night", notify=False, now=NOW_21)

        self.assertFalse(result["posted"])
        self.assertTrue(result["manual_required"])
        record = self._slots()["2026-11-06:night"]
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["attempts"], 3)
        self.assertIn("token expired", record["error"])
        parked = json.loads((self.posted / "clip-a.json").read_text(encoding="utf-8"))
        self.assertTrue(parked["manual_required"])

    def test_stale_pending_claim_is_recovered_next_day(self):
        self.add_item("clip-a")
        self.seed_slots(
            {
                "2026-11-05:evening": {
                    "clip": "clip-a",
                    "status": "pending",
                    "claim_version": 2,
                    "claimed_at": "2026-11-05T19:00:00+03:00",
                    "platforms": {},
                }
            }
        )

        result = sched.run_slot("evening", notify=False, now=NOW_19)

        self.assertTrue(result["posted"])
        self.assertEqual(self.calls, ["instagram", "tiktok"], "one publication")
        old = self._slots()["2026-11-05:evening"]
        self.assertEqual(old["status"], "abandoned")
        self.assertIn("abandoned_at", old)
        self.assertEqual(old["platforms"], {}, "platform evidence preserved")
        self.assertEqual(self._slots()["2026-11-06:evening"]["status"], "posted")
        self.assertFalse((self.queue / "clip-a.json").exists())

    def test_interrupted_pending_claim_is_never_recovered(self):
        self.add_item("clip-a")
        self.seed_slots(
            {
                "2026-11-01:evening": {
                    "clip": "clip-a",
                    "status": "pending",
                    "claim_version": 2,
                    "claimed_at": "2026-11-01T19:00:00+03:00",
                    "publishing_started": "2026-11-01T19:00:00+03:00",
                    "platforms": {"instagram": {"ok": True, "platform": "instagram"}},
                }
            }
        )

        result = sched.run_slot("evening", notify=False, now=NOW_19)

        self.assertFalse(result["posted"])
        self.assertEqual(result["status"], "pending")
        self.assertEqual(self.calls, [], "uncertain attempt is never republished")
        record = self._slots()["2026-11-01:evening"]
        self.assertEqual(record["status"], "pending")
        self.assertNotIn("abandoned_at", record)
        self.assertTrue(record["platforms"]["instagram"]["ok"])

    def test_legacy_pending_claim_is_never_recovered(self):
        self.add_item("clip-a")
        self.seed_slots(
            {
                "2026-11-05:evening": {
                    "clip": "clip-a",
                    "status": "pending",
                    "platforms": {},
                }
            }
        )

        result = sched.run_slot("evening", notify=False, now=NOW_19)

        self.assertFalse(result["posted"])
        self.assertEqual(self.calls, [])
        record = self._slots()["2026-11-05:evening"]
        self.assertEqual(record["status"], "pending")
        self.assertNotIn("abandoned_at", record)

    def test_same_key_manual_claim_blocks_republish(self):
        self.add_item("clip-a")
        self.seed_slots(
            {
                "2026-11-06:manual": {
                    "clip": "clip-a",
                    "status": "pending",
                    "claim_version": 2,
                    "publishing_started": "2026-11-06T19:00:00+03:00",
                    "platforms": {"instagram": {"ok": True}},
                }
            }
        )

        result = sched.run_slot("manual", notify=False, now=NOW_19)

        self.assertFalse(result["posted"])
        self.assertIn("already pending", result["reason"])
        self.assertEqual(self.calls, [], "a same-key manual retry must not repost")

    def test_publishing_marker_is_written_before_first_platform_call(self):
        self.add_item("clip-a")

        sched.run_slot("evening", notify=False, now=NOW_19)

        claim = self.observed_claim
        self.assertEqual(claim["status"], "pending")
        self.assertEqual(claim["claim_version"], 2)
        self.assertTrue(claim["publishing_started"])
        self.assertEqual(claim["platforms"], {})

    def test_failed_claim_write_prevents_publishing(self):
        self.add_item("clip-a")

        with mock.patch.object(sched, "_update_slot", side_effect=OSError("disk full")):
            result = sched.run_slot("evening", notify=False, now=NOW_19)

        self.assertFalse(result["posted"])
        self.assertIn("could not persist slot claim", result["reason"])
        self.assertEqual(self.calls, [], "no platform call without both claim writes")

    def test_pruning_keeps_pending_and_uncertain_claims(self):
        records = {
            f"2025-01-{day:03d}:evening": {
                "clip": f"old-{day}",
                "status": "posted",
            }
            for day in range(1, 71)
        }
        records["2025-02-01:evening"] = {
            "clip": "clip-a",
            "status": "pending",
            "claim_version": 2,
            "platforms": {},
        }
        self.seed_slots(records)

        sched._update_slot(
            "2026-11-06:evening", NOW_19, status="posted", clip="clip-z"
        )

        slots = self._slots()
        self.assertIn("2025-02-01:evening", slots, "pending claim must survive")
        self.assertEqual(slots["2025-02-01:evening"]["status"], "pending")
        self.assertIn("2026-11-06:evening", slots)
        terminal = [k for k, v in slots.items() if v.get("status") == "posted"]
        self.assertEqual(len(slots), 60, "record cap still applies")
        self.assertEqual(
            len(terminal), 59, "only terminal records were pruned, not the pending one"
        )

    def test_catch_up_posts_once_per_day(self):
        self.add_item(
            "clip-a", scheduled=datetime(2026, 11, 5, 19, 0, tzinfo=EAT)
        )
        morning = datetime(2026, 11, 6, 10, 0, tzinfo=EAT)

        # catch_up delegates to run_slot, which reads its own clock. Freeze it
        # to the injected time so the slot key is deterministic.
        with frozen_clock(sched, morning):
            sched.catch_up(now=morning)
            first_calls = list(self.calls)
            sched.catch_up(now=morning)

        self.assertEqual(first_calls, ["instagram", "tiktok"])
        self.assertEqual(self.calls, first_calls, "catch-up must not repeat")
        record = self._slots()["2026-11-06:catch-up"]
        self.assertEqual(record["status"], "posted")
        self.assertFalse((self.queue / "clip-a.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
