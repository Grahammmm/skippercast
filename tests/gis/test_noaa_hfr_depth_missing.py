"""Provider-declared missing HFR depth is refused instead of published as nominal_depth_m."""

from datetime import datetime, timezone
from io import BytesIO
import unittest
from unittest.mock import patch

import numpy as np
from scipy.io import netcdf_file

from skippercast.pipeline.collect import source
from skippercast.pipeline.noaa_hfr import read_subset

from tests.gis.test_noaa_hfr_packing import BOUNDS, RESOLUTION, WHEN, build

REFUSAL = r"^NOAA HFRNet depth changed$"
D = np.float32(1.4)


def decode(body):
    return read_subset(body, BOUNDS, WHEN, RESOLUTION)


def vector_depth(value, **attrs):
    """Same synthetic subset but with a length-one depth *vector* instead of a scalar."""
    stream = BytesIO()
    with netcdf_file(stream, mode="w") as nc:
        for name, size in (("time", 1), ("lat", 1), ("lon", 2), ("depth", 1)):
            nc.createDimension(name, size)
        t = nc.createVariable("time", "i", ("time",))
        t.units = "seconds since 1970-01-01"
        t[:] = [1790287200]
        depth = nc.createVariable("depth", "f", ("depth",))
        depth[:] = [value]
        for key, marker in attrs.items():
            setattr(depth, key, marker)
        nc.createVariable("lat", "f", ("lat",))[:] = [35.0]
        nc.createVariable("lon", "f", ("lon",))[:] = [-121.0, -120.9375]
        for name, v, standard in (("u", .25, "surface_eastward_sea_water_velocity"),
                                  ("v", -.1, "surface_northward_sea_water_velocity")):
            var = nc.createVariable(name, "f", ("time", "lat", "lon"))
            var.units = "m s-1"
            var.standard_name = standard
            var[:] = [[[v, v]]]
        n = nc.createVariable("number_of_sites", "b", ("time", "lat", "lon"))
        n.units = "count"
        n[:] = [[[2, 2]]]
        nc.createVariable("hdop", "f", ("time", "lat", "lon"))[:] = [[[.2, .5]]]
        nc.flush()
        return stream.getvalue()


class DeclaredMissingDepthTests(unittest.TestCase):
    def test_scalar_markers_refuse(self):
        for attrs in ({"_FillValue": D}, {"missing_value": D}, {"missing_value": np.array([D], dtype="f4")},
                      {"missing_value": np.array([9, D], dtype="f4")},
                      {"missing_value": np.array([D, 9], dtype="f4")},
                      {"_FillValue": D, "missing_value": np.float32(9)},
                      {"_FillValue": np.float32(9), "missing_value": D}):
            with self.subTest(attrs=attrs), self.assertRaisesRegex(ValueError, REFUSAL):
                decode(build({"depth": attrs}))

    def test_length_one_vector_markers_refuse(self):
        for attrs in ({"_FillValue": D}, {"missing_value": D}):
            with self.subTest(attrs=attrs), self.assertRaisesRegex(ValueError, REFUSAL):
                decode(vector_depth(1.4, **attrs))

    def test_length_one_vector_valid_and_nonmatching_accepted(self):
        for attrs in ({}, {"_FillValue": np.float32(9)}):
            with self.subTest(attrs=attrs):
                self.assertEqual(decode(vector_depth(1.4, **attrs))["nominal_depth_m"], 1.399999976158142)

    def test_valid_depth_output_unchanged(self):
        base = decode(build())
        self.assertEqual(base["nominal_depth_m"], 1.399999976158142)
        for attrs in ({"_FillValue": np.float32(9)}, {"missing_value": np.float32(9)},
                      {"_FillValue": np.float32(9), "missing_value": np.float32(8)}):
            with self.subTest(attrs=attrs):
                self.assertEqual(decode(build({"depth": attrs})), base)

    def test_unmarked_zero_depth_still_valid(self):
        self.assertEqual(decode(vector_depth(0.0))["nominal_depth_m"], 0.0)

    def test_nonfinite_and_multiple_depth_still_refused(self):
        for value in (np.nan, np.inf):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, REFUSAL):
                decode(vector_depth(value))

    def test_packing_refusal_precedes_depth_masking(self):
        with self.assertRaisesRegex(ValueError, r"^NOAA HFRNet packed variables unsupported$"):
            decode(build({"depth": {"_FillValue": D, "scale_factor": np.float32(2)}}))

    def test_source_fails_or_retains_never_ok(self):
        body = build({"depth": {"_FillValue": D}})
        previous = {"data": {"sample_at": "2026-09-24T21:00:00Z", "valid_cells": 1},
                    "last_success_at": "2026-09-24T21:05:00Z", "data_retrieved_at": "2026-09-24T21:05:00Z"}
        url = "https://example.invalid/hfr"
        with patch("socket.socket", side_effect=AssertionError("offline only")):
            failed = source("hfr", "Synthetic HFR", "currents", url, 12, lambda client: decode(body), WHEN)
            retained = source("hfr", "Synthetic HFR", "currents", url, 12, lambda client: decode(body), WHEN,
                              previous=previous)
        self.assertEqual((failed["status"], failed["data"]), ("failed", None))
        self.assertIn("NOAA HFRNet depth changed", failed["issue"])
        self.assertEqual(retained["status"], "retained")
        self.assertEqual(retained["data"], previous["data"])
        self.assertEqual(retained["data_retrieved_at"], previous["data_retrieved_at"])
        self.assertEqual(retained["last_success_at"], previous["last_success_at"])

    def test_input_bytes_unchanged(self):
        body = build({"depth": {"_FillValue": D}})
        before = bytes(body)
        with self.assertRaises(ValueError):
            decode(body)
        self.assertEqual(body, before)


if __name__ == "__main__":
    unittest.main()
