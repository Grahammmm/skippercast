"""Encoding-independent identity of normalized scientific raster content.

File SHA256 still verifies stored bytes. This additional reviewed identity permits
different lossless GeoTIFF encodings, never changed grids, masks or soundings.
"""
import hashlib
import json

import numpy as np
import rasterio
from rasterio.windows import Window

VERSION = 'normalized-raster-content-v1'


def raster_identity(path):
    digest = hashlib.sha256()
    with rasterio.open(path) as ds:
        if any(dtype != 'float32' for dtype in ds.dtypes):
            raise ValueError('Normalized raster must contain exact float32 values')
        authority = ds.crs.to_authority() if ds.crs else None
        if not authority:
            raise ValueError('Normalized raster needs an identified CRS for portable review')
        header = {'version': VERSION, 'crs': list(authority),
                  'transform': [float(v).hex() for v in list(ds.transform)[:6]],
                  'width': ds.width, 'height': ds.height, 'count': ds.count,
                  'descriptions': list(ds.descriptions),
                  'vertical_datum': ds.tags().get('vertical_datum', 'unknown'),
                  'depth_basis': ds.tags().get('depth_basis', 'unknown')}
        digest.update(json.dumps(header, sort_keys=True, separators=(',', ':')).encode())
        for band in range(1, ds.count + 1):
            for y in range(0, ds.height, 64):
                window = Window(0, y, ds.width, min(64, ds.height-y))
                values = ds.read(band, window=window, masked=True)
                raw = np.asarray(values.data, dtype='<f4')
                if np.isinf(raw).any():
                    raise ValueError('Infinite normalized raster value')
                valid = ~np.ma.getmaskarray(values) & np.isfinite(raw)
                digest.update(valid.astype('uint8').tobytes(order='C'))
                digest.update(np.where(valid, raw, np.float32(0)).astype('<f4').tobytes(order='C'))
    return {'version': VERSION, 'sha256': digest.hexdigest()}


def verify_review(receipt, review, path):
    for field in ('source_sha256', 'requested_bounds_wgs84', 'native_resolution_m',
                  'vertical_datum', 'valid_pixels_in_requested_bounds',
                  'nominal_0_300ft_pixels_in_requested_bounds'):
        if receipt[field] != review[field]:
            raise ValueError('Normalized source differs from reviewed '+field)
    if receipt.get('adapter_version') == 'measured-multibeam-grid-v1':
        for field in ('grid_spacing_m', 'native_sampling', 'preparation_receipt_sha256'):
            if receipt[field] != review.get(field):
                raise ValueError('Derived grid differs from reviewed '+field)
    identity = review.get('raster_identity')
    if identity is not None:
        if identity.get('version') != VERSION or raster_identity(path) != identity:
            raise ValueError('Normalized scientific raster differs from reviewed content')
    elif receipt['cog_sha256'] != review['cog_sha256']:
        raise ValueError('Normalized source differs from reviewed manifest; content review required')
