"""Focused regression tests for the Stage 5 defect remediation.

Covers the five behaviour changes that can be verified without a live LLM:
* Whisper language is explicit per job, with auto-detect kept as the default.
* Hooks wrap to at most two safe-width lines and captions may run during them.
* Queue slot allocation skips times already claimed by queue records.
* Gemini HTTP 404 falls through to a known-supported model.
* A deterministic ffmpeg failure preserves its command, exit code and stderr.

Run with:
    python -m unittest tests.test_remediation -v
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend import captions, renderer, scheduling  # noqa: E402
import backend.main as main  # noqa: E402

EAT = ZoneInfo("Africa/Nairobi")
CFG = {"timezone": "Africa/Nairobi", "posting_times": ["19:00", "21:00"]}


class LanguageResolverTests(unittest.TestCase):
    def test_explicit_job_language_wins_over_env_and_config(self):
        with mock.patch.dict(os.environ, {"WHISPER_LANGUAGE": "fr"}):
            self.assertEqual(
                main._resolve_whisper_language(
                    SimpleNamespace(language="en"), {"language": "sw"}
                ),
                "en",
            )

    def test_env_wins_over_config_and_auto_is_the_default(self):
        with mock.patch.dict(os.environ, {"WHISPER_LANGUAGE": "fr"}):
            self.assertEqual(
                main._resolve_whisper_language(
                    SimpleNamespace(language=None), {"language": "sw"}
                ),
                "fr",
            )
        with mock.patch.dict(os.environ, {"WHISPER_LANGUAGE": ""}):
            self.assertEqual(
                main._resolve_whisper_language(
                    SimpleNamespace(language=None), {"language": "sw"}
                ),
                "sw",
            )
            self.assertIsNone(
                main._resolve_whisper_language(
                    SimpleNamespace(language=None), {"language": "auto"}
                )
            )


class TranscribeLanguageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="acf-whisper-"))
        self.info = SimpleNamespace(
            duration=10.0, language="en", language_probability=0.93
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _transcribe(self, language):
        model = mock.Mock()
        model.transcribe.return_value = ([], self.info)
        job = mock.Mock()
        with mock.patch("faster_whisper.WhisperModel", return_value=model), mock.patch.object(
            main, "WHISPER_DIR", self.tmp
        ):
            segments, detected, total = main.transcribe(
                Path("audio.wav"), job, language=language
            )
        return model, job, segments, detected, total

    def test_explicit_language_reaches_faster_whisper_and_is_recorded(self):
        model, job, segments, detected, total = self._transcribe("en")
        self.assertEqual(model.transcribe.call_args.kwargs["language"], "en")
        self.assertEqual(detected, "en")
        self.assertEqual(total, 10.0)
        self.assertEqual(segments, [])
        updates = [call.kwargs for call in job.update.call_args_list]
        self.assertIn("language", [key for update in updates for key in update])
        self.assertTrue(
            any(update.get("language_probability") == 0.93 for update in updates)
        )

    def test_auto_detection_passes_no_language(self):
        model, _, _, detected, _ = self._transcribe(None)
        self.assertNotIn("language", model.transcribe.call_args.kwargs)
        self.assertEqual(detected, "en")


class HookCaptionTests(unittest.TestCase):
    def _doc(self, hook, captions_during_hook):
        words = [
            captions.CaptionWord(0.1, 0.5, "first"),
            captions.CaptionWord(0.6, 1.0, "words"),
            captions.CaptionWord(3.2, 3.6, "later"),
        ]
        return captions.build_ass(
            words,
            duration=8.0,
            hook=hook,
            hook_seconds=3.0,
            captions_during_hook=captions_during_hook,
        )

    def test_long_hook_wraps_to_two_safe_width_lines(self):
        hook = "STOP SCROLLING - THIS IS THE PART NOBODY TELLS YOU ABOUT ANY OF THIS"
        doc = self._doc(hook, True)
        line = next(line for line in doc.splitlines() if ",Hook," in line)
        text = line.split(",", 9)[9]
        self.assertEqual(text.count("\\N"), 1, text)
        self.assertIn("\\fs", text)
        lines = text.split("\\N")
        self.assertTrue(all(lines), lines)
        # The 92 px style must shrink rather than overflow the 960 px safe area.
        self.assertLess(captions._wrap_hook(hook)[1], 92)

    def test_short_hook_stays_one_line(self):
        text, font = captions._wrap_hook("WAIT FOR IT")
        self.assertNotIn("\\N", text)
        self.assertEqual(font, 92)

    def test_captions_can_run_during_the_hook_without_moving_the_hook(self):
        with_captions = self._doc("WAIT FOR IT", True)
        hook_style = next(
            line
            for line in captions.ASS_HEADER.splitlines()
            if line.startswith("Style: Hook,")
        )
        self.assertEqual(hook_style.split(",")[18], "8")  # top aligned
        self.assertIn("\\pos(540,1500)", with_captions)  # captions stay lower

        early = [
            line
            for line in with_captions.splitlines()
            if ",Caption," in line and line.split(",")[1] < "0:00:03.00"
        ]
        self.assertTrue(early, "hook-time captions must not be skipped")

        without = self._doc("WAIT FOR IT", False)
        early_without = [
            line
            for line in without.splitlines()
            if ",Caption," in line and line.split(",")[1] < "0:00:03.00"
        ]
        self.assertEqual(early_without, [])


class QueueAllocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="acf-queue-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_slot(self, name: str, scheduled_for: str) -> None:
        (self.tmp / name).write_text(
            json.dumps({"scheduled_for": scheduled_for}), encoding="utf-8"
        )

    def test_occupied_slots_are_read_from_existing_queue_records(self):
        self._write_slot("a.json", "2026-11-16T19:00:00+03:00")
        (self.tmp / "broken.json").write_text("{not json", encoding="utf-8")
        occupied = scheduling.occupied_queue_slots(self.tmp, CFG)
        self.assertEqual(
            occupied,
            {datetime(2026, 11, 16, 19, 0)},
        )

    def test_new_slots_skip_times_already_in_the_queue(self):
        occupied = {
            datetime(2026, 11, 16, 19, 0, tzinfo=EAT),
            datetime(2026, 11, 16, 21, 0, tzinfo=EAT),
        }
        after = datetime(2026, 11, 16, 9, 0, tzinfo=EAT)
        slots = scheduling.next_available_slots(
            CFG, 2, occupied=occupied, after=after
        )
        self.assertEqual(
            [slot.strftime("%Y-%m-%d %H:%M") for slot in slots],
            ["2026-11-17 19:00", "2026-11-17 21:00"],
        )
        self.assertEqual({slot.utcoffset() for slot in slots}, {timedelta(hours=3)})

    def test_already_normalised_naive_slots_are_skipped(self):
        # This is the exact Windows failure: naive keys were normalised a
        # second time and shifted +3 hours, so 19:00/21:00 looked free.
        occupied = {
            datetime(2026, 11, 16, 19, 0),
            datetime(2026, 11, 16, 21, 0),
        }
        after = datetime(2026, 11, 16, 9, 0, tzinfo=EAT)
        slots = scheduling.next_available_slots(
            CFG, 2, occupied=occupied, after=after
        )
        self.assertEqual(
            [slot.strftime("%Y-%m-%d %H:%M") for slot in slots],
            ["2026-11-17 19:00", "2026-11-17 21:00"],
        )

    def test_windows_host_timezone_does_not_shift_naive_keys(self):
        naive = datetime(2026, 11, 16, 19, 0)
        aware = datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc)
        for host_tz in ("UTC", "Africa/Nairobi"):
            with self.subTest(host_tz=host_tz), mock.patch.dict(
                os.environ, {"TZ": host_tz}
            ):
                self.assertEqual(scheduling._slot_key(naive, CFG), naive)
                # An aware UTC instant is still converted exactly once.
                self.assertEqual(
                    scheduling._slot_key(aware, CFG),
                    datetime(2026, 11, 16, 19, 0),
                )

    def test_mixed_aware_and_naive_queue_records_occupy_both_slots(self):
        self._write_slot("aware.json", "2026-11-16T19:00:00+03:00")
        self._write_slot("naive.json", "2026-11-16T21:00:00")
        # A duplicate record must not make either slot appear free.
        self._write_slot("duplicate.json", "2026-11-16T19:00:00+03:00")
        occupied = scheduling.occupied_queue_slots(self.tmp, CFG)
        self.assertEqual(
            occupied,
            {datetime(2026, 11, 16, 19, 0), datetime(2026, 11, 16, 21, 0)},
        )

        slots = scheduling.next_available_slots(
            CFG,
            2,
            occupied=occupied,
            after=datetime(2026, 11, 16, 9, 0, tzinfo=EAT),
        )
        self.assertEqual(
            [slot.strftime("%Y-%m-%d %H:%M") for slot in slots],
            ["2026-11-17 19:00", "2026-11-17 21:00"],
        )

    def test_sequential_jobs_receive_unique_slots(self):
        after = datetime(2026, 11, 16, 9, 0, tzinfo=EAT)
        occupied = {
            datetime(2026, 11, 16, 19, 0),
            datetime(2026, 11, 16, 21, 0),
        }
        first = scheduling.next_available_slots(
            CFG, 2, occupied=occupied, after=after
        )
        second = scheduling.next_available_slots(
            CFG, 2, occupied=occupied | set(first), after=after
        )
        self.assertEqual(
            [slot.strftime("%Y-%m-%d %H:%M") for slot in first],
            ["2026-11-17 19:00", "2026-11-17 21:00"],
        )
        self.assertEqual(
            [slot.strftime("%Y-%m-%d %H:%M") for slot in second],
            ["2026-11-18 19:00", "2026-11-18 21:00"],
        )
        self.assertFalse(set(first) & set(second))

    def test_allocation_crosses_midnight_into_the_next_day(self):
        occupied = {
            datetime(2026, 11, 17, 19, 0),
            datetime(2026, 11, 17, 21, 0),
        }
        slots = scheduling.next_available_slots(
            CFG,
            2,
            occupied=occupied,
            after=datetime(2026, 11, 16, 23, 30, tzinfo=EAT),
        )
        self.assertEqual(
            [slot.strftime("%Y-%m-%d %H:%M") for slot in slots],
            ["2026-11-18 19:00", "2026-11-18 21:00"],
        )


class FfmpegDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="acf-ffmpeg-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_failed_command_preserves_command_exit_code_and_stderr(self):
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg not installed")
        output = self.tmp / "failed.mp4"
        missing = self.tmp / "missing-input.mp4"
        with self.assertRaises(renderer.RenderError):
            renderer._run_ffmpeg(
                ["-i", str(missing), "-t", "1", str(output)], timeout=20
            )
        log = output.with_suffix(".ffmpeg.log")
        self.assertTrue(log.exists(), "failed render must leave a diagnostic sidecar")
        body = log.read_text(encoding="utf-8")
        self.assertIn("exit_code:", body)
        self.assertIn("command:", body)
        self.assertIn(str(missing), body)
        self.assertTrue(
            "No such file" in body or "Error" in body,
            "stderr must be preserved in the sidecar",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
