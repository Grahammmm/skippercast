"""Exercise the preflight CLI boundary with real, tiny local GeoTIFFs."""

import numpy as np
import pytest
import rasterio
from affine import Affine

from scripts.relief import central_normalized_preflight as preflight
from skippercast.relief import select


@pytest.mark.parametrize(
    'case, code, status, detail',
    [
        # A valid pair must not be reported as selected or rejected.
        ('identical-lattice', 0, 'compatible', 'CRS, affine transform and shape match'),
        # A dimensions-only check would accept the shifted mask.
        ('equal-shape-half-pixel-shift', 1, 'incompatible', 'mismatched affine transform'),
        # Matching numeric coordinates do not identify the same CRS.
        ('different-crs', 1, 'incompatible', 'mismatched CRS'),
        # Matching origin and pixel size do not guarantee matching coverage.
        ('different-shape', 1, 'incompatible', 'mismatched shape'),
        # Matching geometry alone would accept a float support mask instead of uint8.
        ('wrong-mask-dtype', 1, 'incompatible', 'aligned uint8'),
        # Two undefined coordinate systems are not a known common lattice.
        ('absent-crs', 2, 'unavailable', 'both inputs must declare a CRS'),
        # Missing or undecodable inputs must not crash or look like grid mismatches.
        ('missing-mask', 2, 'unavailable', 'both inputs must be local regular files'),
        ('unreadable-mask', 2, 'unavailable', 'could not open both inputs'),
    ],
)
def test_reports_one_pair(case, code, status, detail, tmp_path, capsys, monkeypatch):
    def unexpected_selection(*args, **kwargs):
        pytest.fail('preflight must not invoke select.main')

    monkeypatch.setattr(select, 'main', unexpected_selection)
    grid, support = tmp_path / 'grid.tif', tmp_path / 'support.tif'
    profile = dict(driver='GTiff', count=1, width=4, height=3,
                   crs=None if case == 'absent-crs' else 'EPSG:26910',
                   transform=Affine(10, 0, 500000, 0, -10, 4000000))
    with rasterio.open(grid, 'w', dtype='float32', **profile) as dst:
        dst.write(np.full((3, 4), -10, dtype='float32'), 1)

    if case == 'equal-shape-half-pixel-shift':
        profile['transform'] = profile['transform'] @ Affine.translation(0.5, 0)
    elif case == 'different-crs':
        profile['crs'] = 'EPSG:26911'
    elif case == 'different-shape':
        profile['width'] = 5
    if case == 'unreadable-mask':
        support.write_bytes(b'not a GeoTIFF')
    elif case != 'missing-mask':
        dtype = 'float32' if case == 'wrong-mask-dtype' else 'uint8'
        with rasterio.open(support, 'w', dtype=dtype, **profile) as dst:
            dst.write(np.ones((3, profile['width']), dtype=dtype), 1)

    assert preflight.main([str(grid), str(support)]) == code
    output = capsys.readouterr().out
    assert output.startswith(f'{status}: ')
    assert detail in output
    assert 'does not qualify or select an input' in output
