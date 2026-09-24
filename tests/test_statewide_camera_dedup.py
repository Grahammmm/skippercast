"""Overlapping survey products cannot multiply original camera evidence."""
import copy
import unittest

from scripts.audit_statewide_regular_camera import deduplicate_camera_windows


def pair(indices, positives, sector):
    return {
        "cruise": "f208nc", "camera_archive_sha256": "a" * 64,
        "sector_id": sector, "counts": {"qualified_rocky_camera_windows": len(indices)},
        "transects": [{"date": "2008-09-07", "line": "115", "window_count": len(indices),
                       "camera_record_indices": indices,
                       "rockfish_positive_record_indices": positives,
                       "lingcod_positive_record_indices": [],
                       "rockfish_positive_windows": len(positives),
                       "lingcod_positive_windows": 0}],
    }


class CameraDedupTests(unittest.TestCase):
    def test_one_original_window_in_two_bags_counts_once(self):
        rows = [pair([4, 5], [4], "arena-bodega"),
                pair([5, 6], [6], "arena-bodega")]
        result = deduplicate_camera_windows(rows)
        self.assertEqual(result["pair_attributed_qualified_windows"], 4)
        self.assertEqual(result["distinct_original_camera_windows"], 3)
        self.assertEqual(result["repeated_pair_attributions"], 1)
        self.assertEqual(result["distinct_original_camera_transects"], 1)
        self.assertEqual(result["distinct_historical_rockfish_positive_windows"], 2)

    def test_conflicting_or_missing_record_ids_fail(self):
        row = pair([4, 5], [4], "arena-bodega")
        altered = copy.deepcopy(row)
        altered["transects"][0]["camera_record_indices"] = [4, 4]
        with self.assertRaisesRegex(ValueError, "indices"):
            deduplicate_camera_windows([altered])
        altered = copy.deepcopy(row)
        altered["transects"][0]["rockfish_positive_record_indices"] = [999]
        with self.assertRaisesRegex(ValueError, "Positive"):
            deduplicate_camera_windows([altered])
        altered = copy.deepcopy(row)
        altered["camera_archive_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "different camera archive bytes"):
            deduplicate_camera_windows([row, altered])


if __name__ == "__main__":
    unittest.main()
