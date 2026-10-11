from datetime import datetime, timedelta, timezone
import unittest

import os
from unittest.mock import patch

from scripts.check_feed_freshness import (DEFAULT_PUBLIC_BASE, DEGRADED, FEED, HEALTH, RAW, STALE, degraded_sources, main,
                                         public_url, run, run_all, source_verdict, verdict)

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


def source(ident, kind, status, sample_at=None, retrieved_at=None, checked_at="2026-09-27T19:37:00Z"):
    data = {"sample_at": sample_at} if sample_at else None
    item = {"id": ident, "kind": kind, "status": status, "checked_at": checked_at, "data": data}
    if retrieved_at:
        item.update(data_retrieved_at=retrieved_at, last_success_at=retrieved_at)
    return item


def feed_of(*sources, published="2026-09-27T19:37:00Z"):
    return {"published_at": published, "generated_at": published, "sources": {s["id"]: s for s in sources}}


class SourceHealthTests(unittest.TestCase):
    def test_ok_sources_report_nothing(self):
        feed = feed_of(source("diablo", "observation", "ok", "2026-09-27T19:00:00Z"))
        self.assertEqual(degraded_sources(feed), [])
        self.assertEqual(source_verdict(feed, 12, "Live"), (True, []))

    def test_retained_buoy_is_degraded_with_its_data_age(self):
        feed = feed_of(source("diablo", "observation", "retained", "2026-09-27T13:37:00Z", "2026-09-27T13:50:00Z"))
        [row] = degraded_sources(feed)
        self.assertEqual((row["id"], row["status"], row["critical"]), ("diablo", "retained", True))
        self.assertAlmostEqual(row["age_hours"], 6.0)
        ok, lines = source_verdict(feed, 12, "Live")
        self.assertTrue(ok)
        self.assertIn("warn diablo (observation): retained, data 6.0 h old (critical, limit 12 h)", lines[1])

    def test_critical_source_past_limit_fails_and_advisory_only_warns(self):
        feed = feed_of(source("offshore", "observation", "stale", "2026-09-27T01:00:00Z"),
                       source("rules-tuna", "page-watch", "retained", None, "2026-09-20T00:00:00Z"))
        ok, lines = source_verdict(feed, 12, "Live")
        self.assertFalse(ok)
        self.assertIn("critical sources degraded past 12 h", lines[0])
        self.assertIn("FAIL offshore (observation): stale, data 18.6 h old", lines[1])
        self.assertIn("warn rules-tuna (page-watch): retained", lines[2])
        self.assertIn("(advisory)", lines[2])

    def test_age_is_measured_at_build_time_not_now(self):
        # A buoy sampled an hour before the build is an hour old, however old the feed is now.
        feed = feed_of(source("buoy-46215", "observation", "retained", "2026-09-27T18:37:00Z"))
        self.assertAlmostEqual(degraded_sources(feed)[0]["age_hours"], 1.0)

    def test_failed_critical_source_without_data_fails(self):
        feed = feed_of(source("alerts-PZZ645", "advisory", "failed"))
        ok, lines = source_verdict(feed, 48, "Daily")
        self.assertFalse(ok)
        self.assertIn("failed, no data time", lines[1])

    def test_shared_thresholds(self):
        self.assertEqual(set(HEALTH["critical_kinds"]), {"observation", "advisory", "prediction", "forecast"})
        self.assertEqual(HEALTH["feeds"]["conditions"]["max_age_hours"], 3)
        self.assertEqual(HEALTH["feeds"]["data"]["max_age_hours"], 30)


class RunAllTests(unittest.TestCase):
    BASE = "https://site.example"

    def site(self, feeds):
        def fetch(url):
            item = feeds.get(url)
            if item is None or isinstance(item, Exception):
                raise item or OSError(f"404 {url}")
            return item
        return fetch

    def urls(self, branch):
        return f"{self.BASE}/feeds/{branch}/latest.json", f"{RAW}{branch}/latest.json"

    def feeds(self, live, data):
        (lp, lg), (dp, dg) = self.urls("conditions"), self.urls("data")
        return {lp: live, lg: live, dp: data, dg: data}

    def test_everything_fresh_and_ok_exits_zero(self):
        live = feed_of(source("diablo", "observation", "ok", "2026-09-27T19:00:00Z"))
        data = feed_of(source("tides", "prediction", "ok"), published="2026-09-27T05:00:00Z")
        status, message = run_all(self.BASE, NOW, self.site(self.feeds(live, data)))
        self.assertEqual(status, 0, message)
        self.assertIn("Public conditions feed", message)
        self.assertIn("Public data feed", message)

    def test_daily_feed_older_than_30_hours_is_stale(self):
        status, message = run_all(self.BASE, NOW, self.site(self.feeds(feed_of(), feed_of(published="2026-09-26T13:00:00Z"))))
        self.assertEqual(status, STALE)
        self.assertIn("Public data feed", message)
        self.assertIn("is stale", message)
        self.assertIn("limit 30 h", message)

    def test_fresh_feed_with_every_buoy_retained_past_limit_is_degraded(self):
        old = "2026-09-27T04:00:00Z"
        live = feed_of(source("diablo", "observation", "retained", old), source("offshore", "observation", "retained", old))
        status, message = run_all(self.BASE, NOW, self.site(self.feeds(live, feed_of(published="2026-09-27T05:00:00Z"))))
        self.assertEqual(status, DEGRADED)
        self.assertIn("is fresh", message)
        self.assertIn("FAIL diablo", message)
        self.assertIn("FAIL offshore", message)

    def test_unreachable_public_route_reads_sources_from_github_copy(self):
        (lp, lg), (dp, dg) = self.urls("conditions"), self.urls("data")
        live = feed_of(source("diablo", "observation", "retained", "2026-09-27T04:00:00Z"))
        data = feed_of(published="2026-09-27T05:00:00Z")
        status, message = run_all(self.BASE, NOW, self.site({lp: OSError("503"), lg: live, dp: data, dg: data}))
        self.assertEqual(status, STALE | DEGRADED)
        self.assertIn("Live conditions feed (GitHub copy)", message)

    def test_live_only_checks_only_the_live_age(self):
        live = feed_of(source("diablo", "observation", "retained", "2026-09-27T04:00:00Z"), published="2026-09-27T19:40:00Z")
        site = self.site({f"{self.BASE}/feeds/conditions/latest.json": live, FEED: live})
        with self.assertRaises(SystemExit) as exited:
            main(["--public-base", self.BASE, "--live-only", "--max-age-hours", "1.25"], site, NOW)
        self.assertEqual(exited.exception.code, 0)
        # Without --live-only the same feed reports the degraded buoy (the daily feed is absent: stale).
        with self.assertRaises(SystemExit) as exited:
            main(["--public-base", self.BASE], site, NOW)
        self.assertEqual(exited.exception.code, STALE | DEGRADED)


if __name__ == "__main__":
    unittest.main()
