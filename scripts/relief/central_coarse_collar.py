#!/usr/bin/env python3
"""Report missing estimated-grid input on a supplied Central coarse-grid window.

The collar is the outermost row or column of the supplied raster window,
including its corners, not the shoreline or the boundary of the wet mask.
Supply an aligned single-band GeoTIFF mask: 1 means wet and 0 means dry.
This diagnostic makes no claim about survey coverage.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio as rio
from rasterio.errors import RasterioError


def measure(coarse_path: Path, wet_mask_path: Path) -> dict:
    """Count and measure missing wet cells in two disjoint grid partitions."""
    with (
        rio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_PAM_ENABLED='NO', PROJ_NETWORK='OFF'),
        rio.open(coarse_path.resolve(strict=True), driver='GTiff', GEOREF_SOURCES='INTERNAL') as coarse,
        rio.open(wet_mask_path.resolve(strict=True), driver='GTiff', GEOREF_SOURCES='INTERNAL') as wet_mask,
    ):
        if coarse.count != 1 or wet_mask.count != 1:
            raise ValueError('expected single-band coarse grid and wet mask')
        if (wet_mask.shape, wet_mask.crs, wet_mask.transform) != (coarse.shape, coarse.crs, coarse.transform):
            raise ValueError('wet mask must share the coarse grid shape, CRS and transform')
        transform = coarse.transform
        if (coarse.crs != rio.crs.CRS.from_epsg(3310) or not np.isfinite(transform[:6]).all()
                or transform.a <= 0 or transform.e >= 0 or transform.b != 0 or transform.d != 0):
            raise ValueError('expected a north-up EPSG:3310 coarse grid')
        cell_area_m2 = transform.a * -transform.e
        mask = wet_mask.read(1, masked=True)
        if np.ma.getmaskarray(mask).any() or not np.isin(mask.data, (0, 1)).all():
            raise ValueError('wet mask must contain only valid 0 (dry) and 1 (wet) cells')
        samples = coarse.read(1, masked=True)
        nodata = coarse.nodatavals[0]

    invalid = np.ma.getmaskarray(samples) | ~np.isfinite(samples.data)
    # An explicit GDAL validity mask can override the band's nodata mask.
    if nodata is not None and np.isfinite(nodata):
        invalid |= samples.data == nodata
    missing = (mask.data == 1) & invalid
    interior = int(np.count_nonzero(missing[1:-1, 1:-1]))
    collar = int(np.count_nonzero(missing)) - interior
    return {
        'kind': 'missing_estimated_grid_input',
        'outer_collar': {'cells': collar, 'area_m2': collar * cell_area_m2},
        'interior': {'cells': interior, 'area_m2': interior * cell_area_m2},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coarse', type=Path, required=True, help='local coarse GeoTIFF window')
    parser.add_argument('--wet-mask', type=Path, required=True, help='local aligned binary wet-mask GeoTIFF')
    args = parser.parse_args(argv)
    try:
        report = measure(args.coarse, args.wet_mask)
    except (OSError, ValueError, RasterioError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
