import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from skippercast.pipeline import goes_frames


def _record(tag):
    return {"id": "goes-longwave", "tag": tag, "name": "café"}


def _bytes(tag):
    return (f'{{"id":"goes-longwave","tag":"{tag}","name":"café"}}\n').encode("utf-8")


class GoesFrameWriteTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.target = self.dir / "sub" / "goes-times.json"

    def _names(self):
        return sorted(p.name for p in self.target.parent.iterdir())

    def test_overlapping_writers_own_distinct_staging_files(self):
        real_replace = Path.replace
        staged = []

        def replace(src, dst):
            staged.append(Path(src))
            if len(staged) == 1:  # A reached replacement: B completes a full write first
                goes_frames.write(self.target, _record("B"))
            return real_replace(src, dst)

        with mock.patch.object(Path, "replace", replace):
            goes_frames.write(self.target, _record("A"))
        self.assertEqual(len(staged), 2)
        self.assertNotEqual(staged[0], staged[1])
        self.assertEqual(self.target.read_bytes(), _bytes("A"))
        self.assertEqual(self._names(), ["goes-times.json"])

    def test_ordinary_write_bytes_unchanged(self):
        goes_frames.write(self.target, _record("A"))
        self.assertEqual(self.target.read_bytes(), _bytes("A"))
        goes_frames.write(self.target, _record("B"))
        self.assertEqual(self.target.read_bytes(), _bytes("B"))
        self.assertEqual(self._names(), ["goes-times.json"])
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o644)

    def test_serialization_or_write_failure_preserves_previous_target(self):
        goes_frames.write(self.target, _record("old"))
        with self.assertRaises(TypeError):
            goes_frames.write(self.target, {"bad": object()})
        self.assertEqual(self.target.read_bytes(), _bytes("old"))
        self.assertEqual(self._names(), ["goes-times.json"])

        closed = []
        real_fdopen = os.fdopen

        def fdopen(fd, *a, **k):
            stream = real_fdopen(fd, *a, **k)
            def boom(_text):
                raise OSError("disk full")

            stream.write = boom
            closed.append(stream)
            return stream

        with mock.patch("os.fdopen", fdopen):
            with self.assertRaises(OSError):
                goes_frames.write(self.target, _record("new"))
        self.assertTrue(all(s.closed for s in closed) and closed)
        self.assertEqual(self.target.read_bytes(), _bytes("old"))
        self.assertEqual(self._names(), ["goes-times.json"])

    def test_replace_failure_preserves_previous_target_and_foreign_files(self):
        goes_frames.write(self.target, _record("old"))
        legacy = self.target.with_suffix(".json.tmp")
        legacy.write_bytes(b"legacy")
        sentinel = self.target.parent / "other.json"
        sentinel.write_bytes(b"other")
        with mock.patch.object(Path, "replace", side_effect=OSError("busy")):
            with self.assertRaises(OSError):
                goes_frames.write(self.target, _record("new"))
        self.assertEqual(self.target.read_bytes(), _bytes("old"))
        self.assertEqual(legacy.read_bytes(), b"legacy")
        self.assertEqual(sentinel.read_bytes(), b"other")
        self.assertEqual(self._names(), ["goes-times.json", "goes-times.json.tmp", "other.json"])

    def test_cleanup_failure_does_not_mask_primary_error(self):
        primary = OSError("busy")
        with mock.patch.object(Path, "replace", side_effect=primary), \
                mock.patch.object(Path, "unlink", side_effect=OSError("cleanup")):
            with self.assertRaises(OSError) as ctx:
                goes_frames.write(self.target, _record("new"))
        self.assertIs(ctx.exception, primary)


if __name__ == "__main__":
    unittest.main()
