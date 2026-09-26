import json
from pathlib import Path
import unittest

from scripts import audit_estero_vdatum_spatial as spatial


ROOT = Path(__file__).resolve().parents[1]


class EsteroSpatialDatumTests(unittest.TestCase):
    def test_published_surface_diagnostic_does_not_convert_or_rank(self):
        report = json.loads((ROOT / "dist/data/estero-2012-vdatum-spatial-diagnostic.json").read_text())
        self.assertEqual(report["scope"], "estero-2012-vdatum-spatial-offset-diagnostic")
        self.assertEqual(report["sample_lattice"]["points"], 28)
        self.assertEqual(report["api_request_horizontal_frame"], "NAD83_2011")
        self.assertIn("CORS96", report["survey_horizontal_frame"])
        self.assertFalse(report["converted_source_raster"])
        self.assertFalse(report["full_error_budget_resolved"])
        self.assertEqual(report["qualified_waypoints"], 0)
        self.assertLess(report["offset_m"]["range"], 0.1)

    def test_incomplete_lattice_fails_closed(self):
        block = {"type": "Feature", "properties": {"fishing_target": False},
                 "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [3000, 0], [3000, 2000], [0, 2000], [0, 0]]]}}
        blocks = {"type": "FeatureCollection", "features": [block] * 60}
        with self.assertRaisesRegex(ValueError, "Incomplete VDatum spatial lattice"):
            spatial.summarize(blocks, [])


if __name__ == "__main__":
    unittest.main()
