"""NOAA HFRNet: variables declaring scale_factor/add_offset are refused, never published as physical values."""

from datetime import datetime, timezone
from io import BytesIO
import unittest
from unittest.mock import patch

import numpy as np
from scipy.io import netcdf_file

from skippercast.pipeline.collect import source
from skippercast.pipeline.noaa_hfr import read_subset

WHEN = datetime(2026, 9, 24, 22, tzinfo=timezone.utc)
BOUNDS = {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.9]}
RESOLUTION = [.05394, .06246]
REFUSAL = r"^NOAA HFRNet packed variables unsupported$"
REQUIRED = ("time", "lat", "lon", "u", "v", "number_of_sites", "hdop", "depth")


def build(attrs=None, omit=(), u=(.25, .25), n=(2, 2), hdop=(.2, .5)):
    """Real classic-NetCDF bytes; ``attrs`` maps variable name to {attribute: value}."""
    attrs = attrs or {}
    stream = BytesIO()
    with netcdf_file(stream, mode="w") as nc:
        for name, size in (("time", 1), ("lat", 1), ("lon", 2)):
            nc.createDimension(name, size)
        made = {}
        if "time" not in omit:
            made["time"] = nc.createVariable("time", "i", ("time",))
            made["time"].units = "seconds since 1970-01-01"
            made["time"][:] = [1790287200]
        if "depth" not in omit:
            made["depth"] = nc.createVariable("depth", "f", ())
            made["depth"].data[...] = 1.4
        made["lat"] = nc.createVariable("lat", "f", ("lat",))
        made["lat"][:] = [35.0]
        made["lon"] = nc.createVariable("lon", "f", ("lon",))
        made["lon"][:] = [-121.0, -120.9375]
        for name, values, standard in (("u", u, "surface_eastward_sea_water_velocity"),
                                       ("v", (-.1, -.1), "surface_northward_sea_water_velocity")):
            made[name] = nc.createVariable(name, "f", ("time", "lat", "lon"))
            made[name].units = "m s-1"
            made[name].standard_name = standard
            made[name][:] = [[list(values)]]
        made["number_of_sites"] = nc.createVariable("number_of_sites", "b", ("time", "lat", "lon"))
        made["number_of_sites"].units = "count"
        made["number_of_sites"][:] = [[list(n)]]
        made["hdop"] = nc.createVariable("hdop", "f", ("time", "lat", "lon"))
        made["hdop"][:] = [[list(hdop)]]
        for name, pairs in attrs.items():
            for key, value in pairs.items():
                setattr(made[name], key, value)
        nc.flush()
        return stream.getvalue()


def decode(body):
    return read_subset(body, BOUNDS, WHEN, RESOLUTION)


class PackedVariablesRefusedTests(unittest.TestCase):
    def test_packed_u_never_publishes_raw_physical_vector(self):
        self.assertEqual(decode(build())["samples"][0]["water_u"], .25)
        body = build({"u": {"scale_factor": np.float32(.1), "add_offset": np.float32(.5)}}, u=(2, 2))
        with self.assertRaisesRegex(ValueError, REFUSAL):
            decode(body)

    def test_each_required_variable_is_checked(self):
        for name in REQUIRED:
            for attrs in ({"scale_factor": np.float32(.1)}, {"add_offset": np.float32(.5)}):
                with self.subTest(variable=name, attribute=sorted(attrs)):
                    with self.assertRaisesRegex(ValueError, REFUSAL):
                        decode(build({name: attrs}))

    def test_attribute_presence_is_not_truthiness(self):
        values = (np.float32(1), np.float32(0), np.array([1, 2], dtype="f"), "text", np.float32("nan"))
        for value in values:
            for attrs in ({"scale_factor": value}, {"add_offset": value},
                          {"scale_factor": value, "add_offset": value}):
                with self.subTest(value=repr(value), attribute=sorted(attrs)):
                    with self.assertRaisesRegex(ValueError, REFUSAL):
                        decode(build({"hdop": attrs}))

    def test_packed_source_is_failed_or_retained_not_ok(self):
        body = build({"u": {"scale_factor": np.float32(.1), "add_offset": np.float32(.5)}}, u=(2, 2))
        previous = {"data": {"sample_at": "2026-09-24T21:00:00Z", "valid_cells": 1},
                    "last_success_at": "2026-09-24T21:05:00Z", "data_retrieved_at": "2026-09-24T21:05:00Z"}
        with patch("socket.socket", side_effect=AssertionError("offline only")):
            failed = source("hfr", "Synthetic HFR", "currents", "https://example.invalid/hfr", 12,
                            lambda client: decode(body), WHEN)
            retained = source("hfr", "Synthetic HFR", "currents", "https://example.invalid/hfr", 12,
                              lambda client: decode(body), WHEN, previous=previous)
        self.assertEqual((failed["status"], failed["data"]), ("failed", None))
        self.assertIn("NOAA HFRNet packed variables unsupported", failed["issue"])
        self.assertEqual(retained["status"], "retained")
        self.assertEqual(retained["data"], previous["data"])
        self.assertEqual(retained["data_retrieved_at"], previous["data_retrieved_at"])
        self.assertEqual(retained["last_success_at"], previous["last_success_at"])

    def test_required_field_refusal_stays_first(self):
        body = build({"u": {"scale_factor": np.float32(.1)}}, omit=("depth",))
        original = bytes(body)
        with self.assertRaisesRegex(ValueError, r"^NOAA HFRNet subset lacks required fields$"):
            decode(body)
        self.assertEqual(body, original)

    def test_refused_and_accepted_calls_leave_input_bytes_unchanged(self):
        for body, refused in ((build(), False), (build({"v": {"add_offset": np.float32(0)}}), True)):
            original = bytes(body)
            if refused:
                with self.assertRaisesRegex(ValueError, REFUSAL):
                    decode(body)
            else:
                decode(body)
            self.assertEqual(body, original)


class UnpackedOutputUnchangedTests(unittest.TestCase):
    def test_unpacked_zero_fills_and_quality_are_unchanged(self):
        # Cell 0: genuine zero u with two sites; cell 1: declared sentinel u, so both components are null.
        result = decode(build({"u": {"_FillValue": np.float32(-999)}}, u=(0, -999), hdop=(.2, -1)))
        first, second = result["samples"]
        self.assertEqual((first["water_u"], first["water_v"], first["number_of_sites"], first["hdop"]),
                         (0.0, -.1, 2, .2))
        self.assertEqual((second["water_u"], second["water_v"], second["number_of_sites"], second["hdop"]),
                         (None, None, 2, None))
        self.assertEqual((result["valid_cells"], result["total_cells"]), (1, 2))

    def test_single_radar_and_hdop_only_missingness_are_unchanged(self):
        result = decode(build({"hdop": {"_FillValue": np.float32(-1)}}, n=(2, 1), hdop=(-1, .5)))
        first, second = result["samples"]
        self.assertEqual((first["water_u"], first["hdop"]), (.25, None))
        self.assertEqual((second["water_u"], second["water_v"], second["hdop"]), (None, None, .5))
        self.assertEqual(result["nominal_depth_m"], 1.399999976158142)


if __name__ == "__main__":
    unittest.main()
