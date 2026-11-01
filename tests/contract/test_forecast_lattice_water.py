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


CAMBRIA_LATTICE = ['offshore-0-0', 'offshore-0-1', 'offshore-1-0', 'offshore-1-1',
                   'offshore-s-0', 'offshore-s-1', 'offshore-s-2', 'offshore-0-2']


@pytest.mark.parametrize('name,count,added', [
    ('morro-bay', 11, {'offshore-0-s', 'offshore-1-s'}),
    ('cambria-san-simeon', 8, set(CAMBRIA_LATTICE[4:])),
])
def test_every_lattice_point_is_water(name, count, added):
    points = [p for p in _region(name)['forecast_points'] if p.get('offshore')]
    assert len(points) == count
    assert {p['id'] for p in points} >= added
    for p in points:
        assert on_water(p['latitude'], p['longitude']), p['id']


def test_cambria_keeps_the_four_water_candidates_in_order_and_leaves_inshore_points_off_the_lattice():
    points = _region('cambria-san-simeon')['forecast_points']
    assert [p['id'] for p in points if p.get('offshore')] == CAMBRIA_LATTICE
    inshore = [p['id'] for p in points if not p.get('offshore')]
    assert inshore == ['cambria', 'san-simeon', 'north-coast']
    assert len({p['id'] for p in points}) == len(points), 'no duplicate ids'
    assert len({(p['latitude'], p['longitude']) for p in points}) == len(points), 'no duplicate coordinates'


@pytest.mark.parametrize('lat,lon,why', [
    (35.55, -121.0, 'Cambria coast: on land, east of the shore and within 8 km'),
    (35.3, -120.95, 'west of Point Buchon but within 8 km of the shore'),
    (35.05, -120.3, 'far from every vertex but east of the shore (inland)'),
    (36.5, -122.5, 'no shoreline at this latitude to confirm it'),
])
def test_a_planted_point_off_the_water_rule_fails(lat, lon, why):
    assert not on_water(lat, lon), why


@pytest.mark.parametrize('name,lat,lon', [
    ('morro-bay', 35.55, -121.0),
    ('cambria-san-simeon', 35.65, -121.25),  # Piedras Blancas: under 8 km from the shore
])
def test_a_left_out_candidate_fails_the_water_rule_and_is_not_in_the_region(name, lat, lon):
    assert not on_water(lat, lon)
    coords = {(p['latitude'], p['longitude']) for p in _region(name)['forecast_points']}
    assert (lat, lon) not in coords


@pytest.mark.parametrize('lat,ok', [(35.45, True), (35.449, False)])
def test_the_cambria_south_row_sits_on_the_inclusive_bound_and_a_point_south_of_it_is_refused(lat, ok):
    from skippercast.platform.contracts import REPO, load_catalogs, validate_region
    region = _region('cambria-san-simeon')
    assert region['bounds'][1] == 35.45
    planted = next(p for p in region['forecast_points'] if p['id'] == 'offshore-s-0')
    planted['latitude'] = lat
    if ok:
        validate_region(region, *load_catalogs(REPO), root=REPO)
    else:
        with pytest.raises(ValueError, match='outside its region bounds'):
            validate_region(region, *load_catalogs(REPO), root=REPO)


def test_every_region_requests_at_most_50_forecast_points():
    counts = {path.parent.name: len(json.loads(path.read_text()).get('forecast_points', []))
              for path in sorted((ROOT / 'regions').glob('*/region.json'))}
    assert counts and counts['morro-bay'] == 15 and counts['cambria-san-simeon'] == 11
    assert max(counts.values()) <= MAX_POINTS, counts
