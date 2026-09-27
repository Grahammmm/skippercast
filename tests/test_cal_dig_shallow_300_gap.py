import unittest

from scripts.audit_cal_dig_shallow_300_gap import build, summarize


def table(kind, depth):
    header = "FID,depth_mete,Longitude,Latitude,video_sequ," + ("concept" if kind == "biotic" else "Induration")
    return f"{header}\r\n0,{depth},-121.2,35.2,ROV 1,rockfish\r\n".encode()


class CalDigShallowGapTest(unittest.TestCase):
    def test_deep_original_points_do_not_support_shallow_spots(self):
        report = build(table("biotic", "370.9"), table("substrate", "371"))
        self.assertFalse(report["fishing_target"])
        self.assertEqual(report["sources"]["biotic"]["observations_in_200_300ft_depth_band"], 0)

    def test_new_shallow_observation_requires_spatial_review(self):
        with self.assertRaisesRegex(ValueError, "spatial review required"):
            summarize(table("substrate", "80"), "substrate")

    def test_negative_source_depth_is_not_shallow_support(self):
        raw = table("substrate", "-955.4") + b"1,371,-121.2,35.2,ROV 1,mud\r\n"
        summary = summarize(raw, "substrate")
        self.assertEqual(summary["negative_depth_rows_excluded"], 1)
        self.assertEqual(summary["minimum_nonnegative_observation_depth_m"], 371)

    def test_missing_essential_schema_fails(self):
        with self.assertRaisesRegex(ValueError, "schema changed"):
            summarize(b"Longitude,Latitude\n-121.2,35.2\n", "biotic")


if __name__ == "__main__":
    unittest.main()
