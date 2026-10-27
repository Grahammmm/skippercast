"""Offline real-GDAL controls for the whole-segment research mosaic."""
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

from research.scripts.coast_mvp.coast_mosaic import file_hash, load_sources, mosaic


def fixture(tmp_path):
    w, s, e, n = transform_bounds('EPSG:3310', 'EPSG:4326', -100, -100, 0, 0)
    region = tmp_path / 'region.json'
    region.write_text(json.dumps({'id': 'synthetic', 'bounds': [w, s, e, n]}))
    rows = []
    for ident, res, value in [('fine', 5, -20), ('coarse', 10, 100)]:
        a = np.full((int(100/res), int(100/res)), value, dtype='float32')
        if ident == 'fine':
            a[:, :10] = -9999
        a[0:2, 0:2] = -9999
        path = tmp_path / f'{ident}.tif'
        with rasterio.open(path, 'w', driver='GTiff', width=a.shape[1], height=a.shape[0],
                           count=1, dtype='float32', nodata=-9999, crs='EPSG:3310',
                           transform=from_origin(-100, 0, res, res)) as grid:
            grid.write(a, 1)
        rows.append(dict(id=ident, path=str(path), sha256=file_hash(path), resolution_m=res,
                         units='m', vertical_datum='unstated' if ident=='coarse' else 'NAVD88',
                         vertical_offset_m=0 if ident=='coarse' else 3,
                         value_convention='depth_positive_down' if ident=='coarse' else 'elevation_positive_up',
                         citation='synthetic fixture', rights='synthetic', attribution='synthetic',
                         offset_note='synthetic constant, not geodetic'))
    table = tmp_path / 'sources.json'
    table.write_text(json.dumps({'schema_version': 1, 'sources': list(reversed(rows))}))
    return region, table


def test_real_gdal_priority_offsets_holes_and_contributors(tmp_path):
    region, table = fixture(tmp_path)
    out = tmp_path / 'result'
    manifest = mosaic(region, table, out, reserve_gib=0)
    assert manifest['status'] == 'review_required'
    assert manifest['stats']['minimum_elevation_m'] == -100
    assert manifest['stats']['maximum_elevation_m'] == -17
    assert manifest['stats']['hole_cells'] > 0
    assert manifest['stats']['overlap_cells'] > 0
    assert manifest['sources'][0]['id'] == 'fine'
    assert manifest['sources'][1]['datum_unresolved'] is True
    assert sum(manifest['contributor_cells'].values()) == manifest['stats']['valid_cells']
    with rasterio.open(out/'elevation.tif') as depth, rasterio.open(out/'contributor.tif') as codes, rasterio.open(out/'support_count.tif') as support:
        d, c, count = depth.read(1), codes.read(1), support.read(1)
        assert np.all(d[c == 1] == -17)
        assert np.all(d[c == 2] == -100)
        assert np.array_equal(depth.read_masks(1) > 0, c > 0)
        assert np.array_equal(count > 0, c > 0)
        assert int((count > 1).sum()) == manifest['stats']['overlap_cells']
        assert depth.crs.to_string() == 'EPSG:3310'
        assert depth.res == (10, 10)
        assert depth.tags(ns='IMAGE_STRUCTURE')['LAYOUT'] == 'COG'
    for entry in manifest['outputs'].values():
        assert file_hash(out/entry['path']) == entry['sha256']
    assert not (out/'work').exists()
    with pytest.raises(FileExistsError):
        mosaic(region, table, out, reserve_gib=0)


@pytest.mark.parametrize('change,match', [
    ({'sha256': '0'*64}, 'hash changed'),
    ({'vertical_offset_m': 1, 'vertical_datum': 'unstated'}, 'zero offset'),
    ({'units': 'ft'}, 'metre'),
    ({'resolution_m': 3}, 'resolution differs'),
    ({'vertical_offset_m': float('nan')}, 'finite'),
    ({'path': 'https://example.invalid/data.tif'}, 'local'),
    ({'path': '/vsicurl/https://example.invalid/data.tif'}, 'local'),
    ({'value_convention': 'unknown'}, 'value_convention'),
])
def test_refuse_changed_or_ambiguous_sources(tmp_path, change, match):
    _, table = fixture(tmp_path)
    doc = json.loads(table.read_text())
    doc['sources'][0].update(change)
    table.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match=match):
        load_sources(table)


def test_caps_fail_before_output(tmp_path):
    region, table = fixture(tmp_path)
    with pytest.raises(ValueError, match='cell cap'):
        mosaic(region, table, tmp_path/'out', max_cells=1)
    with pytest.raises(ValueError, match='reserve'):
        mosaic(region, table, tmp_path/'out', reserve_gib=1e12)
    assert not (tmp_path/'out').exists()


def test_duplicate_ids(tmp_path):
    _, table = fixture(tmp_path)
    doc = json.loads(table.read_text())
    doc['sources'].append(dict(doc['sources'][0]))
    table.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='unique'):
        load_sources(table)
