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


@pytest.mark.parametrize('hole', [False, True])
def test_closed_bowl_crossing_contributor_boundary(stack, make_rasters, hole):
    _, rio, _, shape, Point, transform, Transformer, c2 = stack
    from shapely.geometry import box
    from shapely.ops import linemerge, snap, unary_union

    directory = make_rasters('bowl', hole=hole, boundary=True)
    run(c2, directory)
    features = json.loads((directory / 'output/contours.geojson').read_text())['features']
    project = Transformer.from_crs('EPSG:4326', 'EPSG:3310', always_xy=True).transform
    with rio.open(directory / 'elevation.tif') as grid:
        west, south, east, north = grid.bounds
    boundary_x = west + 32 * 40
    hole_mask = box(west + 24 * 40, north - 40 * 40,
                    west + 40 * 40, north - 24 * 40)
    masks = {1: box(west, south, boundary_x, north),
             2: box(boundary_x, south, east, north)}
    if hole:
        masks = {code: mask.difference(hole_mask) for code, mask in masks.items()}
    crossing = []
    for feature in features:
        line = transform(project, shape(feature['geometry']))
        code = feature['properties']['source_code']
        assert line.is_simple and line.is_valid
        assert masks[code].buffer(0.001).covers(line)
        if not line.is_closed:
            for endpoint in (line.coords[0], line.coords[-1]):
                assert Point(endpoint).distance(masks[code].boundary) < 0.001
        # This level is a complete interior ring, outside the masked hole.
        if feature['properties']['depth_ft'] == 300:
            crossing.append((code, line))
    assert sorted(code for code, _ in crossing) == [1, 2]
    assert all(not line.is_closed for _, line in crossing)
    assert all(abs(endpoint[0] - boundary_x) < 0.001
               for _, line in crossing
               for endpoint in (line.coords[0], line.coords[-1]))
    # Inverse projection can introduce sub-mm endpoint drift; snap only that
    # drift, not the half-cell simplification tolerance, before rejoining.
    first, second = [line for _, line in crossing]
    joined = linemerge(unary_union([first, snap(second, first, 0.001)]))
    assert joined.geom_type == 'LineString'
    assert joined.is_closed and joined.is_simple and joined.is_valid


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


def test_nearby_depths_do_not_cross_after_simplification(stack, make_rasters, monkeypatch):
    """Individually simple lines can still cross a different depth band."""
    _, rio, _, shape, _, transform, Transformer, c2 = stack
    from shapely.geometry import LineString, mapping

    directory = make_rasters(hole=False, boundary=False)
    with rio.open(directory / 'elevation.tif') as grid:
        west, south, east, north = grid.bounds
    mid_x, mid_y = (west + east) / 2, (south + north) / 2
    raw = [LineString([(west, mid_y), (mid_x, mid_y + 20.5), (east, mid_y)]),
           LineString([(west, mid_y + 1), (mid_x, mid_y + 21), (east, mid_y + 1)])]
    assert not raw[0].intersects(raw[1])
    # Negative control: the previous per-line algorithm creates intersections.
    old = [line.simplify(20) for line in raw]
    assert old[0].crosses(old[1])

    def contours(self, raster, destination, depth_levels, nodata):
        features = [dict(type='Feature', properties={'elevation_m': -depth * c2.FOOT},
                         geometry=mapping(line)) for depth, line in zip([10, 20], raw)]
        destination.write_text(json.dumps(dict(type='FeatureCollection', features=features)))
    monkeypatch.setattr(c2.GDAL, 'contours', contours)
    run(c2, directory)
    features = json.loads((directory / 'output/contours.geojson').read_text())['features']
    assert [f['properties']['depth_ft'] for f in features] == [10, 20]
    project = Transformer.from_crs('EPSG:4326', 'EPSG:3310', always_xy=True).transform
    lines = [transform(project, shape(f['geometry'])) for f in features]
    assert all(line.is_simple for line in lines)
    assert not lines[0].intersects(lines[1])
    assert all(line.hausdorff_distance(original) <= 20.001 for line, original in zip(lines, raw))


