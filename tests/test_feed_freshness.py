from datetime import datetime, timedelta, timezone
import unittest

from scripts.check_feed_freshness import verdict

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


if __name__ == "__main__":
    unittest.main()
