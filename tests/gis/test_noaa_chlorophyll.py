"""NOAA ocean-color gaps and source clocks must survive ingestion."""

from datetime import datetime, timezone
from io import BytesIO
import json
import re
import unittest
from xml.etree import ElementTree

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


DIR = "chlociVIIRSnpp-n20GlobalDailyWW00/V{}_D1_NPP-N20_WW00_chloci.nc"


class CatalogClient:
    """Catalog of explicit VIIRS stems (e.g. "2024366"); binary reads reuse the Oct 2026 fixtures."""

    def __init__(self, now, stems):
        self.now, self.stems, self.urls = now, stems, []

    def get(self, url, as_binary=False):
        self.urls.append(url)
        if url == CATALOG:
            return "<catalog>" + "".join(f'<dataset urlPath="{DIR.format(s)}"/>' for s in self.stems) + "</catalog>"
        day = re.search(r"V2026(\d{3})_", url).group(1)
        return (FIXTURES / f"morro-bay-V2026{day}.nc").read_bytes()


def paths(client):
    return [p for _, p in recent_files(client)]


class NoaaChlorophyllOrdinalDateTests(unittest.TestCase):
    def test_catalog_bad_ordinal_keeps_valid_siblings(self):
        valid = DIR.format("2026300")
        for stems in (("2026000", "2026367", "2026999", "2026300"), ("2026300", "2026000", "2026367", "2026999"),
                      ("2026367", "2026300", "2026000")):
            with self.subTest(stems=stems):
                client = CatalogClient(at(30), stems)
                found = recent_files(client)
                self.assertEqual([p for _, p in found], [valid])
                self.assertEqual(found[0][0], datetime(2026, 10, 27, tzinfo=timezone.utc))
                self.assertEqual(client.urls, [CATALOG])

    def test_catalog_nonleap_366_is_not_next_year(self):
        now = datetime(2027, 1, 2, tzinfo=timezone.utc)
        found = recent_files(CatalogClient(now, ("2026366", "2026365")))
        self.assertEqual([(d.date().isoformat(), p) for d, p in found], [("2026-12-31", DIR.format("2026365"))])

    def test_catalog_leap_366_and_year_edges(self):
        now = datetime(2025, 1, 2, tzinfo=timezone.utc)
        found = recent_files(CatalogClient(now, ("2024366", "2024365", "2024001", "2025001", "2025002", "2025003")))
        self.assertEqual([d.date().isoformat() for d, _ in found], ["2025-01-02", "2025-01-01", "2024-12-31"])
        self.assertEqual(found[2][1], DIR.format("2024366"))
        self.assertEqual(paths(CatalogClient(datetime(2025, 1, 1, tzinfo=timezone.utc), ("2024366", "2024366"))),
                         [DIR.format("2024366")])

    def test_catalog_all_invalid_has_existing_named_error(self):
        for stems in (("2026000", "2026367"), ("2026000", "2026999", "2026366")):
            with self.subTest(stems=stems), self.assertRaisesRegex(ValueError, "No dated NOAA VIIRS chlorophyll file"):
                recent_files(CatalogClient(at(30), stems))
        with self.assertRaisesRegex(ValueError, "No dated NOAA VIIRS chlorophyll file"):
            recent_files(CatalogClient(at(30), ("2026000", "2026367", "2026310")))

    def test_fetch_invalid_catalog_siblings_never_requested(self):
        client = CatalogClient(at(30), ("2026000", "2026300", "2026367", "2026999"))
        data = fetch(client, BOUNDS)
        self.assertEqual((data["dataset"], data["valid_cells"], data["sample_at"]), (FULL.format("300"), 353, "2026-10-27T12:00:00Z"))
        self.assertEqual(len(client.urls), 2)
        self.assertEqual(client.urls[0], CATALOG)
        self.assertIn("V2026300_", client.urls[1])
        self.assertFalse([u for u in client.urls if re.search(r"V2026(000|367|999)_", u)])

    def test_malformed_catalog_xml_still_propagates(self):
        class Bad(CatalogClient):
            def get(self, url, as_binary=False):
                return "<catalog><dataset"
        with self.assertRaises(ElementTree.ParseError):
            recent_files(Bad(at(30), ()))


if __name__ == "__main__":
    unittest.main()
