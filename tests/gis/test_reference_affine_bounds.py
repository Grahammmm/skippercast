"""Synthetic NPZ samples exercise reference mosaic clipping with full affines."""
import numpy as np
from pyproj import CRS, Transformer
import pytest
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject

from skippercast.seafloor.grid import mosaic_reference


@pytest.mark.parametrize(('x_shear', 'y_shear', 'shallow_cell'), [
    pytest.param(0, 0, (8, 1), id='north-up'),
    pytest.param(50, 0, (8, 6), id='x-shear'),
    pytest.param(0, 50, (1, 3), id='y-shear'),
])
def test_reference_window_matches_full_grid(tmp_path, x_shear, y_shear, shallow_cell):
    unproject = Transformer.from_crs(3310, 4326, always_xy=True)
    west, south = unproject.transform(1, -249)
    east, north = unproject.transform(249, -1)
    config = {'reference_pixel_m': 25, 'cell_size_m': 250,
              'reference_depth_m': [0, 100], 'bounds': [west, south, east, north]}
    dst_transform = Affine(25, 0, 0, 0, -25, 0)
    src_transform = Affine(25, x_shear, 25, y_shear, -25, -150)
    crs = CRS.from_epsg(3310).to_wkt()
    path = tmp_path / 'sample.npz'
    elevation = np.array([[5, np.nan, -30], [5, 5, 5], [-40, 5, 5]], dtype='float32')
    np.savez_compressed(path, elevation=elevation,
                        transform=np.array(tuple(src_transform)[:6]), crs=np.array(crs))

    # The oracle warps known classes directly into the entire planning cell.
    expected = np.zeros((10, 10), dtype='uint8')
    reproject(np.array([[1, 0, 2], [1, 1, 1], [2, 1, 1]], dtype='uint8'), expected,
              src_transform=src_transform, src_crs=crs, dst_transform=dst_transform,
              dst_crs=crs, src_nodata=0, dst_nodata=0, resampling=Resampling.nearest)
    assert expected[shallow_cell] == 2
    if x_shear or y_shear:
        row, col = shallow_cell
        # The old diagonal-only bounds covered rows 6–8 and columns 1–3.
        assert not (6 <= row < 9 and 1 <= col < 4)

    tile = {'id': 'fixture', 'native_resolution_m': 25, 'delivered_date': '2026-01-01'}
    actual, affine = mosaic_reference(config, [tile], [(path, {})])
    assert affine == dst_transform
    np.testing.assert_array_equal(actual, expected)
