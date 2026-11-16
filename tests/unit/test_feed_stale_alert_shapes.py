from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from scripts import feed_stale_alert as alert

NOW = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)
SENTINEL = [{"feed": alert.CHECK_FEED, "last_published": None,
             "reason": "the freshness check crashed or reported stale without naming a feed"}]
ISSUE = {"number": 7, "title": alert.TITLE + "conditions", "createdAt": "2026-11-01T20:00:00+00:00", "comments": []}

BAD_ROOTS = [None, [], "x", 5, True]
BAD_STALE = [0, 1, "false", None, [], {}]
BAD_FEEDS = [None, {}, "", 0, False]


class ShapeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def load(self, report, flag, raw=False):
        path = Path(self.tmp.name) / "r.json"
        path.write_text(report if raw else json.dumps(report))
        return alert.load_events(path, flag)

    def bad_envelopes(self):
        for root in BAD_ROOTS:
            yield root
        for stale in BAD_STALE:
            yield {"stale": stale, "stale_feeds": []}
        yield {"stale_feeds": []}
        for feeds in BAD_FEEDS:
            yield {"stale": False, "stale_feeds": feeds}
        yield {"stale": True, "stale_feeds": None}
        yield {"stale": True}

    def test_bad_envelope_uses_unreadable_fallback(self):
        for report in self.bad_envelopes():
            with self.subTest(report=report):
                self.assertEqual(self.load(report, "true"), SENTINEL)
                self.assertEqual(self.load(report, "false"), [])

    def test_invalid_envelope_is_not_recovery(self):
        for report in self.bad_envelopes():
            with self.subTest(report=report):
                actions = alert.plan(self.load(report, "true"), [ISSUE], NOW)
                self.assertFalse([a for a in actions if a[0] == "close"])
                self.assertEqual(alert.plan(self.load(report, "true"), [], NOW)[0][:2],
                                 ("create", alert.TITLE + alert.CHECK_FEED))

    def test_main_never_closes_on_invalid_envelope(self):
        path = Path(self.tmp.name) / "r.json"
        path.write_text(json.dumps({"stale": False, "stale_feeds": {}}))
        calls = []

        def runner(*args):
            calls.append(args)
            return json.dumps([ISSUE]) if args[:2] == ("issue", "list") else ""
        alert.main(["--report", str(path), "--stale", "true"], runner=runner, now=NOW)
        self.assertFalse([c for c in calls if c[:2] == ("issue", "close")])

    def test_valid_reports_unchanged(self):
        self.assertEqual(self.load({"stale": False, "stale_feeds": []}, "true"), [])
        self.assertEqual(alert.plan([], [ISSUE], NOW)[0][0], "close")
        self.assertEqual(self.load({"stale": True, "stale_feeds": []}, "false"), SENTINEL)
        events = [{"feed": "conditions", "last_published": "x", "reason": "r"}]
        self.assertEqual(self.load({"stale": True, "stale_feeds": events, "degraded": [], "partial": True}, "false"), events)

    def test_existing_read_errors(self):
        self.assertEqual(self.load("{not json", "true", raw=True), SENTINEL)
        self.assertEqual(self.load("{not json", "false", raw=True), [])
        missing = Path(self.tmp.name) / "none.json"
        self.assertEqual(alert.load_events(missing, "true"), SENTINEL)
        self.assertEqual(alert.load_events(missing, "false"), [])


if __name__ == "__main__":
    unittest.main()
