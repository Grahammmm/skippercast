"""F07-10: an inferred fishing-event centre must not land in an excluded harbor.

Contract: dropping in-harbor fixes is not enough, because the component-wise
median of fixes on opposite sides of a harbor falls inside it, and that point
is what the aggregator bins. The event point is then an observed outside fix
(deterministic), and ``radius_m`` is measured from the point actually used.
Believable bug: ``build_events`` keeps the raw median (event at the harbor
centre) or recomputes the radius from the discarded median.

Synthetic harbors and made-up MMSI only; no real positions.
"""
from dataclasses import dataclass
import random

from skippercast.fleet.ais import events as ev
from skippercast.fleet.ais.classify import Classification, Segment
from skippercast.fleet.ais.events import build_events
from tests.unit.test_fleet_classify import PORT_A, PORTS, T0
from tests.unit.test_fleet_events import MIN, ctx, fix, metres


def _events(fixes, ports=PORTS, kind="drift-anchor"):
    segment = Segment(0, kind, T0, T0 + len(fixes) * MIN, tuple(fixes), 0.5, 0.2, 0.1)
    return build_events(Classification(None, (segment,), "c1-x"), ports, ctx())


def _fixes(points):
    return [fix(T0 + k * MIN, lat, lon) for k, (lat, lon) in enumerate(points)]


# PORT_A is a +/-0.02 degree square at (10.0, -150.0).
WEST, EAST = (10.0, -150.05), (10.0, -149.95)


def test_opposite_side_fixes_do_not_put_the_event_in_the_harbor():
    points = [WEST, WEST, EAST, EAST]
    # Negative control: the raw median is the harbor centre (the cited failure).
    assert PORT_A.contains(*ev.median_point(points))
    [e] = _events(_fixes(points))
    assert not PORT_A.contains(e.lat, e.lon)
    assert (e.lat, e.lon) in {WEST, EAST}  # an observed fix, not an invented point
    assert e.basis == "inferred-from-movement" and e.kind == "drift-anchor"


def test_radius_is_measured_from_the_chosen_point():
    points = [WEST, WEST, EAST, EAST]
    [e] = _events(_fixes(points))
    far = max(metres((e.lat, e.lon), p) for p in points)
    assert e.radius_m == round(far, 1)
    assert e.radius_m > metres(ev.median_point(points), WEST) * 1.5  # not the discarded median's radius


def test_choice_is_deterministic_and_order_independent():
    points = [WEST, (10.001, -150.06), EAST, (10.002, -149.94)]
    assert PORT_A.contains(*ev.median_point(points))
    chosen = {(e.lat, e.lon) for order in range(6)
              for [e] in [_events(_fixes(random.Random(order).sample(points, len(points))))]}
    assert len(chosen) == 1
    assert not PORT_A.contains(*chosen.pop())


def test_single_side_fixes_keep_the_median_positive_control():
    points = [(10.05 + k * 1e-4, -150.0) for k in range(9)]
    [e] = _events(_fixes(points))
    clean = ev.median_point(points)
    assert (e.lat, e.lon) == (round(clean[0], 6), round(clean[1], 6))
    assert e.radius_m == round(ev.p90_radius_m(points, clean), 1)


def test_all_inside_fixes_yield_no_event():
    points = [(10.0 + k * 1e-3, -150.0) for k in range(5)]
    assert all(PORT_A.contains(*p) for p in points)
    assert _events(_fixes(points)) == []


@dataclass(frozen=True)
class SeamHarbor:
    """Synthetic harbor straddling the antimeridian (the repo's Port has no wrap handling)."""
    id: str = "seam"
    geofence: tuple = ()

    def contains(self, lat, lon):
        return abs(lat - 10.0) <= 0.02 and min(abs(lon - 180.0), abs(lon + 180.0)) <= 0.02


def test_longitude_seam_opposite_sides_stay_outside_the_harbor():
    harbor = SeamHarbor()
    east_of_seam, west_of_seam = (10.0, 179.95), (10.0, -179.95)
    points = [east_of_seam, east_of_seam, west_of_seam, west_of_seam]
    assert harbor.contains(*ev.median_point(points))  # unwrapped median sits on the seam
    [e] = _events(_fixes(points), ports=(harbor,))
    assert not harbor.contains(e.lat, e.lon)
    assert (e.lat, e.lon) in {east_of_seam, west_of_seam}
    # Radius is the great-circle distance across the seam, not a 359.9 degree longitude span.
    assert e.radius_m == round(max(metres((e.lat, e.lon), p) for p in points), 1)
    assert e.radius_m < 12_000
