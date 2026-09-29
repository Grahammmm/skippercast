import unittest

from research.scripts.audit_point_buchon_vdatum_grid_bridge import summarize


class PointBuchonVDatumGridBridgeTest(unittest.TestCase):
    def test_reports_raw_grid_shortcut_residual_not_a_correction(self):
        rows = [{"api_navd88_to_mllw": .14, "api_navd88_to_lmsl": -.70,
                 "api_lmsl_to_mllw_step": .84, "raw_grid_mllw_minus_tss": .002,
                 "api_minus_raw_grid_shortcut": .138, "raw_grid_negative_mllw": .86,
                 "api_tidal_step_minus_raw_grid_negative_mllw": -.02},
                {"api_navd88_to_mllw": .15, "api_navd88_to_lmsl": -.69,
                 "api_lmsl_to_mllw_step": .84, "raw_grid_mllw_minus_tss": .003,
                 "api_minus_raw_grid_shortcut": .147, "raw_grid_negative_mllw": .86,
                 "api_tidal_step_minus_raw_grid_negative_mllw": -.02}]
        result = summarize(rows)
        self.assertEqual(result["api_minus_raw_grid_shortcut_range_m"], [.138, .147])
        self.assertEqual(result["raw_grid_mllw_minus_tss_range_m"], [.002, .003])

    def test_no_samples_cannot_imply_zero_residual(self):
        with self.assertRaises(ValueError):
            summarize([])


if __name__ == "__main__":
    unittest.main()
