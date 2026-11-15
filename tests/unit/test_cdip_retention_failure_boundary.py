"""A malformed retained CDIP feed must not escape collect_site/collect or discard healthy sites."""

from datetime import timedelta
import json
from unittest import TestCase

from skippercast.http import FakeSession
from skippercast.pipeline import cdip_nearshore as cdip
from tests.unit.test_cdip_nearshore import BINDING, NOW, PISMO, parse, routes

REGION = "morro-bay"


def pismo_record(age=timedelta(hours=1), **changes):
    return {**parse(), **PISMO, "fetchedAt": cdip.iso(NOW - age), **changes}


def collect(previous):
    """PISMO's fetch fails (no route); BINDING (the healthy sibling) parses."""
    return cdip.collect(REGION, [PISMO, BINDING], NOW, previous, session=FakeSession(routes(BINDING)))


class RetentionFailureBoundaryTests(TestCase):
    def assert_failed_site_alone_degraded(self, feed):
        failed, healthy = feed["nearshore"]
        self.assertEqual(feed["health"], {"status": "degraded", "issues": ["cdip-SL097"]})
        self.assertEqual((failed["availability"], failed["hours"]), ("error", []))
        self.assertEqual((healthy["availability"], healthy["hours"]), ("available", parse()["hours"]))
        self.assertEqual([s["outcome"] for s in feed["sources"]], ["error", "ok"])

    def test_non_list_previous_containers_cannot_escape_or_supply_a_record(self):
        record = pismo_record()
        for container in (7, 0, True, "SL097", None, {"SL097": record}, {"id": "SL097", **record}):
            with self.subTest(container=container):
                self.assert_failed_site_alone_degraded(collect({"region_id": REGION, "nearshore": container}))
                site, _ = cdip.collect_site(FakeSession({}), PISMO, NOW, {"nearshore": container})
                self.assertEqual(site["availability"], "error")
        for previous in (None, "feed", [record], 7):
            with self.subTest(previous=previous):
                self.assertIsNone(cdip._retained(previous, PISMO, NOW))
                self.assert_failed_site_alone_degraded(collect(previous))

    def test_malformed_list_entries_cannot_supply_retained_data(self):
        entries = [None, 7, "SL097", [record := pismo_record()], {}, {"id": "SL097"},
                   {**record, "fetchedAt": 12}, {**record, "fetchedAt": "yesterday"}, {**record, "hours": "none"},
                   {**record, "availability": "error"}, {**record, "id": ["SL097"]}]
        feed = collect({"region_id": REGION, "nearshore": entries})
        self.assert_failed_site_alone_degraded(feed)
        self.assertNotIn("kept the previous record", feed["sources"][0]["error"])

    def test_valid_recent_matching_record_is_kept_unchanged_but_expired_or_mismatched_is_not(self):
        record = pismo_record()
        original = json.dumps(record, sort_keys=True)
        # A malformed sibling entry in the same list does not stop the valid one being found.
        feed = collect({"region_id": REGION, "nearshore": [None, record]})
        self.assertEqual(json.dumps(feed["nearshore"][0], sort_keys=True), original)
        self.assertEqual(feed["nearshore"][0]["fetchedAt"], record["fetchedAt"])
        self.assertEqual(feed["health"], {"status": "degraded", "issues": ["cdip-SL097"]})
        self.assertIn("kept the previous record fetched", feed["sources"][0]["error"])
        self.assertEqual(feed["nearshore"][1]["availability"], "available")
        for label, stale in (("expired", pismo_record(age=cdip.RETAIN_FOR)), ("future", pismo_record(age=-timedelta(hours=1))),
                             ("other name", pismo_record(name="Elsewhere")), ("other area", pismo_record(areaId="north")),
                             ("other id", pismo_record(id="SL999"))):
            with self.subTest(label):
                self.assert_failed_site_alone_degraded(collect({"region_id": REGION, "nearshore": [stale]}))
        self.assert_failed_site_alone_degraded(collect({"region_id": "other-region", "nearshore": [record]}))
