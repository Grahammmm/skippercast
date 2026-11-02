"""NOAA HFRNet: bounds checked before any request; unreadable metadata and odd depth are named errors."""

from datetime import datetime, timezone
from io import BytesIO
import unittest

from scipy.io import netcdf_file

from skippercast.pipeline.noaa_hfr import fetch, latest_time, read_subset

WHEN = datetime(2026, 9, 24, 22, tzinfo=timezone.utc)
BOUNDS = {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.9]}
RESOLUTION = [.05394, .06246]
METADATA_XML = ('<gridDataset><axis name="lat"><values resolution="0.05394"/></axis><axis name="lon">'
                '<values resolution="0.06246"/></axis><TimeSpan><end>{end}</end></TimeSpan></gridDataset>')


def subset(depth=(1.4,)):
    stream = BytesIO()
    with netcdf_file(stream, mode="w") as nc:
        for name, size in (("time", 1), ("lat", 1), ("lon", 2)):
            nc.createDimension(name, size)
        t = nc.createVariable("time", "i", ("time",))
        t.units = "seconds since 1970-01-01"
        t[:] = [1790287200]
        if len(depth) == 1:
            nc.createVariable("depth", "f", ()).data[...] = depth[0]
        else:
            nc.createDimension("depth", len(depth))
            nc.createVariable("depth", "f", ("depth",))[:] = list(depth)
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
        return stream.getvalue()


class Client:
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)

    def __init__(self, metadata=METADATA_XML.format(end="2026-09-24T22:00:00Z"), body=None):
        self.metadata, self.body, self.calls = metadata, body, []

    def get(self, url, as_binary=False):
        self.calls.append(url)
        return self.body if as_binary else self.metadata


class BoundsBeforeRequestTests(unittest.TestCase):
    def assert_refused(self, bounds):
        client = Client(body=subset())
        with self.assertRaisesRegex(ValueError, r"^Invalid NOAA HFRNet regional bounds$"):
            fetch(client, bounds)
        self.assertEqual(client.calls, [])

    def test_south_above_north_makes_no_request(self):
        self.assert_refused({"latitude": [35.05, 34.95], "longitude": [-121.05, -120.9]})

    def test_west_not_below_east_and_out_of_range_make_no_request(self):
        self.assert_refused({"latitude": [34.95, 35.05], "longitude": [-120.9, -121.05]})
        self.assert_refused({"latitude": [34.95, 35.05], "longitude": [-120.9, -120.9]})
        self.assert_refused({"latitude": [34.95, 85.0], "longitude": [-121.05, -120.9]})
        self.assert_refused({"latitude": [34.95, 35.05], "longitude": [-181.0, -120.9]})

    def test_malformed_bounds_make_no_request(self):
        for bounds in ({"latitude": [True, 35.05], "longitude": [-121.05, -120.9]},
                       {"latitude": [34.95, 35.05], "longitude": [-121.05, False]},
                       {"latitude": [float("nan"), 35.05], "longitude": [-121.05, -120.9]},
                       {"latitude": [34.95, 35.05], "longitude": [-121.05, float("inf")]},
                       {"latitude": [34.95, 35.05], "longitude": [float("-inf"), -120.9]},
                       {"latitude": [34.95], "longitude": [-121.05, -120.9]},
                       {"latitude": [34.95, 35.0, 35.05], "longitude": [-121.05, -120.9]},
                       {"latitude": ["34.95", "35.05"], "longitude": [-121.05, -120.9]},
                       {"latitude": "34.95,35.05", "longitude": [-121.05, -120.9]},
                       {"latitude": [34.95, 35.05]},
                       {"longitude": [-121.05, -120.9]},
                       None, [[34.95, 35.05], [-121.05, -120.9]]):
            with self.subTest(bounds=bounds):
                self.assert_refused(bounds)


class MetadataTests(unittest.TestCase):
    def test_non_xml_metadata_is_named(self):
        for body in (b"<html>oops", "<html>oops", b"", "not xml at all"):
            with self.subTest(body=body):
                with self.assertRaises(ValueError) as caught:
                    latest_time(Client(metadata=body))
                self.assertEqual(str(caught.exception), "NOAA HFRNet metadata is not XML")
                self.assertIsNone(caught.exception.__cause__)

    def test_unreadable_end_time_is_named_without_raw_text(self):
        for end in ("yesterday", "2026-13-40T99:00:00Z", ""):
            with self.subTest(end=end):
                with self.assertRaises(ValueError) as caught:
                    latest_time(Client(metadata=METADATA_XML.format(end=end)))
                self.assertEqual(str(caught.exception), "NOAA HFRNet advertised time unreadable")
                self.assertNotIn("yesterday", str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
                self.assertTrue(caught.exception.__suppress_context__)

    def test_readable_but_stale_time_keeps_its_message(self):
        with self.assertRaisesRegex(ValueError, "stale or future"):
            latest_time(Client(metadata=METADATA_XML.format(end="2026-09-23T22:00:00Z")))


class DepthTests(unittest.TestCase):
    def test_depth_must_be_one_finite_value(self):
        for depth in ((1.4, 2.0), (float("nan"),), (float("inf"),)):
            with self.subTest(depth=depth):
                with self.assertRaisesRegex(ValueError, r"^NOAA HFRNet depth changed$"):
                    read_subset(subset(depth), BOUNDS, WHEN, RESOLUTION)

    def test_valid_fetch_is_unchanged(self):
        client = Client(body=subset())
        data = fetch(client, BOUNDS)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(data["sample_at"], "2026-09-24T22:00:00Z")
        self.assertEqual((data["valid_cells"], data["total_cells"]), (1, 2))
        self.assertIs(type(data["nominal_depth_m"]), float)
        self.assertEqual(data["nominal_depth_m"], 1.399999976158142)
        self.assertEqual(data["requested_bounds"], BOUNDS)
        self.assertEqual(data["native_resolution_degrees"], RESOLUTION)
        tuple_bounds = {"latitude": (34.95, 35.05), "longitude": (-121, -120.9)}
        self.assertEqual(fetch(Client(body=subset()), tuple_bounds)["total_cells"], 2)


if __name__ == "__main__":
    unittest.main()
