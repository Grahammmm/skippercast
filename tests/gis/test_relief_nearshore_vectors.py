"""Receipt-bound QA products, using fictional grids and an isolated style root."""
import hashlib
import json
import shutil

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform
from shapely.geometry import LineString, Point, Polygon, box, mapping, shape
from shapely.ops import transform as project_shape
from pyproj import Transformer

from scripts.relief import region as cli
from scripts.style.gen_style import group_digests
from skippercast.relief import inventory, receipts, render_config
from skippercast.seafloor import substrate
from tests._support import ROOT


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(receipts.canonical(data))


class Scene:
    def __init__(self, root, monkeypatch, cell, *, gap=False):
        self.region = receipts.Region(root / 'out', 'tiny')
        self.config = root / 'config'
        self.styles = self.config / 'style'
        self.index = json.loads((ROOT / 'style/index.json').read_bytes())
        self.version = self.index['default']
        self.tokens = json.loads((ROOT / 'style' / self.index['versions'][self.version]['file']).read_bytes())
        self.tokens['pier_view']['window_m'] = 380
        self.tokens['rock_piles']['label']['nms_m'] = 50
        self.styles.mkdir(parents=True)
        shutil.copy(ROOT / 'style/groups.json', self.styles)
        schema = self.config / 'schemas/sc-render-v1.schema.json'
        schema.parent.mkdir()
        shutil.copy(ROOT / 'schemas/sc-render-v1.schema.json', schema)
        self.set_style(self.version, self.tokens)
        monkeypatch.setattr(render_config, 'repo_root', lambda: self.config)
        self.region_config = self.config / 'regions/tiny/region.json'
        put(self.region_config, {'id': 'tiny', 'bounds': [-123, 34, -119, 38]})
        self.dataset_transform = from_origin(-200000, -50000, cell, cell)
        self.xy = [(-199750.5, -50240.5), (-199740.5, -50240.5), (-199765.5, -50240.5)]
        coords = list(zip(*transform('EPSG:3310', 'EPSG:4326', *zip(*self.xy))))
        put(self.region_config.with_name('render.json'), dict(schema='sc-render/1', region='tiny', previews=[], piers=[
            dict(id='test-pier', name='Fictional Pier', osm_way=124, coordinates=coords),
            dict(id='way-only', name='Held Way', osm_way=123),
        ]))
        size = 480 // cell
        y, x = np.mgrid[:size, :size] * cell
        dem = (-15 + sum(9 * np.exp(-((x - i)**2 + (y - 205)**2) / 34) for i in (215, 247, 320)))
        dem[:, x[0] < 130] = 1
        dem[240 // cell, 259 // cell] = -19
        self.write_grid(root / 'native.tif', dem, self.dataset_transform)
        support = root / 'support.tif'
        cert = np.full(dem.shape, 3, dtype='uint8')
        if gap:
            cert[80, 200] = 2  # well inside the wet window, away from the pier and its rings
        self.write_grid(support, cert, self.dataset_transform)

        def selected(out):
            put(out / 'native.json', [dict(id='fake-grid', path=str(root / 'native.tif'),
                sha256=receipts.sha256_file(root / 'native.tif'), support_path=str(support),
                support_sha256=receipts.sha256_file(support), rights_class='public', resolution_m=cell)])
            put(out / 'sources.json', dict(scope='public', sources=[
                dict(id='fake-grid', rights_class='public', resolution_m=cell)]))

        def mosaicked(out):
            # Flat lower-tier halo; no real-region data.
            self.write_grid(out / 'elevation.tif', np.full((48, 48), -20.), from_origin(-200000, -50000, 10, 10))

        for name, fn, scope, target in [('select', selected, None, 'select'),
                                        ('mosaic', mosaicked, 'public', 'mosaic/public')]:
            assert receipts.run_stage(receipts.StageRun(self.region, name, fn, 'a' * 64,
                                                       scope=scope, target=target)).state == 'ok'

    @staticmethod
    def write_grid(path, values, grid):
        dtype = 'uint8' if values.dtype == 'uint8' else 'float32'
        with rasterio.open(path, 'w', driver='GTiff', crs='EPSG:3310', transform=grid,
                           width=values.shape[1], height=values.shape[0], count=1, dtype=dtype) as ds:
            ds.write(values.astype(dtype), 1)

    def set_style(self, version, tokens):
        path = self.styles / f'{version}.json'
        put(path, tokens)
        rules = json.loads((self.styles / 'groups.json').read_bytes())
        self.index['versions'][version] = dict(self.index['versions'][self.version], file=path.name,
            sha256=receipts.sha256_file(path), digests=group_digests(tokens, rules))
        self.index['default'] = version
        put(self.styles / 'index.json', self.index)

    def invoke(self):
        return cli.main(['nearshore_vectors', '--region', self.region.id, '--out', str(self.region.out_root),
                         '--scope', 'public', '--region-config', str(self.region_config)])

    def run(self, capsys, state='OK'):
        rc = self.invoke()
        stdout = capsys.readouterr().out
        assert rc == 0, stdout
        assert state in stdout
        verdict = receipts.check(self.region, 'nearshore_vectors', 'public')
        assert verdict.done and verdict.receipt is not None
        return verdict.receipt

    def outputs(self):
        return {p.name: p.read_bytes() for p in (self.region.dir / 'layers/public/nearshore').glob('*')}


def _synthetic_package(scene, monkeypatch, capsys):
    """Seed tiny unrelated producer outputs; exercise real inventory and package readers."""
    from skippercast.relief import package
    from skippercast.relief.pmtiles_v3 import write_pmtiles

    monkeypatch.setattr(package, 'repo_root', lambda: scene.config)
    put(scene.config / 'catalog/sources.json', {'sources': [dict(id='fake-grid', review_status='approved', rights=dict(
        public_display='allowed', license='public-domain', attribution='Fictional survey'))]})
    put(scene.config / 'catalog/relief/pointer.schema.json',
        json.loads((ROOT / 'catalog/relief/pointer.schema.json').read_bytes()))

    def archive(out):
        bounds = (-121.3, 35.1, -121., 35.5)
        write_pmtiles(out / 'relief.pmtiles', [((8, 41, 101), b'fake tile')], bounds=bounds, minzoom=8, maxzoom=8,
                      center=(8, -121.1, 35.3), metadata=dict(bounds=list(bounds), minzoom=8, maxzoom=8,
                          native_support_by_zoom={'8': {'tiles': 1, 'limit_m': inventory.SHALLOW_M}}))

    producers = [('tiles:public', 'layers/public/tiles', archive),
                 ('digests', 'layers/public/relief.digests', lambda out: put(out / 'root.json', {})),
                 ('zone:public', 'layers/public/zone', lambda out: None)]
    for ref, target, build in producers:
        stage = receipts.Ref.parse(ref)
        result = receipts.run_stage(receipts.StageRun(scene.region, stage.stage, build, 'b' * 64,
                                                      scope=stage.scope, target=target))
        assert result.state == 'ok', result.line()

    def snapshot():
        # Force both builds. A cache hit could hide accidental admission of the QA files.
        common = ['--region', scene.region.id, '--out', str(scene.region.out_root)]
        manifest = scene.region.dir / 'inventory/manifest.json'
        for stage in ('inventory', 'package'):
            scene.region.receipt_path(stage).unlink(missing_ok=True)
        assert cli.main(['inventory', *common]) == 0, capsys.readouterr().out
        args = ['package', *common, '--manifest', str(manifest)]
        for ref in ('tiles:public', 'digests', 'zone:public', 'inventory'):
            args.extend(('--upstream', ref))
        assert cli.main(args) == 0, capsys.readouterr().out
        capsys.readouterr()
        verdict = receipts.check(scene.region, 'package')
        assert verdict.done and verdict.receipt is not None
        release = scene.region.dir / verdict.receipt['target'] / 'release.json'
        for paths in (json.loads(manifest.read_bytes())['layer_paths'],
                      [row['path'] for row in json.loads(release.read_bytes())['layers']]):
            assert paths == sorted([package.ARCHIVE, package.DIGEST_ROOT])
        return manifest.read_bytes(), release.read_bytes()

    return snapshot


@pytest.mark.parametrize('cell,gap', [(1, False), (1, True), (2, False), (4, False)])
def test_public_vectors_on_native_support(tmp_path, monkeypatch, capsys, cell, gap):
    # Catches sample-spacing-only certification, using a terminal vertex instead of the
    # deepest vertex, land-crossing arc segments, and habitat marks leaking to coarse grids.
    scene = Scene(tmp_path, monkeypatch, cell, gap=gap)

    def forbidden(*args, **kwargs):
        raise AssertionError('the public stage attempted to read substrate')

    monkeypatch.setattr(substrate, 'class_reader', forbidden)
    monkeypatch.setattr(substrate, 'read_classes', forbidden)
    receipt = scene.run(capsys)
    metrics = receipt['metrics']
    assert metrics['pier_view']['way-only'] == dict(status='skipped',
        reason='no pier geometry: osm_way only (held-extract reader not admitted)')
    layers = scene.outputs()
    assert set(layers) == {'piles.geojson', 'peaks.geojson', 'pier.geojson', 'arcs.geojson'}
    assert metrics['bytes'] == {name: len(blob) for name, blob in layers.items()}
    piles, peaks, piers, arcs = (json.loads(layers[f'{name}.geojson'])['features']
                                for name in ('piles', 'peaks', 'pier', 'arcs'))
    assert metrics['piles_total'] == metrics['piles_by_basis']['relief'] == len(piles)
    if cell == 4:
        assert not piles and not peaks
    if cell != 1 or gap:
        assert not piers and not arcs
        assert metrics['pier_view']['test-pier'] == dict(status='skipped', reason='no certified ≤1 m support (C7)')
        return
    assert 2 <= len(peaks) < len(piles)
    heights = [f['properties']['height_ft'] for f in peaks]
    assert heights == sorted(heights, reverse=True)
    assert all(f['properties']['basis'] == 'relief' for f in piles + peaks)
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    points = [project(*f['geometry']['coordinates']) for f in peaks]
    assert all(LineString([a, b]).length >= 50 for i, a in enumerate(points) for b in points[:i])
    assert metrics['pier_view']['test-pier']['status'] == 'produced'
    pier, = piers
    assert project(*pier['properties']['seaward_end']) == pytest.approx(scene.xy[1], abs=1e-5)
    assert pier['properties']['end_depth_ft'] == pytest.approx(19 / .3048, abs=.001)
    assert [f['properties'] for f in arcs] == [dict(radius_m=r, radius_index=i, pier_id='test-pier',
                                                    source_id='fake-grid') for i, r in enumerate((50, 100, 150))]
    outer = project_shape(project, shape(arcs[-1]['geometry']))
    assert not outer.is_empty and outer.distance(box(-200000, -50480, -199870.01, -50000)) > 0
    assert outer.length < 2 * np.pi * 150 - 50  # had to remove a real land-crossing span


def test_over_budget_vectors_shard_without_dropping(tmp_path, monkeypatch, capsys):
    # Catches the old refusal, local NMS/tie reorder, extra simplification, and envelope/cap drift.
    from skippercast.relief import nearshore_vectors as vectors

    scene = Scene(tmp_path, monkeypatch, 1)
    points = [Point(-200000 + x, -50205.5) for x in (150.5, 175.5, 235.5, 260.5, 320.5, 409.5)]
    records = []
    for i, (point, height) in enumerate(zip(points, (25., 30., 20., 20., 26., 27.))):
        # Sub-cell bump survives a quarter-cell tolerance, but not a half-cell tolerance.
        x, y = point.x, point.y
        geom = Polygon([(x-2, y-2), (x, y-2.4), (x+2, y-2), (x+2, y+2), (x-2, y+2)])
        records.append((geom, point, height, 47.25 + i))
    monkeypatch.setattr(vectors, 'pile_shapes', lambda *args: records)
    project = Transformer.from_crs(3310, 4326, always_xy=True).transform

    def feature(geometry, **props):
        return dict(type='Feature', geometry=mapping(project_shape(project, geometry)),
                    properties=dict(basis='relief', source_id='fake-grid', **props))

    def collection(features):
        return json.dumps(dict(type='FeatureCollection', features=features), sort_keys=True,
                          separators=(',', ':'), ensure_ascii=False).encode('utf-8')

    def expected_piles(tolerance):
        return [feature(geom.simplify(tolerance, preserve_topology=True), id=i, area_m2=round(geom.area, 3),
                        height_ft=height, depth_ft=depth)
                for i, (geom, _, height, depth) in enumerate(records, 1)]

    # Across the prospective one-pile shard boundaries: 2 beats 1 on height, 3 beats 4 on a tie.
    retained = [records[i] for i in (1, 5, 4, 2)]
    peak_features = [feature(point, height_ft=height, label=f'+{height:.0f} ft')
                     for _, point, height, _ in retained]
    expected_peaks = collection(peak_features)
    quarter, half = [collection(expected_piles(tol)) for tol in (.25, .5)]
    half_cap = len(half) + len(expected_peaks)
    quarter_cap = len(quarter) + len(expected_peaks)
    shard_cap = max(len(collection([f])) for f in expected_piles(.5)) + len(collection([]))
    assert shard_cap < half_cap < quarter_cap

    release_snapshot = _synthetic_package(scene, monkeypatch, capsys)
    before_release = release_snapshot()
    receipt_path = scene.region.receipt_path('nearshore_vectors', 'public')

    def rebuild(cap):
        monkeypatch.setattr(vectors, 'MAX_PILE_BYTES', cap)
        receipt_path.unlink(missing_ok=True)
        receipt = scene.run(capsys)
        return receipt, scene.outputs()

    for cap, piles in ((quarter_cap, quarter), (half_cap, half)):
        reference, unsharded = rebuild(cap)
        assert set(unsharded) == {'piles.geojson', 'peaks.geojson', 'pier.geojson', 'arcs.geojson'}
        assert unsharded['piles.geojson'] == piles and unsharded['peaks.geojson'] == expected_peaks
        assert set(reference['metrics']) == {'style', 'pier_view', 'piles_total', 'piles_by_basis', 'bytes'}

    sharded, blobs = rebuild(shard_cap)
    assert release_snapshot() == before_release
    index = json.loads(blobs['pile-shards.json'])
    assert index['schema'] == 'sc-nearshore-pile-shards/1'
    assert index['pair_cap_bytes'] == shard_cap
    ordered = {'piles': [], 'peaks': []}
    payload_bytes, filenames = 0, set()
    pair_sizes = []
    for i, pair in enumerate(index['pairs'], 1):
        pair_size = 0
        for stream in ordered:
            name = f'{stream}-{i:06d}.geojson'
            data = blobs[name]
            decoded = json.loads(data)
            assert decoded['type'] == 'FeatureCollection'
            features = decoded['features']
            assert pair[stream] == dict(name=name, bytes=len(data),
                                        sha256=hashlib.sha256(data).hexdigest(), count=len(features))
            assert data == collection(features)
            if stream == 'piles' and i <= len(records):
                assert [f['properties']['id'] for f in features] == [i]
            ordered[stream].extend(features)
            pair_size += len(data)
            filenames.add(name)
        assert pair_size == pair['bytes'] <= shard_cap
        pair_sizes.append(pair_size)
        payload_bytes += pair_size
    assert len(pair_sizes) > len(records) and max(pair_sizes) == shard_cap
    assert payload_bytes == index['total_pair_bytes'] > shard_cap
    for stream, features in ordered.items():
        assert index['counts'][stream] == len(features)
        assert collection(features) == unsharded[f'{stream}.geojson']
    assert all((geom := shape(f['geometry'])).geom_type == 'Polygon' and geom.is_valid and not geom.is_empty
               for f in ordered['piles'])
    assert set(blobs) == filenames | {'pile-shards.json', 'pier.geojson', 'arcs.geojson'}
    assert len(blobs['pile-shards.json']) <= vectors.MAX_PILE_INDEX_BYTES
    for name in ('pier.geojson', 'arcs.geojson'):
        assert blobs[name] == unsharded[name] and json.loads(blobs[name])['features']
    assert {row['path']: (row['bytes'], row['sha256']) for row in sharded['outputs']} == {
        f'layers/public/nearshore/{name}': (len(blob), hashlib.sha256(blob).hexdigest())
        for name, blob in blobs.items()}
    assert sharded['metrics'] == reference['metrics'] | {
        'bytes': {name: len(blob) for name, blob in blobs.items()},
        'pile_layout': index['schema'], 'pile_pair_bytes_total': payload_bytes,
        'pile_half_cell_unsharded_bytes': half_cap,
    }
    for key in ('params', 'inputs', 'upstream', 'code'):
        assert sharded[key] == reference[key]

    # The comma between two peaks is a real byte: it fits at equality, not one byte below.
    two_peaks_cap = len(collection(peak_features[:2])) + len(collection([]))
    assert two_peaks_cap > shard_cap
    for cap, count in ((two_peaks_cap, 2), (two_peaks_cap - 1, 1)):
        _, other = rebuild(cap)
        first_peak_pair = json.loads(other['pile-shards.json'])['pairs'][len(records)]
        assert first_peak_pair['peaks']['count'] == count
        assert first_peak_pair['piles']['count'] == 0
    # Do not close the final pile pair until the next peak would actually breach the cap.
    mixed_cap = len(collection(expected_piles(.5)[-1:])) + len(collection(peak_features[:1]))
    _, mixed = rebuild(mixed_cap)
    mixed_pair = json.loads(mixed['pile-shards.json'])['pairs'][len(records) - 1]
    assert mixed_pair['piles']['count'] == mixed_pair['peaks']['count'] == 1
    assert mixed_pair['bytes'] == mixed_cap
    assert rebuild(shard_cap)[1] == blobs

    # An index one byte over its own cap must fail even though all pairs fit.
    monkeypatch.setattr(vectors, 'MAX_PILE_INDEX_BYTES', len(blobs['pile-shards.json']) - 1)
    receipt_path.unlink()
    _assert_vector_refusal(scene, capsys, 'index budget')
    assert scene.outputs() == blobs  # preserve the last complete generation's bytes


def _assert_vector_refusal(scene, capsys, reason):
    assert scene.invoke() == 1
    assert reason in capsys.readouterr().out
    verdict = receipts.check(scene.region, 'nearshore_vectors', 'public')
    assert not verdict.done and verdict.receipt is not None
    failure = verdict.receipt
    assert failure['status'] == 'failed' and failure['outputs'] == [] and 'metrics' not in failure
    assert reason in failure['error']
    assert not list((scene.region.dir / failure['failed_dir']).iterdir())


def test_over_budget_vectors_refuse_indivisible_feature(tmp_path, monkeypatch, capsys):
    # An indivisible feature cannot be omitted, clipped, or published in an over-cap pair.
    from skippercast.relief import nearshore_vectors as vectors

    scene = Scene(tmp_path, monkeypatch, 1)
    point = Point(-199799.5, -50205.5)
    geom = box(point.x - 2, point.y - 2, point.x + 2, point.y + 2)
    monkeypatch.setattr(vectors, 'pile_shapes', lambda *args: [(geom, point, 25., 47.25)])
    scene.run(capsys)
    single_bytes = len(scene.outputs()['piles.geojson']) + len(receipts.canonical(
        dict(type='FeatureCollection', features=[])))

    # Use a fresh target to prove a failed attempt cannot expose any product.
    fresh = Scene(tmp_path / 'refusal', monkeypatch, 1)
    monkeypatch.setattr(vectors, 'MAX_PILE_BYTES', single_bytes - 1)
    _assert_vector_refusal(fresh, capsys, f'piles feature 1 requires {single_bytes} bytes with both envelopes; '
                                       f'shard budget {single_bytes - 1} exceeded')
    assert not (fresh.region.dir / vectors.TARGET).exists()


def test_only_output_groups_invalidate_production_receipt(tmp_path, monkeypatch, capsys):
    # A paint key leaking into params or output would invalidate the cached arcs or
    # change their bytes on rebuild; omitting either true dependency would reuse stale products.
    scene = Scene(tmp_path, monkeypatch, 1)
    base = scene.run(capsys)
    before = scene.outputs()
    assert set(base['params']) == {'baked', 'habitat', 'piers'}
    assert {x['role'] for x in base['inputs']} == {'region', 'elevation', 'native', 'grid:fake-grid', 'support:fake-grid'}
    assert json.loads(before['arcs.geojson'])['features']
    paint = scene.tokens['pier_view']['cast_arcs']
    paint.update(dash=['dotted'] * 3)
    paint['label']['angles_deg'] = [10, 20, 30]
    scene.set_style('nearshore-v1.0.1', scene.tokens)
    assert scene.run(capsys, 'DONE')['generation'] == base['generation']
    assert scene.outputs() == before
    # Force an actual rebuild as well; a cache hit alone wouldn't detect paint read during build.
    scene.region.receipt_path('nearshore_vectors', 'public').unlink()
    assert scene.run(capsys)['generation'] == base['generation']
    assert scene.outputs() == before
    paint['radii_m'] = [45, 100, 150]
    scene.set_style('nearshore-v1.1.0', scene.tokens)
    habitat = scene.run(capsys)
    assert habitat['generation'] != base['generation'] and habitat['params']['baked'] == base['params']['baked']
    assert habitat['params']['habitat'] != base['params']['habitat']
    assert json.loads(scene.outputs()['arcs.geojson'])['features'][0]['properties']['radius_m'] == 45
    scene.tokens['derived']['rock_piles']['min_peak_m'] = 100
    scene.set_style('nearshore-v1.2.0', scene.tokens)
    baked = scene.run(capsys)
    assert baked['generation'] != habitat['generation'] and baked['params']['habitat'] == habitat['params']['habitat']
    assert baked['params']['baked'] != habitat['params']['baked']
    assert baked['metrics']['piles_total'] == 0 < habitat['metrics']['piles_total']


@pytest.mark.parametrize('support_value', [0, 2])
def test_pier_rejects_uncertified_dry_boundary(tmp_path, support_value):
    from skippercast.relief import nearshore_vectors, tiles

    grid = from_origin(-200000, -50000, 1, 1)
    elevation = np.full((480, 480), -10, dtype='float32')
    elevation[200, 100] = 1  # dry, but still part of the clipping window
    support = np.full(elevation.shape, 3, dtype='uint8')
    support[200, 100] = support_value
    Scene.write_grid(tmp_path / 'elevation.tif', elevation, grid)
    Scene.write_grid(tmp_path / 'support.tif', support, grid)
    xy = [(-199780.5, -50240.5), (-199760.5, -50240.5)]
    coords = list(zip(*transform('EPSG:3310', 'EPSG:4326', *zip(*xy))))
    row = dict(id='pier', name='Pier', coordinates=coords)
    habitat = {'pier_view': {'window_m': 380, 'max_cell_m': 1,
               'cast_arcs': {'clip': 'water cells only', 'radii_m': [150]}}}
    baked = type('Baked', (), {'native_max_zoom': lambda self, res: 20})()
    source = dict(id='grid', support_path=tmp_path / 'support.tif', resolution_m=1)
    with rasterio.open(tmp_path / 'elevation.tif') as ds:
        assert nearshore_vectors._certified_pier(ds, source, row, baked, habitat, tiles._builder()) is None


def test_pier_certifies_complete_outer_ring(tmp_path):
    from skippercast.relief import nearshore_vectors, tiles

    grid = from_origin(-200000, -50000, 1, 1)
    elevation = np.full((1600, 1600), -10, dtype='float32')
    elevation[800, 1250] = -20
    support = np.full(elevation.shape, 3, dtype='uint8')
    Scene.write_grid(tmp_path / 'elevation.tif', elevation, grid)
    Scene.write_grid(tmp_path / 'support.tif', support, grid)
    xy = [(-199800.5, -50800.5), (-198749.5, -50800.5)]
    coords = list(zip(*transform('EPSG:3310', 'EPSG:4326', *zip(*xy))))
    row = dict(id='pier', name='Pier', coordinates=coords)
    habitat = {'pier_view': {'window_m': 1200, 'max_cell_m': 1,
               'cast_arcs': {'clip': 'water cells only', 'radii_m': [150]}}}
    baked = type('Baked', (), {'native_max_zoom': lambda self, res: 20})()
    source = dict(id='grid', support_path=tmp_path / 'support.tif', resolution_m=1)
    with rasterio.open(tmp_path / 'elevation.tif') as ds:
        result = nearshore_vectors._certified_pier(ds, source, row, baked, habitat, tiles._builder())
    assert result is not None
    project = Transformer.from_crs(4326, 3310, always_xy=True).transform
    ring = project_shape(project, shape(result[1][0]['geometry']))
    assert ring.length == pytest.approx(2 * np.pi * 150, rel=1e-4)
    # A support gap beyond the old midpoint square must not be silently clipped.
    support[800, 1380] = 2
    Scene.write_grid(tmp_path / 'support.tif', support, grid)
    with rasterio.open(tmp_path / 'elevation.tif') as ds:
        assert nearshore_vectors._certified_pier(ds, source, row, baked, habitat, tiles._builder()) is None
