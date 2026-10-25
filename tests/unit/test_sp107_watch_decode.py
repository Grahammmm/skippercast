"""SP-10-v1 regression coverage for invalid UTF-8 AIS watch files."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from skippercast.fleet.ais.watch import WatchFile, write_watch


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

    def _load_fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def _write_fixture(self, name):
        document = self._load_fixture(name)
        self.watch_path.write_text(json.dumps(document), encoding="utf-8")

    def test_primary_regression(self):
        """A1: capture baseline exception as data, then require safe rejection."""
        self._write_fixture("valid-initial.json")
        watch = WatchFile(self.watch_path, "XX")
        self.assertTrue(watch.poll())
        accepted = watch.current
        self.assertEqual(accepted.watched, frozenset({INITIAL}))

        self.watch_path.write_bytes(b"\xff{\"schema_version\":1}")
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
        self.assertTrue(watch.last_error)
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

    def test_invalid_sequences_preserve_prior_state_and_repeat_is_bounded(self):
        """A2: invalid encodings at start/middle do not replace accepted state."""
        for invalid in (b"\xff{}", b'{"schema_version":1,\xff}'):
            with self.subTest(invalid=invalid):
                self._write_fixture("valid-initial.json")
                watch = WatchFile(self.watch_path, "XX")
                self.assertTrue(watch.poll())
                accepted = watch.current
                self.watch_path.write_bytes(invalid)
                self.assertIs(watch.poll(), False)
                self.assertIs(watch.current, accepted)
                self.assertTrue(watch.last_error)
                errors = watch.errors
                self.assertIs(watch.poll(), False)
                self.assertEqual(watch.errors, errors)
                self.assertIs(watch.current, accepted)

    def test_invalid_initial_read_and_recovery(self):
        """A2/A3: first read fails safely; valid correction recovers/no-ops."""
        watch = WatchFile(self.watch_path, "XX")
        self.watch_path.write_bytes(b"\xff")
        self.assertIs(watch.poll(), False)
        self.assertEqual(watch.current.watched, frozenset())
        self.assertTrue(watch.last_error)
        self.assertEqual(watch.errors, 1)

        self._write_fixture("valid-updated.json")
        self.assertTrue(watch.poll())
        self.assertEqual(watch.current.watched, frozenset({UPDATED}))
        self.assertIsNone(watch.last_error)
        self.assertIs(watch.poll(), False)

    def test_malformed_json_and_schema_rejection_still_retain_state(self):
        """A3: existing malformed-JSON/schema paths retain accepted watches."""
        self._write_fixture("valid-initial.json")
        watch = WatchFile(self.watch_path, "XX")
        self.assertTrue(watch.poll())
        accepted = watch.current
        for text in ('{"schema_version":', '{"schema_version":2,"region":"XX","watched":[]}'):
            with self.subTest(text=text):
                self.watch_path.write_text(text, encoding="utf-8")
                self.assertIs(watch.poll(), False)
                self.assertIs(watch.current, accepted)
                self.assertTrue(watch.last_error)


if __name__ == "__main__":
    unittest.main()
