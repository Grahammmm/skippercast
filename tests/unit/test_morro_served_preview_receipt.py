"""Served-build receipt: the assembled Morro preview tree is read back over loopback HTTP and bound to its manifest."""
from hashlib import sha256
import json
import shutil

import pytest

from scripts.relief import morro_preview_assets as assets
from scripts.relief import morro_served_preview_receipt as served

BUILD = '0123456789'
POINTER = json.dumps({'region': 'morro-bay', 'status': 'reviewed', 'envelope_sha256': 'e' * 63 + 'f'}).encode()
DETAIL = b'{"type":"FeatureCollection","features":[2]}'
OVERVIEW = b'{"type":"FeatureCollection","features":[3]}'
SOURCES = b'<!doctype html><main>Credits: NOAA topobathy, BlueTopo; ft-v3 contours</main>'
APP = b'<!doctype html><div id="app"></div>'


def _sha(raw):
    return sha256(raw).hexdigest()


def _write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _manifest(out):
    manifest = {
        'schema': assets.MANIFEST_SCHEMA, 'region': 'morro-bay', 'publication_signature': None,
        'identity_sha256': '1' * 63 + '2', 'envelope_sha256': 'e' * 63 + 'f', 'release_sha256': 'b' * 63 + 'c',
        'generation': 'a' * 63 + 'd', 'build': BUILD, 'sources_shell': f'client/sources.{BUILD}.html',
        'candidate': {'pointer': _sha(POINTER), 'catalog_contours': '9' * 63 + '8', 'detail': _sha(DETAIL), 'overview': _sha(OVERVIEW)},
        'served': {'/catalog/relief/morro-bay.json': 'pointer', '/regions/morro-bay/depth-contours.geojson': 'detail',
                   '/regions/morro-bay/depth-contours-overview.geojson': 'overview', '/sources': f'client/sources.{BUILD}.html'},
        'files': assets._files(out),
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return manifest


@pytest.fixture
def tree(tmp_path):
    out = tmp_path / 'preview-assets'
    client = out / 'client'
    _write(client / 'catalog/relief/morro-bay.json', POINTER)
    _write(client / 'regions/morro-bay/depth-contours.geojson', DETAIL)
    _write(client / 'regions/morro-bay/depth-contours-overview.geojson', OVERVIEW)
    _write(client / f'sources.{BUILD}.html', SOURCES)
    _write(client / f'app.{BUILD}.html', APP)
    _write(out / 'server/index.js', b'export default {}')
    _manifest(out)
    return out


def test_receipt_binds_pointer_contours_and_credits_over_http(tree):
    receipt = served.receipt_for(tree)
    assert receipt['schema'] == served.RECEIPT_SCHEMA and receipt['publication_signature'] is None
    assert receipt['manifest_sha256'] == _sha((tree / 'manifest.json').read_bytes())
    want = {'/catalog/relief/morro-bay.json': POINTER, '/regions/morro-bay/depth-contours.geojson': DETAIL,
            '/regions/morro-bay/depth-contours-overview.geojson': OVERVIEW}
    for path, raw in want.items():
        row = receipt['served'][path]
        assert row['status'] == 200 and row['sha256'] == row['pinned'] == _sha(raw) and '_body' not in row
    assert receipt['sources']['status'] == 200 and receipt['sources']['sha256'] == _sha(SOURCES)
    assert receipt['app_shell']['sha256'] == _sha(APP)
    assert receipt['absent_probe']['status'] == 404  # the Worker's answer for an unknown asset


def test_cli_writes_new_receipt_and_refuses_overwrite(tree, tmp_path, capsys):
    out = tmp_path / 'receipt.json'
    assert served.main(['--assets', str(tree), '--receipt', str(out)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary['receipt_sha256'] == _sha(out.read_bytes()) and summary['build'] == BUILD
    before = out.read_bytes()
    assert served.main(['--assets', str(tree), '--receipt', str(out)]) == 2
    assert 'already exists' in capsys.readouterr().err and out.read_bytes() == before


@pytest.fixture
def host(tree, tmp_path, monkeypatch):
    """A host that serves its own copy of client/ (a stale or partial deployment), while the tree on disk is right."""
    copy = tmp_path / 'host-client'
    shutil.copytree(tree / 'client', copy)
    real = served.serve
    monkeypatch.setattr(served, 'serve', lambda client, build_id, miss='404': real(copy, build_id, miss))
    return copy


def test_disk_assets_missing_from_their_pins_are_refused_before_serving(tree, monkeypatch):
    # A tree that lost an asset (with its manifest rows regenerated) fails the manifest's candidate pins first.
    (tree / 'client/regions/morro-bay/depth-contours-overview.geojson').unlink()
    _manifest(tree)
    monkeypatch.setattr(served, 'serve', lambda *a: pytest.fail('served a tree that fails its manifest'))
    with pytest.raises(assets.Held, match='not the pinned overview'):
        served.receipt_for(tree)


@pytest.mark.parametrize('missing', ['regions/morro-bay/depth-contours-overview.geojson', 'catalog/relief/morro-bay.json'])
def test_app_shell_fallback_for_a_missing_asset_is_refused(tree, host, tmp_path, capsys, missing):
    # The host lacks the asset and, like a single-page host, answers HTTP 200 with the app shell.
    (host / missing).unlink()
    with pytest.raises(served.Held, match='HTML page'):
        served.receipt_for(tree, miss='app-shell')
    receipt = tmp_path / 'receipt.json'
    assert served.main(['--assets', str(tree), '--receipt', str(receipt), '--miss', 'app-shell']) == 2
    assert 'app-shell fallback' in capsys.readouterr().err and not receipt.exists()


def test_missing_asset_on_worker_like_host_is_refused(tree, host):
    (host / 'regions/morro-bay/depth-contours.geojson').unlink()
    with pytest.raises(served.Held, match='depth-contours.geojson: HTTP 404'):
        served.receipt_for(tree)


def test_present_assets_pass_even_on_a_single_page_host(tree):
    receipt = served.receipt_for(tree, miss='app-shell')
    assert receipt['absent_probe']['status'] == 200 and receipt['absent_probe']['sha256'] == _sha(APP)
    assert all(row['sha256'] == row['pinned'] for row in receipt['served'].values())


@pytest.mark.parametrize('path, raw, message', [
    ('regions/morro-bay/depth-contours.geojson', b'{"type":"FeatureCollection","features":[9]}', 'not the pinned detail'),
    ('catalog/relief/morro-bay.json', POINTER.replace(b'"reviewed"', b'"draft"'), 'not the pinned pointer'),
    ('regions/morro-bay/depth-contours-overview.geojson', APP, 'HTML page'),
    (f'sources.{BUILD}.html', b'<!doctype html><main>stale v1 credits</main>', 'pinned credits shell'),
])
def test_served_bytes_that_differ_from_the_pins_are_refused(tree, host, path, raw, message):
    (host / path).write_bytes(raw)
    with pytest.raises(served.Held, match=message):
        served.receipt_for(tree)


def test_stale_credits_on_disk_are_refused_by_the_manifest(tree):
    (tree / f'client/sources.{BUILD}.html').write_bytes(b'<!doctype html><main>stale v1 credits</main>')
    with pytest.raises(assets.Held, match='differ from the manifest'):
        served.receipt_for(tree)


def test_stale_credits_in_the_response_are_refused(tree):
    # The tree on disk is right, but the host answered /sources with other bytes.
    manifest = json.loads((tree / 'manifest.json').read_bytes())
    stale = b'<!doctype html><main>stale v1 credits</main>'
    responses = {p: {'status': 200, 'content_type': 'application/json', 'sha256': manifest['candidate'][k], '_body': b'{}'}
                 for p, k in served.DATA_PATHS.items()}
    responses['/sources'] = {'status': 200, 'content_type': 'text/html', 'sha256': _sha(stale), '_body': stale}
    responses['/map'] = {'status': 200, 'content_type': 'text/html', 'sha256': _sha(APP), '_body': APP}
    problems = served.check_responses(manifest, responses)
    assert problems == [p for p in problems if p.startswith('/sources:')] and 'pinned credits shell' in problems[0]


def test_tampered_tree_is_refused_before_serving(tree, monkeypatch):
    (tree / 'client/regions/morro-bay/depth-contours.geojson').write_bytes(b'{}')
    monkeypatch.setattr(served, 'serve', lambda *a: pytest.fail('served a tree that fails its manifest'))
    with pytest.raises(assets.Held, match='differ from the manifest'):
        served.receipt_for(tree)


def test_non_loopback_origin_is_refused():
    with pytest.raises(served.Held, match='loopback'):
        served.fetch('http://example.com', '/sources')


def test_manifest_that_serves_a_path_as_something_else_is_refused(tree):
    manifest = json.loads((tree / 'manifest.json').read_bytes())
    manifest['served']['/regions/morro-bay/depth-contours.geojson'] = 'overview'
    (tree / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    with pytest.raises(served.Held, match='is not served as detail'):
        served.receipt_for(tree)
