import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from skippercast.seafloor import io


class CacheHitCapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "sc83-cached-asset-cap" / "payload.txt"
        self.payload = fixture.read_bytes()
        self.destination = self.root / "asset.bin"
        self.destination.write_bytes(self.payload)
        self.expected = hashlib.sha256(self.payload).hexdigest()
        self.url = io.NOAA_PREFIX + "synthetic/asset.bin"

    def tearDown(self):
        self.temp.cleanup()

    def test_matching_cache_below_cap(self):
        session = Mock()
        with patch.object(io.http, "default_session") as factory:
            self.assertEqual(io.verified_file(self.url, self.expected, self.destination, False,
                                              max_bytes=len(self.payload) + 1, session=session), self.expected)
        factory.assert_not_called()
        session.download.assert_not_called()

    def test_matching_cache_exact_cap(self):
        session = Mock()
        with patch.object(io.http, "default_session") as factory:
            self.assertEqual(io.verified_file(self.url, self.expected, self.destination, False,
                                              max_bytes=len(self.payload), session=session), self.expected)
        factory.assert_not_called()
        session.download.assert_not_called()

    def test_oversized_cache_rejected_before_hash_or_session(self):
        session = Mock()
        original = self.destination.read_bytes()
        sentinel = self.root / "unrelated-sentinel"
        sentinel.write_bytes(b"untouched")
        partial = self.destination.with_suffix(self.destination.suffix + ".part")
        partial.write_bytes(b"prior-partial")
        with patch.object(io, "sha256", wraps=io.sha256) as reader, patch.object(io.http, "default_session") as factory:
            with self.assertRaisesRegex(ValueError, "Source exceeds byte limit"):
                io.verified_file(self.url, self.expected, self.destination, True,
                                 max_bytes=len(self.payload) - 1, session=session)
            reader.assert_not_called()
        factory.assert_not_called()
        session.download.assert_not_called()
        self.assertEqual(self.destination.read_bytes(), original)
        self.assertEqual(sentinel.read_bytes(), b"untouched")
        self.assertEqual(partial.read_bytes(), b"prior-partial")

    def test_invalid_caps(self):
        for cap in (True, False, 0, -1, 1.5, "4", None):
            with self.subTest(cap=cap):
                with self.assertRaisesRegex(ValueError, "max_bytes"):
                    io.verified_file(self.url, self.expected, self.destination, False,
                                     max_bytes=cap)  # type: ignore[arg-type]

    def test_cache_checksum_mismatch_unchanged(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            io.verified_file(self.url, "0" * 64, self.destination, False,
                             max_bytes=len(self.payload))

    def test_missing_offline_refusal_unchanged(self):
        missing = self.root / "missing.bin"
        with self.assertRaises(FileNotFoundError):
            io.verified_file(self.url, self.expected, missing, False, max_bytes=100)

    def test_small_download_remains_accepted(self):
        class MemorySession:
            def __init__(self, payload=b"new"):
                self.calls = 0
                self.payload = payload
            def download(self, url, output, **kwargs):
                self.calls += 1
                output.write(self.payload)
        dest = self.root / "download.bin"
        session = MemorySession()
        digest = hashlib.sha256(b"new").hexdigest()
        self.assertEqual(io.verified_file(self.url, digest, dest, True, max_bytes=3, session=session), digest)
        self.assertEqual(session.calls, 1)

    def test_download_oversize_failure_preserves_absent_destination(self):
        class MemorySession:
            def download(self, url, output, **kwargs):
                raise io.http.BodyTooLarge("synthetic oversize")
        dest = self.root / "oversize.bin"
        with self.assertRaisesRegex(ValueError, "Source exceeds byte limit"):
            io.verified_file(self.url, self.expected, dest, True, max_bytes=10, session=MemorySession())
        self.assertFalse(dest.exists())
        self.assertFalse(dest.with_suffix(".bin.part").exists())

    def test_download_hash_failure_preserves_absent_destination(self):
        class MemorySession:
            def __init__(self):
                self.calls = 0
            def download(self, url, output, **kwargs):
                self.calls += 1
                output.write(b"wrong")
        dest = self.root / "hash-failure.bin"
        session = MemorySession()
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch for downloaded asset"):
            io.verified_file(self.url, self.expected, dest, True, max_bytes=100, session=session)
        self.assertEqual(session.calls, 1)
        self.assertFalse(dest.exists())
        self.assertFalse(dest.with_suffix(".bin.part").exists())



if __name__ == "__main__":
    unittest.main()
