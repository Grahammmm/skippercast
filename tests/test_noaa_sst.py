"""The replacement SST feed must preserve units, masks and true sample time."""

from io import BytesIO
import unittest

import numpy as np
from scipy.io import netcdf_file

from skippercast.pipeline.noaa_sst import read_subset


class NoaaSstTests(unittest.TestCase):
    def fixture(self):
        stream = BytesIO()
        with netcdf_file(stream, mode="w") as nc:
            nc.createDimension("time", 1)
            nc.createDimension("lat", 2)
            nc.createDimension("lon", 2)
            t = nc.createVariable("time", "i", ("time",))
            t.units = "seconds since 1981-01-01 00:00:00"
            t[:] = [1443009600]  # 2026-09-23 12:00 UTC
            nc.createVariable("lat", "f", ("lat",))[:] = [35.025, 34.975]
            nc.createVariable("lon", "f", ("lon",))[:] = [-121.025, -120.975]
            temp = nc.createVariable("analysed_sst", "h", ("time", "lat", "lon"))
            temp.units = "kelvin"
            temp.scale_factor = .01
            temp.add_offset = 273.15
            temp[:] = [[[1800, -32768], [1900, 2000]]]
            error = nc.createVariable("analysis_error", "h", ("time", "lat", "lon"))
            error.units = "kelvin"
            error.scale_factor = .01
            error[:] = [[[20, 20], [30, 50]]]
            mask = nc.createVariable("mask", "b", ("time", "lat", "lon"))
            mask.flag_values = np.array([1, 2, 4], dtype="i1")
            mask[:] = [[[1, 1], [2, 1]]]
            nc.flush()
            body = stream.getvalue()
        return body

    def test_scaled_sst_excludes_missing_and_land(self):
        data = read_subset(self.fixture(), {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.95]}, "reviewed.nc")
        self.assertEqual(data["sample_at"], "2026-09-23T12:00:00Z")
        self.assertEqual((data["valid_cells"], data["total_cells"]), (2, 4))
        self.assertEqual(data["samples"][0]["analysed_sst"], 18.0)
        self.assertIsNone(data["samples"][1]["analysed_sst"])
        self.assertIsNone(data["samples"][2]["analysed_sst"])
        self.assertEqual(data["samples"][3]["analysis_error"], .5)

    def test_wrong_units_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "NetCDF classic"):
            read_subset(b"not netcdf", {"latitude": [34, 35], "longitude": [-122, -121]}, "bad.nc")


if __name__ == "__main__":
    unittest.main()
