"""Places searches cut short by max_requests / max_pages must not turn a prefix into a unique match."""

from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

from skippercast.fleet import ops
from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters.google_places import GooglePlaces
from skippercast.fleet.config import load_region
from skippercast.fleet.runs import Run

NOW = "2026-10-05T10:00:00Z"
REGION = load_region("CA")
BOAT = {"vessel_id": ops.vessel_id("CA", "name-port:test-1|morro-bay"), "name": "Sea Example", "port_id": "morro-bay"}
OTHER = {"vessel_id": ops.vessel_id("CA", "name-port:test-2|san-diego"), "name": "Other Example", "port_id": "san-diego"}


def place(pid, label):
    return {"id": pid, "displayName": {"text": label}, "businessStatus": "OPERATIONAL"}


class _Pages:
    """Transport serving per-port page lists; a page's token points at the next page."""

    def __init__(self, pages_by_port):
        self.pages_by_port = pages_by_port
        self.calls = []

    def search_text(self, body, field_mask):
        self.calls.append(body["textQuery"])
        port = "Morro Bay" if "Morro Bay" in body["textQuery"] else "San Diego"
        index = int(body.get("pageToken", "0"))
        pages = self.pages_by_port.get(port, [{}])
        page = dict(pages[index])
        if index + 1 < len(pages) or page.pop("more", False):
            page["nextPageToken"] = str(index + 1)
        return page

    def details(self, place_id, field_mask):
        raise AssertionError("no details expected")


UNIQUE = {"places": [place("ChIJexampleSeaExample01", "Sea Example Charters")]}
TWIN = {"places": [place("ChIJexampleSeaExample02", "Sea Example Too")]}
OTHER_PAGE = {"places": [place("ChIJexampleOtherExmpl01", "Other Example Charters")]}


class PlacesBoundTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        self.ctx = RunContext(region=REGION, net=None, run_dir=Run("CA", "20261005T100000Z-abcdef", var=tmp).dir,
                              clock=lambda: NOW)

    def run_places(self, pages, vessels=(BOAT,), **params):
        binding = SimpleNamespace(id="google-places", params={"query": "fishing charter", **params}, rights="api-terms")
        transport = _Pages(pages)
        adapter = GooglePlaces(transport=transport, environ={})
        adapter.prepare(list(vessels), binding, self.ctx)
        facts = {v["name"]: adapter.enrich(v, binding, self.ctx) for v in vessels}
        return adapter, transport, facts

    def test_budget_truncated_prefix_never_becomes_unique(self):
        adapter, transport, facts = self.run_places({"Morro Bay": [UNIQUE, TWIN]}, max_requests=1)
        self.assertEqual(facts["Sea Example"], [])
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual((adapter.report["matched"], adapter.report["errors"], adapter.report["searches"]), (0, 1, 1))
        self.assertTrue(adapter.report["budget_exhausted"])
        full, _t, full_facts = self.run_places({"Morro Bay": [UNIQUE, TWIN]}, max_requests=2)
        self.assertEqual(full_facts["Sea Example"], [])
        self.assertEqual((full.report["ambiguous"], full.report["errors"]), (1, 0))

    def test_page_cap_truncated_prefix_never_becomes_unique(self):
        adapter, transport, facts = self.run_places({"Morro Bay": [UNIQUE, TWIN]}, max_pages=1)
        self.assertEqual(facts["Sea Example"], [])
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual((adapter.report["matched"], adapter.report["errors"]), (0, 1))
        self.assertNotIn("budget_exhausted", adapter.report)

    def test_terminal_page_at_exact_bound_is_complete(self):
        adapter, transport, facts = self.run_places({"Morro Bay": [{"places": []}, UNIQUE]}, max_requests=2, max_pages=2)
        self.assertEqual([f.value for f in facts["Sea Example"]], ["ChIJexampleSeaExample01"])
        self.assertEqual((len(transport.calls), adapter.report["errors"], adapter.report["matched"]), (2, 0, 1))

    def test_empty_prefix_with_token_is_not_complete(self):
        adapter, _t, facts = self.run_places({"Morro Bay": [{"places": [], "more": True}]}, max_pages=1)
        self.assertEqual((facts["Sea Example"], adapter.report["errors"]), ([], 1))
        done, _t, _f = self.run_places({"Morro Bay": [{"places": []}]}, max_pages=1)
        self.assertEqual((done.report["errors"], done.report["matched"]), (0, 0))

    def test_zero_calls_and_prior_completed_ports_preserved(self):
        adapter, transport, facts = self.run_places({"Morro Bay": [UNIQUE]}, max_requests=0)
        self.assertEqual((transport.calls, facts["Sea Example"], adapter.report["errors"]), ([], [], 0))
        adapter, transport, facts = self.run_places({"Morro Bay": [UNIQUE]}, max_pages=0)
        self.assertEqual((transport.calls, facts["Sea Example"], adapter.report["errors"]), ([], [], 0))
        # morro-bay sorts before san-diego: it completes, then san-diego cannot start
        adapter, transport, facts = self.run_places({"Morro Bay": [UNIQUE], "San Diego": [OTHER_PAGE]},
                                                    vessels=(BOAT, OTHER), max_requests=1)
        self.assertEqual([f.value for f in facts["Sea Example"]], ["ChIJexampleSeaExample01"])
        self.assertEqual(facts["Other Example"], [])
        self.assertEqual((len(transport.calls), adapter.report["errors"]), (1, 0))

    def test_incomplete_port_does_not_block_a_complete_port(self):
        adapter, transport, facts = self.run_places({"Morro Bay": [UNIQUE, TWIN], "San Diego": [OTHER_PAGE]},
                                                    vessels=(BOAT, OTHER), max_pages=1, max_requests=5)
        self.assertEqual(facts["Sea Example"], [])
        self.assertEqual([f.value for f in facts["Other Example"]], ["ChIJexampleOtherExmpl01"])
        self.assertEqual((len(transport.calls), adapter.report["errors"], adapter.report["matched"]), (2, 1, 1))

    def test_all_accumulated_pages_discarded_on_late_bound(self):
        pages = {"Morro Bay": [{"places": []}, UNIQUE, TWIN]}
        for params in ({"max_pages": 2}, {"max_requests": 2}):
            adapter, transport, facts = self.run_places(pages, **params)
            self.assertEqual(facts["Sea Example"], [], params)
            self.assertEqual((len(transport.calls), adapter.report["errors"], adapter.report["matched"]), (2, 1, 0))


if __name__ == "__main__":
    unittest.main()
