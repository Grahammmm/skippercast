"""Audit persisted coarse metadata and real GeoTIFF headers, without a region run."""

import hashlib
import json

import numpy as np
import pytest
import rasterio as rio

from scripts.relief.north_b_coarse_audit import main
from skippercast.relief.coarse import write_coarse

REGION = 'shelter-cove-north-mendocino'
BOUNDS = [-120.2, 37.99, -119.8, 38.05]  # Synthetic, not this region's operational bounds.
CELL = 1000
TRANSFORM = rio.Affine(CELL, 0, -18000, 0, -CELL, 4000)
SHAPE = (7, 36)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path, doc):
    path.write_text(json.dumps(doc), encoding='utf-8')


@pytest.fixture
def saved(tmp_path):
    config, metadata, grid = (tmp_path / name for name in ('region.json', 'coarse.json', 'coarse-3310.tif'))
    _write_json(config, {'id': REGION, 'bounds': BOUNDS, 'fishing_bounds': [-120.1, 38, -119.9, 38.01]})
    _write_json(metadata, {'region': REGION, 'bbox': BOUNDS, 'cell_m': CELL})
    # The real producer writes a matching header even when every cell is nodata.
    write_coarse(grid, np.full(SHAPE, np.nan, dtype='float32'), TRANSFORM)
    return config, metadata, grid


def _args(saved):
    config, metadata, grid = saved
    return ['--region-config', str(config), '--metadata', str(metadata), '--metadata-sha256', _sha(metadata),
            '--grid', str(grid), '--grid-sha256', _sha(grid)]


@pytest.mark.parametrize(('shift', 'exit_code'), [(0, 0), (1, 1)], ids=['fits', 'equal-size-offset'])
def test_extent_is_georeferenced_not_shape_or_valid_cell_coverage(saved, capsys, shift, exit_code):
    """A shape-only, corner-only, or fishing_bounds check misses a real region edge."""
    if shift:
        write_coarse(saved[2], np.full(SHAPE, np.nan, dtype='float32'),
                     TRANSFORM @ rio.Affine.translation(shift, 0))
    assert main(_args(saved)) == exit_code
    report = json.loads(capsys.readouterr().out)
    assert report['extent_fits'] is (shift == 0)
    assert report['valid_cell_coverage'] == 'not_assessed'
    assert report['region_bounds_wgs84'] == BOUNDS
    assert report['grid_envelope_3310'] == [-18000 + shift * CELL, -3000, 18000 + shift * CELL, 4000]
    # At the south edge, projected mid-edge samples are ~18 m below the corner-only box.
    assert report['region_envelope_3310'] == pytest.approx([-17541.931, -2930.919, 17541.931, 3757.521], abs=0.01)


@pytest.mark.parametrize('member', ['metadata', 'grid'])
def test_expected_digest_detects_changed_output(saved, capsys, member):
    """An otherwise usable output from another version is not the pinned one."""
    args = _args(saved)
    if member == 'metadata':
        with saved[1].open('a', encoding='utf-8') as file:
            file.write('\n')
    else:
        write_coarse(saved[2], np.full(SHAPE, -10, dtype='float32'), TRANSFORM)
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    result = capsys.readouterr()
    assert not result.out
    assert f'coarse {member} SHA-256 mismatch' in result.err


@pytest.mark.parametrize('field', ['region', 'bbox'])
def test_matching_output_digests_cannot_override_the_intended_region(saved, capsys, field):
    """Hashing an output cannot make the wrong region ID or census bbox authoritative."""
    doc = json.loads(saved[1].read_bytes())
    doc[field] = 'fort-bragg-point-arena' if field == 'region' else [-120.1, 38, -119.9, 38.01]
    _write_json(saved[1], doc)
    with pytest.raises(SystemExit) as error:
        main(_args(saved))
    assert error.value.code == 2
    assert 'does not match intended region config' in capsys.readouterr().err


@pytest.mark.parametrize(('crs', 'transform', 'diagnostic'), [
    pytest.param(None, TRANSFORM, 'EPSG:3310 CRS', id='unreferenced-crs'),
    pytest.param('EPSG:32610', TRANSFORM, 'EPSG:3310 CRS', id='wrong-projected-crs'),
    pytest.param('EPSG:3310', rio.Affine(CELL, 25, -18000, 0, -CELL, 4000), 'north-up', id='sheared-affine'),
    pytest.param('EPSG:3310', rio.Affine(CELL, 0, -18000, 0, -500, 4000), 'matching cell_m', id='wrong-pixel-size'),
])
def test_digest_matched_tiff_still_requires_coarse_grid_georeferencing(saved, capsys, crs, transform, diagnostic):
    """A pinned file with plausible numeric coordinates can still have the wrong CRS or pixel geometry."""
    with rio.open(saved[2], 'w', driver='GTiff', crs=crs, transform=transform,
                  width=SHAPE[1], height=SHAPE[0], count=1, dtype='float32') as dst:
        dst.write(np.zeros(SHAPE, dtype='float32'), 1)
    with pytest.raises(SystemExit) as error:
        main(_args(saved))
    assert error.value.code == 2
    assert diagnostic in capsys.readouterr().err
