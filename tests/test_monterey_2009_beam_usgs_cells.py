"""Original beam-to-cell matches remain research evidence, not spot ranks."""

import json
from pathlib import Path
import unittest

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import box
from shapely.ops import transform as transform_geometry

from scripts.build_central_300_qualification_plan import build
from scripts.audit_monterey_2009_beam_usgs_cells import join_outline


ROOT = Path(__file__).resolve().parents[1]


class BeamCellGate(unittest.TestCase):
    def test_beam_inside_outline_does_not_count_nearest_cell_center_outside(self):
        grid = from_origin(500000, 4000000, 2, 2)
        profile = {"driver": "GTiff", "height": 5, "width": 5, "count": 1,
                   "crs": "EPSG:26910", "transform": grid}
        to_geo = Transformer.from_crs("EPSG:26910", "EPSG:4326", always_xy=True).transform
        polygon = transform_geometry(to_geo, box(500001.5, 3999998.0, 500002.5, 4000000.0))
        lon, lat = to_geo(500002.1, 3999999.0)
        with MemoryFile() as depth_file, MemoryFile() as class_file:
            with depth_file.open(**profile, dtype="float32") as bathy, class_file.open(**profile, dtype="uint8") as character:
                bathy.write(np.full((1, 5, 5), -70, dtype="float32"))
                character.write(np.full((1, 5, 5), 3, dtype="uint8"))
                result = join_outline(np.array([lon]), np.array([lat]), np.array([70.0]), polygon, bathy, character)
        self.assertEqual(result["source_valid_beams_inside_outline"], 1)
        self.assertEqual(result["source_valid_beams_nearest_usgs_cell_center_inside_outline"], 0)
        self.assertEqual(result["unique_paired_class3_band_cells_under_source_beams"], 0)

    def test_pairing_improves_coverage_evidence_without_depth_or_habitat_promotion(self):
        report = json.loads((ROOT / "dist/data/monterey-2009-beam-usgs-cell-screen.json").read_text())
        self.assertEqual(report["scope"], "monterey-2009-original-beams-to-usgs-native-cell-screen")
        self.assertFalse(report["fishing_target"])
        self.assertFalse(report["exportable"])
        for ident, beam_count, paired_cells, stable_cells in (
                ("023", 314362, 16524, 10886), ("046", 72083, 2651, 1705)):
            row = report["outlines"][ident]
            self.assertEqual(row["source_valid_beams_inside_outline"], beam_count)
            self.assertEqual(row["unique_paired_class3_band_cells_under_source_beams"], paired_cells)
            self.assertEqual(row["unique_3x3_stable_class3_band_cells_under_source_beams"], stable_cells)
            self.assertGreater(paired_cells, stable_cells)
            for gate in ("mllw_depth_qualified", "horizontal_registration_qualified",
                         "independent_substrate_qualified", "fishing_target", "exportable"):
                self.assertFalse(row[gate])

    def test_plan_retains_research_receipt_and_no_rank(self):
        sector = next(row for row in build(ROOT)["sectors"] if row["sector_id"] == "monterey-sur")
        self.assertIn("dist/data/monterey-2009-beam-usgs-cell-screen.json", sector["source_receipts"])
        self.assertEqual(sector["qualified_200_to_300ft_targets"], 0)
        self.assertIsNone(sector["fishing_rank"])


if __name__ == "__main__":
    unittest.main()
