"""The landing-pages adapter (CF-14): fr-fleet-php and generic templates on synthetic fixtures.

Offline: a local plain-HTTP server stands in for every landing host, reached through a
real FleetSession (allowlist, robots, budget), so the test sees every path the adapter
asked for. Photos must stay links: no image path may ever be requested.
"""
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import socket
import tempfile
import threading
from types import SimpleNamespace
import unittest

from skippercast.fleet import ops
from skippercast.fleet.adapters import get
from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters._html import LayoutError
from skippercast.fleet.adapters.landing_pages import (_names, cash_cents, day_set, fleet_entries, parse_html,
                                                      price_cents, season_range, trip_type)
from skippercast.fleet.config import Binding, Landing
from skippercast.fleet.net import FleetSession
from skippercast.fleet.sinks import SqliteSink
from tests._support import FIXTURES

PAGES = {"/fleet.php": "fr-fleet.html", "/boats/kelpfixture.php": "fr-boat-kelp.html",
         "/boats/blueplaceholder.php": "fr-boat-blue.html", "/charter-fleet/": "generic.html",
         "/boats/changedfixture.php": "fr-boat-changed.html", "/changed/fleet.php": "fr-fleet-changed.html"}
FR_HOST, GENERIC_HOST = "www.example-harbor.example.com", "www.generic-landing.example.com"
T0 = "2026-10-05T09:47:00Z"
LANDING = Landing("example-harbor-landing", "Example Harbor Landing", "example-port", (33.0, -117.0), None)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.paths.append(self.path)
        name = PAGES.get(self.path)
        if self.path == "/robots.txt":
            status, body = 200, b"User-agent: *\nDisallow:\n"
        elif name:
            status, body = 200, (FIXTURES / "fleet" / "landings" / name).read_bytes()
        elif self.path.endswith((".jpg", ".png")):
            status, body = 200, b"\xff\xd8 image bytes"
        else:
            status, body = 404, b"not found"
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def binding(template, url, ident="example-harbor-landing"):
    return Binding(ident, "landing-pages", True, {"landing": "example-harbor-landing", "template": template, "url": url},
                   "facts-only")


