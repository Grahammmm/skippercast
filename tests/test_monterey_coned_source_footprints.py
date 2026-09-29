import json
from pathlib import Path
import unittest

from research.scripts.audit_monterey_coned_source_footprints import build, gpkg_polygon
from research.lib.receipts import RECEIPTS


ROOT = Path(__file__).resolve().parents[1]


class ConedSourceFootprintTest(unittest.TestCase):
    def test_invalid_geometry_cannot_enter_lineage(self):
        with self.assertRaisesRegex(ValueError, "header"):
            gpkg_polygon(b"not a GeoPackage feature")

    def test_2017_compilation_does_not_count_as_independent_survey(self):
        receipt = json.loads((RECEIPTS / "monterey-coned-source-footprint-audit.json").read_text())
        self.assertEqual(receipt["research_outlines_checked"], 17)
        self.assertEqual(receipt["source_footprints_checked"], 67)
        self.assertEqual([r["source_object_id"] for r in receipt["outlines"]["023"]["source_footprints"]], [10])
        self.assertEqual([r["source_object_id"] for r in receipt["outlines"]["001"]["source_footprints"]], [6, 10, 29])
        self.assertFalse(receipt["outlines"]["023"]["independent_newer_measured_source_established"])
        self.assertFalse(receipt["cellwise_upper_uncertainty_obtained"])
        self.assertFalse(receipt["fishing_target"])
        source = ROOT / "var/review/CentCA_Topobathy_DEM_Spatial_Metadata.gpkg"
        if source.exists():
            self.assertEqual(build(source), receipt)


if __name__ == "__main__":
    unittest.main()
