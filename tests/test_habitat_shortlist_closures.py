import unittest
from datetime import datetime, timezone

from scripts.audit_habitat_shortlist_closures import audit


def square(x, y, width=0.001):
    return {"type": "Polygon", "coordinates": [[[x, y], [x + width, y],
            [x + width, y + width], [x, y + width], [x, y]]]}


class FreshClosureAuditTests(unittest.TestCase):
    def sources(self, *, mpa_x=-124.4, federal_x=-124.3, status="ok"):
        stamp = datetime.now(timezone.utc).isoformat()
        queue = {"scope": "original-habitat-site-review-queue", "fishing_target": False,
                 "source_context_outlines": 1, "research_shortlist_count": 1,
                 "research_shortlist": [{"context_id": "test-001", "survey_id": "H11975",
                                         "fishing_target": False}]}
        context = {"scope": "northern-native-noaa-usgs-hard-bottom-context",
                   "features": [{"geometry": square(-124.4, 40.4),
                                 "properties": {"id": "test-001", "survey_id": "H11975",
                                                "fishing_target": False}}]}
        mpa_features = [{"geometry": square(mpa_x, 40.4), "properties": {"NAME": f"MPA {i}"}}
                        for i in range(100)]
        coastal = {"sources": {"mpas": {"status": status, "data_retrieved_at": stamp,
                   "max_age_hours": 36, "data": {"feature_count": 100,
                   "source_url": "https://wildlife.ca.gov/mpa-test",
                   "geojson": {"features": mpa_features}}}}}
        features = [{"geometry": square(federal_x, 40.4),
                     "properties": {"area_type": "GEA"}} for _ in range(10)]
        federal = {"scope": "noaa-west-coast-groundfish-conservation-areas",
                   "status": "ok", "retrieved_at": stamp, "feature_count": 10,
                   "service_url": "https://maps.fisheries.noaa.gov/test",
                   "source_layers": [{} for _ in range(25)], "features": features}
        return queue, context, coastal, federal

    def test_mpa_nearby_holds_research_outline(self):
        result = audit(*self.sources())
        self.assertEqual(result["held_count"], 1)
        self.assertFalse(result["outlines"][0]["fishing_target"])

    def test_distant_closures_do_not_promote_research_outline(self):
        result = audit(*self.sources(mpa_x=-124.2))
        self.assertEqual(result["held_count"], 0)
        self.assertEqual(result["outlines"][0]["closure_screen"], "no-mapped-overlap-with-buffer")
        self.assertFalse(result["exportable"])

    def test_failed_mpa_refresh_fails_closed(self):
        with self.assertRaises(ValueError):
            audit(*self.sources(status="retained"))

    def test_geographic_crs_cannot_be_used_as_meter_buffer(self):
        with self.assertRaises(ValueError):
            audit(*self.sources(), projected_crs="EPSG:4326")


if __name__ == "__main__":
    unittest.main()
