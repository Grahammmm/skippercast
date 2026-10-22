"""Offline C2 acceptance using only analytical fixtures, never real caches.

GIS imports are lazy and the module is marked gis: ordinary CI excludes it;
survey-science executes it with the pinned survey interpreter.
"""
import json
from pathlib import Path

import pytest
from tests._support import ROOT

pytestmark = pytest.mark.gis
FIXTURES = ROOT / 'research/tests/fixtures/coast_mvp/contours'


@pytest.fixture
def stack():
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import shape, Point
    from shapely.ops import transform
    from pyproj import Transformer
    from research.scripts.coast_mvp import coast_contours as c2
    return np, rasterio, from_origin, shape, Point, transform, Transformer, c2


@pytest.fixture
def make_rasters(tmp_path, stack):
    np, rio, from_origin, *_ = stack
    config = json.loads((FIXTURES / 'synthetic.json').read_text())

    def make(kind='gradient', hole=True, boundary=True):
        directory = tmp_path / f'{kind}-{hole}-{boundary}'
        directory.mkdir()
        height, width = config['shape']
        yy, xx = np.indices((height, width))
        depth = xx * 1000 / (width - 1) if kind == 'gradient' else ((xx - 31.5)**2 + (yy - 31.5)**2) / 2
        elevation = (-depth * 0.3048).astype('float32')
        codes = np.where(xx < config['source_boundary_column'], 1, 2).astype('uint16') if boundary else np.ones((height, width), dtype='uint16')
        if hole:
            r0, r1, c0, c1 = config['hole_rows_cols']
            codes[r0:r1, c0:c1] = 0
        elevation[codes == 0] = -999999
        profile = dict(driver='GTiff', width=width, height=height, count=1,
                       crs=config['crs'], transform=from_origin(*config['origin'], config['cell_m'], config['cell_m']))
        for name, data, nodata in [('elevation', elevation, -999999), ('contributor', codes, 0)]:
            with rio.open(directory / f'{name}.tif', 'w', dtype=data.dtype, nodata=nodata, **profile) as target:
                target.write(data, 1)
        (directory / 'sources.json').write_text(json.dumps(config))
        return directory
    return make


def run(c2, directory, **kwargs):
    return c2.build(directory / 'elevation.tif', directory / 'contributor.tif',
                    directory / 'sources.json', directory / 'output', zoom=14, **kwargs)


def test_depth_levels_and_invalid_limits(stack):
    c2 = stack[-1]
    assert c2.levels(1000) == list(range(10, 601, 10)) + [700, 800, 900, 1000]
    assert c2.levels(609) == list(range(10, 601, 10))
    assert c2.levels(9) == []
    for value in [-1, float('nan'), float('inf')]:
        with pytest.raises(ValueError):
            c2.levels(value)


def test_gradient_mask_boundary_and_monotonicity(stack, make_rasters):
    np, rio, _, shape, Point, transform, Transformer, c2 = stack
    directory = make_rasters()
    result = run(c2, directory)
    features = json.loads((directory / 'output/contours.geojson').read_text())['features']
    project = Transformer.from_crs('EPSG:4326', 'EPSG:3310', always_xy=True).transform
    with rio.open(directory / 'elevation.tif') as grid:
        affine = grid.transform
        west, south, east, north = grid.bounds
    boundary_x = west + 32 * 40
    hole_bounds = (west + 24 * 40, north - 40 * 40, west + 40 * 40, north - 24 * 40)
    from shapely.geometry import box
    hole = box(*hole_bounds)
    means = {}
    for feature in features:
        properties = feature['properties']
        line = transform(project, shape(feature['geometry']))
        assert line.is_simple and line.is_valid
        assert line.intersection(hole.buffer(-0.001)).is_empty
        depth = properties['depth_ft']
        assert depth in result['levels_ft']
        assert properties['interval_ft'] == (10 if depth <= 600 else 100)
        assert properties['depth_band'] == ('0-600ft' if depth <= 600 else '600ft+')
        assert properties['source_resolution_m'] == (2 if properties['source_code'] == 1 else 10)
        coords = np.array(line.coords)
        # GDAL interpolates adjacent to nodata edges; both that displacement
        # and Douglas-Peucker must stay within the stated half-cell tolerance.
        assert np.ptp(coords[:, 0]) <= result['simplify_m'] + 0.01
        expected = west + 20 + depth / 1000 * 63 * 40
        assert abs(coords[:, 0].mean() - expected) <= result['simplify_m'] + 0.01
        means[depth] = coords[:, 0].mean()
        if properties['source_code'] == 1:
            assert coords[:, 0].max() <= boundary_x + 0.01
        else:
            assert coords[:, 0].min() >= boundary_x - 0.01
        for coord in (coords[0], coords[-1]):
            x, y = coord
            distances = [abs(x - west), abs(x - east), abs(y - south), abs(y - north),
                         abs(x - boundary_x), Point(x, y).distance(hole.boundary)]
            assert min(distances) < 0.05
    ordered = [means[d] for d in sorted(means)]
    assert all(a < b for a, b in zip(ordered, ordered[1:]))
    assert 600 in means and 700 in means and 900 in means
    assert result['status'] == 'review_required'
    assert result['simplify_m'] == 20


