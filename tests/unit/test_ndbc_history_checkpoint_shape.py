"""RF1110-5: a checkpoint whose `records` is not a JSON object stops before any request."""
from contextlib import ExitStack, redirect_stderr
from datetime import datetime, timezone
import gzip
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests._support import FIXTURES, ROOT

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
HISTORY = FIXTURES / "ndbc-history"
ONE_STATION = ("slo", (("46215", "Diablo Canyon", 35.204, -120.859),))
MESSAGE = "checkpoint morro-bay-checkpoint.json: records must be a JSON object; fix or remove it"
BAD_RECORDS = (("null", None), ("empty list", []), ("list", [{"a": 1}]), ("string", "records"), ("bool", True), ("int", 7))


class NdbcCheckpointShapeTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {"SKIPPERCAST_ROOT": str(ROOT), "SKIPPERCAST_HTTP_CACHE": ""}))
        from skippercast.pipeline import ndbc_history
        from skippercast.http import FakeSession
        self.nh, self.FakeSession = ndbc_history, FakeSession
        stack.enter_context(patch.dict(ndbc_history.STATIONS, {"morro-bay": ONE_STATION}))
        self.dir = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.cache, self.output = self.dir / "cache", self.dir / "out" / "history.json"
        self.checkpoint = self.cache / "morro-bay-checkpoint.json"
        test = self

        class Refusing(FakeSession):  # any request at all fails the test
            def request(self, method, url, **options):
                test.fail(f"unexpected request {url}")

        self.refusing = Refusing()

    def routes(self):
        nh = self.nh
        return {nh.index_url("46215"): (HISTORY / "index.html").read_bytes(), nh.recent_url("46215"): (HISTORY / "recent.txt").read_bytes(),
                nh.annual_url("46215", 2023): gzip.compress((HISTORY / "h2023.txt").read_bytes(), mtime=0),
                nh.annual_url("46215", 2024): gzip.compress((HISTORY / "h2024.txt").read_bytes(), mtime=0)}

    def write_checkpoint(self, records=None, *, whole=None):
        self.cache.mkdir(parents=True, exist_ok=True)
        value = whole if whole is not None else {"schemaVersion": 1, "regionId": "morro-bay", "records": records}
        self.checkpoint.write_text(json.dumps(value))

    def collect(self, session):
        return self.nh.collect("morro-bay", "full", session, self.cache, now=NOW)

    def assert_refused(self, session=None):
        with self.assertRaises(SystemExit) as caught:
            self.collect(session or self.refusing)
        self.assertEqual(caught.exception.code, MESSAGE)
        self.assertNotIn(str(self.dir), str(caught.exception.code))
        self.assertFalse(self.output.exists())

    def test_checkpoint_records_nonobjects_stop_before_fetch(self):
        for label, records in BAD_RECORDS:
            with self.subTest(records=label):
                self.write_checkpoint(records)
                self.assert_refused()

    def test_checkpoint_missing_records_is_named(self):
        self.write_checkpoint(whole={})
        self.assert_refused()

    def test_checkpoint_refusal_preserves_checkpoint_and_old_output(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_bytes(b'{"old":true}\n')
        self.write_checkpoint([])
        before = (self.checkpoint.read_bytes(), self.output.read_bytes())
        argv = ["ndbc_history", "--mode", "full", "--cache", str(self.cache), "--output", str(self.output)]
        stderr = io.StringIO()
        with patch.object(sys, "argv", argv), patch.object(self.nh.http, "Session", lambda **_: self.refusing), \
                redirect_stderr(stderr), patch("sys.stdout", io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                self.nh.main()
        self.assertEqual(caught.exception.code, MESSAGE)
        self.assertEqual((self.checkpoint.read_bytes(), self.output.read_bytes()), before)
        self.assertEqual(sorted(p.name for p in self.cache.iterdir()), ["morro-bay-checkpoint.json"])
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_empty_or_missing_checkpoint_uses_healthy_map(self):
        for label in ("absent", "empty-map", "extra-key"):
            with self.subTest(case=label):
                self.checkpoint.unlink(missing_ok=True)
                if label != "absent":
                    self.write_checkpoint({})
                if label == "extra-key":
                    self.write_checkpoint(whole={"schemaVersion": 1, "regionId": "morro-bay", "records": {}, "note": "kept"})
                session = self.FakeSession(self.routes())
                bundle = self.collect(session)
                self.assertEqual(bundle["stations"][0]["stationId"], "46215")
                self.assertEqual(len(bundle["stations"][0]["baseline"]["years"]), 2)
                self.assertIn(self.nh.index_url("46215"), [url for _, url, _ in session.calls])
                self.assertEqual(len(json.loads(self.checkpoint.read_text())["records"]), 2)

    def test_individual_bad_receipt_still_refills(self):
        key = f"46215:annual:2023"
        self.write_checkpoint({key: ["not", "a", "receipt"]})
        session = self.FakeSession(self.routes())
        bundle = self.collect(session)
        annual = self.nh.annual_url("46215", 2023)
        self.assertEqual([url for _, url, _ in session.calls].count(annual), 1)
        self.assertEqual(bundle["stations"][0]["baseline"]["years"], [2023, 2024])
        self.assertEqual(json.loads(self.checkpoint.read_text())["records"][key]["outcome"], "ok")


if __name__ == "__main__":
    unittest.main()
