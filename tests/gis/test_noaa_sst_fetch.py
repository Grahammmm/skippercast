"""NOAA SST: bounds are checked before any request; an unreadable current-year catalog falls back."""

from datetime import datetime, timezone
import unittest

from skippercast import http
from skippercast.pipeline.noaa_sst import CATALOG, PATH, fetch, latest_file

NOW = datetime(2026, 1, 2, 6, tzinfo=timezone.utc)
GOOD = {"latitude": [34, 35], "longitude": [-121, -120]}


def name(stamp):
    return f"{stamp}-OSPO-L4_GHRSST-SSTfnd-Geo_Polar_Blended_Night-GLOB-v02.0-fv01.0.nc"


def catalog(year, *stamps):
    rows = "".join(f'<dataset urlPath="{PATH}/{year}/{name(s)}"/>' for s in stamps)
    return f"<catalog>{rows}</catalog>".encode()


class FakeClient:
    def __init__(self, *bodies):
        self.now, self.bodies, self.urls = NOW, list(bodies), []

    def get(self, url, as_binary=False):
        self.urls.append(url)
        body = self.bodies.pop(0)
        if isinstance(body, Exception):
            raise body
        return body


class BoundsTests(unittest.TestCase):
    def assert_refused(self, bounds):
        client = FakeClient()
        with self.assertRaisesRegex(ValueError, r"^Invalid NOAA SST regional bounds$"):
            fetch(client, bounds)
        self.assertEqual(client.urls, [])

    def test_reversed_latitude_refused_before_any_request(self):
        self.assert_refused({"latitude": [35, 34], "longitude": [-121, -120]})

    def test_malformed_bounds_refused_before_any_request(self):
        for bounds in ({"latitude": [True, 35], "longitude": [-121, -120]},
                       {"latitude": [34, float("nan")], "longitude": [-121, -120]},
                       {"latitude": [34, 35], "longitude": ["-121", -120]},
                       {"latitude": [34, 35, 36], "longitude": [-121, -120]},
                       {"latitude": [34, 35]},
                       {"latitude": [34, 35], "longitude": [-121, float("inf")]},
                       {"latitude": [34, 35], "longitude": [-181, -120]},
                       {"latitude": [34, 81], "longitude": [-121, -120]},
                       [[34, 35], [-121, -120]], None):
            with self.subTest(bounds=bounds):
                self.assert_refused(bounds)

    def test_oversized_integer_bounds_refused_not_overflow(self):
        for bounds in ({"latitude": [34, 35], "longitude": [-121, 10**400]},
                       {"latitude": [-10**400, 35], "longitude": [-121, -120]}):
            with self.subTest(bounds=bounds):
                self.assert_refused(bounds)

    def test_valid_bounds_go_to_the_catalog_first(self):
        client = FakeClient(http.SourceError("down"), http.SourceError("down"))
        with self.assertRaisesRegex(ValueError, "No readable NOAA blended SST catalog"):
            fetch(client, {"latitude": (34.5, 35.0), "longitude": (-121, -120.5)})
        self.assertEqual(client.urls, [f"{CATALOG}/2026/catalog.xml", f"{CATALOG}/2025/catalog.xml"])


class CatalogFallbackTests(unittest.TestCase):
    def test_current_year_fetch_failure_falls_back_to_previous_year(self):
        client = FakeClient(http.SourceError("404"), catalog(2025, "20251231000000", "20251230000000"))
        path, url = latest_file(client, NOW)
        self.assertEqual(path, f"{PATH}/2025/{name('20251231000000')}")
        self.assertEqual(url, f"{CATALOG}/2025/catalog.xml")

    def test_current_year_empty_response_falls_back(self):
        client = FakeClient(ValueError("Empty response"), catalog(2025, "20251231000000"))
        self.assertEqual(latest_file(client, NOW)[0], f"{PATH}/2025/{name('20251231000000')}")

    def test_current_year_not_xml_falls_back(self):
        client = FakeClient(b"<not xml", catalog(2025, "20251231000000"))
        self.assertEqual(latest_file(client, NOW)[0], f"{PATH}/2025/{name('20251231000000')}")

    def test_both_years_unreadable_named(self):
        client = FakeClient(b"<not xml", b"<not xml")
        with self.assertRaises(ValueError) as caught:
            latest_file(client, NOW)
        self.assertEqual(str(caught.exception),
                         "No readable NOAA blended SST catalog (2026: ParseError; 2025: ParseError)")

    def test_mixed_failures_named_per_year(self):
        client = FakeClient(http.HTTPStatusError("not found", 404), catalog(2025))
        with self.assertRaisesRegex(ValueError, r"\(2026: HTTPStatusError\)$"):
            latest_file(client, NOW)

    def test_current_year_with_file_does_not_read_previous_year(self):
        client = FakeClient(catalog(2026, "20260101000000"), b"<not xml")
        self.assertEqual(latest_file(client, NOW)[0], f"{PATH}/2026/{name('20260101000000')}")
        self.assertEqual(len(client.urls), 1)

    def test_unexpected_error_still_escapes(self):
        client = FakeClient(RuntimeError("bug"))
        with self.assertRaisesRegex(RuntimeError, "bug"):
            latest_file(client, NOW)

    def test_both_valid_without_file_keeps_message(self):
        client = FakeClient(catalog(2026), catalog(2025, "20270101000000"))
        with self.assertRaisesRegex(ValueError, r"^No dated NOAA blended SST file in official catalog$"):
            latest_file(client, NOW)

    def test_stale_file_keeps_message(self):
        client = FakeClient(catalog(2026), catalog(2025, "20251229020000"))  # 100 h before NOW
        with self.assertRaisesRegex(ValueError, r"^Latest NOAA blended SST file is stale$"):
            latest_file(client, NOW)


if __name__ == "__main__":
    unittest.main()
