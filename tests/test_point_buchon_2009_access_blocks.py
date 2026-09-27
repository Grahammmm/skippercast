import copy
import json
from pathlib import Path
import unittest

from scripts.audit_point_buchon_2009_access_blocks import stable


ROOT = Path(__file__).resolve().parents[1]


class PointBuchon2009AccessBlocksTests(unittest.TestCase):
    def setUp(self):
        self.report = json.loads((ROOT / "dist/data/point-buchon-2009-csumb-access-triage.json").read_text())

    def test_partial_screen_cannot_promote_waypoints(self):
        totals = self.report["totals"]
        self.assertEqual(totals["blocks"], 181)
        self.assertEqual(totals["mpa_margin_blocks"], 8)
        self.assertEqual(totals["all_three_clear_margin_blocks"], 173)
        self.assertEqual(totals["200-250ft_2m_cells"] +
                         totals["250-300ft_2m_cells"] +
                         totals["250-300ft_5m_cells"], 87257)
        self.assertEqual(self.report["noaa_enc_query_layers"], 18)
        self.assertEqual(self.report["qualified_waypoints"], 0)
        self.assertFalse(self.report["fishing_target"])
        self.assertFalse(self.report["exportable"])

    def test_changed_spatial_result_is_not_ignored_as_retrieval_noise(self):
        changed = copy.deepcopy(self.report)
        changed["source_checked_at"]["cdfw_mpa"] = "later"
        changed["input_sha256"]["mpas"] = "changed"
        self.assertEqual(stable(changed), stable(self.report))
        changed["official_geometry_sha256"]["cdfw_mpas"] = "changed"
        self.assertNotEqual(stable(changed), stable(self.report))
        changed = copy.deepcopy(self.report)
        changed["totals"]["mpa_margin_blocks"] += 1
        self.assertNotEqual(stable(changed), stable(self.report))


if __name__ == "__main__":
    unittest.main()
