"""Offline contract test for the WCOFS habitat reader on a small synthetic THREDDS/DAP answer.

The fake client answers only the URLs `wcofs_surface` is expected to ask for; any other request raises,
so a new or changed request fails here instead of reading a silent empty answer.
"""
from datetime import datetime, timedelta, timezone
import re
import unittest
from urllib.parse import unquote

from skippercast.pipeline.habitat_dynamics import WCOFS_URL, wcofs_surface
from tests._support import NOW

REGION = {"bounds": [-121.1, 34.9, -120.9, 35.1]}
ORIGIN = datetime(2016, 1, 1, tzinfo=timezone.utc)
UNITS = {"temp": "Celsius", "u_eastward": "meters second-1", "v_northward": "meters second-1", "Depth": "m"}
CELLS = {"mask": [1, 1, 1, 1], "temp": [15.0, 15.5, 16.0, 16.5],
         "u_eastward": [0.1, 0.2, -0.1, 0.0], "v_northward": [0.05, -0.05, 0.0, 0.3]}


def name(cycle, fh):
    return f"wcofs.t{cycle:%H}z.{cycle:%Y%m%d}.regulargrid.f{fh:03d}.nc"


def ascii(arrays):
    lines = ["Dataset {", "} wcofs;", "-" * 45]
    for key, (shape, values) in arrays.items():
        lines.append(key + "".join(f"[{d}]" for d in shape))
        width = shape[-1]
        for i in range(0, len(values), width):
            lines.append(f"[{i // width}], " + ", ".join(repr(float(v)) for v in values[i:i + width]))
    return "\n".join(lines) + "\n"


def das(units, flags, time_units):
    blocks = [f'    {v} {{\n        String units "{u}";\n    }}' for v, u in units.items()]
    blocks.append(f'    mask {{\n        String flag_meanings "{flags}";\n    }}')
    blocks.append(f'    time {{\n        String units "{time_units}";\n    }}')
    return "Attributes {\n" + "\n".join(blocks) + "\n}\n"


def answer(day=NOW, steps=(0, 3, 4, 75), units=None, flags="land, water", time_units="hours since 2016-01-01 00:00:00",
           per_hour=1.0, lat=(35.0, 35.04), lon=(-121.0, -120.96), depth0=0, cells=None, frame_lat=None):
    """Pages keyed `catalog/<Y/m/d>` or `<Y/m/d>/<file><.dds|.das|.axes|.frame>` for cycle t03z of `day`."""
    cycle = day.replace(hour=3, minute=0, second=0, microsecond=0)
    files = [name(cycle, fh) for fh in steps] + [name(cycle.replace(hour=0), 0)]  # plus an older t00z cycle
    folder = f"{day:%Y/%m/%d}"
    pages = {"catalog/" + folder: "<catalog>\n" + "".join(f'  <dataset name="{f}" urlPath="x/{f}"/>\n' for f in files) + "</catalog>\n"}
    values = {**CELLS, **(cells or {})}
    ny, nx = len(lat), len(lon)
    grid_lat = frame_lat or [y for y in lat for _ in lon]
    for fh in steps:
        f = f"{folder}/{name(cycle, fh)}"
        pages[f + ".dds"] = f"Dataset {{\n    Float64 Latitude[ny = {ny}][nx = {nx}];\n    Float64 Longitude[ny = {ny}][nx = {nx}];\n}} x;\n"
        pages[f + ".das"] = das({**UNITS, **(units or {})}, flags, time_units)
        pages[f + ".axes"] = ascii({"Latitude": ([ny, 1], lat), "Longitude": ([1, nx], lon), "Depth": ([3], [depth0, 1, 2])})
        hours = (cycle - ORIGIN).total_seconds() / 3600 + fh
        pages[f + ".frame"] = ascii({
            "Latitude": ([ny, nx], grid_lat), "Longitude": ([ny, nx], [x for _ in lat for x in lon]),
            "mask": ([ny, nx], values["mask"]), "temp": ([1, 1, ny, nx], values["temp"]),
            "u_eastward": ([1, 1, ny, nx], values["u_eastward"]), "v_northward": ([1, 1, ny, nx], values["v_northward"]),
            "time": ([1], [hours * per_hour])})
    return pages


class FakeDap:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url):
        self.urls.append(url)
        path = url.removeprefix(WCOFS_URL)
        if m := re.fullmatch(r"catalog/NOAA/WCOFS/MODELS/(\d{4}/\d{2}/\d{2})/catalog\.xml", path):
            key = "catalog/" + m[1]
        elif m := re.fullmatch(r"dodsC/NOAA/WCOFS/MODELS/(\d{4}/\d{2}/\d{2}/wcofs\.\S+?\.nc)(\.dds|\.das|\.ascii\?(.+))", path):
            kind = m[2] if m[3] is None else ".frame" if unquote(m[3]).endswith(",time") else ".axes"
            key = m[1] + kind
        else:
            key = None
        if key not in self.pages: raise LookupError("unexpected WCOFS request: " + url)
        return self.pages[key]


def at(cycle, fh=0):
    return int((cycle + timedelta(hours=fh)).timestamp())


