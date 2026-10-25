"""Portable synthetic GeoTIFFs; dependencies are imported only inside guards."""
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from pathlib import Path
import os
import socket
import subprocess
from unittest.mock import patch

MESSAGE = 'Normalized raster must contain unpacked physical values'


@contextmanager
def offline_scope():
    """Reversible ordinary-test sentinels; no import-time environment changes."""
    def refused(*args, **kwargs):
        raise RuntimeError('SC115 offline sentinel: network/model/subprocess forbidden')
    with ExitStack() as stack:
        for owner, names in ((socket, ('connect', 'connect_ex')),
                             (subprocess, ('Popen',)),
                             (os, ('system', 'popen', 'fork', 'posix_spawn', 'posix_spawnp'))):
            for name in names:
                if hasattr(owner, name):
                    stack.enter_context(patch.object(owner, name, refused))
        stack.enter_context(patch.object(socket.socket, 'connect', refused))
        stack.enter_context(patch.object(socket.socket, 'connect_ex', refused))
        stack.enter_context(patch.object(socket, 'getaddrinfo', refused))
        yield


def make_raster(path, *, scales=None, offsets=None, compress=None, count=2,
                dtype='float32', crs='EPSG:32610', datum='MLLW', mask=True):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin
    options = dict(driver='GTiff', width=3, height=2, count=count, dtype=dtype,
                   crs=crs, transform=from_origin(690000, 3920000, 2, 2))
    if dtype == 'float32':
        options['nodata'] = np.nan
    if compress:
        options['compress'] = compress
    with rasterio.open(path, 'w', **options) as ds:
        for band in range(1, count + 1):
            values = np.full((2, 3), band * 10, dtype=dtype)
            if dtype == 'float32':
                values[1, 2] = np.nan
            ds.write(values, band)
            ds.set_band_description(band, 'depth_m' if band == 1 else 'uncertainty_m')
        ds.update_tags(vertical_datum=datum, depth_basis='nominal')
        if scales is not None:
            ds.scales = scales
        if offsets is not None:
            ds.offsets = offsets
        if mask:
            ds.write_mask(np.array([[255, 0, 255], [255, 255, 255]], dtype='uint8'))
    return Path(path)


def hashes(root):
    return {str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob('*')) if p.is_file()}
