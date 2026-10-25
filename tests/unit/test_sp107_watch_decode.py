"""SP-10-v1 regression coverage for invalid UTF-8 AIS watch files."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from skippercast.fleet.ais.watch import WatchFile, parse_watch


REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "sp107_watch_decode"
INITIAL = 367000001
UPDATED = 367000002


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="sp107-watch-")
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.watch_path = self.root / "XX" / "watch.json"
        self.watch_path.parent.mkdir(parents=True)

    def _fixture_bytes(self, name="valid-initial.json"):
        payload = (FIXTURES / name).read_bytes()
        # Each invalid-encoding case starts from a complete accepted producer shape.
        parse_watch(json.loads(payload.decode("utf-8")), "XX")
        return payload

    def _write_bytes(self, payload):
        # Match the producer's atomic replacement, not timestamp resolution.
        # Every version deliberately has the same mtime to exercise same-tick writes.
        previous = self.watch_path.stat() if self.watch_path.exists() else None
        replacement = self.watch_path.with_name("watch.next")
        self.assertFalse(replacement.exists())
        replacement.write_bytes(payload)
        stamp = 1_700_000_000_000_000_000
        os.utime(replacement, ns=(stamp, stamp))
        os.replace(replacement, self.watch_path)
        if previous is not None:
            current = self.watch_path.stat()
            self.assertEqual(current.st_mtime_ns, previous.st_mtime_ns)
            self.assertNotEqual(current.st_ino, previous.st_ino)

    def _write_fixture(self, name):
        self._write_bytes(self._fixture_bytes(name))

    def _invalid_cases(self):
        healthy = self._fixture_bytes()
        return {
            "leading": b"\xff" + healthy,
            "mid_document": healthy.replace(b"2026-10-24", b"2026-\xc3\x28-24"),
            "surrogate_encoding": healthy.replace(b"2026-10-24", b"2026-\xed\xa0\x80-24"),
            "truncated_multibyte": healthy + b"\xe2\x82",
        }

    def test_primary_regression(self):
        """A1: capture baseline exception as data, then require safe rejection."""
        self._write_fixture("valid-initial.json")
        watch = WatchFile(self.watch_path, "XX")
        self.assertTrue(watch.poll())
        accepted = watch.current
        self.assertEqual(accepted.watched, frozenset({INITIAL}))
        self._write_bytes(self._invalid_cases()["leading"])
        observed_exception = None
        try:
            outcome = watch.poll()
        except UnicodeDecodeError as error:
            observed_exception = error
            outcome = None
        self.assertIsNone(observed_exception, f"poll raised {observed_exception!r}")
        self.assertIs(outcome, False)
        self.assertIs(watch.current, accepted)
        self.assertEqual(watch.current.watched, frozenset({INITIAL}))
        self.assertEqual(watch.last_error, "watch.json is not valid UTF-8")
        self.assertEqual(watch.errors, 1)

    def test_healthy_control(self):
        """A4 control: valid initial and changed watch files load as expected."""
        self._write_fixture("valid-initial.json")
        watch = WatchFile(self.watch_path, "XX")
        self.assertTrue(watch.poll())
        self.assertEqual(watch.current.watched, frozenset({INITIAL}))
        self._write_fixture("valid-updated.json")
        self.assertTrue(watch.poll())
        self.assertEqual(watch.current.watched, frozenset({UPDATED}))
        self.assertIsNone(watch.last_error)
        self.assertIs(watch.poll(), False)

    def test_invalid_sequences_preserve_prior_state_and_repeat_is_bounded(self):
        """A2/A3: each failure preserves exact state, then the same path recovers."""
        for name, invalid in self._invalid_cases().items():
            with self.subTest(case=name):
                self._write_fixture("valid-initial.json")
                watch = WatchFile(self.watch_path, "XX")
                self.assertTrue(watch.poll())
                accepted = watch.current
                self._write_bytes(invalid)
                self.assertIs(watch.poll(), False)
                self.assertIs(watch.current, accepted)
                self.assertEqual(watch.current.watched, frozenset({INITIAL}))
                self.assertEqual(watch.last_error, "watch.json is not valid UTF-8")
                self.assertEqual(watch.errors, 1)
                self.assertIs(watch.poll(), False)
                self.assertEqual(watch.errors, 1)
                self.assertIs(watch.current, accepted)
                self.assertTrue(watch.last_error)
                self._write_fixture("valid-updated.json")
                self.assertTrue(watch.poll())
                self.assertEqual(watch.current.watched, frozenset({UPDATED}))
                self.assertIsNone(watch.last_error)
                self.assertIs(watch.poll(), False)

    def test_invalid_initial_read_and_recovery(self):
        """A2/A3: invalid first read and repeated poll, then correction/no-op."""
        for name, invalid in self._invalid_cases().items():
            with self.subTest(case=name):
                watch = WatchFile(self.watch_path, "XX")
                empty = watch.current
                self._write_bytes(invalid)
                self.assertIs(watch.poll(), False)
                self.assertIs(watch.current, empty)
                self.assertEqual(watch.current.watched, frozenset())
                self.assertEqual(watch.last_error, "watch.json is not valid UTF-8")
                self.assertEqual(watch.errors, 1)
                self.assertIs(watch.poll(), False)
                self.assertEqual(watch.errors, 1)
                self.assertIs(watch.current, empty)
                self._write_fixture("valid-updated.json")
                self.assertTrue(watch.poll())
                self.assertEqual(watch.current.watched, frozenset({UPDATED}))
                self.assertIsNone(watch.last_error)
                self.assertIs(watch.poll(), False)

    def test_malformed_json_and_schema_rejection_still_retain_state(self):
        """A3: isolate unchanged malformed-JSON and schema rejection paths."""
        self._write_fixture("valid-initial.json")
        watch = WatchFile(self.watch_path, "XX")
        self.assertTrue(watch.poll())
        accepted = watch.current
        document = json.loads(self._fixture_bytes())
        invalid_schema = dict(document, schema_version=2)
        cases = [(self._fixture_bytes()[:-2], "watch.json is not JSON"),
                 (json.dumps(invalid_schema).encode(), "watch.json schema_version must be 1")]
        for payload, diagnostic in cases:
            with self.subTest(diagnostic=diagnostic):
                self._write_bytes(payload)
                self.assertIs(watch.poll(), False)
                self.assertIs(watch.current, accepted)
                self.assertEqual(watch.last_error, diagnostic)

    def test_read_error_still_retains_state(self):
        """A3: the pre-existing OSError path remains bounded and recoverable."""
        self._write_fixture("valid-initial.json")
        watch = WatchFile(self.watch_path, "XX")
        self.assertTrue(watch.poll())
        accepted = watch.current
        self._write_fixture("valid-updated.json")
        with mock.patch.object(Path, "read_text", side_effect=PermissionError(13, "synthetic denied")):
            self.assertIs(watch.poll(), False)
        self.assertIs(watch.current, accepted)
        self.assertEqual(watch.last_error, "watch.json cannot be read: synthetic denied")
        self.assertEqual(watch.errors, 1)
        # A changed file is required: unchanged unreadable bytes are not retried.
        self._write_bytes(self._fixture_bytes("valid-updated.json") + b"\n")
        self.assertTrue(watch.poll())
        self.assertEqual(watch.current.watched, frozenset({UPDATED}))
        self.assertIsNone(watch.last_error)


if __name__ == "__main__":
    unittest.main()
