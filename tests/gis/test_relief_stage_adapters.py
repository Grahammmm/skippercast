"""Offline R4/R5 integration through region.py on the shared tiny raster fixture."""
import gzip
import json
import runpy
import shutil
import struct
import subprocess
import sys
from types import SimpleNamespace

import pytest

from skippercast.relief import envelope, mosaic, package, receipts
from tests._support import FIXTURES, ROOT

pytestmark = pytest.mark.gis


def write_json(path, document):
    path.write_bytes(receipts.canonical(document) + b'\n')


def pmtiles_metadata(path):
    with path.open('rb') as stream:
        assert stream.read(8) == b'PMTiles\x03'
        stream.seek(24)
        offset, length = struct.unpack('<QQ', stream.read(16))
        stream.seek(offset)
        return json.loads(gzip.decompress(stream.read(length)))


def test_public_stage_chain(tmp_path, monkeypatch, capsys):
    # Existing builder tests qualify the individual GIS transforms. This exercises their
    # real handoffs: wrong receipt dependencies, builder inputs or stage targets break the chain.
    np = pytest.importorskip('numpy')
    rio = pytest.importorskip('rasterio')
    from rasterio.warp import transform_bounds
    geom = pytest.importorskip('shapely.geometry')

    tiny = runpy.run_path(str(FIXTURES / 'relief/tiny/tiny_region.py'))
    main = runpy.run_path(str(ROOT / 'scripts/relief/region.py'))['main']
    region = receipts.Region(tmp_path / 'out', 'tiny')
    grid = tiny['write_grids'](region.dir / 'raw')['projected_1m.tif']
    with rio.open(grid) as ds:
        w, s, e, n = transform_bounds(ds.crs, 'EPSG:4326', *ds.bounds)
    bounds = [w - 0.0002, s - 0.0002, e + 0.0002, n + 0.0002]
    config = tmp_path / 'region.json'
    write_json(config, {'id': region.id, 'bounds': bounds})
    w, s, e, n = transform_bounds('EPSG:4326', 'EPSG:3310', *bounds)
    coarse = tmp_path / 'coarse.tif'
    with rio.open(coarse, 'w', driver='GTiff', width=8, height=8, count=1, dtype='float32',
                  crs='EPSG:3310', transform=rio.transform.from_bounds(w, s, e, n, 8, 8)) as ds:
        ds.write(np.full((8, 8), -10, dtype='float32'), 1)
    water = tmp_path / 'water.geojson'
    write_json(water, {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': geom.mapping(geom.box(*bounds)), 'properties': {}}]})

    def select(revision):
        def build(out):
            row = {'id': 'tiny-grid', 'path': str(grid), 'sha256': receipts.sha256_file(grid),
                   'resolution_m': 1, 'vertical_datum': 'unstated', 'units': 'm', 'vertical_offset_m': 0,
                   'value_convention': 'elevation_positive_up', 'offset_note': 'Nominal datum.',
                   'citation': 'Tiny synthetic fixture', 'rights': 'synthetic', 'attribution': 'fixture',
                   'rights_class': 'public', 'label': 'estimated', 'max_zoom': 15}
            write_json(out / 'sources.json', {'schema_version': 1, 'scope': 'public', 'sources': [row]})
            write_json(out / 'native.json', [row])
            write_json(out / 'selection.json', {'region': region.id, 'scope': 'public', 'files': [
                {'id': row['id'], 'decision': 'included', 'rights_class': 'public', 'reason': revision}]})

        assert receipts.run_stage(receipts.StageRun(region, 'select', build, 'f' * 64,
                                                     plan=receipts.Plan(params={'revision': revision}))).state == 'ok'

    # Exercise the actual mosaic CLI and its production argv. Supply only the disk
    # measurement for this tiny synthetic run: a CI runner need not have 250 GiB free.
    tool = mosaic.run_tool

    def run_tool(script, *args, **kwargs):
        if script != mosaic.SCRIPT:
            return tool(script, *args, **kwargs)
        argv = [str(ROOT / script), *map(str, args)]
        assert argv[argv.index('--reserve-gib') + 1] == '250'
        with monkeypatch.context() as patch:
            patch.setattr(sys, 'argv', argv)
            patch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=2**40))
            runpy.run_path(argv[0], run_name='__main__')

    monkeypatch.setattr(mosaic, 'run_tool', run_tool)
    outputs = {'mosaic': {'elevation.tif', 'contributor.tif', 'support_count.tif', 'manifest.json'},
               'tiles': {'relief.pmtiles', 'coverage.json'}, 'zone': {'zone.geojson', 'detail.geojson'}}

    def run(stage, expected='OK', rc=0):
        command = [stage, '--region', region.id, '--out', str(region.out_root), '--scope', 'public',
                   '--region-config', str(config)]
        if stage == 'zone':
            command += ['--coarse', str(coarse), '--water', str(water), '--coarse-source', 'tiny-coarse']
        capsys.readouterr()
        actual = main(command)
        message = capsys.readouterr().out
        assert actual == rc, message
        assert f'[{stage}.public] {expected}' in message

    def stage_receipt(stage):
        doc = receipts.read_receipt(region.receipt_path(stage, 'public'))
        assert doc is not None
        return doc

    def recorded_outputs(stage):
        doc = stage_receipt(stage)
        assert doc['status'] == 'ok' and doc['attempt'] == 1
        recorded = {region.resolve(item['path']).name: region.resolve(item['path']) for item in doc['outputs']}
        assert set(recorded) - {'support_class.tif'} == outputs[stage]
        assert receipts.check(region, stage, 'public').done
        return recorded

    run('mosaic', 'BLOCKED', 3)
    select('initial')
    run('tiles', 'BLOCKED', 3)
    run('zone', 'BLOCKED', 3)
    for stage in outputs:
        run(stage)
        recorded = recorded_outputs(stage)
        for artifact in recorded.values():
            assert str(tmp_path).encode() not in artifact.read_bytes()

    tile_paths = recorded_outputs('tiles')
    metadata = pmtiles_metadata(tile_paths['relief.pmtiles'])
    assert metadata['ramp'] == 'deep-fixed-v1'
    assert metadata['maxzoom'] <= 15 and metadata['maxzoom'] >= 14
    clip = stage_receipt('tiles')['metrics']['clip_bounds']
    help_text = subprocess.check_output([sys.executable, str(ROOT / 'scripts/build_bathy_tiles.py'), '--help'],
                                        text=True)
    if '--clip-bounds' in help_text:
        assert clip == bounds
        assert metadata['bounds'] == pytest.approx(bounds, abs=1e-6)
    else:
        assert clip is None
        assert 'no --clip-bounds' in stage_receipt('tiles')['metrics']['clip_status']
    assert mosaic.read_json(tile_paths['coverage.json'])['native'][0]['id'] == 'tiny-grid'
    detail = mosaic.read_json(recorded_outputs('zone')['detail.geojson'])
    assert {f['properties']['tier'] for f in detail['features']} == {'estimated', 'none'}
    assert any(f['properties']['sources'] == ['tiny-grid'] for f in detail['features'])

    old = {stage: stage_receipt(stage) for stage in outputs}
    for stage in outputs:
        run(stage, 'DONE')
        assert stage_receipt(stage) == old[stage]

    # A zone-only input renews that stage, not either sibling/upstream stage.
    water.write_text(water.read_text() + '\n', encoding='utf-8')
    run('mosaic', 'DONE')
    run('tiles', 'DONE')
    run('zone')
    assert stage_receipt('zone')['generation'] != old['zone']['generation']
    old['zone'] = stage_receipt('zone')
    select('revised source decision')
    run('tiles', 'BLOCKED', 3)
    selector = region.receipt_path('select').read_bytes()
    for stage in outputs:
        run(stage)
        assert stage_receipt(stage)['generation'] != old[stage]['generation']
        recorded_outputs(stage)
    assert region.receipt_path('select').read_bytes() == selector

    # Release handoff (R6): the digest index, inventory and package read the producers' own
    # leaves through their receipts. A package fixture with a layout no producer writes, or an
    # inventory that drops a producer, breaks here.
    pytest.importorskip('jsonschema')
    repo = tmp_path / 'repo'
    write_json(_mkdir(repo / 'catalog') / 'sources.json', {'sources': [{
        'id': 'tiny-grid', 'review_status': 'approved', 'provider': 'Fixture survey',
        'rights': {'public_display': 'allowed', 'license': 'public-domain', 'attribution': 'Fixture survey'}}]})
    write_json(_mkdir(repo / 'regions/tiny') / 'region.json', {'id': region.id, 'bounds': bounds})
    shutil.copy(ROOT / 'catalog/relief/pointer.schema.json', _mkdir(repo / 'catalog/relief') / 'pointer.schema.json')
    for module in (package, envelope):
        monkeypatch.setattr(module, 'repo_root', lambda: repo)

    def step(name, *args, rc=0):
        capsys.readouterr()
        actual = main([name, '--region', region.id, '--out', str(region.out_root), *map(str, args)])
        message = capsys.readouterr().out
        assert actual == rc, message
        return message

    manifest = region.dir / 'inventory/manifest.json'
    producers = ['--upstream', 'tiles:public', '--upstream', 'digests', '--upstream', 'zone:public']
    step('inventory', rc=3)  # no digest index yet
    step('digests')
    step('inventory')
    doc = json.loads(manifest.read_bytes())
    assert package.ARCHIVE in doc['layer_paths'] and package.DIGEST_ROOT in doc['layer_paths']
    assert {'layers/public/zone/zone.geojson', 'layers/public/zone/detail.geojson'} <= set(doc['layer_paths'])
    assert [s['id'] for s in doc['sources']] == ['tiny-grid'] and doc['sources'][0]['estimated'] is True

    # A hand-edited copy of the manifest, or a missing producer, is refused.
    copy = tmp_path / 'edited.json'
    copy.write_bytes(receipts.canonical(dict(doc, layer_paths=[p for p in doc['layer_paths'] if '/zone/' not in p])))
    assert 'not the current inventory stage output' in step(
        'package', '--manifest', copy, *producers, '--upstream', 'inventory', rc=1)
    assert 'not in the current upstream outputs' in step(
        'package', '--manifest', manifest, '--upstream', 'tiles:public', '--upstream', 'digests', rc=1)
    step('package', '--manifest', manifest, *producers, '--upstream', 'inventory')
    gen = receipts.check(region, 'package').receipt['generation']
    release = region.dir / f'release/{gen}/release.json'
    report = {'status': 'PASS', 'release_sha256': receipts.sha256_file(release)}
    assert receipts.run_stage(receipts.StageRun(region, 'qa', lambda out: write_json(out / 'qa.json', report), 'b' * 64,
                                                upstream=[receipts.Ref('package')], target=f'qa/{gen}')).state == 'ok'
    step('envelope', '--generation', gen)
    assert json.loads((region.dir / f'review/{gen}/envelope.json').read_bytes())['layers'] == \
        json.loads(release.read_bytes())['layers']

    # A new archive makes every downstream receipt stale; nothing reuses the old inventory.
    select('second revision')
    for name in outputs:
        run(name)
    for name in ('inventory', 'package', 'envelope'):
        assert receipts.check(region, name).state == 'stale'
    step('inventory', rc=3)


def _mkdir(path):
    path.mkdir(parents=True, exist_ok=True)
    return path
