"""C39: a correct-looking build is not enough if one region's inputs cross."""
import json

import pytest

from scripts.relief import central_preview_tree as preview


def write(root, path, raw):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(raw)


def fixture(root):
    pins = {'regions': {}}
    bundle = {'schema': 'sc-central-preview-bundle/1', 'regions': {}, 'sources_page_sha256': 'credits'}
    for region in preview.CENTRAL_RELEASES:
        terrain = region in preview.TERRAIN_ONLY
        row = {'schema': 'sc-relief-pointer/1', 'region': region, 'private': False,
               'generation': f'g-{region}', 'release_sha256': f'r-{region}', 'envelope_sha256': f'e-{region}'}
        assets = {'pointer': (f'catalog/relief/{region}.json', json.dumps(row).encode())}
        if not terrain:
            for role, name in preview.CONTOURS.items():
                assets[role] = (f'regions/{region}/{name}', f'{region} {role}'.encode())
        row['kind'] = 'terrain-only' if terrain else 'terrain+contours'
        row['served'] = {'/sources': {'sha256': 'credits'}}
        pin = pins['regions'][region] = {}
        for role, (path, raw) in assets.items():
            write(root, path if role == 'pointer' else f'dist/{path}', raw)
            pin[role] = preview.digest(raw)
            row['served'][f'/{path}'] = {'sha256': pin[role]}
        bundle['regions'][region] = row
    return pins, bundle


def test_rejects_neighbor_envelope_even_with_matching_file_pin(tmp_path):
    pins, bundle = fixture(tmp_path)
    assert len(preview.candidate(tmp_path, pins, bundle)) == 14
    bundle['regions']['big-sur-coast']['envelope_sha256'] = bundle['regions']['cambria-san-simeon']['envelope_sha256']
    with pytest.raises(ValueError, match='big-sur-coast: pointer does not identify'):
        preview.candidate(tmp_path, pins, bundle)


def test_terrain_only_file_not_listed_by_pins_still_fails(tmp_path):
    pins, bundle = fixture(tmp_path)
    write(tmp_path, 'dist/regions/monterey-point-sur/depth-contours.geojson', b'{"neighbor": true}')
    with pytest.raises(ValueError, match='monterey-point-sur: terrain-only'):
        preview.candidate(tmp_path, pins, bundle)


def test_candidate_credits_must_survive_client_fingerprinting(tmp_path):
    begin, end = preview.sources.register.BEGIN.encode(), preview.sources.register.END.encode()
    page = begin + b'shading credit' + end
    build = '3a132db110'
    write(tmp_path, 'precache.json', json.dumps({'build': build}).encode())
    write(tmp_path, f'sources.{build}.html', b'<!doctype html>' + page)
    assert preview.check_client(tmp_path, {}, page, {}) == (build, f'sources.{build}.html')
    write(tmp_path, f'sources.{build}.html', begin + b'stale contour credit' + end)
    with pytest.raises(ValueError, match='stale credits'):
        preview.check_client(tmp_path, {}, page, {})


def test_client_rejects_contour_index_that_disagrees_with_pinned_files(tmp_path):
    # The Chart skips unlisted files even if the exact GeoJSON is on disk.
    pins, bundle = fixture(tmp_path / 'input')
    snapshot = preview.candidate(tmp_path / 'input', pins, bundle)
    client = tmp_path / 'client'
    page = preview.sources.register.BEGIN.encode() + preview.sources.register.END.encode()
    build = '3a132db110'
    write(client, 'precache.json', json.dumps({'build': build}).encode())
    write(client, f'sources.{build}.html', page)
    for path, raw in snapshot.items():
        write(client, path, raw)
    for region in preview.CENTRAL_RELEASES:
        files = ['shoreline.geojson']
        if region not in preview.TERRAIN_ONLY:
            files += list(preview.CONTOURS.values())
        write(client, f'regions/{region}/region.json', json.dumps({'id': region, 'chart_files': files}).encode())
    assert preview.check_client(client, snapshot, page, {}) == (build, f'sources.{build}.html')
    for region, files in [('cambria-san-simeon', ['depth-contours.geojson']),
                          ('monterey-point-sur', ['depth-contours-overview.geojson'])]:
        path = f'regions/{region}/region.json'
        original = (client / path).read_bytes()
        write(client, path, json.dumps({'id': region, 'chart_files': files}).encode())
        with pytest.raises(ValueError, match=rf'{region}: .*chart_files'):
            preview.check_client(client, snapshot, page, {})
        write(client, path, original)


def test_vite_checkout_paths_do_not_change_asset_identity(tmp_path):
    outputs = []
    for name in ('first', 'second'):
        repo = tmp_path / name
        css = f'{repo}/web/chart.css'
        write(repo, 'client/.vite/manifest.json', json.dumps({css: {'src': css, 'file': 'assets/chart.a12.css'}}).encode())
        preview.normalize_vite_index(repo / 'client', repo)
        outputs.append((repo / 'client/.vite/manifest.json').read_bytes())
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0]) == {'web/chart.css': {'src': 'web/chart.css', 'file': 'assets/chart.a12.css'}}
