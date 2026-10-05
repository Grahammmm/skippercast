"""skippercast.fleet.ais.segment and classify: trip splitting and segment labels (CF-43).

Every track here is synthetic: a made-up MMSI (999xxxxxx) sailing between two
square harbor geofences drawn in open ocean, generated fix by fix at one-minute
intervals. Thresholds are the committed ``regions/CA/fleet.json`` values, so a
change there is exercised here too.
"""
from dataclasses import replace
import json
import math
import random
import unittest

from skippercast.fleet.ais import classify, segment
from skippercast.fleet.ais.classify import classifier_version, classify_trip, label_positions
from skippercast.fleet.ais.segment import ActivityThresholds, LATE_MS, is_suspect, split_trips
from skippercast.fleet.ais.sources.base import AisPosition
from skippercast.fleet.config import Port
from tests._support import ROOT

MMSI = 999000123
T0 = 1_780_000_000_000  # an arbitrary epoch millisecond
MIN = 60_000


def square(lat, lon, half_deg):
    s, n, w, e = lat - half_deg, lat + half_deg, lon - half_deg, lon + half_deg
    return ((w, s), (e, s), (e, n), (w, n), (w, s))


PORT_A = Port('port-a', 'Port A', (10.0, -150.0), None, None, ('ocean',), square(10.0, -150.0, 0.02), 'drawn')
PORT_B = Port('port-b', 'Port B', (10.0, -149.5), None, None, ('ocean',), square(10.0, -149.5, 0.02), 'drawn')
PORTS = (PORT_A, PORT_B)


def region_thresholds():
    doc = json.loads((ROOT / 'regions' / 'CA' / 'fleet.json').read_text(encoding='utf-8'))
    return doc['thresholds']


TH = ActivityThresholds.from_mapping(region_thresholds())


