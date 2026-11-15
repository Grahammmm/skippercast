"""Directory entries the GGFA/SAC selectors recognise must not vanish when their name is blank.

Offline: invented markup and an in-memory ``get`` stand-in; no sockets, no service requests.
"""
from __future__ import annotations

from types import SimpleNamespace
import unittest

from skippercast.fleet.adapters import RunContext
from skippercast.fleet.adapters.directories import Directories, LayoutError, parse_ggfa, parse_sac
from skippercast.fleet.config import Binding

URL = "https://association.example.org/list"
CLOCK = "2026-10-05T12:00:00Z"
GGFA_HEAD = "<h3>Example Bay</h3>"
GGFA_GOOD = "<b><i>Example Vessel</i></b><br><b>Fictional Skipper</b><br>(805) 555-0100<br>"
SAC_GOOD = '<a class="wixui-button" href="https://landing.example.org/"><span class="wixui-button__label">Example Landing - Example Bay</span></a>'


def sac_link(label_html: str | None, aria: str | None = None) -> str:
    aria_attr = "" if aria is None else f' aria-label="{aria}"'
    inner = "" if label_html is None else f'<span class="wixui-button__label">{label_html}</span>'
    return f'<a class="wixui-button" href="https://other.example.org/"{aria_attr}>{inner}</a>'


def binding(kind: str) -> Binding:
    return Binding(id=f"{kind}-list", adapter="directories", enabled=True, rights="facts-only",
                   params={"list": kind, "url": URL})


class _Net:
    def __init__(self, body: str):
        self.body, self.urls, self.skips = body, [], []

    def get(self, url):
        self.urls.append(url)
        return SimpleNamespace(body=self.body.encode("utf-8"))


def context(body: str) -> RunContext:
    region = SimpleNamespace(id="XX", ports=(SimpleNamespace(id="example-bay", name="Example Bay"),), landings=())
    return RunContext(region=region, net=_Net(body), run_dir=None, clock=lambda: CLOCK)


class GgfaBlankTests(unittest.TestCase):
    def test_ggfa_blank_member_refuses_with_healthy_sibling(self):
        for blank in ("", " \n ", "&nbsp;", "&#160; &nbsp;"):
            bad = f"<b><i>{blank}</i></b><br>"
            for order in (GGFA_HEAD + GGFA_GOOD + bad, GGFA_HEAD + bad + GGFA_GOOD):
                with self.subTest(blank=blank), self.assertRaises(LayoutError) as caught:
                    parse_ggfa(order, URL)
                self.assertEqual(caught.exception.url, URL)
                self.assertEqual(caught.exception.detail, "vessel entry has no name")

    def test_blank_only_and_no_structure_still_refuse(self):
        with self.assertRaises(LayoutError) as caught:
            parse_ggfa(GGFA_HEAD + "<b><i> </i></b>", URL)
        self.assertEqual(caught.exception.detail, "vessel entry has no name")
        with self.assertRaises(LayoutError) as caught:
            parse_ggfa(GGFA_HEAD + "<b>Fictional Skipper</b>", URL)
        self.assertEqual(caught.exception.detail, "no vessel entries under port headings")
        with self.assertRaises(LayoutError) as caught:
            parse_ggfa("<b><i>Example Vessel</i></b>", URL)
        self.assertEqual(caught.exception.detail, "vessel entry before any port heading")

    def test_healthy_order_dedupe_and_privacy_unchanged(self):
        markup = (GGFA_HEAD + GGFA_GOOD + "<b><i>Second Vessel</i></b><br>" + "<b><i>Example Vessel</i></b>"
                  + "<h3>Other Port</h3><b><i>Third Vessel</i></b>")
        seeds = parse_ggfa(markup, URL)
        self.assertEqual([(s.name, s.port) for s in seeds],
                         [("Example Vessel", "Example Bay"), ("Second Vessel", "Example Bay"),
                          ("Third Vessel", "Other Port")])
        self.assertNotIn("Fictional", repr(seeds))
        self.assertNotIn("555", repr(seeds))


