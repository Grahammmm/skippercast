"""NOAA HFRNet: repeated latitude/longitude coordinates are refused, never counted as distinct cells."""

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
REFUSAL = r"^NOAA HFRNet axes changed$"


def build(lat=(35.0,), lon=(-121.0, -120.9375), u=None, n=None, lat_rank2=False, lon_rank2=False):
    """Real classic-NetCDF bytes with caller-chosen axes; field values default to one per cell."""
    cells = len(lat) * len(lon)
    u = list(u if u is not None else [.25 + .5 * k for k in range(cells)])
    n = list(n if n is not None else [2] * cells)
    stream = BytesIO()
    with netcdf_file(stream, mode="w") as nc:
        nc.createDimension("time", 1)
        nc.createDimension("lat", len(lat))
        nc.createDimension("lon", len(lon))
        time = nc.createVariable("time", "i", ("time",))
        time.units = "seconds since 1970-01-01"
        time[:] = [1790287200]
        depth = nc.createVariable("depth", "f", ())
        depth.data[...] = 1.4
        if lat_rank2:
            ya = nc.createVariable("lat", "f", ("lat", "lat"))
            ya[:] = np.tile(np.array(lat, dtype="f"), (len(lat), 1))
        else:
            nc.createVariable("lat", "f", ("lat",))[:] = list(lat)
        if lon_rank2:
            xa = nc.createVariable("lon", "f", ("lon", "lon"))
            xa[:] = np.tile(np.array(lon, dtype="f"), (len(lon), 1))
        else:
            nc.createVariable("lon", "f", ("lon",))[:] = list(lon)
        for name, values, standard in (("u", u, "surface_eastward_sea_water_velocity"),
                                       ("v", [-.1] * cells, "surface_northward_sea_water_velocity")):
            var = nc.createVariable(name, "f", ("time", "lat", "lon"))
            var.units = "m s-1"
            var.standard_name = standard
            var[:] = np.array(values, dtype="f").reshape(1, len(lat), len(lon))
        sites = nc.createVariable("number_of_sites", "b", ("time", "lat", "lon"))
        sites.units = "count"
        sites[:] = np.array(n).reshape(1, len(lat), len(lon))
        nc.createVariable("hdop", "f", ("time", "lat", "lon"))[:] = np.full((1, len(lat), len(lon)), .2, dtype="f")
        nc.flush()
        return stream.getvalue()


def decode(body):
    return read_subset(body, BOUNDS, WHEN, RESOLUTION)


class DuplicateAxisTests(unittest.TestCase):
    def refused(self, body):
        original = bytes(body)
        with self.assertRaisesRegex(ValueError, REFUSAL):
            decode(body)
        self.assertEqual(body, original)

    def test_duplicate_lon_refuses_whatever_the_vectors(self):
        for kwargs in ({}, {"u": (.25, .25)}, {"u": (-999, .25)}, {"u": (7, 7)}, {"n": (1, 1)}):
            with self.subTest(kwargs=kwargs):
                self.refused(build(lon=(-121.0, -121.0), **kwargs))

    def test_duplicate_lat_refuses(self):
        self.refused(build(lat=(35.0, 35.0), lon=(-121.0,)))
        self.refused(build(lat=(35.0, 35.0), lon=(-121.0,), u=(7, 7)))

    def test_both_axes_duplicated_and_nonadjacent_repeat_refuse(self):
        self.refused(build(lat=(35.0, 35.0), lon=(-121.0, -121.0)))
        self.refused(build(lat=(34.99, 35.0, 34.99), lon=(-121.0,)))
        self.refused(build(lat=(35.0,), lon=(-121.0, -120.9375, -121.0)))

    def test_rank_two_axes_refuse_as_axes_changed(self):
        self.refused(build(lat=(35.0, 35.01), lon=(-121.0,), lat_rank2=True))
        self.refused(build(lat=(35.0,), lon=(-121.0, -120.9375), lon_rank2=True))


class OrdinaryAxesUnchangedTests(unittest.TestCase):
    def test_unique_axes_keep_order_values_and_counts(self):
        ascending = decode(build(lon=(-121.0, -120.9375)))
        self.assertEqual([(s["latitude"], s["longitude"], s["water_u"]) for s in ascending["samples"]],
                         [(35.0, -121.0, .25), (35.0, -120.9375, .75)])
        self.assertEqual((ascending["valid_cells"], ascending["total_cells"]), (2, 2))
        descending = decode(build(lat=(35.02, 35.0), lon=(-120.9375, -121.0)))
        self.assertEqual([(s["latitude"], s["longitude"]) for s in descending["samples"]],
                         [(35.02, -120.9375), (35.02, -121.0), (35.0, -120.9375), (35.0, -121.0)])
        self.assertEqual((descending["valid_cells"], descending["total_cells"]), (4, 4))

    def test_singleton_grid_is_accepted(self):
        result = decode(build(lon=(-121.0,)))
        self.assertEqual((result["valid_cells"], result["total_cells"]), (1, 1))
        self.assertEqual(result["sample_at"], "2026-09-24T22:00:00Z")
        self.assertEqual(result["units"]["water_u"], "m s-1")
        self.assertEqual(result["nominal_depth_m"], 1.399999976158142)

    def test_accepted_call_leaves_input_bytes_unchanged(self):
        body = build()
        original = bytes(body)
        decode(body)
        self.assertEqual(body, original)


class SourceBoundaryTests(unittest.TestCase):
    def test_duplicate_axis_source_is_failed_or_retained_not_ok(self):
        bad = build(lon=(-121.0, -121.0))
        good = build()
        previous = {"data": {"sample_at": "2026-09-24T21:00:00Z", "valid_cells": 1},
                    "last_success_at": "2026-09-24T21:05:00Z", "data_retrieved_at": "2026-09-24T21:05:00Z"}

        def run(body, **kw):
            return source("hfr", "Synthetic HFR", "currents", "https://example.invalid/hfr", 12,
                          lambda client: decode(body), WHEN, **kw)

        with patch("socket.socket", side_effect=AssertionError("offline only")):
            failed = run(bad)
            retained = run(bad, previous=previous)
            healthy = run(good)
        self.assertEqual((failed["status"], failed["data"]), ("failed", None))
        self.assertIn("NOAA HFRNet axes changed", failed["issue"])
        self.assertEqual(retained["status"], "retained")
        self.assertEqual(retained["data"], previous["data"])
        self.assertEqual(retained["data_retrieved_at"], previous["data_retrieved_at"])
        self.assertEqual(retained["last_success_at"], previous["last_success_at"])
        self.assertEqual(healthy["status"], "ok")


if __name__ == "__main__":
    unittest.main()
