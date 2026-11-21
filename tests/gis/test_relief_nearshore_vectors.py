"""Receipt-bound QA products, using fictional grids and an isolated style root."""
import json
import shutil

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform
from shapely.geometry import LineString, box, shape
from shapely.ops import transform as project_shape
from pyproj import Transformer

from scripts.relief import region as cli
from scripts.style.gen_style import group_digests
from skippercast.relief import receipts, render_config
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

    def run(self, capsys, state='OK'):
        assert cli.main(['nearshore_vectors', '--region', self.region.id, '--out', str(self.region.out_root),
                         '--scope', 'public', '--region-config', str(self.region_config)]) == 0
        assert state in capsys.readouterr().out
        return receipts.check(self.region, 'nearshore_vectors', 'public').receipt

    def outputs(self):
        return {p.name: p.read_bytes() for p in (self.region.dir / 'layers/public/nearshore').glob('*')}


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
