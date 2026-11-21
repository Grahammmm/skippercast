"""Preserve decoded RGBA bytes across extraction of the shared assembly."""
from hashlib import sha256

import pytest

from skippercast import style
from skippercast.relief import tiles


@pytest.mark.gis
@pytest.mark.parametrize('joined, expected', [
    (False, '686b1fd55456d552c8d1b3788e8919c65db65dd919db19c25b94c19352133a2c'),
    (True, 'b6c5b3968eb11ef69dc50ea435fc633e7370bc657b2cf3a4ad4d6bef9940040d'),
])
def test_bake_rgba_bytes(tmp_path, joined, expected):
    # Detect changed halo, feather/sky-view join or native output alpha.
    import numpy as np
    import rasterio as rio

    def grid(name, values, cell, origin):
        path = tmp_path / name
        with rio.open(path, 'w', driver='GTiff', crs='EPSG:3310', count=1,
                      dtype='float32', width=values.shape[1], height=values.shape[0],
                      transform=rio.transform.from_origin(*origin, cell, cell)) as dst:
            dst.write(values.astype('float32'), 1)
        return rio.open(path)

    y, x = np.mgrid[:88, :104]
    fine = -18 + x / 30 + 6 * np.exp(-((x - 48)**2 + (y - 37)**2) / 50)
    fine[:11, :23] = np.nan
    j, i = np.mgrid[:124, :132]
    lower = -32 + i / 20 + j / 30
    out = tmp_path / 'rgba.tif'
    with grid('native.tif', fine, 1, (0, 88)) as src, grid('lower.tif', lower, 2, (-80, 168)) as base:
        with rio.open(out, 'w', **dict(src.profile, count=4, dtype='uint8')) as dst:
            tiles._bake(src, [(base, True)] if joined else (), style.load().view('baked'),
                        {'closeup': dst}, tiles._builder(), native=True, chunk=64)
    with rio.open(out) as ds:
        actual = sha256(ds.read().tobytes()).hexdigest()
    assert actual == expected
