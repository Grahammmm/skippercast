"""RF1210-6: ``write_jsonl`` replaces its checkpoint only after a complete, closed write (synthetic data only)."""
import errno
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from skippercast.fleet import ingest

ROW = {"name": "Synthetic Prior", "source_id": "synthetic"}
NEW_ROWS = [{"name": "Zoë Boat", "source_id": "s", "a": 1}, {"name": "Second", "source_id": "t"}]


class _FaultyFile:
    """Wraps the real staged file: writes a prefix then fails, or fails on close."""

    def __init__(self, real, *, partial=None, close_error=None):
        self.real, self.partial, self.close_error = real, partial, close_error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.real.close()
        if self.close_error is not None and not exc[0]:
            raise self.close_error
        return False

    def write(self, data):
        if self.partial is not None:
            self.real.write(data[: self.partial])
            self.real.flush()
            raise self.partial_error
        return self.real.write(data)

    partial_error = OSError(errno.ENOSPC, "No space left on device")


def faulty_fdopen(**kw):
    real_fdopen = os.fdopen
    return lambda fd, mode: _FaultyFile(real_fdopen(fd, mode), **kw)


class WriteJsonlAtomicTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.target = self.dir / "candidates.jsonl"

    def seed(self):
        ingest.write_jsonl(self.target, [ROW])
        return self.target.read_bytes()

    def names(self):
        return sorted(p.name for p in self.dir.iterdir())

    def test_partial_write_preserves_previous_checkpoint(self):
        before = self.seed()
        with mock.patch.object(ingest.os, "fdopen", faulty_fdopen(partial=12)):
            with self.assertRaises(OSError) as cm:
                ingest.write_jsonl(self.target, NEW_ROWS)
        self.assertEqual(cm.exception.errno, errno.ENOSPC)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.names(), ["candidates.jsonl"])
        self.assertEqual([c.name for c in ingest.run_candidates(self.dir)], ["Synthetic Prior"])

    def test_partial_write_without_previous_file_leaves_target_absent(self):
        with mock.patch.object(ingest.os, "fdopen", faulty_fdopen(partial=12)):
            with self.assertRaises(OSError):
                ingest.write_jsonl(self.target, NEW_ROWS)
        self.assertEqual(self.names(), [])

    def test_fdopen_failure_closes_acquired_descriptor(self):
        before = self.seed()
        opened = []
        error = MemoryError("wrapper allocation failed")

        def fail_fdopen(fd, mode):
            opened.append(fd)
            raise error

        with mock.patch.object(ingest.os, "fdopen", side_effect=fail_fdopen):
            with self.assertRaises(MemoryError) as cm:
                ingest.write_jsonl(self.target, NEW_ROWS)
        self.assertIs(cm.exception, error)
        self.assertEqual(len(opened), 1)
        try:
            with self.assertRaises(OSError) as closed:
                os.fstat(opened[0])
            self.assertEqual(closed.exception.errno, errno.EBADF)
        finally:
            # Release the leaked descriptor when exercising the unfixed implementation.
            try:
                os.close(opened[0])
            except OSError:
                pass
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.names(), ["candidates.jsonl"])

    def test_close_failure_is_atomic(self):
        before = self.seed()
        err = OSError(errno.EIO, "close failed")
        with mock.patch.object(ingest.os, "fdopen", faulty_fdopen(close_error=err)):
            with self.assertRaises(OSError) as cm:
                ingest.write_jsonl(self.target, NEW_ROWS)
        self.assertIs(cm.exception, err)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.names(), ["candidates.jsonl"])

    def test_replace_failure_is_atomic(self):
        before = self.seed()
        with mock.patch.object(ingest.os, "replace", side_effect=OSError(errno.EACCES, "no")):
            with self.assertRaises(OSError) as cm:
                ingest.write_jsonl(self.target, NEW_ROWS)
        self.assertEqual(cm.exception.errno, errno.EACCES)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.names(), ["candidates.jsonl"])

    def test_interrupt_during_write_cleans_up(self):
        before = self.seed()
        _FaultyFile.partial_error = KeyboardInterrupt()
        self.addCleanup(setattr, _FaultyFile, "partial_error", OSError(errno.ENOSPC, "No space left on device"))
        with mock.patch.object(ingest.os, "fdopen", faulty_fdopen(partial=5)):
            with self.assertRaises(KeyboardInterrupt):
                ingest.write_jsonl(self.target, NEW_ROWS)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.names(), ["candidates.jsonl"])

    def test_preparation_failures_never_touch_target(self):
        before = self.seed()

        def boom():
            yield {"a": 1}
            raise RuntimeError("iterable failed")

        for rows, exc in ((boom(), RuntimeError), ([{"a": 1}, {"b": object()}], TypeError)):
            with self.assertRaises(exc):
                ingest.write_jsonl(self.target, rows)
        with mock.patch.object(ingest.tempfile, "mkstemp", side_effect=OSError(errno.EMFILE, "x")):
            with self.assertRaises(OSError):
                ingest.write_jsonl(self.target, NEW_ROWS)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.names(), ["candidates.jsonl"])
        missing = self.dir / "absent" / "x.jsonl"
        with self.assertRaises(OSError):
            ingest.write_jsonl(missing, NEW_ROWS)
        self.assertFalse(missing.parent.exists())

    def test_successful_replacement_is_byte_compatible(self):
        self.seed()
        rows = [dict(r) for r in NEW_ROWS]
        self.assertEqual(ingest.write_jsonl(self.target, rows), 2)
        expected = (json.dumps(NEW_ROWS[0], sort_keys=True, ensure_ascii=False) + "\n"
                    + json.dumps(NEW_ROWS[1], sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        self.assertEqual(self.target.read_bytes(), expected)
        self.assertEqual(rows, NEW_ROWS)
        self.assertIn("Zoë".encode("utf-8"), expected)
        self.assertEqual(ingest.write_jsonl(self.target, []), 0)
        self.assertEqual(self.target.read_bytes(), b"")
        self.assertEqual(self.names(), ["candidates.jsonl"])

    def test_permissions_and_cleanup_ownership(self):
        sentinel = self.dir / ".candidates.jsonl.old.tmp"
        sentinel.write_bytes(b"keep")
        ingest.write_jsonl(self.target, [ROW])
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)
        self.target.chmod(0o640)
        ingest.write_jsonl(self.target, NEW_ROWS)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o640)
        with mock.patch.object(ingest.os, "replace", side_effect=OSError(errno.EIO, "x")):
            with self.assertRaises(OSError):
                ingest.write_jsonl(self.target, [ROW])
        self.assertEqual(sentinel.read_bytes(), b"keep")
        self.assertEqual(self.names(), [".candidates.jsonl.old.tmp", "candidates.jsonl"])

    def test_concurrent_staging_names_are_distinct(self):
        seen = []
        real = tempfile.mkstemp

        def spy(*a, **k):
            fd, name = real(*a, **k)
            seen.append(name)
            return fd, name

        with mock.patch.object(ingest.tempfile, "mkstemp", spy):
            ingest.write_jsonl(self.target, [ROW])
            ingest.write_jsonl(self.target, [ROW])
        self.assertEqual(len(set(seen)), 2)


if __name__ == "__main__":
    unittest.main()