class Track:
    """Builds one vessel's fixes: each step is one minute and reports SOG and COG."""

    def __init__(self, lat=10.0, lon=-150.0, t=T0, delay_ms=2_000):
        self.lat, self.lon, self.t, self.delay_ms = lat, lon, t, delay_ms
        self.fixes = []
        self.emit(0.0, None)

    def emit(self, sog, cog, delay_ms=None):
        delay = self.delay_ms if delay_ms is None else delay_ms
        self.fixes.append(AisPosition(MMSI, self.t, round(self.lat, 7), round(self.lon, 7), sog, cog, None, None,
                                      'PositionReport', 'synthetic', self.t + delay))

    def step(self, heading, sog, minutes=1, report=True):
        for _ in range(int(minutes)):
            d = sog / 60.0
            self.lat += d * math.cos(math.radians(heading)) / 60.0
            self.lon += d * math.sin(math.radians(heading)) / (60.0 * math.cos(math.radians(self.lat)))
            self.t += MIN
            if report:
                self.emit(sog, heading)
        return self

    def stay(self, minutes):
        """Slow shuffle around the berth, inside the geofence."""
        for k in range(int(minutes)):
            self.step((k * 90) % 360, 0.3)
        return self

    def go_to(self, lat, lon, sog):
        while True:
            dy = (lat - self.lat) * 60.0
            dx = (lon - self.lon) * 60.0 * math.cos(math.radians(self.lat))
            dist = math.hypot(dx, dy)
            if dist <= sog / 60.0:
                return self
            self.step(math.degrees(math.atan2(dx, dy)) % 360, sog)

    def drift(self, minutes, sog=1.0):
        for k in range(int(minutes)):
            self.step(200 + 25 * math.sin(k / 4), sog)
        return self

    def zigzag(self, minutes, sog=6.0, leg=3, headings=(30, 150)):
        for k in range(int(minutes)):
            self.step(headings[(k // leg) % 2], sog)
        return self

    def silence(self, minutes, heading, sog):
        self.step(heading, sog, minutes, report=False)
        return self


OFFSHORE = (10.0, -149.85)  # about 8.9 nm east of port A


def fishing_trip(activity):
    """Port A -> 6 kn out -> activity -> 6 kn back -> Port A."""
    track = Track().stay(30).go_to(*OFFSHORE, 6.0)
    activity(track)
    return track.go_to(10.0, -150.0, 6.0).stay(30).fixes


def classified(fixes, th=TH):
    trips = split_trips(fixes, PORTS, th, vessel_class='six-pack')
    return trips, [classify_trip(trip, PORTS, th) for trip in trips]


def kinds(result):
    return [s.kind for s in result.segments]


class ThresholdTest(unittest.TestCase):
    def test_reads_region_activity_thresholds(self):
        activity = region_thresholds()['activity']
        self.assertEqual(TH.window_min, activity['window_min'])
        self.assertEqual(TH.drift_max_sog_kn, activity['drift']['max_sog_kn'])
        self.assertEqual(TH.troll_min_heading_variance, activity['troll']['min_heading_variance'])
        self.assertEqual(ActivityThresholds.from_mapping(activity), TH)

    def test_classifier_version_tracks_thresholds(self):
        base = classifier_version(TH)
        self.assertRegex(base, r'^c\d+-[0-9a-f]{16}$')
        self.assertEqual(classifier_version(ActivityThresholds.from_mapping(region_thresholds())), base)
        changed = region_thresholds()
        changed['activity']['drift']['max_sog_kn'] = 1.5
        self.assertNotEqual(classifier_version(ActivityThresholds.from_mapping(changed)), base)
        changed = region_thresholds()
        changed['activity']['window_min'] = 30
        self.assertNotEqual(classifier_version(ActivityThresholds.from_mapping(changed)), base)

    def test_classifier_version_tracks_algorithm(self):
        base = classifier_version(TH)
        original = classify.ALGORITHM_VERSION
        try:
            classify.ALGORITHM_VERSION = original + 1
            self.assertNotEqual(classifier_version(TH), base)
        finally:
            classify.ALGORITHM_VERSION = original


class TripSplitTest(unittest.TestCase):
    def test_harbor_shuffle_yields_no_trip(self):
        # Shuffle in port, poke just past the east edge for a few minutes, come back.
        track = Track().stay(40)
        track.go_to(10.0, -149.978, 1.5).step(90, 1.0, 4).go_to(10.0, -150.0, 1.5).stay(40)
        self.assertEqual(split_trips(track.fixes, PORTS, TH), [])
        # A longer loiter that never gets past min_trip_offshore_nm is dropped as well.
        track = Track().stay(20).go_to(10.0, -149.976, 2.0)
        for k in range(40):
            track.step(0 if k % 10 < 5 else 180, 1.0)
        track.go_to(10.0, -150.0, 2.0).stay(20)
        self.assertEqual(split_trips(track.fixes, PORTS, TH), [])

    def test_out_and_back_is_one_closed_trip(self):
        fixes = fishing_trip(lambda t: t.drift(30))
        trips = split_trips(fixes, PORTS, TH)
        self.assertEqual(len(trips), 1)
        trip = trips[0]
        self.assertEqual((trip.depart_port_id, trip.return_port_id, trip.status), ('port-a', 'port-a', 'closed'))
        self.assertEqual(trip.basis, 'inferred-from-movement')
        self.assertTrue(all(PORT_A.contains(p.lat, p.lon) is False for p in trip.positions))
        self.assertGreater(trip.max_offshore_nm, 7.5)
        self.assertGreater(trip.distance_nm, 15)
        self.assertGreater(trip.returned_at, trip.positions[-1].ts)

    def test_short_dip_into_a_geofence_does_not_end_the_trip(self):
        track = Track().stay(20).go_to(*OFFSHORE, 6.0).go_to(10.0, -149.53, 6.0)
        for lon in (-149.519, -149.53):        # one fix just inside port B, then out again
            track.lon, track.t = lon, track.t + MIN
            track.emit(2.0, 90)
        self.assertTrue(PORT_B.contains(10.0, -149.519))
        track.go_to(10.0, -150.0, 6.0).stay(20)
        trips = split_trips(track.fixes, PORTS, TH)
        self.assertEqual(len(trips), 1)
        self.assertEqual(trips[0].return_port_id, 'port-a')
        result = classify_trip(trips[0], PORTS, TH)
        self.assertNotIn('in-port', kinds(result))  # a one-minute stay merges into its neighbour

    def test_return_to_another_port(self):
        track = Track().stay(20).go_to(10.0, -149.5, 6.0).stay(20)
        (trip,) = split_trips(track.fixes, PORTS, TH)
        self.assertEqual((trip.depart_port_id, trip.return_port_id), ('port-a', 'port-b'))

    def test_long_silence_then_seen_in_port_truncates(self):
        track = Track().stay(20).go_to(*OFFSHORE, 6.0).step(90, 6.0, 20)
        last_at_sea = track.t
        track.silence(13 * 60, 0, 0.0)
        track.lat, track.lon = 10.0, -150.0
        track.emit(0.0, None)
        track.stay(20)
        (trip,) = split_trips(track.fixes, PORTS, TH)
        self.assertEqual((trip.status, trip.returned_at, trip.return_port_id), ('truncated', last_at_sea, None))

    def test_open_trip_and_age_limit(self):
        track = Track().stay(20).go_to(*OFFSHORE, 6.0).drift(60)
        (trip,) = split_trips(track.fixes, PORTS, TH, vessel_class='six-pack')
        self.assertEqual(trip.status, 'open')
        later = trip.departed_at + 19 * 3_600_000
        (trip,) = split_trips(track.fixes, PORTS, TH, vessel_class='six-pack', now_ms=later)
        self.assertEqual(trip.status, 'truncated')
        (trip,) = split_trips(track.fixes, PORTS, TH, vessel_class='inspected-party', now_ms=later)
        self.assertEqual(trip.status, 'open')

    def test_starting_at_sea_is_truncated(self):
        track = Track(lat=OFFSHORE[0], lon=OFFSHORE[1]).go_to(10.0, -150.0, 6.0).stay(20)
        (trip,) = split_trips(track.fixes, PORTS, TH)
        self.assertEqual((trip.depart_port_id, trip.return_port_id, trip.status), (None, 'port-a', 'truncated'))

    def test_one_mmsi_at_a_time(self):
        fixes = Track().stay(5).fixes
        other = replace(fixes[0], mmsi=999000456, ts=fixes[0].ts + 1)
        with self.assertRaises(ValueError):
            split_trips(fixes + [other], PORTS, TH)

    def test_repeated_fix_keeps_earliest_receipt(self):
        fixes = fishing_trip(lambda t: t.drift(30))
        dupes = [replace(p, received_at=p.received_at + 5_000, lat=p.lat + 0.01) for p in fixes[::7]]
        self.assertEqual(split_trips(fixes + dupes, PORTS, TH), split_trips(fixes, PORTS, TH))

    def test_duplicates_differing_only_in_motion_fields_resolve_in_any_order(self):
        fixes = fishing_trip(lambda t: t.drift(30))
        dupes = []
        for p in fixes[::5]:
            dupes += [replace(p, sog=None), replace(p, sog=(p.sog or 0) + 3.0), replace(p, cog=None),
                      replace(p, heading=180), replace(p, cog=((p.cog or 0) + 90) % 360)]
        rows = fixes + dupes
        expected = segment.prepare(rows)
        self.assertEqual(len(expected), len(fixes))
        trips = classified(rows)
        for seed in range(5):
            shuffled = list(rows)
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(segment.prepare(shuffled), expected)
            self.assertEqual(classified(shuffled), trips)


class ClassifyTest(unittest.TestCase):
    def assert_tiles(self, result):
        segs = result.segments
        self.assertEqual(segs[0].started_at, result.trip.departed_at)
        self.assertEqual(segs[-1].ended_at, result.trip.returned_at)
        for a, b in zip(segs, segs[1:]):
            self.assertEqual(a.ended_at, b.started_at)
        self.assertEqual([s.seq for s in segs], list(range(len(segs))))
        self.assertEqual(sum(s.points_n for s in segs), len(result.trip.positions))
        self.assertTrue(all(s.basis == 'inferred-from-movement' for s in segs))
        self.assertEqual(result.basis, 'inferred-from-movement')
        self.assertTrue(all(s.minutes >= TH.min_segment_minutes for s in segs if s.kind != 'gap'))

    def test_drift_at_one_knot_for_thirty_minutes(self):
        _, (result,) = classified(fishing_trip(lambda t: t.drift(30, sog=1.0)))
        self.assert_tiles(result)
        self.assertEqual(kinds(result), ['transit', 'fishing-drift', 'transit'])
        drift = result.segments[1]
        self.assertGreaterEqual(drift.minutes, TH.drift_min_minutes)
        self.assertLessEqual(drift.mean_sog, TH.drift_max_sog_kn)
        self.assertAlmostEqual(result.fishing_min, drift.minutes)
        self.assertEqual(result.classifier_version, classifier_version(TH))

    def test_short_drift_is_transit(self):
        _, (result,) = classified(fishing_trip(lambda t: t.drift(8, sog=1.0)))
        self.assertEqual(kinds(result), ['transit'])

    def test_six_knot_zigzag_is_troll(self):
        _, (result,) = classified(fishing_trip(lambda t: t.zigzag(60)))
        self.assert_tiles(result)
        self.assertEqual(kinds(result), ['transit', 'fishing-troll', 'transit'])
        troll = result.segments[1]
        self.assertGreaterEqual(troll.minutes, 45)
        self.assertTrue(troll.straightness <= TH.troll_max_straightness
                        or troll.heading_var >= TH.troll_min_heading_variance)

    def test_straight_six_knot_run_is_transit(self):
        track = Track().stay(20).go_to(10.0, -149.5, 6.0).stay(20)
        _, (result,) = classified(track.fixes)
        self.assert_tiles(result)
        self.assertEqual(kinds(result), ['transit'])
        self.assertGreater(result.segments[0].straightness, 0.99)
        self.assertLess(result.segments[0].heading_var, 0.01)
        self.assertEqual(result.fishing_min, 0)

    def test_three_hour_gap_at_sea(self):
        track = Track().stay(20).go_to(*OFFSHORE, 6.0).step(0, 6.0, 30)
        track.silence(180, 0, 6.0)
        track.step(0, 6.0, 30).go_to(10.0, -150.0, 6.0).stay(20)
        (trip,), (result,) = classified(track.fixes)
        self.assertEqual(trip.status, 'closed')
        self.assert_tiles(result)
        self.assertEqual(kinds(result), ['transit', 'gap', 'transit'])
        gap = result.segments[1]
        self.assertEqual(gap.points_n, 0)
        self.assertAlmostEqual(gap.minutes, 181)
        self.assertAlmostEqual(result.gap_min, 181)

    def test_silence_before_return_is_a_gap(self):
        # Drift 30 min, go dark for 3 h, next seen in port: the dark time is a gap, not more drift.
        track = Track().stay(20).go_to(*OFFSHORE, 6.0).drift(30, sog=1.0)
        last_at_sea = track.t
        track.silence(180, 0, 0.0)
        track.lat, track.lon = 10.0, -150.0
        track.emit(0.0, None)
        track.stay(20)
        (trip,), (result,) = classified(track.fixes)
        self.assertEqual(trip.status, 'closed')
        self.assert_tiles(result)
        self.assertEqual(kinds(result)[-2:], ['fishing-drift', 'gap'])
        self.assertIn(kinds(result)[:-2], ([], ['transit']))
        drift, gap = result.segments[-2:]
        self.assertTrue(20 <= drift.minutes <= 31, drift.minutes)
        self.assertEqual(drift.ended_at, last_at_sea)
        self.assertAlmostEqual(gap.minutes, 180)
        self.assertEqual(gap.points_n, 0)

    def test_short_silence_is_not_a_gap(self):
        track = Track().stay(20).go_to(*OFFSHORE, 6.0).silence(20, 90, 6.0).step(90, 6.0, 10)
        track.go_to(10.0, -150.0, 6.0).stay(20)
        _, (result,) = classified(track.fixes)
        self.assertNotIn('gap', kinds(result))

    def test_suspect_fixes_are_kept_out_of_heading_and_straightness(self):
        # A straight 6 kn run whose every other fix is a late report placed two minutes behind,
        # with no reported COG: counted, the path doubles back and looks like trolling.
        def build(late):
            track = Track().stay(20).go_to(10.0, -149.97, 6.0)
            for k in range(60):
                track.step(90, 6.0, report=False)
                if k % 2:
                    behind = AisPosition(MMSI, track.t, track.lat, track.lon - 2 * 0.1 / (60 * math.cos(math.radians(10))),
                                         6.0, None, None, None, 'PositionReport', 'synthetic',
                                         track.t + (LATE_MS + 5_000 if late else 2_000))
                    track.fixes.append(behind)
                else:
                    track.emit(6.0, None)
            return track.go_to(10.0, -149.5, 6.0).stay(20).fixes

        honest = build(late=True)
        self.assertTrue(any(is_suspect(p) for p in honest))
        _, (result,) = classified(honest)
        self.assertEqual(kinds(result), ['transit'])
        _, (result,) = classified(build(late=False))
        self.assertIn('fishing-troll', kinds(result))

    def test_derived_speed_when_sog_missing(self):
        fixes = [replace(p, sog=None, cog=None) for p in fishing_trip(lambda t: t.drift(30, sog=1.0))]
        _, (result,) = classified(fixes)
        self.assertEqual(kinds(result), ['transit', 'fishing-drift', 'transit'])

    def test_same_input_same_output(self):
        fixes = fishing_trip(lambda t: t.zigzag(40).drift(30))
        shuffled = list(fixes)
        random.Random(7).shuffle(shuffled)
        first = classified(fixes)
        self.assertEqual(classified(fixes), first)
        self.assertEqual(classified(shuffled), first)
        # The centred window blends 6 kn and 1 kn into a short transit stretch between the two.
        self.assertEqual(kinds(first[1][0]), ['transit', 'fishing-troll', 'transit', 'fishing-drift', 'transit'])

    def test_in_port_label_inside_geofence(self):
        fixes = Track().stay(5).fixes
        self.assertEqual(set(label_positions(fixes, PORTS, TH)), {'in-port'})


if __name__ == '__main__':
    unittest.main()
