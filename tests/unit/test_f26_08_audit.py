"""F26-08: CDFW ds3091 tiles must be bound to the reviewed grid origin and edition."""
import json
import sys

import pytest

pytest.importorskip('lerc')
pytest.importorskip('numpy')
pytest.importorskip('pyproj')
pytestmark = pytest.mark.gis

import lerc  # noqa: E402
import numpy as np  # noqa: E402

from research.scripts import audit_cdfw_substrate_tiles as m  # noqa: E402

TILE_M = 256 * m.RESOLUTION_M
SECTORS = {'sectors': [{'coast': 'northern', 'bounds': [-124.30, 40.75, -124.25, 40.80]}]}
CLASSES = {'features': [{'attributes': {'Value': 1, 'CLASSNAME': 'Hard'}},
                        {'attributes': {'Value': 2, 'CLASSNAME': 'Soft'}}]}


def service(origin=(m.ORIGIN[0], m.ORIGIN[1])):
    tile = {'format': 'LERC2D', 'rows': 256, 'cols': 256, 'spatialReference': {'wkid': 3310},
            'lods': [{'level': 7, 'resolution': 40}]}
    if origin is not None:
        tile['origin'] = {'x': origin[0], 'y': origin[1]}
    return {'name': 'biosds3091_cru', 'spatialReference': {'wkid': 3310}, 'tileInfo': tile}


def lerc_tile(code):
    data = np.full((256, 256), code, dtype=np.uint8)
    result, size, buffer = lerc.encode(data, 1, False, None, 0, 1)
    assert result == 0
    return buffer.raw[:size]


class Upstream:
    """Synthetic tile endpoint; no network."""

    def __init__(self, code=1):
        self.blob, self.calls = lerc_tile(code), []

    def __call__(self, request, timeout=None):
        self.calls.append(request.full_url)
        blob = self.blob

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return blob
        return Response()


@pytest.fixture
def run(tmp_path, monkeypatch):
    sectors = tmp_path / 'sectors.json'
    sectors.write_text(json.dumps(SECTORS))
    cache, output = tmp_path / 'cache', tmp_path / 'audit.json'

    def go(upstream, *extra, svc=None):
        monkeypatch.setattr(m, 'read_json', lambda url: CLASSES if 'rasterAttributeTable' in url else (svc or service()))
        monkeypatch.setattr(m.urllib.request, 'urlopen', upstream)
        monkeypatch.setattr(sys, 'argv', ['audit', '--sectors', str(sectors), '--cache', str(cache),
                                          '--output', str(output), '--workers', '2', *extra])
        m.main()
        return json.loads(output.read_text())
    go.cache, go.output = cache, output
    return go


def manifest(cache):
    return json.loads((cache / m.CACHE_MANIFEST).read_text())


def test_reviewed_origin_is_accepted():
    m.verify_service(service(), CLASSES)
    m.verify_service(service((m.ORIGIN[0] + 1e-6, m.ORIGIN[1])), CLASSES)


@pytest.mark.parametrize('origin, message', [
    ((m.ORIGIN[0] + TILE_M, m.ORIGIN[1]), 'differs'),
    ((m.ORIGIN[0], m.ORIGIN[1] - TILE_M), 'differs'),
    (None, 'missing'),
    (('', m.ORIGIN[1]), 'missing'),
], ids=['one-tile-east', 'one-tile-south', 'missing', 'non-numeric'])
def test_shifted_or_missing_origin_holds(origin, message):
    with pytest.raises(ValueError, match=f'origin {message}'):
        m.verify_service(service(origin), CLASSES)


def test_shifted_origin_holds_before_selection_and_leaves_cache(run, monkeypatch):
    upstream = Upstream()
    run(upstream, '--edition', 'reviewed-A')
    before = {p: p.read_bytes() for p in run.cache.rglob('*') if p.is_file()}
    upstream.calls.clear()
    monkeypatch.setattr(m, 'sector_tiles', lambda sectors: pytest.fail('tiles selected on an unreviewed grid'))
    with pytest.raises(ValueError, match='origin differs'):
        run(upstream, '--edition', 'reviewed-A', svc=service((m.ORIGIN[0] + TILE_M, m.ORIGIN[1])))
    assert upstream.calls == []
    assert {p: p.read_bytes() for p in run.cache.rglob('*') if p.is_file()} == before


def test_cache_from_another_grid_or_unbound_cache_is_not_reused(tmp_path):
    old = m.grid_identity('reviewed-A')
    old['origin'] = [m.ORIGIN[0] + TILE_M, m.ORIGIN[1]]
    other = tmp_path / 'other'
    other.mkdir()
    m.seal_cache(other, old)
    with pytest.raises(ValueError, match='different grid'):
        m.bind_cache(other, m.grid_identity('reviewed-A'))
    assert manifest(other) == old

    legacy = tmp_path / 'legacy'
    (legacy / '7' / '1').mkdir(parents=True)
    (legacy / '7' / '1' / '2.lerc').write_bytes(lerc_tile(2))
    with pytest.raises(ValueError, match='no grid identity'):
        m.bind_cache(legacy, m.grid_identity('reviewed-A'))
    assert not (legacy / m.CACHE_MANIFEST).exists()


def test_matching_immutable_edition_reuses_cache(run):
    first = Upstream(code=1)
    audit = run(first, '--edition', 'reviewed-A')
    assert first.calls and audit['cache_reused'] is False
    assert manifest(run.cache) == m.grid_identity('reviewed-A') == audit['grid_identity']

    again = Upstream(code=2)
    reused = run(again, '--edition', 'reviewed-A')
    assert again.calls == [] and reused['cache_reused'] is True
    assert [t['sha256'] for t in reused['tiles']] == [t['sha256'] for t in audit['tiles']]
    assert reused['coasts']['northern']['soft_cells'] == 0


@pytest.mark.parametrize('extra, edition', [(('--edition', 'reviewed-B'), 'reviewed-B'), ((), None)],
                         ids=['new-edition', 'unpinned'])
def test_other_or_unpinned_edition_refetches(run, extra, edition):
    run(Upstream(code=1), '--edition', 'reviewed-A')
    fresh = Upstream(code=2)
    audit = run(fresh, *extra)
    assert len(fresh.calls) == audit['requested_tiles'] and audit['cache_reused'] is False
    assert audit['coasts']['northern']['hard_cells'] == 0
    assert manifest(run.cache)['edition'] == edition


def test_failed_run_does_not_seal_edition(run):
    bad = Upstream()
    bad.blob = b'not a tile'
    with pytest.raises(SystemExit):
        run(bad, '--edition', 'reviewed-A')
    assert manifest(run.cache)['edition'] is None
    good = Upstream()
    run(good, '--edition', 'reviewed-A')
    assert good.calls
