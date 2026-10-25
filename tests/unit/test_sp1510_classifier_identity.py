"""SP-15-v1 A1-A4: synthetic public API tests; no live source/store access."""
from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
import unittest

from scripts.accept_sp1510_classifier_identity import offline_boundary

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/fixtures/sp1510_classifier_identity/synthetic.json'


def reordered(value):
    if isinstance(value, dict):
        return {key: reordered(value[key]) for key in reversed(list(value))}
    return value


class ClassifierIdentityTest(unittest.TestCase):
    def setUp(self):
        self.boundary = offline_boundary(ROOT)
        self.boundary.__enter__()
        self.addCleanup(self.boundary.__exit__, None, None, None)
        from skippercast.fleet.ais import classify
        from skippercast.fleet.ais.events import segment_geometry
        from skippercast.fleet.ais.segment import ActivityThresholds, Trip
        from skippercast.fleet.ais.sources.base import AisPosition
        self.classify = classify
        self.geometry = segment_geometry
        self.Thresholds = ActivityThresholds
        self.fixture = json.loads(FIXTURE.read_text())
        self.th = ActivityThresholds.from_mapping(self.fixture['activity'])
        p = AisPosition(**self.fixture['position'])
        rows = tuple(replace(p, ts=p.ts + k * self.fixture['interval_ms'],
                             received_at=p.received_at + k * self.fixture['interval_ms'])
                     for k in range(self.fixture['count']))
        self.trip = Trip(p.mmsi, None, None, rows[0].ts, rows[-1].ts, 'truncated', rows, 0.0, 0.0)

    def result(self, th=None):
        return self.classify.classify_trip(self.trip, (), self.th if th is None else th)

    def test_primary_regression(self):
        """A1: same raw, different effective threshold/labels must have different IDs."""
        changed = replace(self.th, drift_max_sog_kn=0.5)
        original, other = self.result(), self.result(changed)
        self.assertEqual(changed.raw, self.th.raw)
        self.assertEqual([s.kind for s in original.segments], ['drift-anchor'])
        self.assertEqual([s.kind for s in other.segments], ['uncertain'])
        print(json.dumps({'observation': 'A1', 'original': original.classifier_version,
                          'changed': other.classifier_version, 'labels': ['drift-anchor', 'uncertain']}))
        self.assertNotEqual(original.classifier_version, other.classifier_version,
                            'A1_FINGERPRINT_COLLISION')

    def test_healthy_control(self):
        """Same threshold object yields identical full segments and version."""
        first = self.result()
        self.assertEqual(first, self.result())
        self.assertEqual(first.classifier_version, self.classify.classifier_version(self.th))
        self.assertRegex(first.classifier_version, r'^c\d+-[0-9a-f]{16}$')

    def test_a2_key_order_and_repeat(self):
        other = self.Thresholds.from_mapping(reordered(self.fixture['activity']))
        self.assertEqual(self.result(), self.result(other))
        other = replace(other, max_open_trip_hours=dict(reversed(list(other.max_open_trip_hours.items()))))
        self.assertEqual(self.result(), self.result(other))
        self.assertEqual(self.result().classifier_version.encode(), self.result(other).classifier_version.encode())

    def test_a3_every_effective_typed_field(self):
        base = self.result().classifier_version
        seen = {base}
        for field in fields(self.th):
            if field.name == 'raw':
                continue
            value = getattr(self.th, field.name)
            changes = ({key: {**value, key: number + 1} for key, number in value.items()}
                       if isinstance(value, dict) else {field.name: value + 0.125})
            for key, changed in changes.items():
                with self.subTest(field=field.name, entry=key):
                    other = replace(self.th, **{field.name: changed})
                    self.assertEqual(other.raw, self.th.raw)
                    version = self.result(other).classifier_version
                    self.assertNotIn(version, seen)
                    seen.add(version)

    def test_a3_complete_raw_auxiliary_mapping(self):
        base = self.result()
        paths = [('simplify_tolerance_m',), ('future_auxiliary',), ('drift', 'future_auxiliary')]
        for path in paths:
            with self.subTest(path=path):
                raw = json.loads(json.dumps(self.th.raw))
                node = raw
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = node.get(path[-1], 0) + 1
                other = self.result(replace(self.th, raw=raw))
                self.assertNotEqual(base.classifier_version, other.classifier_version)
                self.assertEqual(base.segments, other.segments)

    def test_a4_original_labels_geometry_and_statistics(self):
        result = self.result()
        expected = self.fixture['expected']
        self.assertEqual(len(result.segments), 1)
        (seg,) = result.segments
        self.assertEqual(seg.kind, expected['kind'])
        self.assertEqual(seg.positions, self.trip.positions)
        self.assertEqual((seg.seq, seg.started_at, seg.ended_at),
                         (0, self.trip.departed_at, self.trip.returned_at))
        for name in ('mean_sog', 'straightness', 'heading_var', 'p90_sog', 'distance_nm'):
            self.assertEqual(getattr(seg, name), expected[name], name)
        self.assertEqual(self.geometry(seg, self.th.raw['simplify_tolerance_m']), expected['geometry'])
        self.assertEqual(result.basis, 'inferred-from-movement')
        self.assertEqual(seg.basis, result.basis)
        # The typed threshold changes the label, not the source points/geometry/statistics.
        (other,) = self.result(replace(self.th, drift_max_sog_kn=0.5)).segments
        self.assertEqual(other, replace(seg, kind=expected['changed_kind']))
        self.assertEqual(self.geometry(other, 25), expected['geometry'])

    def test_canonical_payload_and_algorithm_bump(self):
        self.assertEqual(self.classify.ALGORITHM_VERSION, 3)
        effective = {f.name: getattr(self.th, f.name) for f in fields(self.th) if f.name != 'raw'}
        body = json.dumps({'algorithm': 3, 'activity': self.th.raw, 'effective': effective},
                          sort_keys=True, separators=(',', ':'))
        expected = 'c3-' + hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]
        self.assertEqual(self.result().classifier_version, expected)
        from unittest.mock import patch
        with patch.object(self.classify, 'ALGORITHM_VERSION', 4):
            self.assertNotEqual(self.result().classifier_version, expected)

    def test_mapping_protocol_not_only_mutable_dict(self):
        def freeze(value):
            if isinstance(value, dict):
                return MappingProxyType({key: freeze(item) for key, item in value.items()})
            return value
        other = replace(self.th, raw=freeze(self.th.raw), max_open_trip_hours=freeze(self.th.max_open_trip_hours))
        self.assertEqual(self.result(), self.result(other))


if __name__ == '__main__':
    unittest.main()
