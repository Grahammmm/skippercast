"""Tiny source-shaped BlueTopo samples; all binary output belongs to data_root."""
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
from rasterio.transform import Affine


def make_case(data_root):
    data_root = Path(data_root)
    data_root.mkdir(parents=True, exist_ok=False)
    # A single 250 m planning cell, safely inside the actual projected envelope.
    affine = Affine(25, 0, 0, 0, -25, 0)
    unproject = Transformer.from_crs(3310, 4326, always_xy=True)
    west, south = unproject.transform(1, -249)
    east, north = unproject.transform(249, -1)
    config = {'reference_pixel_m': 25, 'cell_size_m': 250,
              'reference_depth_m': [0, 100], 'bounds': [west, south, east, north]}
    coarse = np.full((10, 10), np.nan, dtype='float32')
    fine = coarse.copy()
    coarse[2:8, 2:8] = -50
    fine[3:6, 3:6] = 5
    fine[4, 4] = np.nan  # Fine hole retains coarse valid data.
    fine[1, 1] = -25   # Fine valid value fills a coarse hole.
    tiles = [{'id': 'coarse', 'native_resolution_m': 50, 'delivered_date': '2026-01-01'},
             {'id': 'fine', 'native_resolution_m': 25, 'delivered_date': '2026-01-02'}]
    samples = []
    for tile, elevation in zip(tiles, (coarse, fine)):
        path = data_root / (tile['id'] + '.npz')
        np.savez_compressed(path, elevation=elevation,
                            transform=np.array(tuple(affine)[:6]),
                            crs=np.array(CRS.from_epsg(3310).to_wkt()))
        samples.append((path, {'sample_shape': [10, 10]}))
    expected = np.zeros((10, 10), dtype='uint8')
    expected[2:8, 2:8] = 2
    expected[3:6, 3:6] = 1
    expected[4, 4] = 2
    expected[1, 1] = 2
    return config, tiles, samples, expected, affine
