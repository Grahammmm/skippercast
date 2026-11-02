from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from scripts import feed_stale_alert as alert
from scripts.check_feed_freshness import STALE, run_all, write_report

T0 = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)
BASE = "https://site.example"
STALE_STAMP = "2026-11-01T14:00:00Z"  # 6 h before T0; the conditions limit is 3 h
FRESH_STAMP = "2026-11-01T19:40:00Z"


class FakeGitHub:
    """Just enough of `gh issue ...` to hold the alert's only state: open issues, their age and comments."""

    def __init__(self, clock):
        self.clock, self.issues, self.n = clock, [], 0
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("issue", "list"):
            return json.dumps([i for i in self.issues if i["state"] == "open"])
        if args[:2] == ("issue", "create"):
            self.n += 1
            title = args[args.index("--title") + 1]
            body = args[args.index("--body") + 1]
            self.issues.append({"number": self.n, "title": title, "body": body, "state": "open",
                                "createdAt": self.clock().isoformat(), "comments": []})
        elif args[:2] == ("issue", "comment"):
            self.find(args[2])["comments"].append({"body": args[args.index("--body") + 1]})
        elif args[:2] == ("issue", "close"):
            issue = self.find(args[2])
            issue["state"] = "closed"
            issue["comments"].append({"body": args[args.index("--comment") + 1]})
        return ""

    def find(self, number):
        return next(i for i in self.issues if str(i["number"]) == str(number))


def stale_fetch(published):
    def fetch(url):
        if "/conditions/latest.json" in url and "regions" not in url:
            return {"published_at": published, "run_id": "7"}
        if url.endswith("/data/latest.json"):
            return {"published_at": FRESH_STAMP, "schedule": {"max_delay_hours": 36}}
        raise OSError("not under test: " + url)
    return fetch


