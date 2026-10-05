"""CF-13: the teck-reports and directories adapters.

Parsers run on synthetic HTML fixtures modelled on the TECK.net report sites,
the GGFA charter-boat page and the SAC member page (invented names, fictional
555-01XX phones) and must match the expected JSON beside them. Discovery runs
offline: a local plain-HTTP server stands in for every host behind a real
``FleetSession``, so the robots, allowlist and cache paths are the production
ones. TECK.net pages must go through ``pipeline.collect``'s Client and cache.
"""
from __future__ import annotations

from dataclasses import asdict
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import re
import socket
import tempfile
import threading
from types import SimpleNamespace
import unittest

from skippercast import http
from skippercast.fleet.adapters import RunContext, get
from skippercast.fleet.adapters import directories as directories_module
from skippercast.fleet.adapters import teck_reports as teck_module
from skippercast.fleet.adapters.directories import Directories, parse_ggfa, parse_sac
from skippercast.fleet.adapters.teck_reports import (LayoutError, TeckReports, parse_boat_page, parse_directory,
                                                     teck_client)
from skippercast.fleet.config import Binding
from skippercast.fleet.net import FleetSession
from skippercast.pipeline import collect
from tests._support import FIXTURES as _FIXTURES

FIXTURES = _FIXTURES / "fleet"
TECK, DIRS = FIXTURES / "teck", FIXTURES / "directories"
BASE = "https://reports.example.org"
DIRECTORY = BASE + "/charter_boats/index.php"
CLOCK = "2026-10-05T12:00:00Z"
PHONE = re.compile(r"\(?\d{3}\)?[ .-]*\d{3}[ .-]?\d{4}")


