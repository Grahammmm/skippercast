#!/usr/bin/env python3
"""Check one local synthetic normalized elevation/support pair, not a region.

Compatibility only describes the grid pairing. It does not qualify or select
any input for a Central run.
"""

import argparse

import rasterio
from rasterio.errors import RasterioIOError

from skippercast.relief import select


def check_pair(elevation, support):
    """Return (status, explanation) without reading pixels or running selection."""
    try:
        paths = (select.local_path(elevation), select.local_path(support))
        if not all(path.is_file() for path in paths):
            return 'unavailable', 'both inputs must be local regular files'
        # A copied GeoTIFF must not inherit georeferencing from its new directory.
        with (
            rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_PAM_ENABLED='NO', PROJ_NETWORK='OFF'),
            rasterio.open(paths[0], driver='GTiff', GEOREF_SOURCES='INTERNAL') as grid,
            rasterio.open(paths[1], driver='GTiff', GEOREF_SOURCES='INTERNAL') as mask,
        ):
            if grid.crs is None or mask.crs is None:
                return 'unavailable', 'both inputs must declare a CRS'
            if grid.count != 1:
                return 'unavailable', 'elevation must be single-band'
            try:
                select.check_support(grid, mask)
            except ValueError as exc:
                differences = [
                    label for field, label in (
                        ('crs', 'CRS'), ('transform', 'affine transform'), ('shape', 'shape')
                    ) if getattr(grid, field) != getattr(mask, field)
                ]
                detail = f"; mismatched {', '.join(differences)}" if differences else ''
                return 'incompatible', f'{exc}{detail}'
            # The transforms match, but a singular lattice has no map-to-pixel inverse.
            if grid.transform.determinant == 0:
                return 'unavailable', 'shared affine transform is singular'
    except (OSError, ValueError, RasterioIOError):
        return 'unavailable', 'could not open both inputs as local GeoTIFFs'
    return 'compatible', 'CRS, affine transform and shape match'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('elevation', help='local synthetic normalized elevation GeoTIFF')
    parser.add_argument('support', help='local synthetic normalized support GeoTIFF')
    args = parser.parse_args(argv)
    status, reason = check_pair(args.elevation, args.support)
    print(f'{status}: {reason}. Compatibility does not qualify or select an input.')
    return {'compatible': 0, 'incompatible': 1, 'unavailable': 2}[status]


if __name__ == '__main__':
    raise SystemExit(main())
