"""NOAA HF radar vectors require a dated grid and two contributing radars."""

from datetime import datetime, timezone
from io import BytesIO
import unittest
from unittest.mock import patch

import numpy as np

from skippercast.pipeline.collect import source

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

    def marked_fixture(self, changes):
        stream = BytesIO(self.fixture())
        with netcdf_file(stream, mode="a", mmap=False) as nc:
            for name, values, attrs in changes:
                var = nc.variables[name]
                var[:] = [[values]]
                for key, marker in attrs.items():
                    setattr(var, key, marker)
            nc.flush()
            return stream.getvalue()

    def decode(self, body):
        return read_subset(body, {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.9]},
                           datetime(2026, 9, 24, 22, tzinfo=timezone.utc), [.05394, .06246])

    def assert_unavailable(self, data, index=0):
        self.assertIsNone(data["samples"][index]["water_u"])
        self.assertIsNone(data["samples"][index]["water_v"])

    def test_declared_component_fill_masks_both_components(self):
        for name, attr, value in (("u", "_FillValue", 0), ("v", "missing_value", 0),
                                  ("u", "missing_value", .25)):
            with self.subTest(name=name, attr=attr, value=value):
                data = self.decode(self.marked_fixture([(name, [value, value], {attr: np.float32(value)})]))
                self.assert_unavailable(data)
                self.assertEqual(data["valid_cells"], 0)

    def test_declared_site_count_fill_cannot_qualify_vector(self):
        for attr in ("_FillValue", "missing_value"):
            with self.subTest(attr=attr):
                data = self.decode(self.marked_fixture([("number_of_sites", [2, 1], {attr: np.int8(2)})]))
                self.assertIsNone(data["samples"][0]["number_of_sites"])
                self.assert_unavailable(data)
                self.assertEqual((data["valid_cells"], data["total_cells"]), (0, 2))
                self.assertEqual(data["sample_at"], "2026-09-24T22:00:00Z")

    def test_hdop_fill_is_null_without_new_vector_gate(self):
        for attr in ("_FillValue", "missing_value"):
            with self.subTest(attr=attr):
                data = self.decode(self.marked_fixture([("hdop", [.2, .5], {attr: np.float32(.2)})]))
                self.assertIsNone(data["samples"][0]["hdop"])
                self.assertEqual(data["samples"][1]["hdop"], .5)
                self.assertEqual(data["valid_cells"], 1)
                self.assertEqual((data["samples"][0]["water_u"], data["samples"][0]["water_v"]), (.25, -.1))

    def test_missing_marker_union_and_array_values(self):
        for missing in (np.float32(.5), np.array([.5], dtype="f"), np.array([.5, .75], dtype="f")):
            for value in (.25, *np.atleast_1d(missing)):
                with self.subTest(missing=missing, value=value):
                    data = self.decode(self.marked_fixture([
                        ("u", [value, 1], {"_FillValue": np.float32(.25), "missing_value": missing}),
                        ("number_of_sites", [2, 2], {})]))
                    self.assert_unavailable(data)
                    self.assertEqual(data["valid_cells"], 1)
                    self.assertEqual(data["samples"][1]["water_u"], 1)

    def test_unmarked_zero_and_existing_ranges_preserved(self):
        for attrs in ({}, {"_FillValue": np.float32(4)}):
            data = self.decode(self.marked_fixture([("u", [0, 0], attrs), ("v", [0, 0], attrs)]))
            self.assertEqual(data["valid_cells"], 1)
            self.assertEqual((data["samples"][0]["water_u"], data["samples"][0]["water_v"]), (0, 0))
            self.assert_unavailable(data, 1)
        for name in ("u", "v", "number_of_sites", "hdop"):
            for value in (float("nan"), float("inf"), -float("inf"), 101):
                if name == "number_of_sites" and not np.isfinite(value):
                    continue  # The existing fixture stores site counts as signed bytes.
                with self.subTest(name=name, value=value):
                    data = self.decode(self.marked_fixture([(name, [value, value], {"missing_value": np.float32(4)})]))
                    if name == "hdop":
                        self.assertIsNone(data["samples"][0]["hdop"])
                        self.assertEqual(data["valid_cells"], 1)
                    else:
                        self.assert_unavailable(data)
                        self.assertEqual(data["valid_cells"], 0)

    def test_all_declared_missing_source_is_missing_not_calm(self):
        body = self.marked_fixture([("u", [0, 0], {"_FillValue": np.float32(0)})])
        original = bytes(body)
        with patch("socket.socket", side_effect=AssertionError("offline only")):
            result = source("hfr", "Synthetic HFR", "currents", "https://example.invalid/hfr", 12,
                            lambda client: self.decode(body), datetime(2026, 9, 24, 22, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "missing")
        self.assertEqual((result["data"]["valid_cells"], result["data"]["total_cells"]), (0, 2))
        for i in range(2):
            self.assert_unavailable(result["data"], i)
        self.assertEqual(body, original)

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
