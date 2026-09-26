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

    def test_source_queue_keeps_native_band_leads_on_hold(self):
        result = sources.build(ROOT)
        self.assertEqual(result["status"], "research-only")
        self.assertEqual(len(result["sectors"]), 6)
        self.assertIn("not measured 25–300 ft raster coverage", result["method_note"])
        self.assertTrue(all(row["noaa_catalog_leads_with_bag_links"] <= row["noaa_catalog_lead_count"]
                            for row in result["sectors"]))
        pigeon = result["sectors"][0]
        self.assertNotIn("F00600", pigeon["noaa_filename_fine_grid_leads"])
        self.assertEqual(pigeon["noaa_original_300ft_depth_refutations"][0]["survey_id"], "F00600")
        self.assertEqual({row["survey_id"] for row in pigeon["noaa_no_measured_cells_in_17_monterey_outlines"]},
                         {"W00431", "W00433", "W00444", "W00447"})
        self.assertEqual(pigeon["noaa_original_300ft_depth_leads"][0]["survey_id"], "W00614")
        self.assertGreater(pigeon["noaa_original_300ft_depth_leads"][0]["eligible_supergrid_center_bounds"][1], 37.1)
        conception = result["sectors"][-1]
        self.assertEqual(conception["noaa_original_200_300ft_sector_refutations"][0]["survey_id"], "H11951")
        self.assertEqual(set(conception["noaa_filename_fine_grid_leads"]),
                         {"H11951", "H11952", "H11953"})
        self.assertEqual({row["survey_id"] for row in conception["noaa_reviewed_vr_fine_grids_outside_sector"]},
                         {"F00844", "W00341"})
        self.assertEqual(next(row for row in conception["noaa_reviewed_vr_fine_grids_outside_sector"]
                              if row["survey_id"] == "F00844")["uninspected_candidate_urls"], [])
        big_sur = next(row for row in result["sectors"] if row["sector_id"] == "big-sur")
        self.assertEqual(big_sur["bluetopo_rat_tile_count"], 12)
        self.assertGreater(big_sur["ncei_multibeam_footprint_lead_count"], 0)
        self.assertIn("W00479_MB_VR_MLLW_1of1", big_sur["bluetopo_rat_historical_hydrography_ids"])
        self.assertTrue(big_sur["bluetopo_rat_coastal_dem_ids"])
        self.assertEqual({row["source_id"] for row in big_sur["csumb_native_band_leads"]},
                         {"csumb-bss-block08", "csumb-bss-block12", "csumb-bss-block13"})
        south = next(row for row in result["sectors"] if row["sector_id"] == "sur-san-simeon")
        block02 = next(row for row in south["csumb_native_band_leads"]
                       if row["source_id"] == "csumb-bss-block02")
        self.assertEqual(block02["measured_200_300ft_navd88_comparison_cells"], 1_987_547)
        self.assertEqual(block02["release_status"], "datum-uncertainty-rights-hold")
        estero = next(row for row in result["sectors"] if row["sector_id"] == "cambria-morro")
        lead = estero["estero_independent_depth_character_lead"]
        self.assertEqual(lead["nominal_200_300ft_depth_cells"], 9_593_612)
        self.assertEqual(lead["nominal_200_300ft_independent_hard_rugose_overlap_cells"], 24_210)
        self.assertFalse(lead["fishing_target"])
        self.assertFalse(lead["exportable"])
        self.assertTrue(all(row["estero_independent_depth_character_lead"] is None
                            for row in result["sectors"] if row["sector_id"] != "cambria-morro"))

    def test_unreviewed_bluetopo_lead_blocks_queue(self):
        original = sources.read

        def stale_report(path):
            result = original(path)
            if str(path).endswith("central-bluetopo-upstream-source-leads.json"):
                result = copy.deepcopy(result)
                result["scheme_sha256"] = "0" * 64
            return result

        with patch.object(sources, "read", side_effect=stale_report):
            with self.assertRaisesRegex(ValueError, "receipt is missing or stale"):
                sources.build(ROOT)

    def test_changed_csumb_uncertainty_inventory_blocks_queue(self):
        original = sources.read

        def changed_report(path):
            result = original(path)
            if str(path).endswith("csumb-bss-native-source-review.json"):
                result = copy.deepcopy(result)
                result["sources"][0]["archive_product_inventory"]["named_uncertainty_or_cube_surface_products"] = ["new CUBE surface"]
            return result

        with patch.object(sources, "read", side_effect=changed_report):
            with self.assertRaisesRegex(ValueError, "CSUMB native 300 ft source audit"):
                sources.build(ROOT)

    def test_new_fine_refinement_invalidates_f00844_refutation(self):
        original = sources.read

        def changed_report(path):
            result = original(path)
            if str(path).endswith("f00844-original-fifth-bag-review.json"):
                result = copy.deepcopy(result)
                result["native"]["refinement_grids_at_most_4m"] = 1
            return result

        with patch.object(sources, "read", side_effect=changed_report):
            with self.assertRaisesRegex(ValueError, "F00844 fifth BAG"):
                sources.build(ROOT)

    def test_deep_noaa_cells_near_pigeon_point_are_not_fishing_spots(self):
        receipt = sources.read(ROOT / "dist/data/w00614-original-300-pigeon-monterey-review.json")
        self.assertGreater(receipt["counts"]["depth_uncertainty_qualified_200_300ft_cells"], 100000)
        self.assertGreater(receipt["eligible_supergrid_center_bounds"][1], 37.1)
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])

    def test_measured_cell_invalidates_monterey_bag_refutation(self):
        original = sources.read

        def changed_report(path):
            result = original(path)
            if str(path).endswith("w00444-monterey-original-bag-overlap.json"):
                result = copy.deepcopy(result)
                result["outlines_with_measured_cells"] = 1
            return result

        with patch.object(sources, "read", side_effect=changed_report):
            with self.assertRaisesRegex(ValueError, "overlap refutation failed"):
                sources.build(ROOT)

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