class StaleAlertTests(unittest.TestCase):
    def report(self, published):
        events = []
        status, _ = run_all(BASE, T0, stale_fetch(published), regions=[], events=events)
        path = Path(self.tmp.name) / "feed-health.json"
        write_report(path, status, events)
        return path

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_check_names_the_feed_its_last_publish_and_how_late(self):
        report = json.loads(self.report(STALE_STAMP).read_text())
        self.assertTrue(report["stale"])
        [event] = report["stale_feeds"]
        self.assertEqual((event["feed"], event["last_published"], event["age_hours"], event["late_hours"], event["limit_hours"]),
                         ("conditions", STALE_STAMP, 6.0, 3.0, 3))
        self.assertEqual(json.loads(self.report(FRESH_STAMP).read_text())["stale_feeds"], [])

    def test_alert_once_then_aged_not_repeated_then_closed(self):
        now = [T0]
        gh = FakeGitHub(lambda: now[0])

        def pass_(published, at):
            now[0] = at
            return alert.main(["--report", str(self.report(published))], runner=gh, now=at)

        pass_(STALE_STAMP, T0)  # first seen: one issue, the alert line is its body
        [issue] = gh.issues
        self.assertEqual(issue["title"], "Published feed is stale: conditions")
        self.assertIn("STALE conditions: last published 2026-11-01T14:00:00Z (6.0 h ago), 3.0 h past its 3 h limit.", issue["body"])
        for hours in (1, 2, 3, 4, 5):  # hourly passes inside the interval: nothing new, no duplicate issue
            pass_(STALE_STAMP, T0 + timedelta(hours=hours))
        self.assertEqual((len(gh.issues), gh.issues[0]["comments"]), (1, []))
        pass_(STALE_STAMP, T0 + timedelta(hours=6))  # fixed interval reached: one aged line
        pass_(STALE_STAMP, T0 + timedelta(hours=6, minutes=1))  # the same pass again: no duplicate
        pass_(STALE_STAMP, T0 + timedelta(hours=7))
        [comment] = gh.issues[0]["comments"]
        self.assertTrue(comment["body"].startswith("still: 6 h - STALE conditions: last published 2026-11-01T14:00:00Z"))
        self.assertEqual(len([c for c in gh.calls if c[:2] == ("issue", "create")]), 1)
        pass_(STALE_STAMP, T0 + timedelta(hours=12))
        self.assertTrue(gh.issues[0]["comments"][1]["body"].startswith("still: 12 h"))
        pass_(FRESH_STAMP, T0 + timedelta(hours=13))  # recovery closes it
        self.assertEqual(gh.issues[0]["state"], "closed")
        self.assertTrue(gh.issues[0]["comments"][-1]["body"].startswith("Recovered"))

    def test_one_issue_per_feed_and_a_new_event_is_a_new_issue(self):
        events = [{"feed": "conditions", "last_published": STALE_STAMP, "age_hours": 6.0, "late_hours": 3.0, "limit_hours": 3},
                  {"feed": "region:monterey", "last_published": None, "reason": "HTTP 404"}]
        issues = []
        acts = alert.plan(events, issues, T0)
        self.assertEqual([a[1] for a in acts], ["Published feed is stale: conditions", "Published feed is stale: region:monterey"])
        self.assertIn("no readable publish time (HTTP 404)", acts[1][2])
        closed = [{"number": 1, "title": "Published feed is stale: conditions", "createdAt": T0.isoformat(), "comments": []}]
        self.assertEqual(alert.plan([], closed, T0 + timedelta(hours=2))[0][:2], ("close", 1))

    def test_legacy_single_issue_is_replaced_and_crashed_check_still_alerts(self):
        legacy = [{"number": 9, "title": "Published feed is stale", "createdAt": T0.isoformat(), "comments": []}]
        report = Path(self.tmp.name) / "missing.json"  # the check crashed before writing its report
        acts = alert.plan(alert.load_events(report, "true"), legacy, T0)
        self.assertEqual([a[0] for a in acts], ["create", "close"])
        self.assertIn("freshness-check", acts[0][1])
        self.assertEqual(alert.load_events(report, "false"), [])

    def test_skipped_interval_then_repeat_posts_once(self):
        now = [T0]
        gh = FakeGitHub(lambda: now[0])

        def pass_(published, at):
            now[0] = at
            return alert.main(["--report", str(self.report(published))], runner=gh, now=at)

        pass_(STALE_STAMP, T0)
        pass_(STALE_STAMP, T0 + timedelta(hours=12))  # the 6 h pass never ran: one 12 h line
        pass_(STALE_STAMP, T0 + timedelta(hours=12, minutes=1))  # the same interval again: nothing new
        pass_(STALE_STAMP, T0 + timedelta(hours=17))
        self.assertEqual([c["body"][:11] for c in gh.issues[0]["comments"]], ["still: 12 h"])
        pass_(STALE_STAMP, T0 + timedelta(hours=18))
        pass_(STALE_STAMP, T0 + timedelta(hours=18, minutes=1))
        self.assertEqual([c["body"][:11] for c in gh.issues[0]["comments"]], ["still: 12 h", "still: 18 h"])

    def test_crashed_check_is_not_a_recovery(self):
        now = [T0]
        gh = FakeGitHub(lambda: now[0])
        missing = str(Path(self.tmp.name) / "missing.json")

        def pass_(argv, at):
            now[0] = at
            return alert.main(argv, runner=gh, now=at)

        pass_(["--report", str(self.report(STALE_STAMP))], T0)  # stale: conditions issue opens
        pass_(["--report", missing, "--stale", "true"], T0 + timedelta(hours=1))  # crash: freshness unknown
        conditions, check = gh.issues
        self.assertEqual((conditions["title"], conditions["state"], conditions["comments"]),
                         ("Published feed is stale: conditions", "open", []))
        self.assertEqual((check["title"], check["state"]), ("Published feed is stale: freshness-check", "open"))
        pass_(["--report", str(self.report(STALE_STAMP))], T0 + timedelta(hours=2))  # still stale: same incident
        self.assertEqual(len([c for c in gh.calls if c[:2] == ("issue", "create")]), 2)
        self.assertEqual((conditions["state"], conditions["comments"]), ("open", []))
        self.assertEqual(check["state"], "closed")
        self.assertFalse(check["comments"][-1]["body"].startswith("Recovered: published again"))
        pass_(["--report", str(self.report(STALE_STAMP))], T0 + timedelta(hours=6))  # ages from its first alert
        self.assertTrue(conditions["comments"][0]["body"].startswith("still: 6 h"))

    def test_unreadable_feed_is_not_per_record(self):
        events = []
        status, _ = run_all(BASE, T0, lambda url: (_ for _ in ()).throw(OSError("down")), regions=[], events=events)
        self.assertTrue(status & STALE)
        self.assertEqual(sorted(e["feed"] for e in events), ["conditions", "data"])  # one per feed
        self.assertTrue(all(e["last_published"] is None for e in events))


if __name__ == "__main__":
    unittest.main()
