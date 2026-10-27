"""Regression tests for the Windows job-file race-condition fixes.

Covers:
  * concurrent JSON writes to one destination never share a temp file
    (the shared fixed ``.tmp`` name raised WinError 32 on Windows)
  * JSON stays valid after repeated writes; temp files are cleaned up after
    successful *and* failed writes
  * ``generate.lock`` is only ever removed by its owner
  * a cancelled job document is never overwritten by a live worker

Run with:
    python -m unittest discover -s tests -p "test_*.py" -v
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

# Redirect every state file into a throw-away directory BEFORE backend.paths
# is imported (it reads ACF_DATA_ROOT at import time). dotenv will not
# override an already-set variable, so the project's .env stays inert here.
_TEST_ROOT = tempfile.mkdtemp(prefix="acf-jobstate-")
os.environ["ACF_DATA_ROOT"] = _TEST_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import common, paths  # noqa: E402
import backend.main as main  # noqa: E402


def tearDownModule() -> None:
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)


def _process_write(args: tuple) -> None:
    """One writer process: hammer a shared destination with valid JSON."""
    target_str, worker, iterations = args
    target = Path(target_str)
    for i in range(iterations):
        common.write_json(target, {"worker": worker, "i": i})


class JsonWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(dir=_TEST_ROOT))
        self.target = self.dir / "job-abc.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_concurrent_threaded_writes_no_temp_collisions(self) -> None:
        """Writers + readers on one destination: no shared temp, no bad JSON."""
        errors: list[BaseException] = []
        common.write_json(self.target, {"worker": "seed", "i": 0})

        def writer(worker: int) -> None:
            try:
                for i in range(25):
                    common.write_json(self.target, {"worker": worker, "i": i})
            except BaseException as exc:  # noqa: BLE001 - recorded, re-raised below
                errors.append(exc)

        def reader() -> None:
            try:
                for _ in range(300):
                    try:
                        raw = self.target.read_text(encoding="utf-8")
                    except FileNotFoundError:
                        continue  # only possible before the seed write
                    except PermissionError:
                        # Transient sharing violation while a writer renames
                        # over the file - production readers tolerate exactly
                        # this (read_job/readJSON catch OSError), so retry.
                        time.sleep(0.01)
                        continue
                    try:
                        json.loads(raw)
                    except ValueError as exc:
                        errors.append(AssertionError(f"reader saw invalid JSON: {exc}"))
                        return
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(w,)) for w in range(4)]
        threads += [threading.Thread(target=reader) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"concurrent access raised: {errors}")
        data = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertIn("worker", data)
        leftovers = list(self.dir.glob("*.tmp"))
        self.assertEqual(leftovers, [], f"temp files left behind: {leftovers}")

    def test_concurrent_process_writes_no_temp_collisions(self) -> None:
        """Cross-process writers (worker vs bot vs dashboard) never collide."""
        payload = [(str(self.target), w, 15) for w in range(4)]
        with ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_process_write, args) for args in payload]
            for future in futures:
                future.result()  # re-raises any writer failure

        data = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertIn("worker", data)
        leftovers = list(self.dir.glob("*.tmp"))
        self.assertEqual(leftovers, [], f"temp files left behind: {leftovers}")

    def test_repeated_writes_keep_json_valid(self) -> None:
        for i in range(50):
            common.write_json(self.target, {"i": i, "text": "héllo wörld ✓"})
            data = json.loads(self.target.read_text(encoding="utf-8"))
            self.assertEqual(data["i"], i)
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_failed_write_cleans_up_and_keeps_old_content(self) -> None:
        common.write_json(self.target, {"i": 1})
        with self.assertRaises(TypeError):
            common.write_json(self.target, {"bad": object()})  # not serializable
        # Destination untouched, and our own temp file was removed.
        data = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertEqual(data, {"i": 1})
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

        # Same for a first write that fails: no destination, no leftovers.
        fresh = self.dir / "never-written.json"
        with self.assertRaises(TypeError):
            common.write_json(fresh, {"bad": object()})
        self.assertFalse(fresh.exists())
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_unicode_preserved_not_escaped(self) -> None:
        common.write_json(self.target, {"t": "故事 𝕊"})
        raw = self.target.read_text(encoding="utf-8")
        self.assertIn("故事 𝕊", raw)  # ensure_ascii=False kept as before
        self.assertEqual(json.loads(raw)["t"], "故事 𝕊")


class LockOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        paths.ensure_dirs()
        paths.LOCK_FILE.unlink(missing_ok=True)

    def tearDown(self) -> None:
        paths.LOCK_FILE.unlink(missing_ok=True)

    def test_acquire_records_job_and_pid(self) -> None:
        main.acquire_lock("job-a")
        info = common.read_lock()
        self.assertEqual(info.get("job_id"), "job-a")
        self.assertEqual(int(info.get("pid")), os.getpid())
        self.assertIn("created_at", info)

    def test_release_lock_only_removes_own_lock(self) -> None:
        main.acquire_lock("job-a")
        # A different job (or a cancellation for another job) must not free it.
        self.assertFalse(common.remove_lock_if_owned("job-b"))
        self.assertTrue(paths.LOCK_FILE.exists())
        main.release_lock("job-b")  # logs a warning, still must not remove
        self.assertTrue(paths.LOCK_FILE.exists())
        # The owner releases it.
        main.release_lock("job-a")
        self.assertFalse(paths.LOCK_FILE.exists())

    def test_legacy_plain_text_lock_ownership(self) -> None:
        paths.LOCK_FILE.write_text("job-a", encoding="utf-8")
        self.assertEqual(common.read_lock(), {"job_id": "job-a"})
        self.assertFalse(common.remove_lock_if_owned("job-b"))
        self.assertTrue(paths.LOCK_FILE.exists())
        self.assertTrue(common.remove_lock_if_owned("job-a"))
        self.assertFalse(paths.LOCK_FILE.exists())

    def test_missing_or_empty_lock_is_never_owned(self) -> None:
        self.assertFalse(common.remove_lock_if_owned("job-a"))
        paths.LOCK_FILE.write_text("", encoding="utf-8")
        self.assertEqual(common.read_lock(), {})
        self.assertFalse(common.remove_lock_if_owned("job-a"))
        self.assertTrue(paths.LOCK_FILE.exists())


class CancelledJobGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        paths.ensure_dirs()
        self.job_id = "job-cancel-guard"
        self.doc = paths.JOBS / f"{self.job_id}.json"
        self.doc.unlink(missing_ok=True)

    def tearDown(self) -> None:
        self.doc.unlink(missing_ok=True)

    def _disk(self) -> dict:
        return json.loads(self.doc.read_text(encoding="utf-8"))

    def test_worker_never_overwrites_an_existing_cancellation(self) -> None:
        # A cancellation that landed before the worker started wins.
        common.write_json(
            self.doc,
            {"id": self.job_id, "status": "cancelled", "progress": 10},
        )
        job = main.Job(self.job_id, "https://example.com/v", 3, "viral")
        self.assertTrue(job.cancelled)
        self.assertEqual(self._disk()["status"], "cancelled")

        with self.assertRaises(main.JobCancelled):
            job.update(progress=50, message="still working")
        job.fail("worker blew up")  # must be a no-op, not an error state
        job.finish([{"id": "clip-01"}])  # must be a no-op, not done
        self.assertEqual(self._disk()["status"], "cancelled")

    def test_cancellation_during_run_stops_further_writes(self) -> None:
        job = main.Job(self.job_id, "https://example.com/v", 3, "viral")
        self.assertEqual(self._disk()["status"], "running")

        # Dashboard/bot cancellation lands between two worker updates.
        common.write_json(
            self.doc,
            {"id": self.job_id, "status": "cancelled", "progress": 7},
        )
        with self.assertRaises(main.JobCancelled):
            job.update(progress=25, message="download still going")
        self.assertTrue(job.cancelled)
        self.assertEqual(self._disk()["status"], "cancelled")

        # Subsequent writes stay silent even without re-checking the disk.
        job._write()
        self.assertEqual(self._disk()["status"], "cancelled")

    def test_normal_worker_flow_still_writes_progress(self) -> None:
        """The guards must not break the ordinary running/done transitions."""
        job = main.Job(self.job_id, "https://example.com/v", 3, "viral")
        self.assertEqual(job._disk_status(), "running")
        job.update(stage="download", progress=12, message="Downloading")
        data = self._disk()
        self.assertEqual(data["progress"], 12)
        self.assertEqual(data["stage"], "download")
        self.assertEqual(int(data["pid"]), os.getpid())
        job.finish([{"id": "clip-01"}, {"id": "clip-02"}])
        data = self._disk()
        self.assertEqual(data["status"], "done")
        self.assertEqual(data["progress"], 100)
        self.assertEqual(len(data["clips"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)