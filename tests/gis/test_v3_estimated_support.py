"""Estimated ft-v3 support and shoal-side contracts on native GeoTIFFs."""
from contextlib import ExitStack

import pytest

CRS = 'EPSG:32610'
COMMON = {'source_id': 'fixture', 'survey_date': '2024-01-01', 'vertical_datum': 'MLLW'}


@pytest.fixture
def tracer():
    from skippercast import style
    from skippercast.relief import contours

    return contours.producer(), style.load().view('contours')


def _trace(path, tracer, depths_ft, classes, *, cell=1, east_at=None, **kwargs):
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import array_bounds, from_origin
    from rasterio.warp import transform_bounds

    tool, view = tracer
    to_ll = Transformer.from_crs(CRS, 'EPSG:4326', always_xy=True)
    height, width = depths_ft.shape
    affine = from_origin(850000, 3920000 + height * cell, cell, cell)
    w, s, e, n = transform_bounds(CRS, 'EPSG:4326', *array_bounds(height, width, affine))
    east = e + 0.01 if east_at is None else to_ll.transform(*(affine @ east_at))[0]
    region = {'bounds': (w - 0.01, s - 0.01, east, n + 0.01)}
    path.mkdir(exist_ok=True)
    with ExitStack() as stack:
        def raster(name, values, nodata):
            target = path / (name + '.tif')
            with rasterio.open(target, 'w', driver='GTiff', crs=CRS, transform=affine,
                               count=1, width=width, height=height, dtype=values.dtype, nodata=nodata) as ds:
                ds.write(values, 1)
            return stack.enter_context(rasterio.open(target))

        grid = raster('depth', -depths_ft / tool.dc.FEET_PER_M, -9999)
        support = None if classes is None else raster('support', np.broadcast_to(
            np.asarray(classes, dtype='uint8'), depths_ft.shape), 0)
        features = list(tool.v3_grid(grid, region, view, COMMON, cell, support=support,
                                     certified=True, **kwargs))
    return features, affine, to_ll


def _slope():
    import numpy as np

    return np.broadcast_to(np.linspace(0.01, 100.25, 101)[:, None], (101, 101))


def _projected(feature):
    from pyproj import Transformer
    from shapely import transform
    from shapely.geometry import shape

    to_xy = Transformer.from_crs('EPSG:4326', CRS, always_xy=True)
    return transform(shape(feature['geometry']), to_xy.transform, interleaved=False)


@pytest.mark.parametrize('cell', [1, 4])
def test_v3_unknown_support_traces_estimated_tiers(tmp_path, tracer, cell):
    # The old measured-only mask silently emits nothing for an official class-2 grid.
    features, _, _ = _trace(tmp_path, tracer, _slope(), 2, cell=cell)
    observed = {}
    for f in features:
        props = f['properties']
        assert props['estimated'] is True
        observed.setdefault(props['tier'], {})[props['depth_ft']] = props['index']
    expected = {
        'z8': {60: True},
        'z11': {30: False, 60: True, 90: False},
        'z13': {d: d % 50 == 0 for d in range(10, 101, 10)},
    }
    if cell == 1:
        expected['z15'] = {d: d % 10 == 0 for d in range(5, 101, 5)}
    assert observed == expected


def test_v3_pier_needs_measured_cells(tmp_path, tracer):
    import numpy as np

    # Reusing either tier's mask for the other loses broad coverage or leaks pier detail.
    slope = _slope()
    classes = np.where(np.arange(slope.shape[1]) < 50, 3, 2)
    mixed, affine, _ = _trace(tmp_path / 'mixed', tracer, slope, classes)
    unknown, _, _ = _trace(tmp_path / 'unknown', tracer, slope, 2)
    measured, _, _ = _trace(tmp_path / 'measured', tracer, slope, 3)
    boundary, _ = affine @ (50, 0)
    piers = [_projected(f) for f in mixed if f['properties']['tier'] == 'pier']
    assert piers and all(g.bounds[2] <= boundary + affine.a for g in piers)
    assert not any(f['properties']['tier'] == 'pier' for f in unknown)
    assert any(f['properties']['tier'] == 'pier' for f in measured)
    broad = [f for f in mixed if f['properties']['tier'] != 'pier']
    assert {f['properties']['tier'] for f in broad} == {'z8', 'z11', 'z13', 'z15'}
    assert all(g.bounds[0] < boundary < g.bounds[2] for g in map(_projected, broad))


