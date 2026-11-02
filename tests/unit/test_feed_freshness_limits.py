"""--max-age-hours / --data-max-age-hours accept only finite hours in (0, 8760]; anything else is argparse usage (exit 2)."""
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_feed_freshness import FEED, main

NOW = datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc)
BASE = "https://site.example"
FRESH = {"published_at": "2026-09-27T19:59:50Z", "generated_at": "2026-09-27T19:59:50Z", "sources": {}}  # 10 s old
FLAGS = ("--max-age-hours", "--data-max-age-hours")


class AgeLimitFlagTests(unittest.TestCase):
    def setUp(self):
        self.fetched = []

    def fetch(self, url):
        self.fetched.append(url)
        return FRESH

    def exit_code(self, argv):
        """Run main; return (exit code, stderr)."""
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as exited:
            main(["--public-base", BASE, *argv], self.fetch, NOW)
        return exited.exception.code, err.getvalue()

    def test_non_finite_zero_negative_or_huge_limit_is_usage_error(self):
        for flag in FLAGS:
            for value in ("nan", "inf", "-inf", "0", "-1", "8760.5", "1e9"):
                for mode in ([], ["--live-only"]):
                    with self.subTest(flag=flag, value=value, mode=mode), tempfile.TemporaryDirectory() as tmp:
                        report = Path(tmp) / "report.json"
                        code, err = self.exit_code([*mode, "--report", str(report), f"{flag}={value}"])
                        self.assertEqual(code, 2)
                        self.assertIn(f"argument {flag}: must be a number of hours above 0 and at most 8760", err)
                        self.assertEqual(self.fetched, [])  # refused before any feed is read
                        self.assertFalse(report.exists())

    def test_negative_value_as_separate_argument_is_still_refused(self):
        for flag in FLAGS:
            with self.subTest(flag=flag):
                code, err = self.exit_code([flag, "-1"])
                self.assertEqual((code, self.fetched), (2, []))
                self.assertIn(f"argument {flag}: must be a number of hours", err)

    def test_non_number_is_still_a_usage_error(self):
        for flag in FLAGS:
            with self.subTest(flag=flag):
                code, err = self.exit_code([flag, "abc"])
                self.assertEqual((code, self.fetched), (2, []))
                self.assertIn(f"argument {flag}: invalid", err)
                self.assertIn("'abc'", err)

    def test_finite_limits_in_range_are_accepted_on_the_live_path(self):
        for value in ("0.01", "1.25", "8760"):
            with self.subTest(value=value):
                self.fetched = []
                code, _ = self.exit_code(["--live-only", "--max-age-hours", value])
                self.assertEqual(code, 0)
                self.assertEqual(self.fetched, [f"{BASE}/feeds/conditions/latest.json", FEED])

    def test_limits_reach_the_full_run_unchanged(self):
        with patch("scripts.check_feed_freshness.run_all", return_value=(0, "ok")) as run_all:
            self.assertEqual(self.exit_code(["--max-age-hours", "0.01", "--data-max-age-hours", "8760"])[0], 0)
            self.assertEqual(run_all.call_args.kwargs["live_max_age_hours"], 0.01)
            self.assertEqual(run_all.call_args.kwargs["data_max_age_hours"], 8760.0)

    def test_no_flags_keep_the_catalog_defaults(self):
        with patch("scripts.check_feed_freshness.run_all", return_value=(0, "ok")) as run_all:
            self.assertEqual(self.exit_code([])[0], 0)
            self.assertIsNone(run_all.call_args.kwargs["live_max_age_hours"])
            self.assertIsNone(run_all.call_args.kwargs["data_max_age_hours"])
        with patch("scripts.check_feed_freshness.run", return_value=(True, "ok")) as run:
            self.assertEqual(self.exit_code(["--live-only"])[0], 0)
            self.assertEqual(run.call_args.args[3], timedelta(hours=3))  # catalog/feed-health.json live max_age_hours


if __name__ == "__main__":
    unittest.main()
