"""NOAA ocean-color gaps and source clocks must survive ingestion."""

from datetime import datetime, timezone
from io import BytesIO
import unittest

from scipy.io import netcdf_file

from skippercast.pipeline.noaa_chlorophyll import latest_file, read_subset


class NoaaChlorophyllTests(unittest.TestCase):
    def fixture(self):
        stream = BytesIO()
        with netcdf_file(stream, mode="w") as nc:
            for name, n in (("time", 1), ("altitude", 1), ("lat", 1), ("lon", 2)):
                nc.createDimension(name, n)
            t = nc.createVariable("time", "d", ("time",))
            t.units = "seconds since 1970-01-01 00:00:00Z"
            t[:] = [1790078400]
            nc.createVariable("altitude", "d", ("altitude",))[:] = [0]
            nc.createVariable("lat", "d", ("lat",))[:] = [35.0]
            nc.createVariable("lon", "d", ("lon",))[:] = [-121.0, -120.9625]
            chl = nc.createVariable("chl_oci", "f", ("time", "altitude", "lat", "lon"))
            chl.units = "mg m^-3"
            chl.standard_name = "mass_concentration_of_chlorophyll_a_in_sea_water"
            chl._FillValue = -32767.0
            chl[:] = [[[[.75, -32767.0]]]]
            nc.flush()
            body = stream.getvalue()
        return body

    def test_real_value_and_gap_are_distinct(self):
        bounds = {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.95]}
        day = datetime(2026, 9, 22, tzinfo=timezone.utc)
        data = read_subset(self.fixture(), bounds, "reviewed.nc", day)
        self.assertEqual(data["sample_at"], "2026-09-22T12:00:00Z")
        self.assertEqual((data["valid_cells"], data["total_cells"]), (1, 2))
        self.assertEqual(data["samples"][0]["chlorophyll"], .75)
        self.assertIsNone(data["samples"][1]["chlorophyll"])

    def test_filename_time_conflict_is_rejected(self):
        bounds = {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.95]}
        with self.assertRaisesRegex(ValueError, "conflicts"):
            read_subset(self.fixture(), bounds, "reviewed.nc", datetime(2026, 9, 21, tzinfo=timezone.utc))

    def test_catalog_requires_dated_exact_path(self):
        class Client:
            now = datetime(2026, 9, 24, tzinfo=timezone.utc)
            def get(self, _url):
                return '<catalog><dataset urlPath="chlociVIIRSnpp-n20GlobalDailyWW00/V2026265_D1_NPP-N20_WW00_chloci.nc"/><dataset urlPath="other/V2026266_D1_NPP-N20_WW00_chloci.nc"/></catalog>'
        day, path = latest_file(Client())
        self.assertEqual(day.date().isoformat(), "2026-09-22")
        self.assertTrue(path.startswith("chlociVIIRSnpp-n20GlobalDailyWW00/"))


if __name__ == "__main__":
    unittest.main()
