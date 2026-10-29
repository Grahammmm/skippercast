"""Synthetic local C2/C1/C5 adapter checks; never acquire source data."""
import hashlib
import json

import pytest

from research.scripts.coast_mvp import coast_manifest


def save(path, value):
    path.write_text(json.dumps(value))
    return path


def inputs(tmp_path):
    c2 = tmp_path / 'c2'
    c2.mkdir()
    save(c2 / 'manifest.json', dict(
        schema_version=1, status='review_required', zoom=12, terrain_tiles=1,
        contour_features=1, value_convention='elevation_positive_up',
        contour_crs='EPSG:4326', tile_scheme='XYZ',
        terrain_template='terrain/{z}/{x}/{y}.png', vector_template='vector/{z}/{x}/{y}.pbf'))
    for kind, suffix in [('terrain', 'png'), ('vector', 'pbf')]:
        path = c2 / kind / '12/671'
        path.mkdir(parents=True)
        (path / f'1616.{suffix}').write_bytes(b'synthetic asset bytes')
    save(c2 / 'contours.geojson', dict(type='FeatureCollection', features=[dict(
        type='Feature', geometry=dict(type='LineString', coordinates=[[-121, 35.44], [-121, 35.45]]),
        properties=dict(source_code=1, source_id='fixture', source_resolution_m=2,
                        depth_ft=10, depth_m=3.048))]))
    c1 = save(tmp_path / 'c1.json', dict(
        schema_version=1, units='m', value_convention='elevation_positive_up',
        contributor_cells={'1': 4}, stats={'valid_cells': 4}, sources=[dict(
            code=1, id='fixture', resolution_m=2, vertical_datum='unstated',
            offset_note='No datum reconciliation', citation='https://example.org/source',
            rights='Unknown terms; review required', attribution='Synthetic author', sha256='a' * 64)]))
    rights = save(tmp_path / 'rights.json', dict(schema_version=1, fixture_only=True, sources=[dict(
        source_id='fixture', name='Synthetic source', source_url='https://example.org/source',
        sha256='a' * 64, contributed_cells=4, rights=dict(
            license='Unknown terms; review required', terms_url='https://example.org/terms',
            attribution='Synthetic author', csumb_involved=False))]))
    return c2, c1, rights


def test_exports_local_viewer_contract_with_complete_held_provenance(tmp_path):
    c2, c1, rights = inputs(tmp_path)
    before = (c2 / 'contours.geojson').read_bytes()
    result = coast_manifest.build(c2, c1, rights, region='Synthetic demo', synthetic=True)
    assert result['schemaVersion'] == 1
    assert result['synthetic'] is True
    assert result['terrain'] == 'terrain/{z}/{x}/{y}.png'
    assert result['contours'] == 'vector/{z}/{x}/{y}.pbf'
    assert result['contourLayer'] == 'contours'
    assert result['tileSize'] == 256 and result['tileZoom'] == 12
    assert result['status'] == 'review_required'
    assert result['publicationHeld'] is True
    source = result['sources'][0]
    assert source['sha256'] == 'a' * 64
    assert source['datum'] == 'unstated'
    assert source['resolutionM'] == 2
    assert source['permissionRequired'] is True
    assert source['attribution'] == 'Synthetic author'
    assert source['termsUrl'] == 'https://example.org/terms'
    assert result['provenance']['c1Sha256'] == hashlib.sha256(c1.read_bytes()).hexdigest()
    assert json.loads((c2 / 'viewer-manifest.json').read_text()) == result
    assert (c2 / 'contours.geojson').read_bytes() == before


def test_c2_fixture_cannot_be_relabelled_measured(tmp_path):
    c2, c1, rights = inputs(tmp_path)
    manifest = json.loads((c2 / 'manifest.json').read_text())
    manifest['fixture_only'] = True
    save(c2 / 'manifest.json', manifest)
    manifest = json.loads(rights.read_text())
    manifest.pop('fixture_only')
    save(rights, manifest)
    with pytest.raises(ValueError, match='Synthetic fixture'):
        coast_manifest.build(c2, c1, rights, region='demo', synthetic=False)
    assert not (c2 / 'viewer-manifest.json').exists()


@pytest.mark.parametrize('field', ['sha256', 'contributed_cells', 'source_url', 'rights'])
def test_missing_rights_fails_before_output(tmp_path, field):
    c2, c1, rights = inputs(tmp_path)
    manifest = json.loads(rights.read_text())
    del manifest['sources'][0][field]
    save(rights, manifest)
    with pytest.raises(ValueError):
        coast_manifest.build(c2, c1, rights, region='demo', synthetic=True)
    assert not (c2 / 'viewer-manifest.json').exists()


@pytest.mark.parametrize('field,value', [('sha256', 'b' * 64), ('contributed_cells', 3),
                                        ('source_url', 'https://example.org/other')])
def test_mismatched_rights_refused(tmp_path, field, value):
    c2, c1, rights = inputs(tmp_path)
    manifest = json.loads(rights.read_text())
    manifest['sources'][0][field] = value
    save(rights, manifest)
    with pytest.raises(ValueError, match='mismatch'):
        coast_manifest.build(c2, c1, rights, region='demo', synthetic=True)


