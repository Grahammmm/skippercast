"""SP75: producer-shaped synthetic inputs through the complete actual factory."""
import copy
import hashlib
import json
import unittest
from types import MappingProxyType

from skippercast.fleet.ais.aggregate.base import AggregateParams
from tests._support import FIXTURES

FIXTURE = FIXTURES / "sp75_aggregate_finite/healthy.json"
HEALTHY = json.loads(FIXTURE.read_text(encoding="utf-8"))["aggregate"]
NONFINITE = (float("nan"), float("inf"), float("-inf"))
HEALTHY_JSON = '{"delay_hours":24,"min_distinct_vessels":2,"module":"grid","resolution_m":1000}'


class AggregateFiniteTests(unittest.TestCase):
    def assert_field_error(self, data, field):
        with self.assertRaises(ValueError) as error:
            AggregateParams.from_mapping(data)
        self.assertIn(field, str(error.exception))

    def test_A1_nonfinite_declared_numbers(self):
        for field in ("delay_hours", "resolution_m", "min_distinct_vessels"):
            for value in NONFINITE:
                with self.subTest(field=field, value=value):
                    self.assert_field_error(dict(HEALTHY, **{field: value}), field)

    def test_A1_types_and_integer_fraction(self):
        for field in ("delay_hours", "resolution_m", "min_distinct_vessels"):
            for value in (True, False, "24", [], {}):
                with self.subTest(field=field, value=value):
                    self.assert_field_error(dict(HEALTHY, **{field: value}), field)
        self.assert_field_error(dict(HEALTHY, min_distinct_vessels=1.5), "min_distinct_vessels")

    def test_A2_nonfinite_kind_edges_with_null_or_finite_base(self):
        for kind in ("drift-anchor", "troll-slow", "troll-pelagic"):
            for value in NONFINITE:
                for base in (None, 1000):
                    with self.subTest(kind=kind, value=value, base=base):
                        self.assert_field_error(dict(HEALTHY, resolution_m=base,
                                                     resolution_by_kind={kind: value}),
                                                "resolution_by_kind." + kind)

    def test_A2_nested_nonfinite_extensions(self):
        for value in NONFINITE:
            for extension in (value, [value], {"nested": [1, {"bad": value}]}, (1, value)):
                with self.subTest(extension=extension):
                    self.assert_field_error(dict(HEALTHY, extension=extension), "extension")

    def test_A2_null_limits_and_kind_edges(self):
        data = dict(HEALTHY, resolution_m=None, delay_hours=None, min_distinct_vessels=None,
                    resolution_by_kind={"troll-slow": 1.5})
        params = AggregateParams.from_mapping(data)
        self.assertIsNone(params.resolution_m)
        self.assertIsNone(params.delay_hours)
        self.assertIsNone(params.min_distinct_vessels)
        self.assertEqual(params.resolution_for("troll-slow"), 1.5)
        self.assertIsNone(params.resolution_for("drift-anchor"))
        self.assertEqual(json.loads(params.params_json), data)

    def test_A2_kind_type_and_kind_rules(self):
        for value in (True, "1000", None, 0, -1):
            with self.subTest(value=value):
                self.assert_field_error(dict(HEALTHY, resolution_by_kind={"troll-slow": value}),
                                        "resolution_by_kind.troll-slow")
        self.assert_field_error(dict(HEALTHY, resolution_by_kind={"transit": 1000}), "transit")
        self.assert_field_error(dict(HEALTHY, resolution_by_kind=[1000]), "resolution_by_kind")

    def test_A3_minimum_boundaries_and_valid_fractions(self):
        for field, lower, boundary in (("resolution_m", 0.999, 1),
                                       ("delay_hours", -0.001, 0),
                                       ("min_distinct_vessels", 0, 1)):
            with self.subTest(field=field):
                self.assert_field_error(dict(HEALTHY, **{field: lower}), field)
                params = AggregateParams.from_mapping(dict(HEALTHY, **{field: boundary}))
                self.assertEqual(getattr(params, field), boundary)
        params = AggregateParams.from_mapping(dict(HEALTHY, resolution_m=1.5, delay_hours=0.25,
                                                   min_distinct_vessels=2.0))
        self.assertEqual((params.resolution_m, params.delay_hours, params.min_distinct_vessels),
                         (1.5, 0.25, 2))

    def test_A3_exact_multiples(self):
        for base, edge in ((1000, 1000), (1000, 2000), (1000, 3000), (1.5, 4.5)):
            params = AggregateParams.from_mapping(dict(HEALTHY, resolution_m=base,
                                                       resolution_by_kind={"troll-slow": edge}))
            self.assertEqual(params.resolution_for("troll-slow"), edge)
        for edge in (999, 1500):
            self.assert_field_error(dict(HEALTHY, resolution_by_kind={"troll-slow": edge}),
                                    "resolution_by_kind.troll-slow")

    def test_A3_canonical_hash_and_input_immutability(self):
        original = dict(HEALTHY, extension={"nested": [1, {"ok": True}], "name": "synthetic"})
        frozen = copy.deepcopy(original)
        expected = '{"delay_hours":24,"extension":{"name":"synthetic","nested":[1,{"ok":true}]},"min_distinct_vessels":2,"module":"grid","resolution_m":1000}'
        for data in (original, dict(reversed(list(original.items()))), {"aggregate": original},
                     MappingProxyType({"aggregate": MappingProxyType(original)})):
            params = AggregateParams.from_mapping(data)
            self.assertEqual(params.params_json, expected)
            self.assertEqual(params.params_hash, hashlib.sha256(expected.encode()).hexdigest()[:16])
        self.assertEqual(original, frozen)
        self.assertIsNot(AggregateParams.from_mapping(original).raw, original)

    def test_A4_primary_nan_delay(self):
        # Capture the outcome before asserting: product exceptions are data, not harness errors.
        try:
            returned = AggregateParams.from_mapping(dict(HEALTHY, delay_hours=float("nan")))
            outcome = {"kind": "returned", "params_json": returned.params_json}
        except Exception as error:
            outcome = {"kind": "exception", "type": type(error).__name__, "message": str(error)}
        print("SP75_PRIMARY_OUTCOME=" + json.dumps(outcome, sort_keys=True))
        self.assertEqual(outcome["kind"], "exception", "SP75_PRIMARY_NAN_ACCEPTED")
        self.assertEqual(outcome["type"], "ValueError")
        self.assertIn("delay_hours", outcome["message"])

    def test_A4_healthy_control(self):
        # Also freeze finite compatibility against unmodified product in the two-case baseline.
        params = AggregateParams.from_mapping(dict(HEALTHY))
        self.assertEqual(params.params_json, HEALTHY_JSON)
        self.assertEqual((params.resolution_m, params.delay_hours, params.min_distinct_vessels),
                         (1000, 24, 2))
        self.assertEqual(params.params_hash, hashlib.sha256(HEALTHY_JSON.encode()).hexdigest()[:16])
        self.test_A2_null_limits_and_kind_edges()
        self.test_A3_minimum_boundaries_and_valid_fractions()
        self.test_A3_exact_multiples()
        self.test_A3_canonical_hash_and_input_immutability()


if __name__ == "__main__":
    unittest.main()
