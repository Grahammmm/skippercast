"""Original Big Creek terrain evidence stays research-only and source-bound."""
import json
from pathlib import Path
import unittest

from research.scripts.audit_bigcreek_original_grids import ARCHIVE_SHA256, LOCATIONS


ROOT = Path(__file__).resolve().parents[1]


class BigCreekOriginalGridsTest(unittest.TestCase):
    def test_original_grid_receipt_is_not_a_fishing_layer(self):
        receipt = json.loads((ROOT / "dist/data/bigcreek-lopez-original-300-research.json").read_text())
        candidate = json.loads((ROOT / "catalog/candidates/csumb-bigcreek-lopez-original-grids.json").read_text())
        self.assertEqual(receipt["source_archive_sha256"], ARCHIVE_SHA256)
        self.assertEqual({row["survey_area"] for row in receipt["areas"]}, {row[0] for row in LOCATIONS})
        self.assertEqual(receipt["source_grid_vertical_datum"], "NAVD88 Geoid09")
        self.assertFalse(receipt["fishing_target"])
        self.assertFalse(receipt["exportable"])
        self.assertFalse(candidate["rights"]["redistribution_reviewed"])
        self.assertEqual(candidate["region_ids"], ["big-sur-coast"])

    def test_lopez_has_a_research_lead_with_held_rank(self):
        receipt = json.loads((ROOT / "dist/data/bigcreek-lopez-original-300-research.json").read_text())
        lopez = next(row for row in receipt["areas"] if row["survey_area"] == "LopezPt")
        self.assertEqual([row["source_grid_resolution_m"] for row in lopez["tiers"]], [2, 5])
        self.assertEqual([row["derived_rough_cells_outside_mpa_plus_75m"] for row in lopez["tiers"]],
                         [36806, 63])
        self.assertEqual(lopez["named_uncertainty_grids_in_bathy_zip"], [])
        self.assertEqual(receipt["cdfw_mpa_names"], ["Big Creek SMCA", "Big Creek SMR"])
        self.assertTrue(all(row["derived_rough_cells_outside_mpa_plus_75m"] <=
                            row["derived_rough_cells"] for area in receipt["areas"] for row in area["tiers"]))
        queue = json.loads((ROOT / "dist/data/central-source-acquisition-queue.json").read_text())
        big_sur = next(row for row in queue["sectors"] if row["sector_id"] == "big-sur")
        lead = big_sur["bigcreek_lopez_original_grids"]
        self.assertEqual(big_sur["priority_tier"], 2)
        self.assertEqual(lead["lopez_rough_dem_cells_outside_current_mpa_plus_75m"], 36869)
        self.assertFalse(lead["fishing_target"])
        self.assertFalse(lead["exportable"])


if __name__ == "__main__":
    unittest.main()
