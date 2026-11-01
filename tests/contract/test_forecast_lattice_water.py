"""Forecast lattice points stay on water, and every regional request stays small (NB-SC-06, #501).

Water rule, checked against the NOAA CUSP shoreline the region ships
(catalog/shoreline/morro-bay.geojson): a point is water when it lies at least
8 km from every shoreline vertex and west of the westernmost vertex within
0.01° of its latitude. A latitude with no vertex there cannot be confirmed.
"""
import json
import math

import pytest

from tests._support import ROOT

CLEARANCE_KM = 8.0
BAND_DEG = 0.01
MAX_POINTS = 50


def _vertices():
    shore = json.loads((ROOT / 'catalog/shoreline/morro-bay.geojson').read_text())
    out = []

    def walk(c):
        if isinstance(c[0], (int, float)):
            out.append((c[0], c[1]))
        else:
            for part in c:
                walk(part)
    for feature in shore['features']:
        walk(feature['geometry']['coordinates'])
    return out


VERTICES = _vertices()


def _km(lon_a, lat_a, lon_b, lat_b):
    mid = math.radians((lat_a + lat_b) / 2)
    return math.hypot((lon_a - lon_b) * 111.32 * math.cos(mid), (lat_a - lat_b) * 110.57)


def on_water(lat, lon):
    band = [v_lon for v_lon, v_lat in VERTICES if abs(v_lat - lat) <= BAND_DEG]
    if not band or lon >= min(band):
        return False
    return all(_km(lon, lat, v_lon, v_lat) >= CLEARANCE_KM for v_lon, v_lat in VERTICES)


def _region(name):
    return json.loads((ROOT / 'regions' / name / 'region.json').read_text())


def test_every_morro_bay_lattice_point_is_water():
    points = [p for p in _region('morro-bay')['forecast_points'] if p.get('offshore')]
    assert len(points) == 11
    assert {p['id'] for p in points} >= {'offshore-0-s', 'offshore-1-s'}
    for p in points:
        assert on_water(p['latitude'], p['longitude']), p['id']


@pytest.mark.parametrize('lat,lon,why', [
    (35.55, -121.0, 'Cambria coast: on land, east of the shore and within 8 km'),
    (35.3, -120.95, 'west of Point Buchon but within 8 km of the shore'),
    (35.05, -120.3, 'far from every vertex but east of the shore (inland)'),
    (36.5, -122.5, 'no shoreline at this latitude to confirm it'),
])
def test_a_planted_point_off_the_water_rule_fails(lat, lon, why):
    assert not on_water(lat, lon), why


def test_the_left_out_cambria_column_point_is_not_in_the_region():
    coords = {(p['latitude'], p['longitude']) for p in _region('morro-bay')['forecast_points']}
    assert (35.55, -121.0) not in coords


def test_every_region_requests_at_most_50_forecast_points():
    counts = {path.parent.name: len(json.loads(path.read_text()).get('forecast_points', []))
              for path in sorted((ROOT / 'regions').glob('*/region.json'))}
    assert counts and counts['morro-bay'] == 15
    assert max(counts.values()) <= MAX_POINTS, counts