def test_closed_bowl_contours(stack, make_rasters):
    *_, c2 = stack
    directory = make_rasters('bowl', hole=False, boundary=False)
    run(c2, directory)
    from shapely.geometry import shape
    lines = [shape(f['geometry']) for f in json.loads((directory / 'output/contours.geojson').read_text())['features']]
    assert any(line.is_closed for line in lines)
    assert all(line.is_simple and line.is_valid for line in lines)


def test_terrain_rgb_and_mvt_open(stack, make_rasters):
    np, rio, *_, c2 = stack
    directory = make_rasters()
    result = run(c2, directory)
    pngs = list((directory / 'output/terrain').rglob('*.png'))
    assert len(pngs) == result['terrain_tiles']
    opaque = transparent = 0
    for tile in pngs:
        with rio.open(tile) as grid:
            assert grid.count == 4 and grid.shape == (256, 256)
            rgba = grid.read().astype('int64')
        valid = rgba[3] == 255
        opaque += int(valid.sum())
        transparent += int((~valid).sum())
        decoded = -10000 + (rgba[0] * 65536 + rgba[1] * 256 + rgba[2]) * 0.1
        assert np.all(decoded[valid] <= 0.05)
        # Nearest sampling must retain analytical column depths to RGB precision.
        if valid.any():
            expected = -np.arange(64) * 1000 / 63 * 0.3048
            errors = abs(decoded[valid, None] - expected[None, :]).min(axis=1)
            assert errors.max() <= 0.051
    assert opaque and transparent
    pbfs = list((directory / 'output/vector').rglob('*.pbf'))
    assert pbfs
    engine = c2.GDAL()
    for tile in pbfs:
        handle = engine.lib.GDALOpenEx(str(tile).encode(), 4, None, None, None)
        assert handle, str(tile)
        engine.lib.GDALClose(handle)
    assert json.loads((directory / 'output/vector/metadata.json').read_text())


@pytest.mark.parametrize('case', ['cells', 'tiles', 'unknown-code', 'alignment', 'empty', 'existing'])
def test_fail_closed_inputs(stack, make_rasters, case):
    _, rio, *_, c2 = stack
    directory = make_rasters()
    kwargs = {}
    if case == 'cells':
        kwargs['max_cells'] = 1
    elif case == 'tiles':
        kwargs['max_tiles'] = 0
    elif case in {'unknown-code', 'empty'}:
        with rio.open(directory / 'contributor.tif', 'r+') as grid:
            data = grid.read(1)
            data[:] = 0 if case == 'empty' else 99
            grid.write(data, 1)
    elif case == 'alignment':
        with rio.open(directory / 'contributor.tif', 'r+') as grid:
            grid.crs = 'EPSG:3857'
    else:
        (directory / 'output').mkdir()
    with pytest.raises((ValueError, FileExistsError)):
        run(c2, directory, **kwargs)
