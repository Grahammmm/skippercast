"""NOAA SST catalog: impossible filename dates are skipped without losing valid siblings."""

from datetime import datetime, timezone
import itertools
import unittest

from skippercast import http
from skippercast.pipeline.noaa_sst import CATALOG, PATH, latest_file
from tests.gis.test_noaa_sst_fetch import FakeClient, catalog, name

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
EARLY = datetime(2026, 1, 2, 6, tzinfo=timezone.utc)


def path(year, stamp):
    return f"{PATH}/{year}/{name(stamp)}"


def url(year):
    return f"{CATALOG}/{year}/catalog.xml"


class CatalogDateTests(unittest.TestCase):
    def test_invalid_calendar_entry_preserves_valid_siblings(self):
        stamps = ("20261007000000", "20261006000000", "20260230000000")
        for order in itertools.permutations(stamps):
            with self.subTest(order=order):
                client = FakeClient(catalog(2026, *order))
                self.assertEqual(latest_file(client, NOW), (path(2026, "20261007000000"), url(2026)))
                self.assertEqual(client.urls, [url(2026)])

    def test_invalid_month_day_and_clock_fields_are_skipped(self):
        for bad in ("20261301000000", "20260229000000", "20260900000000",
                    "20261007240000", "20261007126000", "20261007120060"):
            with self.subTest(bad=bad):
                client = FakeClient(catalog(2026, bad, "20261007000000"))
                self.assertEqual(latest_file(client, NOW)[0], path(2026, "20261007000000"))
                self.assertEqual(client.urls, [url(2026)])

    def test_real_leap_day_is_accepted(self):
        leap_now = datetime(2028, 2, 29, 12, tzinfo=timezone.utc)
        client = FakeClient(catalog(2028, "20280229000000", "20270229000000"))
        self.assertEqual(latest_file(client, leap_now), (path(2028, "20280229000000"), url(2028)))

    def test_all_invalid_current_year_uses_previous_year(self):
        client = FakeClient(catalog(2026, "20260230000000", "20261301000000"), catalog(2025, "20251231000000"))
        self.assertEqual(latest_file(client, EARLY), (path(2025, "20251231000000"), url(2025)))
        self.assertEqual(client.urls, [url(2026), url(2025)])

    def test_all_invalid_readable_catalogs_keep_no_dated_message(self):
        client = FakeClient(catalog(2026, "20260230000000"), catalog(2025, "20250431000000"))
        with self.assertRaisesRegex(ValueError, r"^No dated NOAA blended SST file in official catalog$"):
            latest_file(client, EARLY)
        self.assertEqual(client.urls, [url(2026), url(2025)])

    def test_invalid_entries_preserve_future_and_stale_rules(self):
        client = FakeClient(catalog(2026, "20260230000000", "20261008000000", "20261007000000"))
        self.assertEqual(latest_file(client, NOW)[0], path(2026, "20261007000000"))
        stale = FakeClient(catalog(2026, "20260230000000", "20261003000000"))  # 108 h old
        with self.assertRaisesRegex(ValueError, r"^Latest NOAA blended SST file is stale$"):
            latest_file(stale, NOW)
        self.assertEqual(stale.urls, [url(2026)])

    def test_invalid_entries_keep_year_error_notes(self):
        client = FakeClient(http.HTTPStatusError("not found", 404), catalog(2025, "20250230000000"))
        with self.assertRaisesRegex(ValueError, r"\(2026: HTTPStatusError\)$"):
            latest_file(client, NOW)

    def test_unrelated_client_error_is_not_swallowed(self):
        client = FakeClient(RuntimeError("bug"))
        with self.assertRaisesRegex(RuntimeError, "bug"):
            latest_file(client, NOW)


if __name__ == "__main__":
    unittest.main()
