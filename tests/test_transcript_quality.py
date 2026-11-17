"""Stage 3A transcript-evidence tests.

These tests are hermetic: faster-whisper is mocked, no audio is read, and the
only filesystem writes go to a temporary ACF exports directory.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend import transcript_quality  # noqa: E402
import backend.main as main  # noqa: E402


class FakeJob:
    def __init__(self, job_id: str = "job-evidence") -> None:
        self.id = job_id
        self.data: dict = {}

    def update(self, **extra) -> None:
        self.data.update(extra)


def make_segment(**overrides):
    values = {
        "id": 0,
        "seek": 0,
        "start": 0.0,
        "end": 2.0,
        "text": "Hello world.",
        "avg_logprob": -0.2,
        "no_speech_prob": 0.01,
        "compression_ratio": 1.1,
        "temperature": 0.0,
        "tokens": [1, 2],
        "words": [
            SimpleNamespace(start=0.0, end=1.0, word="Hello", probability=0.91),
            SimpleNamespace(start=1.0, end=2.0, word="world.", probability=0.83),
        ],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TranscriptEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="acf-evidence-"))
        self.exports = self.tmp / "exports"
        self.model = mock.Mock()
        self.info = SimpleNamespace(
            duration=10.0,
            duration_after_vad=8.5,
            language="en",
            language_probability=0.98,
            all_language_probs=[("en", 0.98), ("fr", 0.01)],
        )
        self.patchers = [
            mock.patch.object(main, "WHISPER_DIR", self.tmp / "models"),
            mock.patch.object(main.paths, "EXPORTS", self.exports),
            mock.patch("faster_whisper.WhisperModel", return_value=self.model),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, segments, info=None, language="en"):
        self.model.transcribe.return_value = (iter(segments), info or self.info)
        job = FakeJob()
        result = main.transcribe(Path("audio.wav"), job, language=language)
        return job, result

    def _sidecar(self, job_id="job-evidence"):
        path = self.exports / job_id / "transcript.json"
        return path, json.loads(path.read_text(encoding="utf-8"))

    def test_segment_metrics_and_word_probabilities_survive(self):
        segment = make_segment()
        job, (segments, detected, total) = self._run([segment])

        self.assertEqual(detected, "en")
        self.assertEqual(total, 10.0)
        self.assertEqual(segments[0]["start"], 0.0)
        self.assertEqual(segments[0]["end"], 2.0)
        self.assertEqual(segments[0]["text"], "Hello world.")
        self.assertEqual(segments[0]["avg_logprob"], -0.2)
        self.assertEqual(segments[0]["no_speech_prob"], 0.01)
        self.assertEqual(segments[0]["compression_ratio"], 1.1)
        self.assertEqual(segments[0]["temperature"], 0.0)
        self.assertEqual(segments[0]["tokens"], [1, 2])
        self.assertEqual(
            segments[0]["words"],
            [
                {"start": 0.0, "end": 1.0, "word": "Hello", "probability": 0.91},
                {"start": 1.0, "end": 2.0, "word": "world.", "probability": 0.83},
            ],
        )

        _, sidecar = self._sidecar()
        self.assertEqual(sidecar["segments"][0]["avg_logprob"], -0.2)
        self.assertEqual(sidecar["segments"][0]["words"][0]["probability"], 0.91)
        self.assertEqual(sidecar["text"], "Hello world.")
        self.assertEqual(job.data["transcript_sidecar"], "transcript.json")
        self.assertIn("transcript_quality", job.data)

    def test_transcription_language_and_vad_fields_are_preserved(self):
        _, _ = self._run([make_segment()])

        _, sidecar = self._sidecar()
        self.assertEqual(sidecar["language"], "en")
        self.assertEqual(sidecar["language_probability"], 0.98)
        self.assertEqual(sidecar["language_requested"], "en")
        self.assertEqual(sidecar["duration"], 10.0)
        self.assertEqual(sidecar["duration_after_vad"], 8.5)
        self.assertEqual(
            sidecar["all_language_probs"], [["en", 0.98], ["fr", 0.01]]
        )
        self.assertEqual(sidecar["quality"]["speech_coverage"]["ratio"], 0.85)
        self.assertEqual(sidecar["quality"]["language"]["margin"], 0.97)

    def test_missing_and_non_finite_metrics_stay_null(self):
        segment = make_segment(
            avg_logprob=float("nan"),
            no_speech_prob=float("inf"),
            compression_ratio=None,
            temperature=None,
            tokens=None,
            words=[
                SimpleNamespace(
                    start=0.0, end=1.0, word="Hello", probability=float("nan")
                )
            ],
        )
        info = SimpleNamespace(
            duration=10.0,
            language="en",
            language_probability=None,
        )
        _, (segments, _, _) = self._run([segment], info=info)

        self.assertIsNone(segments[0]["avg_logprob"])
        self.assertIsNone(segments[0]["no_speech_prob"])
        self.assertIsNone(segments[0]["compression_ratio"])
        self.assertIsNone(segments[0]["temperature"])
        self.assertIsNone(segments[0]["tokens"])
        self.assertIsNone(segments[0]["words"][0]["probability"])

        _, sidecar = self._sidecar()
        self.assertIsNone(sidecar["duration_after_vad"])
        self.assertIsNone(sidecar["all_language_probs"])
        self.assertIsNone(sidecar["quality"]["speech_coverage"])
        self.assertIn("duration_after_vad", sidecar["quality"]["missing_metrics"])
        self.assertIn("language_probability", sidecar["quality"]["missing_metrics"])
        # The finally serialized file must be strict JSON, not Python NaN/Infinity.
        json.dumps(sidecar, allow_nan=False)

    def test_sidecar_is_safe_and_contains_no_source_or_environment_data(self):
        _, _ = self._run([make_segment()])
        path, sidecar = self._sidecar()

        self.assertTrue(path.exists())
        self.assertNotIn("source_url", sidecar)
        self.assertNotIn("url", sidecar)
        self.assertNotIn("WHISPER", json.dumps(sidecar))
        self.assertEqual(sidecar["job_id"], "job-evidence")
        self.assertEqual(sidecar["version"], 1)

    def test_legacy_job_document_still_loads(self):
        jobs = self.tmp / "jobs"
        jobs.mkdir()
        legacy = {"id": "old-job", "status": "done", "clips": []}
        (jobs / "old-job.json").write_text(
            json.dumps(legacy), encoding="utf-8"
        )
        with mock.patch.object(main.paths, "JOBS", jobs):
            self.assertEqual(main.read_job("old-job"), legacy)


class QualitySummaryTests(unittest.TestCase):
    def test_repetition_and_metric_summaries_are_reported_without_thresholds(self):
        segments = [
            {
                "start": 0.0,
                "end": 2.0,
                "text": "The spirit warned the village.",
                "avg_logprob": -0.2,
                "no_speech_prob": 0.1,
                "compression_ratio": 1.2,
                "temperature": 0.0,
                "words": [{"probability": 0.9}],
            },
            {
                "start": 2.0,
                "end": 4.0,
                "text": "The spirit warned the village.",
                "avg_logprob": -0.4,
                "no_speech_prob": 0.2,
                "compression_ratio": 1.3,
                "temperature": 0.2,
                "words": [{"probability": 0.7}],
            },
        ]
        summary = transcript_quality.summarize_transcript(
            segments,
            duration=10.0,
            duration_after_vad=9.0,
            language_probability=0.9,
            all_language_probs=[("en", 0.9), ("fr", 0.05)],
        )

        self.assertEqual(summary["segment_count"], 2)
        self.assertEqual(summary["word_count"], 2)
        self.assertAlmostEqual(summary["avg_logprob"]["mean"], -0.3)
        self.assertEqual(summary["no_speech_prob"]["max"], 0.2)
        self.assertEqual(summary["compression_ratio"]["max"], 1.3)
        self.assertEqual(summary["word_probability"]["count"], 2)
        self.assertEqual(summary["speech_coverage"]["ratio"], 0.9)
        self.assertEqual(summary["repeated_text"]["duplicate_segments"], 1)
        self.assertEqual(summary["repeated_text"]["longest_consecutive_run"], 2)
        self.assertGreater(summary["repeated_text"]["repeated_3gram_ratio"], 0)
        self.assertEqual(summary["missing_metrics"], [])
        # Stage 3A must not classify or reject.
        self.assertNotIn("quality", summary)
        self.assertNotIn("publishable", summary)

    def test_empty_transcript_has_explicit_missing_metrics(self):
        summary = transcript_quality.summarize_transcript([])
        self.assertEqual(summary["segment_count"], 0)
        self.assertIsNone(summary["speech_coverage"])
        self.assertIn("avg_logprob", summary["missing_metrics"])
        self.assertIn("word_probability", summary["missing_metrics"])


if __name__ == "__main__":
    unittest.main()
