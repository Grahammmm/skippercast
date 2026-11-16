"""NOAA chlorophyll: malformed or non-finite _FillValue declarations are refused, never published as ok."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
import unittest

import numpy as np
from scipy.io import netcdf_file

from skippercast.pipeline.noaa_chlorophyll import _fill_declared, fetch
from tests.gis.test_noaa_chlorophyll import BOUNDS, MaskedClient, at
from tests.gis.test_noaa_chlorophyll_packing import build, decode

REFUSAL = r"^NOAA chlorophyll units or fill value changed$"


def _rewrite(body, value):
    """Classic NetCDF like the packing-test row but with _FillValue = value (None omits it)."""
    stamp = datetime(2026, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=264)
    stream = BytesIO()
    with netcdf_file(stream, mode="w") as nc:
        for name, n in (("time", 1), ("altitude", 1), ("lat", 1), ("lon", 2)):
            nc.createDimension(name, n)
        nc.createVariable("time", "d", ("time",))[:] = [int(stamp.timestamp())]
        nc.variables["time"].units = "seconds since 1970-01-01 00:00:00Z"
        nc.createVariable("altitude", "d", ("altitude",))[:] = [0]
        nc.createVariable("lat", "d", ("lat",))[:] = [35.0]
        nc.createVariable("lon", "d", ("lon",))[:] = [-121.0, -120.99]
        chl = nc.createVariable("chl_oci", "f", ("time", "altitude", "lat", "lon"))
        chl.units = "mg m^-3"
        chl.standard_name = "mass_concentration_of_chlorophyll_a_in_sea_water"
        if value is not None:
            chl._FillValue = value
        chl[:] = [[[(.75, -32767.0)]]]
        nc.flush()
        return stream.getvalue()


class NoaaChlorophyllFillMetadataTests(unittest.TestCase):
    def test_fill_nan_cannot_publish_ok(self):
        with self.assertRaisesRegex(ValueError, REFUSAL):
            decode(_rewrite(None, np.float32("nan")))

    def test_fill_metadata_requires_finite_numeric_scalar(self):
        for label, value in (("absent", None), ("numeric_text", "-32767"), ("inf", np.float32("inf")), ("neg_inf", np.float32("-inf")),
                             ("vector", np.array([-32767.0, -32767.0], dtype="f4"))):
            with self.subTest(label), self.assertRaisesRegex(ValueError, REFUSAL):
                decode(_rewrite(None, value))
        for label, value in (("bool", np.True_), ("complex", np.complex64(-32767)),
                             ("rank2", np.full((1, 1), -32767.0)), ("empty", np.array([])),
                             ("bytes", b"-32767"), ("none", None)):
            with self.subTest(label):
                self.assertFalse(_fill_declared(SimpleNamespace(_FillValue=value)))
        self.assertFalse(_fill_declared(SimpleNamespace()))

    def test_fill_tolerance_and_values_preserved(self):
        for value in (np.float32(-32767.0), np.float64(-32767.005), np.int32(-32767)):
            with self.subTest(value=value):
                data = decode(_rewrite(None, value))
                self.assertEqual([s["chlorophyll"] for s in data["samples"]], [.75, None])
                self.assertEqual(data["valid_cells"], 1)
        for value in (np.float64(-32767.5), np.float32(0.0)):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, REFUSAL):
                decode(_rewrite(None, value))

    def test_bad_newest_fill_does_not_walk_back(self):
        client = MaskedClient(at(31), {"301": _rewrite(None, np.float32("nan")), "300": build(ordinal=300)})
        with self.assertRaisesRegex(ValueError, REFUSAL):
            fetch(client, BOUNDS)
        self.assertFalse([u for u in client.urls if "V2026300_" in u])

    def test_other_metadata_guards_unchanged(self):
        with self.assertRaisesRegex(ValueError, r"packed variables unsupported"):
            decode(build({"scale_factor": 2.0}))
        with self.assertRaisesRegex(ValueError, REFUSAL):
            decode(build({"units": "mg/m3"}))
        with self.assertRaisesRegex(ValueError, REFUSAL):
            decode(build({"standard_name": "other"}))


if __name__ == "__main__":
    unittest.main()
