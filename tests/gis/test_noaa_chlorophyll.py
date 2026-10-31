"""NOAA ocean-color gaps and source clocks must survive ingestion."""

from datetime import datetime, timezone
from io import BytesIO
import json
import re
import unittest

from scipy.io import netcdf_file

from skippercast.pipeline.noaa_chlorophyll import latest_file, read_subset
from skippercast.pipeline.noaa_chlorophyll import CATALOG, MAX_AGE_HOURS, MAX_FILES, fetch, recent_files
from tests._support import FIXTURES as FIXTURE_ROOT, ROOT


class NoaaChlorophyllTests(unittest.TestCase):
    def fixture(self):
        stream = BytesIO()
        with netcdf_file(stream, mode="w") as nc:
            for name, n in (("time", 1), ("altitude", 1), ("lat", 1), ("lon", 2)):
                nc.createDimension(name, n)
            t = nc.createVariable("time", "d", ("time",))
            t.units = "seconds since 1970-01-01 00:00:00Z"
            t[:] = [1790078400]
            nc.createVariable("altitude", "d", ("altitude",))[:] = [0]
            nc.createVariable("lat", "d", ("lat",))[:] = [35.0]
            nc.createVariable("lon", "d", ("lon",))[:] = [-121.0, -120.9625]
            chl = nc.createVariable("chl_oci", "f", ("time", "altitude", "lat", "lon"))
            chl.units = "mg m^-3"
            chl.standard_name = "mass_concentration_of_chlorophyll_a_in_sea_water"
            chl._FillValue = -32767.0
            chl[:] = [[[[.75, -32767.0]]]]
            nc.flush()
            body = stream.getvalue()
        return body

    def test_real_value_and_gap_are_distinct(self):
        bounds = {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.95]}
        day = datetime(2026, 9, 22, tzinfo=timezone.utc)
        data = read_subset(self.fixture(), bounds, "reviewed.nc", day)
        self.assertEqual(data["sample_at"], "2026-09-22T12:00:00Z")
        self.assertEqual((data["valid_cells"], data["total_cells"]), (1, 2))
        self.assertEqual(data["samples"][0]["chlorophyll"], .75)
        self.assertIsNone(data["samples"][1]["chlorophyll"])

    def test_filename_time_conflict_is_rejected(self):
        bounds = {"latitude": [34.95, 35.05], "longitude": [-121.05, -120.95]}
        with self.assertRaisesRegex(ValueError, "conflicts"):
            read_subset(self.fixture(), bounds, "reviewed.nc", datetime(2026, 9, 21, tzinfo=timezone.utc))

    def test_catalog_requires_dated_exact_path(self):
        class Client:
            now = datetime(2026, 9, 24, tzinfo=timezone.utc)
            def get(self, _url):
                return '<catalog><dataset urlPath="chlociVIIRSnpp-n20GlobalDailyWW00/V2026265_D1_NPP-N20_WW00_chloci.nc"/><dataset urlPath="other/V2026266_D1_NPP-N20_WW00_chloci.nc"/></catalog>'
        day, path = latest_file(Client())
        self.assertEqual(day.date().isoformat(), "2026-09-22")
        self.assertTrue(path.startswith("chlociVIIRSnpp-n20GlobalDailyWW00/"))


FIXTURES = FIXTURE_ROOT / "noaa-chlorophyll"
BOUNDS = {"latitude": [34.95, 35.85], "longitude": [-121.95, -120.55]}
FULL = "chlociVIIRSnpp-n20GlobalDailyWW00/V2026{}_D1_NPP-N20_WW00_chloci.nc"


class FakeClient:
    def __init__(self, now, days=("300", "301"), fail=None):
        self.now, self.days, self.fail, self.urls = now, days, fail, []

    def get(self, url, as_binary=False):
        self.urls.append(url)
        if url == CATALOG:
            return "<catalog>" + "".join(f'<dataset urlPath="{FULL.format(d)}"/>' for d in self.days) + "</catalog>"
        if self.fail and self.fail in url:
            raise OSError("fetch failed")
        day = re.search(r"V2026(\d{3})_", url).group(1)
        return (FIXTURES / f"morro-bay-V2026{day}.nc").read_bytes()


