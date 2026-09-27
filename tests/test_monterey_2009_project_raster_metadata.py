import json
from pathlib import Path
import unittest

from scripts.audit_monterey_2009_project_raster_metadata import evaluate


ROOT = Path(__file__).resolve().parents[1]


class ProjectRasterDatumScopeTest(unittest.TestCase):
    def test_unreviewed_project_xml_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "changed"):
            evaluate(b"<metadata><datum>MLLW</datum></metadata>")

    def test_northern_raster_datum_cannot_qualify_southern_gsf_lines(self):
        review = json.loads((ROOT / "dist/data/monterey-2009-project-raster-datum-scope.json").read_text())
        self.assertEqual(review["source_product"], "cmb_n_2mbathy")
        self.assertFalse(review["source_reported_accuracy"]["conservative_upper_product_error_bounded"])
        for ident in ("023", "046"):
            self.assertFalse(review["priority_outlines"][ident]["within_documented_raster_bbox"])
            self.assertFalse(review["priority_outlines"][ident]["selected_gsf_line_datum_proven"])
        self.assertFalse(review["mllw_depth_qualified"])
        self.assertFalse(review["fishing_target"])
        self.assertFalse(review["exportable"])


if __name__ == "__main__":
    unittest.main()
