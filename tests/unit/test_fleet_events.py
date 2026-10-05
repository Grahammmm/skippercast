"""skippercast.fleet.ais events, simplify and aggregate (CF-44).

Tracks are synthetic: a made-up MMSI (999xxxxxx) off two square harbor
geofences drawn in open ocean (the CF-43 fixtures). Vessel ids, trip ids and
rights tags are made up. Thresholds come from the committed
``regions/CA/fleet.json``.
"""
from dataclasses import replace
import math
import random
import unittest

from skippercast.fleet.ais import events as ev
from skippercast.fleet.ais.aggregate import AggregateParams, compute, grid_cell, module, most_restrictive
from skippercast.fleet.ais.classify import Classification, Segment, classify_trip
from skippercast.fleet.ais.events import Event, TripContext, build_events, segment_geometry, simplify_tolerance_m
from skippercast.fleet.ais.segment import BASIS, distance_nm, split_trips
from skippercast.fleet.ais.simplify import decode_polyline, encode_polyline, simplify
from skippercast.fleet.ais.sources.base import AisPosition
from tests.unit.test_fleet_classify import MIN, MMSI, PORT_A, PORTS, T0, TH, fishing_trip, region_thresholds

HOUR = 60 * MIN


def ctx(**over):
    base = dict(trip_id='t' * 32, vessel_id='v-sea-example', region='CA', source='aisstream', rights='internal-only',
                season='2026', season_part='summer', port_id='port-a', vessel_class='six-pack', trip_type='half-day')
    base.update(over)
    return TripContext(**base)


def fix(t, lat, lon, sog=0.5):
    return AisPosition(MMSI, t, lat, lon, sog, 180.0, None, None, 'PositionReport', 'synthetic', t + 2_000)


def metres(a, b):
    return distance_nm(a[0], a[1], b[0], b[1]) * 1852.0


def event(vessel, lat, lon, *, kind='drift-anchor', part='summer', rights='internal-only', start=T0, dwell=30,
          season='2026', region='CA'):
    return Event(id=f'{vessel}-{start}', trip_id='trip', segment_id='seg', vessel_id=vessel, region=region, kind=kind,
                 lat=lat, lon=lon, radius_m=50.0, started_at=start, ended_at=start + dwell * MIN, dwell_min=dwell,
                 port_id='port-a', vessel_class='six-pack', trip_type=None, season=season, season_part=part,
                 source='aisstream', rights=rights, classifier_version='c1-0000000000000000')


def params(**over):
    raw = dict(region_thresholds()['aggregate'])
    raw.update(over)
    return AggregateParams.from_mapping(raw)


# ---------------------------------------------------------------- polylines

