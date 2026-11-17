"""NOAA HFRNet radar-site counts are discrete: a fractional count is unavailable, never truncated into support."""

from datetime import datetime, timezone
from io import BytesIO
import unittest

from scipy.io import netcdf_file

from skippercast.pipeline.collect import source
from skippercast.pipeline.noaa_hfr import read_subset

WHEN = datetime(2026, 9, 24, 22, tzinfo=timezone.utc)
BOUNDS = {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.9]}
RESOLUTION = [.05394, .06246]


def body(counts, kind="d", **attrs):
    """Real classic-NetCDF bytes; counts are stored with the given dtype code (float64 by default)."""
    stream = BytesIO()
    with netcdf_file(stream, mode="w") as nc:
        for name, size in (("time", 1), ("lat", 1), ("lon", len(counts))):
            nc.createDimension(name, size)
        t = nc.createVariable("time", "i", ("time",))
        t.units = "seconds since 1970-01-01"
        t[:] = [1790287200]
        nc.createVariable("depth", "f", ()).data[...] = 1.4
        nc.createVariable("lat", "f", ("lat",))[:] = [35.0]
        nc.createVariable("lon", "f", ("lon",))[:] = [-121.0, -120.9375][:len(counts)]
        for name, value, standard in (("u", .25, "surface_eastward_sea_water_velocity"),
                                      ("v", -.1, "surface_northward_sea_water_velocity")):
            var = nc.createVariable(name, "f", ("time", "lat", "lon"))
            var.units = "m s-1"
            var.standard_name = standard
            var[:] = [[[value] * len(counts)]]
        n = nc.createVariable("number_of_sites", kind, ("time", "lat", "lon"))
        n.units = "count"
        for key, value in attrs.items():
            setattr(n, key, value)
        n[:] = [[list(counts)]]
        nc.createVariable("hdop", "f", ("time", "lat", "lon"))[:] = [[[.2] * len(counts)]]
        nc.flush()
        return stream.getvalue()


def decode(data):
    return read_subset(data, BOUNDS, WHEN, RESOLUTION)


def pairs(result):
    return [(s["number_of_sites"], s["water_u"], s["water_v"]) for s in result["samples"]]


class SiteCountTests(unittest.TestCase):
    def test_fractional_counts_cannot_qualify_vectors(self):
        for first, second in ((2.5, 3.75), (99.5, .5), (1.5, 2.25)):
            with self.subTest(counts=(first, second)):
                result = decode(body([first, second]))
                self.assertEqual(pairs(result), [(None, None, None)] * 2)
                self.assertEqual(result["valid_cells"], 0)

    def test_fractional_count_does_not_mask_valid_neighbor(self):
        result = decode(body([2.5, 2.0]))
        self.assertEqual(pairs(result), [(None, None, None), (2, .25, -.1)])
        self.assertEqual((result["valid_cells"], result["total_cells"]), (1, 2))
        self.assertEqual([s["hdop"] for s in result["samples"]], [.2, .2])
        self.assertAlmostEqual(result["nominal_depth_m"], 1.4, places=5)

    def test_whole_float_and_integer_count_controls(self):
        for counts, expected in (([0, 1], [(0, None, None), (1, None, None)]),
                                 ([2, 100], [(2, .25, -.1), (100, .25, -.1)])):
            with self.subTest(counts=counts):
                as_float = decode(body(counts))
                self.assertEqual(pairs(as_float), expected)
                self.assertTrue(all(type(s["number_of_sites"]) is int for s in as_float["samples"]))
                self.assertEqual(as_float, decode(body(counts, kind="i")))

    def test_nonfinite_out_of_range_and_declared_missing_counts_stay_unavailable(self):
        result = decode(body([float("nan"), float("inf")]))
        self.assertEqual(pairs(result), [(None, None, None)] * 2)
        result = decode(body([float("-inf"), -1.0]))
        self.assertEqual(pairs(result), [(None, None, None)] * 2)
        result = decode(body([101.0, 100.0]))
        self.assertEqual(pairs(result), [(None, None, None), (100, .25, -.1)])
        for attr in ("_FillValue", "missing_value"):
            with self.subTest(attr=attr):
                result = decode(body([5.0, 2.0], **{attr: 5.0}))
                self.assertEqual(pairs(result), [(None, None, None), (2, .25, -.1)])

    def test_all_fractional_support_is_missing_source(self):
        def run(counts):
            return source("hfr", "HFR", "currents", "https://example.invalid", 6,
                          lambda client: decode(body(counts)), datetime(2026, 9, 24, 22, 30, tzinfo=timezone.utc))
        result = run([2.5, 3.75])
        self.assertEqual(result["status"], "missing")
        self.assertEqual((result["data"]["valid_cells"], result["data"]["total_cells"]), (0, 2))
        self.assertEqual(run([2.5, 2.0])["status"], "ok")


if __name__ == "__main__":
    unittest.main()
