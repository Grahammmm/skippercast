"""Synthetic GeoTIFF helpers. Every raster here is invented; nothing is real survey data."""
import importlib.util
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine

REPO = Path(__file__).resolve().parents[1]
UTM10 = 'EPSG:32610'


def write_tif(path, array, *, transform=None, crs=UTM10, nodata=None, scale=None, offset=None,
              units=None, tags=None, dtype=None):
    array = np.asarray(array)
    if array.ndim == 2:
        array = array[None]
    transform = transform or Affine(2, 0, 500000, 0, -2, 4000000)
    profile = dict(driver='GTiff', height=array.shape[1], width=array.shape[2], count=array.shape[0],
                   dtype=dtype or str(array.dtype), crs=crs, transform=transform, nodata=nodata)
    with rasterio.open(path, 'w', **profile) as dst:
        dst.write(array.astype(profile['dtype']))
        if scale is not None:
            dst.scales = (scale,) * array.shape[0]
        if offset is not None:
            dst.offsets = (offset,) * array.shape[0]
        if units is not None:
            dst.units = (units,) * array.shape[0]
        if tags:
            dst.update_tags(**tags)
    return Path(path)


def load_script(name):
    """Import scripts/<name>.py without running main()."""
    import sys
    sys.path.insert(0, str(REPO / 'src'))
    spec = importlib.util.spec_from_file_location(name, REPO / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
