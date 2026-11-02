"""RF1500-6: a bad --max-files budget and unreadable --previous/checkpoint JSON stop before any request."""
from contextlib import ExitStack, redirect_stderr
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests._support import ROOT

INDEX = "https://www.ndbc.noaa.gov/station_history.php?station=46215"
ANNUAL = "https://www.ndbc.noaa.gov/data/historical/stdmet/46215h2000.txt.gz"
ONE_STATION = ("slo", (("46215", "Diablo Canyon", 35.204, -120.859),))


class NdbcHistoryInputTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {"SKIPPERCAST_ROOT": str(ROOT), "SKIPPERCAST_HTTP_CACHE": ""}))
        from skippercast.pipeline import ndbc_history
        from skippercast.http import FakeSession
        self.nh = ndbc_history
        stack.enter_context(patch.dict(ndbc_history.STATIONS, {"morro-bay": ONE_STATION}))
        self.dir = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.cache, self.output = self.dir / "cache", self.dir / "out" / "history.json"
        test = self

        class Refusing(FakeSession):  # any request at all fails the test
            def request(self, method, url, **options):
                test.fail(f"unexpected request {url}")

        self.refusing = Refusing()
        self.fake = FakeSession({INDEX: '<a href="/data/historical/stdmet/46215h2000.txt.gz">'.encode()})

    def run_main(self, session, *extra, mode="full"):
        argv = ["ndbc_history", "--mode", mode, "--cache", str(self.cache), "--output", str(self.output), *extra]
        self.stderr = io.StringIO()
        with patch.object(sys, "argv", argv), patch.object(self.nh.http, "Session", lambda **_: session), \
                redirect_stderr(self.stderr), patch("sys.stdout", io.StringIO()):
            self.nh.main()

    def refused(self, *extra, mode="full"):
        with self.assertRaises(SystemExit) as caught:
            self.run_main(self.refusing, *extra, mode=mode)
        self.assertFalse(self.output.exists())
        return caught.exception

    def test_max_files_outside_range_is_usage_before_any_request(self):
        for value in ("0", "-1", "1001"):
            with self.subTest(value=value):
                self.assertEqual(self.refused("--max-files", value).code, 2)
                self.assertIn("--max-files must be between 1 and 1000", self.stderr.getvalue())
                self.assertFalse(self.cache.exists())

    def test_max_files_bounds_are_accepted(self):
        for value in ("1", "1000"):
            with self.subTest(value=value):
                self.fake.calls.clear()
                self.output.unlink(missing_ok=True)
                self.run_main(self.fake, "--max-files", value)
                self.assertEqual([url for _, url, _ in self.fake.calls[:2]], [INDEX, ANNUAL])
                self.assertEqual(json.loads(self.output.read_text())["stations"][0]["stationId"], "46215")

    def test_unreadable_previous_is_named_before_any_request(self):
        previous = self.dir / "previous.json"
        for body in (b"{bad", b"[]", b"\xff\xfe\x00{"):
            with self.subTest(body=body):
                previous.write_bytes(body)
                error = self.refused("--previous", str(previous))
                self.assertEqual(error.code, "--previous: not a readable JSON object; fix or remove it")

    def test_unreadable_checkpoint_is_named_by_file_name_only(self):
        self.cache.mkdir()
        (self.cache / "morro-bay-checkpoint.json").write_text("{bad")
        error = self.refused()
        self.assertEqual(error.code, "checkpoint morro-bay-checkpoint.json: not a readable JSON object; fix or remove it")
        self.assertNotIn(str(self.dir), str(error.code))

    def test_missing_previous_is_still_no_previous(self):
        error = self.refused("--previous", str(self.dir / "absent.json"), mode="recent")
        self.assertEqual(error.code, "Recent refresh needs a matching published history; run the full backfill first")


if __name__ == "__main__":
    unittest.main()
