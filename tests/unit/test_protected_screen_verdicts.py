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