def _at_30(features):
    return [f for f in features if f['properties']['depth_ft'] == 30]


def test_v3_unknown_support_is_shoal_safe(tmp_path, tracer):
    import numpy as np
    from shapely.geometry import Point
    from shapely.ops import polygonize

    # Unclamped Gaussian smoothing erases this interior pinnacle; keep the
    # kit's unchanged Gaussian smoothing only for the measured control.
    depths = np.full((41, 41), 40.0)
    depths[20, 20] = 25
    measured, _, _ = _trace(tmp_path / 'measured', tracer, depths, 3)
    assert not any(f['properties']['tier'] == 'z13' for f in _at_30(measured))
    unknown, affine, _ = _trace(tmp_path / 'unknown', tracer, depths, 2)
    rings = [face for f in _at_30(unknown) if f['properties']['tier'] == 'z13'
             for face in polygonize(_projected(f).geoms)]
    assert any(face.contains(Point(affine @ (20.5, 20.5))) for face in rings)


@pytest.mark.parametrize('support', [1, 0, 255])
def test_v3_interpolated_or_nodata_support_never_traced(tmp_path, tracer, support):
    # An allow-all/nonzero mask would also admit interpolation or invalid codes.
    features, _, _ = _trace(tmp_path, tracer, _slope(), support)
    assert features == []


def test_v3_estimated_blocks_match_whole_window(tmp_path, tracer):
    from shapely import hausdorff_distance

    # A missing halo or incorrect ownership rule changes geometry at a seam.
    # Avoid a plateau exactly at a kit level; keep the shoal and its notch.
    depths = _shelf(2) + 0.25
    whole, _, _ = _trace(tmp_path / 'whole', tracer, depths, 2)
    blocked, _, _ = _trace(tmp_path / 'blocked', tracer, depths, 2, block_max_pixels=5000)
    assert whole
    assert [(f['id'], f['properties']) for f in blocked] == [(f['id'], f['properties']) for f in whole]
    whole_length = block_length = 0
    for a, b in zip(whole, blocked, strict=True):
        ga, gb = _projected(a), _projected(b)
        assert hausdorff_distance(ga, gb, densify=0.25) <= min(1, tracer[0].CONTOUR_TOLERANCE_M), a['id']
        whole_length += ga.length
        block_length += gb.length
    assert block_length == pytest.approx(whole_length, rel=0.01)


def _shelf(width):
    import numpy as np

    depths = np.full((101, 101), 40.0)
    depths[:50, :75] = 20
    depths[:30, 75:] = 20
    depths[50, 40:40 + width] = 25
    return depths


def _assert_ridge_shoal(features, affine, to_ll, width):
    from shapely.geometry import LineString, shape

    crossed = []
    for f in features:
        geometry = shape(f['geometry'])
        for col in range(40, 40 + width):
            to_shelf = LineString([to_ll.transform(*(affine @ (col + 0.5, row))) for row in (50.5, 49.5)])
            if geometry.intersects(to_shelf):
                crossed.append((f['id'], col))
    assert not crossed


@pytest.mark.parametrize('width', [1, 2])
def test_v3_estimated_narrow_shoal_survives_simplification(tmp_path, tracer, width):
    # Footprint-only simplification cuts the narrow 30 ft notch on the shelf's long edge.
    features, affine, to_ll = _trace(tmp_path, tracer, _shelf(width), 2)
    lines = _at_30(features)
    assert any(f['properties']['tier'] == 'z15' for f in lines)
    _assert_ridge_shoal(lines, affine, to_ll, width)


def test_v3_estimated_shoal_survives_clip_boundary(tmp_path, tracer):
    # Testing faces after the east clip cannot detect a notch with open ends.
    features, affine, to_ll = _trace(tmp_path, tracer, _shelf(1), 2, east_at=(40.75, 50.5))
    lines = _at_30(features)
    assert lines
    _assert_ridge_shoal(lines, affine, to_ll, 1)
