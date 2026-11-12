"""RF2150-7: a TECK directory pager that loops back must fail, not end early.

Pages are invented inline HTML served by an in-memory fake client that records
every requested URL; the real parser, pager traversal and discover run on them.
No server, cache, credentials or network.
"""
from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest import mock

from skippercast.fleet.adapters import teck_reports as teck_module
from skippercast.fleet.adapters.teck_reports import LayoutError, TeckReports
from skippercast.fleet.config import Binding

BASE = "https://reports.example.org"
FIRST = BASE + "/charter_boats/index.php"
REPEAT = "directory pager repeats a previously visited page"


def page_url(n: int) -> str:
    return FIRST if n == 1 else f"{FIRST}?page={n}"


def directory_page(names, pager: str | None = None) -> str:
    cards = "".join(
        f'<div class="boat-card"><div class="boat-card-top"><a href="/charter_boats/{n.lower().replace(" ", "_")}.php">'
        f'{n}</a></div></div>' for n in names)
    return f"<html><body>{cards}{pager or ''}</body></html>"


def pager(page: int, pages: int, href: str | None = None) -> str:
    link = f'<a class="next" href="{href}">Next</a>' if href is not None else ""
    return f'<div class="pager-panel"><span>Page {page} of {pages}</span>{link}</div>'


BOAT = ("<html><body><div><h3>Boat Information</h3><table><tr><td>Boat</td><td>{name}</td></tr>"
        "</table></div></body></html>")


class FakeClient:
    def __init__(self, pages: dict[str, str]):
        self.pages, self.requested = pages, []

    def get(self, url: str) -> str:
        self.requested.append(url)
        return self.pages[url]


def binding() -> Binding:
    return Binding(id="examplefishreports", adapter="teck-reports", enabled=True, rights="facts-only",
                   params={"base": BASE, "directory": "/charter_boats/index.php"})


def context() -> SimpleNamespace:
    region = SimpleNamespace(id="XX", ports=(), landings=())
    return SimpleNamespace(clock=lambda: "2026-10-05T12:00:00Z", region=region, net=SimpleNamespace(skips=[]))


