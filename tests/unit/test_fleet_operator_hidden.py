"""Operator-site parser: attributes inside suppressed containers never become facts or crawl candidates.

Pure synthetic HTML and an in-memory fake net; no server, socket or real site.
"""
from pathlib import Path
from types import SimpleNamespace
import unittest

from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters.operator_site import OperatorSite, _Page
from skippercast.fleet.config import load_region
from tests._support import FIXTURES

REGION = load_region("CA")
NOW = "2026-10-05T10:00:00Z"
START = "https://operator.example/"
BINDING = SimpleNamespace(id="operator-site", params={}, rights="facts-only")

HIDDEN = (
    '<template><a href="mailto:template@operator.example">m</a><a href="/contact-template">c</a>'
    '<a href="tel:805-555-0111">t</a><a href="https://www.instagram.com/hiddenhandle/">i</a>'
    '<iframe src="https://fareharbor.com/embeds/book/x/"></iframe>'
    '<script src="https://fareharbor.com/embeds/script/x/"></script>'
    '<meta property="og:image" content="https://operator.example/template.png"></template>'
)


def parse(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    page.close()
    return page


class _FakeNet:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def allow_host(self, name):
        pass

    def get(self, url, max_bytes=None):
        self.calls.append(url)
        body = self.pages.get(url, "<html></html>")
        return SimpleNamespace(final_url=url, headers={"Content-Type": "text/html"}, body=body.encode())


def crawl(pages, start=START):
    net = _FakeNet(pages)
    ctx = RunContext(region=REGION, net=net, run_dir=Path("."), clock=lambda: NOW)
    facts = list(OperatorSite().enrich({"vessel_id": "v", "website": start}, BINDING, ctx))
    return [(f.field, f.value) for f in facts], net.calls


class HiddenAttributeTests(unittest.TestCase):
    def test_template_attributes_never_become_business_facts(self):
        page = parse(f"<p>visible@operator.example</p>{HIDDEN}<a href='mailto:after@operator.example'>x</a>")
        self.assertEqual(page.links, [("mailto:after@operator.example", "x")])
        self.assertEqual(page.embeds, [])
        self.assertIsNone(page.og_image)
        facts, _ = crawl({START: f"<html><p>visible@operator.example</p>{HIDDEN}"
                                 "<meta property='og:image' content='/real.png'></html>"})
        self.assertEqual(facts, [("email_business", "visible@operator.example"),
                                 ("photos[]", {"url": "https://operator.example/real.png", "attribution": "operator.example"})])

    def test_hidden_same_site_link_does_not_spend_page_budget(self):
        facts, calls = crawl({START: f'{HIDDEN}<a href="/contact">Contact</a><a href="https://other.example/x">o</a>'})
        self.assertEqual(calls, [START, "https://operator.example/contact"])

    def test_visible_booking_script_is_preserved(self):
        src = '<script src="https://fareharbor.com/embeds/script/x/"></script>'
        self.assertEqual(parse(src).embeds, ["https://fareharbor.com/embeds/script/x/"])
        self.assertEqual(crawl({START: src})[0], [("booking_platform", "fareharbor")])
        for wrapper in ("template", "noscript"):
            self.assertEqual(crawl({START: f"<{wrapper}>{src}</{wrapper}>"})[0], [], wrapper)
        self.assertEqual(parse('<iframe src="https://fareharbor.com/x"></iframe>').embeds, ["https://fareharbor.com/x"])

    def test_nested_suppression_resumes_visible_text(self):
        page = parse("<template><noscript><a href='/n'>n</a>nested</noscript><a href='/t'>t</a><template/>"
                     "<a href='/u'>u</a></template><p>after</p><a href='/v'>v</a>")
        self.assertEqual(page.links, [("/v", "v")])
        self.assertEqual("".join(page.text), "afterv")
        self.assertEqual(parse("<noscript/><a href='/ok'>ok</a>").links, [("/ok", "ok")])

    def test_hidden_anchor_cannot_overwrite_or_finish_visible_anchor(self):
        page = parse("<a href='/visible'>Vis<template><a href='/hidden'>hid</a>den</template>ible</a>")
        self.assertEqual(page.links, [("/visible", "Visible")])

    def test_legacy_fixture_contracts_replayed_in_memory(self):
        site = "https://www.seaexample.example/"
        folder = FIXTURES / "fleet" / "operator-site"
        pages = {site: (folder / "index.html").read_text(), site + "contact.html": (folder / "contact.html").read_text()}
        facts, calls = crawl(pages, site)
        self.assertEqual(calls[:2], [site, site + "contact.html"])
        self.assertLessEqual(len(calls), 6)
        self.assertNotIn("https://fareharbor.com/embeds/book/seaexample/items/?full-items=yes", calls)
        values = {v for f, v in facts if f == "email_business"}
        self.assertEqual(values, {"info@seaexample.example", "seaexample.charters@gmail.com"})
        self.assertIn(("booking_platform", "fareharbor"), facts)


if __name__ == "__main__":
    unittest.main()
