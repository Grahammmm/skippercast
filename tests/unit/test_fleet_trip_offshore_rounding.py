"""split_trips judges the offshore minimum on unrounded distance (RF1511-1); stored statistics stay six-decimal."""
from dataclasses import replace
import json

from skippercast.fleet.ais.segment import ActivityThresholds, offshore_nm, split_trips
from skippercast.fleet.ais.sources.base import AisPosition
from skippercast.fleet.config import Port
from tests._support import ROOT

MMSI = 999000456
T0 = 1_780_000_000_000
MIN = 60_000
HALF = 0.02
PORT = Port('port-a', 'Port A', (10.0, -150.0), None, None, ('ocean',),
            ((-150.02, 9.98), (-149.98, 9.98), (-149.98, 10.02), (-150.02, 10.02), (-150.02, 9.98)), 'drawn')
PORTS = (PORT,)
TH = ActivityThresholds.from_mapping(
    json.loads((ROOT / 'regions' / 'CA' / 'fleet.json').read_text(encoding='utf-8'))['thresholds'])


def lat_for(offshore):
    """A latitude due north of the harbor whose offshore distance is ``offshore`` nm."""
    return 10.0 + HALF + offshore / 60.0


def track(offshore, sea_minutes=30, start_at_sea=False, end_at_sea=False):
    """In-port fixes, an excursion peaking at ``offshore`` nm, then in-port fixes (unless ``end_at_sea``)."""
    lat = lat_for(offshore)
    plan = [] if start_at_sea else [10.0] * 40
    plan += [lat] * sea_minutes
    if not end_at_sea:
        plan += [10.0] * 40
    return [AisPosition(MMSI, T0 + k * MIN, la, -150.0, 5.0, 0.0, None, None, 'PositionReport', 'synthetic',
                        T0 + k * MIN + 2_000) for k, la in enumerate(plan)]


def trips(offshore, minimum, **kw):
    th = replace(TH, min_trip_offshore_nm=minimum)
    return split_trips(track(offshore, **{k: v for k, v in kw.items() if k != 'now'}), PORTS, th,
                       vessel_class='six-pack', now_ms=kw.get('now'))


def test_closed_trip_just_above_offshore_minimum_survives():
    assert 0.5 < offshore_nm(PORTS, lat_for(0.5000004), -150.0)
    out = trips(0.5000004, 0.5)
    assert [t.status for t in out] == ['closed']
    assert out[0].max_offshore_nm == 0.5  # six-decimal display value unchanged


def test_rounding_up_does_not_admit_subthreshold_trip():
    raw = offshore_nm(PORTS, lat_for(0.49999996), -150.0)
    minimum = 0.49999998
    assert raw < minimum < round(raw, 6)
    assert trips(0.49999996, minimum) == []


def test_equal_and_below_offshore_minimum_are_dropped():
    exact = offshore_nm(PORTS, lat_for(0.5), -150.0)
    assert trips(0.5, exact) == []
    assert trips(0.49, 0.5) == []


def test_truncated_trip_uses_unrounded_offshore_predicate():
    out = trips(0.5000004, 0.5, start_at_sea=True)
    assert [t.status for t in out] == ['truncated']
    assert out[0].depart_port_id is None and out[0].max_offshore_nm == 0.5
    assert trips(0.49999996, 0.49999998, start_at_sea=True) == []


def test_open_trip_remains_kept_below_offshore_and_duration_minima():
    out = trips(0.1, 0.5, sea_minutes=3, end_at_sea=True)
    assert [t.status for t in out] == ['open']
    assert out[0].depart_port_id == PORT.id


def test_duration_and_healthy_distance_controls():
    assert TH.min_trip_minutes > 3
    assert trips(0.5000004, 0.5, sea_minutes=3) == []
    out = trips(0.51, 0.5)
    assert [t.status for t in out] == ['closed']
    assert out[0].max_offshore_nm == round(offshore_nm(PORTS, lat_for(0.51), -150.0), 6)
