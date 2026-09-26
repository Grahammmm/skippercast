import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PointBuchonDatumLeadsTests(unittest.TestCase):
    def test_related_datum_does_not_promote_usgs_depth(self):
        r = json.loads((ROOT / "dist/data/point-buchon-datum-provenance-leads.json").read_text())
        self.assertEqual(r["related_csmp_mbes_product"]["reported_vertical_datum"],
                         "NAVD88 (geoids03-09)")
        self.assertFalse(r["related_csmp_mbes_product"]["same_bytes_or_processing_lineage_as_usgs_release_proven"])
        self.assertEqual(r["usgs_published_raster"]["output_vertical_datum"], "unresolved")
        self.assertIsNone(r["usgs_published_raster"]["upper_depth_uncertainty_m"])
        self.assertEqual(r["usgs_published_raster"]["source_gridding_m_deeper_than_80m"], 5)
        self.assertEqual(r["qualified_waypoints"], 0)
        self.assertFalse(r["fishing_target"])
        self.assertFalse(r["exportable"])


if __name__ == "__main__":
    unittest.main()
