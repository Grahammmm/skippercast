import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np
from pyproj import CRS

SCRIPT = Path(__file__).parents[2] / "scripts" / "qualify_original_vr_window.py"
spec = importlib.util.spec_from_file_location("qualify_original_vr_window", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class NativeVRControls(unittest.TestCase):
    def test_original_masks_depth_uncertainty_and_support_bound(self):
        depth = np.array([[-10.0, -20.0, -91.44, -92.0, -10.0, np.nan]])
        unc = np.array([[0.2, 1.0, 0.1, 0.1, 1.01, 0.2]])
        inside = np.array([[True, True, True, True, True, True]])
        finite, qualified = tool.native_qualified_mask(depth, unc, 1.0, 1.0, inside)
        self.assertEqual(finite.tolist(), [[True, True, True, True, True, False]])
        self.assertEqual(qualified.tolist(), [[True, True, True, False, False, False]])
        finite, qualified = tool.native_qualified_mask(depth, unc, 1.0, 1.0,
                                                       np.array([[True, False, True, True, True, True]]))
        self.assertFalse(qualified[0, 1])

    def test_reviewed_direct_depth_is_separate_from_legacy_margin_rule(self):
        depth = np.array([[-91.44]])
        uncertainty = np.array([[0.1]])
        inside = np.array([[True]])
        _, direct = tool.native_qualified_mask(depth, uncertainty, 1.0, 1.0, inside)
        _, legacy = tool.native_qualified_mask(depth, uncertainty, 1.0, 1.0, inside,
                                               "uncertainty-plus-planning-margin", 2.0)
        self.assertTrue(direct[0, 0])
        self.assertFalse(legacy[0, 0])
        with self.assertRaisesRegex(ValueError, "does not accept"):
            tool.native_qualified_mask(depth, uncertainty, 1.0, 1.0, inside, "direct-depth", 0.0)

    def test_unknown_native_spacing_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unsupported native resolution"):
            tool.native_qualified_mask(np.array([[-10.]]), np.array([[.1]]), 3.0, 3.0,
                                      np.array([[True]]), 0.0)

    def test_exact_spacing_and_native_band_are_distinct_without_rounding(self):
        self.assertFalse(tool.native_resolution_allowed(1.02048, 1.02048, "exact-1-2-4m"))
        self.assertTrue(tool.native_resolution_allowed(1.02048, 1.02048, "source-native-1-to-4m-band"))
        self.assertEqual(f"{1.02048:g}", "1.02048")

    def test_native_band_flows_through_qualification_without_rounding(self):
        depth = np.array([[-20.0]])
        uncertainty = np.array([[0.3]])
        inside = np.array([[True]])
        _, qualified = tool.native_qualified_mask(
            depth, uncertainty, 1.02048, 1.02048, inside,
            spacing_policy="source-native-1-to-4m-band")
        self.assertTrue(qualified[0, 0])
        self.assertEqual(f"{1.02048:g}", "1.02048")
        with self.assertRaisesRegex(ValueError, "unsupported native resolution"):
            tool.native_qualified_mask(depth, uncertainty, 1.02048, 1.02048, inside,
                                       spacing_policy="exact-1-2-4m")

    def test_source_hash_is_required_and_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.bin"
            path.write_bytes(b"synthetic original source")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(tool.verify_source_hash(path, digest), digest)
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                tool.verify_source_hash(path, "0" * 64)

    def test_selected_cell_limit_is_bounded(self):
        self.assertEqual(tool.add_selected(7, 3, 10), 10)
        with self.assertRaisesRegex(ValueError, "limit exceeded"):
            tool.add_selected(7, 4, 10)
        with self.assertRaisesRegex(ValueError, "limit exceeded"):
            tool.add_selected(0, 1, 262145)

    def test_full_grid_read_budget_is_separate_and_fails_before_read(self):
        self.assertEqual(tool.add_full_grid_slots(100, 50, 200), 150)
        with self.assertRaisesRegex(ValueError, "full native supergrid-slot limit"):
            tool.add_full_grid_slots(100, 101, 200)

    def test_semantic_crs_rejects_nested_geographic_authority(self):
        projected = CRS.from_epsg(26911)
        self.assertTrue(tool.semantic_projected_crs_matches(projected, CRS.from_epsg(26911)))
        self.assertFalse(tool.semantic_projected_crs_matches(projected, CRS.from_epsg(4269)))

    def test_gdal_bounds_authority_wins_over_shifted_metadata_bounds(self):
        metadata_bounds = (0, 0, 10, 10)
        gdal_bounds = (10.1, 0, 20.1, 10)
        window = (20, 1, 21, 2)
        self.assertFalse(tool.bounds_intersect(metadata_bounds, window))
        self.assertTrue(tool.bounds_intersect(gdal_bounds, window))


if __name__ == "__main__":
    unittest.main()