def test_regional_terrain_exact_nearest_and_mask(stack, tmp_path):
    """Small invented regional grid exposes approximate-warp cell errors."""
    np, rio, from_origin, _, _, _, Transformer, c2 = stack
    from rasterio.transform import from_bounds, rowcol, xy
    from rasterio.warp import reproject, Resampling
    directory = tmp_path / 'regional-synthetic'
    directory.mkdir()
    rows, cols = np.indices((512, 512))
    values = (-rows * 5 - cols - 1).astype('float32')
    valid = np.ones(values.shape, dtype=bool)
    valid[100:160, 180:210] = False
    values[~valid] = -999999
    affine = from_origin(100000, 200000, 250, 250)
    for name, data, nodata in [('elevation', values, -999999),
                             ('contributor', valid.astype('uint16'), 0)]:
        with rio.open(directory / f'{name}.tif', 'w', driver='GTiff', width=512, height=512,
                      count=1, dtype=data.dtype, nodata=nodata, crs='EPSG:3310', transform=affine) as grid:
            grid.write(data, 1)
    (directory / 'sources.json').write_text(json.dumps({'sources': [{'code': 1, 'id': 'invented', 'resolution_m': 250}]}))
    c2.build(directory / 'elevation.tif', directory / 'contributor.tif', directory / 'sources.json',
             directory / 'output', zoom=10)
    project = Transformer.from_crs('EPSG:3857', 'EPSG:3310', always_xy=True)
    old_mismatches = 0
    supported = unsupported = 0
    for tile in (directory / 'output/terrain').rglob('*.png'):
        z, x, y = int(tile.parts[-3]), int(tile.parts[-2]), int(tile.stem)
        span = 2 * c2.WORLD / 2**z
        west, north = -c2.WORLD + x * span, c2.WORLD - y * span
        tile_affine = from_bounds(west, north - span, west + span, north, 256, 256)
        rr, cc = np.indices((256, 256))
        tx, ty = xy(tile_affine, rr.ravel(), cc.ravel(), offset='center')
        sx, sy = project.transform(tx, ty)
        r, c = [np.asarray(v).reshape(256, 256) for v in rowcol(affine, sx, sy)]
        inside = (r >= 0) & (r < 512) & (c >= 0) & (c < 512)
        expected = np.full((256, 256), -999999, dtype='float32')
        expected[inside] = values[r[inside], c[inside]]
        mask = expected != -999999
        with rio.open(tile) as png:
            rgba = png.read().astype('int64')
        assert np.array_equal(rgba[3] == 255, mask)
        decoded = -10000 + (rgba[0] * 65536 + rgba[1] * 256 + rgba[2]) * 0.1
        assert np.allclose(decoded[mask], expected[mask], rtol=0, atol=0.051)
        supported += int(mask.sum())
        unsupported += int((~mask).sum())
        # Actual old reproject call, not a fabricated failure oracle.
        old = np.full((256, 256), -999999, dtype='float32')
        reproject(values, old, src_transform=affine, src_crs='EPSG:3310', src_nodata=-999999,
                  dst_transform=tile_affine, dst_crs='EPSG:3857', dst_nodata=-999999,
                  resampling=Resampling.nearest)
        old_mismatches += int((old != expected).sum())
    assert supported and unsupported
    assert old_mismatches > 0, 'Fixture must expose the old approximate-warp regression'


def test_simplify_contours_reverts_conflicts_to_a_crossing_free_fixpoint(stack):
    """Many tightly spaced noisy bands: per-line simplification crosses, the fix does not."""
    np, *_, c2 = stack
    from shapely.geometry import LineString
    rng = np.random.default_rng(844)
    x = np.linspace(0, 2000, 400)
    base = 30 * np.sin(x / 150)
    # Twenty bands 1 m apart (conflicts) and ten bands 20 m apart (none).
    offsets = list(range(20)) + [40 + 20 * j for j in range(10)]
    raw = [LineString(np.column_stack([x, k + base + rng.uniform(-0.45, 0.45, x.size)]))
           for k in offsets]
    assert not any(a.intersects(b) for i, a in enumerate(raw) for b in raw[i + 1:])
    # Negative control: independent topology-preserving calls cross other bands.
    old = [line.simplify(5, preserve_topology=True) for line in raw]
    assert any(a.intersects(b) for i, a in enumerate(old) for b in old[i + 1:])
    result = c2.simplify_contours(raw, 5)
    assert len(result) == len(raw)
    assert not any(a.intersects(b) for i, a in enumerate(result) for b in result[i + 1:])
    assert all(line.is_simple and line.is_valid for line in result)
    assert all(r.coords[0] == o.coords[0] and r.coords[-1] == o.coords[-1] for r, o in zip(result, raw))
    assert all(r.hausdorff_distance(o) <= 5 + 1e-9 for r, o in zip(result, raw))
    # Not a no-op: lines without conflicts keep their simplification.
    assert all(len(r.coords) < len(o.coords) for r, o in zip(result[20:], raw[20:]))
    assert c2.simplify_contours([], 5) == []
