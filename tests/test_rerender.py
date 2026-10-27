"""Regression tests for backend/rerender.py (the manual clip editor).

Generates a short test video with FFmpeg, then exercises the re-render
function and CLI: correct cut duration, atomic replacement of an existing
file, thumbnail regeneration, validation errors, and temp-file cleanup.

Run with:
    python -m unittest discover -s tests -p "test_*.py" -v
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "backend" / "rerender.py"
sys.path.insert(0, str(REPO_ROOT))

from backend import rerender  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _duration(path: Path) -> float:
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class RerenderTests(unittest.TestCase):
    workdir = Path()

    @classmethod
    def setUpClass(cls) -> None:
        cls.workdir = Path(tempfile.mkdtemp(prefix="acf-rerender-"))
        cls.source = cls.workdir / "source.mp4"
        subprocess.run(
            [
                FFMPEG, "-y", "-v", "error",
                "-f", "lavfi", "-i", "testsrc=duration=10:size=320x240:rate=30",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                str(cls.source),
            ],
            check=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.workdir, ignore_errors=True)

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(dir=self.workdir))
        self.out = self.dir / "clip.mp4"

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def leftovers(self) -> list[Path]:
        """Anything in the per-test dir other than the expected outputs."""
        return [p for p in self.dir.iterdir() if p.name not in {"clip.mp4", "clip.jpg"}]

    @unittest.skipUnless(FFPROBE, "ffprobe not installed")
    def test_cut_matches_requested_duration(self) -> None:
        rerender.rerender_clip(self.source, 2, 6, self.out)
        self.assertTrue(self.out.exists())
        self.assertAlmostEqual(_duration(self.out), 4.0, delta=0.2)

    @unittest.skipUnless(FFPROBE, "ffprobe not installed")
    def test_cut_replaces_existing_output(self) -> None:
        self.out.write_bytes(b"stale partial render")
        rerender.rerender_clip(self.source, 0, 3, self.out)
        self.assertGreater(self.out.stat().st_size, len(b"stale partial render"))
        self.assertAlmostEqual(_duration(self.out), 3.0, delta=0.2)
        self.assertEqual(self.leftovers(), [], "temp files left behind")

    @unittest.skipUnless(FFPROBE, "ffprobe not installed")
    def test_thumbnail_regenerated_from_new_cut(self) -> None:
        thumb = self.dir / "clip.jpg"
        thumb.write_bytes(b"stale-thumb")
        rerender.rerender_clip(self.source, 1, 5, self.out, thumb=thumb)
        data = thumb.read_bytes()
        self.assertNotEqual(data, b"stale-thumb")
        self.assertTrue(data.startswith(b"\xff\xd8"), "not a JPEG")
        self.assertGreater(len(data), 100)
        self.assertEqual(self.leftovers(), [])

    def test_thumbnail_failure_is_not_fatal(self) -> None:
        # A thumb path whose parent is a regular file cannot be created; the
        # video render must still succeed (thumbnail is cosmetic).
        blocker = self.dir / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        result = rerender.rerender_clip(
            self.source, 1, 3, self.out, thumb=blocker / "clip.jpg"
        )
        self.assertEqual(result, self.out)
        self.assertTrue(self.out.exists())

    def test_missing_source_raises_and_creates_nothing(self) -> None:
        with self.assertRaises(FileNotFoundError):
            rerender.rerender_clip(self.dir / "missing.mp4", 0, 2, self.out)
        self.assertFalse(self.out.exists())
        self.assertEqual(list(self.dir.glob("clip*")), [])

    def test_invalid_ranges_rejected(self) -> None:
        with self.assertRaises(ValueError):
            rerender.rerender_clip(self.source, 5, 5, self.out)  # end <= start
        with self.assertRaises(ValueError):
            rerender.rerender_clip(self.source, -1, 3, self.out)  # negative start
        self.assertFalse(self.out.exists())

    def test_failed_render_cleans_temp_and_keeps_old_file(self) -> None:
        broken = self.dir / "broken-input.mp4"
        broken.write_text("this is not a video", encoding="utf-8")
        self.out.write_bytes(b"previous good render")
        with self.assertRaises(RuntimeError):
            rerender.rerender_clip(broken, 0, 2, self.out)
        self.assertEqual(self.out.read_bytes(), b"previous good render")
        strays = [p for p in self.dir.iterdir() if p.name not in {"broken-input.mp4", "clip.mp4"}]
        self.assertEqual(strays, [], f"temp files left behind: {strays}")

    def test_cli_entrypoint(self) -> None:
        proc = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--source", str(self.source),
                "--start", "2", "--end", "6",
                "--out", str(self.out),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.out.exists())
        self.assertEqual([p for p in self.dir.iterdir() if p.name != "clip.mp4"], [])

    def test_cli_reports_errors(self) -> None:
        proc = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--source", str(self.dir / "nope.mp4"),
                "--start", "0", "--end", "2",
                "--out", str(self.out),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Source video not found", proc.stderr)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
