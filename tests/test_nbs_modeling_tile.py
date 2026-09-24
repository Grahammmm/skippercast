import tempfile
import unittest
from pathlib import Path

from scripts.audit_nbs_modeling_tile import audit, item_year, verified_file


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
