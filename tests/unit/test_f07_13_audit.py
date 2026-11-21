"""F07-13 (SCA-270): a TECK card fact cites the directory listing it was read from.

Contract: facts seen only on a directory card are attributed to the listing page, never to a boat
page that was not read; a successful detail fetch cites each field to the page it came from,
including a landing that was filled from the card. Believable bug: the adapter cites the unread
boat URL for card facts (the pre-fix behaviour), or cites the boat page for a card-filled landing.
Synthetic markup and an in-memory client; no network.
"""
from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

from skippercast import http
from skippercast.fleet.adapters import teck_reports as teck_module
from skippercast.fleet.adapters.teck_reports import TeckReports
from skippercast.fleet.config import Binding

BASE = "https://reports.example.org"
LISTING_1 = BASE + "/charter_boats/index.php"
LISTING_2 = BASE + "/charter_boats/index.php?page=2"
BOAT = BASE + "/charter_boats/synthetic.php"
BOAT_2 = BASE + "/charter_boats/second.php"


def card(slug: str, name: str, landing: str | None = "Card Landing") -> str:
    bottom = f'<div class="boat-card-bottom"><a href="/landings/x.php">{landing}</a></div>' if landing else ""
    return (f'<div class="boat-card"><div class="boat-card-top"><a href="/charter_boats/{slug}.php">{name}</a></div>'
            f"{bottom}</div>")


def listing(cards: str, next_page: str | None = None) -> str:
    pager = (f'<div class="pager-panel">Page 1 of 2 <a class="next" href="{next_page}">Next</a></div>'
             if next_page else "")
    return f"<html><body>{cards}{pager}</body></html>"


def boat_page(landing: str | None) -> str:
    landing_block = (f"<div><h3>Landing Information</h3><table><tr><td>Landing</td><td>{landing}</td></tr>"
                     "<tr><td>City</td><td>Example Bay</td></tr><tr><td>State</td><td>CA</td></tr></table></div>"
                     if landing else "")
    return ("<html><body><div><h3>Boat Information</h3><table><tr><td>Boat</td><td>Synthetic Example</td></tr>"
            "<tr><td>Dimensions</td><td>65 x 18</td></tr><tr><td>Year Built</td><td>2000</td></tr></table></div>"
            f"{landing_block}</body></html>")


class FakeClient:
    """Serves in-memory pages; a ``http.SourceError`` value is raised, standing in for a failed fetch."""

    def __init__(self, pages):
        self.pages = pages

    def get(self, url):
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page


def discover(pages):
    ctx = SimpleNamespace(clock=lambda: "2026-10-05T12:00:00Z", net=SimpleNamespace(skips=[]),
                          region=SimpleNamespace(id="XX", ports=(), landings=()))
    binding = Binding(id="examplefishreports", adapter="teck-reports", enabled=True, rights="facts-only",
                      params={"base": BASE, "directory": "/charter_boats/index.php"})
    with mock.patch.object(teck_module, "teck_client", lambda _ctx: FakeClient(pages)):
        return list(TeckReports().discover(binding, ctx)), ctx


class ListingCitationTests(unittest.TestCase):
    def test_skipped_detail_fetch_cites_only_the_listing_it_was_seen_on(self):
        # negative control: the boat page cannot be read, so it must not be cited at all
        pages = {LISTING_1: listing(card("synthetic", "Synthetic Example (MB)"), next_page=LISTING_2),
                 LISTING_2: listing(card("second", "Second Example")),
                 BOAT: http.SourceError("boat page unavailable"), BOAT_2: http.SourceError("boat page unavailable")}
        candidates, ctx = discover(pages)
        self.assertEqual([(s["reason"], s["url"]) for s in ctx.net.skips],
                         [("fetch-error", BOAT), ("fetch-error", BOAT_2)])
        by_name = {c.name: c for c in candidates}
        self.assertEqual(set(by_name), {"Synthetic Example", "Second Example"})
        for name, listing_url in (("Synthetic Example", LISTING_1), ("Second Example", LISTING_2)):
            facts = by_name[name].facts
            self.assertEqual({f.field for f in facts}, {"name", "catch_reporting.report_name", "landing"})
            self.assertEqual({f.source_url for f in facts}, {listing_url})

    def test_successful_detail_fetch_cites_each_field_to_its_page(self):
        # positive control: the boat page states its own landing
        candidates, _ = discover({LISTING_1: listing(card("synthetic", "Synthetic Example")),
                                  BOAT: boat_page("Page Landing")})
        urls = {f.field: (f.value, f.source_url) for f in candidates[0].facts}
        self.assertEqual(urls["landing"], ("Page Landing", BOAT))
        self.assertEqual({url for _, url in urls.values()}, {BOAT})

    def test_landing_filled_from_the_card_cites_the_listing(self):
        candidates, _ = discover({LISTING_1: listing(card("synthetic", "Synthetic Example")), BOAT: boat_page(None)})
        urls = {f.field: (f.value, f.source_url) for f in candidates[0].facts}
        self.assertEqual(urls["landing"], ("Card Landing", LISTING_1))
        self.assertEqual(urls["name"][1], BOAT)
        self.assertEqual(urls["year_built"], (2000, BOAT))

    def test_card_repeated_on_two_pages_stays_one_candidate_citing_its_first_listing(self):
        same = card("synthetic", "Synthetic Example")
        candidates, _ = discover({LISTING_1: listing(same, next_page=LISTING_2), LISTING_2: listing(same),
                                  BOAT: http.SourceError("unavailable")})
        self.assertEqual(len(candidates), 1)
        self.assertEqual({f.source_url for f in candidates[0].facts}, {LISTING_1})


if __name__ == "__main__":
    unittest.main()
