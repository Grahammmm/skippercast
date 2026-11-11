"""Malformed Places response envelopes are contained per port / per vessel (RF1025-7).

Offline: a fake transport returns synthetic JSON-equivalent values; no key, HTTP or disk cache.
"""
from pathlib import Path
import shutil
import tempfile
import unittest

from skippercast.fleet import ops
from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters.google_places import GooglePlaces
from skippercast.fleet.config import load_region
from skippercast.fleet.runs import Run

NOW = "2026-10-05T10:00:00Z"
REGION = load_region("CA")
BAD = {"list": [], "none": None, "int": 7, "bool": True, "str": "x"}
GOOD_PLACE = {"id": "ChIJexampleSeaExample01", "displayName": {"text": "Sea Example Charters"},
              "businessStatus": "OPERATIONAL"}
OTHER_PLACE = {"id": "ChIJexampleOtherBoat001", "displayName": {"text": "Other Boat Sportfishing"},
               "businessStatus": "OPERATIONAL"}


def vid(n: int, port: str) -> str:
    return ops.vessel_id("CA", f"name-port:test-{n}|{port}")


V_MORRO = {"vessel_id": vid(1, "morro-bay"), "name": "Sea Example", "port_id": "morro-bay"}
V_SD = {"vessel_id": vid(2, "san-diego"), "name": "Other Boat", "port_id": "san-diego"}


class _Transport:
    def __init__(self, search=None, details=None):
        self.search_fn = search or (lambda body: {})
        self.details_map = details or {}
        self.searches = 0
        self.detail_calls = 0

    def search_text(self, body, mask):
        self.searches += 1
        return self.search_fn(body)

    def details(self, place_id, mask):
        self.detail_calls += 1
        return self.details_map.get(place_id)


class PlacesPayloadTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        run = Run("CA", "20261005T100000Z-abcdef", var=tmp)
        self.ctx = RunContext(region=REGION, net=None, run_dir=run.dir, clock=lambda: NOW)
        self.binding = REGION.binding("google-places")

    def run_places(self, transport, vessels):
        adapter = GooglePlaces(transport=transport, environ={})
        adapter.prepare(vessels, self.binding, self.ctx)
        return adapter, {v["vessel_id"]: [f.value for f in adapter.enrich(v, self.binding, self.ctx)]
                         for v in vessels}

    def test_search_root_shape_errors_are_contained(self):
        for label, bad in BAD.items():
            with self.subTest(root=label):
                adapter, facts = self.run_places(_Transport(search=lambda body, b=bad: b), [V_MORRO])
                self.assertEqual(facts[V_MORRO["vessel_id"]], [])
                self.assertEqual(adapter.report["errors"], 1)
                self.assertEqual(adapter.report["matched"], 0)

    def test_places_collection_has_a_real_array_boundary(self):
        for label, bad in {"dict": {"a": 1}, "int": 3, "str": "x", "bool": True}.items():
            with self.subTest(places=label):
                adapter, facts = self.run_places(_Transport(search=lambda body, b=bad: {"places": b}), [V_MORRO])
                self.assertEqual(facts[V_MORRO["vessel_id"]], [])
                self.assertEqual(adapter.report["errors"], 1)
        for label, ok in {"missing": {}, "null": {"places": None}, "empty": {"places": []}}.items():
            with self.subTest(places=label):
                adapter, facts = self.run_places(_Transport(search=lambda body, o=ok: o), [V_MORRO])
                self.assertEqual(facts[V_MORRO["vessel_id"]], [])
                self.assertEqual(adapter.report["errors"], 0)
        with self.subTest(places="junk items"):
            adapter, facts = self.run_places(
                _Transport(search=lambda body: {"places": [1, "x", None, GOOD_PLACE]}), [V_MORRO])
            self.assertEqual(facts[V_MORRO["vessel_id"]], ["ChIJexampleSeaExample01"])
            self.assertEqual(adapter.report["errors"], 0)

    def test_later_bad_page_discards_partial_uniqueness_and_other_ports_survive(self):
        def search(body):
            if "San Diego" in body["textQuery"]:
                return {"places": [OTHER_PLACE]}
            if body.get("pageToken"):
                return {"places": {"bad": "shape"}}
            return {"places": [GOOD_PLACE], "nextPageToken": "page-2-token"}

        transport = _Transport(search=search)
        adapter, facts = self.run_places(transport, [V_MORRO, V_SD])
        self.assertEqual(facts[V_MORRO["vessel_id"]], [])
        self.assertEqual(facts[V_SD["vessel_id"]], ["ChIJexampleOtherBoat001"])
        self.assertEqual(adapter.report["errors"], 1)
        self.assertEqual(adapter.report["matched"], 1)
        self.assertEqual(adapter.report["searches"], 3)
        self.assertEqual(transport.searches, 3)
        self.assertEqual(adapter.requests, 3)

    def test_details_nonobjects_are_errors_not_not_found(self):
        stored = {"vessel_id": vid(3, "morro-bay"), "name": "Stored", "port_id": "morro-bay",
                  "place_id": "ChIJexampleStoredOld01"}
        fresh = {"vessel_id": vid(4, "morro-bay"), "name": "Fresh", "port_id": "morro-bay",
                 "place_id": "ChIJexampleFreshOld001"}
        for label, bad in {"list": [], "int": 7, "str": "x", "bool": True}.items():
            with self.subTest(details=label):
                transport = _Transport(details={stored["place_id"]: bad, fresh["place_id"]: {"id": "ChIJexampleFreshNew001"}})
                adapter, facts = self.run_places(transport, [stored, fresh])
                self.assertEqual(facts[stored["vessel_id"]], [])
                self.assertEqual(facts[fresh["vessel_id"]], ["ChIJexampleFreshNew001"])
                report = adapter.report
                self.assertEqual((report["errors"], report["not_found"], report["refreshed"], report["details"]),
                                 (1, 0, 1, 2))
        with self.subTest(details="None"):
            adapter, facts = self.run_places(_Transport(), [stored])
            self.assertEqual(facts[stored["vessel_id"]], [])
            self.assertEqual((adapter.report["errors"], adapter.report["not_found"]), (0, 1))

    def test_ordinary_contract_unchanged(self):
        stored = {"vessel_id": vid(3, "morro-bay"), "name": "Stored", "port_id": "morro-bay",
                  "place_id": "ChIJexampleStoredOld01"}
        transport = _Transport(search=lambda body: {"places": [GOOD_PLACE]},
                               details={stored["place_id"]: {"id": 5}})
        adapter, facts = self.run_places(transport, [V_MORRO, stored])
        self.assertEqual(facts[V_MORRO["vessel_id"]], ["ChIJexampleSeaExample01"])
        self.assertEqual(facts[stored["vessel_id"]], [])   # wrong-type id: no fact, no error
        self.assertEqual((adapter.report["errors"], adapter.report["matched"], adapter.report["refreshed"]), (0, 1, 0))


if __name__ == "__main__":
    unittest.main()
