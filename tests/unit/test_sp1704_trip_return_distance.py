"""SP1704-TRIP-RETURN-DISTANCE (spec SP-17-v1): a confirmed closed trip counts its observed return leg.

``segment.split_trips`` closes a trip at the first fix of a held stay in port (the
return fix). ``Trip.positions`` stop before that fix by design, but the trip's
``distance_nm`` must still cover the observed sea-to-port leg that ends there.
Open, truncated and debounced trips keep their recorded-positions distance.

Every track is synthetic (``tests/fixtures/sp1704_trip_return_distance``): a
made-up MMSI between square harbor geofences drawn in open ocean. Thresholds
are the committed ``regions/CA/fleet.json`` values, read through the real
``ActivityThresholds``; trips come from the real ``split_trips`` and
``classify_trip``. ``expected.json`` pins the values the unchanged staged base
produced for every field the repair must not move.

The module anchors ``sys.path`` to this checkout before importing product code
and refuses a ``skippercast`` package imported from anywhere else.
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO), str(_REPO / 'src')):
    while _entry in sys.path:
        sys.path.remove(_entry)
    sys.path.insert(0, _entry)  # final order: <repo>/src, <repo>, ...


def _inside(module, root):
    origin = getattr(module, '__file__', None)
    return bool(origin) and Path(origin).resolve().is_relative_to(root)


if 'skippercast' in sys.modules and not _inside(sys.modules['skippercast'], _REPO / 'src'):
    raise ImportError(f"skippercast already imported from outside this checkout: {sys.modules['skippercast'].__file__}")

from dataclasses import fields, replace  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import unittest  # noqa: E402

import skippercast  # noqa: E402
from skippercast.fleet.ais.classify import classify_trip  # noqa: E402
from skippercast.fleet.ais.segment import ActivityThresholds, distance_nm, split_trips  # noqa: E402
from skippercast.fleet.ais.sources.base import AisPosition  # noqa: E402
from skippercast.fleet.config import Port  # noqa: E402
from tests._support import FIXTURES, ROOT  # noqa: E402

if not _inside(skippercast, _REPO / 'src') or ROOT != _REPO:
    raise ImportError(f'product or test support imported from outside {_REPO}: {skippercast.__file__}, {ROOT}')

FIXTURE_DIR = FIXTURES / 'sp1704_trip_return_distance'
DATA = json.loads((FIXTURE_DIR / 'tracks.json').read_text(encoding='utf-8'))
EXPECTED = json.loads((FIXTURE_DIR / 'expected.json').read_text(encoding='utf-8'))
MIN = 60_000
T0 = DATA['t0_ms']
TH = ActivityThresholds.from_mapping(
    json.loads((ROOT / 'regions' / 'CA' / 'fleet.json').read_text(encoding='utf-8'))['thresholds'])
# The open track again, judged later than six-pack's max_open_trip_hours: truncated by age.
AGED = dict(vessel_class='six-pack', now_ms=T0 + 30 * 3_600_000)


def _square(lat, lon, half):
    s, n, w, e = lat - half, lat + half, lon - half, lon + half
    return ((w, s), (e, s), (e, n), (w, n), (w, s))


PORTS = tuple(Port(p['id'], p['name'], tuple(p['center']), None, None, ('ocean',),
                   _square(p['center'][0], p['center'][1], p['half_deg']), 'drawn') for p in DATA['ports'])


def _fix(row):
    minute, lat, lon, sog = row[:4]
    delay = row[4] if len(row) > 4 else DATA['receipt_delay_ms']
    ts = T0 + minute * MIN
    return AisPosition(DATA['mmsi'], ts, lat, lon, sog, None, None, None, 'PositionReport', 'synthetic', ts + delay)


def positions(track):
    return [_fix(row) for row in DATA['tracks'][track]['fixes']]


def at(track, minutes):
    """The fixture fixes of ``track`` at these minutes, in order."""
    by_minute = {row[0]: _fix(row) for row in DATA['tracks'][track]['fixes']}
    return [by_minute[m] for m in minutes]


def legs_nm(fixes):
    """Sum of the observed great-circle legs between consecutive fixes, at the trip's six-decimal precision."""
    return round(sum(distance_nm(a.lat, a.lon, b.lat, b.lon) for a, b in zip(fixes, fixes[1:])), 6)


def trips(track, **kwargs):
    return split_trips(positions(track), PORTS, TH, **kwargs)


def only(track, **kwargs):
    found = trips(track, **kwargs)
    if len(found) != 1:
        raise AssertionError(f'{track}: expected exactly one trip, got {len(found)}')
    return found[0]


