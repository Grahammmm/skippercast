"""RF2210-9: a malformed URL attribute on an operator page is skipped alone; valid facts survive.

Pure and offline: invented HTML served by an in-memory fake net, no socket or server.
"""
from __future__ import annotations

from types import SimpleNamespace
import unittest
from urllib.parse import urlsplit

from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters.operator_site import OperatorSite, _Found, _Page
from skippercast.fleet.config import load_region

REGION = load_region("CA")
SITE = "https://www.seaexample.example/"
BAD = "https://[broken/"
EMAIL = "visible@seaexample.example"
BOOK = "https://fareharbor.com/synthetic/"


class _FakeNet:
    def __init__(self, pages):
        self.pages, self.calls, self.allowed = pages, [], []

    def allow_host(self, name):
        self.allowed.append(name)

    def get(self, url, max_bytes=None):
        self.calls.append(url)
        return SimpleNamespace(final_url=url, headers={"Content-Type": "text/html"}, body=self.pages[url].encode())


def _page(body, head=""):
    return f"<html><head>{head}</head><body>{body}</body></html>"


def _enrich(pages, max_pages=6):
    net = _FakeNet(pages)
    ctx = RunContext(region=REGION, net=net, run_dir=None, clock=lambda: "2026-10-05T10:00:00Z")
    binding = SimpleNamespace(id="operator-site", rights="public-record", params={"max_pages": max_pages})
    facts = list(OperatorSite().enrich({"vessel_id": "v", "website": SITE}, binding, ctx))
    return [(f.field, f.value) for f in facts], net


def _parse(html):
    page = _Page()
    page.feed(html)
    page.close()
    return page


class MalformedUrlTests(unittest.TestCase):
    def test_bad_values_really_fail_to_parse(self):
        for bad in (BAD, "https://[::1/x", "https://exa\uff03mple.com[/"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                urlsplit(bad)

    def test_bad_anchor_keeps_later_and_earlier_contacts(self):
        for body in (f'<a href="{BAD}">x</a><a href="{BOOK}">Book</a>{EMAIL}',
                     f'{EMAIL}<a href="{BOOK}">Book</a><a href="{BAD}">x</a>'):
            facts, net = _enrich({SITE: _page(body)})
            self.assertEqual(facts, [("booking_platform", "fareharbor"), ("booking_url", BOOK),
                                     ("email_business", EMAIL)])
            self.assertEqual(net.calls, [SITE])

    def test_bad_embed_and_image_are_individual_omissions(self):
        head = f'<meta property="og:image" content="{BAD}">'
        body = f'<iframe src="{BAD}"></iframe><script src="{BOOK}"></script>{EMAIL}'
        facts, _ = _enrich({SITE: _page(body, head)}, max_pages=1)
        self.assertEqual(facts, [("booking_platform", "fareharbor"), ("email_business", EMAIL)])
        facts, _ = _enrich({SITE: _page(f'<iframe src="{BAD}"></iframe>{EMAIL}', head)}, max_pages=1)
        self.assertEqual(facts, [("email_business", EMAIL)])

    def test_valid_image_still_becomes_a_photo(self):
        facts, _ = _enrich({SITE: _page(EMAIL, '<meta property="og:image" content="/a.jpg">')}, max_pages=1)
        self.assertIn(("photos[]", {"url": SITE + "a.jpg", "attribution": "www.seaexample.example"}), facts)

    def test_bad_candidate_is_never_queued_or_fetched(self):
        site = {"www.seaexample.example", "seaexample.example"}
        links = OperatorSite._next_links(
            _parse(f'<a href="{BAD}">bad</a><a href="/contact">Contact</a><a href="https://elsewhere.example/">o</a>'),
            SITE, site)
        self.assertEqual(links, [(SITE + "contact", "Contact")])
        contact = SITE + "contact"
        pages = {SITE: _page(f'<a href="{BAD}">bad</a><a href="/contact">Contact</a><a href="https://elsewhere.example/">o</a>'),
                 contact: _page(EMAIL)}
        facts, net = _enrich(pages, max_pages=2)
        self.assertEqual(net.calls, [SITE, contact])
        self.assertEqual(facts, [("email_business", EMAIL)])

    def test_direct_external_bad_url_is_harmless(self):
        found = _Found()
        OperatorSite._external(BAD, SITE, found)
        self.assertEqual(found.best, {})
        OperatorSite._external(BOOK, SITE, found)
        self.assertIn(("booking_url", repr(BOOK)), found.best)


if __name__ == "__main__":
    unittest.main()
