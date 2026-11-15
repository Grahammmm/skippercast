"""NOAA chlorophyll: chl_oci declaring scale_factor/add_offset is refused, never published as mg m-3."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import unittest

import numpy as np
from scipy.io import netcdf_file

from skippercast.pipeline.noaa_chlorophyll import fetch, read_subset
from tests.gis.test_noaa_chlorophyll import BOUNDS, FULL, SMALL_BOUNDS, SMALL_DAY, MaskedClient, NoaaChlorophyllTests, at

REFUSAL = r"^NOAA chlorophyll packed variables unsupported$"


def build(attrs=None, values=(.75, -32767.0), ordinal=None):
    """Classic NetCDF chlorophyll row; ``attrs`` are set on chl_oci (e.g. scale_factor)."""
    stamp = datetime(2026, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=int(ordinal or 265) - 1)
    stream = BytesIO()
    with netcdf_file(stream, mode="w") as nc:
        for name, n in (("time", 1), ("altitude", 1), ("lat", 1), ("lon", len(values))):
            nc.createDimension(name, n)
        nc.createVariable("time", "d", ("time",))[:] = [int(stamp.timestamp())]
        nc.variables["time"].units = "seconds since 1970-01-01 00:00:00Z"
        nc.createVariable("altitude", "d", ("altitude",))[:] = [0]
        nc.createVariable("lat", "d", ("lat",))[:] = [35.0]
        nc.createVariable("lon", "d", ("lon",))[:] = [-121.0 + .01 * i for i in range(len(values))]
        chl = nc.createVariable("chl_oci", "f", ("time", "altitude", "lat", "lon"))
        chl.units = "mg m^-3"
        chl.standard_name = "mass_concentration_of_chlorophyll_a_in_sea_water"
        chl._FillValue = -32767.0
        for key, value in (attrs or {}).items():
            setattr(chl, key, value)
        chl[:] = [[[values]]]
        nc.flush()
        return stream.getvalue()


def decode(body):
    return read_subset(body, SMALL_BOUNDS, "synthetic.nc", SMALL_DAY)


class NoaaChlorophyllPackingTests(unittest.TestCase):
    def test_packing_declarations_are_refused(self):
        for attrs in ({"scale_factor": 2.0}, {"add_offset": 1.0}, {"scale_factor": 2.0, "add_offset": 1.0},
                      {"scale_factor": 1.0, "add_offset": 0.0}, {"scale_factor": 1.0}, {"add_offset": 0.0}):
            with self.subTest(attrs=attrs), self.assertRaisesRegex(ValueError, REFUSAL):
                decode(build(attrs))

    def test_unpacked_control_is_unchanged(self):
        data = read_subset(NoaaChlorophyllTests().fixture(), SMALL_BOUNDS, "r.nc", SMALL_DAY)
        self.assertEqual([s["chlorophyll"] for s in data["samples"]], [.75, None])
        self.assertEqual((data["valid_cells"], data["total_cells"], data["sample_at"]), (1, 2, "2026-09-22T12:00:00Z"))
        same = decode(build())
        self.assertEqual([s["chlorophyll"] for s in same["samples"]], [.75, None])
        self.assertEqual((same["valid_cells"], same["sample_at"]), (1, "2026-09-22T12:00:00Z"))

    def test_declared_missing_and_walk_back_still_work(self):
        masked = build({"missing_value": np.float32(.75)}, ordinal=301)
        self.assertEqual([s["chlorophyll"] for s in decode_day(masked, 301)["samples"]], [None, None])
        client = MaskedClient(at(31), {"301": masked, "300": build(ordinal=300)})
        data = fetch(client, BOUNDS)
        self.assertEqual((data["dataset"], data["valid_cells"]), (FULL.format("300"), 1))

    def test_packed_newest_file_never_falls_back(self):
        client = MaskedClient(at(31), {"301": build({"scale_factor": 2.0}, ordinal=301), "300": build(ordinal=300)})
        with self.assertRaisesRegex(ValueError, REFUSAL):
            fetch(client, BOUNDS)
        self.assertFalse([u for u in client.urls if "V2026300_" in u])


def decode_day(body, ordinal):
    day = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=ordinal - 1)
    return read_subset(body, SMALL_BOUNDS, "synthetic.nc", day)


if __name__ == "__main__":
    unittest.main()
