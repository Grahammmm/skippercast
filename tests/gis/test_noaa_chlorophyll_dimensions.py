"""NOAA chlorophyll: named axes must match the decoder's indexing; shape equality alone is not identity."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import unittest

import numpy as np
from scipy.io import netcdf_file

from skippercast.pipeline.collect import source
from skippercast.pipeline.noaa_chlorophyll import fetch, read_subset
from tests.gis.test_noaa_chlorophyll import BOUNDS, FIXTURES, FULL, MaskedClient, at

AXES = ("time", "altitude", "lat", "lon")
DAY = datetime(2026, 9, 22, tzinfo=timezone.utc)
WIDE = {"latitude": [34.9, 35.1], "longitude": [-121.1, -120.9]}
REFUSAL = "NOAA chlorophyll axes changed"


def build(chl_dims=AXES, coord_dims=None, sizes=(1, 1, 2, 2), values=(1, 2, 3, 4), ordinal=265, scalar=None):
    """Classic NetCDF with distinct values; coord_dims maps a coordinate name to a replacement dimension tuple."""
    stamp = datetime(2026, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=ordinal - 1)
    coord_dims = coord_dims or {}
    size = dict(zip(AXES, sizes))
    stream = BytesIO()
    with netcdf_file(stream, mode="w") as nc:
        for name in AXES:
            nc.createDimension(name, size[name])
        data = {"time": [int(stamp.timestamp())] * size["time"], "altitude": [0] * size["altitude"],
                "lat": [35.0 + .01 * i for i in range(size["lat"])], "lon": [-121.0 + .01 * i for i in range(size["lon"])]}
        for name in AXES:
            dims = coord_dims.get(name, (name,))
            var = nc.createVariable(name, "d", dims)
            if name in coord_dims and dims != (name,):
                continue
            var[:] = data[name]
        nc.variables["time"].units = "seconds since 1970-01-01 00:00:00Z"
        chl = nc.createVariable("chl_oci", "f", chl_dims)
        chl.units = "mg m^-3"
        chl.standard_name = "mass_concentration_of_chlorophyll_a_in_sea_water"
        chl._FillValue = -32767.0
        chl[:] = np.array(list(values), dtype="f").reshape(chl.shape)
        nc.flush()
        return stream.getvalue()


def decode(body, bounds=WIDE):
    return read_subset(body, bounds, "synthetic.nc", DAY)


class NoaaChlorophyllDimensionTests(unittest.TestCase):
    def test_square_transposed_grid_refused_before_sampling(self):
        with self.assertRaises(ValueError) as caught:
            decode(build(chl_dims=("time", "altitude", "lon", "lat")))
        self.assertEqual(str(caught.exception), REFUSAL)
        rows = decode(build())["samples"]
        self.assertEqual([(r["latitude"], r["longitude"], r["chlorophyll"]) for r in rows],
                         [(35.0, -121.0, 1.0), (35.0, -120.99, 2.0), (35.01, -121.0, 3.0), (35.01, -120.99, 4.0)])

    def test_equal_singleton_dimensions_cannot_swap_identity(self):
        with self.assertRaisesRegex(ValueError, f"^{REFUSAL}$"):
            decode(build(chl_dims=("altitude", "time", "lat", "lon")))
        self.assertEqual(decode(build(sizes=(1, 1, 1, 1), values=(2,)))["total_cells"], 1)
        self.assertEqual(decode(build(sizes=(1, 1, 2, 1), values=(1, 2)))["total_cells"], 2)

    def test_coordinate_variable_dimensions_are_not_aliases(self):
        for name, dims in (("lat", ("lon",)), ("lon", ("lat",)), ("lat", ()), ("lon", ("lat", "lon")),
                           ("altitude", ("time",)), ("time", ("altitude",))):
            with self.subTest(name=name, dims=dims), self.assertRaisesRegex(ValueError, f"^{REFUSAL}$"):
                decode(build(coord_dims={name: dims}))
        with self.assertRaisesRegex(ValueError, f"^{REFUSAL}$"):
            decode(build(sizes=(1, 2, 2, 2), values=range(8)))

    def test_recorded_product_layout_and_result_stays_compatible(self):
        for day, valid, clock in (("300", 353, at(27)), ("301", 0, at(28))):
            body = (FIXTURES / f"morro-bay-V2026{day}.nc").read_bytes()
            data = read_subset(body, BOUNDS, FULL.format(day), clock)
            self.assertEqual((data["valid_cells"], data["total_cells"]), (valid, 975))
            self.assertEqual(data["sample_at"], f"2026-10-{int(day) - 273:02d}T12:00:00Z")

    def test_bad_newest_axes_is_not_missing_scene_fallback(self):
        bad = build(chl_dims=("time", "altitude", "lon", "lat"), ordinal=301)
        client = MaskedClient(at(31), {"301": bad, "300": build(ordinal=300)})
        with self.assertRaisesRegex(ValueError, f"^{REFUSAL}$"):
            fetch(client, {"latitude": [34.9, 35.1], "longitude": [-121.1, -120.9]})
        self.assertFalse([u for u in client.urls if "V2026300_" in u])

    def test_source_wrapper_does_not_report_bad_axes_ok(self):
        body = build(chl_dims=("time", "altitude", "lon", "lat"))
        now = datetime(2026, 9, 22, 13, tzinfo=timezone.utc)
        result = source("synthetic-chl", "Synthetic", "chlorophyll", "https://example.invalid", 96,
                        lambda client: decode(body), now)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["data"])
        self.assertIn(REFUSAL, result["issue"])


if __name__ == "__main__":
    unittest.main()
