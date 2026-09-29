from datetime import datetime, timedelta, timezone
import unittest

import os
from unittest.mock import patch

from scripts.check_feed_freshness import DEFAULT_PUBLIC_BASE, FEED, public_url, run, verdict

NOW = datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc)
LIMIT = timedelta(hours=3)


class FeedFreshnessTests(unittest.TestCase):
    def test_recent_feed_is_fresh(self):
        ok, message = verdict({"completed_at": "2026-09-27T19:37:00Z"}, NOW, LIMIT)
        self.assertTrue(ok)
        self.assertIn("fresh", message)

    def test_old_feed_is_stale(self):
        ok, message = verdict({"completed_at": "2026-09-26T21:53:46Z"}, NOW, LIMIT)
        self.assertFalse(ok)
        self.assertIn("stale", message)

    def test_missing_or_naive_time_fails_closed(self):
        self.assertFalse(verdict({}, NOW, LIMIT)[0])
        self.assertFalse(verdict({"completed_at": "2026-09-27T19:37:00"}, NOW, LIMIT)[0])
        self.assertFalse(verdict({"completed_at": 5}, NOW, LIMIT)[0])

    def test_published_at_is_preferred(self):
        ok, message = verdict({"published_at": "2026-09-27T19:37:00Z", "completed_at": "2026-09-26T00:00:00Z",
                               "run_id": "42"}, NOW, LIMIT)
        self.assertTrue(ok)
        self.assertIn("run 42", message)


class PublicRouteTests(unittest.TestCase):
    PUBLIC = "https://site.example/feeds/conditions/latest.json"

    def site(self, public, github):
        def fetch(url):
            item = public if url == self.PUBLIC else github if url == FEED else None
            if isinstance(item, Exception) or item is None:
                raise item or AssertionError(url)
            return item
        return fetch

    def test_public_route_default_and_override(self):
        with patch.dict(os.environ, {"FEEDS_PUBLIC_BASE": ""}):
            self.assertEqual(public_url(), DEFAULT_PUBLIC_BASE + "/feeds/conditions/latest.json")
            self.assertEqual(DEFAULT_PUBLIC_BASE, "https://skippercast.g4651.workers.dev")
        with patch.dict(os.environ, {"FEEDS_PUBLIC_BASE": "https://site.example/"}):
            self.assertEqual(public_url(), self.PUBLIC)
        self.assertEqual(public_url("https://other.example"), "https://other.example/feeds/conditions/latest.json")

    def test_stale_public_route_fails_even_when_github_is_fresh(self):
        ok, message = run(self.PUBLIC, FEED, NOW, LIMIT, self.site({"completed_at": "2026-09-26T21:53:46Z"},
                                                                  {"published_at": "2026-09-27T19:37:00Z"}))
        self.assertFalse(ok)
        public_line, github_line = message.splitlines()
        self.assertIn("Public conditions feed", public_line)
        self.assertIn("stale", public_line)
        self.assertIn("GitHub conditions branch is fresh: published 0.4 h ago", github_line)

    def test_unreachable_public_route_fails(self):
        ok, message = run(self.PUBLIC, FEED, NOW, LIMIT, self.site(OSError("503"), {"completed_at": "2026-09-27T19:37:00Z"}))
        self.assertFalse(ok)
        self.assertIn("could not be fetched", message)

    def test_fresh_public_route_passes_and_reports_stale_github(self):
        ok, message = run(self.PUBLIC, FEED, NOW, LIMIT, self.site({"published_at": "2026-09-27T19:37:00Z"},
                                                                  {"completed_at": "2026-09-26T21:53:46Z"}))
        self.assertTrue(ok)
        self.assertIn("fresh", message.splitlines()[0])
        self.assertIn("GitHub conditions branch is stale", message.splitlines()[1])
        self.assertIn("(secondary signal)", message)


if __name__ == "__main__":
    unittest.main()
