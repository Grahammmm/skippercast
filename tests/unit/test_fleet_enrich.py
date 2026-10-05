"""enrich-code (CF-16): operator sites, Google Places and the CPRA file import.

Offline. The operator site is served by a local plain-HTTP server standing in
for every host (the pattern of test_fleet_net.py): the session's connection
factory records the host of every connection, so a URL that is stored as a
value but never fetched can be shown to open no connection. Places runs on a
fake transport; the HTTP transport on ``skippercast.http.FakeSession``.
Fixtures under tests/fixtures/fleet/ are synthetic.
"""
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import socket
import tempfile
import threading
from types import SimpleNamespace
import unittest

from skippercast import http
from skippercast.fleet import enrich, ops
from skippercast.fleet.adapters import REGISTRY, get
from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters.file_import import FileImport, FileImportError, is_entity, read_rows
from skippercast.fleet.adapters.google_places import (CACHE_DAYS, GooglePlaces, HttpPlacesTransport, place_url,
                                                      places_purge_ops)
from skippercast.fleet.adapters.operator_site import OperatorSite, WEBMAIL_FLAG, phone_e164
from skippercast.fleet.config import load_region
from skippercast.fleet.net import FleetSession
from skippercast.fleet.runs import Run
from skippercast.fleet.sinks import SqliteSink
from tests._support import FIXTURES as _FIXTURES

FIXTURES = _FIXTURES / "fleet"
SITE = "https://www.seaexample.example/"
NOW = "2026-10-05T10:00:00Z"
REGION = load_region("CA")


def vessel_id(n: int) -> str:
    return ops.vessel_id("CA", f"name-port:test-{n}|morro-bay")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.paths.append(self.path)
        name = self.path.split("?", 1)[0].lstrip("/") or "index.html"
        fixture = FIXTURES / "operator-site" / name
        if self.path == "/robots.txt":
            body, kind = b"User-agent: *\nDisallow:\n", "text/plain"
        elif fixture.is_file():
            body, kind = fixture.read_bytes(), "text/html; charset=utf-8"
        else:  # every other page links on, so the crawl always has more pages than it may read
            n = len(self.server.paths)
            body, kind = f'<html><body><a href="/more-{n}.html">More</a></body></html>'.encode(), "text/html"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _Context:
    """A RunContext over the CA region and a FleetSession whose every connection goes to the local server."""

    def __init__(self, test, var: Path):
        self.connected: list[str] = []

        def factory(host, port, addresses, context=None, timeout=None):
            self.connected.append(host)
            return HTTPConnection("127.0.0.1", test.server.server_address[1], timeout=timeout)

        def resolver(host, port, type=None):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        net = FleetSession(set(), REGION.off_limits, sleep=lambda s: None, clock=lambda: 0.0,
                           connection_factory=factory, resolver=resolver, attempts=1)
        run = Run("CA", "20261005T100000Z-abcdef", var=var)
        self.ctx = RunContext(region=REGION, net=net, run_dir=run.dir, clock=lambda: NOW)


class OperatorSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.server.paths = []
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.server.paths.clear()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.context = _Context(self, self.tmp)
        self.binding = REGION.binding("operator-site")

    def facts(self, website=SITE, n=1):
        adapter = OperatorSite()
        found = list(adapter.enrich({"vessel_id": vessel_id(n), "website": website}, self.binding, self.context.ctx))
        return adapter, found

    def by_field(self, facts):
        out = {}
        for fact in facts:
            out.setdefault(fact.field, []).append(fact)
        return out

    def test_off_limits_booking_url_is_a_value_sourced_to_the_operator_page_and_never_fetched(self):
        _adapter, facts = self.facts()
        fields = self.by_field(facts)
        [booking] = fields["booking_url"]
        self.assertEqual(booking.value, "https://fareharbor.com/embeds/book/seaexample/items/?full-items=yes")
        self.assertEqual(booking.source_url, SITE)
        self.assertEqual(booking.method, "page")
        self.assertEqual([f.value for f in fields["booking_platform"]], ["fareharbor"])
        self.assertTrue(all(REGION.is_off_limits(f.value) for f in fields["social.instagram.url"]))
        self.assertTrue(all(not REGION.is_off_limits(f.source_url) for f in facts), "no source_url is off-limits")
        connected = set(self.context.connected)
        self.assertEqual(connected, {"www.seaexample.example"}, "only the operator's own host was contacted")

    def test_reads_at_most_six_pages_contact_first(self):
        adapter, _facts = self.facts()
        pages = [p for p in self.server.paths if p != "/robots.txt"]
        self.assertLessEqual(len(pages), 6)
        self.assertEqual(adapter.report["pages"], len(pages))
        self.assertEqual(pages[:2], ["/", "/contact.html"], "the homepage, then the best-ranked link")
        self.assertNotIn("/brochure.pdf", pages)

    def test_max_pages_param_is_capped_at_six(self):
        binding = SimpleNamespace(id="operator-site", params={"max_pages": 50}, rights="facts-only")
        OperatorSite().enrich({"vessel_id": vessel_id(1), "website": SITE}, binding, self.context.ctx)
        self.assertLessEqual(len([p for p in self.server.paths if p != "/robots.txt"]), 6)

    def test_contacts_social_and_photo(self):
        _adapter, facts = self.facts()
        fields = self.by_field(facts)
        phones = {f.value: f for f in fields["phone_business"]}
        self.assertEqual(set(phones), {"+18055550142", "+18055550143"})
        self.assertEqual(phones["+18055550142"].confidence, 0.8, "a tel: link beats the same number in text")
        self.assertEqual(phones["+18055550142"].source_url, SITE)
        emails = {f.value: f for f in fields["email_business"]}
        self.assertEqual(set(emails), {"info@seaexample.example", "seaexample.charters@gmail.com"})
        self.assertEqual(emails["info@seaexample.example"].flags, ())
        webmail = emails["seaexample.charters@gmail.com"]
        self.assertEqual(webmail.flags, (WEBMAIL_FLAG,))
        self.assertLess(webmail.confidence, REGION.resolver["email_business"].min_confidence, "cannot win unreviewed")
        self.assertEqual([f.value for f in fields["social.instagram.handle"]], ["seaexample"])
        self.assertEqual([f.value for f in fields["social.facebook.url"]], ["https://www.facebook.com/seaexample.charters/"])
        self.assertEqual([f.value for f in fields["photos[]"]],
                         [{"url": "https://www.seaexample.example/img/sea-example.jpg", "attribution": "www.seaexample.example"}])
        self.assertNotIn("website", fields)

    def test_every_fact_is_a_valid_fact_upsert(self):
        _adapter, facts = self.facts()
        for fact in facts:
            row = {"vessel_id": vessel_id(1), **fact.as_dict()}
            op = {"op": "fact.upsert", "vessel_id": row["vessel_id"], "field": row["field"], "value_json": row["value"],
                  "source_id": row["source_id"], "source_url": row["source_url"], "method": row["method"],
                  "confidence": row["confidence"], "rights": row["rights"], "retrieved_at": row["retrieved_at"]}
            ops.validate_op(op, 0, "CA")

    def test_a_shared_site_is_read_once(self):
        adapter = OperatorSite()
        first = adapter.enrich({"vessel_id": vessel_id(1), "website": SITE}, self.binding, self.context.ctx)
        count = len(self.server.paths)
        second = adapter.enrich({"vessel_id": vessel_id(2), "website": SITE}, self.binding, self.context.ctx)
        self.assertEqual(len(self.server.paths), count)
        self.assertEqual([f.value for f in first], [f.value for f in second])

    def test_off_limits_website_is_refused_before_any_connection(self):
        adapter, facts = self.facts("https://www.facebook.com/seaexample.charters/")
        self.assertEqual(facts, [])
        self.assertEqual(self.context.connected, [])
        self.assertEqual(adapter.report["refused"], 1)
        self.assertEqual(self.context.ctx.net.skips[0]["reason"], "off-limits")
        self.assertNotIn("www.facebook.com", self.context.ctx.net.hosts)

    def test_phone_normalisation(self):
        self.assertEqual(phone_e164("+1 (805) 555-0142"), "+18055550142")
        self.assertEqual(phone_e164("805.555.0143"), "+18055550143")
        self.assertIsNone(phone_e164("555-0142"))