class LandingPagesTests(unittest.TestCase):
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
        self.connected = []

        def factory(host, port, addresses, context=None, timeout=None):
            self.connected.append(host)
            return HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=timeout)

        def resolver(host, port, type=None):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        net = FleetSession({FR_HOST, GENERIC_HOST, "offsite.example.net"}, ("fareharbor.com",), sleep=lambda s: None,
                           connection_factory=factory, resolver=resolver, attempts=1)
        self.ctx = RunContext(SimpleNamespace(landings=(LANDING,)), net, Path("."), lambda: T0)
        self.adapter = get("landing-pages")()

    def fr(self):
        return {c.name: c for c in self.adapter.discover(binding("fr-fleet-php", f"https://{FR_HOST}/fleet.php"), self.ctx)}

    def test_fleet_list_and_boat_pages_without_fetching_images(self):
        boats = self.fr()
        self.assertEqual(list(boats), ["Kelp Fixture", "Blue Placeholder II", "Offsite Example", "Gone Fixture",
                                       "Changed Fixture"])
        # Only HTML pages on the landing's host: never an image, never the other host's boat page.
        self.assertEqual(self.server.paths, ["/robots.txt", "/fleet.php", "/boats/kelpfixture.php",
                                             "/boats/blueplaceholder.php", "/boats/gonefixture.php",
                                             "/boats/changedfixture.php"])
        self.assertEqual(set(self.connected), {FR_HOST})
        self.assertEqual(self.ctx.net.skips, [
            {"url": f"https://{FR_HOST}/boats/gonefixture.php", "reason": "fetch-error", "detail": "HTTPStatusError"},
            {"url": f"https://{FR_HOST}/boats/changedfixture.php", "reason": "layout",
             "detail": "boat page without pod_boat_details, rates-container or data-trip-id"}])
        # record_id is the boat's record URL (the review fingerprint): one per boat, never shared.
        self.assertEqual(len({c.record_id for c in boats.values()}), len(boats))
        kelp = boats["Kelp Fixture"]
        self.assertEqual((kelp.source_id, kelp.landing_hint, kelp.port_hint, kelp.record_id),
                         ("landing-pages", "example-harbor-landing", "example-port", f"https://{FR_HOST}/boats/kelpfixture.php"))
        facts = {}
        for f in kelp.facts:
            facts.setdefault(f.field, []).append(f.value)
            self.assertEqual((f.method, f.rights, f.retrieved_at), ("page", "facts-only", T0))
            self.assertTrue(f.source_url.startswith(f"https://{FR_HOST}/"))
        self.assertEqual(facts["photos[]"], [
            {"url": f"https://{FR_HOST}/graphics/boats/kelp_large.jpg", "attribution": "Example Harbor Landing"},
            {"url": f"https://{FR_HOST}/graphics/boats/kelp_detail_large.jpg", "attribution": "Example Harbor Landing"}])
        self.assertEqual({c["name"] for c in facts["captains[]"]}, {"Alex Sample", "Jordan Placeholder"})
        self.assertEqual((facts["length_ft"], facts["beam_ft"], facts["passengers_max"]), ([65.0], [20.0], [40]))
        self.assertEqual(facts["website"], ["http://kelpfixture.example.com"])
        self.assertEqual((facts["landing"], facts["port"]), (["Example Harbor Landing"], ["example-port"]))
        # Never owners, mailing addresses, trip comments or open spots.
        text = json.dumps([[f.value for f in c.facts] + [vars(d) | {"offering": None} for d in c.departures]
                           for c in boats.values()], default=str)
        for private in ("Ownerexample", "Example Way", "Pat Example", "PAT EXAMPLE", "Holdings", "Chartered"):
            self.assertNotIn(private, text)
        offsite = boats["Offsite Example"]
        self.assertEqual(offsite.record_id, "https://offsite.example.net/boat.php")
        self.assertEqual([f.value for f in offsite.facts if f.field == "photos[]"],
                         [{"url": "https://offsite.example.net/photo.png", "attribution": "Example Harbor Landing"}])
        # Photos must be https: the gone boat's http image is not recorded.
        self.assertEqual([f for f in boats["Gone Fixture"].facts if f.field == "photos[]"], [])

    def test_changed_boat_page_is_a_layout_skip_keeping_the_fleet_card(self):
        changed = self.fr()["Changed Fixture"]
        self.assertEqual(changed.record_id, f"https://{FR_HOST}/boats/changedfixture.php")
        fields = {}
        for f in changed.facts:
            fields.setdefault(f.field, []).append(f.value)
            self.assertEqual(f.source_url, f"https://{FR_HOST}/fleet.php")  # nothing read from the changed page
        self.assertEqual(sorted(fields), ["captains[]", "landing", "name", "photos[]", "port"])
        # "(relief)", "TBA" and "Owner/Operator" are not captains.
        self.assertEqual(fields["captains[]"], [{"name": "Riley Example", "role": "captain"}])
        self.assertEqual((changed.offerings, changed.departures), ((), ()))

    def test_changed_fleet_page_is_a_layout_skip_not_an_empty_fleet(self):
        for template in ("fr-fleet-php", "generic"):
            self.ctx.net.skips.clear()
            url = f"https://{FR_HOST}/changed/fleet.php"
            self.assertEqual(list(self.adapter.discover(binding(template, url), self.ctx)), [])
            self.assertEqual(self.ctx.net.skips, [{"url": url, "reason": "layout",
                                                   "detail": f"no boats on the {template} fleet page"}])
        self.assertNotIn("/v.php", " ".join(self.server.paths))

    def test_rate_rows_and_schedule_prices_parse_to_cents_with_basis(self):
        boats = self.fr()
        kelp = [(o.name, o.trip_type, o.price_cents, o.price_basis, o.capacity, o.days, o.season_from, o.season_to)
                for o in boats["Kelp Fixture"].offerings]
        self.assertEqual(kelp, [
            ("Private charter: Half Day (Mon - Thu)", "half-day", 240000, "private", 40, ("mon", "tue", "wed", "thu"), "05-01", "10-31"),
            ("Private charter: Half Day (Fri - Sun)", "half-day", 265050, "private", 40, ("fri", "sat", "sun"), "05-01", "10-31"),
            ("Private charter: Twilight", "half-day", 150000, "private", 40, None, "11-01", "04-30"),
            ("Private charter: Full Day Local (Fri - Sun)", "full-day", 545000, "private", 30, ("fri", "sat", "sun"), None, None),
            ("AM Half Day", "half-day", 8280, "per-person", 40, None, None, None),
            ("3/4 Day", "three-quarter-day", None, "per-person", None, None, None, None)])
        am = boats["Kelp Fixture"].offerings[4]
        self.assertEqual((am.departs_local, am.duration_h), ("06:30", 5.5))
        blue = boats["Blue Placeholder II"]
        self.assertEqual([(o.name, o.price_cents, o.price_basis, o.capacity) for o in blue.offerings], [
            ("Private charter: Overnight", None, "private", 30),
            ("Private charter: 1.5 Day (Winter)", 1556000, "private", 26),
            ("2 Day Limited Load", 98325, "per-person", 24)])  # the repeated rate row and trip spelling are one each
        # The repeated Overnight row ($10,500 cash, then $9,999) names the same offering at another price: the
        # price is unknown, and the offering cites both rows.
        self.assertEqual([f.value["price_cents"] for f in blue.offerings[0].facts], [1050000, 999900])
        self.assertEqual(blue.offerings[2].duration_h, 44.0)
        self.assertEqual([(d.offering.name, d.date, d.departs_local, d.price_cents) for d in blue.departures],
                         [("2 Day Limited Load", "2026-11-02", "10:00", 98325)])
        self.assertEqual({(f.field, f.value) for f in blue.facts if f.field in ("length_ft", "beam_ft", "passengers_max")},
                         {("length_ft", 88.0), ("beam_ft", 24.0), ("passengers_max", 26)})
        self.assertEqual({c["name"] for f in blue.facts if f.field == "captains[]" for c in [f.value]},
                         {"Casey Example", "Morgan Fixture"})
        for o in blue.offerings + boats["Kelp Fixture"].offerings:  # each offering cites the facts it was read from
            self.assertEqual({f.field for f in o.facts}, {"trip_types[]"})
            for fact in o.facts:
                self.assertIn(fact, blue.facts + boats["Kelp Fixture"].facts)
        # as_dict serialises offerings and departures (the run files and goldens use it).
        row = json.loads(json.dumps(blue.as_dict()))
        self.assertEqual((row["offerings"][2]["name"], row["departures"][0]["offering"]["name"],
                          row["departures"][0]["date"]), ("2 Day Limited Load", "2 Day Limited Load", "2026-11-02"))

    def test_schedule_rows_become_departures_with_deterministic_ids(self):
        kelp = self.fr()["Kelp Fixture"]
        rows = [(d.offering.name, d.date, d.departs_local, d.price_cents, d.load_text) for d in kelp.departures]
        self.assertEqual(rows, [("AM Half Day", "2026-10-06", "06:30", 8280, "40"),
                                ("AM Half Day", "2026-10-07", "06:30", 8280, "40"),
                                ("3/4 Day", "2026-10-10", "05:30", None, None)])
        # The other boat's row and the row naming no boat are dropped.
        vessel = ops.vessel_id("XX", "name-port:kelp-fixture|example-port")
        first = [d.op(vessel) for d in kelp.departures]
        again = [d.op(vessel) for d in self.fr()["Kelp Fixture"].departures]
        self.assertEqual(first, again)
        offering = kelp.offerings[4].id(vessel)
        self.assertEqual(offering, ops.offering_id(vessel, "AMHALFDAY", ""))
        self.assertEqual(first[0]["id"], ops.departure_id(offering, "2026-10-06", "06:30"))
        self.assertEqual(len({op["id"] for op in first}), 3)
        # The ops pass the job contract, and replaying them changes nothing.
        operations = [{"op": "vessel.upsert", "id": vessel, "creation_key": "name-port:kelp-fixture|example-port",
                       "slug": "kelp-fixture", "name": "Kelp Fixture", "name_norm": "KELPFIXTURE", "status": "active",
                       "profile_status": "hidden", "completeness": 0.2, "first_seen_at": T0, "last_seen_at": T0}]
        operations += [o.op(vessel, T0) for o in kelp.offerings] + first
        self.assertEqual(ops.validate_ops(operations, "XX")[1], [])
        with tempfile.TemporaryDirectory() as tmp:
            sink = SqliteSink(Path(tmp) / "XX.sqlite", "XX", "run-1")
            try:
                self.assertEqual(sink.apply(operations)["counts"]["departure.upsert"], {"ops": 3, "changed": 3})
                self.assertEqual(sink.apply(operations)["changed"], 0)
                ids = sink.db.execute("SELECT source_fact_ids_json FROM fleet_offerings WHERE id=?", (offering,)).fetchone()
            finally:
                sink.close()
        fact = kelp.offerings[4].facts[0]
        self.assertEqual(json.loads(ids[0]), [ops.fact_id(vessel, "trip_types[]", "landing-pages", fact.source_url,
                                                          ops.value_key(fact.value))])

    def test_generic_template_records_names_and_links_only(self):
        url = f"https://{GENERIC_HOST}/charter-fleet/"
        boats = list(self.adapter.discover(binding("generic", url, "generic-landing"), self.ctx))
        self.assertEqual([(c.name, c.record_id) for c in boats], [
            ("Tidepool Example", f"https://{GENERIC_HOST}/boat/tidepool-example"),
            ("Swell Placeholder", f"https://{GENERIC_HOST}/boat/swell-placeholder"),
            ("Sandbar Fixture", f"https://{GENERIC_HOST}/boat/sandbar-fixture")])
        self.assertEqual(self.server.paths, ["/robots.txt", "/charter-fleet/"])
        for c in boats:
            self.assertEqual({f.field for f in c.facts}, {"name", "landing", "port"})
            self.assertEqual((c.offerings, c.departures), ((), ()))

    def test_unknown_template_and_refused_fleet_url(self):
        with self.assertRaises(ValueError):
            list(self.adapter.discover(binding("wordpress", f"https://{FR_HOST}/fleet.php"), self.ctx))
        self.assertEqual(list(self.adapter.discover(binding("generic", "https://www.fareharbor.com/x"), self.ctx)), [])
        self.assertEqual(self.ctx.net.skips[0]["reason"], "off-limits")
        self.assertEqual(self.server.paths, [])


class ParserTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual([price_cents(x) for x in ("$10,867.50 Credit", "$1656", "$82.8", "N/A", "-", "$ 75")],
                         [1086750, 165600, 8280, None, None, 7500])
        self.assertEqual([trip_type(x) for x in ("3/4 Day", "AM 1/2 Day", "Twilight", "Overnight - Summer", "2,5 Day",
                                                 "1 Day Islands", "Full Day Offshore", "Private Charter", "Rockfish")],
                         ["three-quarter-day", "half-day", "half-day", "overnight", "multi-day", "full-day", "full-day",
                          "private-charter", "other"])
        self.assertEqual(season_range("Nov- April"), ("11-01", "04-30"))
        self.assertEqual(season_range("Feb - June"), ("02-01", "06-30"))
        self.assertIsNone(season_range("All Year"))
        self.assertEqual(day_set("Fri - Mon"), ("fri", "sat", "sun", "mon"))
        self.assertEqual(day_set("Friday"), ("fri",))
        self.assertIsNone(day_set("Credit"))

    def test_cash_price_is_chosen_by_label(self):
        self.assertEqual([cash_cents(x) for x in ("$2,400 Cash $2,484 Credit", "$2,484 Credit $2,400 Cash",
                                                  "Credit: $2,484 Cash: $2,400", "$983.25 $1,017.66 Credit", "$1,500",
                                                  "$2,484 Credit", "$100 $120", "N/A")],
                         [240000, 240000, 240000, 98325, 150000, None, None, None])

    def test_captain_names_drop_non_name_tokens(self):
        self.assertEqual(_names("Captains: Alex Sample & Jordan Placeholder"), ["Alex Sample", "Jordan Placeholder"])
        self.assertEqual(_names("Capt. Casey Example/Morgan Fixture (relief)"), ["Casey Example", "Morgan Fixture"])
        self.assertEqual(_names("Captain: Riley Example (owner), TBA - Owner/Operator"), ["Riley Example"])
        self.assertEqual(_names("Rotating captains; call the office"), [])

    def test_empty_fleet_page_raises_layout_error(self):
        with self.assertRaises(LayoutError):
            fleet_entries(parse_html("<html><body><h1>Fleet</h1></body></html>"), "https://x.example.com/f", "generic")

    def test_deeply_nested_page_does_not_hit_the_recursion_limit(self):
        page = "<div>" * 20000 + '<a href="/boat/deep-example">Deep Example</a>' + "</div>" * 20000
        self.assertEqual(fleet_entries(parse_html(page), "https://x.example.com/fleet/", "generic"),
                         [{"name": "Deep Example", "link": "https://x.example.com/boat/deep-example"}])


if __name__ == "__main__":
    unittest.main()
