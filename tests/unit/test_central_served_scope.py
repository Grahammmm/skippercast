"""C40 distinct failure surfaces: disk scope, transport behavior and served bytes."""
from types import SimpleNamespace

import pytest

from scripts.relief import central_served_scope as scope


def fixture(tree):
    regions = sorted(scope.REGIONS)
    pointer_paths = {f'/catalog/relief/{region}.json' for region in regions}
    contours = {f'/regions/{region}/depth-contours{s}.geojson'
                for region in scope.CONTOUR for s in scope.SUFFIXES}
    static = {path: scope.digest(path.encode()) for path in pointer_paths | contours}
    for path in static:
        file = tree / 'client' / path.lstrip('/')
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(path.encode())
    overlay = scope.digest(b'prebuild credits')
    fingerprint = '35ef08a2c1'
    shell = f'client/sources.{fingerprint}.html'
    result = {'schema': 'sc-central-local-scope/1', 'regions': regions, 'routes': {**static, '/sources': overlay}}
    manifest = {'schema': 'sc-central-stage-tree/1', 'regions': regions, 'build': fingerprint,
                'pinned': static, 'sources_overlay_html_sha256': overlay, 'sources_shell': shell,
                'served': {**{p: f'client{p}' for p in static}, '/sources': shell},
                'files': {**{f'client{k}': {'sha256': v} for k, v in static.items()},
                          shell: {'sha256': scope.digest(b'built credits')}}}
    return result, manifest


def test_scope_refuses_unmanifested_neighbor_even_without_neighbor_in_pinned_table(tmp_path):
    reference, manifest = fixture(tmp_path)
    extra = tmp_path / 'client/regions/neighbor/depth-contours.geojson'
    extra.parent.mkdir(parents=True)
    extra.write_bytes(b'{}')
    with pytest.raises(ValueError, match='extra=.*neighbor/depth-contours'):
        scope.check(tmp_path, reference, manifest, 1)


@pytest.mark.parametrize(('route', 'status', 'data', 'failure'), [
    ('/sources', 200, b'old prebuild credits', '/sources: expected exact pinned bytes'),
    ('/catalog/relief/morro-bay.json', 200, b'fallback', 'must be absent'),
    ('/catalog/relief/big-sur-coast.json', 302, b'', 'received HTTP 302'),
])
def test_refuses_wrong_http_result_even_when_disk_inventory_is_correct(tmp_path, monkeypatch,
                                                                   route, status, data, failure):
    reference, manifest = fixture(tmp_path)
    projected = {p: (200, scope.digest(p.encode())) for p in manifest['pinned']}
    projected['/sources'] = (200, scope.digest(b'built credits'))
    monkeypatch.setattr(scope, 'fetch', lambda port, path: (status, scope.digest(data)) if route == path
                        else projected.get(path, (404, None)))
    with pytest.raises(ValueError, match=failure):
        scope.check(tmp_path, reference, manifest, 1)


def test_rejects_html_body_served_as_json(monkeypatch):
    from io import BytesIO
    from contextlib import nullcontext

    body = BytesIO(b' \n<!doctype html><h1>App shell</h1>')
    response = SimpleNamespace(status=200, read=body.read, getheader=lambda key, default: default)
    connection = SimpleNamespace(request=lambda *a, **k: None, getresponse=lambda: nullcontext(response), close=lambda: None)
    monkeypatch.setattr(scope, 'HTTPConnection', lambda *a, **k: connection)
    with pytest.raises(ValueError, match='HTTP 200 HTML fallback'):
        scope.fetch(1, '/catalog/relief/big-sur-coast.json')
