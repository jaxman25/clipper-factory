"""Stage 3B tests: quality-aware Viral, Equal and Transform selection.

Everything here is mocked and side-effect free.  No Whisper model, ffmpeg,
network provider, scheduler or queue record is touched.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend import quality, selection, viral  # noqa: E402
import backend.main as main  # noqa: E402


GOOD_TEXT = "The spirit warned the village at midnight and the elders listened."


def raw_segment(start: float, end: float, text: str = GOOD_TEXT, **metrics) -> dict:
    values = {
        "avg_logprob": -0.20,
        "no_speech_prob": 0.02,
        "compression_ratio": 1.10,
        "temperature": 0.0,
    }
    values.update(metrics)
    return {
        "start": start,
        "end": end,
        "text": text,
        "words": [
            {
                "start": start,
                "end": end,
                "word": word,
                "probability": 0.94,
            }
            for word in text.split()
        ],
        **values,
    }


def make_good_segments(duration: float, seg: float = 10.0) -> list[viral.Segment]:
    raw = []
    for index, start in enumerate(range(0, int(duration), int(seg))):
        text = f"The spirit warned the village at midnight in story {index}."
        raw.append(raw_segment(float(start), float(start + seg), text))
    return viral.build_segments(raw)


def assessment_with(status: str) -> dict:
    return {
        "status": status,
        "available": True,
        "provisional": True,
        "reasons": [f"{status} fixture"],
        "warnings": [],
        "evidence": {},
        "missing_metrics": [],
        "language_confidence_used": False,
    }


def candidate(start: float, end: float, score: float, status: str) -> viral.Candidate:
    return viral.Candidate(
        start=start,
        end=end,
        text=GOOD_TEXT,
        words=[],
        score=score,
        reasons=[f"{status} fixture"],
        quality=assessment_with(status),
    )


class QualityAssessmentTests(unittest.TestCase):
    def test_good_candidate_with_strong_evidence(self):
        result = quality.assess_segments(viral.build_segments([raw_segment(0, 40)]))
        self.assertEqual(result["status"], "good")
        self.assertTrue(result["available"])
        self.assertEqual(result["warnings"], [])
        self.assertFalse(result["language_confidence_used"])

    def test_poor_candidate_needs_multiple_independent_warnings(self):
        raw = raw_segment(
            0,
            40,
            avg_logprob=-2.1,
            no_speech_prob=0.96,
            compression_ratio=3.6,
            temperature=1.0,
        )
        raw["words"] = [
            {"start": 0, "end": 1, "word": "word", "probability": 0.10}
        ]
        result = quality.assess_segments(viral.build_segments([raw]))
        self.assertEqual(result["status"], "poor")
        codes = {warning["code"] for warning in result["warnings"]}
        self.assertIn("low_avg_logprob", codes)
        self.assertIn("high_no_speech_prob", codes)
        self.assertIn("high_compression_ratio", codes)
        self.assertGreaterEqual(len(codes), 2)
        self.assertTrue(all("message" in warning for warning in result["warnings"]))

    def test_mixed_evidence_is_review_not_poor(self):
        result = quality.assess_segments(
            viral.build_segments([raw_segment(0, 40, avg_logprob=-1.1)])
        )
        self.assertEqual(result["status"], "review")
        self.assertTrue(result["available"])
        self.assertTrue(result["reasons"])

    def test_missing_optional_metrics_are_not_poor(self):
        raw = raw_segment(0, 40)
        raw.pop("words")
        raw.pop("compression_ratio")
        raw.pop("temperature")
        result = quality.assess_segments(viral.build_segments([raw]))
        self.assertNotEqual(result["status"], "poor")
        self.assertIn("word_probability", result["missing_metrics"])
        self.assertIn("compression_ratio", result["missing_metrics"])
        self.assertIn("missing", " ".join(result["reasons"]).lower())

    def test_legitimate_repeated_phrases_are_not_rejected_on_repetition_alone(self):
        raw = [
            raw_segment(float(start), float(start + 10), "I do. I do. I do.")
            for start in range(0, 40, 10)
        ]
        result = quality.assess_segments(viral.build_segments(raw))
        codes = {warning["code"] for warning in result["warnings"]}
        self.assertIn("repetition", codes)
        self.assertEqual(result["status"], "review")
        self.assertNotEqual(result["status"], "poor")


class ViralQualityTests(unittest.TestCase):
    def test_viral_selection_prefers_good_over_review(self):
        candidates = [
            candidate(0, 40, 90, "good"),
            candidate(100, 140, 99, "review"),
        ]
        with mock.patch.object(selection.viral, "find_candidates", return_value=candidates):
            selected, diag = selection.select_viral(
                [viral.Segment(0, 1, "seed")], [], None, 1, 30, 45, 600
            )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].quality_status, "good")
        self.assertEqual(diag["quality"]["good"], 1)
        self.assertEqual(diag["quality"]["review"], 1)

    def test_viral_selection_rejects_poor_candidates(self):
        candidates = [
            candidate(0, 40, 100, "poor"),
            candidate(100, 140, 99, "poor"),
        ]
        with mock.patch.object(selection.viral, "find_candidates", return_value=candidates):
            selected, diag = selection.select_viral(
                [viral.Segment(0, 1, "seed")], [], None, 2, 30, 45, 600
            )
        self.assertEqual(selected, [])
        self.assertEqual(diag["shortfall"], 2)
        self.assertEqual(diag["quality_rejected"], 2)

    def test_requested_count_shortfall_is_honest(self):
        candidates = [candidate(0, 40, 90, "good"), candidate(100, 140, 80, "good")]
        with mock.patch.object(selection.viral, "find_candidates", return_value=candidates):
            selected, diag = selection.select_viral(
                [viral.Segment(0, 1, "seed")], [], None, 5, 30, 45, 600
            )
        self.assertEqual(len(selected), 2)
        self.assertEqual(diag["requested"], 5)
        self.assertEqual(diag["shortfall"], 3)


class EqualQualityTests(unittest.TestCase):
    def test_equal_slices_preserve_interval_boundaries(self):
        duration = 600.0
        segments = make_good_segments(duration)
        selected, diag = selection.select_equal(segments, duration, 3, 30, 45)
        self.assertEqual(len(selected), 3)
        width = duration / 3
        for item in selected:
            self.assertGreaterEqual(item.start, (int(item.start // width)) * width - 0.01)
            high = min(duration, (int(item.start // width) + 1) * width)
            self.assertLessEqual(item.end, high + 0.01)
            self.assertNotEqual(item.quality_status, "poor")
        self.assertEqual(
            [item.start for item in selected],
            sorted(item.start for item in selected),
        )
        for first, second in zip(selected, selected[1:]):
            self.assertLessEqual(first.end, second.start + 0.01)

    def test_equal_slices_prefer_good_over_review_inside_an_interval(self):
        segments = viral.build_segments(
            [
                raw_segment(
                    float(start),
                    float(start + 10),
                    ("Review" if start < 50 else "Good")
                    + f" candidate {start}.",
                )
                for start in range(0, 100, 10)
            ]
        )

        def fake_assess(window, text=None):
            status = "review" if "review" in (text or "").lower() else "good"
            return assessment_with(status)

        with mock.patch.object(
            selection.quality, "assess_segments", side_effect=fake_assess
        ), mock.patch.object(selection.viral, "_score_text", return_value=(1.0, [])):
            selected, _ = selection.select_equal(segments, 100.0, 1, 30, 45)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].quality_status, "good")

    def test_equal_slices_report_intervals_with_no_acceptable_candidate(self):
        duration = 300.0
        segments = viral.build_segments(
            [
                *[
                    raw_segment(float(start), float(start + 10), f"Good interval {start}.")
                    for start in range(0, 90, 10)
                ],
                *[
                    raw_segment(
                        float(start),
                        float(start + 10),
                        f"Bad interval {start}.",
                        avg_logprob=-2.2,
                        no_speech_prob=0.97,
                        compression_ratio=3.7,
                        temperature=1.0,
                    )
                    for start in range(100, 190, 10)
                ],
            ]
        )
        selected, diag = selection.select_equal(segments, duration, 3, 30, 45)
        self.assertEqual(len(selected), 1)
        empty = [row for row in diag["intervals"] if not row["selected"]]
        self.assertEqual(len(empty), 2)
        self.assertIn("poor-quality", empty[0]["reason"])
        self.assertIn("no complete speech", empty[1]["reason"])
        self.assertGreaterEqual(diag["quality_rejected"], 1)
        self.assertTrue(all(item.start < 100 for item in selected))


class TransformQualityTests(unittest.TestCase):
    def test_transform_selection_reports_poor_windows(self):
        segments = viral.build_segments(
            [
                raw_segment(
                    float(start),
                    float(start + 10),
                    f"Unreliable piece {start}.",
                    avg_logprob=-2.2,
                    no_speech_prob=0.97,
                    compression_ratio=3.7,
                    temperature=1.0,
                )
                for start in range(0, 600, 10)
            ]
        )
        selected, diag = selection.select_transform(segments, [], None, 600, 2)
        self.assertEqual(selected, [])
        self.assertGreater(diag["quality_rejected"], 0)
        self.assertEqual(diag["shortfall"], 2)
        self.assertTrue(diag["quality_rejections"])

    def test_transform_refuses_to_rewrite_a_poor_candidate(self):
        tmp = Path(tempfile.mkdtemp(prefix="acf-quality-transform-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        queue = tmp / "queue"
        queue.mkdir()
        poor = candidate(0, 60, 50, "poor")
        piece = selection.Selected(poor)
        report = {
            "fallback": 0,
            "quality": {"good": 0, "review": 0, "poor": 1},
            "quality_rejected": 1,
            "quality_rejections": [],
        }
        job = main.Job("quality-refuse", "https://example.com/v", 1, "transform")
        with mock.patch.object(main.paths, "QUEUE", queue), mock.patch.object(
            main.selection, "select_transform", return_value=([piece], report)
        ), mock.patch.object(
            main.viral, "compute_rms", return_value=[]
        ), mock.patch.object(
            main.transform, "rewrite_script"
        ) as rewrite:
            with self.assertRaises(main.JobError):
                main._render_transform(
                    source=Path("source.mp4"),
                    audio=Path("audio.wav"),
                    info={},
                    duration=600.0,
                    segments_raw=[raw_segment(0, 60)],
                    language="en",
                    job=job,
                    cfg={"clip_min_seconds": 30, "clip_max_seconds": 45},
                    job_id="quality-refuse",
                    job_dir=tmp,
                    broll_path=None,
                    hashtags="#test",
                    source_url="https://example.com/v",
                    count=1,
                    mode="transform",
                )
        rewrite.assert_not_called()
        self.assertTrue(any("poor transcript quality" in error for error in job.data["transform_errors"]))


class LegacyQualityTests(unittest.TestCase):
    def test_legacy_candidates_explicitly_report_unavailable_evidence(self):
        raw = [{"start": 0.0, "end": 40.0, "text": GOOD_TEXT, "words": []}]
        segments = viral.build_segments(raw)
        assessment = quality.assess_segments(segments)
        self.assertEqual(assessment["status"], "review")
        self.assertFalse(assessment["available"])
        self.assertIn("word_probability", assessment["missing_metrics"])

    def test_existing_selection_behavior_is_preserved_without_evidence(self):
        raw = [
            {
                "start": float(start),
                "end": float(start + 10),
                "text": f"The spirit warned the village in old job {start}.",
                "words": [],
            }
            for start in range(0, 600, 10)
        ]
        segments = viral.build_segments(raw)
        selected, diag = selection.select_viral(
            segments, [], None, 3, 30, 45, 600
        )
        self.assertEqual(len(selected), 3)
        self.assertEqual(diag["shortfall"], 0)
        self.assertTrue(all(item.quality_status == "review" for item in selected))
        self.assertFalse(any(item.fallback for item in selected))


if __name__ == "__main__":
    unittest.main()
