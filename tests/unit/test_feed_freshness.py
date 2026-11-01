from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_feed_freshness import (DEFAULT_PUBLIC_BASE, DEGRADED, FEED, HEALTH, PARTIAL, RAW, STALE, age_limit_hours,
                                         degraded_sources, failing_kinds, main, public_url, published_regions, run, run_all,
                                         source_verdict, verdict)

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


def feed_of(*sources, published="2026-09-27T19:37:00Z", **extra):
    return {"published_at": published, "generated_at": published, "sources": {s["id"]: s for s in sources}, **extra}


OLD = "2026-09-27T01:00:00Z"   # 18.6 h before the build: past the 12 h live limit
RECENT = "2026-09-27T19:00:00Z"


class SourceHealthTests(unittest.TestCase):
    def test_ok_sources_report_nothing(self):
        feed = feed_of(source("diablo", "observation", "ok", RECENT))
        self.assertEqual(degraded_sources(feed), [])
        self.assertEqual(source_verdict(feed, 12, "Live"), (0, []))

    def test_retained_buoy_is_degraded_with_its_data_age(self):
        feed = feed_of(source("diablo", "observation", "retained", "2026-09-27T13:37:00Z", "2026-09-27T13:50:00Z"))
        [row] = degraded_sources(feed)
        self.assertEqual((row["id"], row["status"], row["critical"]), ("diablo", "retained", True))
        self.assertAlmostEqual(row["age_hours"], 6.0)
        bits, lines = source_verdict(feed, 12, "Live")
        self.assertEqual(bits, 0)
        self.assertIn("warn diablo (observation): retained, data 6.0 h old (critical, limit 12 h)", lines[1])

    def test_one_buoy_past_limit_while_another_reports_is_partial(self):
        # A single NDBC outage: reported (and kept in the issue) but it does not fail the run.
        feed = feed_of(source("offshore", "observation", "stale", OLD), source("diablo", "observation", "ok", RECENT),
                       source("rules-tuna", "page-watch", "retained", None, "2026-09-20T00:00:00Z"))
        bits, lines = source_verdict(feed, 12, "Live")
        self.assertEqual(bits, PARTIAL)
        self.assertEqual(failing_kinds(feed, 12), [])
        self.assertIn("1 critical source(s) degraded past 12 h while others of the same kind are not", lines[0])
        self.assertIn("over offshore (observation): stale, data 18.6 h old", lines[1])
        self.assertIn("warn rules-tuna (page-watch): retained", lines[2])
        self.assertIn("(advisory)", lines[2])

    def test_every_source_of_a_critical_kind_past_limit_fails(self):
        feed = feed_of(source("offshore", "observation", "stale", OLD), source("buoy-46011-spectrum", "observation", "retained", OLD),
                       source("tides", "prediction", "ok", RECENT))
        bits, lines = source_verdict(feed, 12, "Live")
        self.assertEqual(bits, DEGRADED)
        self.assertEqual(failing_kinds(feed, 12), ["observation"])
        self.assertIn("every observation source degraded past 12 h", lines[0])
        self.assertTrue(all(line.startswith("- FAIL") for line in lines[1:]))

    def test_a_reporting_spectrum_keeps_the_observation_kind_alive(self):
        feed = feed_of(source("diablo", "observation", "stale", OLD), source("diablo-spectrum", "observation", "ok", RECENT))
        self.assertEqual(source_verdict(feed, 12, "Live")[0], PARTIAL)

    def test_age_is_measured_at_build_time_not_now(self):
        # A buoy sampled an hour before the build is an hour old, however old the feed is now.
        feed = feed_of(source("buoy-46215", "observation", "retained", "2026-09-27T18:37:00Z"))
        self.assertAlmostEqual(degraded_sources(feed)[0]["age_hours"], 1.0)

    def test_sole_failed_critical_source_without_data_fails(self):
        feed = feed_of(source("alerts-PZZ645", "advisory", "failed"))
        bits, lines = source_verdict(feed, 48, "Daily")
        self.assertEqual(bits, DEGRADED)
        self.assertIn("failed, no data time", lines[1])

    def test_shared_thresholds(self):
        self.assertEqual(set(HEALTH["critical_kinds"]), {"observation", "advisory", "prediction", "forecast"})
        self.assertEqual(HEALTH["feeds"]["conditions"]["max_age_hours"], 3)
        self.assertEqual(HEALTH["feeds"]["data"]["max_age_hours"], 36)
        self.assertEqual(HEALTH["regions"]["path"], "conditions/regions/{region}/latest.json")


