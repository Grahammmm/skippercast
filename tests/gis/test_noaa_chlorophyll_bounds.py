"""Chlorophyll bounds are admitted before any provider request or decode."""

from copy import deepcopy
from datetime import datetime, timezone
import unittest

from skippercast.pipeline.noaa_chlorophyll import fetch, read_subset
from tests.gis.test_noaa_chlorophyll import BOUNDS, FakeClient, NoaaChlorophyllTests

MSG = "Invalid regional chlorophyll bounds"
DAY = datetime(2026, 9, 22, tzinfo=timezone.utc)
HUGE = 10 ** 400
BAD = {
    "reversed": {"latitude": [36, 35], "longitude": [-122, -120]},
    "equal": {"latitude": [35, 35], "longitude": [-122, -120]},
    "missing_key": {"latitude": [35, 36]},
    "not_dict": [[35, 36], [-122, -120]],
    "scalar_axis": {"latitude": 35, "longitude": [-122, -120]},
    "triple": {"latitude": [35, 36, 37], "longitude": [-122, -120]},
    "string": {"latitude": ["35", "36"], "longitude": [-122, -120]},
    "none": {"latitude": [None, 36], "longitude": [-122, -120]},
    "bool_south": {"latitude": [False, 36], "longitude": [-122, -120]},
    "bool_north": {"latitude": [35, True], "longitude": [-122, -120]},
    "bool_west": {"latitude": [35, 36], "longitude": [False, -120]},
    "bool_east": {"latitude": [35, 36], "longitude": [-122, True]},
    "nan": {"latitude": [35, float("nan")], "longitude": [-122, -120]},
    "inf": {"latitude": [35, 36], "longitude": [-122, float("inf")]},
    "huge": {"latitude": [35, 36], "longitude": [-122, HUGE]},
    "out_of_range": {"latitude": [35, 81], "longitude": [-122, -120]},
}


class Exploding(FakeClient):
    def get(self, url, as_binary=False):
        raise AssertionError("client reached")


class ChlorophyllBoundsTests(unittest.TestCase):
    def test_invalid_bounds_never_contact_client(self):
        for name, bounds in BAD.items():
            with self.subTest(name):
                client = Exploding(datetime(2026, 10, 27, tzinfo=timezone.utc))
                with self.assertRaisesRegex(ValueError, MSG):
                    fetch(client, bounds)
                self.assertEqual(client.urls, [])

    def test_direct_subset_has_same_bounds_contract(self):
        body = NoaaChlorophyllTests().fixture()
        for name, bounds in BAD.items():
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, MSG):
                    read_subset(body, bounds, "x.nc", DAY)
                with self.assertRaisesRegex(ValueError, MSG):
                    read_subset(b"garbage", bounds, "x.nc", DAY)

    def test_valid_numeric_bounds_preserve_result(self):
        body = NoaaChlorophyllTests().fixture()
        base = {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.95]}
        for bounds in (base, {"latitude": (34.95, 35.05), "longitude": (-121.05, -120.95)},
                       {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.95], "extra": 1}):
            before = deepcopy(bounds)
            data = read_subset(body, bounds, "x.nc", DAY)
            self.assertEqual(bounds, before)
            self.assertEqual((data["valid_cells"], data["total_cells"]), (1, 2))
        ints = {"latitude": [34, 36], "longitude": [-122, -120]}
        self.assertEqual(read_subset(body, ints, "x.nc", DAY)["total_cells"], 2)

    def test_fetch_valid_bounds_keeps_query_and_requested_bounds(self):
        client = FakeClient(datetime(2026, 10, 27, tzinfo=timezone.utc))
        data = fetch(client, BOUNDS)
        self.assertIs(data["requested_bounds"], BOUNDS)
        self.assertIn("north=35.85&south=34.95&west=-121.95&east=-120.55&accept=netcdf", data["query_url"])

    def test_boolean_latitude_no_longer_qualifies_but_numeric_zero_does(self):
        body = NoaaChlorophyllTests().fixture()
        with self.assertRaisesRegex(ValueError, MSG):
            read_subset(body, {"latitude": [False, 36], "longitude": [-122, -120]}, "x.nc", DAY)
        self.assertEqual(read_subset(body, {"latitude": [0, 36], "longitude": [-122, -120]}, "x.nc", DAY)["total_cells"], 2)

    def test_valid_bounds_transport_error_propagates_without_retry(self):
        client = FakeClient(datetime(2026, 10, 27, tzinfo=timezone.utc), fail="ncss")
        with self.assertRaisesRegex(OSError, "fetch failed"):
            fetch(client, BOUNDS)
        self.assertEqual(len(client.urls), 2)


if __name__ == "__main__":
    unittest.main()
