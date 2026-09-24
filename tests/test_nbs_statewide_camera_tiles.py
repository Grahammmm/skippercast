import unittest

import numpy as np
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import GeometryCollection, Point

from scripts.audit_nbs_statewide_camera_tiles import camera_window_screen


class NbsStatewideCameraTileTest(unittest.TestCase):
    def test_native_neighborhood_and_mpa_hold(self):
        with MemoryFile() as memory:
            with memory.open(driver="GTiff", width=80, height=80, count=3,
                             dtype="float32", crs="EPSG:32610",
                             transform=from_origin(500000, 4000000, 4, 4)) as raster:
                raster.write(np.full((80, 80), -50, dtype="float32"), 1)
                raster.write(np.full((80, 80), .5, dtype="float32"), 2)
                raster.write(np.full((80, 80), 1, dtype="float32"), 3)
                inverse = Transformer.from_crs(raster.crs, "EPSG:4326", always_xy=True)
                project = Transformer.from_crs("EPSG:4326", raster.crs, always_xy=True)
                lon, lat = inverse.transform(500160, 3999840)
                sources = {1: {"coverage": "1", "bathy_coverage": "1",
                               "source_survey_id": "H12345", "survey_date_end": "2020-01-01"}}
                self.assertEqual(camera_window_screen(raster, sources, lon, lat, project,
                                                       inverse, GeometryCollection()),
                                 "locally_qualified_90pct")
                self.assertEqual(camera_window_screen(raster, sources, lon, lat, project,
                                                       inverse, Point(lon, lat).buffer(.001)),
                                 "mpa_or_edge_held")


if __name__ == "__main__":
    unittest.main()