class AgeLimitTests(unittest.TestCase):
    CONFIG = {"max_age_hours": 36}

    def test_feed_schedule_wins_over_the_catalog_default(self):
        self.assertEqual(age_limit_hours({"schedule": {"max_delay_hours": 40}}, self.CONFIG), 40)
        self.assertEqual(age_limit_hours({"schedule": {"max_delay_hours": 40}}, self.CONFIG, 12), 12)

    def test_missing_or_invalid_schedule_falls_back(self):
        for feed in ({}, None, {"schedule": None}, {"schedule": {"max_delay_hours": "36"}},
                     {"schedule": {"max_delay_hours": 0}}, {"schedule": {"max_delay_hours": True}}):
            self.assertEqual(age_limit_hours(feed, self.CONFIG), 36)


class RegionIndexTests(unittest.TestCase):
    def test_regions_come_from_the_published_index_without_the_default(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "dist/regions").mkdir(parents=True)
            (Path(root) / "dist/regions/index.json").write_text(json.dumps({"default_region": "morro-bay", "regions": [
                {"id": "morro-bay", "status": "active"}, {"id": "big-sur-coast", "status": "preview"},
                {"id": "crescent-city", "status": "active"}]}))
            self.assertEqual(published_regions(root=root), [("big-sur-coast", False), ("crescent-city", True)])

    def test_committed_index_lists_regions(self):
        regions = published_regions()
        self.assertTrue(regions)
        self.assertNotIn("morro-bay", [region for region, _ in regions])


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

    def region_urls(self, region):
        return self.urls(f"conditions/regions/{region}")

    def feeds(self, live, data, **regions):
        (lp, lg), (dp, dg) = self.urls("conditions"), self.urls("data")
        feeds = {lp: live, lg: live, dp: data, dg: data}
        for region, feed in regions.items():
            feeds.update(dict.fromkeys(self.region_urls(region.replace("_", "-")), feed))
        return feeds

    def run_all(self, feeds, regions=(), **kwargs):
        return run_all(self.BASE, NOW, self.site(feeds), regions=list(regions), **kwargs)

    def test_everything_fresh_and_ok_exits_zero(self):
        live = feed_of(source("diablo", "observation", "ok", RECENT))
        data = feed_of(source("tides", "prediction", "ok"), published="2026-09-27T05:00:00Z")
        status, message = self.run_all(self.feeds(live, data))
        self.assertEqual(status, 0, message)
        self.assertIn("Public conditions feed", message)
        self.assertIn("Public data feed", message)

    def test_daily_feed_uses_its_declared_delay_then_the_36_hour_default(self):
        # 31 h old: within the 36 h the daily job declares (the old hard-coded 30 h would have failed it).
        data = feed_of(published="2026-09-26T13:00:00Z", schedule={"max_delay_hours": 36})
        self.assertEqual(self.run_all(self.feeds(feed_of(), data))[0], 0)
        status, message = self.run_all(self.feeds(feed_of(), feed_of(published="2026-09-26T07:00:00Z")))
        self.assertEqual(status, STALE)
        self.assertIn("Public data feed", message)
        self.assertIn("limit 36 h", message)
        status, message = self.run_all(self.feeds(feed_of(), feed_of(published="2026-09-26T13:00:00Z",
                                                                     schedule={"max_delay_hours": 24})))
        self.assertEqual(status, STALE)
        self.assertIn("limit 24 h", message)

    def test_fresh_feed_with_every_buoy_retained_past_limit_is_degraded(self):
        live = feed_of(source("diablo", "observation", "retained", OLD), source("offshore", "observation", "retained", OLD))
        status, message = self.run_all(self.feeds(live, feed_of(published="2026-09-27T05:00:00Z")))
        self.assertEqual(status, DEGRADED)
        self.assertIn("is fresh", message)
        self.assertIn("FAIL diablo", message)
        self.assertIn("FAIL offshore", message)

    def test_unreachable_public_route_reads_sources_from_github_copy(self):
        (lp, lg), (dp, dg) = self.urls("conditions"), self.urls("data")
        live = feed_of(source("diablo", "observation", "retained", "2026-09-27T04:00:00Z"))
        data = feed_of(published="2026-09-27T05:00:00Z")
        status, message = self.run_all({lp: OSError("503"), lg: live, dp: data, dg: data})
        self.assertEqual(status, STALE | DEGRADED)
        self.assertIn("Live conditions feed (GitHub copy)", message)

    def test_region_feeds_are_checked_per_region(self):
        fresh = feed_of(source("diablo", "observation", "ok", RECENT))
        data = feed_of(published="2026-09-27T05:00:00Z")
        # Big Sur loses one of two buoys (partial); Crescent City loses both (whole kind: fails).
        big_sur = feed_of(source("buoy-46028", "observation", "stale", OLD), source("buoy-46239", "observation", "ok", RECENT))
        crescent = feed_of(source("buoy-46027", "observation", "stale", OLD), source("buoy-46027-spectrum", "observation", "stale", OLD))
        feeds = self.feeds(fresh, data, big_sur_coast=big_sur, crescent_city=crescent)
        status, message = self.run_all(feeds, [("big-sur-coast", False)])
        self.assertEqual(status, PARTIAL, message)
        self.assertIn("Public Live regional feed big-sur-coast is fresh", message)
        self.assertIn("over buoy-46028", message)
        status, message = self.run_all(feeds, [("big-sur-coast", False), ("crescent-city", False)])
        self.assertEqual(status, PARTIAL, message)  # preview regions never fail the run
        status, message = self.run_all(feeds, [("big-sur-coast", False), ("crescent-city", True)])
        self.assertEqual(status, DEGRADED | PARTIAL, message)
        self.assertIn("Live regional feed crescent-city: every observation source degraded past 12 h", message)
        # Grouping is per region: one region's healthy buoy does not rescue another's.
        self.assertNotIn("FAIL buoy-46239", message)

    def test_stale_region_feed_fails_only_for_an_active_region(self):
        fresh, data = feed_of(), feed_of(published="2026-09-27T05:00:00Z")
        old = feed_of(published="2026-09-27T12:00:00Z")
        feeds = self.feeds(fresh, data, big_sur_coast=old)
        status, message = self.run_all(feeds, [("big-sur-coast", False)])
        self.assertEqual(status, PARTIAL)
        self.assertIn("big-sur-coast is stale", message)
        self.assertIn("not an active region; reported, does not fail", message)
        self.assertEqual(self.run_all(feeds, [("big-sur-coast", True)])[0], STALE)

    def test_unreadable_region_route_reads_sources_from_github_copy(self):
        fresh, data = feed_of(), feed_of(published="2026-09-27T05:00:00Z")
        feeds = self.feeds(fresh, data)
        public, github = self.region_urls("big-sur-coast")
        feeds.update({public: OSError("503"), github: feed_of(source("alerts", "advisory", "failed"))})
        status, message = self.run_all(feeds, [("big-sur-coast", False)])
        self.assertEqual(status, PARTIAL)
        self.assertEqual(self.run_all(feeds, [("big-sur-coast", True)])[0], STALE | DEGRADED)
        self.assertIn("big-sur-coast could not be fetched", message)
        self.assertIn("Live regional feed big-sur-coast (GitHub copy): every advisory source", message)

    def test_live_only_checks_only_the_live_age(self):
        live = feed_of(source("diablo", "observation", "retained", "2026-09-27T04:00:00Z"), published="2026-09-27T19:40:00Z")
        site = self.site({f"{self.BASE}/feeds/conditions/latest.json": live, FEED: live})
        with self.assertRaises(SystemExit) as exited:
            main(["--public-base", self.BASE, "--live-only", "--max-age-hours", "1.25"], site, NOW)
        self.assertEqual(exited.exception.code, 0)

    def test_partial_outage_exits_zero_and_reports_it(self):
        live = feed_of(source("diablo", "observation", "retained", OLD), source("offshore", "observation", "ok", RECENT))
        data = feed_of(published="2026-09-27T05:00:00Z")
        site = self.site(self.feeds(live, data))
        with tempfile.TemporaryDirectory() as tmp, patch("scripts.check_feed_freshness.published_regions", return_value=[]):
            report = Path(tmp) / "report.json"
            with self.assertRaises(SystemExit) as exited:
                main(["--public-base", self.BASE, "--report", str(report)], site, NOW)
            self.assertEqual(exited.exception.code, 0)
            self.assertEqual(json.loads(report.read_text()), {"stale": False, "degraded": False, "partial": True, "stale_feeds": []})
            # Both buoys out fails the run, and the report says why.
            live["sources"]["offshore"] = source("offshore", "observation", "stale", OLD)
            with self.assertRaises(SystemExit) as exited:
                main(["--public-base", self.BASE, "--report", str(report)], site, NOW)
            self.assertEqual(exited.exception.code, DEGRADED)
            self.assertEqual(json.loads(report.read_text()), {"stale": False, "degraded": True, "partial": False, "stale_feeds": []})


if __name__ == "__main__":
    unittest.main()
