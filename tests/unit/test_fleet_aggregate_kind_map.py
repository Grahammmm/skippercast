"""RF0721-5: an explicit ``resolution_by_kind`` must be an object, even when its value is falsy."""
import copy
import hashlib
import json
import unittest
from types import MappingProxyType

from skippercast.fleet.ais.aggregate.base import AggregateParams

BASE = {"module": "grid", "resolution_m": 1000, "min_distinct_vessels": 2, "delay_hours": 24}
MESSAGE = "thresholds.aggregate.resolution_by_kind must be an object"
FALSY = ([], "", False, 0, 0.0, None)
TRUTHY = ([3000], "grid", True, 1)


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class ResolutionByKindAdmissionTests(unittest.TestCase):
    def assert_refused(self, value):
        for form in ("direct", "wrapped"):
            data = dict(BASE, resolution_by_kind=value)
            with self.subTest(value=value, form=form):
                with self.assertRaises(ValueError) as error:
                    AggregateParams.from_mapping(data if form == "direct" else {"aggregate": data})
                self.assertEqual(str(error.exception), MESSAGE)

    def test_falsy_present_nonobjects_refuse(self):
        for value in FALSY:
            self.assert_refused(value)

    def test_nonempty_wrong_types_stay_refused(self):
        for value in TRUTHY:
            self.assert_refused(value)

    def test_omitted_map_retains_legacy_bytes(self):
        original = copy.deepcopy(BASE)
        for form in (BASE, {"aggregate": BASE}, MappingProxyType(BASE)):
            params = AggregateParams.from_mapping(form)
            self.assertEqual(dict(params.resolution_by_kind), {})
            self.assertEqual(params.resolution_for("troll-slow"), 1000)
            self.assertEqual(params.params_json,
                             '{"delay_hours":24,"min_distinct_vessels":2,"module":"grid","resolution_m":1000}')
            self.assertEqual(params.params_hash, digest(canonical(original)))
        self.assertEqual(BASE, original)

    def test_empty_object_is_explicit_valid_configuration(self):
        data = dict(BASE, resolution_by_kind={})
        params = AggregateParams.from_mapping({"aggregate": data})
        self.assertEqual(dict(params.resolution_by_kind), {})
        self.assertEqual(params.resolution_for("troll-slow"), 1000)
        self.assertIn('"resolution_by_kind":{}', params.params_json)
        self.assertEqual(params.params_hash, digest(canonical(data)))
        self.assertNotEqual(params.params_hash, AggregateParams.from_mapping(BASE).params_hash)

    def test_valid_kind_overrides_and_wrappers_unchanged(self):
        cases = (dict(BASE, resolution_by_kind={"troll-slow": 3000, "drift-anchor": 1000}),
                 dict(BASE, resolution_m=None, resolution_by_kind={"troll-slow": 1.5}))
        for data in cases:
            original = copy.deepcopy(data)
            for form in (data, {"aggregate": data}, MappingProxyType(data)):
                with self.subTest(data=data, form=type(form).__name__):
                    params = AggregateParams.from_mapping(form)
                    self.assertEqual(params.params_json, canonical(original))
                    self.assertEqual(params.params_hash, digest(canonical(original)))
                    self.assertEqual(params.resolution_for("troll-slow"), original["resolution_by_kind"]["troll-slow"])
            self.assertEqual(data, original)
        params = AggregateParams.from_mapping(cases[0])
        self.assertEqual(params.resolution_for("troll-pelagic"), 1000)

    def test_existing_field_refusals_are_not_weakened(self):
        cases = ({"transit": 1000}, {"troll-slow": 1500}, {"troll-slow": True}, {"troll-slow": 0},
                 {"troll-slow": -1000}, {"troll-slow": float("nan")}, {"troll-slow": float("inf")})
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    AggregateParams.from_mapping(dict(BASE, resolution_by_kind=value))


if __name__ == "__main__":
    unittest.main()
