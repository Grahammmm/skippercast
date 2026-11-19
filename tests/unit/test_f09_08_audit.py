"""F09-08: only storable evidence can set a resolved profile field."""
from dataclasses import replace
import unittest

from skippercast.fleet import ops
from skippercast.fleet.adapters.base import Candidate, Fact
from skippercast.fleet.config import ResolverRule
from skippercast.fleet.resolve import ResolverConfig, Snapshot, resolve


class EvidenceAdmissibilityTest(unittest.TestCase):
    def test_unstorable_length_neither_wins_nor_supersedes(self):
        now = "2026-10-05T09:47:00Z"
        config = ResolverConfig("CA", {"length_ft": ResolverRule(("strong", "weak"), 0.6)}, 0.9, 0.6, {}, {})
        good = Fact("length_ft", 36, "weak", "https://registry.example.com/vessel", "page", 0.9, "facts-only", now)
        bad = replace(good, value=42, source_id="strong", source_url="")
        candidate = Candidate("weak", "Example Vessel", None, None, {"state_reg": "TEST-370"}, (), record_id="test")
        vessel_id = ops.vessel_id("CA", "reg:TEST-370")
        stored = {"id": vessel_id, "slug": "example-vessel", "name": candidate.name, "name_norm": "EXAMPLEVESSEL",
                  "state_reg": "TEST-370", "length_ft": 39, "first_seen_at": now,
                  "sources": [{"id": "a" * 32, "field": "length_ft", "source_id": "strong", "confidence": 0.9,
                               "retrieved_at": now}]}
        # The old resolver ranked invalid evidence before dropping its fact.upsert. It could also
        # discard a stored winner simply because the same source sent an invalid replacement.
        for label, snapshot, facts, extra, length, evidence in (
            ("unsupported new length", Snapshot(), (bad,), None, None, []),
            ("supported fallback", Snapshot(), (bad, good), None, 36, [good]),
            ("valid control", Snapshot(), (good,), None, 36, [good]),
            ("stored winner", Snapshot([stored]), (good,), {vessel_id: [bad]}, None, [good]),
        ):
            with self.subTest(label=label):
                result = resolve(snapshot, [replace(candidate, facts=facts)], config, now, extra_facts=extra)
                vessel, = (op for op in result.ops if op["op"] == "vessel.upsert")
                if length is None:
                    self.assertNotIn("length_ft", vessel)
                else:
                    self.assertEqual(vessel["length_ft"], length)
                fact_ops = [op for op in result.ops if op["op"] == "fact.upsert"]
                self.assertEqual([(op["vessel_id"], op["field"], op["value_json"], op["source_id"], op["source_url"])
                                  for op in fact_ops],
                                 [(vessel["id"], f.field, f.value, f.source_id, f.source_url) for f in evidence])
                self.assertEqual(ops.validate_ops(result.ops, config.region)[1], [])
