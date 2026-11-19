"""F08-16: numeric hash inputs follow Worker JSON without rewriting stored fact IDs."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from skippercast.fleet import ops
from skippercast.fleet.sinks import SinkError, SqliteSink
from tests._support import ROOT
from tests.unit.test_fleet_sinks import T0, fact, vessel


class NumericFactIdsTests(unittest.TestCase):
    def test_number_spelling_matches_worker_json(self):
        # Pin both sides of the fixed/exponent boundary, including a binary64
        # subnormal, and distinguish a number from an identical-looking string.
        value = {"v": [1e-5, 1e-6, 9.999999999999997e-7, -1e-7, 5e-324,
                       -0.0, -9007199254740991, 9007199254740990.0, 9007199254740991,
                       1.25, "1e-05", True]}
        self.assertEqual(ops.canonical_json(value).encode(),
                         b'{"v":[0.00001,0.000001,9.999999999999997e-7,-1e-7,5e-324,'
                         b'0,-9007199254740991,9007199254740990,9007199254740991,1.25,"1e-05",true]}')

    def test_unsafe_integers_are_not_hashable(self):
        # At magnitudes where two distinct integral inputs can round to the
        # same Worker Number, neither sink should issue a fact identity.
        for number in (2**53, 2**53 + 1, -2**53, float(2**53), 1e20, 1e21, 1e22, 10**100):
            with self.subTest(number=number), self.assertRaisesRegex(ops.OpError, "value_json: not JSON"):
                ops.validate_op(fact(field="sample", value_json={"v": [number]}), 0, "CA")

    def test_legacy_staging_ids_are_not_rewritten_on_reopen_or_retry(self):
        timestamp = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)
        op = fact(field="sample", value_json=1e-5)
        old_text = "1e-05"
        old_key = ops.sha256(old_text)[:16]
        old_id = ops.fact_id(op["vessel_id"], op["field"], op["source_id"], op["source_url"], old_key)
        new_id = ops.fact_id(op["vessel_id"], op["field"], op["source_id"], op["source_url"], ops.value_key(1e-5))
        self.assertNotEqual(new_id, old_id)
        with TemporaryDirectory() as scratch:
            def open_staging():
                return closing(SqliteSink(Path(scratch) / "staging.sqlite", "CA", "audit",
                                          root=ROOT, clock=lambda: timestamp))

            with open_staging() as sink:
                sink.apply([vessel()])
                sink.db.execute(
                    "INSERT INTO fleet_vessel_facts (id, vessel_id, field, value_json, value_key, source_id, source_url,"
                    " method, confidence, rights, retrieved_at, first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (old_id, op["vessel_id"], op["field"], old_text, old_key, op["source_id"], op["source_url"],
                     op["method"], op["confidence"], op["rights"], T0, T0, T0),
                )
                sink.apply([{"op": "review.open", "kind": "fact-conflict", "subject_id": old_id,
                             "proposal_json": {"fact_ids": [old_id]}, "fingerprint": "legacy", "opened_at": T0}])
            with open_staging() as sink:
                with self.assertRaisesRegex(SinkError, "id: does not match the derived id"):
                    sink.apply([{**op, "id": old_id}])
                self.assertEqual(sink.apply([{**op, "id": new_id}])["changed"], 1)
                self.assertEqual(sink.apply([{**op, "id": new_id}])["changed"], 0)
                self.assertEqual(sink.db.execute(
                    "SELECT value_json, value_key, superseded_by FROM fleet_vessel_facts WHERE id=?", (old_id,)
                ).fetchone(), (old_text, old_key, None))
                subject, proposal = sink.db.execute("SELECT subject_id, proposal_json FROM fleet_reviews").fetchone()
                self.assertEqual((subject, json.loads(proposal)), (old_id, {"fact_ids": [old_id]}))