class PolylineTest(unittest.TestCase):
    def test_google_reference_vector(self):
        points = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
        self.assertEqual(encode_polyline(points), '_p~iF~ps|U_ulLnnqC_mqNvxq`@')
        self.assertEqual(decode_polyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@'), points)

    def test_round_trip_within_precision(self):
        rng = random.Random(44)
        points = [(rng.uniform(-80, 80), rng.uniform(-179.9, 179.9)) for _ in range(500)]
        decoded = decode_polyline(encode_polyline(points))
        self.assertEqual(len(decoded), len(points))
        for (a, b), (c, d) in zip(points, decoded):
            self.assertLessEqual(abs(a - c), 0.5e-5 + 1e-12)
            self.assertLessEqual(abs(b - d), 0.5e-5 + 1e-12)

    def test_rounds_halves_up_like_javascript(self):
        # Math.round(-0.5) is -0 and Math.round(0.5) is 1; Python's round() would give 0 for both.
        self.assertEqual(decode_polyline(encode_polyline([(0.000005, -0.000005)])), [(1e-05, 0.0)])

    def test_malformed_decodes_to_nothing(self):
        self.assertEqual(decode_polyline('_p~iF'), [])
        self.assertEqual(decode_polyline(' \u0000'), [])
        self.assertEqual(decode_polyline(''), [])


class SimplifyTest(unittest.TestCase):
    def test_every_dropped_point_stays_within_tolerance(self):
        trips = split_trips(fishing_trip(lambda t: t.zigzag(90)), PORTS, TH, vessel_class='six-pack')
        result = classify_trip(trips[0], PORTS, TH)
        tolerance = simplify_tolerance_m(TH)
        self.assertEqual(tolerance, region_thresholds()['activity']['simplify_tolerance_m'])
        for segment in result.segments:
            raw = [(p.lat, p.lon) for p in segment.positions]
            geometry = segment_geometry(segment, tolerance)
            if segment.kind == 'gap':
                self.assertIsNone(geometry)
                continue
            line = decode_polyline(geometry)
            self.assertLessEqual(len(line), len(raw))
            self.assertAlmostEqual(line[0][0], raw[0][0], places=5)
            self.assertAlmostEqual(line[-1][1], raw[-1][1], places=5)
            for point in raw:
                # Within the DP tolerance plus the encoding's rounding (< 1.2 m at 1e-5 degrees).
                self.assertLessEqual(_distance_to_line(point, line), tolerance + 1.5)

    def test_straight_line_collapses_and_corner_survives(self):
        straight = [(10.0 + k * 0.001, -149.9) for k in range(50)]
        self.assertEqual(simplify(straight, 25), [straight[0], straight[-1]])
        corner = straight + [(10.049, -149.9 + k * 0.001) for k in range(1, 50)]
        kept = simplify(corner, 25)
        self.assertIn((10.049, -149.9), kept)
        self.assertEqual(len(kept), 3)
        zero = simplify(corner, 0)
        self.assertEqual((zero[0], zero[-1]), (corner[0], corner[-1]))
        self.assertIn((10.049, -149.9), zero)

    def test_degenerate_inputs(self):
        self.assertEqual(simplify([], 25), [])
        self.assertEqual(simplify([(1.0, 2.0)], 25), [(1.0, 2.0)])
        self.assertEqual(decode_polyline(encode_polyline([(1.0, 2.0)])), [(1.0, 2.0)])
        with self.assertRaises(ValueError):
            simplify([(0, 0), (1, 1), (2, 2)], -1)

    def test_long_track_does_not_recurse(self):
        rng = random.Random(7)
        points = [(10 + k * 1e-4, -150 + rng.uniform(-1e-3, 1e-3)) for k in range(20_000)]
        self.assertGreater(len(simplify(points, 1)), 2)


def _distance_to_line(point, line):
    if len(line) == 1:
        return metres(point, line[0])
    kx = 111_320.0 * math.cos(math.radians(point[0]))
    px, py = 0.0, 0.0
    best = math.inf
    for a, b in zip(line, line[1:]):
        ax, ay = (a[1] - point[1]) * kx, (a[0] - point[0]) * 111_320.0
        bx, by = (b[1] - point[1]) * kx, (b[0] - point[0]) * 111_320.0
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
        best = min(best, math.hypot(ax + t * dx - px, ay + t * dy - py))
    return best


# ---------------------------------------------------------------- events

class EventTest(unittest.TestCase):
    def test_one_event_per_fishing_segment(self):
        def activity(t):
            t.drift(40)
            t.go_to(10.0, -149.8, 6.0)
            t.zigzag(40)
        trips = split_trips(fishing_trip(activity), PORTS, TH, vessel_class='six-pack')
        result = classify_trip(trips[0], PORTS, TH)
        events = build_events(result, PORTS, ctx())
        fishing = [s for s in result.segments if s.kind in ('fishing-drift', 'fishing-troll')]
        self.assertEqual([e.kind for e in events],
                         [{'fishing-drift': 'drift-anchor', 'fishing-troll': 'troll'}[s.kind] for s in fishing])
        self.assertIn('drift-anchor', [e.kind for e in events])
        self.assertIn('troll', [e.kind for e in events])
        for e, s in zip(events, fishing):
            self.assertEqual(e.basis, BASIS)
            self.assertEqual(e.basis, 'inferred-from-movement')
            self.assertEqual((e.started_at, e.ended_at), (s.started_at, s.ended_at))
            self.assertEqual(e.dwell_min, round(s.minutes))
            self.assertEqual(e.segment_id, ev.segment_id(e.trip_id, s.seq))
            self.assertEqual(e.id, ev.event_id(e.trip_id, s.started_at, e.kind))
            self.assertEqual(e.classifier_version, result.classifier_version)
            self.assertIsNone(e.species_json)
            self.assertEqual((e.rights, e.source, e.season, e.season_part), ('internal-only', 'aisstream', '2026', 'summer'))
            points = [(p.lat, p.lon) for p in s.positions]
            within = sum(metres((e.lat, e.lon), p) <= e.radius_m + 0.1 for p in points)
            self.assertGreaterEqual(within / len(points), 0.9)

    def test_median_and_p90_radius(self):
        positions = [fix(T0 + k * MIN, 10.0 + k * 1e-4, -149.85) for k in range(10)]
        segment = Segment(3, 'fishing-drift', T0, T0 + 30 * MIN, tuple(positions), 0.5, 0.2, 0.1)
        [e] = build_events(Classification(None, (segment,), 'c1-x'), PORTS, ctx())
        self.assertAlmostEqual(e.lat, 10.00045, places=6)
        self.assertAlmostEqual(e.lon, -149.85, places=6)
        distances = sorted(metres((10.00045, -149.85), (p.lat, p.lon)) for p in positions)
        self.assertAlmostEqual(e.radius_m, round(distances[8], 1), places=1)   # nearest rank: ceil(0.9 * 10) = 9th
        self.assertEqual(e.dwell_min, 30)
        self.assertEqual(e.kind, 'drift-anchor')

    def test_in_geofence_fixes_are_dropped(self):
        outside = [fix(T0 + k * MIN, 10.03 + k * 1e-5, -150.0) for k in range(10)]
        dip = [fix(T0 + (10 + k) * MIN, 10.0, -150.0) for k in range(8)]   # inside port A's geofence
        self.assertTrue(PORT_A.contains(10.0, -150.0))
        segment = Segment(0, 'fishing-troll', T0, T0 + 18 * MIN, tuple(outside + dip), 5.0, 0.4, 0.5)
        [e] = build_events(Classification(None, (segment,), 'c1-x'), PORTS, ctx())
        clean = ev.median_point([(p.lat, p.lon) for p in outside])
        self.assertEqual((e.lat, e.lon), (round(clean[0], 6), round(clean[1], 6)))
        self.assertFalse(PORT_A.contains(e.lat, e.lon))
        self.assertLess(e.radius_m, 20)
        self.assertEqual(e.kind, 'troll')
        # Only in-geofence fixes: no event at all.
        only_dip = replace(segment, positions=tuple(dip))
        self.assertEqual(build_events(Classification(None, (only_dip,), 'c1-x'), PORTS, ctx()), [])

    def test_non_fishing_segments_make_no_event(self):
        positions = (fix(T0, 10.03, -150.0, 6.0), fix(T0 + MIN, 10.04, -150.0, 6.0))
        segments = (Segment(0, 'transit', T0, T0 + MIN, positions, 6.0, 1.0, 0.0),
                    Segment(1, 'gap', T0 + MIN, T0 + 60 * MIN, (), None, None, None),
                    Segment(2, 'in-port', T0 + 60 * MIN, T0 + 61 * MIN, positions, 0.0, None, None))
        self.assertEqual(build_events(Classification(None, segments, 'c1-x'), PORTS, ctx()), [])

    def test_rows_round_trip(self):
        e = event('v1', 10.0, -149.9)
        row = e.as_row()
        self.assertRegex(row['started_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$')
        self.assertEqual(row['basis'], 'inferred-from-movement')
        self.assertEqual(Event.from_row(row), e)

    def test_ids_and_season(self):
        trip = ev.trip_id(MMSI, T0, 'aisstream')
        self.assertRegex(trip, r'^[0-9a-f]{32}$')
        self.assertNotEqual(trip, ev.trip_id(MMSI, T0, 'marinecadastre'))
        self.assertNotEqual(ev.segment_id(trip, 0), ev.segment_id(trip, 1))
        parts = {'winter': (12, 1, 2), 'spring': (3, 4, 5), 'summer': (6, 7, 8), 'fall': (9, 10, 11)}
        # 2026-07-01T05:00Z is still 30 June in Los Angeles.
        july_utc = ev.from_iso('2026-07-01T05:00:00Z')
        self.assertEqual(ev.season_of(july_utc, 'America/Los_Angeles', parts), ('2026', 'summer'))
        new_year = ev.from_iso('2027-01-01T07:00:00Z')
        self.assertEqual(ev.season_of(new_year, 'America/Los_Angeles', parts), ('2026', 'winter'))
        self.assertEqual(ev.iso_utc(ev.from_iso('2026-07-01T05:00:00.123Z')), '2026-07-01T05:00:00.123Z')


# ---------------------------------------------------------------- aggregates

class AggregateTest(unittest.TestCase):
    def setUp(self):
        self.p = params()
        self.lat, self.lon = 34.0, -119.5

    def test_params_from_region(self):
        raw = region_thresholds()['aggregate']
        self.assertEqual(self.p.module, raw['module'])
        self.assertEqual(self.p.resolution_m, raw['resolution_m'])
        self.assertIsNone(self.p.min_distinct_vessels)
        self.assertIsNone(self.p.delay_hours)
        self.assertEqual(AggregateParams.from_mapping(region_thresholds()), self.p)
        with self.assertRaises(ValueError):
            params(min_distinct_vessels=0)
        with self.assertRaises(ValueError):
            params(min_distinct_vessels=2.5)
        with self.assertRaises(ValueError):
            module('h3-not-yet')

    def test_min_distinct_vessels_suppresses_and_null_keeps(self):
        two = [event('v1', self.lat, self.lon), event('v2', self.lat + 1e-4, self.lon, start=T0 + HOUR),
               event('v1', self.lat, self.lon + 1e-4, start=T0 + 2 * HOUR)]
        kept = compute(two, params(min_distinct_vessels=None), now_ms=T0 + 10 * HOUR)
        self.assertTrue(kept)
        self.assertTrue(all(c.vessels_n == 2 and c.events_n == 3 for c in kept))
        self.assertEqual(compute(two, params(min_distinct_vessels=3), now_ms=T0 + 10 * HOUR), [])
        three = two + [event('v3', self.lat, self.lon, start=T0 + 3 * HOUR)]
        cells = compute(three, params(min_distinct_vessels=3), now_ms=T0 + 10 * HOUR)
        self.assertEqual({c.vessels_n for c in cells}, {3})
        self.assertEqual(len(cells), 2)   # the whole-season cell and the summer cell

    def test_whole_season_cells_always_written(self):
        events = [event('v1', self.lat, self.lon, part='summer', dwell=30),
                  event('v2', self.lat, self.lon, part='fall', start=T0 + HOUR, dwell=45),
                  event('v3', self.lat, self.lon, part=None, start=T0 + 2 * HOUR, dwell=10)]
        cells = compute(events, self.p, now_ms=T0 + 10 * HOUR)
        whole = [c for c in cells if c.season_part is None]
        self.assertEqual(len(whole), 1)
        self.assertEqual((whole[0].events_n, whole[0].vessels_n, whole[0].dwell_min), (3, 3, 85))
        parts = {c.season_part: c.dwell_min for c in cells if c.season_part is not None}
        self.assertEqual(parts, {'summer': 30, 'fall': 45})
        self.assertEqual(len({c.id for c in cells}), len(cells))
        # Per kind: a troll in the same cell gets its own whole-season cell.
        cells = compute(events + [event('v1', self.lat, self.lon, kind='troll')], self.p, now_ms=T0 + 10 * HOUR)
        self.assertEqual(sorted(c.kind for c in cells if c.season_part is None), ['drift-anchor', 'troll'])

    def test_rights_are_most_restrictive_input(self):
        self.assertEqual(most_restrictive(['public-domain', 'noaa-planning-only', 'facts-only']), 'noaa-planning-only')
        self.assertEqual(most_restrictive(['noaa-planning-only', 'internal-only']), 'internal-only')
        self.assertEqual(most_restrictive(['public-domain']), 'public-domain')
        with self.assertRaises(ValueError):
            most_restrictive(['made-up'])
        with self.assertRaises(ValueError):
            most_restrictive([])
        events = [event('v1', self.lat, self.lon, rights='public-domain'),
                  event('v2', self.lat, self.lon, rights='noaa-planning-only', start=T0 + HOUR, part='fall')]
        cells = {(c.season_part): c.rights for c in compute(events, self.p, now_ms=T0 + 10 * HOUR)}
        self.assertEqual(cells, {None: 'noaa-planning-only', 'summer': 'public-domain', 'fall': 'noaa-planning-only'})

    def test_delay_hours(self):
        events = [event('v1', self.lat, self.lon, start=T0), event('v2', self.lat, self.lon, start=T0 + 5 * HOUR)]
        now = T0 + 6 * HOUR
        self.assertEqual(compute(events, self.p, now_ms=now)[0].events_n, 2)          # null: pass-through
        self.assertEqual(compute(events, self.p)[0].events_n, 2)                      # no clock needed
        delayed = compute(events, params(delay_hours=3), now_ms=now)
        self.assertEqual({c.events_n for c in delayed}, {1})
        with self.assertRaises(ValueError):
            compute(events, params(delay_hours=3))                                    # fails closed without a clock

    def test_grid_cells(self):
        cell_id, lat, lon = grid_cell(self.lat, self.lon, 1000)
        self.assertRegex(cell_id, r'^g1000:-?\d+:-?\d+$')
        self.assertLess(metres((self.lat, self.lon), (lat, lon)), 1000 / math.sqrt(2) + 1)
        far = grid_cell(self.lat + 0.02, self.lon, 1000)
        self.assertNotEqual(far[0], cell_id)
        cells = compute([event('v1', self.lat, self.lon)], self.p, now_ms=T0 + 10 * HOUR, tz='America/Los_Angeles',
                        computed_at='2026-10-05T00:00:00.000Z')
        c = cells[0]
        self.assertEqual((c.cell_id, c.lat, c.lon), (cell_id, round(lat, 6), round(lon, 6)))
        self.assertEqual(c.module, 'grid')
        self.assertEqual(c.params_json, self.p.params_json)
        self.assertIn('"resolution_m":1000', c.params_json)   # map.ts cellSize reads it
        self.assertRegex(c.id, r'^[0-9a-f]{32}$')
        self.assertRegex(c.first_date, r'^\d{4}-\d\d-\d\d$')
        self.assertEqual(c.computed_at, '2026-10-05T00:00:00.000Z')
        # A different resolution is a different parameter set: different ids, never an overwrite.
        other = compute([event('v1', self.lat, self.lon)], params(resolution_m=500), now_ms=T0 + 10 * HOUR)
        self.assertTrue({x.id for x in other}.isdisjoint({x.id for x in cells}))

    def test_deterministic(self):
        rng = random.Random(3)
        events = [event(f'v{rng.randint(1, 5)}', 34 + rng.uniform(0, 0.05), -119.5 + rng.uniform(0, 0.05),
                        part=rng.choice(['summer', 'fall', None]), start=T0 + k * HOUR) for k in range(60)]
        a = compute(events, self.p, now_ms=T0 + 100 * HOUR)
        b = compute(list(reversed(events)), self.p, now_ms=T0 + 100 * HOUR)
        self.assertEqual(a, b)
        whole = sum(c.dwell_min for c in a if c.season_part is None)
        self.assertEqual(whole, sum(e.dwell_min for e in events))


if __name__ == '__main__':
    unittest.main()