def minutes(trip):
    return [(p.ts - T0) // MIN for p in trip.positions]


def scenarios():
    """(name, trip) for every pinned scenario."""
    out = [(name, only(name)) for name in DATA['tracks']]
    out.append(('open_aged', only('open', **AGED)))
    return out


def segment_summary(classification):
    return [[s.kind, (s.started_at - T0) // MIN, (s.ended_at - T0) // MIN, len(s.positions)]
            for s in classification.segments]


class BaselineTests(unittest.TestCase):
    # The frozen diagnostic pair: red on the unchanged base, green after the repair.

    def test_primary_regression(self):
        # A1: a confirmed closed trip's distance runs departure fix -> ... -> confirmed return fix.
        trip = only('closed')
        self.assertEqual(trip.status, 'closed')
        self.assertEqual(trip.return_port_id, 'port-a')
        observed = legs_nm(at('closed', [20, 50, 80, 100]))
        print('SP1704_OBSERVATION ' + json.dumps({'track': 'closed', 'status': trip.status,
                                                  'distance_nm': trip.distance_nm, 'observed_legs_nm': observed,
                                                  'positions_min': minutes(trip)}, sort_keys=True))
        self.assertEqual(trip.distance_nm, observed,
                         f'SP1704_RETURN_LEG_OMITTED closed trip reports {trip.distance_nm} nm, '
                         f'observed departure-to-return legs total {observed} nm')

    def test_healthy_control(self):
        # The matching open track: unchanged observed distance and unchanged positions.
        trip = only('open')
        self.assertEqual(trip.status, 'open')
        self.assertIsNone(trip.return_port_id)
        self.assertEqual(list(trip.positions), at('open', [20, 50, 80]))
        self.assertEqual(trip.distance_nm, legs_nm(at('open', [20, 50, 80])))
        self.assertEqual(trip.distance_nm, EXPECTED['open']['distance_nm'])
        print('SP1704_CONTROL ' + json.dumps({'track': 'open', 'distance_nm': trip.distance_nm,
                                              'positions_min': minutes(trip)}, sort_keys=True))


class ClosedReturnLegTests(unittest.TestCase):
    # A1 beyond the primary track.

    def test_a1_return_into_another_port(self):
        trip = only('closed_to_port_b')
        self.assertEqual((trip.status, trip.depart_port_id, trip.return_port_id), ('closed', 'port-a', 'port-b'))
        self.assertEqual(minutes(trip), [20, 50, 80])
        self.assertEqual(trip.distance_nm, legs_nm(at('closed_to_port_b', [20, 50, 80, 95])))

    def test_a1_return_leg_counted_once(self):
        closed, open_ = only('closed'), only('open')
        a, b = at('closed', [80, 100])
        leg = distance_nm(a.lat, a.lon, b.lat, b.lon)
        self.assertGreater(leg, 1.0)  # the fixture's return leg is long enough to see
        self.assertAlmostEqual(closed.distance_nm - open_.distance_nm, leg, delta=2e-6)

    def test_a1_harbor_fixes_after_return_not_counted(self):
        trip = only('closed')
        with_harbor = legs_nm(at('closed', [20, 50, 80, 100, 110, 120]))
        self.assertGreater(with_harbor - trip.distance_nm, 0.1)  # the fixture would expose them
        self.assertEqual(trip.distance_nm, legs_nm(at('closed', [20, 50, 80, 100])))


class OpenAndTruncationTests(unittest.TestCase):
    # A2: open and truncated trips keep the sum of their recorded legs.

    def test_a2_zero_length_final_leg_adds_zero(self):
        trip = only('open_zero_final')
        self.assertEqual(trip.status, 'open')
        self.assertEqual(minutes(trip), [20, 50, 80, 90])
        self.assertEqual(trip.distance_nm, only('open').distance_nm)
        self.assertEqual(trip.distance_nm, legs_nm(at('open_zero_final', [20, 50, 80, 90])))

    def test_a2_gap_truncation_unchanged(self):
        trip = only('gap_truncated')
        self.assertEqual((trip.status, trip.return_port_id), ('truncated', None))
        self.assertEqual(trip.returned_at, T0 + 50 * MIN)
        self.assertEqual(trip.distance_nm, legs_nm(at('gap_truncated', [20, 50])))
        self.assertEqual(trip.distance_nm, EXPECTED['gap_truncated']['distance_nm'])

    def test_a2_open_age_truncation_unchanged(self):
        trip = only('open', **AGED)
        self.assertEqual(trip.status, 'truncated')
        self.assertEqual(trip.distance_nm, only('open').distance_nm)
        self.assertEqual(trip.distance_nm, EXPECTED['open_aged']['distance_nm'])

    def test_a2_unknown_start_truncation_unchanged(self):
        trip = only('start_unknown')
        self.assertEqual((trip.status, trip.depart_port_id, trip.return_port_id), ('truncated', None, 'port-a'))
        self.assertEqual(trip.distance_nm, legs_nm(at('start_unknown', [0, 30])))
        self.assertEqual(trip.distance_nm, EXPECTED['start_unknown']['distance_nm'])


class ReturnConfirmationTests(unittest.TestCase):
    # A3: only a confirmed return adds a return leg; debounce and filters keep their outcomes.

    def test_a3_in_port_hint_is_not_a_return(self):
        trip = only('open_port_hint')
        self.assertEqual((trip.status, trip.return_port_id), ('open', None))
        self.assertEqual(trip.returned_at, T0 + 101 * MIN)
        self.assertEqual(minutes(trip), [20, 50, 80, 100, 101])
        self.assertEqual(trip.distance_nm, legs_nm(at('open_port_hint', [20, 50, 80, 100, 101])))
        self.assertEqual(trip.distance_nm, EXPECTED['open_port_hint']['distance_nm'])

    def test_a3_short_dip_is_debounced(self):
        trip = only('closed_with_dip')
        self.assertEqual((trip.status, trip.return_port_id), ('closed', 'port-a'))
        self.assertEqual(minutes(trip), [20, 50, 60, 61, 80])
        self.assertEqual(trip.returned_at, T0 + 100 * MIN)
        self.assertEqual(trip.distance_nm, legs_nm(at('closed_with_dip', [20, 50, 60, 61, 80, 100])))

    def test_a3_order_and_replayed_duplicates_do_not_matter(self):
        noise = [_fix(row) for row in DATA['noise']['duplicates']]
        rng = random.Random(17040)
        for track in DATA['tracks']:
            clean = trips(track)
            rows = positions(track)
            variants = [list(reversed(rows)), rows + noise if track == 'closed' else rows]
            for _ in range(3):
                shuffled = list(rows)
                rng.shuffle(shuffled)
                variants.append(shuffled)
            for k, variant in enumerate(variants):
                with self.subTest(track=track, variant=k):
                    self.assertEqual(split_trips(variant, PORTS, TH), clean)
        closed_noisy = list(reversed(positions('closed') + noise))
        self.assertEqual(split_trips(closed_noisy, PORTS, TH), trips('closed'))


class EquivalenceTests(unittest.TestCase):
    # A4: everything but the corrected closed-trip distance matches the unchanged base.

    def test_a4_every_other_trip_field_matches_base(self):
        names = [f.name for f in fields(scenarios()[0][1]) if f.name not in ('distance_nm', 'positions')]
        self.assertEqual(sorted(k for k in EXPECTED if not k.startswith('_')), sorted(name for name, _ in scenarios()))
        for name, trip in scenarios():
            pinned = EXPECTED[name]
            with self.subTest(scenario=name):
                actual = {f: getattr(trip, f) for f in names}
                actual['departed_at'] = (trip.departed_at - T0) // MIN
                actual['returned_at'] = (trip.returned_at - T0) // MIN
                self.assertEqual(actual, pinned['fields'])
                self.assertEqual(minutes(trip), pinned['positions_min'])
                track = 'open' if name == 'open_aged' else name
                self.assertEqual(list(trip.positions), at(track, pinned['positions_min']))

    def test_a4_only_closed_distance_changes(self):
        for name, trip in scenarios():
            pinned = EXPECTED[name]
            with self.subTest(scenario=name):
                if trip.status != 'closed':
                    self.assertEqual(trip.distance_nm, pinned['distance_nm'])
                    continue
                track = DATA['tracks'][name]['fixes']
                last = trip.positions[-1]
                ret = next(_fix(row) for row in track if T0 + row[0] * MIN == trip.returned_at)
                leg = distance_nm(last.lat, last.lon, ret.lat, ret.lon)
                self.assertAlmostEqual(trip.distance_nm, pinned['distance_nm'] + leg, delta=2e-6)

    def test_a4_classifier_segmentation_unchanged(self):
        for name, trip in scenarios():
            pinned = EXPECTED[name]
            with self.subTest(scenario=name):
                result = classify_trip(trip, PORTS, TH)
                legacy = classify_trip(replace(trip, distance_nm=pinned['distance_nm']), PORTS, TH)
                self.assertEqual(segment_summary(result), pinned['segments'])
                self.assertEqual(result.segments, legacy.segments)
                self.assertEqual(result.classifier_version, pinned['classifier_version'])

    def test_a4_no_pre_departure_harbor_travel(self):
        trip = only('closed')
        self.assertEqual(trip.departed_at, T0 + 20 * MIN)
        harbor = legs_nm(at('closed', [0, 10, 20, 50, 80, 100]))
        self.assertGreater(harbor - trip.distance_nm, 0.1)
        self.assertEqual(trip.distance_nm, legs_nm(at('closed', [20, 50, 80, 100])))


if __name__ == '__main__':
    unittest.main()
