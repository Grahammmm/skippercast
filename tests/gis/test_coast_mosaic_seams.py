"""MB-02: the whole-segment mosaic blends every source boundary (40 m elevation feather).

Real GDAL mosaics of synthetic sources, rendered through scripts/build_bathy_tiles.py. The seam
is measured as the CIE L* step between the two rendered pixel columns either side of the boundary.
"""
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

from research.scripts.coast_mvp import coast_mosaic as cm
from scripts import build_bathy_tiles as bt
from tests.gis.test_build_bathy_tiles import decode_png

BOUNDARY_X = 1500.0        # EPSG:3310 metres; source A west of it, source B east of it
OFFSET_M = 0.5


def surface(x, y):
    """A sloping shelf with relief at 25-400 m wavelengths (amplitude ~ wavelength / 250), like real seafloor."""
    z = -30 - 0.004 * x
    for wavelength, angle in ((400, 0.3), (230, 1.9), (130, 0.9), (70, 2.6), (40, 1.3), (25, 0.1)):
        k = 2 * np.pi / wavelength
        z = z + wavelength / 250 * np.sin(k * (x * np.cos(angle) + y * np.sin(angle)) + angle)
    return z


def write_grid(path, west, north, cols, rows, values, res):
    with rasterio.open(path, 'w', driver='GTiff', width=cols, height=rows, count=1, dtype='float32',
                       nodata=-9999, crs='EPSG:3310', transform=from_origin(west, north, res, res)) as grid:
        grid.write(values.astype('float32'), 1)


def row(ident, path, resolution):
    return dict(id=ident, path=str(path), sha256=cm.file_hash(path), resolution_m=resolution, units='m',
                vertical_datum='NAVD88', vertical_offset_m=0, value_convention='elevation_positive_up',
                citation='synthetic fixture', rights='synthetic', attribution='synthetic',
                offset_note='synthetic constant, not geodetic')


def two_sources(tmp_path, *, overlap=False, offset_m=OFFSET_M):
    """A (west) and B (east, +offset_m) abut at x = 1500 m; with overlap=True, A is a 5 m survey lying over a
    10 m B that covers everything, so the boundary is A's edge inside B. offset_m=0 is the seamless reference."""
    tmp_path.mkdir(exist_ok=True)
    w, s, e, n = transform_bounds('EPSG:3310', 'EPSG:4326', 0, -3200, 3200, 0)
    region = tmp_path / 'region.json'
    region.write_text(json.dumps({'id': 'seams', 'bounds': [w, s, e, n]}))
    west, north = -1000.0, 1000.0
    rows_out = []
    for ident, res, x0, x1, offset in (('a', 5 if overlap else 10, -1000, BOUNDARY_X, 0.0),
                                        ('b', 10, -1000 if overlap else BOUNDARY_X, 4200, offset_m)):
        cols, rows = int((x1 - x0) / res), int((north + 4200) / res)
        yy, xx = np.mgrid[0:rows, 0:cols]
        x, y = x0 + (xx + 0.5) * res, north - (yy + 0.5) * res
        path = tmp_path / f'{ident}.tif'
        write_grid(path, x0, north, cols, rows, surface(x, y) + offset, res)
        rows_out.append(row(ident, path, res))
    table = tmp_path / 'sources.json'
    table.write_text(json.dumps({'schema_version': 1, 'sources': rows_out}))
    return region, table


def read(out):
    with rasterio.open(out / 'elevation.tif') as depth, rasterio.open(out / 'contributor.tif') as codes:
        return depth.read(1), codes.read(1), depth.transform


