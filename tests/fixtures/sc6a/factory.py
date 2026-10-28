"""Tiny self-contained synthetic metre grids; no acquired data or binary fixtures."""
from pathlib import Path


def make_grid(root, dtype, *, fully_masked=False, nonbinary=False,
              scale=1.0, offset=0.0, nonfinite=False, unsigned_samples=False):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    unsigned_samples = unsigned_samples or dtype == 'uint16'
    values = np.arange(25).reshape(5, 5).astype(dtype)
    if not unsigned_samples:
        values -= 12
    values[0, 0] = 0  # a genuine supported zero, never a substitute for missing data
    if unsigned_samples:
        values[0, 1] = 65534
    nodata = 65535 if unsigned_samples else -32768
    values[2, 2] = nodata
    if fully_masked:
        values[:] = nodata
    if nonfinite:
        values[1, 1], values[1, 2], values[1, 3] = np.nan, np.inf, -np.inf
    support = np.ones((5, 5), dtype='uint8')
    support[0, 4] = 0
    support[4, 0] = 255  # explicit masked support, in addition to a supported-data void
    if nonbinary:
        support[0, 1] = 2
    rgb = (np.arange(75).reshape(3, 5, 5) + 1).astype('uint8')
    profile = dict(driver='GTiff', height=5, width=5, crs='EPSG:26910',
                   transform=from_origin(729183, 3819093, 2, 2))
    terrain, mask, image = (root / name for name in ('terrain.tif', 'support.tif', 'imagery.tif'))
    with rasterio.open(terrain, 'w', count=1, dtype=dtype, nodata=nodata, **profile) as ds:
        ds.write(values, 1)
        ds.set_band_unit(1, 'm')
        ds.scales = (scale,)
        ds.offsets = (offset,)
    with rasterio.open(mask, 'w', count=1, dtype='uint8', nodata=255, **profile) as ds:
        ds.write(support, 1)
    with rasterio.open(image, 'w', count=3, dtype='uint8', **profile) as ds:
        ds.write(rgb)
    valid = (values != nodata) & np.isfinite(values) & (support == 1)
    return dict(paths=(terrain, mask, image), values=values, valid=valid, rgb=rgb,
                transform=profile['transform'])
