"""F08-11: only same-harbor observations can confirm a return."""
from dataclasses import replace
import unittest

from skippercast.fleet.ais.segment import split_trips
from tests.unit.test_fleet_classify import MIN, OFFSHORE, PORT_A, PORT_B, PORTS, T0, TH, Track


class HarborDwellTest(unittest.TestCase):
    def test_return_needs_two_fixes_spanning_debounce_in_the_same_harbor(self):
        track = Track()
        track.lat, track.lon = OFFSHORE
        track.t += MIN
        track.emit(6.0, None)
        departure = track.fixes[-1]
        first = replace(track.fixes[0], ts=T0 + 60 * MIN, received_at=T0 + 60 * MIN)

        def after(minutes, location):
            ts = first.ts + minutes * MIN
            return replace(first, ts=ts, received_at=ts, lat=location[0], lon=location[1])

        offshore = after(45, OFFSHORE)
        other_harbor = after(15, PORT_B.point)
        dwell = 3
        thresholds = replace(TH, in_port_debounce_min=dwell)
        # A later offshore fix or a fix in another harbor cannot extend a stay.
        for name, tail, return_port, end in (
            ('lone fix then silence', [offshore], None, offshore),
            ('short observed stay then silence', [after(dwell - 1, PORT_A.point), offshore], None, offshore),
            ('different harbors', [other_harbor, offshore], None, offshore),
            ('same harbor at the threshold', [after(dwell, PORT_A.point)], PORT_A.id, first),
            ('dwell begins in the second harbor', [other_harbor, after(15 + dwell, PORT_B.point)],
             PORT_B.id, other_harbor),
        ):
            with self.subTest(name=name):
                fixes = [*track.fixes, first, *tail]
                (trip,) = split_trips(fixes, PORTS, thresholds)
                self.assertEqual(trip.departed_at, departure.ts)
                self.assertEqual((trip.status, trip.return_port_id, trip.returned_at),
                                 ('closed' if return_port else 'open', return_port, end.ts))
                self.assertEqual(trip.positions, tuple(p for p in fixes[1:] if not return_port or p.ts < end.ts))
