"""F26-05 offline controls: atlas completeness must gate the all-clear."""
from datetime import datetime
import copy

import pytest

pytest.importorskip('pyproj')
pytest.importorskip('shapely')
pytestmark = pytest.mark.gis

from research.scripts import audit_central_atlas_closures as m
from tests._support import NOW as FIXED_NOW

NOW = FIXED_NOW.isoformat()


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr(m, 'datetime', _FixedDatetime)


def _sq(x, y, d=0.001):
    return {'type': 'Polygon', 'coordinates': [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]]}


def _atlas():
    return {'fishing_depth_limit_ft': 200,
            'targets': [{'id': f'T{i}', 'longitude': -121 + i * .01, 'latitude': 35.0} for i in range(132)],
            'areas': [{'id': f'A{i}', 'geometry': _sq(-121 + i * .01, 35.1)} for i in range(107)],
            'drifts': [{'id': f'D{i}', 'geometry': {'type': 'LineString',
                        'coordinates': [[-121 + i * .01, 35.2], [-121 + i * .01 + .002, 35.2]]}}
                       for i in range(31)]}


def _sources():
    mpa_feats = [{'type': 'Feature', 'properties': {}, 'geometry': _sq(-110 + i, 30)} for i in range(100)]
    geas = [{'properties': {'area_type': 'GEA'}, 'geometry': _sq(-100 + i, 30)} for i in range(25)]
    mpa = {'sources': {'mpas': {'status': 'ok', 'data_retrieved_at': NOW,
                                'data': {'geojson': {'features': mpa_feats}}}}}
    return mpa, {'status': 'ok', 'retrieved_at': NOW, 'features': geas}


def _ids():
    a = _atlas()
    return {k: [i['id'] for i in a[k]] for k in ('targets', 'areas', 'drifts')}


def _run(a, ids=True):
    mpa, fed = _sources()
    return m.audit(a, mpa, fed, expected_ids=_ids() if ids else None)


def test_complete_fixture_is_clear():
    assert _run(_atlas())['all_geometry_clear_of_screen_buffers'] is True


@pytest.mark.parametrize('bad_id', [None, ['T0']])
def test_invalid_id_withholds_clearance(bad_id):
    a = _atlas()
    if bad_id is None:
        del a['targets'][0]['id']
    else:
        a['targets'][0]['id'] = bad_id
    r = _run(a)
    assert not r['all_geometry_clear_of_screen_buffers']
    assert r['sections']['targets']['completeness']['invalid_id_count'] == 1
    assert r['sections']['targets']['completeness']['missing_ids'] == ['T0']


def test_invalid_projected_target_is_rejected():
    a = _atlas()
    a['targets'][0]['latitude'] = 95
    with pytest.raises(ValueError, match='Invalid.*geometry'):
        _run(a)


def test_repeated_single_target_not_clear():
    a = _atlas()
    a['targets'] = [copy.deepcopy(a['targets'][0]) for _ in range(132)]
    a['areas'], a['drifts'] = a['areas'][:1], a['drifts'][:1]
    r = _run(a, ids=False)
    assert r['all_geometry_clear_of_screen_buffers'] is False
    assert r['sections']['targets']['completeness']['duplicate_ids'] == ['T0']


def test_duplicate_target_not_clear():
    a = _atlas()
    a['targets'][5]['id'] = 'T0'
    r = _run(a)
    c = r['sections']['targets']['completeness']
    assert not r['all_geometry_clear_of_screen_buffers']
    assert c['duplicate_ids'] == ['T0'] and c['missing_ids'] == ['T5']


def test_missing_drift_not_clear():
    a = _atlas()
    a['drifts'].pop()
    r = _run(a)
    assert not r['all_geometry_clear_of_screen_buffers']
    assert r['sections']['drifts']['completeness']['missing_ids'] == ['D30']


def test_unexpected_id_not_clear():
    a = _atlas()
    a['areas'][0]['id'] = 'X'
    r = _run(a)
    assert not r['all_geometry_clear_of_screen_buffers']
    assert r['sections']['areas']['completeness']['unexpected_ids'] == ['X']


def test_wrong_geometry_type_not_clear():
    a = _atlas()
    a['drifts'][0]['geometry'] = _sq(-121, 35.2)
    r = _run(a)
    assert r['sections']['drifts']['completeness']['wrong_geometry_type_ids'] == ['D0']
    assert not r['all_geometry_clear_of_screen_buffers']


def test_unbound_atlas_not_clear():
    assert not _run(_atlas(), ids=False)['all_geometry_clear_of_screen_buffers']


def test_digest_binding_clears_complete_atlas():
    mpa, fed = _sources()
    r = m.audit(_atlas(), mpa, fed, expected_atlas_sha256='ab', atlas_sha256='ab')
    assert r['all_geometry_clear_of_screen_buffers'] is True


def test_complete_fixture_with_held_feature():
    a = _atlas()
    a['targets'][3].update(longitude=-100.0, latitude=30.0005)  # inside a GEA square
    r = _run(a)
    assert r['sections']['targets']['held_ids'] == ['T3']
    assert r['sections']['targets']['completeness']['complete'] is True
    assert r['all_geometry_clear_of_screen_buffers'] is False
