"""The replacement SST feed must preserve units, masks and true sample time."""

from io import BytesIO
import unittest

import numpy as np
from scipy.io import netcdf_file

from skippercast.pipeline.noaa_sst import fetch, read_subset
from tests.gis.test_noaa_sst_fetch import GOOD, FakeClient, catalog, name

SUPPORTED_UNITS = "seconds since 1981-01-01 00:00:00"
OMIT_UNITS = object()
BOUNDS = {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.95]}


class NoaaSstTests(unittest.TestCase):
    def fixture(self, time_units=SUPPORTED_UNITS):
        stream = BytesIO()
        with netcdf_file(stream, mode="w") as nc:
            nc.createDimension("time", 1)
            nc.createDimension("lat", 2)
            nc.createDimension("lon", 2)
            t = nc.createVariable("time", "i", ("time",))
            if time_units is not OMIT_UNITS:
                t.units = time_units
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

    def test_time_units_require_exact_supported_origin(self):
        for units in ("seconds since 1981-01-01 12:00:00", "seconds since 1981-01-02 00:00:00",
                      "seconds since 1981-01-01 00:00:00.5", "seconds since 1981-01-01 00:00:00 +01:00",
                      "seconds since 1981-01-01 00:00:00 junk", "seconds since 1981-01-01",
                      "days since 1981-01-01 00:00:00"):
            with self.subTest(units=units):
                with self.assertRaisesRegex(ValueError, r"^NOAA SST time units changed$"):
                    read_subset(self.fixture(units), BOUNDS, "reviewed.nc")

    def test_missing_or_nontext_time_units_are_named(self):
        for units in (OMIT_UNITS, 1981):
            with self.subTest(units=units):
                with self.assertRaisesRegex(ValueError, r"^NOAA SST time units changed$"):
                    read_subset(self.fixture(units), BOUNDS, "reviewed.nc")

    def test_supported_time_origin_preserves_sample_and_rows(self):
        data = read_subset(self.fixture(SUPPORTED_UNITS), BOUNDS, "reviewed.nc")
        self.assertEqual(data["sample_at"], "2026-09-23T12:00:00Z")
        self.assertEqual({r["time"] for r in data["samples"]}, {"2026-09-23T12:00:00Z"})
        self.assertEqual((data["valid_cells"], data["total_cells"]), (2, 4))
        self.assertEqual(data["units"], {"analysed_sst": "degree_C", "analysis_error": "degree_C", "mask": "flag"})
        self.assertEqual([r["analysed_sst"] for r in data["samples"]], [18.0, None, None, 20.0])

    def test_fetch_rejects_changed_subset_time_origin(self):
        stamp = "20260101000000"
        client = FakeClient(catalog(2026, stamp), self.fixture("seconds since 1981-01-01 12:00:00"))
        with self.assertRaisesRegex(ValueError, r"^NOAA SST time units changed$"):
            fetch(client, GOOD)
        self.assertEqual(len(client.urls), 2)
        self.assertIn(name(stamp), client.urls[1])
        self.assertEqual(client.bodies, [])
        control = FakeClient(catalog(2026, stamp), self.fixture())
        self.assertEqual(fetch(control, GOOD)["sample_at"], "2026-09-23T12:00:00Z")
        self.assertEqual(len(control.urls), 2)


if __name__ == "__main__":
    unittest.main()
