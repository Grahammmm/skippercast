"""SC83: verified_file enforces its caller cap on existing cached assets.

Synthetic, offline tests against the real ``skippercast.seafloor.io.verified_file``.
Each test records the before/after SHA-256 of the files it observes in
``EVIDENCE`` so the SC83 acceptance runner can report preservation evidence;
the list is inert under ordinary unittest discovery.
"""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from skippercast.seafloor import io

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "sc83-cached-asset-cap"

# test name -> assertion class, reported by the acceptance runner.
ASSERTION_CLASSES = {
    "test_matching_cache_below_cap": "positive",
    "test_matching_cache_exact_cap": "positive",
    "test_small_download_remains_accepted": "positive",
    "test_oversized_cache_rejected_before_hash_or_session": "negative",
    "test_invalid_caps": "negative",
    "test_cache_checksum_mismatch_unchanged": "compatibility",
    "test_missing_offline_refusal_unchanged": "compatibility",
    "test_download_oversize_failure_preserves_absent_destination": "compatibility",
    "test_download_hash_failure_preserves_absent_destination": "compatibility",
}

EVIDENCE = []


def _digest(path):
    path = Path(path)
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MemorySession:
    """In-memory session double: writes a fixed body, or raises a fixed error."""

    def __init__(self, body=b"", error=None):
        self.body = body
        self.error = error
        self.calls = []

    def download(self, url, output, **kwargs):
        self.calls.append((url, kwargs.get("max_bytes")))
        if self.error is not None:
            raise self.error
        output.write(self.body)


class CacheHitCapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.payload = (FIXTURE_ROOT / "payload.txt").read_bytes()
        self.destination = self.root / "asset.bin"
        self.destination.write_bytes(self.payload)
        self.partial = self.destination.with_suffix(self.destination.suffix + ".part")
        self.sentinel = self.root / "unrelated-sentinel"
        self.sentinel.write_bytes(b"untouched")
        self.expected = hashlib.sha256(self.payload).hexdigest()
        self.url = io.NOAA_PREFIX + "synthetic/asset.bin"
        self.watched = {"destination": self.destination, "sentinel": self.sentinel,
                        "partial": self.partial}
        self.before = self._snapshot()

    def tearDown(self):
        EVIDENCE.append({"test": self._testMethodName,
                         "assertion_class": ASSERTION_CLASSES.get(self._testMethodName),
                         "payload_bytes": len(self.payload),
                         "before": self.before, "after": self._snapshot()})
        self.temp.cleanup()

    def _snapshot(self):
        return {name: _digest(path) for name, path in self.watched.items()}

    def assertWatchedUnchanged(self):
        self.assertEqual(self._snapshot(), self.before)

    def test_matching_cache_below_cap(self):
        session = Mock()
        with patch.object(io.http, "default_session") as factory:
            result = io.verified_file(self.url, self.expected, self.destination, True,
                                      max_bytes=len(self.payload) + 1, session=session)
        self.assertEqual(result, self.expected)
        factory.assert_not_called()
        session.download.assert_not_called()
        self.assertWatchedUnchanged()

    def test_matching_cache_exact_cap(self):
        session = Mock()
        with patch.object(io.http, "default_session") as factory:
            result = io.verified_file(self.url, self.expected, self.destination, True,
                                      max_bytes=len(self.payload), session=session)
        self.assertEqual(result, self.expected)
        factory.assert_not_called()
        session.download.assert_not_called()
        self.assertWatchedUnchanged()

    def test_oversized_cache_rejected_before_hash_or_session(self):
        # Cap-plus-one: cached bytes are one larger than the cap; the expected hash is correct.
        self.partial.write_bytes(b"prior-partial")
        self.before = self._snapshot()
        session = Mock()
        with patch.object(io, "sha256", wraps=io.sha256) as reader, \
                patch.object(io.http, "default_session") as factory:
            with self.assertRaisesRegex(ValueError, "^Source exceeds byte limit$"):
                io.verified_file(self.url, self.expected, self.destination, True,
                                 max_bytes=len(self.payload) - 1, session=session)
        reader.assert_not_called()
        factory.assert_not_called()
        session.download.assert_not_called()
        self.assertWatchedUnchanged()

    def test_invalid_caps(self):
        for cap in (True, False, 0, -1, 1.5, "4", None):
            with self.subTest(cap=repr(cap)):
                session = Mock()
                with patch.object(io, "sha256", wraps=io.sha256) as reader, \
                        patch.object(io.http, "default_session") as factory:
                    with self.assertRaisesRegex(ValueError, "^max_bytes must be a positive integer$"):
                        io.verified_file(self.url, self.expected, self.destination, True,
                                         max_bytes=cap, session=session)  # type: ignore[arg-type]
                reader.assert_not_called()
                factory.assert_not_called()
                session.download.assert_not_called()
                self.assertWatchedUnchanged()

    def test_cache_checksum_mismatch_unchanged(self):
        with patch.object(io.http, "default_session") as factory:
            with self.assertRaisesRegex(ValueError, "^SHA-256 mismatch for asset.bin$"):
                io.verified_file(self.url, "0" * 64, self.destination, True,
                                 max_bytes=len(self.payload), session=Mock())
        factory.assert_not_called()
        self.assertWatchedUnchanged()

    def test_missing_offline_refusal_unchanged(self):
        missing = self.root / "missing.bin"
        self.watched["missing"] = missing
        self.before = self._snapshot()
        with patch.object(io.http, "default_session") as factory:
            with self.assertRaises(FileNotFoundError):
                io.verified_file(self.url, self.expected, missing, False, max_bytes=100)
        factory.assert_not_called()
        self.assertWatchedUnchanged()

    def test_small_download_remains_accepted(self):
        body = b"new"
        dest = self.root / "download.bin"
        self.watched["download"] = dest
        self.before = self._snapshot()
        session = MemorySession(body)
        digest = hashlib.sha256(body).hexdigest()
        with patch.object(io.http, "default_session") as factory:
            result = io.verified_file(self.url, digest, dest, True,
                                      max_bytes=len(body), session=session)
        self.assertEqual(result, digest)
        factory.assert_not_called()
        self.assertEqual(session.calls, [(self.url, len(body))])
        self.assertEqual(dest.read_bytes(), body)
        self.assertFalse(dest.with_suffix(".bin.part").exists())

    def test_download_oversize_failure_preserves_absent_destination(self):
        dest = self.root / "oversize.bin"
        self.watched["download"] = dest
        self.before = self._snapshot()
        session = MemorySession(error=io.http.BodyTooLarge("synthetic oversize"))
        with self.assertRaisesRegex(ValueError, "^Source exceeds byte limit$"):
            io.verified_file(self.url, self.expected, dest, True, max_bytes=10, session=session)
        self.assertEqual(session.calls, [(self.url, 10)])
        self.assertFalse(dest.exists())
        self.assertFalse(dest.with_suffix(".bin.part").exists())
        self.assertWatchedUnchanged()

    def test_download_hash_failure_preserves_absent_destination(self):
        dest = self.root / "hash-failure.bin"
        self.watched["download"] = dest
        self.before = self._snapshot()
        session = MemorySession(b"wrong")
        with self.assertRaisesRegex(ValueError, "^SHA-256 mismatch for downloaded asset$"):
            io.verified_file(self.url, self.expected, dest, True, max_bytes=100, session=session)
        self.assertEqual(session.calls, [(self.url, 100)])
        self.assertFalse(dest.exists())
        self.assertFalse(dest.with_suffix(".bin.part").exists())
        self.assertWatchedUnchanged()


if __name__ == "__main__":
    unittest.main()
