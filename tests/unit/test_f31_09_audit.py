"""F31-09 / C1-01: native grid inspection must not count packed samples as metres."""
from hashlib import sha256
from struct import pack

import pytest

pytestmark = pytest.mark.gis


@pytest.fixture
def inspect_grid(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from research.scripts.inspect_native_grid_units import inspect

    def run(sample, *, scale=1, offset=0):
        # An in-band nodata sentinel must remain in the raw hash but not the count.
        raw = np.array([[sample, -10]], dtype='int16')
        path = tmp_path / 'synthetic.tif'
        with rasterio.open(
            path, 'w', driver='GTiff', width=2, height=1, count=1,
            dtype=raw.dtype, crs='EPSG:4326', nodata=-10,
            transform=from_origin(0, 1, 1, 1),
        ) as dst:
            dst.write(raw, 1)
            dst.scales = (scale,)
            dst.offsets = (offset,)
        return inspect(path, (0, 0, 2, 1),
                       value_convention='elevation-m-positive-up', vertical_datum='unknown')

    return run


@pytest.mark.parametrize(('sample', 'shallow'), [(-120, 0), (-30, 1)])
def test_inspector_counts_unpacked_depth_and_preserves_evidence(inspect_grid, sample, shallow):
    receipt = inspect_grid(sample)
    assert receipt['valid_pixels_in_requested_bounds'] == 1
    assert receipt['nominal_0_300ft_valid_grid_pixels'] == shallow
    assert receipt['native_values_sha256'] == sha256(pack('=hh', sample, -10)).hexdigest()
    assert receipt['native_masks_sha256'] == sha256(bytes([255, 0])).hexdigest()
    assert receipt['measured_support'] == receipt['interpolation_mask'] == 'unverified'
    assert receipt['terrain_eligible'] is receipt['exportable'] is receipt['coverage_credit'] is False


@pytest.mark.parametrize(('scale', 'offset'), [(5, -20), (6, 0), (1, -100)])
def test_inspector_refuses_packed_120m_instead_of_counting_raw_20m(inspect_grid, scale, offset):
    # All three encodings store -20 for -120 m; either nonidentity field is enough to refuse.
    with pytest.raises(ValueError, match='scale/offset'):
        inspect_grid(-20, scale=scale, offset=offset)
