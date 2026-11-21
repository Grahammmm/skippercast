"""C1–C3: prove the HEAD-bound full contours projection through the loopback site."""
from argparse import Namespace
from http.client import HTTPResponse
import json

import pytest

from skippercast.relief import live_check
from tests.unit.test_relief_live_check import (
    CONTOURS, POINTER, REGION, argv, commit, encoded, git, report, row, trace, verified,
)

pytest_plugins = ('tests.unit.test_relief_live_check',)

CATALOG = f'catalog/depth-contours/{REGION}.geojson'


@pytest.fixture
def projection(checkout):
    bounds = [-121, 35, -120, 36]
    source = dict(id='fixture-survey', review_status='approved', needs=['bathymetry'], reviewed_at='2024-01-10')
    omitted = dict(id='fixture-omitted', review_status='candidate', needs=['bathymetry'])
    definition = dict(id=REGION, bounds=bounds, source_bindings={'bathymetry': [source['id'], omitted['id']]})
    provenance = dict(region_id=REGION, features=1, interval_ft=30, shelf_limit_ft=600, units='ft', bounds=bounds,
                      sources=[dict(source_id=source['id'], sha256='f' * 64, survey_date='2020', vertical_datum='MLLW')])
    contour = dict(type='Feature', id='fixture-30', properties=dict(kind='contour', source_id=source['id'],
                   depth_ft=30, index=False, survey_date='2020', vertical_datum='MLLW'),
                   geometry=dict(type='LineString', coordinates=[[-120.8, 35.1], [-120.7, 35.2]]))
    collection = dict(type='FeatureCollection', provenance=provenance, features=[contour])
    raw = encoded(collection)
    for name, content in ((CATALOG, raw), (f'regions/{REGION}/region.json', encoded(definition)),
                          ('catalog/sources.json', encoded(dict(schema_version=1, sources=[source, omitted])))):
        path = checkout.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    commit(checkout.repo, 'Merged contours fixture')
    # A clean status alone does not prove that checkout file bytes equal HEAD.
    git(checkout.repo, 'update-index', '--skip-worktree', CATALOG)
    (checkout.repo / CATALOG).write_bytes(b'not the HEAD blob')
    assert git(checkout.repo, 'status', '--porcelain') == ''
    stamped = dict(provenance, review_expires='2025-01-09', review_days=365,
                   sources_omitted=[dict(source_id=omitted['id'], review_status='candidate')])
    deployed = json.dumps(dict(collection, provenance=stamped), separators=(',', ':')).encode() + b'\n'
    return raw, deployed


@pytest.mark.parametrize('case, reason', [
    pytest.param('exact', 'identical', id='C1: identical full projection'),
    pytest.param('catalog', 'differs', id='C1: raw catalog is not the projection'),
    pytest.param('whitespace', 'differs', id='C1: one extra byte is not identical'),
    pytest.param('missing', 'missing', id='C1: merged but 404'),
    pytest.param('oversize', 'oversize', id='C1: two extra bytes cross the bounded read limit'),
])
def test_C1_projected_bytes(checkout, release, site, projection, monkeypatch, case, reason):
    """C1: Comparing parsed JSON, raw catalog/worktree bytes, or reading an entire body is wrong."""
    raw, expected = projection
    sizes = []
    read = HTTPResponse.read

    def observe(response, size=None):
        if response.getheader('X-Fixture-Contours') == 'yes':
            sizes.append(size)
        return read(response, size)

    monkeypatch.setattr(HTTPResponse, 'read', observe)
    bodies = dict(exact=expected, catalog=raw, whitespace=expected + b' ', oversize=expected + b' ' * 4096)
    if case != 'missing':
        site.responses[CONTOURS] = 200, {'X-Fixture-Contours': 'yes'}, bodies[case]
    passed = case == 'exact'
    assert live_check.main(argv(checkout, site)) == (0 if passed else 1)
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, checkout.deployed, verified(release) + [row('contours', reason, key=CONTOURS, fail=not passed)],
        'PASS' if passed else 'FAIL', 8)
    assert site.requests == trace('deploy.json', POINTER, release.archive, release.root, *release.chunks, CONTOURS)
    if case == 'oversize':
        assert sizes == [len(expected) + 2]


@pytest.mark.parametrize('status, reason', [
    pytest.param(404, 'none-merged', id='C2: absent in both locations'),
    pytest.param(200, 'unexpected', id='C2: unmerged but served'),
    pytest.param(302, 'redirect', id='C2: redirected absence is not a 404'),
])
def test_C2_no_merged_blob(checkout, release, site, status, reason):
    """C2: Local absence alone is no proof; following a redirect could falsely establish absence."""
    if status != 404:
        site.responses[CONTOURS] = status, {'Location': '/not-allowed'}, b''
    passed = status == 404
    check = 'fetch' if status == 302 else 'contours'
    assert live_check.main(argv(checkout, site)) == (0 if passed else 1)
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, checkout.deployed, verified(release) + [row(check, reason, key=CONTOURS, fail=not passed)],
        'PASS' if passed else 'FAIL', 8)
    assert site.requests == trace('deploy.json', POINTER, release.archive, release.root, *release.chunks, CONTOURS)


def test_C1_mismatched_region_identity_is_local_refusal(checkout, site, projection):
    """C1: The writer must not select a different contours input based on a mismatched region ID."""
    (checkout.repo / f'regions/{REGION}/region.json').write_bytes(encoded(dict(id='other-region')))
    commit(checkout.repo, 'Mismatched region identity')
    args = Namespace(region=REGION, base=site.base, repo=checkout.repo, out=checkout.out)
    with pytest.raises(live_check.LocalError) as error:
        live_check._run(args)
    assert (type(error.value), str(error.value), site.requests, checkout.report.exists()) == (
        live_check.LocalError, 'region directory and id differ in HEAD', [], False)


@pytest.mark.parametrize('extra', [
    pytest.param(0, id='C3: contours is the twentieth operation'),
    pytest.param(1, id='C3: contours cannot become a twenty-first operation'),
])
def test_C3_contours_respects_total_budget(checkout, release, site, monkeypatch, extra):
    """C3: Reserve a request for contours and refuse it if a chain caller uses that slot anyway."""
    keys = [f'fixture/{i}' for i in range(16 + extra)]
    for key in keys:
        site.responses[key] = 200, {}, b'x'
    index_rows = [row('chunk', '', key=key) for key in keys]

    def archive(pointer, fetch, *, budget):
        assert (pointer, budget) == (release.pointer, 16)
        for key in keys:
            assert b''.join(fetch(key, max_bytes=1)) == b'x'
        return index_rows

    monkeypatch.setattr(live_check.live_archive, 'check_archive', archive)
    end = row('fetch', 'budget', key=CONTOURS, fail=True) if extra else row('contours', 'none-merged', key=CONTOURS)
    assert live_check.main(argv(checkout, site)) == extra
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, checkout.deployed, verified(release)[:2] + index_rows + [end], 'FAIL' if extra else 'PASS', 20)
    tail = () if extra else (CONTOURS,)
    assert site.requests == trace('deploy.json', POINTER, *keys, *tail)
