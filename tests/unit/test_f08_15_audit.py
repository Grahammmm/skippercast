"""F08-15: linked offering facts must cite each component's own observation."""
from datetime import datetime
import json
import unittest

from skippercast.fleet import ops
from skippercast.fleet.ingest import profile_ops
from skippercast.fleet.resolve import ResolverConfig, Snapshot
from skippercast.fleet.sinks import SqliteSink

NAME_PAGE = "https://trips.example/list"
PRICE_PAGE = "https://trips.example/fares"
NAME_AT = "2026-10-01T12:00:00Z"
PRICE_AT = "2026-10-02T12:00:00Z"
NOW = "2026-10-03T12:00:00Z"
VESSEL = "a" * 32


def leaf(value, url, at, method="page"):
    return {"value": value, "source_url": url, "retrieved_at": at, "method": method, "confidence": 0.9}


class OfferingProvenanceTests(unittest.TestCase):
    def test_offering_fact_cites_the_actual_source_and_time_for_each_component(self):
        # A later price observation must not inherit the name URL, nor lend its time to the name.
        for url, at in ((NAME_PAGE, NAME_AT), (PRICE_PAGE, PRICE_AT), (NAME_PAGE, PRICE_AT)):
            with self.subTest(price_url=url, price_at=at):
                trip = {"name": leaf("Half Day", NAME_PAGE, NAME_AT), "price_usd": leaf(65, url, at, "search"),
                        "target_species": [leaf("Rockfish", NAME_PAGE, NAME_AT), leaf("Lingcod", url, at)]}
                vessel = {"id": VESSEL, "name": "Example Vessel", "slug": "example-vessel", "name_norm": "EXAMPLEVESSEL",
                          "first_seen_at": NAME_AT, "last_seen_at": NAME_AT}
                doc = {"vessel_id": VESSEL, "region": "CA", "boat": {"trip_types": [trip]}}
                batch, info = profile_ops(Snapshot([vessel]), [doc], ResolverConfig("CA", {}, 0.95, 0.5, {}, {}), NOW)
                self.assertFalse(info["skipped"])
                with self.subTest(storage="staging"):
                    sink = SqliteSink(":memory:", "CA", "f08-15", clock=lambda: datetime.fromisoformat(NOW))
                    try:
                        sink.apply(batch)
                        offering = sink.db.execute("SELECT name, price_cents, target_species_json, source_fact_ids_json "
                                                   "FROM fleet_offerings").fetchone()
                        self.assertEqual((*offering[:2], json.loads(offering[2])), ("Half Day", 6500, ["rockfish", "lingcod"]))
                        (fact_id,) = json.loads(offering[3])
                        raw, source, stamp, method, confidence = sink.db.execute(
                            "SELECT value_json, source_url, retrieved_at, method, confidence FROM fleet_vessel_facts WHERE id=?",
                            (fact_id,)).fetchone()
                    finally:
                        sink.close()
                self.assertEqual((method, confidence), ("search", 0.8))  # preserve the existing display eligibility
                value = json.loads(raw)
                expected_name = {"source_url": NAME_PAGE, "retrieved_at": NAME_AT}
                expected_price = {"source_url": url, "retrieved_at": at}
                anchor = {"source_url": source, "retrieved_at": stamp.replace(".000Z", "Z")}
                sources = value.get("component_sources", {})
                self.assertEqual((value["name"], sources.get("name", anchor)), (offering[0], expected_name))
                self.assertEqual((value["price_usd"], sources.get("price_usd", anchor)), (offering[1] / 100, expected_price))
                self.assertEqual(anchor, expected_name)
                self.assertEqual(sources.get("target_species", [anchor] * 2), [expected_name, expected_price])
                if (url, at) == (NAME_PAGE, NAME_AT):
                    self.assertEqual(value, {"name": "Half Day", "price_usd": 65, "target_species": ["Rockfish", "Lingcod"]})
                self.assertEqual(stamp, ops.iso(NAME_AT, "retrieved_at"))
