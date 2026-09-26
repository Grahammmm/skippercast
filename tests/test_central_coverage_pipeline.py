import copy
import pathlib
import unittest
from unittest.mock import patch

from scripts import build_central_coverage_ledger as coverage
from scripts import build_central_source_queue as sources


ROOT = pathlib.Path(__file__).resolve().parents[1]


class CentralCoveragePipelineTests(unittest.TestCase):
    def test_ledger_separates_research_outlines_from_exportable_targets(self):
        result = coverage.build(ROOT)
        self.assertEqual(result["totals"]["qualified_targets_at_or_under_200ft"], 132)
        self.assertEqual(result["totals"]["qualified_targets_200_to_300ft"], 0)
        self.assertEqual(result["totals"]["regions_without_qualified_targets"], 6)
        self.assertGreater(result["totals"]["research_only_outlines"], 0)
        for region in result["regions"]:
            if region["region_id"] != "morro-bay":
                self.assertEqual(region["fishing_coordinate_status"], "none-qualified")
            self.assertIn("not a survey footprint", region["bounds_meaning"])

    def test_failed_closure_screen_blocks_ledger(self):
        original = coverage.read

        def bad_read(path):
            result = original(path)
            if str(path).endswith("central-atlas-300-current-closure-screen.json"):
                result = copy.deepcopy(result)
                result["all_geometry_clear_of_screen_buffers"] = False
            return result

        with patch.object(coverage, "read", side_effect=bad_read):
            with self.assertRaisesRegex(ValueError, "closure screen failed"):
                coverage.build(ROOT)

    def test_source_queue_is_catalog_leads_only(self):
        result = sources.build(ROOT)
        self.assertEqual(result["status"], "research-only")
        self.assertEqual(len(result["sectors"]), 6)
        self.assertIn("not measured raster coverage", result["method_note"])
        self.assertTrue(all(row["noaa_catalog_leads_with_bag_links"] <= row["noaa_catalog_lead_count"]
                            for row in result["sectors"]))

    def test_new_deeper_waypoint_needs_explicit_qualification_receipt(self):
        original = coverage.read

        def deeper_read(path):
            result = original(path)
            if str(path).endswith("dist/data/atlas.json"):
                result = copy.deepcopy(result)
                result["fishing_depth_limit_ft"] = 300
                result["targets"][0]["neighborhood_depth_ft"] = [210, 250]
            return result

        with patch.object(coverage, "read", side_effect=deeper_read):
            with self.assertRaisesRegex(ValueError, "Unreviewed >200 ft target"):
                coverage.build(ROOT)


if __name__ == "__main__":
    unittest.main()