class _FakePlaces:
    """A Places transport answering from the fixtures; records every call."""

    def __init__(self, details=None):
        self.calls = []
        self.details_map = details or {}

    def search_text(self, body, field_mask):
        self.calls.append(("search", dict(body), field_mask))
        name = "search-morro-bay-page2.json" if body.get("pageToken") else "search-morro-bay.json"
        if "Morro Bay" not in body["textQuery"]:
            return {}
        return json.loads((FIXTURES / "places" / name).read_text())

    def details(self, place_id, field_mask):
        self.calls.append(("details", place_id, field_mask))
        return self.details_map.get(place_id)


VESSELS = [
    {"vessel_id": vessel_id(1), "name": "Sea Example", "port_id": "morro-bay"},
    {"vessel_id": vessel_id(2), "name": "Test Boat", "port_id": "morro-bay"},          # two places match: ambiguous
    {"vessel_id": vessel_id(3), "name": "Closed Example", "port_id": "morro-bay"},     # permanently closed
    {"vessel_id": vessel_id(4), "name": "Paged Example", "port_id": "morro-bay"},      # on the second page
    {"vessel_id": vessel_id(5), "name": "Stored", "port_id": "san-diego", "place_id": "ChIJexampleStoredOld01"},
    {"vessel_id": vessel_id(6), "name": "Gone", "port_id": "san-diego", "place_id": "ChIJexampleGoneGone001"},
]


class GooglePlacesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        run = Run("CA", "20261005T100000Z-abcdef", var=self.tmp)
        self.ctx = RunContext(region=REGION, net=None, run_dir=run.dir, clock=lambda: NOW)
        self.binding = REGION.binding("google-places")

    def run_places(self, transport):
        adapter = GooglePlaces(transport=transport)
        adapter.prepare(VESSELS, self.binding, self.ctx)
        return adapter, {v["vessel_id"]: adapter.enrich(v, self.binding, self.ctx) for v in VESSELS}

    def test_without_a_key_places_is_skipped_and_reported(self):
        made = []
        adapter = GooglePlaces(environ={}, transport_factory=lambda key: made.append(key))
        adapter.prepare(VESSELS, self.binding, self.ctx)
        self.assertEqual([adapter.enrich(v, self.binding, self.ctx) for v in VESSELS], [[]] * len(VESSELS))
        self.assertEqual(made, [], "no transport is built without a key")
        self.assertEqual(adapter.report["status"], "skipped")
        self.assertIn("GOOGLE_PLACES_API_KEY", adapter.report["reason"])

    def test_key_comes_from_the_environment(self):
        made = []
        adapter = GooglePlaces(environ={"GOOGLE_PLACES_API_KEY": " test-key "},
                               transport_factory=lambda key: made.append(key) or _FakePlaces())
        self.assertTrue(adapter.available)
        self.assertEqual(made, ["test-key"])

    def test_one_search_per_port_and_one_to_one_matches_only(self):
        transport = _FakePlaces(details={"ChIJexampleStoredOld01": {"id": "ChIJexampleStoredNew01"}})
        adapter, facts = self.run_places(transport)
        searches = [c for c in transport.calls if c[0] == "search"]
        self.assertEqual(len(searches), 2, "Morro Bay: two pages; San Diego vessels already have place ids")
        self.assertIn("fishing charter Morro Bay, California", searches[0][1]["textQuery"])
        self.assertEqual(searches[0][1]["locationBias"]["circle"]["center"],
                         {"latitude": REGION.port("morro-bay").point[0], "longitude": REGION.port("morro-bay").point[1]})
        self.assertEqual(searches[1][1]["pageToken"], "page-2-token")
        self.assertEqual({k: [f.value for f in v] for k, v in facts.items() if v}, {
            vessel_id(1): ["ChIJexampleSeaExample01"], vessel_id(4): ["ChIJexamplePagedBoat001"],
            vessel_id(5): ["ChIJexampleStoredNew01"]})
        self.assertEqual(adapter.report["ambiguous"], 1)
        self.assertEqual(adapter.report["closed"], 1)
        self.assertEqual(adapter.report["not_found"], 1)
        self.assertEqual(adapter.report["refreshed"], 1)

    def test_only_place_id_is_requested_and_stored(self):
        transport = _FakePlaces(details={"ChIJexampleStoredOld01": {"id": "ChIJexampleStoredOld01"}})
        _adapter, facts = self.run_places(transport)
        for call in transport.calls:
            mask = call[2]
            for content in ("rating", "userRatingCount", "website", "phone", "location", "formattedAddress"):
                self.assertNotIn(content, mask)
        self.assertEqual([c[2] for c in transport.calls if c[0] == "details"], ["id", "id"])
        stored = [f for v in facts.values() for f in v]
        self.assertTrue(stored)
        for fact in stored:
            self.assertEqual(fact.field, "place_id")
            self.assertIn(fact.field, CACHE_DAYS)
            self.assertEqual((fact.source_id, fact.method, fact.rights), ("google-places", "api", "api-terms"))
            self.assertEqual(fact.source_url, place_url(fact.value))
            ops.validate_op({"op": "fact.upsert", "vessel_id": vessel_id(1), "field": fact.field,
                             "value_json": fact.value, "source_id": fact.source_id, "source_url": fact.source_url,
                             "method": fact.method, "confidence": fact.confidence, "rights": fact.rights,
                             "retrieved_at": fact.retrieved_at}, 0, "CA")

    def test_request_budget(self):
        binding = SimpleNamespace(id="google-places", params={"query": "fishing charter", "max_requests": 1},
                                  rights="api-terms")
        transport = _FakePlaces()
        adapter = GooglePlaces(transport=transport)
        adapter.prepare(VESSELS, binding, self.ctx)
        for vessel in VESSELS:
            adapter.enrich(vessel, binding, self.ctx)
        self.assertEqual(len(transport.calls), 1)
        self.assertTrue(adapter.report["budget_exhausted"])

    def test_http_transport_posts_with_the_key_in_a_header_and_never_caches(self):
        session = http.FakeSession({
            "https://places.googleapis.com/v1/places:searchText": b'{"places": []}',
            "https://places.googleapis.com/v1/places/ChIJexampleGoneGone001": (404, b'{"error": {"status": "NOT_FOUND"}}'),
        })
        transport = HttpPlacesTransport("test-key", session)
        self.assertEqual(transport.search_text({"textQuery": "x"}, "places.id"), {"places": []})
        self.assertIsNone(transport.details("ChIJexampleGoneGone001", "id"))
        (method, url, options), (method2, url2, options2) = session.calls
        self.assertEqual((method, method2), ("POST", "GET"))
        self.assertNotIn("test-key", url + url2)
        self.assertEqual(options["headers"]["X-Goog-Api-Key"], "test-key")
        self.assertEqual(options["headers"]["X-Goog-FieldMask"], "places.id")
        self.assertEqual(json.loads(options["data"]), {"textQuery": "x"})
        self.assertFalse(options["use_cache"] or options2["use_cache"])

    def test_purge_ops_follow_the_caching_rule(self):
        self.assertEqual(places_purge_ops("2026-10-05T10:00:00Z"), [
            {"op": "fact.purge", "source_id": "google-places",
             "keep_fields": ["location.latitude", "location.longitude", "place_id"], "seen_before": "2026-10-05T10:00:00Z"},
            {"op": "fact.purge", "source_id": "google-places", "keep_fields": ["place_id"],
             "seen_before": "2026-09-05T10:00:00Z"},
        ])
        for op in places_purge_ops(NOW):
            ops.validate_op(op, 0, "CA")


class FileImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.run = Run("CA", "20261005T100000Z-abcdef", var=self.tmp)
        self.ctx = RunContext(region=REGION, net=None, run_dir=self.run.dir, clock=lambda: NOW)
        self.binding = SimpleNamespace(id="cpra-cpfv", adapter="file-import", rights="public-record",
                                       params={"path": "inputs/cpra-cpfv.csv", "columns": "cdfw-cpfv-v1"})
        shutil.copy(FIXTURES / "cpra" / "cpfv-v1.csv", self.tmp / "CA" / "inputs" / "cpra-cpfv.csv")

    def test_individual_licensee_names_are_dropped(self):
        adapter = FileImport()
        candidates = list(adapter.discover(self.binding, self.ctx))
        text = json.dumps([c.as_dict() for c in candidates]) + json.dumps(adapter.report)
        for person in ("Pat Placeholder", "Jordan Example"):
            self.assertNotIn(person, text)
        businesses = {c.name: [f.value for f in c.facts if f.field == "operator_business"] for c in candidates}
        self.assertEqual(businesses, {"Sea Example": ["Sea Example Sportfishing, LLC"], "Test Boat": [],
                                      "Placeholder Queen": ["Example Fishing Co."]})
        self.assertEqual(adapter.report["cpra-cpfv"]["individual_licensees_dropped"], 1, "the nameless row is skipped")
        self.assertEqual(adapter.report["cpra-cpfv"]["rows_without_name"], 1)

    def test_columns_keys_ports_and_provenance(self):
        candidates = {c.name: c for c in FileImport().discover(self.binding, self.ctx)}
        sea = candidates["Sea Example"]
        self.assertEqual(dict(sea.keys), {"uscg_doc": "D1234567"})
        self.assertEqual(sea.port_hint, "morro-bay")
        facts = {f.field: f.value for f in sea.facts}
        self.assertEqual(facts["cdfw.fg_number"], "FG12345")
        self.assertEqual(facts["cdfw.cpfv_licence_number"], "CPFV000101")
        self.assertEqual(facts["cdfw.licence_year"], "2026-27")
        self.assertIs(facts["cdfw.crab_trap_validation"], True)
        test_boat = candidates["Test Boat"]
        self.assertEqual(dict(test_boat.keys), {"state_reg": "CF1234EX"})
        self.assertEqual(test_boat.port_hint, "port-san-luis")
        self.assertIs({f.field: f.value for f in test_boat.facts}["cdfw.crab_trap_validation"], False)
        self.assertIsNone(candidates["Placeholder Queen"].port_hint)
        self.assertNotIn("cdfw.crab_trap_validation", {f.field for f in candidates["Placeholder Queen"].facts})
        fact = sea.facts[0]
        self.assertTrue(fact.source_url.startswith("https://wildlife.ca.gov/General-Counsel/Public-Records-Requests#cpra-cpfv-"))
        self.assertEqual((fact.method, fact.rights, fact.source_id), ("registry", "public-record", "cpra-cpfv"))
        again = {c.name: c for c in FileImport().discover(self.binding, self.ctx)}
        self.assertEqual(again["Sea Example"].facts, sea.facts, "re-importing the same file gives the same facts")

    def test_entity_rule(self):
        for name in ("Sea Example Sportfishing, LLC", "Example Charters Inc.", "Example Fishing Co.", "Example L.L.C.",
                     "Example Boats Corporation", "Example Partners LP"):
            self.assertTrue(is_entity(name), name)
        for name in ("Pat Placeholder", "Jordan Example Family Trust", "Colby Example", "Example Inc Smith"):
            self.assertFalse(is_entity(name), name)

    def test_missing_required_columns_and_bad_paths(self):
        with self.assertRaises(FileImportError):
            read_rows(b"Vessel Name,Home Port\nSea Example,Morro Bay\n", "cdfw-cpfv-v1")
        with self.assertRaises(FileImportError):
            read_rows(b"FG Number\nFG1\n", "cdfw-cpfv-v1")
        for path in ("/etc/passwd", "inputs/../../secret.csv", "runs/x.csv"):
            binding = SimpleNamespace(**{**vars(self.binding), "params": {"path": path, "columns": "cdfw-cpfv-v1"}})
            with self.assertRaises(FileImportError):
                list(FileImport().discover(binding, self.ctx))

    def test_missing_file_is_a_reported_skip(self):
        (self.tmp / "CA" / "inputs" / "cpra-cpfv.csv").unlink()
        adapter = FileImport()
        self.assertEqual(list(adapter.discover(self.binding, self.ctx)), [])
        self.assertEqual(adapter.report["cpra-cpfv"]["status"], "skipped")


class EnrichStepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.run = Run("CA", "20261005T100000Z-abcdef", var=self.tmp)
        self.ctx = RunContext(region=REGION, net=None, run_dir=self.run.dir, clock=lambda: NOW)
        self.sink = SqliteSink(self.tmp / "CA.sqlite", "CA", self.run.id)
        self.addCleanup(self.sink.close)

    def seed(self):
        vessel = {"op": "vessel.upsert", "id": vessel_id(1), "creation_key": "name-port:test-1|morro-bay",
                  "slug": "sea-example", "name": "Sea Example", "name_norm": "SEAEXAMPLE", "port_id": "morro-bay",
                  "status": "active", "profile_status": "hidden", "completeness": 0.1,
                  "first_seen_at": "2026-08-01T00:00:00Z", "last_seen_at": NOW}

        def fact(field, value, seen, source="google-places"):
            return {"op": "fact.upsert", "vessel_id": vessel_id(1), "field": field, "value_json": value,
                    "source_id": source, "source_url": place_url("ChIJexampleSeaExample01"), "method": "api",
                    "confidence": 0.85, "rights": "api-terms", "retrieved_at": seen}

        self.sink.apply([vessel, fact("place_id", "ChIJexampleSeaExample01", "2026-01-01T00:00:00Z"),
                         fact("reputation.google_rating", 4.7, "2026-10-04T00:00:00Z"),
                         fact("location.latitude", 35.37, "2026-10-01T00:00:00Z"),
                         fact("location.longitude", -120.86, "2026-08-01T00:00:00Z"),
                         {**fact("reputation.google_rating", 4.2, "2026-10-04T00:00:00Z", source="osint"),
                          "source_url": "https://www.seaexample.example/", "method": "page"}])

    def stored(self):
        return sorted(self.sink.db.execute("SELECT source_id, field FROM fleet_vessel_facts").fetchall())

    def test_step_writes_facts_reports_skip_and_purges_places_content(self):
        self.seed()
        self.run.write_jsonl("resolved.jsonl", [VESSELS[0]])
        counts = enrich.enrich_code(self.ctx, self.sink, adapters={
            "operator-site": OperatorSite(), "google-places": GooglePlaces(environ={})})
        self.assertEqual(counts["places_skipped"], 1)
        self.assertEqual(counts["vessels"], 1)
        self.assertEqual(counts["purged"], 2, "the rating at once; the 65-day-old longitude after 30 days")
        self.assertEqual(self.stored(), [("google-places", "location.latitude"), ("google-places", "place_id"),
                                         ("osint", "reputation.google_rating")])
        report = json.loads((self.run.dir / "enrich-code.json").read_text())
        self.assertEqual(report["bindings"]["google-places"]["status"], "skipped")
        self.assertTrue((self.run.dir / "facts.jsonl").exists())
        self.assertEqual(self.sink.apply(places_purge_ops(NOW))["changed"], 0, "a second purge deletes nothing")

    def test_step_runs_places_and_imports(self):
        self.run.write_jsonl("resolved.jsonl", VESSELS)
        shutil.copy(FIXTURES / "cpra" / "cpfv-v1.csv", self.tmp / "CA" / "inputs" / "cpra-cpfv.csv")
        region = SimpleNamespace(**{k: getattr(REGION, k) for k in ("id", "name", "ports", "agencies", "port")})
        cpra = SimpleNamespace(id="cpra-cpfv", adapter="file-import", enabled=True, rights="public-record",
                               params={"path": "inputs/cpra-cpfv.csv", "columns": "cdfw-cpfv-v1"})
        sources = (REGION.binding("google-places"), cpra)
        region.sources = sources
        region.enabled_sources = lambda: sources
        region.binding = lambda ident: next(b for b in sources if b.id == ident)
        ctx = RunContext(region=region, net=None, run_dir=self.run.dir, clock=lambda: NOW)
        counts = enrich.enrich_code(ctx, self.sink, adapters={"google-places": GooglePlaces(transport=_FakePlaces())})
        rows = [json.loads(line) for line in (self.run.dir / "facts.jsonl").read_text().splitlines()]
        self.assertEqual({(r["vessel_id"], r["field"], r["value"]) for r in rows}, {
            (vessel_id(1), "place_id", "ChIJexampleSeaExample01"), (vessel_id(4), "place_id", "ChIJexamplePagedBoat001")})
        self.assertEqual(counts["imported"], 3)
        self.assertEqual(counts["places_skipped"], 0)
        imported = (self.run.dir / "imported.jsonl").read_text()
        self.assertNotIn("Pat Placeholder", imported)


class RegistryTests(unittest.TestCase):
    def test_cf16_adapters_are_registered(self):
        self.assertIs(get("operator-site"), OperatorSite)
        self.assertIs(get("google-places"), GooglePlaces)
        self.assertIs(get("file-import"), FileImport)
        self.assertEqual({k for k, v in REGISTRY.items() if v is not None} >= {"operator-site", "google-places", "file-import"}, True)


if __name__ == "__main__":
    unittest.main()
