"""F04-12: an omitted critical source group is missing, not healthy.

Contract protected: the freshness check compares each feed with the critical kinds that feed is
reviewed to carry (catalog/feed-health.json `required_kinds`). The believable bug: the denominator
of failing_kinds holds only sources that made it into the feed, so an assembler that drops the whole
advisory group yields no failing kind and a fresh published_at hides it. Controls are synthetic
feeds; nothing is fetched.
"""
from datetime import datetime, timezone
import unittest

from scripts.check_feed_freshness import (DEGRADED, HEALTH, PARTIAL, check_feed, check_region, failing_kinds, missing_kinds,
                                          required_kinds_of, source_verdict)

NOW = datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc)
BUILT = "2026-09-27T19:37:00Z"
RECENT = "2026-09-27T19:00:00Z"
FOUR = ("observation", "prediction", "advisory", "forecast")


def source(ident, kind, status="ok"):
    return {"id": ident, "kind": kind, "status": status, "checked_at": BUILT, "data": {"sample_at": RECENT}}


def feed_of(*kinds):
    sources = {f"{kind}-1": source(f"{kind}-1", kind) for kind in kinds}
    return {"published_at": BUILT, "generated_at": BUILT, "sources": sources}


def checked(name, feed):
    url = f"https://site.example/feeds/{HEALTH['feeds'][name]['path']}"
    return check_feed(name, url, url + "?github", NOW, lambda _url: feed)


class MissingGroupTests(unittest.TestCase):
    def test_reviewed_expectations_come_from_the_shared_catalog(self):
        # Worker and Python read the same file; the live feeds carry buoys only, the daily feed all four kinds.
        self.assertEqual(required_kinds_of(HEALTH["feeds"]["conditions"]), ["observation"])
        self.assertEqual(required_kinds_of(HEALTH["regions"]), ["observation"])
        self.assertEqual(required_kinds_of(HEALTH["feeds"]["data"]), sorted(FOUR))
        with self.assertRaises(ValueError):
            required_kinds_of({"required_kinds": ["observatoin"]})  # a typo must not switch the check off
        with self.assertRaises(ValueError):
            required_kinds_of({"required_kinds": "advisory"})

    def test_negative_control_omitted_advisory_group_fails_with_a_fresh_stamp(self):
        feed = feed_of("observation", "prediction", "forecast")  # no advisory source at all; published 23 minutes ago
        self.assertEqual(missing_kinds(feed, FOUR), ["advisory"])
        self.assertEqual(failing_kinds(feed, 48, required_kinds=FOUR), ["advisory"])
        self.assertEqual(failing_kinds(feed, 48), [])  # the old denominator: nothing flagged
        bits, lines = source_verdict(feed, 48, "Daily", required_kinds=FOUR)
        self.assertEqual(bits, DEGRADED)
        self.assertIn("required advisory source group missing from the feed", lines[0])
        self.assertIn("partial coverage: forecast, observation, prediction still reporting", lines[0])
        self.assertEqual(lines[1], "- FAIL (advisory): MISSING, no advisory source in the feed (required for this feed)")
        status, message = checked("data", feed)
        self.assertEqual(status, DEGRADED)  # fresh feed, so only the missing group sets the bit
        self.assertIn("MISSING", message)

    def test_positive_control_every_required_group_present_is_quiet(self):
        status, message = checked("data", feed_of(*FOUR))
        self.assertEqual(status, 0)
        self.assertNotIn("MISSING", message)
        self.assertEqual(source_verdict(feed_of(*FOUR), 48, "Daily", required_kinds=FOUR), (0, []))

    def test_degraded_is_not_missing(self):
        # A present failed advisory is the old failing-kind case and keeps its own wording.
        feed = feed_of("observation", "prediction", "forecast")
        feed["sources"]["advisory-1"] = {"id": "advisory-1", "kind": "advisory", "status": "failed", "checked_at": BUILT, "data": None}
        bits, lines = source_verdict(feed, 48, "Daily", required_kinds=FOUR)
        self.assertEqual(bits, DEGRADED)
        self.assertIn("every advisory source degraded past 48 h", lines[0])
        self.assertNotIn("MISSING", "\n".join(lines))
        self.assertEqual(missing_kinds(feed, FOUR), [])

    def test_healthy_sibling_keeps_partial_coverage_and_degraded_sibling_still_reports(self):
        feed = feed_of("observation")  # daily feed lost every group but observation
        feed["sources"]["observation-2"] = source("observation-2", "observation", "stale")
        bits, lines = source_verdict(feed, 48, "Daily", required_kinds=FOUR)
        self.assertEqual(bits, DEGRADED)
        self.assertIn("required advisory, forecast, prediction source group missing", lines[0])
        self.assertIn("(partial coverage: observation still reporting)", lines[0])
        self.assertTrue(any(line.startswith("- warn observation-2") for line in lines))

    def test_optional_absent_groups_stay_quiet(self):
        # The live feed carries buoys only: advisory, prediction and forecast are not applicable to it.
        status, message = checked("conditions", feed_of("observation"))
        self.assertEqual(status, 0)
        self.assertNotIn("MISSING", message)
        # A feed without a required_kinds declaration expects nothing.
        self.assertEqual(source_verdict(feed_of("observation"), 12, "Live"), (0, []))
        self.assertEqual(required_kinds_of({}), [])

    def test_live_feed_without_buoys_fails_even_when_other_kinds_report(self):
        status, message = checked("conditions", feed_of("advisory", "forecast"))
        self.assertEqual(status, DEGRADED)
        self.assertIn("required observation source group missing", message)

    def test_unreadable_feed_reports_no_missing_kinds_and_empty_sources_fail_all(self):
        self.assertEqual(missing_kinds(None, FOUR), [])
        self.assertEqual(missing_kinds({"published_at": BUILT}, ["observation"]), ["observation"])

    def test_preview_region_missing_group_is_only_a_partial_outage(self):
        fetch = lambda _url: feed_of("advisory")  # noqa: E731 - no buoys in a region's live feed
        active, _ = check_region("morro-bay", True, "https://site.example", NOW, fetch)
        preview, _ = check_region("point-reyes", False, "https://site.example", NOW, fetch)
        self.assertEqual(active & DEGRADED, DEGRADED)
        self.assertEqual(preview, PARTIAL)


if __name__ == "__main__":
    unittest.main()