def test_all_terrain_contributors_included_even_without_contours(tmp_path):
    c2, c1, rights = inputs(tmp_path)
    native, inventory = json.loads(c1.read_text()), json.loads(rights.read_text())
    native['sources'].append(dict(native['sources'][0], code=2, id='terrain-only'))
    native['contributor_cells']['2'] = 3
    native['stats']['valid_cells'] = 7
    inventory['sources'].append(dict(inventory['sources'][0], source_id='terrain-only', contributed_cells=3))
    inventory['sources'].append(dict(source_id='unused', contributed_cells=0))
    save(c1, native)
    save(rights, inventory)
    result = coast_manifest.build(c2, c1, rights, region='demo', synthetic=True)
    assert [s['id'] for s in result['sources']] == ['fixture', 'terrain-only']
    assert all(s['permissionRequired'] for s in result['sources'])


def test_csumb_hold_detected_even_with_false_flag(tmp_path):
    c2, c1, rights = inputs(tmp_path)
    manifest = json.loads(rights.read_text())
    manifest['sources'][0]['name'] = 'CSUMB synthetic co-production'
    save(rights, manifest)
    source = coast_manifest.build(c2, c1, rights, region='demo', synthetic=True)['sources'][0]
    assert source['rightsStatus'] == 'needs_permission'
    assert source['csumbInvolved'] and source['permissionRequired']


@pytest.mark.parametrize('template', ['https://foreign.example/{z}/{x}/{y}.png',
                                    '//foreign.example/a', '../terrain.png', '/terrain.png',
                                    'terrain/%2e%2e/{z}.png', 'terrain.png?url=https://x'])
def test_remote_or_escaping_templates_refused(tmp_path, template):
    c2, c1, rights = inputs(tmp_path)
    manifest = json.loads((c2 / 'manifest.json').read_text())
    manifest['terrain_template'] = template
    save(c2 / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='local tile templates'):
        coast_manifest.build(c2, c1, rights, region='demo', synthetic=True)


def test_symlink_asset_refused(tmp_path):
    c2, c1, rights = inputs(tmp_path)
    tile = c2 / 'terrain/12/671/1616.png'
    tile.unlink()
    tile.symlink_to(c1)
    with pytest.raises(ValueError, match='Local regular asset'):
        coast_manifest.build(c2, c1, rights, region='demo', synthetic=True)


@pytest.mark.parametrize('coordinates', [[[float('nan'), 35.44], [-121, 35.45]],
                                         [[-181, 35.44], [-121, 35.45]],
                                         [[True, 35.44], [-121, 35.45]]])
def test_nonfinite_or_out_of_bounds_geometry_refused(tmp_path, coordinates):
    c2, c1, rights = inputs(tmp_path)
    path = c2 / 'contours.geojson'
    manifest = json.loads(path.read_text())
    manifest['features'][0]['geometry']['coordinates'] = coordinates
    save(path, manifest)
    with pytest.raises(ValueError, match='finite tile bounds'):
        coast_manifest.build(c2, c1, rights, region='demo', synthetic=True)


@pytest.mark.parametrize('field,value', [('depth_m', 10), ('source_code', 3),
                                        ('source_resolution_m', 10), ('source_id', 'other')])
def test_contour_units_and_provenance_refused(tmp_path, field, value):
    c2, c1, rights = inputs(tmp_path)
    path = c2 / 'contours.geojson'
    manifest = json.loads(path.read_text())
    manifest['features'][0]['properties'][field] = value
    save(path, manifest)
    with pytest.raises(ValueError):
        coast_manifest.build(c2, c1, rights, region='demo', synthetic=True)


def test_existing_output_never_overwritten(tmp_path):
    c2, c1, rights = inputs(tmp_path)
    coast_manifest.build(c2, c1, rights, region='demo', synthetic=True)
    before = (c2 / 'viewer-manifest.json').read_bytes()
    with pytest.raises(FileExistsError):
        coast_manifest.build(c2, c1, rights, region='changed', synthetic=True)
    assert (c2 / 'viewer-manifest.json').read_bytes() == before


def test_measured_stays_held_and_cli_requires_explicit_mode(tmp_path, capsys):
    c2, c1, rights = inputs(tmp_path)
    manifest = json.loads(rights.read_text())
    manifest.pop('fixture_only')
    save(rights, manifest)
    with pytest.raises(SystemExit) as exc:
        coast_manifest.main(['--c2-dir', str(c2), '--c1-manifest', str(c1),
                             '--rights-manifest', str(rights), '--region', 'demo'])
    assert exc.value.code == 2
    assert coast_manifest.main(['--c2-dir', str(c2), '--c1-manifest', str(c1),
                                '--rights-manifest', str(rights), '--region', 'demo', '--measured']) == 0
    result = json.loads((c2 / 'viewer-manifest.json').read_text())
    assert result['synthetic'] is False and result['publicationHeld']
    assert result['sources'][0]['permissionRequired']
    assert 'publication held' in capsys.readouterr().out