def lstar(rgb):
    c = rgb.astype(np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    y = lin @ np.array([0.2126, 0.7152, 0.0722])
    f = np.where(y > (6 / 29) ** 3, np.cbrt(y), y / (3 * (6 / 29) ** 2) + 4 / 29)
    return 116 * f - 16


def across_boundary(elevation, transform):
    """Per-row L* step from the last rendered column west of the boundary to the first one east of it,
    in a 10 m-per-pixel render of the mosaic with the z13 'medium' relief (the builder's default)."""
    pad = bt.pad_for(bt.ENHANCE['medium'])
    size = bt.TILE + 2 * pad
    cb = int(round((BOUNDARY_X - transform.c) / 10))      # first column east of the boundary
    r0 = (elevation.shape[0] - size) // 2
    crop = elevation[r0:r0 + size, cb - size // 2:cb + size // 2]
    assert crop.shape == (size, size)
    invalid = crop == cm.NODATA
    assert not invalid.any()
    tiles = bt.render_zoom({(0, 0): (crop, invalid, 10.0)}, 13, bt.ENHANCE['medium'])
    light = lstar(decode_png(tiles[(13, 0, 0)])[..., :3])
    east = size // 2 - pad                                 # core column just east of the boundary
    return light[:, east] - light[:, east - 1]


def test_feather_constant_matches_the_tile_builder():
    assert cm.FEATHER_M == bt.FEATHER_M == 40.0


@pytest.mark.parametrize('overlap', [False, True], ids=['abutting tiles', 'finer survey over coarser'])
def test_half_metre_offset_seam_is_blended_and_far_cells_are_unchanged(tmp_path, overlap):
    region, table = two_sources(tmp_path, overlap=overlap)
    hard = cm.mosaic(region, table, tmp_path / 'hard', reserve_gib=0, feather_m=0)
    soft = cm.mosaic(region, table, tmp_path / 'soft', reserve_gib=0)
    ref_region, ref_table = two_sources(tmp_path / 'ref', overlap=overlap, offset_m=0.0)
    cm.mosaic(ref_region, ref_table, tmp_path / 'ref' / 'mosaic', reserve_gib=0, feather_m=0)
    z0, c0, transform = read(tmp_path / 'hard')
    z1, c1, _ = read(tmp_path / 'soft')
    reference = across_boundary(read(tmp_path / 'ref' / 'mosaic')[0], transform)
    # the seam step: how far the rendered step across the boundary departs from the seamless terrain's
    before = float(np.median(np.abs(across_boundary(z0, transform) - reference)))
    after = float(np.median(np.abs(across_boundary(z1, transform) - reference)))
    print(f'MB-02 synthetic 0.5 m seam ({"overlap" if overlap else "abutting"}): '
          f'rendered dL* step across the boundary before {before:.2f}, after {after:.2f}')
    assert before > 3            # today's hard boundary is a visible step
    assert after <= 3
    # identity, support and every cell centred more than 40 m from the boundary are untouched
    assert np.array_equal(c0, c1) and np.array_equal(z0 == cm.NODATA, z1 == cm.NODATA)
    centres = transform.c + (np.arange(z0.shape[1]) + 0.5) * 10
    far = np.abs(centres - BOUNDARY_X) > cm.FEATHER_M
    assert np.array_equal(z0[:, far], z1[:, far])
    moved = np.abs(z1 - z0)
    assert moved[:, ~far].max() <= OFFSET_M / 2 + 0.05
    assert soft['seam_feather']['changed_cells'] == int((z0 != z1).sum()) > 0
    [seam] = soft['seam_feather']['boundaries']
    assert seam['sources'] == ['a', 'b'] and abs(seam['mean_offset_m'] - OFFSET_M) < 0.05
    assert soft['seam_feather']['feather_m'] == 40.0 and hard['seam_feather']['feather_m'] == 0
    assert soft['contributor_cells'] == hard['contributor_cells']


def test_feather_is_block_independent_and_never_fills_holes(tmp_path):
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0:150, 0:170]
    elevation = (-40 + 0.05 * xx + rng.normal(0, 0.05, xx.shape)).astype('float32')
    codes = np.where(xx < 60, 1, np.where(yy < 70, 2, 3)).astype('uint16')    # three tiles and a T junction
    elevation[codes == 2] += 0.8
    elevation[codes == 3] -= 0.6
    codes[40:55, 100:120] = 0                                                  # a survey hole on a boundary
    elevation[codes == 0] = cm.NODATA
    profile = dict(driver='GTiff', width=170, height=150, count=1, crs='EPSG:3310',
                   transform=from_origin(0, 0, 10, 10), tiled=True, blockxsize=16, blockysize=16)
    with rasterio.open(tmp_path / 'z.tif', 'w', dtype='float32', nodata=cm.NODATA, **profile) as grid:
        grid.write(elevation, 1)
    with rasterio.open(tmp_path / 'c.tif', 'w', dtype='uint16', nodata=0, **profile) as grid:
        grid.write(codes, 1)
    whole, moved = cm.seam_feather(elevation, codes)
    outs = []
    for block in (32, 512):
        cm.feather_raster(tmp_path / 'z.tif', tmp_path / 'c.tif', tmp_path / f'out{block}.tif', block=block)
        with rasterio.open(tmp_path / f'out{block}.tif') as grid:
            outs.append(grid.read(1))
    assert np.array_equal(outs[0], outs[1]) and np.array_equal(outs[0], whole)
    assert np.array_equal(whole == cm.NODATA, codes == 0)                     # no new support
    assert moved.any()
    # every changed cell centre lies within 40 m of a boundary: < 4.5 cells from a cell of another contributor
    from scipy import ndimage
    near = np.zeros(codes.shape, bool)
    for code in (1, 2, 3):
        other = (codes > 0) & (codes != code)
        near |= (codes == code) & (ndimage.distance_transform_edt(~other) < 4.5)
    assert not (moved & ~near).any()


def test_feather_width_is_validated(tmp_path):
    region, table = two_sources(tmp_path)
    for bad in (-1, 3, float('nan'), True, 500):
        with pytest.raises(ValueError, match='feather_m'):
            cm.mosaic(region, table, tmp_path / 'out', reserve_gib=0, feather_m=bad)
    assert not (tmp_path / 'out').exists()


def mixed_support_sources(tmp_path):
    region = tmp_path / 'region.json'
    bounds = transform_bounds('EPSG:3310', 'EPSG:4326', 0, -900, 800, 0)
    region.write_text(json.dumps({'id': 'mixed-support', 'bounds': bounds}))
    fine, coarse, evidence = (tmp_path / name for name in ('a.tif', 'b.tif', 'support.tif'))
    # Offset and stripe individual 4 m pixels to expose a different sampling kernel/overview.
    west, north = -80, 80
    yy, xx = np.mgrid[0:270, 0:120]
    values = np.full((270, 120), 3, dtype='uint8')
    values[:, 40:52:2] = 1
    values[:, 52:65] = 2
    values[:, 65:70] = 0  # elevation exists, but evidence has nodata
    values[160:245, -4] = 1  # x=385 m: the fine-side slope sample, not the edge cell at x=395 m
    write_grid(fine, west, north, 120, 270, -10 + (yy + xx) * 0.0001, 4)
    write_grid(coarse, 200, north, 50, 108, np.full((108, 50), -9.5), 10)
    with rasterio.open(evidence, 'w', driver='GTiff', height=270, width=120, count=1,
                       dtype='uint8', crs='EPSG:3310', transform=from_origin(west, north, 4, 4), nodata=0) as grid:
        grid.write(values, 1)
        grid.build_overviews([2], rasterio.enums.Resampling.nearest)
    table = tmp_path / 'sources.json'
    unbound = row('a', fine, 4)
    doc = {'schema_version': 1, 'sources': [row('b', coarse, 10), unbound]}
    return region, table, doc, evidence, values


def test_mosaic_carries_only_winning_support_and_feathers_with_lowest_class(tmp_path):
    # At the real raster boundary: a losing legacy grid must not downgrade the hard winner;
    # the same grid must downgrade the winning measured cells whenever it joins the blend.
    region, table, doc, evidence, native = mixed_support_sources(tmp_path)
    table.write_text(json.dumps(doc))
    legacy = cm.mosaic(region, table, tmp_path / 'legacy', reserve_gib=0)
    doc['sources'][1].update(support_path=evidence.name, support_sha256=cm.file_hash(evidence))
    table.write_text(json.dumps(doc))
    hard, soft = tmp_path / 'hard', tmp_path / 'soft'
    cm.mosaic(region, table, hard, reserve_gib=0, feather_m=0)
    cm.mosaic(region, table, soft, reserve_gib=0)
    _, codes, transform = read(hard)
    with rasterio.open(hard / 'support_class.tif') as raster:
        classes = raster.read(1)
        assert (raster.transform, raster.nodata, raster.dtypes) == (transform, 0, ('uint8',))
        assert not raster.overviews(1)
    x = transform.c + (np.arange(codes.shape[1]) + 0.5) * 10
    y = transform.f - (np.arange(codes.shape[0]) + 0.5) * 10
    rr, cc = np.nonzero(codes == 1)
    expected = native[((80 - y[rr]) // 4).astype(int), ((x[cc] + 80) // 4).astype(int)]
    assert set(expected) == {0, 1, 2, 3}
    np.testing.assert_array_equal(classes[rr, cc], np.where(expected == 0, 2, expected))
    assert np.all(classes[codes == 2] == 2) and np.any(codes == 2)
    assert np.any(codes == 0)
    np.testing.assert_array_equal(classes == 0, codes == 0)

    with rasterio.open(soft / 'support_class.tif') as raster:
        blended = raster.read(1)
    assert np.all(blended <= classes)
    far = np.abs(x - 400) >= 40
    np.testing.assert_array_equal(blended[:, far], classes[:, far])
    col = int(np.flatnonzero(x == 395)[0])
    top = int(np.flatnonzero(y == -95)[0])
    bottom = int(np.flatnonzero(y == -715)[0])
    assert classes[top, col:col + 2].tolist() == [3, 2]
    assert blended[top, col:col + 2].tolist() == [2, 2]
    assert classes[bottom, col:col + 2].tolist() == [3, 2]
    assert blended[bottom, col:col + 2].tolist() == [1, 1]
    manifest = json.loads((soft / 'manifest.json').read_text())
    assert manifest['seam_feather']['changed_cells'] > 0
    entry = manifest['outputs'].pop('support_class')
    assert entry == {'path': 'support_class.tif', 'sha256': cm.file_hash(soft / 'support_class.tif'),
                     'bytes': (soft / 'support_class.tif').stat().st_size}
    assert manifest['outputs'] == legacy['outputs']
    assert not (tmp_path / 'legacy' / 'support_class.tif').exists()


@pytest.mark.parametrize('defect', ['stale pin', 'shifted grid', 'cap'])
def test_support_input_is_bound_to_the_winning_grid_and_can_only_lower(tmp_path, defect):
    # Otherwise a stale/shifted raster could certify unrelated pixels, or an R3 cap be ignored.
    region, table, doc, evidence, _ = mixed_support_sources(tmp_path)
    if defect == 'shifted grid':
        with rasterio.open(evidence, 'r+') as raster:
            raster.transform = from_origin(-76, 80, 4, 4)
    doc['sources'][1].update(support_path=evidence.name,
                             support_sha256='a' * 64 if defect == 'stale pin' else cm.file_hash(evidence))
    if defect == 'cap':
        doc['sources'][1]['support_class_cap'] = 1
    table.write_text(json.dumps(doc))
    out = tmp_path / 'result'
    if defect != 'cap':
        with pytest.raises(ValueError, match='Support hash changed' if defect == 'stale pin' else 'aligned uint8'):
            cm.mosaic(region, table, out, reserve_gib=0)
        assert not out.exists()
    else:
        cm.mosaic(region, table, out, reserve_gib=0, feather_m=0)
        _, codes, _ = read(out)
        with rasterio.open(out / 'support_class.tif') as raster:
            np.testing.assert_array_equal(raster.read(1), codes)
