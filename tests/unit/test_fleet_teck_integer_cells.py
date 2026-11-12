"""RF1741-10: an oversized optional integer cell is unavailable, not a failed page.

Invented inline markup; the real boat parser, candidate conversion and discover
run, with only ``teck_client`` replaced by an in-memory fake. No network.
"""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest import mock

from skippercast.fleet.adapters import teck_reports as teck_module
from skippercast.fleet.adapters.teck_reports import DirectoryEntry, LayoutError, TeckReports, parse_boat_page
from skippercast.fleet.config import Binding

BASE = "https://reports.example.org"
DIRECTORY = BASE + "/charter_boats/index.php"
BOAT_URL = BASE + "/charter_boats/synthetic.php"
HUGE = "9" * 5000


def boat_html(year="2000", load="20", bunks="10", boat="Synthetic Example") -> str:
    rows = [("Boat", boat), ("Owner(s)", "Owner Placeholder"), ("Dimensions", "65 x 18"),
            ("Year Built", year), ("Max Load", load), ("Bunks", bunks)]
    boat_table = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows if v is not None)
    return ("<html><body><div><h3>Boat Information</h3><table>" + boat_table + "</table></div>"
            "<div><h3>Landing Information</h3><table><tr><td>Landing</td><td>Sample Landing</td></tr>"
            "<tr><td>City</td><td>Example Bay</td></tr><tr><td>State</td><td>CA</td></tr></table></div>"
            "</body></html>")


def parse(**cells):
    return parse_boat_page(boat_html(**cells), BOAT_URL)


class FakeClient:
    def __init__(self, pages):
        self.pages, self.requested = pages, []

    def get(self, url):
        self.requested.append(url)
        return self.pages[url]


class OptionalIntegerTests(unittest.TestCase):
    def test_oversized_year_keeps_other_boat_fields(self):
        control, page = parse(), parse(year=HUGE)
        self.assertIsNone(page.year_built)
        self.assertEqual(page, replace(control, year_built=None))
        self.assertEqual((page.length_ft, page.beam_ft, page.passengers_max, page.bunks, page.name),
                         (65.0, 18.0, 20, 10, "Synthetic Example"))

    def test_oversized_load_is_local(self):
        control, page = parse(), parse(load=HUGE)
        self.assertIsNone(page.passengers_max)
        self.assertEqual(page, replace(control, passengers_max=None))

    def test_oversized_bunks_is_local(self):
        control, page = parse(), parse(bunks=HUGE)
        self.assertIsNone(page.bunks)
        self.assertEqual(page, replace(control, bunks=None))
        self.assertEqual((page.year_built, page.passengers_max), (2000, 20))

    def test_all_optional_integers_unavailable_still_parse(self):
        control = parse()
        for cells in ({"year": HUGE, "load": HUGE, "bunks": HUGE}, {"year": None, "load": "n/a", "bunks": "none"}):
            page = parse(**cells)
            self.assertEqual(page, replace(control, year_built=None, passengers_max=None, bunks=None))
            self.assertEqual((page.landing, page.length_ft, page.name), ("Sample Landing", 65.0, "Synthetic Example"))

    def test_ordinary_bounds_and_tokens_unchanged(self):
        self.assertEqual((parse(year="1900").year_built, parse(year="2100").year_built), (1900, 2100))
        self.assertEqual([parse(load=v).passengers_max for v in ("1", "400")], [1, 400])
        self.assertEqual([parse(bunks=v).bunks for v in ("1", "400")], [1, 400])
        self.assertEqual([parse(year=v).year_built for v in ("1899", "2101")], [None, None])
        self.assertEqual([parse(load=v).passengers_max for v in ("0", "401")], [None, None])
        self.assertEqual([parse(bunks=v).bunks for v in ("0", "401")], [None, None])
        self.assertEqual(parse(load="Up to 24 anglers").passengers_max, 24)
        self.assertEqual(parse(bunks="0012").bunks, 12)

    def test_layout_errors_remain(self):
        with self.assertRaises(LayoutError):
            parse_boat_page("<html><body><p>nothing</p></body></html>", BOAT_URL)
        with self.assertRaises(LayoutError):
            parse(boat="")


class DiscoverTests(unittest.TestCase):
    def test_discover_does_not_mislabel_numeric_gap_as_fetch_failure(self):
        directory = ('<html><body><div class="boat-card"><div class="boat-card-top">'
                     '<a href="/charter_boats/synthetic.php">Synthetic Example</a></div></div></body></html>')
        client = FakeClient({DIRECTORY: directory, BOAT_URL: boat_html(bunks=HUGE)})
        ctx = SimpleNamespace(clock=lambda: "2026-10-05T12:00:00Z", net=SimpleNamespace(skips=[]),
                              region=SimpleNamespace(id="XX", ports=(), landings=()))
        binding = Binding(id="examplefishreports", adapter="teck-reports", enabled=True, rights="facts-only",
                          params={"base": BASE, "directory": "/charter_boats/index.php"})
        with mock.patch.object(teck_module, "teck_client", lambda _ctx: client):
            candidates = list(TeckReports().discover(binding, ctx))
        self.assertEqual(len(candidates), 1)
        facts = {f.field: f for f in candidates[0].facts}
        self.assertEqual((facts["length_ft"].value, facts["year_built"].value, facts["passengers_max"].value),
                         (65.0, 2000, 20))
        self.assertNotIn("bunks", facts)
        for fact in facts.values():
            self.assertEqual((fact.source_id, fact.rights), ("examplefishreports", "facts-only"))
        self.assertEqual(ctx.net.skips, [])
        self.assertEqual(client.requested, [DIRECTORY, BOAT_URL])


if __name__ == "__main__":
    unittest.main()
