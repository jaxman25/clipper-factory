"""Task A (Phase 9): a failed TTS attempt must not leave its own MP3 behind.

Everything here runs inside a throwaway temp directory; no real exports, queue
records or Phase 8 evidence are read or written.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import main

SEGMENTS = [
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


class TtsCleanupTests(unittest.TestCase):
    """Failed voiceovers are removed; successful and sibling audio is kept."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="acf-tts-cleanup-"))
        self.queue = self.tmp / "queue"
        self.jobs = self.tmp / "jobs"
        self.job_dir = self.tmp / "export"
        for directory in (self.queue, self.jobs, self.job_dir):
            directory.mkdir(parents=True)
        self.voice = self._voice_ok
        self.warnings: list[str] = []
        self.patches = [
            mock.patch.object(main.paths, "QUEUE", self.queue),
            mock.patch.object(main.paths, "JOBS", self.jobs),
            mock.patch.object(main.renderer, "probe", side_effect=self._probe),
            mock.patch.object(main.renderer, "render_clip", side_effect=self._render),
            mock.patch.object(
                main.transform,
                "rewrite_script",
                side_effect=lambda text, max_words=None: (
                    ("The spirit warned the village at midnight. " * 40).strip(),
                    "gemini",
                ),
            ),
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
                main.transform,
                "synthesize_voiceover",
                side_effect=lambda script, out_path, voice=None: self.voice(
                    script, out_path
                ),
            ),
            mock.patch.object(main.broll_mod, "fetch", return_value=None),
            mock.patch.object(
                main.common,
                "warn",
                side_effect=lambda message, **fields: self.warnings.append(message),
            ),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------- fixtures
    @staticmethod
    def _probe(path):
        # Source probes are short; a valid voiceover must cover its target.
        if str(path).lower().endswith(".mp3"):
            return {"duration": 60.0}
        return {"duration": 10.0}

    @staticmethod
    def _voice_ok(script, out_path):
        path = Path(out_path)
        path.write_bytes(b"ID3" + b"0" * 800)
        return path, [{"start": 0.0, "end": 1.0, "text": "word"}]

    def _voice_writes(self, payload: bytes, error: str):
        """A TTS attempt that writes ``payload`` and then raises like edge-tts."""

        def side_effect(script, out_path):
            Path(out_path).write_bytes(payload)
            raise RuntimeError(error)

        return side_effect

    def _voice_failing_piece(self, piece_tag: str, payload: bytes):
        """Succeed normally except for one piece, which fails after writing."""

        def side_effect(script, out_path):
            path = Path(out_path)
            if f"-{piece_tag}-" in path.name:
                path.write_bytes(payload)
                raise RuntimeError("edge-tts produced no audio (network blocked?)")
            return self._voice_ok(script, out_path)

        return side_effect

    @staticmethod
    def _render(source, out_path, start, end, words, cfg, **kwargs):
        Path(out_path).write_bytes(b"0" * 30000)
        return {
            "duration": kwargs.get("target_duration") or (end - start),
            "width": 1080,
            "height": 1920,
            "face_detected": False,
            "speed": 1.15,
            "broll": None,
        }

    def _run(self, job_id: str = "job-tts"):
        job = main.Job(job_id, "https://example.com/v", 3, "transform")
        try:
            items, pieces = main._render_transform(
                source=Path("source.mp4"),
                audio=Path("audio.wav"),
                info={"width": 1920, "height": 1080, "has_audio": True},
                duration=1800.0,
                segments_raw=SEGMENTS,
                language="en",
                job=job,
                cfg={"clip_min_seconds": 30, "clip_max_seconds": 45},
                job_id=job_id,
                job_dir=self.job_dir,
                broll_path=None,
                hashtags="#tag",
                source_url="https://example.com/v",
                count=3,
                mode="transform",
            )
        except main.JobError as exc:
            return job, [], 0, exc
        return job, items, pieces, None

    # ---------------------------------------------------------------- tests
    def test_zero_byte_mp3_is_removed_when_tts_fails(self):
        self.voice = self._voice_writes(b"", "edge-tts produced no audio (network blocked?)")

        job, items, pieces, error = self._run("job-tts-zero")

        self.assertIsInstance(error, main.JobError)
        self.assertEqual(items, [])
        self.assertEqual(pieces, 0)
        self.assertEqual(list(self.job_dir.glob("*.mp3")), [])
        self.assertIn("voiceover unavailable", job.data["transform_errors"][0])

    def test_partial_mp3_is_removed_and_only_the_failed_output(self):
        self.voice = self._voice_failing_piece("02", b"\xff\xfb" + b"0" * 120)

        job, items, pieces, error = self._run("job-tts-partial")

        self.assertIsNone(error)  # other pieces still rendered
        self.assertEqual(pieces, 2)
        self.assertEqual(len(items), 6)
        # Piece 2's three failed attempts left nothing; pieces 1 and 3 kept
        # exactly their own audio.
        self.assertEqual(
            sorted(p.name for p in self.job_dir.glob("*.mp3")),
            [
                "job-tts-partial-01-t21.mp3",
                "job-tts-partial-01-t30.mp3",
                "job-tts-partial-01-t59.mp3",
                "job-tts-partial-03-t21.mp3",
                "job-tts-partial-03-t30.mp3",
                "job-tts-partial-03-t59.mp3",
            ],
        )
        self.assertEqual(len(job.data["transform_errors"]), 3)

    def test_successful_voiceover_is_retained(self):
        job, items, pieces, error = self._run("job-tts-ok")

        self.assertIsNone(error)
        self.assertEqual(pieces, 3)
        self.assertEqual(len(items), 9)
        self.assertEqual(len(list(self.job_dir.glob("*.mp3"))), 9)
        self.assertTrue(all(p.stat().st_size > 0 for p in self.job_dir.glob("*.mp3")))
        self.assertEqual(job.data["transform_errors"], [])

    def test_another_pieces_valid_mp3_is_untouched(self):
        self.voice = self._voice_failing_piece("02", b"")
        # A file from an earlier job that still lives in this directory.
        other = self.job_dir / "previous-job-01-t59.mp3"
        other.write_bytes(b"ID3" + b"1" * 4096)
        before = (other.stat().st_size, other.read_bytes())

        self._run("job-tts-sibling")

        self.assertTrue(other.exists())
        self.assertEqual((other.stat().st_size, other.read_bytes()), before)

    def test_cleanup_failure_keeps_tts_error_visible_and_logs_cleanup(self):
        self.voice = self._voice_writes(b"", "edge-tts produced no audio (network blocked?)")
        target = "job-tts-locked-01-t21.mp3"
        real_unlink = Path.unlink

        def refuse(self, *args, **kwargs):
            if self.name == target:
                raise OSError("file held by another process")
            return real_unlink(self, *args, **kwargs)

        with mock.patch.object(Path, "unlink", refuse):
            job, items, pieces, error = self._run("job-tts-locked")

        self.assertIsInstance(error, main.JobError)
        self.assertIn(
            "voiceover unavailable (edge-tts produced no audio",
            job.data["transform_errors"][0],
        )
        self.assertTrue(
            any(
                "cleanup failed for job-tts-locked-01-t21.mp3" in message
                and "file held by another process" in message
                for message in self.warnings
            ),
            self.warnings,
        )


if __name__ == "__main__":
    unittest.main()
