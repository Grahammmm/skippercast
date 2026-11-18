from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from scripts import feed_stale_alert as alert

NOW = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)
SENTINEL = [{"feed": alert.CHECK_FEED, "last_published": None,
             "reason": "the freshness check crashed or reported stale without naming a feed"}]
ISSUE = {"number": 7, "title": alert.TITLE + "conditions", "createdAt": "2026-11-01T20:00:00+00:00", "comments": []}


class DeepReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def load(self, text, flag):
        path = Path(self.tmp.name) / "r.json"
        path.write_text(text)
        return alert.load_events(path, flag)

    def deep(self):
        return "[" * 100000 + "]" * 100000

    def test_deep_report_uses_stale_fallback(self):
        self.assertEqual(self.load(self.deep(), "true"), SENTINEL)

    def test_deep_report_false_fallback(self):
        self.assertEqual(self.load(self.deep(), "false"), [])

    def test_unknown_does_not_close_existing_feed(self):
        actions = alert.plan(self.load(self.deep(), "true"), [ISSUE], NOW)
        self.assertFalse([a for a in actions if a[0] == "close"])

    def test_valid_fresh_control(self):
        self.assertEqual(self.load('{"stale": false, "stale_feeds": []}', "true"), [])
