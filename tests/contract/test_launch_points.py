"""Launch points: every published region gets a list, each point sits inside its
region and names a real forecast point, and the committed output is the build's."""
from copy import deepcopy
from pathlib import Path
import tempfile
from unittest import TestCase

from skippercast.platform.contracts import REPO, read_json, load_region
from skippercast.platform.launch_points import compile_launch_points, distance_nm, validate_launch_point


def catalog():
    return read_json(REPO / "catalog/launch-points.json")


class LaunchPointCatalog(TestCase):
    def test_morro_bay_and_avila_launches_are_catalogued_with_their_state_record(self):
        points = {p["id"]: p for p in catalog()["launch_points"] if p["region"] == "morro-bay"}
        self.assertEqual(set(points), {"morro-bay-public-launch", "port-san-luis-launch", "olde-port-beach"})
        for point in points.values():
            self.assertEqual(point["source"], "dbw")
            self.assertRegex(point["source_id"], r"^\d+$")
            self.assertIn("never navigation waypoints", catalog()["description"])
        self.assertEqual(points["morro-bay-public-launch"]["forecast_point"], "central")
        self.assertEqual(points["port-san-luis-launch"]["forecast_point"], "avila")
        self.assertEqual(points["olde-port-beach"]["kind"], "beach")

    def test_every_published_region_has_a_built_list_matching_the_catalog(self):
        regions = read_json(REPO / "dist/regions/index.json")["regions"]
        by_region = {}
        for point in catalog()["launch_points"]:
            by_region.setdefault(point["region"], []).append(point["id"])
        for entry in regions:
            built = read_json(REPO / "dist/regions" / entry["id"] / "launch-points.json")
            self.assertEqual(built["region_id"], entry["id"])
            self.assertEqual([p["id"] for p in built["launch_points"]], sorted(by_region.get(entry["id"], [])))
            self.assertEqual(set(built["sources"]), {p["source"] for p in built["launch_points"]})

    def test_a_point_is_refused_outside_its_region_or_with_an_unknown_forecast_point(self):
        region = load_region("morro-bay")
        sources = catalog()["sources"]
        good = next(p for p in catalog()["launch_points"] if p["id"] == "morro-bay-public-launch")
        validate_launch_point(good, region, sources)
        for change, message in [
            ({"latitude": 36.9}, "outside the morro-bay bounds"),
            ({"latitude": 35.84, "longitude": -121.94, "departure": {"latitude": 35.86, "longitude": -121.96, "note": ""}}, "departure lies outside"),
            ({"departure": {"latitude": 35.42, "longitude": -121.0, "note": ""}}, "more than 5 nm"),
            ({"forecast_point": "nowhere"}, "unknown forecast point"),
            ({"region": "crescent-city"}, "belongs to crescent-city"),
            ({"source": "hearsay"}, "unlisted source"),
        ]:
            with self.assertRaisesRegex(ValueError, message):
                validate_launch_point({**deepcopy(good), **change}, region, sources)

    def test_duplicate_ids_and_unknown_regions_stop_the_build(self):
        region = load_region("morro-bay")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "catalog").mkdir()
            base = catalog()
            point = next(p for p in base["launch_points"] if p["id"] == "morro-bay-public-launch")
            import json
            (root / "catalog/launch-points.json").write_text(json.dumps({**base, "launch_points": [point, point]}))
            with self.assertRaisesRegex(ValueError, "Duplicate launch point id"):
                compile_launch_points(root, [region])
            (root / "catalog/launch-points.json").write_text(json.dumps({**base, "launch_points": [{**point, "region": "atlantis"}]}))
            with self.assertRaisesRegex(ValueError, "unknown or draft region atlantis"):
                compile_launch_points(root, [region])
            (root / "catalog/launch-points.json").write_text(json.dumps({**base, "launch_points": [point]}))
            out = compile_launch_points(root, [region])
            self.assertEqual(set(out), {"morro-bay"})
            self.assertEqual(read_json(root / "dist/regions/morro-bay/launch-points.json")["launch_points"][0]["id"], point["id"])

    def test_distance_is_in_nautical_miles(self):
        # One degree of latitude is 60 nm.
        self.assertAlmostEqual(distance_nm(35.0, -121.0, 36.0, -121.0), 60.0, delta=0.1)
        self.assertEqual(distance_nm(35.3, -120.9, 35.3, -120.9), 0)
