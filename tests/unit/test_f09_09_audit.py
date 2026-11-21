"""F09-09: a failed CDIP fetch can only borrow usable hours for the current site."""

from datetime import datetime, timedelta, timezone
from unittest import TestCase

from skippercast.http import FakeSession, TransportError
from skippercast.pipeline import cdip_nearshore as cdip


class NearshoreRetentionTests(TestCase):
    def test_failed_fetch_retains_only_spatially_bound_usable_hours(self):
        # Labels alone used to admit a moved site or an available record with no usable samples.
        now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        binding = {"id": "ZZ123", "name": "Synthetic site", "areaId": "synthetic", "lat": 0, "lon": 0}
        sample = {"at": "2026-01-01T12:00:00.000Z", "waveFt": 0.0, "periodS": None, "directionDeg": None,
                  "qualityFlag": 1, "secondaryFlag": 2}
        prior = {**binding, "lat": 0.01, "lon": -0.01, "availability": "available",
                 "sourceId": "cdip-ZZ123", "kind": "forecast", "url": cdip.page_url("ZZ123"),
                 "freshness": "current", "fetchedAt": cdip.iso(now - timedelta(hours=1)),
                 "issuedAt": cdip.iso(now - timedelta(hours=2)), "hours": [sample]}
        for label, changes in (
            ("compatible", {}),
            ("latitude moved", {"lat": 1}),
            ("longitude moved", {"lon": 1}),
            ("malformed coordinates", {"lat": "0.01"}),
            ("empty hours", {"hours": []}),
            ("masked height", {"hours": [{**sample, "waveFt": None}]}),
            ("undated height", {"hours": [{**sample, "at": "unknown"}]}),
            ("height outside report window", {"hours": [{**sample, "at": "2026-01-01T08:00:00.000Z"}]}),
        ):
            with self.subTest(label=label):
                saved = {**prior, **changes}
                session = FakeSession({cdip.das_url("ZZ123"): TransportError("synthetic fetch failed")})
                site, attempt = cdip.collect_site(session, binding, now, {"nearshore": [saved]})
                self.assertEqual(attempt["outcome"], "error")
                self.assertIn("synthetic fetch failed", attempt["error"])
                self.assertNotIn("issuedAt", attempt)
                if not changes:
                    self.assertEqual(site, prior)
                    self.assertNotEqual(attempt["fetchedAt"], site["fetchedAt"])
                else:
                    self.assertEqual((site["availability"], site["hours"], site["issuedAt"]), ("error", [], None))
                    self.assertEqual((site["lat"], site["lon"]), (binding["lat"], binding["lon"]))
