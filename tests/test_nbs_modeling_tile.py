import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.audit_nbs_modeling_tile import audit, is_measured_survey, item_year, qualified_mask, verified_file


class NbsModelingTileTest(unittest.TestCase):
    def test_survey_year(self):
        self.assertEqual(item_year("2016-05-28"), 2016)
        self.assertEqual(item_year(None), 0)
        self.assertEqual(item_year("unknown"), 0)

    def test_checksum_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tile.tiff"
            path.write_bytes(b"data")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                verified_file("https://example.invalid/tile", "0" * 64, path, False)

    def test_charts_and_interpolation_are_not_measured_surveys(self):
        row = {"coverage": "1", "bathy_coverage": "1", "source_survey_id": "H12345"}
        self.assertTrue(is_measured_survey(row))
        for source in ("H12345.interpolated", "Chart 18686", "NBS Generalization"):
            self.assertFalse(is_measured_survey({**row, "source_survey_id": source}))

    def test_depth_margin_and_original_contributor_are_required(self):
        sources = {1: {"coverage": "1", "bathy_coverage": "1", "source_survey_id": "H12345",
                       "survey_date_end": "2020-01-01"},
                   2: {"coverage": "0", "bathy_coverage": "0",
                       "source_survey_id": "H12345.interpolated", "survey_date_end": "2020-01-01"}}
        elevation = np.array([[-55.0, -60.0, -55.0]])
        uncertainty = np.array([[0.5, 1.0, 0.5]])
        contributor = np.array([[1, 1, 2]])
        self.assertEqual(qualified_mask(elevation, uncertainty, contributor, sources,
                                        resolution_m=4).tolist(), [[True, False, False]])

    def test_real_point_sur_tile_does_not_promote_old_or_interpolated_depth(self):
        root = Path(__file__).resolve().parents[1]
        scheme = root / "var/modeling-tile-scheme-20260923.gpkg"
        cache = root / "var/nbs-cache"
        if not scheme.exists() or not (cache / "BH44P5CD.tiff").exists():
            self.skipTest("Pinned original NOAA research assets are not cached")
        result = audit(scheme, "BH44P5CD", cache)
        self.assertGreater(result["counts"]["depth_25_to_200_ft_pixels"], 1_000_000)
        self.assertEqual(result["counts"]["qualified_screen_pixels"], 0)
        self.assertFalse(result["fishing_target"])


if __name__ == "__main__":
    unittest.main()