class WcofsSurfaceTests(unittest.TestCase):
    def read(self, pages, region=REGION):
        client = FakeDap(pages)
        return wcofs_surface(client, region, NOW), client

    def fails(self, message, pages, region=REGION):
        with self.assertRaises(ValueError) as caught: self.read(pages, region)
        self.assertEqual(str(caught.exception), message)

    def test_happy_path_reads_newest_cycle_native_steps_only(self):
        layer, client = self.read(answer())
        cycle = datetime(2026, 9, 28, 3, tzinfo=timezone.utc)
        self.assertEqual(layer["issued_at"], "2026-09-28T03:00:00Z")
        self.assertEqual([f["time"] for f in layer["frames"]], [at(cycle, 0), at(cycle, 3)])
        self.assertEqual([f["source_file"] for f in layer["frames"]], [name(cycle, 0), name(cycle, 3)])
        for frame in layer["frames"]:
            self.assertEqual((frame["valid_cells"], frame["total_cells"], len(frame["cells"])), (4, 4, 4))
        self.assertEqual((layer["valid_cells"], layer["total_cells"]), (8, 8))
        self.assertEqual(layer["resolution_degrees"], [0.04, 0.04])
        self.assertEqual(layer["frames"][0]["cells"][0][:5], [35.0, -121.0, 15.0, 0.1, 0.05])
        self.assertEqual(client.urls[0], WCOFS_URL + "catalog/NOAA/WCOFS/MODELS/2026/09/28/catalog.xml")
        self.assertFalse([u for u in client.urls if re.search(r"f075|f004|t00z", u)])
        frame_query = next(unquote(u.split("?", 1)[1]) for u in client.urls if "mask" in unquote(u))
        self.assertEqual(frame_query, "Latitude[0:1:1][0:1:1],Longitude[0:1:1][0:1:1],mask[0:1:1][0:1:1],"
                         "temp[0][0][0:1:1][0:1:1],u_eastward[0][0][0:1:1][0:1:1],v_northward[0][0][0:1:1][0:1:1],time")

    def test_land_and_fill_are_skipped_but_counted_and_wild_current_is_dropped_as_a_pair(self):
        cells = {"mask": [1, 0, 1, 1], "temp": [15.0, 15.5, 9.96921e36, 16.5], "u_eastward": [0.1, 0.2, -0.1, 99]}
        layer, _ = self.read(answer(cells=cells))
        for frame in layer["frames"]:
            self.assertEqual((frame["valid_cells"], frame["total_cells"]), (2, 4))
            self.assertEqual([c[:5] for c in frame["cells"]], [[35.0, -121.0, 15.0, 0.1, 0.05], [35.04, -120.96, 16.5, None, None]])
        self.assertEqual((layer["valid_cells"], layer["total_cells"]), (4, 8))

    def test_today_catalog_failure_falls_back_to_yesterday_and_both_failing_is_named(self):
        yesterday = NOW - timedelta(days=1)
        layer, client = self.read(answer(day=yesterday))
        self.assertEqual(client.urls[:2], [WCOFS_URL + "catalog/NOAA/WCOFS/MODELS/2026/09/28/catalog.xml",
                                           WCOFS_URL + "catalog/NOAA/WCOFS/MODELS/2026/09/27/catalog.xml"])
        self.assertTrue(all("/MODELS/2026/09/27/" in u for u in client.urls[1:]))
        self.assertEqual(layer["issued_at"], "2026-09-27T03:00:00Z")
        self.fails("No populated WCOFS forecast catalog in the last two dates", {})

    def test_changed_units_fail_by_variable(self):
        self.fails("WCOFS units changed: temp", answer(units={"temp": "degC"}))
        self.fails("WCOFS units changed: u_eastward", answer(units={"u_eastward": "cm/s"}))

    def test_reordered_wet_mask_fails(self):
        self.fails("WCOFS wet-mask contract changed", answer(flags="water, land"))

    def test_time_origin_variants_scale_and_mismatches_fail(self):
        cycle = datetime(2026, 9, 28, 3, tzinfo=timezone.utc)
        for units, per_hour in (("seconds since 2016-01-01T00:00:00Z", 3600), ("days since 2016-01-01 00:00:00 UTC", 1 / 24)):
            with self.subTest(units=units):
                layer, _ = self.read(answer(time_units=units, per_hour=per_hour))
                self.assertEqual([f["time"] for f in layer["frames"]], [at(cycle, 0), at(cycle, 3)])
        self.fails("Unknown WCOFS time unit", answer(time_units="minutes since 2016-01-01 00:00:00", per_hour=60))
        self.fails("WCOFS valid time disagrees with cycle", answer(time_units="hours since 2016-01-02 00:00:00"))

    def test_grid_spacing_and_surface_layer_contracts(self):
        self.fails("WCOFS regular-grid spacing changed", answer(lat=(35.0, 35.08)))
        self.fails("Requested WCOFS layer is not surface", answer(depth0=1))

    def test_frame_coordinate_drift_and_incomplete_grid_fail(self):
        self.fails("WCOFS coordinate drift", answer(frame_lat=[35.0, 35.0, 35.04, 36.0]))
        self.fails("Incomplete WCOFS grid", answer(cells={"temp": [15.0, 15.5, 16.0]}))

    def test_cycle_without_native_steps_fails(self):
        self.fails("No WCOFS forecast steps returned", answer(steps=(4, 75)))

    def test_single_row_region_is_named_not_an_index_error(self):
        self.fails("WCOFS regional subset needs at least 2 x 2 cells", answer(), {"bounds": [-121.1, 34.95, -120.9, 35.02]})
        self.fails("WCOFS regional subset needs at least 2 x 2 cells", answer(), {"bounds": [-121.05, 34.9, -120.98, 35.1]})


if __name__ == "__main__":
    unittest.main()
