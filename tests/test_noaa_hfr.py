"""NOAA HF radar vectors require a dated grid and two contributing radars."""

from datetime import datetime, timezone
from io import BytesIO
import unittest

from scipy.io import netcdf_file

from skippercast.pipeline.noaa_hfr import latest_time, read_subset


class NoaaHfrTests(unittest.TestCase):
    def fixture(self):
        stream = BytesIO()
        with netcdf_file(stream, mode="w") as nc:
            for name, size in (("time", 1), ("lat", 1), ("lon", 2)):
                nc.createDimension(name, size)
            t = nc.createVariable("time", "i", ("time",))
            t.units = "seconds since 1970-01-01"
            t[:] = [1790287200]
            nc.createVariable("depth", "f", ()).data[...] = 1.4
            nc.createVariable("lat", "f", ("lat",))[:] = [35.0]
            nc.createVariable("lon", "f", ("lon",))[:] = [-121.0, -120.9375]
            for name, value, standard in (("u", .25, "surface_eastward_sea_water_velocity"),
                                          ("v", -.1, "surface_northward_sea_water_velocity")):
                var = nc.createVariable(name, "f", ("time", "lat", "lon"))
                var.units = "m s-1"
                var.standard_name = standard
                var[:] = [[[value, value]]]
            n = nc.createVariable("number_of_sites", "b", ("time", "lat", "lon"))
            n.units = "count"
            n[:] = [[[2, 1]]]
            nc.createVariable("hdop", "f", ("time", "lat", "lon"))[:] = [[[.2, .5]]]
            nc.flush()
            body = stream.getvalue()
        return body

    def test_single_radar_does_not_publish_vector(self):
        when = datetime(2026, 9, 24, 22, tzinfo=timezone.utc)
        data = read_subset(self.fixture(), {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.9]}, when, [.05394, .06246])
        self.assertEqual((data["valid_cells"], data["total_cells"]), (1, 2))
        self.assertEqual(data["nominal_depth_m"], 1.399999976158142)
        self.assertEqual(data["samples"][0]["water_u"], .25)
        self.assertIsNone(data["samples"][1]["water_u"])

    def test_wrong_time_fails(self):
        with self.assertRaisesRegex(ValueError, "differs"):
            read_subset(self.fixture(), {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.9]},
                        datetime(2026, 9, 24, 21, tzinfo=timezone.utc), [.05394, .06246])

    def test_metadata_time_and_resolution_are_verified(self):
        class Client:
            now = datetime(2026, 9, 25, tzinfo=timezone.utc)
            def get(self, _url):
                return '<gridDataset><axis name="lat"><values resolution="0.05394"/></axis><axis name="lon"><values resolution="0.06246"/></axis><TimeSpan><end>2026-09-24T22:00:00Z</end></TimeSpan></gridDataset>'
        when, resolution = latest_time(Client())
        self.assertEqual(when.isoformat(), "2026-09-24T22:00:00+00:00")
        self.assertEqual(resolution, [.05394, .06246])


if __name__ == "__main__":
    unittest.main()