def at(day, hour=0):
    return datetime(2026, 10, day, hour, tzinfo=timezone.utc)


class NoaaChlorophyllWalkBackTests(unittest.TestCase):
    def test_real_populated_fixture_decodes(self):
        data = read_subset((FIXTURES / "morro-bay-V2026300.nc").read_bytes(), BOUNDS, FULL.format("300"), at(27))
        self.assertEqual((data["valid_cells"], data["total_cells"]), (353, 975))
        self.assertEqual(data["sample_at"], "2026-10-27T12:00:00Z")
        values = [s["chlorophyll"] for s in data["samples"] if s["chlorophyll"] is not None]
        self.assertEqual((min(values), max(values)), (0.21859, 6.66022))

    def test_real_empty_fixture_stays_empty(self):
        data = read_subset((FIXTURES / "morro-bay-V2026301.nc").read_bytes(), BOUNDS, FULL.format("301"), at(28))
        self.assertEqual((data["valid_cells"], data["total_cells"]), (0, 975))

    def test_empty_newest_walks_back_to_populated_file(self):
        client = FakeClient(at(31))
        data = fetch(client, BOUNDS)
        self.assertEqual(data["dataset"], FULL.format("300"))
        self.assertEqual(data["valid_cells"], 353)
        self.assertIn("V2026300_", data["query_url"])
        self.assertEqual(data["sample_at"], "2026-10-27T12:00:00Z")
        self.assertEqual(len(client.urls), 3)
        self.assertEqual(client.urls[0], CATALOG)
        self.assertIn("V2026301_", client.urls[1])
        self.assertIn("V2026300_", client.urls[2])

    def test_no_populated_file_in_window_keeps_newest_gap(self):
        client = FakeClient(at(31, 13))
        data = fetch(client, BOUNDS)
        self.assertEqual((data["dataset"], data["valid_cells"]), (FULL.format("301"), 0))
        self.assertIn("V2026301_", data["query_url"])
        self.assertFalse([u for u in client.urls if "V2026300_" in u])

    def test_populated_newest_file_is_used_directly(self):
        client = FakeClient(at(30), days=("300",))
        self.assertEqual(fetch(client, BOUNDS)["valid_cells"], 353)
        self.assertEqual(len([u for u in client.urls if "/ncss/" in u]), 1)

    def test_fetch_error_propagates_without_fallback(self):
        client = FakeClient(at(31), fail="V2026301_")
        with self.assertRaises(OSError):
            fetch(client, BOUNDS)
        self.assertFalse([u for u in client.urls if "V2026300_" in u])

    def test_window_cap_duplicates_and_future_files(self):
        client = FakeClient(at(31), days=("299", "300", "301", "302", "303", "305"))
        self.assertEqual([p for _, p in recent_files(client)], [FULL.format(d) for d in ("303", "302", "301")])
        self.assertEqual(client.urls, [CATALOG])
        edge = recent_files(FakeClient(at(31, 12), days=("299", "300", "301", "301")))
        self.assertEqual([p for _, p in edge], [FULL.format("301"), FULL.format("300")])  # 300 is exactly 96 h old
        self.assertEqual([p for _, p in recent_files(FakeClient(at(31, 13), days=("300",)))], [FULL.format("300")])

    def test_cap_and_age_pin(self):
        sources = json.loads((ROOT / "catalog" / "sources.json").read_text())
        source = next(s for s in sources["sources"] if s["id"] == "noaa-viirs-merged-chlorophyll")
        self.assertEqual(MAX_AGE_HOURS, source["request"]["max_age_hours"])
        self.assertEqual(MAX_FILES, 3)


if __name__ == "__main__":
    unittest.main()