class PagerCycleTests(unittest.TestCase):
    def walk(self, pages):
        client = FakeClient(pages)
        names = []
        try:
            for entry in TeckReports().directory(binding(), context(), client):
                names.append(entry.name)
        except LayoutError as error:
            return names, client.requested, error
        return names, client.requested, None

    def assert_repeat(self, error, url):
        self.assertIsInstance(error, LayoutError)
        self.assertEqual((error.url, error.detail), (url, REPEAT))

    def test_self_cycle_is_layout_failure(self):
        names, requested, error = self.walk({FIRST: directory_page(["Alpha"], pager(1, 3, FIRST))})
        self.assert_repeat(error, FIRST)
        self.assertEqual(requested, [FIRST])
        self.assertEqual(names, ["Alpha"])

    def test_multi_page_cycle_is_layout_failure(self):
        names, requested, error = self.walk({
            FIRST: directory_page(["Alpha"], pager(1, 3, page_url(2))),
            page_url(2): directory_page(["Bravo"], pager(2, 3, FIRST))})
        self.assert_repeat(error, FIRST)
        self.assertEqual(requested, [FIRST, page_url(2)])
        self.assertEqual(names, ["Alpha", "Bravo"])

    def test_cycle_to_earlier_noninitial_page(self):
        names, requested, error = self.walk({
            FIRST: directory_page(["Alpha"], pager(1, 4, page_url(2))),
            page_url(2): directory_page(["Bravo"], pager(2, 4, page_url(3))),
            page_url(3): directory_page(["Charlie"], pager(3, 4, page_url(2)))})
        self.assert_repeat(error, page_url(2))
        self.assertEqual(requested, [FIRST, page_url(2), page_url(3)])
        self.assertEqual(names, ["Alpha", "Bravo", "Charlie"])

    def test_relative_next_resolves_before_cycle_check(self):
        names, requested, error = self.walk({
            FIRST: directory_page(["Alpha"], pager(1, 3, "?page=2")),
            page_url(2): directory_page(["Bravo"], pager(2, 3, "index.php"))})
        self.assert_repeat(error, FIRST)
        self.assertEqual(requested, [FIRST, page_url(2)])

    def test_discover_does_not_return_partial_candidates(self):
        client = FakeClient({FIRST: directory_page(["Alpha"], pager(1, 3, FIRST)),
                             BASE + "/charter_boats/alpha.php": BOAT.format(name="Alpha")})
        with mock.patch.object(teck_module, "teck_client", return_value=client):
            with self.assertRaises(LayoutError) as caught:
                TeckReports().discover(binding(), context())
        self.assertEqual(caught.exception.detail, REPEAT)
        self.assertEqual(client.requested, [FIRST])

    def test_terminal_and_no_pager_controls(self):
        names, requested, error = self.walk({
            FIRST: directory_page(["Alpha"], pager(1, 2, page_url(2))),
            page_url(2): directory_page(["Bravo", "Charlie"], pager(2, 2))})
        self.assertIsNone(error)
        self.assertEqual((names, requested), (["Alpha", "Bravo", "Charlie"], [FIRST, page_url(2)]))
        names, requested, error = self.walk({FIRST: directory_page(["Alpha", "Bravo"])})
        self.assertIsNone(error)
        self.assertEqual((names, requested), (["Alpha", "Bravo"], [FIRST]))
        boats = {BASE + f"/charter_boats/{n}.php": BOAT.format(name=n.title()) for n in ("alpha", "bravo")}
        client = FakeClient({FIRST: directory_page(["Alpha"], pager(1, 2, page_url(2))),
                             page_url(2): directory_page(["Bravo"], pager(2, 2)), **boats})
        ctx = context()
        with mock.patch.object(teck_module, "teck_client", return_value=client):
            candidates = TeckReports().discover(binding(), ctx)
        self.assertEqual([c.name for c in candidates], ["Alpha", "Bravo"])
        self.assertEqual(ctx.net.skips, [])

    def test_unique_page_budget_preserved(self):
        chain = {page_url(n): directory_page([f"Boat {n}"], pager(n, 4, page_url(n + 1))) for n in (1, 2, 3)}
        with mock.patch.object(teck_module, "MAX_PAGES", 3):
            names, requested, error = self.walk(chain)
            self.assertEqual((error.url, error.detail), (page_url(4), "directory pager runs past 3 pages"))
            self.assertEqual(requested, [page_url(1), page_url(2), page_url(3)])
            exact = {**chain, page_url(3): directory_page(["Boat 3"], pager(3, 3))}
            names, requested, error = self.walk(exact)
            self.assertIsNone(error)
            self.assertEqual(names, ["Boat 1", "Boat 2", "Boat 3"])
            looped = {**chain, page_url(3): directory_page(["Boat 3"], pager(3, 4, page_url(1)))}
            names, requested, error = self.walk(looped)
            self.assert_repeat(error, page_url(1))
            self.assertEqual(requested, [page_url(1), page_url(2), page_url(3)])

    def test_existing_layout_refusals_unchanged(self):
        cases = (("<html><body></body></html>", "no boat cards on the directory page"),
                 (directory_page(["Alpha"], '<div class="pager-panel">Next</div>'), "pager without 'Page N of M'"),
                 (directory_page(["Alpha"], pager(1, 2)), "page 1 of 2 has no next link"))
        for markup, detail in cases:
            with self.subTest(detail=detail):
                names, requested, error = self.walk({FIRST: markup})
                self.assertEqual((error.url, error.detail), (FIRST, detail))
                self.assertEqual(requested, [FIRST])


if __name__ == "__main__":
    unittest.main()
