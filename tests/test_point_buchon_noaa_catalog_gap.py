import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import audit_point_buchon_noaa_catalog_gap as audit


ROOT = Path(__file__).resolve().parents[1]


class PointBuchonCatalogGapTests(unittest.TestCase):
    def test_catalog_change_requires_review_before_source_queue_changes(self):
        deep = json.loads((ROOT / "dist/data/central-deep-original-300-refutation.json").read_text())
        with patch.object(audit, "hard_rugose_envelope", return_value=(804337, [-121, 35, -120.8, 35.3])):
            def changed(_):
                return {"health": {"status": "ok"}, "sectors": [{"surveys": [{"id": "W00479"},
                                                                                 {"id": "H99999"}]}]}
            with self.assertRaisesRegex(ValueError, "catalog lead set changed"):
                audit.build(Path("unused"), Path("unused"), deep, scan_fn=changed)

    def test_published_envelope_gap_is_research_only(self):
        report = json.loads((ROOT / "dist/data/point-buchon-noaa-catalog-envelope-gap.json").read_text())
        self.assertEqual(report["original_hard_rugose_cells"], 804337)
        self.assertEqual(report["bag_survey_ids_returned"], ["W00479"])
        self.assertEqual(report["qualified_waypoints"], 0)
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        self.assertIn("not an exhaustive inventory", report["limitation"])


if __name__ == "__main__":
    unittest.main()
