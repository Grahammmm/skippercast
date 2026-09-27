import copy
import json
import unittest

from scripts.audit_ciap_rov_portal import build


def collection(count, crs, properties):
    feature = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-121.9, 36.6]},
               "properties": properties}
    return {"type": "FeatureCollection", "totalFeatures": count, "numberReturned": 2,
            "features": [copy.deepcopy(feature), copy.deepcopy(feature)],
            "crs": {"type": "name", "properties": {"name": crs}}}


class CiapPortalTests(unittest.TestCase):
    def test_video_and_aggregate_fish_remain_separate_and_unqualified(self):
        video = collection(236960, "urn:ogc:def:crs:EPSG::4326", {
            "site": "AS2", "location": "Asilomar", "dive": 117, "line": 130,
            "survey_date": "2016-09-16Z", "lon": -121.9, "lat": 36.6,
            "video": "sample", "survey_timestamp": "2016-09-16T18:33:29Z"})
        fish = collection(49076, "urn:ogc:def:crs:EPSG::3857", {
            "area_fish": 1.0, "count": 100, "taxa": 123})
        result = build(video, fish)
        self.assertEqual(result["central_video"]["total_features_reported"], 236960)
        self.assertEqual(result["fish_display"]["total_features_reported"], 49076)
        self.assertFalse(result["biological_fish_gate_satisfied"])
        self.assertEqual(result["qualified_waypoints"], 0)
        self.assertNotIn('"coordinates":', json.dumps(result))

    def test_fish_display_cannot_be_silently_replaced_with_raw_point_schema(self):
        video = collection(2, "urn:ogc:def:crs:EPSG::4326", {
            "site": "AS2", "location": "Asilomar", "dive": 117, "line": 130,
            "survey_date": "2016-09-16Z", "lon": -121.9, "lat": 36.6,
            "video": "sample", "survey_timestamp": "2016-09-16T18:33:29Z"})
        fish = collection(2, "urn:ogc:def:crs:EPSG::3857", {"species": "lingcod", "count": 1})
        with self.assertRaisesRegex(ValueError, "required fields"):
            build(video, fish)


if __name__ == "__main__":
    unittest.main()
