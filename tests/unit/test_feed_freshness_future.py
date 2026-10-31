"""A feed stamped more than 10 minutes in the future is unreadable, never fresh (RF1240-3)."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_feed_freshness import PARTIAL, RAW, STALE, main, run_all, verdict

NOW = datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc)
LIMIT = timedelta(hours=3)
BASE = "https://site.example"
FRESH_DATA = {"published_at": "2026-09-27T05:00:00Z"}
SUFFIX = "(not an active region; reported, does not fail)"


def stamp(delta):
    return (NOW + delta).isoformat().replace("+00:00", "Z")


def ahead(**kwargs):
    return {"published_at": stamp(timedelta(**kwargs))}


def site(feeds, default=None):
    def fetch(url):
        item = feeds.get(url, default)
        if item is None:
            raise OSError(f"404 {url}")
        return item
    return fetch


def routes(branch):
    return f"{BASE}/feeds/{branch}/latest.json", f"{RAW}{branch}/latest.json"


def both(branch, feed):
    return dict.fromkeys(routes(branch), feed)


class FutureStampTests(unittest.TestCase):
    def test_far_future_is_unreadable_with_a_positive_age(self):
        ok, message = verdict(ahead(hours=5), NOW, LIMIT)
        self.assertFalse(ok)
        self.assertIn("Live conditions feed is unreadable: published 2026-09-28T01:00:00Z", message)
        self.assertIn(", 5.0 h in the future (clock or stamp error).", message)
        self.assertNotIn("-5.0", message)
        self.assertNotIn("fresh", message)

    def test_inside_tolerance_is_fresh_and_never_negative(self):
        for feed in (ahead(minutes=9), ahead(minutes=10), ahead(seconds=30)):
            ok, message = verdict(feed, NOW, LIMIT)
            self.assertTrue(ok, message)
            self.assertIn("is fresh: published 0.0 h ago.", message)
            self.assertNotIn("-0.", message)

    def test_one_second_past_tolerance_is_unreadable(self):
        ok, message = verdict(ahead(minutes=10, seconds=1), NOW, LIMIT)
        self.assertFalse(ok)
        self.assertIn("0.2 h in the future", message)

    def test_fallback_stamp_in_the_future_is_refused(self):
        ok, message = verdict({"completed_at": stamp(timedelta(hours=2))}, NOW, LIMIT, "Daily")
        self.assertFalse(ok)
        self.assertIn("Daily is unreadable: published 2026-09-27T22:00:00Z, 2.0 h in the future", message)
        # published_at still wins: a fresh published_at beside a future completed_at is fresh.
        self.assertTrue(verdict({"published_at": "2026-09-27T19:37:00Z", "completed_at": stamp(timedelta(hours=2))},
                                NOW, LIMIT)[0])

    def test_unchanged_messages(self):
        self.assertEqual(verdict({}, NOW, LIMIT), (False, "Live conditions feed is unreadable: feed has no completion time"))
        self.assertEqual(verdict({"completed_at": "2026-09-27T19:37:00"}, NOW, LIMIT),
                         (False, "Live conditions feed is unreadable: feed completion time has no timezone"))
        self.assertEqual(verdict({"completed_at": "2026-09-27T14:00:00Z", "run_id": "7"}, NOW, LIMIT),
                         (False, "Live conditions feed is stale: last published 2026-09-27T14:00:00Z (6.0 h ago, run 7; limit 3 h)."))


class FutureFeedRunTests(unittest.TestCase):
    def test_live_only_exits_stale(self):
        with self.assertRaises(SystemExit) as exited:
            main(["--live-only"], site({}, ahead(hours=5)), NOW)
        self.assertEqual(exited.exception.code, STALE)

    def test_full_run_sets_stale_and_reports_it(self):
        feeds = {**both("conditions", ahead(hours=5)), **both("data", FRESH_DATA)}
        status, message = run_all(BASE, NOW, site(feeds), regions=[])
        self.assertTrue(status & STALE, message)
        self.assertIn("Public conditions feed", message)
        self.assertIn("5.0 h in the future", message)
        self.assertIn("Public data feed", message)
        with tempfile.TemporaryDirectory() as tmp, patch("scripts.check_feed_freshness.published_regions", return_value=[]):
            report = Path(tmp) / "report.json"
            with self.assertRaises(SystemExit) as exited:
                main(["--public-base", BASE, "--report", str(report)], site(feeds), NOW)
            self.assertEqual(exited.exception.code, STALE)
            self.assertTrue(json.loads(report.read_text())["stale"])

    def test_future_region_feed_is_partial_for_preview_and_stale_for_active(self):
        feeds = {**both("conditions", {"published_at": "2026-09-27T19:37:00Z"}), **both("data", FRESH_DATA),
                 **both("conditions/regions/big-sur-coast", ahead(hours=1))}
        status, message = run_all(BASE, NOW, site(feeds), regions=[("big-sur-coast", False)])
        self.assertEqual(status, PARTIAL, message)
        [line] = [line for line in message.splitlines() if "big-sur-coast" in line]
        self.assertIn("big-sur-coast is unreadable", line)
        self.assertIn("1.0 h in the future", line)
        self.assertTrue(line.endswith(SUFFIX), line)
        status, message = run_all(BASE, NOW, site(feeds), regions=[("big-sur-coast", True)])
        self.assertEqual(status, STALE, message)
        self.assertNotIn(SUFFIX, message)


if __name__ == "__main__":
    unittest.main()
