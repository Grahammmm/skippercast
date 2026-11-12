"""NOAA SST subsets whose latitude or longitude axis repeats a coordinate are refused."""

from datetime import datetime, timezone
from io import BytesIO
import unittest

import numpy as np
from scipy.io import netcdf_file

from skippercast.pipeline.noaa_sst import PATH, fetch, read_subset
from tests.gis.test_noaa_sst_fetch import FakeClient, catalog, name

BOUNDS = {"latitude": [34.9, 35.2], "longitude": [-121.2, -120.8]}
REFUSAL = r"^NOAA SST axes changed$"


def subset(lat, lon, temp=None, mask=None, lat_dims=("lat",), lon_dims=("lon",)):
    """Synthetic classic NetCDF; temperature/error/mask default to distinct per-cell values."""
    stream = BytesIO()
    with netcdf_file(stream, mode="w") as nc:
        nc.createDimension("time", 1)
        nc.createDimension("lat", len(lat))
        nc.createDimension("lon", len(lon))
        nc.createDimension("pair", 2)
        t = nc.createVariable("time", "i", ("time",))
        t.units = "seconds since 1981-01-01 00:00:00"
        t[:] = [1443009600]
        nc.createVariable("lat", "f", lat_dims)[:] = lat
        nc.createVariable("lon", "f", lon_dims)[:] = lon
        n_lat, n_lon = len(lat), len(lon)
        cells = np.arange(n_lat * n_lon).reshape(1, n_lat, n_lon)
        for key, values in (("analysed_sst", 1800 + 10 * cells if temp is None else temp),
                            ("analysis_error", 20 + cells)):
            var = nc.createVariable(key, "h", ("time", "lat", "lon"))
            var.units = "kelvin"
            var.scale_factor = .01
            if key == "analysed_sst":
                var.add_offset = 273.15
            var[:] = values
        m = nc.createVariable("mask", "b", ("time", "lat", "lon"))
        m.flag_values = np.array([1, 2, 4], dtype="i1")
        m[:] = np.ones((1, n_lat, n_lon), dtype="i1") if mask is None else mask
        nc.flush()
        return stream.getvalue()


class DuplicateAxisTests(unittest.TestCase):
    def refused(self, body):
        with self.assertRaisesRegex(ValueError, REFUSAL):
            read_subset(body, BOUNDS, "reviewed.nc")

    def test_duplicate_latitude_refuses(self):
        self.refused(subset([35.025, 35.025], [-121.025, -120.975]))

    def test_duplicate_latitude_with_masked_duplicate_row_refuses(self):
        mask = [[[1, 1], [2, 2]]]
        self.refused(subset([35.025, 35.025], [-121.025, -120.975], temp=[[[1800, 1900], [-32768, -32768]]], mask=mask))

    def test_duplicate_longitude_refuses(self):
        self.refused(subset([35.025, 34.975], [-121.025, -121.025]))

    def test_both_axes_duplicated_refuses(self):
        self.refused(subset([35.025, 35.025], [-121.025, -121.025]))

    def test_nonadjacent_duplicate_refuses(self):
        self.refused(subset([35.075, 35.025, 35.075], [-121.025, -120.975]))
        self.refused(subset([35.025, 34.975], [-121.025, -120.975, -121.025]))

    def test_rank_two_coordinates_refuse_named(self):
        two_d = [[35.025, 34.975], [35.025, 34.975]]
        self.refused(subset(two_d, [-121.025, -120.975], lat_dims=("lat", "pair")))
        self.refused(subset([35.025, 34.975], two_d, lon_dims=("lon", "pair")))


class OrdinaryAxisTests(unittest.TestCase):
    def rows(self, body):
        data = read_subset(body, BOUNDS, "reviewed.nc")
        return data, [(r["latitude"], r["longitude"], r["analysed_sst"], r["analysis_error"]) for r in data["samples"]]

    def test_descending_latitude_ascending_longitude_keep_order_and_values(self):
        data, rows = self.rows(subset([35.025, 34.975], [-121.025, -120.975]))
        self.assertEqual(rows, [(35.025, -121.025, 18.0, .2), (35.025, -120.975, 18.1, .21),
                                (34.975, -121.025, 18.2, .22), (34.975, -120.975, 18.3, .23)])
        self.assertEqual((data["valid_cells"], data["total_cells"]), (4, 4))

    def test_ascending_latitude_descending_longitude_keep_order(self):
        _, rows = self.rows(subset([34.975, 35.025], [-120.975, -121.025]))
        self.assertEqual([(y, x) for y, x, _, _ in rows],
                         [(34.975, -120.975), (34.975, -121.025), (35.025, -120.975), (35.025, -121.025)])

    def test_singleton_axes_are_valid(self):
        data, rows = self.rows(subset([35.025], [-121.025]))
        self.assertEqual(rows, [(35.025, -121.025, 18.0, .2)])
        self.assertEqual((data["valid_cells"], data["total_cells"]), (1, 1))
        _, rows = self.rows(subset([35.025], [-121.025, -120.975]))
        self.assertEqual([(y, x) for y, x, _, _ in rows], [(35.025, -121.025), (35.025, -120.975)])
        _, rows = self.rows(subset([35.025, 34.975], [-121.025]))
        self.assertEqual([(y, x) for y, x, _, _ in rows], [(35.025, -121.025), (34.975, -121.025)])


class FetchCompositionTests(unittest.TestCase):
    STAMP = "20260923000000"

    def client(self, body):
        client = FakeClient(catalog(2026, self.STAMP), body)
        client.now = datetime(2026, 9, 23, 6, tzinfo=timezone.utc)
        return client

    def test_fetch_rejects_duplicate_subset_after_exactly_two_reads(self):
        client = self.client(subset([35.025, 35.025], [-121.025, -120.975]))
        with self.assertRaisesRegex(ValueError, REFUSAL):
            fetch(client, BOUNDS)
        self.assertEqual(len(client.urls), 2)
        self.assertEqual(client.bodies, [])

    def test_fetch_accepts_valid_same_shape_control(self):
        client = self.client(subset([35.025, 34.975], [-121.025, -120.975]))
        result = fetch(client, BOUNDS)
        self.assertEqual(len(client.urls), 2)
        self.assertEqual(result["total_cells"], 4)
        self.assertEqual(result["dataset"], f"{PATH}/2026/{name(self.STAMP)}")