def html(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def plain(obj):
    """A dataclass as the JSON it would be written as (tuples become lists)."""
    return json.loads(json.dumps(obj.as_dict() if hasattr(obj, "as_dict") else asdict(obj)))


def expected(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def region():
    """A stand-in region with invented ports and landings (the adapters read only these)."""
    return SimpleNamespace(
        id="XX",
        ports=(SimpleNamespace(id="example-bay", name="Example Bay"),
               SimpleNamespace(id="sample-harbor", name="Harbor Point · Sample Harbor")),
        landings=(SimpleNamespace(id="sample-landing", name="Sample Landing", port="example-bay"),
                  SimpleNamespace(id="fixture-sportfishing", name="Fixture Sportfishing", port="sample-harbor")))


def teck_binding(**params) -> Binding:
    return Binding(id="examplefishreports", adapter="teck-reports", enabled=True, rights="facts-only",
                   params={"base": BASE, "directory": "/charter_boats/index.php", **params})


def dir_binding(kind: str, url: str = "https://association.example.org/fisherman.php") -> Binding:
    return Binding(id=f"{kind}-list", adapter="directories", enabled=True, rights="facts-only",
                   params={"list": kind, "url": url})


def facts_of(candidates):
    return [fact for candidate in candidates for fact in candidate.facts]


class TeckParserTests(unittest.TestCase):
    def test_directory_pages_match_expected(self):
        for name, url in (("directory-1", DIRECTORY), ("directory-2", DIRECTORY + "?page=2")):
            with self.subTest(name):
                page = parse_directory(html(TECK / f"{name}.html"), url)
                self.assertEqual(plain(page), expected(TECK / f"{name}.expected.json"))

    def test_boat_pages_match_expected(self):
        for name in ("boat-table", "boat-dl", "boat-minimal"):
            with self.subTest(name):
                page = parse_boat_page(html(TECK / f"{name}.html"), f"{BASE}/charter_boats/{name}.php")
                self.assertEqual(plain(page), expected(TECK / f"{name}.expected.json"))

    def test_changed_layouts_raise_a_typed_error(self):
        with self.assertRaises(LayoutError) as caught:
            parse_boat_page(html(TECK / "boat-changed.html"), BASE + "/charter_boats/bluefixture.php")
        self.assertIn("Boat Information", caught.exception.detail)
        with self.assertRaises(LayoutError):
            parse_directory(html(TECK / "directory-changed.html"), DIRECTORY)
        self.assertTrue(issubclass(LayoutError, ValueError))

    def test_pager_and_block_anomalies_raise(self):
        card = ("<div class='boat-card'><div class='boat-card-top'><a href='/charter_boats/a.php'>A</a></div></div>")
        with self.assertRaises(LayoutError):  # pager text changed
            parse_directory(card + "<div class='pager-panel'>Seite 1 von 2</div>", DIRECTORY)
        with self.assertRaises(LayoutError):  # says there are more pages but has no next link
            parse_directory(card + "<div class='pager-panel'>Page 1 of 3</div>", DIRECTORY)
        with self.assertRaises(LayoutError):  # a card without a linked name
            parse_directory("<div class='boat-card'><div class='boat-card-top'>A</div></div>", DIRECTORY)
        with self.assertRaises(LayoutError):  # block present but its Boat row is gone
            parse_boat_page("<div><h3>Boat Information</h3><table><tr><td>Vessel</td><td>A</td></tr></table></div>",
                            BASE + "/charter_boats/a.php")

    def test_parsers_never_read_owner_skipper_or_phone_rows(self):
        for name in ("boat-table", "boat-dl", "boat-minimal"):
            page = asdict(parse_boat_page(html(TECK / f"{name}.html"), f"{BASE}/charter_boats/{name}.php"))
            text = json.dumps(page)
            self.assertNotIn("Placeholder", text)
            self.assertIsNone(PHONE.search(text.replace(page["url"], "")), name)
            self.assertFalse({k for k in page if re.search("phone|owner|skipper|captain", k)})


class DirectoryParserTests(unittest.TestCase):
    def test_ggfa_and_sac_match_expected(self):
        self.assertEqual([plain(x) for x in parse_ggfa(html(DIRS / "ggfa.html"), "https://association.example.org/")],
                         expected(DIRS / "ggfa.expected.json"))
        self.assertEqual([plain(x) for x in parse_sac(html(DIRS / "sac.html"), "https://association.example.org/")],
                         expected(DIRS / "sac.expected.json"))

    def test_changed_layouts_raise_a_typed_error(self):
        with self.assertRaises(LayoutError):
            parse_ggfa(html(DIRS / "ggfa-changed.html"), "https://association.example.org/")
        with self.assertRaises(LayoutError):
            parse_sac(html(DIRS / "sac-changed.html"), "https://association.example.org/")
        with self.assertRaises(LayoutError):  # a vessel before any port heading
            parse_ggfa("<b><i>Sea Example</i></b>", "https://association.example.org/")

    def test_ggfa_output_has_no_names_or_phones(self):
        text = json.dumps([asdict(x) for x in parse_ggfa(html(DIRS / "ggfa.html"), "https://association.example.org/")])
        self.assertNotIn("Placeholder", text)
        self.assertIsNone(PHONE.search(text))


class _Handler(BaseHTTPRequestHandler):
    """Serves fixture pages by path with an ETag, and 304 to a matching If-None-Match.

    Every host connects here (the paths of the stand-in hosts do not overlap)."""

    def do_GET(self):
        self.server.requests.append((self.path, self.headers.get("If-None-Match")))
        route = self.server.routes.get(self.path)
        if self.path == "/robots.txt":
            route = b"User-agent: *\nDisallow:\n"
        if route is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = route if isinstance(route, bytes) else route.read_bytes()
        tag = '"' + hashlib.sha256(body).hexdigest()[:16] + '"'
        if self.headers.get("If-None-Match") == tag:
            self.send_response(304)
            self.send_header("ETag", tag)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("ETag", tag)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class DiscoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.server.requests = []
        cls.server.routes = {
            "/charter_boats/index.php": TECK / "directory-1.html",            # reports.example.org
            "/charter_boats/index.php?page=2": TECK / "directory-2.html",
            "/charter_boats/seaexample.php": TECK / "boat-table.html",
            "/charter_boats/harbortest-eb.php": TECK / "boat-dl.html",
            "/charter_boats/kelprunner.php": TECK / "boat-minimal.html",
            "/charter_boats/bluefixture.php": TECK / "boat-changed.html",
            "/fisherman.php": DIRS / "ggfa.html",                             # association.example.org
            "/members": DIRS / "sac.html",
        }
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.server.requests.clear()
        self.connected = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.collector_cache = root / "var" / "http-cache"        # what SKIPPERCAST_HTTP_CACHE=1 gives collect
        self.run_cache = root / "fleet" / "XX" / "http-cache"     # the fleet run's own cache (Run.http_cache)
        previous = http._default
        http.set_default_session(http.Session(cache=self.collector_cache))
        self.addCleanup(http.set_default_session, previous)

    def context(self) -> RunContext:
        port = self.server.server_address[1]

        def factory(host, _port, addresses, context=None, timeout=None):
            self.connected.append(host)
            return HTTPConnection("127.0.0.1", port, timeout=timeout)

        def resolver(host, port, type=None):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        net = FleetSession({"reports.example.org", "association.example.org"}, ("fareharbor.com",),
                           interval=0, sleep=lambda s: None, connection_factory=factory, resolver=resolver,
                           attempts=1, cache=self.run_cache)
        return RunContext(region=region(), net=net, run_dir=Path(self.tmp.name), clock=lambda: CLOCK)

    def test_teck_discover_matches_expected(self):
        ctx = self.context()
        candidates = TeckReports().discover(teck_binding(), ctx)
        self.assertEqual([plain(c) for c in candidates], expected(TECK / "discover.expected.json"))
        # the changed page is a recorded skip, not a silent gap; the off-site card is not fetched
        self.assertEqual([(s["reason"], s["url"]) for s in ctx.net.skips],
                         [("layout", BASE + "/charter_boats/bluefixture.php")])
        self.assertNotIn("www.example.net", self.connected)
        self.assertEqual(set(self.connected), {"reports.example.org"})

    def test_no_phone_or_personal_name_is_emitted(self):
        ctx = self.context()
        candidates = [*TeckReports().discover(teck_binding(), ctx),
                      *Directories().discover(dir_binding("ggfa"), ctx)]
        self.assertTrue(candidates)
        for fact in facts_of(candidates):
            self.assertNotRegex(fact.field, "phone|owner|skipper|captain|email")
            self.assertEqual(fact.rights, "facts-only")
            self.assertEqual(fact.method, "page")
            self.assertTrue(fact.source_url.startswith("https://"))
            if isinstance(fact.value, str):
                self.assertIsNone(PHONE.search(fact.value), fact)
                self.assertNotIn("Placeholder", fact.value)
        text = json.dumps([asdict(c) for c in candidates])
        self.assertNotIn("555-01", text)
        self.assertNotIn("Placeholder", text)

    def test_mostly_changed_boat_pages_fail_the_binding(self):
        routes = dict(self.server.routes)
        self.addCleanup(setattr, self.server, "routes", routes)
        self.server.routes = {**routes, **{path: TECK / "boat-changed.html" for path in routes
                                           if path.startswith("/charter_boats/") and "index" not in path}}
        with self.assertRaises(LayoutError):
            TeckReports().discover(teck_binding(), self.context())

    def test_changed_directory_raises(self):
        routes = dict(self.server.routes)
        self.addCleanup(setattr, self.server, "routes", routes)
        self.server.routes = {**routes, "/charter_boats/index.php": TECK / "directory-changed.html"}
        with self.assertRaises(LayoutError):
            TeckReports().discover(teck_binding(), self.context())

    def test_teck_pages_use_the_collector_cache_not_a_second_one(self):
        ctx = self.context()
        client = teck_client(ctx)
        self.assertIsInstance(client, collect.Client)
        self.assertIs(client.session, ctx.net)                 # fleet rules still apply
        self.assertIs(client.cache, collect.http_cache())      # the collector's cache object
        self.assertEqual(collect.http_cache().directory, self.collector_cache)
        TeckReports().discover(teck_binding(), ctx)
        cached = {json.loads(p.read_text())["url"] for p in self.collector_cache.glob("*.json")}
        self.assertIn(DIRECTORY, cached)
        self.assertIn(BASE + "/charter_boats/seaexample.php", cached)
        in_run_cache = {json.loads(p.read_text())["url"] for p in self.run_cache.glob("*.json")}
        self.assertFalse({u for u in in_run_cache if "/charter_boats/" in u}, "TECK pages leaked into the run cache")
        # a second run revalidates through the same cache directory (conditional GET, 304)
        self.server.requests.clear()
        again = TeckReports().discover(teck_binding(), self.context())
        self.assertEqual(len(again), 4)
        pages = [r for r in self.server.requests if r[0].startswith("/charter_boats/")]
        self.assertTrue(pages and all(tag for _, tag in pages))

    def test_adapters_build_no_session_or_cache_of_their_own(self):
        for module in (teck_module, directories_module):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertNotRegex(source, r"\b(Session|HTTPCache|FleetSession|default_session|cache_from_environment)\(")
            self.assertNotIn("http-cache", source)
        self.assertIn("collect.client_factory(ctx.net, cache=collect.http_cache())",
                      Path(teck_module.__file__).read_text(encoding="utf-8"))

    def test_dedupe_index_binding_is_a_recorded_skip(self):
        ctx = self.context()
        self.assertEqual(list(TeckReports().discover(teck_binding(role="dedupe-index"), ctx)), [])
        self.assertEqual(ctx.net.skips[0]["reason"], "unsupported-role")
        self.assertEqual(self.server.requests, [])

    def test_directories_discover(self):
        ctx = self.context()
        candidates = Directories().discover(dir_binding("ggfa"), ctx)
        self.assertEqual([plain(c) for c in candidates], expected(DIRS / "discover.expected.json"))
        members = dir_binding("sac", "https://association.example.org/members")
        self.assertEqual(list(Directories().discover(members, ctx)), [])  # landings, not vessels
        seeds = Directories().landing_seeds(members, ctx)
        self.assertEqual([plain(x) for x in seeds], expected(DIRS / "sac.expected.json"))
        self.assertEqual(list(Directories().discover(dir_binding("harbor"), ctx)), [])
        self.assertEqual(ctx.net.skips[-1]["reason"], "unsupported-list")

    def test_registry(self):
        self.assertIs(get("teck-reports"), TeckReports)
        self.assertIs(get("directories"), Directories)


class CollectorClientContractTests(unittest.TestCase):
    """The daily collector's own reads are unchanged: no cache option unless one is given."""

    def test_default_client_passes_no_cache_option(self):
        fake = http.FakeSession({"https://www.example.org/a": b"page"})
        self.assertEqual(collect.Client(None, session=fake).get("https://www.example.org/a"), "page")
        self.assertNotIn("cache", fake.calls[0][2])
        self.assertEqual(collect.client_factory(fake, cache=None)(None).get("https://www.example.org/a"), "page")
        self.assertIsNone(fake.calls[1][2]["cache"])

    def test_dock_totals_url_is_unchanged(self):
        self.assertEqual(collect.TECK_DOCK_TOTALS + "2026-10-01",
                         "https://www.socalfishreports.com/dock_totals/boats.php?date=2026-10-01")


if __name__ == "__main__":
    unittest.main()
