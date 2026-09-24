import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "audit_cdfw_crfs_rcgl", Path(__file__).resolve().parents[1] / "scripts/audit_cdfw_crfs_rcgl.py"
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def feature(oid, block, all_value, kept_value):
    return {"attributes": {"OBJECTID": oid, "BlockBox": block, "Catch": "RCGL",
                           "Trip": "Bottomfish", "All_21_24": all_value,
                           "Kept_21_24": kept_value, "Samples": 3},
            "geometry": {"rings": [[[-121.01, 35.4], [-121.0, 35.4],
                                    [-121.0, 35.41], [-121.01, 35.41], [-121.01, 35.4]]]}}


class CRFSAuditTests(unittest.TestCase):
    def test_missing_recent_period_is_not_a_zero_catch(self):
        rows, outside = audit.summarize([feature(1, "A", -9999, -9999),
                                         feature(2, "B", 2.5, 0)],
                                        [{"id": "one", "latitude": [35, 36]}])
        self.assertEqual(outside, 0)
        self.assertEqual(rows[0]["reported_blocks"], 2)
        self.assertEqual(rows[0]["blocks_2021_2024_all_catch"],
                         {"positive": 1, "unavailable": 1})
        self.assertEqual(rows[0]["blocks_2021_2024_kept_catch"],
                         {"unavailable": 1, "zero": 1})

    def test_duplicate_reported_block_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            audit.summarize([feature(1, "A", 1, 1), feature(2, "A", 1, 1)],
                            [{"id": "one", "latitude": [35, 36]}])

    def test_clipped_nominal_block_still_has_bounded_location(self):
        feature_row = feature(1, "A", 1, 1)
        feature_row["geometry"]["rings"][0] = [
            [-121.01, 35.4], [-121.009, 35.4], [-121.009, 35.401],
            [-121.01, 35.401], [-121.01, 35.4]]
        lat, lon = audit.center_of_block(feature_row["geometry"])
        self.assertAlmostEqual(lat, 35.4005)
        self.assertAlmostEqual(lon, -121.0095)


if __name__ == "__main__":
    unittest.main()
