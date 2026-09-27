import json
import unittest

from pyproj import Transformer
from shapely.geometry import box

from scripts.audit_ciap_video_block_overlap import measure


class CiapVideoBlockOverlapTests(unittest.TestCase):
    def test_precise_attributes_and_correlated_line_units(self):
        polygon = box(688100, 3906100, 688200, 3906200)
        to_geo = Transformer.from_crs("EPSG:32610", "EPSG:4326", always_xy=True)

        def feature(uid, x, y, line):
            lon, lat = to_geo.transform(x, y)
            return {"geometry": {"type": "Point", "coordinates": [round(lon, 4), round(lat, 4)]},
                    "properties": {"id": uid, "lon": lon, "lat": lat,
                                   "site": "PB5", "dive": 1, "line": line}}

        result = measure([polygon], "EPSG:32610", [feature(1, 688150, 3906150, 1),
                                                    feature(2, 688160, 3906160, 1),
                                                    feature(3, 688350, 3906150, 2)])
        self.assertEqual(result["video_fix_counts"], {"inside": 2, "within_100m": 2, "within_250m": 3})
        self.assertEqual(result["distinct_site_dive_line_units_within_250m"], 2)
        self.assertEqual(result["distinct_site_dive_units_within_250m"], 1)
        self.assertNotIn('"coordinates":', json.dumps(result))

    def test_duplicate_fix_is_rejected(self):
        polygon = box(688100, 3906100, 688200, 3906200)
        lon, lat = Transformer.from_crs("EPSG:32610", "EPSG:4326", always_xy=True).transform(688150, 3906150)
        feature = {"geometry": {"type": "Point", "coordinates": [lon, lat]},
                   "properties": {"id": 1, "lon": lon, "lat": lat}}
        with self.assertRaisesRegex(ValueError, "duplicated"):
            measure([polygon], "EPSG:32610", [feature, feature])


if __name__ == "__main__":
    unittest.main()
