"""Selection and configuration tests for the three generation modes.

Covers the Phase 5 requirements that can be verified without network or
ffmpeg:

* viral selection honours requested counts 3/5/10/15, ranks distinctly and
  reports a shortfall instead of fabricating scored clips
* equal slices divide the full source into N intervals, pick one complete
  speech segment per interval, stay inside the configured duration limits,
  report empty intervals, and never call the global viral selector
* transform planning yields N distinct pieces and each piece renders up to
  three platform variants (mocked TTS/render), with per-target complete-thought
  scripts
* duration bounds can no longer be inverted, and user preferences resolve
  before explicit per-job flags

Run with:
    python -m unittest discover -s tests -p "test_*.py" -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend import broll, common, renderer, selection, transform, viral  # noqa: E402
import backend.main as main  # noqa: E402


def make_segments(duration: float, seg: float = 10.0, text: str = "The spirit warned the village at midnight."):
    raw = []
    start = 0.0
    index = 0
    while start < duration:
        # Each segment needs distinct content: Stage 3C-3 correctly refuses
        # to present the same transcript at two different timestamps.
        raw.append(
            {
                "start": start,
                "end": min(duration, start + seg),
                "text": f"{text} Story {index} continues with a different detail.",
                "words": [],
            }
        )
        start += seg
        index += 1
    return viral.build_segments(raw)


class DurationBoundsTests(unittest.TestCase):
    def test_configured_window_is_preserved(self):
        self.assertEqual(
            selection.duration_bounds({"clip_min_seconds": 30, "clip_max_seconds": 45}),
            (30.0, 45.0),
        )

    def test_inverted_window_is_widened_not_zeroed(self):
        # The dashboard used to force max=25 while min stayed 30.
        minimum, maximum = selection.duration_bounds(
            {"clip_min_seconds": 30, "clip_max_seconds": 25}
        )
        self.assertEqual(minimum, 30.0)
        self.assertGreater(maximum, minimum)
        segments = make_segments(600)
        candidates = viral.find_candidates(segments, [], None, minimum, maximum)
        self.assertGreater(len(candidates), 0, "widened bounds must still produce candidates")

    def test_missing_values_fall_back_to_defaults(self):
        self.assertEqual(selection.duration_bounds({}), (30.0, 45.0))

    def test_user_config_applies_known_keys_only(self):
        cfg = {"clip_max_seconds": 45, "platforms": {"instagram": True}}
        selection.apply_user_config(
            cfg,
            {
                "clip_max_seconds": 55,
                "playback_speed": 1.2,
                "instagram": False,
                "unknown_key": "ignored",
            },
        )
        self.assertEqual(cfg["clip_max_seconds"], 55.0)
        self.assertEqual(cfg["playback_speed"], 1.2)
        self.assertFalse(cfg["platforms"]["instagram"])
        self.assertNotIn("unknown_key", cfg)


class ViralSelectionTests(unittest.TestCase):
    def test_requested_counts_three_five_ten_fifteen(self):
        segments = make_segments(1800)
        for count in (3, 5, 10, 15):
            with self.subTest(count=count):
                selected, diag = selection.select_viral(
                    segments, [], None, count, 30, 45, 1800
                )
                self.assertEqual(len(selected), count)
                self.assertEqual(diag["shortfall"], 0)
                self.assertFalse(any(item.fallback for item in selected))
                self.assertEqual(
                    [item.start for item in selected],
                    sorted(item.start for item in selected),
                )
                for first, second in zip(selected, selected[1:]):
                    self.assertLessEqual(first.end, second.start + 0.4)
                for item in selected:
                    self.assertGreaterEqual(item.end - item.start, 29.5)
                    self.assertLessEqual(item.end - item.start, 45.5)

    def test_shortfall_is_reported_not_padded(self):
        segments = make_segments(120)  # only a few windows fit
        selected, diag = selection.select_viral(segments, [], None, 10, 30, 45, 120)
        self.assertLess(len(selected), 10)
        self.assertEqual(diag["shortfall"], 10 - len(selected))
        self.assertFalse(any(item.fallback for item in selected))

    def test_no_transcript_uses_flagged_fallback_only(self):
        selected, diag = selection.select_viral([], [], None, 5, 30, 45, 600)
        self.assertEqual(len(selected), 5)
        self.assertTrue(all(item.fallback for item in selected))
        self.assertEqual(diag["fallback"], 5)

    def test_candidates_are_ranked_and_distinct(self):
        # A stronger transcript (keywords + question) should outrank plain text.
        raw = [
            {"start": float(t), "end": float(t + 10), "text": "the market opened early today", "words": []}
            for t in range(0, 300, 10)
        ]
        segments = viral.build_segments(raw)
        candidates = viral.find_candidates(segments, [], None, 30, 45)
        scores = [candidate.score for candidate in candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))
        chosen = viral.select_top(candidates, 3, 30, 45)
        for first, second in zip(chosen, chosen[1:]):
            self.assertLessEqual(first.end, second.start + 0.4)


class EqualSelectionTests(unittest.TestCase):
    def test_sixty_minute_source_counts(self):
        duration = 3600.0
        segments = make_segments(duration)
        for count in (5, 10, 15):
            with self.subTest(count=count):
                selected, diag = selection.select_equal(
                    segments, duration, count, 30, 45
                )
                self.assertEqual(len(selected), count)
                self.assertEqual(len(diag["intervals"]), count)
                width = duration / count
                for item in selected:
                    low = (int(item.start // width)) * width
                    high = min(duration, low + width)
                    self.assertGreaterEqual(item.start, low - 0.01)
                    self.assertLessEqual(item.end, high + 0.01)
                    self.assertGreaterEqual(item.end - item.start, 29.5)
                    self.assertLessEqual(item.end - item.start, 45.5)
                self.assertEqual(
                    [item.start for item in selected],
                    sorted(item.start for item in selected),
                )
                for first, second in zip(selected, selected[1:]):
                    self.assertLessEqual(first.end, second.start + 0.01)

    def test_equal_never_calls_the_global_viral_selector(self):
        segments = make_segments(600)
        with mock.patch.object(
            selection.viral, "select_top", side_effect=AssertionError("global ranking used")
        ), mock.patch.object(
            selection.viral, "find_candidates", side_effect=AssertionError("global ranking used")
        ):
            selected, _ = selection.select_equal(segments, 600, 4, 30, 45)
        self.assertEqual(len(selected), 4)

    def test_empty_intervals_are_reported_and_not_filled(self):
        segments = make_segments(600)  # speech only in the first 10 minutes
        selected, diag = selection.select_equal(segments, 3600, 6, 30, 45)
        self.assertEqual(len(selected), 1)
        empty = [row for row in diag["intervals"] if not row["selected"]]
        self.assertEqual(len(empty), 5)
        self.assertEqual(diag["empty"], 5)
        for row in empty:
            self.assertIn("no complete speech", row["reason"])

    def test_no_transcript_visual_slices_are_flagged(self):
        selected, diag = selection.select_equal([], 600, 5, 30, 45)
        self.assertEqual(len(selected), 5)
        self.assertTrue(all(item.fallback for item in selected))
        self.assertTrue(all(item.candidate.text == "" for item in selected))
        self.assertEqual(diag["fallback"], 5)


class TransformSelectionTests(unittest.TestCase):
    def test_requested_piece_counts(self):
        segments = make_segments(1800)
        for count in (3, 5, 10, 15):
            with self.subTest(count=count):
                selected, diag = selection.select_transform(
                    segments, [], None, 1800, count
                )
                self.assertEqual(len(selected), count, diag)
                self.assertEqual(diag["shortfall"], 0)
                for first, second in zip(selected, selected[1:]):
                    self.assertLessEqual(first.end, second.start + 0.4)
                # Transform windows are long enough for the 59 s target.
                for item in selected:
                    self.assertGreaterEqual(item.end - item.start, 59.5)

    def test_fit_script_preserves_complete_sentences(self):
        script = " ".join(["The spirit warned the village at midnight."] * 40)
        for target in (21, 30, 59):
            budget = transform.words_for_seconds(target)
            fitted = transform.fit_script(script, budget)
            self.assertLessEqual(len(fitted.split()), budget)
            self.assertTrue(fitted.endswith("."), fitted[-20:])
        short = transform.fit_script(script, transform.words_for_seconds(59))
        medium = transform.fit_script(script, transform.words_for_seconds(30))
        tiny = transform.fit_script(script, transform.words_for_seconds(21))
        self.assertGreater(len(short.split()), len(medium.split()))
        self.assertGreater(len(medium.split()), len(tiny.split()))

    def test_extend_script_uses_source_sentences_without_duplicates(self):
        script = "The spirit warned the village at midnight."
        source = (
            "The spirit warned the village at midnight. "
            "The elders gathered by the river and listened. "
            "Rain finally came at dawn."
        )
        extended = transform.extend_script(
            script, source, transform.words_for_seconds(21)
        )
        self.assertGreater(len(extended.split()), len(script.split()))
        self.assertEqual(extended.lower().count("the spirit warned"), 1)
        self.assertIn("elders gathered", extended)

    def test_broll_query_comes_from_the_narration(self):
        query = transform.broll_query(
            "The mermaid cursed the river village at midnight."
        )
        self.assertIn("mermaid", query.lower())
        self.assertNotEqual(query, "african village night")


class TransformRenderTests(unittest.TestCase):
    """Mocked TTS/render: N pieces must produce up to 3N platform files."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="acf-transform-"))
        self.queue = self.tmp / "queue"
        self.jobs = self.tmp / "jobs"
        self.job_dir = self.tmp / "export"
        for directory in (self.queue, self.jobs, self.job_dir):
            directory.mkdir(parents=True)
        self.scripts: list[str] = []
        self.patches = [
            mock.patch.object(main.paths, "QUEUE", self.queue),
            mock.patch.object(main.paths, "JOBS", self.jobs),
            mock.patch.object(main.renderer, "probe", side_effect=self._probe),
            mock.patch.object(main.renderer, "render_clip", side_effect=self._render),
            mock.patch.object(main.transform, "rewrite_script", side_effect=self._rewrite),
            mock.patch.object(
                main.transform,
                "generate_metadata",
                return_value=(
                    {
                        "titles": ["a", "b", "c"],
                        "descriptions": ["d", "e", "f"],
                        "hashtags": [["#a"], ["#b"], ["#c"]],
                    },
                    "template",
                ),
            ),
            mock.patch.object(
                main.transform, "synthesize_voiceover", side_effect=self._voice
            ),
            mock.patch.object(main.broll_mod, "fetch", return_value=None),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rewrite(self, text, max_words=None):
        return ("The spirit warned the village at midnight. " * 40).strip(), "gemini"

    def _probe(self, path):
        # The mocked voiceover must cover its target; source probes are separate.
        if str(path).lower().endswith(".mp3"):
            return {"duration": 60.0}
        return {"duration": 10.0}

    def _voice(self, script, out_path, voice=None):
        self.scripts.append(script)
        Path(out_path).write_bytes(b"ID3" + b"0" * 800)
        return Path(out_path), [{"start": 0.0, "end": 1.0, "text": "word"}]

    def _render(self, source, out_path, start, end, words, cfg, **kwargs):
        Path(out_path).write_bytes(b"0" * 30000)
        return {
            "duration": kwargs.get("target_duration") or (end - start),
            "width": 1080,
            "height": 1920,
            "face_detected": False,
            "speed": 1.15,
            "broll": None,
        }

    def test_each_requested_piece_produces_platform_variants(self):
        segments_raw = [
            {
                "start": float(t),
                "end": float(t + 10),
                "text": (
                    "The spirit warned the village at midnight about story "
                    f"{t // 10} and the lanterns that followed."
                ),
                "words": [],
            }
            for t in range(0, 1800, 10)
        ]
        for count in (3, 5, 10, 15):
            with self.subTest(count=count):
                self.scripts.clear()
                job_id = f"job-transform-{count}"
                job = main.Job(job_id, "https://example.com/v", count, "transform")
                items, pieces = main._render_transform(
                    source=Path("source.mp4"),
                    audio=Path("audio.wav"),
                    info={"width": 1920, "height": 1080, "has_audio": True},
                    duration=1800.0,
                    segments_raw=segments_raw,
                    language="en",
                    job=job,
                    cfg={"clip_min_seconds": 30, "clip_max_seconds": 45},
                    job_id=job_id,
                    job_dir=self.job_dir,
                    broll_path=None,
                    hashtags="#tag",
                    source_url="https://example.com/v",
                    count=count,
                    mode="transform",
                )
                self.assertEqual(pieces, count)
                self.assertEqual(len(items), count * 3)
                self.assertEqual(len(self.scripts), count * 3)
                self.assertEqual(job.data["requested_count"], count)
                self.assertEqual(job.data["selected_count"], count)
                self.assertEqual(job.data["rendered_count"], count)
                self.assertEqual(job.data["rendered_files"], count * 3)

                by_piece: dict[int, set[str]] = {}
                for item in items:
                    by_piece.setdefault(item["piece"], set()).add(item["platform"])
                    self.assertEqual(item["mode"], "transform")
                    self.assertEqual(len(item["variants"]), 3)
                    self.assertLessEqual(
                        len(item["transcript"].split()),
                        transform.words_for_seconds(item["seconds"]),
                    )
                self.assertEqual(sorted(by_piece), list(range(1, count + 1)))
                for platforms in by_piece.values():
                    self.assertEqual(platforms, {"t21", "t30", "t59"})

                # Each target is its own complete-thought narration, not one
                # script reused at three lengths.
                for piece in range(1, count + 1):
                    scripts = {
                        item["seconds"]: item["transcript"]
                        for item in items
                        if item["piece"] == piece
                    }
                    self.assertGreater(
                        len(scripts[59].split()), len(scripts[30].split())
                    )
                    self.assertGreater(
                        len(scripts[30].split()), len(scripts[21].split())
                    )


class ParserTests(unittest.TestCase):
    def test_clip_max_is_optional_and_user_config_is_accepted(self):
        parser = main.build_parser()
        args = parser.parse_args(["--url", "https://example.com/v"])
        self.assertIsNone(
            args.clip_max_seconds,
            "an absent request must not force a clip length over config.json",
        )
        args = parser.parse_args(
            [
                "--clip-max-seconds",
                "40",
                "--user-config-json",
                '{"clip_max_seconds": 55}',
            ]
        )
        self.assertEqual(args.clip_max_seconds, 40.0)
        self.assertEqual(args.user_config_json, '{"clip_max_seconds": 55}')

    def test_render_clip_accepts_forced_broll(self):
        import inspect

        parameters = inspect.signature(renderer.render_clip).parameters
        self.assertIn("force_broll", parameters)

    def test_language_is_optional_and_forwarded_when_explicit(self):
        parser = main.build_parser()
        automatic = parser.parse_args(["--url", "https://example.com/v"])
        self.assertIsNone(automatic.language)
        explicit = parser.parse_args(["--url", "https://example.com/v", "--language", "en"])
        self.assertEqual(explicit.language, "en")


class _Landmark:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class _StubLandmarkerResult:
    """Shape of ``FaceLandmarkerResult``: landmarks only, no ``detections``."""

    def __init__(self, faces):
        self.face_landmarks = faces
        self.face_blendshapes = []
        self.facial_transformation_matrixes = []


class FaceDetectionTests(unittest.TestCase):
    def test_face_centres_read_landmarks_not_legacy_detections(self):
        result = _StubLandmarkerResult(
            [
                [
                    _Landmark(0.2, 0.4),
                    _Landmark(0.6, 0.8),
                    _Landmark(0.4, 0.5),
                ]
            ]
        )
        self.assertFalse(hasattr(result, "detections"))
        centres = renderer._face_centres(result)
        self.assertEqual(len(centres), 1)
        self.assertAlmostEqual(centres[0][0], 0.4)
        self.assertAlmostEqual(centres[0][1], 0.6)

    def test_no_face_result_returns_no_centres(self):
        self.assertEqual(renderer._face_centres(_StubLandmarkerResult([])), [])
        self.assertEqual(renderer._face_centres(_StubLandmarkerResult([[]])), [])
        self.assertEqual(renderer._face_centres(object()), [])

    def test_multiple_faces_each_get_a_centre(self):
        result = _StubLandmarkerResult(
            [
                [_Landmark(0.1, 0.1), _Landmark(0.3, 0.3)],
                [_Landmark(0.6, 0.6), _Landmark(0.8, 0.8)],
            ]
        )
        centres = renderer._face_centres(result)
        self.assertEqual(len(centres), 2)
        self.assertAlmostEqual(centres[0][0], 0.2)
        self.assertAlmostEqual(centres[1][1], 0.7)

    def test_detector_exception_degrades_to_cinematic_fallback(self):
        with tempfile.TemporaryDirectory(prefix="acf-face-") as tmp:
            out = Path(tmp) / "clip.mp4"

            def fake_ffmpeg(args, timeout):
                out.write_bytes(b"0" * 30000)

            with mock.patch.object(
                renderer,
                "detect_face_center",
                side_effect=RuntimeError("detector exploded"),
            ), mock.patch.object(
                renderer, "_run_ffmpeg", side_effect=fake_ffmpeg
            ), mock.patch.object(
                renderer, "ensure_gradient", return_value=None
            ):
                meta = renderer.render_clip(
                    Path("source.mp4"),
                    out,
                    0.0,
                    10.0,
                    [],
                    {"playback_speed": 1.1},
                    info={"width": 1920, "height": 1080, "has_audio": True},
                    max_duration=9.0,
                )
        self.assertFalse(meta["face_detected"])

    def test_landmarker_options_build_without_name_error(self):
        """Regression for the bare ``BaseOptions`` NameError."""
        try:
            probe = subprocess.run(
                [sys.executable, "-c", "import mediapipe"],
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            self.skipTest("mediapipe import timed out in this interpreter")
        if probe.returncode != 0:
            self.skipTest("mediapipe is not importable in this environment")

        model = REPO_ROOT / "assets" / "face_models" / "face_landmarker.task"
        options = renderer._landmarker_options(model)
        self.assertIsNotNone(options)


class RenderLoopTests(unittest.TestCase):
    """Phase 6 defect A: the render loop must unwrap ``selection.Selected``.

    Selection returns ``Selected`` wrappers, so reading ``.score``/``.words``
    off the loop variable raised ``AttributeError`` on the first clip of every
    Viral and Equal job. These tests run the real ``main.run`` loop with the
    heavy stages (download, ffmpeg, whisper, render) mocked out.
    """

    DURATION = 900.0

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="acf-render-loop-"))
        self.dirs = {
            name: self.tmp / name.lower()
            for name in ("DOWNLOADS", "EXPORTS", "QUEUE", "POSTED", "STATE", "JOBS", "LOGS")
        }
        for directory in self.dirs.values():
            directory.mkdir(parents=True, exist_ok=True)
        self.patches = [
            mock.patch.object(main.paths, name, path)
            for name, path in self.dirs.items()
        ] + [
            mock.patch.object(main.paths, "LOCK_FILE", self.dirs["STATE"] / "generate.lock"),
            mock.patch.object(main.common.paths, "LOG_FILE", self.dirs["STATE"] / "logs.jsonl"),
            mock.patch.object(main, "_ensure_tools"),
            mock.patch.object(main, "download_source", side_effect=self._download),
            mock.patch.object(main, "extract_audio", side_effect=self._audio),
            mock.patch.object(main, "transcribe", side_effect=self._transcribe),
            mock.patch.object(main.viral, "compute_rms", return_value=[]),
            mock.patch.object(main.renderer, "probe", side_effect=self._probe),
            mock.patch.object(main.renderer, "render_clip", side_effect=self._render),
            mock.patch.object(
                main.transform,
                "generate_metadata",
                return_value=(
                    {
                        "titles": ["a", "b", "c"],
                        "descriptions": ["d", "e", "f"],
                        "hashtags": [["#a"], ["#b"], ["#c"]],
                    },
                    "template",
                ),
            ),
            mock.patch.object(main.broll_mod, "fetch", return_value=None),
            mock.patch.object(main.telegram, "send_message", return_value=True),
        ]
        for patcher in self.patches:
            patcher.start()
        # No transcript for this variable: the fallback path must stay flagged.
        self.segments_raw: list[dict] = [
            {
                "start": float(t),
                "end": float(t + 10),
                "text": (
                    "The spirit warned the village at midnight about story "
                    f"{t // 10} and the lanterns that followed."
                ),
                "words": [],
            }
            for t in range(0, int(self.DURATION), 10)
        ]

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _download(self, url, job_id, job):
        path = self.dirs["DOWNLOADS"] / f"{job_id}.mp4"
        path.write_bytes(b"0" * 2048)
        return path, "Mocked source", "mock-channel"

    def _audio(self, video, job_id):
        path = self.dirs["DOWNLOADS"] / f"{job_id}.wav"
        path.write_bytes(b"0" * 1024)
        return path

    def _transcribe(self, audio, job, language=None):
        return list(self.segments_raw), "en", self.DURATION

    def _probe(self, path):
        if str(path).lower().endswith(".mp3"):
            return {"duration": 60.0, "width": 0, "height": 0, "has_audio": True}
        return {"duration": self.DURATION, "width": 1280, "height": 720, "has_audio": True}

    def _render(self, source, out_path, start, end, words, cfg, **kwargs):
        Path(out_path).write_bytes(b"0" * 30000)
        thumb = kwargs.get("thumb_path")
        if thumb:
            Path(thumb).write_bytes(b"0" * 64)
        return {
            "duration": round(float(end) - float(start), 2),
            "width": 1080,
            "height": 1920,
            "face_detected": False,
            "speed": cfg.get("playback_speed"),
            "broll": None,
        }

    def _run(self, mode: str, count: int, job_id: str, keep_source: bool = False):
        argv = [
            "--url", "https://example.com/video",
            "--num-shorts", str(count),
            "--job-id", job_id,
            "--mode", mode,
            "--no-notify",
            # Keep the run hermetic whatever config.json/ENV say.
            "--youtube-auto-post", "false",
        ]
        if keep_source:
            argv.append("--keep-source")
        args = main.build_parser().parse_args(argv)
        return main.run(args)

    def _queue_items(self) -> list[dict]:
        items = []
        for path in sorted(self.dirs["QUEUE"].glob("*.json")):
            items.append(json.loads(path.read_text(encoding="utf-8")))
        return items

    def test_viral_count_three_renders_three_distinct_clips(self):
        self.assertEqual(self._run("viral", 3, "loop-viral"), 0)
        job = json.loads((self.dirs["JOBS"] / "loop-viral.json").read_text(encoding="utf-8"))
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["selected_count"], 3)
        self.assertEqual(job["rendered_count"], 3)

        items = self._queue_items()
        self.assertEqual(len(items), 3, "one queue item per selected clip")
        windows = {(item["start"], item["end"]) for item in items}
        self.assertEqual(len(windows), 3, "clips must come from distinct source windows")
        for item in items:
            self.assertEqual(item["mode"], "viral")
            self.assertIsNotNone(item["viral_score"], "transcript clips carry a real score")
            self.assertNotIn("fallback", item)

    def test_equal_count_three_renders_three_chronological_clips(self):
        self.assertEqual(self._run("equal", 3, "loop-equal"), 0)
        job = json.loads((self.dirs["JOBS"] / "loop-equal.json").read_text(encoding="utf-8"))
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["selected_count"], 3)
        self.assertEqual(job["rendered_count"], 3)

        items = self._queue_items()
        self.assertEqual(len(items), 3)
        self.assertEqual(len({(i["start"], i["end"]) for i in items}), 3)
        self.assertEqual([i["start"] for i in items], sorted(i["start"] for i in items))
        for item in items:
            self.assertEqual(item["mode"], "equal")
            self.assertIsNone(item["viral_score"])

    def test_fallback_flag_survives_into_queue_metadata(self):
        self.segments_raw = []  # no transcript: visual windows, flagged
        self.assertEqual(self._run("viral", 3, "loop-fallback"), 0)
        items = self._queue_items()
        self.assertEqual(len(items), 3)
        for item in items:
            self.assertTrue(item.get("fallback"), "a fallback clip must be labelled")
            self.assertTrue(item.get("fallback_reason"), "the reason must be recorded")
            self.assertIsNone(item["viral_score"], "fallbacks never fabricate a score")
            self.assertTrue(
                any(reason.startswith("fallback:") for reason in item["reasons"]),
                "the queue reason keeps the fallback explanation",
            )

    def test_keep_source_preserves_the_downloaded_source(self):
        self.assertEqual(self._run("equal", 3, "loop-keep", keep_source=True), 0)
        self.assertTrue(
            (self.dirs["DOWNLOADS"] / "loop-keep.mp4").exists(),
            "--keep-source must survive the stray-file cleanup",
        )

    def test_default_cleanup_deletes_only_this_jobs_source(self):
        other = self.dirs["DOWNLOADS"] / "someone-else.mp4"
        other.write_bytes(b"0" * 256)
        self.assertEqual(self._run("equal", 3, "loop-clean"), 0)
        self.assertFalse((self.dirs["DOWNLOADS"] / "loop-clean.mp4").exists())
        self.assertFalse((self.dirs["DOWNLOADS"] / "loop-clean.wav").exists())
        self.assertTrue(other.exists(), "other jobs' files must never be touched")

    # --- Phase 8: transform variants fail independently --------------------

    def _voiceover(self, script, out_path, voice=None):
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"0" * 1024)
        return path, [{"start": 0.0, "end": 1.0, "text": "hello"}]

    def _run_transform(self, job_id: str, count: int, render, rewrite=None):
        patches = [mock.patch.object(main.transform, "synthesize_voiceover", side_effect=self._voiceover)]
        if rewrite is not None:
            patches.append(mock.patch.object(main.transform, "rewrite_script", side_effect=rewrite))
        with mock.patch.object(main.renderer, "render_clip", side_effect=render):
            for patcher in patches:
                patcher.start()
            try:
                return self._run("transform", count, job_id)
            finally:
                for patcher in reversed(patches):
                    patcher.stop()

    def _job(self, job_id: str) -> dict:
        return json.loads((self.dirs["JOBS"] / f"{job_id}.json").read_text(encoding="utf-8"))

    def test_middle_variant_failure_keeps_the_other_two(self):
        def render(source, out_path, start, end, words, cfg, **kwargs):
            if str(out_path).endswith("-t30.mp4"):
                # A crashing ffmpeg leaves a half-written file behind.
                Path(out_path).write_bytes(b"partial")
                raise main.renderer.RenderError("ffmpeg failed: simulated crash")
            return self._render(source, out_path, start, end, words, cfg, **kwargs)

        self.assertEqual(self._run_transform("tr-partial", 1, render), 0)
        job = self._job("tr-partial")
        self.assertEqual(job["status"], "done", "a failed sibling must not fail the job")
        self.assertEqual(job["selected_count"], 1)
        self.assertEqual(job["rendered_count"], 1)
        self.assertEqual(job["rendered_files"], 2)
        self.assertTrue(any("t30" in error for error in job["transform_errors"]))

        items = self._queue_items()
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertEqual(len(item["variants"]), 2, "only rendered variants are advertised")
            for variant in item["variants"]:
                self.assertFalse(variant["id"].endswith("-t30"))
                self.assertTrue((self.dirs["QUEUE"] / f"{variant['id']}.mp4").exists())
        self.assertEqual(list((self.dirs["EXPORTS"]).rglob("*-t30.mp4")), [])

    def test_all_variants_failing_marks_the_job_failed(self):
        def render(*args, **kwargs):
            raise main.renderer.RenderError("ffmpeg stalled: simulated")

        self.assertEqual(self._run_transform("tr-dead", 1, render), 1)
        job = self._job("tr-dead")
        self.assertEqual(job["status"], "error")
        self.assertIn("Transform produced no outputs", job["message"])
        self.assertEqual(self._queue_items(), [])

    def test_mock_silent_variant_is_reported_incomplete(self):
        def probe(path):
            if str(path).endswith("-t21.mp3"):
                return {"duration": 10.0, "width": 0, "height": 0, "has_audio": True}
            return {"duration": 60.0, "width": 0, "height": 0, "has_audio": True}

        with mock.patch.object(main.renderer, "probe", side_effect=probe):
            self.assertEqual(self._run_transform("tr-short", 1, self._render), 0)

        job = self._job("tr-short")
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["rendered_files"], 2, "the silent t21 variant must be dropped")
        self.assertTrue(
            any("narration incomplete" in error for error in job["transform_errors"])
        )

    def test_narration_sources_are_aggregated_on_the_job(self):
        def rewrite(text, max_words=None, **kwargs):
            rewrite.calls += 1
            source = "gemini" if rewrite.calls == 1 else "template"
            return f"A rewritten narration for piece {rewrite.calls}.", source

        rewrite.calls = 0
        self.assertEqual(self._run_transform("tr-mixed", 2, self._render, rewrite=rewrite), 0)
        job = self._job("tr-mixed")
        self.assertEqual(job["llm_source"], "mixed")
        self.assertEqual(job["llm_sources"], {"gemini": 1, "template": 1})
        self.assertTrue(job["llm_fallback"])
        self.assertEqual(job["llm_fallback_count"], 1)

        manifest = json.loads(
            (self.dirs["EXPORTS"] / "tr-mixed" / "metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["llm_source"], "mixed")
        self.assertEqual(manifest["llm_fallback_count"], 1)
        self.assertEqual(manifest["pieces_rendered"], 2)

    def test_single_source_narration_is_not_flagged_as_fallback(self):
        def rewrite(text, max_words=None, **kwargs):
            return "A rewritten narration written by the provider.", "gemini"

        self.assertEqual(self._run_transform("tr-gemini", 1, self._render, rewrite=rewrite), 0)
        job = self._job("tr-gemini")
        self.assertEqual(job["llm_source"], "gemini")
        self.assertFalse(job["llm_fallback"])
        self.assertEqual(job["llm_fallback_count"], 0)


class LogRedactionTests(unittest.TestCase):
    """Phase 6 defect B: provider exceptions must never log a credential."""

    GEMINI_KEY = "FAKE-GEMINI-KEY-0123456789"
    PIXABAY_KEY = "FAKE-PIXABAY-KEY-9876543210"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="acf-redaction-"))
        self.state = self.tmp / "state"
        self.log_file = self.state / "logs.jsonl"
        self.state.mkdir(parents=True, exist_ok=True)
        self.patches = [
            mock.patch.object(common.paths, "STATE", self.state),
            mock.patch.object(common.paths, "LOG_FILE", self.log_file),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _captured(self) -> str:
        if not self.log_file.exists():
            return ""
        return self.log_file.read_text(encoding="utf-8")

    def test_redact_secrets_masks_query_parameters(self):
        cleaned = common.redact_secrets(
            "https://example.com/v1?key=SECRET123&api_key=SECRET456&q=africa"
        )
        self.assertNotIn("SECRET123", cleaned)
        self.assertNotIn("SECRET456", cleaned)
        self.assertIn("[REDACTED]", cleaned)
        self.assertIn("q=africa", cleaned, "harmless parameters stay readable")

    def test_redact_secrets_masks_bearer_tokens(self):
        cleaned = common.redact_secrets("Authorization: Bearer sk-abcdef1234567890")
        self.assertNotIn("sk-abcdef1234567890", cleaned)
        self.assertIn("[REDACTED]", cleaned)

    def test_redact_secrets_leaves_ordinary_text_alone(self):
        message = "Rendering clip 1/3 (score 42) in monkey mode"
        self.assertEqual(common.redact_secrets(message), message)

    def test_gemini_key_travels_in_a_header_and_never_reaches_the_log(self):
        calls: dict = {}

        def fake_post(url, **kwargs):
            calls["url"] = url
            calls["kwargs"] = kwargs
            # Worst case: the provider echoes the key back in the error text.
            raise RuntimeError(
                "404 Client Error: Not Found for url: "
                f"{url}?key={self.GEMINI_KEY}"
            )

        with mock.patch.dict(
            os.environ, {"LLM_PROVIDER": "gemini", "LLM_API_KEY": self.GEMINI_KEY}
        ), mock.patch("requests.post", side_effect=fake_post):
            script, source = transform.rewrite_script("The village waited for dawn." * 5)

        self.assertEqual(source, "template", "a provider failure falls back")
        self.assertTrue(script)
        self.assertNotIn("params", calls["kwargs"], "no key in the query string")
        self.assertEqual(calls["kwargs"]["headers"]["x-goog-api-key"], self.GEMINI_KEY)
        self.assertNotIn(self.GEMINI_KEY, calls["url"])

        logged = self._captured()
        self.assertIn("LLM rewrite failed", logged)
        self.assertIn("[REDACTED]", logged)
        self.assertNotIn(self.GEMINI_KEY, logged, "the API key must never be logged")

    def test_pixabay_failure_never_logs_the_key(self):
        def fake_get(url, **kwargs):
            raise RuntimeError(
                "500 Server Error for url: "
                f"https://pixabay.com/api/videos/?key={self.PIXABAY_KEY}"
            )

        with mock.patch.dict(os.environ, {"PIXABAY_API_KEY": self.PIXABAY_KEY}), mock.patch(
            "requests.get", side_effect=fake_get
        ):
            result = broll.fetch("mermaid lagoon", dest_dir=self.tmp / "broll")

        self.assertIsNone(result)
        logged = self._captured()
        self.assertIn("Pixabay search failed", logged)
        self.assertIn("[REDACTED]", logged)
        self.assertNotIn(self.PIXABAY_KEY, logged)

    def test_structured_log_fields_are_redacted_too(self):
        common.error(
            "provider failed",
            trace=f"requests: https://x/y?token={self.GEMINI_KEY}",
        )
        logged = self._captured()
        self.assertNotIn(self.GEMINI_KEY, logged)
        self.assertIn("[REDACTED]", logged)


class DrawtextFontTests(unittest.TestCase):
    """Phase 8 defect A: the handle overlay needs an explicit font file.

    ``drawtext`` resolves its family through fontconfig, so a build with no
    default fontconfig config (the Windows gyan package ships no ``etc/fonts``)
    crashed with an access violation instead of failing cleanly.
    """

    def setUp(self):
        renderer._DRAWTEXT_FONT_WARNED = False
        self.tmp = Path(tempfile.mkdtemp(prefix="acf-fonts-"))
        self.assets = self.tmp / "assets"
        (self.assets / "fonts").mkdir(parents=True)
        self.patches = [mock.patch.object(renderer.paths, "ASSETS", self.assets)]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        renderer._DRAWTEXT_FONT_WARNED = False

    def test_env_override_wins(self):
        font = self.tmp / "brand.ttf"
        font.write_bytes(b"0")
        with mock.patch.dict(os.environ, {"ACF_DRAWTEXT_FONT": str(font)}):
            self.assertEqual(renderer._drawtext_font(), font)

    def test_project_font_asset_is_used_when_no_override(self):
        asset = self.assets / "fonts" / "brand.otf"
        asset.write_bytes(b"0")
        with mock.patch.dict(os.environ, {"ACF_DRAWTEXT_FONT": ""}):
            self.assertEqual(renderer._drawtext_font(), asset)

    def test_no_font_available_returns_none(self):
        with mock.patch.dict(os.environ, {"ACF_DRAWTEXT_FONT": ""}), mock.patch.object(
            renderer, "_DRAWTEXT_LINUX_FONTS", ()
        ), mock.patch("sys.platform", "linux"):
            self.assertIsNone(renderer._drawtext_font())

    def _graph(self, handle: str, font: Path | None) -> tuple[str, int]:
        captured: list[list[str]] = []

        def fake_run(args, timeout, stall_timeout=None):
            captured.append(list(args))
            out = Path(args[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"0" * 30_000)

        out = self.tmp / "graph" / "clip.mp4"
        source = self.tmp / "source.mp4"
        source.write_bytes(b"0")
        info = {"width": 1280, "height": 720, "duration": 30.0, "has_audio": True, "fps": "30/1"}
        with mock.patch.object(renderer, "_run_ffmpeg", side_effect=fake_run), mock.patch.object(
            renderer, "detect_face_center", return_value=None
        ), mock.patch.object(renderer, "_drawtext_font", return_value=font), mock.patch.object(
            renderer.common, "warn"
        ) as warn:
            renderer.render_clip(source, out, 0.0, 12.0, [], {}, handle=handle, info=info)
        graph = captured[0][captured[0].index("-filter_complex") + 1]
        return graph, warn.call_count

    def test_handle_filter_carries_an_explicit_fontfile(self):
        font = self.tmp / "arialbd.ttf"
        font.write_bytes(b"0")
        graph, _ = self._graph("@Jax_Clips", font)
        self.assertIn("drawtext=fontfile='", graph)
        self.assertIn("arialbd.ttf", graph)
        self.assertIn("text='@Jax_Clips'", graph)
        # Appearance is unchanged: same size, border, box and top-left spot.
        self.assertIn("fontsize=44", graph)
        self.assertIn("bordercolor=black@0.75", graph)
        self.assertIn("x=28:y=28", graph)

    def test_missing_font_skips_the_handle_and_warns_once(self):
        graph, warnings = self._graph("@Jax_Clips", None)
        self.assertNotIn("drawtext=", graph)
        self.assertEqual(warnings, 1)
        graph_again, warnings_again = self._graph("@Jax_Clips", None)
        self.assertNotIn("drawtext=", graph_again)
        self.assertEqual(warnings_again, 0, "one warning per process, not per clip")

    def test_stall_timeout_is_configurable(self):
        with mock.patch.dict(os.environ, {"ACF_RENDER_STALL_SECONDS": "42"}):
            self.assertEqual(renderer._stall_timeout(), 42.0)
        with mock.patch.dict(os.environ, {"ACF_RENDER_STALL_SECONDS": "nonsense"}):
            self.assertEqual(renderer._stall_timeout(), 180.0)
        with mock.patch.dict(os.environ, {"ACF_RENDER_STALL_SECONDS": ""}):
            self.assertEqual(renderer._stall_timeout(), 180.0)


class _FakeFfmpeg:
    """Minimal ``Popen`` stand-in: emits progress lines, then optionally hangs."""

    def __init__(self, lines: list[str], hang_after: int | None = None):
        self._lines = list(lines)
        self._hang_after = hang_after
        self._killed = __import__("threading").Event()
        self.returncode = None
        self.stdout = self._reader()

    def _reader(self):
        for index, line in enumerate(self._lines):
            if self._hang_after is not None and index >= self._hang_after:
                self._killed.wait(15)
                return
            yield line
        if self._hang_after is not None:
            self._killed.wait(15)
        self.returncode = 0

    def kill(self):
        self.returncode = -9
        self._killed.set()

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class FfmpegWatchdogTests(unittest.TestCase):
    """Phase 8 defect C: a silent render is a stall, not a slow encode."""

    def _run(self, fake, timeout=30.0, stall=1.0):
        with mock.patch.object(renderer.subprocess, "Popen", return_value=fake), mock.patch.object(
            renderer, "which_ffmpeg", return_value="ffmpeg"
        ):
            return renderer._run_ffmpeg(["-i", "in.mp4", "out.mp4"], timeout, stall_timeout=stall)

    def test_progress_updates_complete_normally(self):
        fake = _FakeFfmpeg(
            ["frame=1\n", "progress=continue\n", "frame=2\n", "progress=end\n"]
        )
        self._run(fake)  # must not raise
        self.assertEqual(fake.returncode, 0)

    def test_silent_process_is_reported_as_a_stall(self):
        fake = _FakeFfmpeg(["frame=7\n", "progress=continue\n"], hang_after=1)
        with self.assertRaises(renderer.RenderError) as caught:
            self._run(fake, stall=1.0)
        message = str(caught.exception)
        self.assertIn("ffmpeg stalled", message)
        self.assertIn("no progress for", message)
        self.assertIn("last frame 7", message)
        self.assertNotIn("timed out", message)

    def test_finalizing_process_is_not_killed_as_stalled(self):
        # progress=end then silence is normal muxing, not a hang.
        fake = _FakeFfmpeg(["frame=9\n", "progress=continue\n", "frame=10\n", "progress=end\n"])
        self._run(fake, stall=0.5)
        self.assertEqual(fake.returncode, 0)

    def test_failed_render_deletes_partial_output_and_thumbnail(self):
        tmp = Path(tempfile.mkdtemp(prefix="acf-partial-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        source = tmp / "source.mp4"
        source.write_bytes(b"0")
        out = tmp / "clip.mp4"
        thumb = tmp / "clip.jpg"
        info = {"width": 1280, "height": 720, "duration": 30.0, "has_audio": True, "fps": "30/1"}

        def fake_run(args, timeout, stall_timeout=None):
            Path(args[-1]).write_bytes(b"0" * 4_000)  # half-muxed leftover
            thumb.write_bytes(b"0" * 64)
            raise renderer.RenderError("ffmpeg stalled: no progress for 180s")

        with mock.patch.object(renderer, "_run_ffmpeg", side_effect=fake_run), mock.patch.object(
            renderer, "detect_face_center", return_value=None
        ):
            with self.assertRaises(renderer.RenderError):
                renderer.render_clip(
                    source, out, 0.0, 12.0, [], {}, info=info, thumb_path=thumb
                )
        self.assertFalse(out.exists(), "partial video must be removed")
        self.assertFalse(thumb.exists(), "partial thumbnail must be removed")


class GeminiModelTests(unittest.TestCase):
    """Phase 8 defect B: a callable model, and visible template fallback."""

    TEXT = (
        "In the village the elders gathered at midnight and told the children "
        "a story about the river that never sleeps."
    )

    def _response(self):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": self.TEXT}]}}]
        }
        return response

    def test_configured_model_is_used_for_generation(self):
        with mock.patch.dict(
            os.environ,
            {"LLM_PROVIDER": "gemini", "LLM_API_KEY": "fake-key", "LLM_MODEL": "gemini-test-model"},
        ), mock.patch("requests.post", return_value=self._response()) as post:
            script, source = transform.rewrite_script("The village waited for dawn. " * 6)
        url = post.call_args.args[0]
        self.assertIn("/models/gemini-test-model:generateContent", url)
        self.assertEqual(source, "gemini")
        self.assertIn("elders", script)

    def test_default_model_is_the_verified_flash_model(self):
        env = {"LLM_PROVIDER": "gemini", "LLM_API_KEY": "fake-key"}
        with mock.patch.dict(os.environ, env), mock.patch.dict(
            os.environ, {"LLM_MODEL": ""}
        ), mock.patch("requests.post", return_value=self._response()) as post:
            script, source = transform.rewrite_script("The village waited for dawn. " * 6)
        self.assertEqual(transform.DEFAULT_GEMINI_MODEL, "gemini-3.5-flash-lite")
        self.assertIn(f"/models/{transform.DEFAULT_GEMINI_MODEL}:", post.call_args.args[0])
        self.assertEqual(source, "gemini")

    def test_provider_outage_falls_back_to_template(self):
        with mock.patch.dict(
            os.environ,
            {"LLM_PROVIDER": "gemini", "LLM_API_KEY": "fake-key", "LLM_MODEL": "gemini-test-model"},
        ), mock.patch("requests.post", side_effect=RuntimeError("503 Server Error: high demand")):
            script, source = transform.rewrite_script("The village waited for dawn. " * 6)
        self.assertEqual(source, "template")
        self.assertTrue(script, "the template keeps the job alive")

    def test_no_key_never_calls_the_provider(self):
        with mock.patch.dict(
            os.environ,
            {"LLM_PROVIDER": "gemini", "LLM_API_KEY": "", "LLM_MODEL": ""}
        ), mock.patch("requests.post", side_effect=AssertionError("provider called")):
            script, source = transform.rewrite_script("The village waited for dawn. " * 6)
        self.assertEqual(source, "template")
        self.assertTrue(script)

    def test_retired_2_5_is_filtered_from_the_effective_chain(self):
        with mock.patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "gemini",
                "LLM_API_KEY": "fake-key",
                "LLM_MODEL": "gemini-2.5-flash",
                "LLM_MODEL_FALLBACKS": "",
            },
        ), mock.patch("requests.post", return_value=self._response()) as post:
            script, source = transform.rewrite_script("The village waited for dawn. " * 6)

        self.assertEqual(source, "gemini")
        self.assertIn("elders", script)
        self.assertEqual(post.call_count, 1)
        self.assertIn("/models/gemini-3.5-flash-lite:", post.call_args.args[0])
        self.assertNotIn("gemini-2.5-flash", transform._gemini_model_candidates())
        self.assertEqual(transform.LAST_MODEL, "gemini-3.5-flash-lite")


if __name__ == "__main__":
    unittest.main(verbosity=2)
