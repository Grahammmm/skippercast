"""SC-PERF-PROTCHECK-1: the publish-time protected-area verdicts equal the browser's (dist/geo-screen.js) on a fixed set of cases.

tests/fixtures/protected_screen_cases.json holds the boundary, the reefs and the answers dist/geo-screen.js gave
(`screenPlace`, `boundaryFingerprint`); tests/test_protected_verdicts.mjs re-checks the same file against the JS.
The whole real export is compared by scripts/protected_screen_parity.py (needs node and the downloaded export).
"""
import json

import pytest

pytest.importorskip('numpy')
from skippercast.seafloor import protected_screen as ps  # noqa: E402
from tests._support import ROOT  # noqa: E402

pytestmark = pytest.mark.gis
CASES = json.loads((ROOT/'tests/fixtures/protected_screen_cases.json').read_text())


def test_each_reef_gets_the_browsers_verdict():
    reefs = [(r['id'], r['geometry'], r['longitude'], r['latitude']) for r in CASES['reefs']]
    got = ps.verdicts(CASES['boundary'], CASES['bounds'], reefs)
    assert got == CASES['expected']


def _names():
    return [ps.feature_name(f) for f in CASES['boundary']]


def test_fingerprint_is_the_browsers_hash():
    assert ps.fingerprint([f['geometry'] for f in CASES['boundary']], CASES['bounds'], _names()) == CASES['fingerprint']


def test_fingerprint_changes_when_only_a_closure_name_changes():
    geoms = [f['geometry'] for f in CASES['boundary']]
    base = ps.fingerprint(geoms, CASES['bounds'], _names())
    assert ps.fingerprint(geoms, CASES['bounds'], _names()) == base
    assert ps.fingerprint(geoms, CASES['bounds'], [_names()[0] + ' (renamed)', *_names()[1:]]) != base
    assert ps.fingerprint(geoms, CASES['bounds'], [None, *_names()[1:]]) != base
    assert ps.fingerprint(geoms, CASES['bounds'], ['\U0001F41F', *_names()[1:]]) != ps.fingerprint(geoms, CASES['bounds'], ['\ufffd', *_names()[1:]])


def test_fingerprint_changes_with_any_boundary_change():
    geoms = [json.loads(json.dumps(f['geometry'])) for f in CASES['boundary']]
    base = ps.fingerprint(geoms, CASES['bounds'], _names())
    geoms[0]['coordinates'][0][0][0] += 1e-9
    assert ps.fingerprint(geoms, CASES['bounds'], _names()) != base
    assert ps.fingerprint(geoms[:-1], CASES['bounds'], _names()[:-1]) != base
    assert ps.fingerprint([f['geometry'] for f in CASES['boundary']], [-121.9, 34.95, -120.55, 35.86], _names()) != base


def test_stamp_adds_a_verdict_to_every_feature_and_a_fingerprint(tmp_path):
    region = tmp_path/'dist/regions/test-bay'
    region.mkdir(parents=True)
    (tmp_path/'dist/data').mkdir(parents=True)
    (region/'region.json').write_text(json.dumps({'mpa': {'bounds': CASES['bounds']}, 'assets': {'protected_areas': 'data/pa.geojson', 'closures': None}}))
    (tmp_path/'dist/data/pa.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': CASES['boundary']}))
    features = [{'type': 'Feature', 'geometry': r['geometry'], 'properties': {'id': r['id'], 'waypoint': {'longitude': r['longitude'], 'latitude': r['latitude']}}}
                for r in CASES['reefs']]
    meta = ps.stamp(tmp_path, 'test-bay', features)
    assert meta['fingerprint'] == CASES['fingerprint'] and meta['boundary_features'] == 3 and meta['bounds'] == CASES['bounds']
    assert {f['properties']['id']: f['properties']['protected_place'] for f in features} == CASES['expected']


def test_a_region_without_a_screen_gets_no_verdicts(tmp_path):
    assert ps.stamp(tmp_path, 'nowhere', []) is None


# ---- RF0825-7: malformed place geometries are refused before any Shape is built ----

UNSCREENED = {'inside': False, 'name': None, 'distanceM': None, 'screened': False}
_BOUNDS = [-1, -1, 1, 1]
_OK = {'type': 'Point', 'coordinates': [0.5, 0.5]}
_MALFORMED = {
    'short_point': {'type': 'Point', 'coordinates': [0]},
    'null_geometry': None,
    'empty_point': {'type': 'Point', 'coordinates': []},
    'empty_polygon': {'type': 'Polygon', 'coordinates': []},
    'short_line_vertex': {'type': 'LineString', 'coordinates': [[0, 0], [0.1]]},
    'bad_multi_depth': {'type': 'MultiPolygon', 'coordinates': [[[0, 0], [0.1, 0.1]]]},
    'short_multiline_vertex': {'type': 'MultiLineString', 'coordinates': [[[0, 0], [0.1, 0.1]], [[0, 0], [0.2]]]},
}


@pytest.fixture
def shape_calls(monkeypatch):
    calls = []
    real = ps.Shape
    monkeypatch.setattr(ps, 'Shape', lambda g: calls.append(g) or real(g))
    return calls


@pytest.mark.parametrize('bad', list(_MALFORMED.values()), ids=list(_MALFORMED))
def test_malformed_outline_is_unscreened_before_shape(bad, shape_calls):
    assert ps.screen_place([], _BOUNDS, [bad], 0, 0) == UNSCREENED
    assert ps.screen_place([], _BOUNDS, [_OK, bad], 0, 0) == UNSCREENED     # a valid sibling does not excuse it
    assert ps.screen_place([], _BOUNDS, [bad, _OK], 0, 0) == UNSCREENED
    assert shape_calls == []


def test_malformed_waypoint_is_unscreened_before_shape(shape_calls):
    assert ps.screen_place([], _BOUNDS, [_OK], 0, None) == UNSCREENED
    assert shape_calls == []


def test_verdict_batch_keeps_valid_siblings():
    boundary = [{'properties': {'NAME': 'Zone'}, 'geometry': {'type': 'Point', 'coordinates': [0.9, 0.9]}}]
    good = ('good', _OK, 0.5, 0.5)
    bad = ('bad', _MALFORMED['short_line_vertex'], 0, 0)
    both = ps.verdicts(boundary, _BOUNDS, [bad, good])
    assert both['bad'] == UNSCREENED
    assert both['good'] == ps.verdicts(boundary, _BOUNDS, [good])['good']
    assert both['good']['screened'] is True