class SacBlankTests(unittest.TestCase):
    def test_sac_blank_member_refuses_with_healthy_sibling(self):
        bads = {
            "absent label node": sac_link(None),
            "empty label node": sac_link(""),
            "whitespace label": sac_link("  \n "),
            "blank aria": sac_link(" ", aria="   "),
        }
        for name, bad in bads.items():
            nav = '<a href="/home">Unrelated navigation</a>'
            for order in (SAC_GOOD + nav + bad, bad + nav + SAC_GOOD):
                with self.subTest(case=name), self.assertRaises(LayoutError) as caught:
                    parse_sac(order, URL)
                self.assertEqual(caught.exception.url, URL)
                self.assertEqual(caught.exception.detail, "member landing link has no label")

    def test_aria_fallback_remains_compatible(self):
        seeds = parse_sac(sac_link(None, aria="Aria Landing - Aria Bay") + sac_link(" ", aria="Plain Landing")
                          + sac_link("Visible Landing", aria="Different Aria"), URL)
        self.assertEqual([(s.name, s.place) for s in seeds],
                         [("Aria Landing", "Aria Bay"), ("Plain Landing", None), ("Visible Landing", None)])
        self.assertEqual({s.url for s in seeds}, {"https://other.example.org/"})

    def test_blank_only_and_no_structure_still_refuse(self):
        with self.assertRaises(LayoutError) as caught:
            parse_sac(sac_link(" "), URL)
        self.assertEqual(caught.exception.detail, "member landing link has no label")
        # links the selector does not recognise are not entries
        ignored = ('<a class="nav" href="/x">Home</a><a class="wixui-button">No href</a>'
                   '<a class="wixui-button" href="">Empty href</a>')
        with self.assertRaises(LayoutError) as caught:
            parse_sac(ignored, URL)
        self.assertEqual(caught.exception.detail, "no member landing links")

    def test_healthy_order_dedupe_unchanged(self):
        seeds = parse_sac(SAC_GOOD + sac_link("Two - Town - Annex") + SAC_GOOD + '<a href="/nav">Nav</a>', URL)
        self.assertEqual([(s.name, s.place, s.url) for s in seeds],
                         [("Example Landing", "Example Bay", "https://landing.example.org/"),
                          ("Two", "Town - Annex", "https://other.example.org/")])


class AdapterPropagationTests(unittest.TestCase):
    def test_adapter_entrypoints_propagate_layout_failure(self):
        ggfa = context(GGFA_HEAD + GGFA_GOOD + "<b><i> </i></b>")
        with self.assertRaises(LayoutError) as caught:
            Directories().discover(binding("ggfa"), ggfa)
        self.assertEqual(caught.exception.detail, "vessel entry has no name")
        self.assertEqual(ggfa.net.urls, [URL])
        self.assertEqual(ggfa.net.skips, [])

        sac = context(SAC_GOOD + sac_link(" "))
        with self.assertRaises(LayoutError) as caught:
            Directories().landing_seeds(binding("sac"), sac)
        self.assertEqual(caught.exception.detail, "member landing link has no label")
        self.assertEqual(sac.net.urls, [URL])
        self.assertEqual(sac.net.skips, [])

    def test_adapter_healthy_and_unsupported_unchanged(self):
        ok = context(GGFA_HEAD + GGFA_GOOD)
        self.assertEqual([c.name for c in Directories().discover(binding("ggfa"), ok)], ["Example Vessel"])
        sac = context(SAC_GOOD)
        self.assertEqual([s.name for s in Directories().landing_seeds(binding("sac"), sac)], ["Example Landing"])
        self.assertEqual(list(Directories().discover(binding("sac"), sac)), [])  # landing lists yield no vessels
        other = context("<b><i> </i></b>")
        self.assertEqual(list(Directories().discover(binding("harbor"), other)), [])
        self.assertEqual(other.net.urls, [])
        self.assertEqual(other.net.skips[0]["reason"], "unsupported-list")


if __name__ == "__main__":
    unittest.main()
