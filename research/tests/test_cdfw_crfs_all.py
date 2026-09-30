import unittest

from research.scripts import audit_cdfw_crfs_all as audit


def feature(oid, block, all_value, kept_value):
    return {"attributes": {"OBJECTID": oid, "BlockBox": block, "Catch": "All",
                           "Trip": "All", "All_21_24": all_value,
                           "Kept_21_24": kept_value, "Samples": 3},
            "geometry": {"rings": [[[-121.01, 35.4], [-121.0, 35.4],
                                    [-121.0, 35.41], [-121.01, 35.41], [-121.01, 35.4]]]}}


class AllSpeciesCRFSAuditTests(unittest.TestCase):
    def test_unavailable_is_not_zero_and_all_species_scope_is_explicit(self):
        anomaly = feature(4098, "489-233", 0, 0)
        anomaly["geometry"]["rings"][0][1][0] = -120.95
        rows, outside, anomalous = audit.summarize(
            [feature(1, "A", -9999, -9999), feature(2, "B", 2.5, 0), anomaly],
            [{"id": "one", "latitude": [35, 36]}])
        self.assertEqual(outside, 0)
        self.assertEqual(anomalous, [{"object_id": 4098, "block_box": "489-233"}])
        self.assertEqual(rows[0]["reported_blocks"], 2)
        self.assertEqual(rows[0]["blocks_2021_2024_all_catch"], {"positive": 1, "unavailable": 1})
        self.assertEqual(rows[0]["blocks_2021_2024_kept_catch"], {"unavailable": 1, "zero": 1})
        wrong_scope = feature(3, "C", 1, 1)
        wrong_scope["attributes"]["Catch"] = "RCGL"
        with self.assertRaisesRegex(ValueError, "scope changed"):
            audit.summarize([wrong_scope], [{"id": "one", "latitude": [35, 36]}])

    def test_duplicate_block_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            audit.summarize([feature(1, "A", 1, 1), feature(2, "A", 1, 1)],
                            [{"id": "one", "latitude": [35, 36]}])


if __name__ == "__main__":
    unittest.main()
