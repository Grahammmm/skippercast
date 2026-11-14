"""A Places identifier is the whole 10-300 character ASCII grammar: a terminal newline is refused (RF2210-8).

Offline and synthetic. Places runs on a fake transport (``GooglePlaces`` prepare/enrich with ``environ={}``);
the direct input validator runs on ``skippercast.http.FakeSession``. Nothing here reads a key or opens a socket.
"""
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

from skippercast import http
from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters.google_places import GooglePlaces, HttpPlacesTransport, PLACE_ID, PlacesError, place_url
from skippercast.fleet.config import load_region
from skippercast.fleet.runs import Run

NOW = "2026-10-05T10:00:00Z"
REGION = load_region("CA")
BINDING = SimpleNamespace(id="google-places", params={"query": "fishing charter"}, rights="api-terms")
GOOD = "SyntheticPlace0001"
BAD = GOOD + "\n"
OTHER = "SyntheticPlace0002"
DETAILS_URL = "https://places.googleapis.com/v1/places/"


def _wire(value):
    """What a transport really hands over: the value after a JSON round trip."""
    return json.loads(json.dumps(value))


class _Fake:
    def __init__(self, places=(), details=None):
        self.places, self.details_map, self.calls = list(places), details or {}, []

    def search_text(self, body, field_mask):
        self.calls.append(("search", field_mask))
        return _wire({"places": self.places})

    def details(self, place_id, field_mask):
        self.calls.append(("details", place_id))
        return _wire(self.details_map.get(place_id))


def _place(place_id, name):
    return {"id": place_id, "displayName": {"text": name}, "businessStatus": "OPERATIONAL"}


class PlacesIdentifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        run = Run("CA", "20261005T100000Z-abcdef", var=self.tmp)
        self.ctx = RunContext(region=REGION, net=None, run_dir=run.dir, clock=lambda: NOW)

    def facts(self, transport, vessels):
        adapter = GooglePlaces(transport=transport, environ={})
        adapter.prepare(vessels, BINDING, self.ctx)
        return adapter, {v["vessel_id"]: adapter.enrich(v, BINDING, self.ctx) for v in vessels}

    def test_search_terminal_lf_never_emits_fact(self):
        vessels = [{"vessel_id": "v-bad", "name": "Sea Example", "port_id": "morro-bay"},
                   {"vessel_id": "v-good", "name": "Test Boat", "port_id": "morro-bay"}]
        transport = _Fake(places=[_place(BAD, "Sea Example Charters"), _place(OTHER, "Test Boat Charters")])
        adapter, facts = self.facts(transport, vessels)
        self.assertEqual(facts["v-bad"], [])
        self.assertEqual([f.value for f in facts["v-good"]], [OTHER])
        self.assertEqual(adapter.report["matched"], 1)
        self.assertEqual(adapter.report["ambiguous"], 0)

    def test_details_terminal_lf_never_emits_fact(self):
        vessels = [{"vessel_id": "v-bad", "name": "Stored One", "port_id": "san-diego", "place_id": "ChIJexampleStoredOld01"},
                   {"vessel_id": "v-good", "name": "Stored Two", "port_id": "san-diego", "place_id": "ChIJexampleStoredOld02"}]
        transport = _Fake(details={"ChIJexampleStoredOld01": {"id": BAD}, "ChIJexampleStoredOld02": {"id": GOOD}})
        adapter, facts = self.facts(transport, vessels)
        self.assertEqual(facts["v-bad"], [])
        self.assertEqual([f.value for f in facts["v-good"]], [GOOD])
        # The existing counting order is unchanged: a truthy returned id counts as refreshed before the final gate.
        self.assertEqual((adapter.report["details"], adapter.report["refreshed"]), (2, 2))
        self.assertEqual((adapter.report["not_found"], adapter.report["errors"]), (0, 0))

    def test_strict_lengths_and_ascii_grammar(self):
        for length in (10, 300):
            token = ("aZ09_-" * 60)[:length]
            self.assertIsNotNone(PLACE_ID.match(token), length)
            self.assertIsNone(PLACE_ID.match(token + "\n"), length)
        for refused in ("a" * 9, "a" * 301, "\n", "\n" + "a" * 10, "a" * 10 + "\r\n", "a" * 5 + "\n" + "a" * 5 + "a",
                        "a" * 9 + " ", "a" * 9 + "\t", "a" * 9 + "\0", "a" * 9 + "é", "a" * 10 + "\n\n"):
            self.assertIsNone(PLACE_ID.match(refused), repr(refused))

    def test_stored_invalid_id_refuses_before_fake_request(self):
        session = http.FakeSession({DETAILS_URL + GOOD: b'{"id": "' + GOOD.encode() + b'"}'})
        transport = HttpPlacesTransport("test-key", session)
        with self.assertRaises(PlacesError):
            transport.details(BAD, "id")
        self.assertEqual(session.calls, [])
        self.assertEqual(transport.details(GOOD, "id"), {"id": GOOD})
        (method, url, options), = session.calls
        self.assertEqual((method, url), ("GET", DETAILS_URL + GOOD))
        self.assertEqual(options["headers"]["X-Goog-FieldMask"], "id")

    def test_valid_facts_and_legacy_contract_unchanged(self):
        vessels = [{"vessel_id": "v-good", "name": "Test Boat", "port_id": "morro-bay"}]
        transport = _Fake(places=[_place(GOOD, "Test Boat Charters")])
        _adapter, facts = self.facts(transport, vessels)
        (fact,) = facts["v-good"]
        self.assertEqual((fact.field, fact.value, fact.source_id, fact.source_url, fact.method, fact.confidence,
                          fact.rights, fact.retrieved_at),
                         ("place_id", GOOD, "google-places", place_url(GOOD), "api", 0.85, "api-terms", NOW))
        self.assertEqual(place_url(GOOD), "https://www.google.com/maps/place/?q=place_id:" + GOOD)


if __name__ == "__main__":
    unittest.main()
