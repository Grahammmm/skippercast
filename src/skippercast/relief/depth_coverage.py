"""Area by depth band and survey support on an aligned water lattice."""

import argparse
import json
import os
from pathlib import Path
import sys

import numpy as np

from skippercast.relief import receipts

# Fixed NAVD88 elevations in metres (positive up).
_ELEVATION_66FT = -20.1168
_ELEVATION_300FT = -91.44
# The finite nodata value written by relief.normalize for Float32 survey grids.
_SURVEY_NODATA = -np.finfo(np.float32).max


def _depth_bands(elevation):
    return (
        (elevation >= _ELEVATION_66FT) & (elevation <= 0),
        (elevation >= _ELEVATION_300FT) & (elevation < _ELEVATION_66FT),
    )


def _valid_elevation(elevation):
    return np.isfinite(elevation) & (elevation != _SURVEY_NODATA)


def depth_coverage(elevation, support, water, *, cell_area_m2, coarse=None) -> dict:
    """Summarize survey coverage in m² from same-shape arrays and one cell area.

    66 ft belongs to the shallow band; 300 ft belongs to the deeper band.
    Land and depths beyond 300 ft are omitted from both band areas. Missing
    survey elevations use only the coarse grid to assign a band; missing coarse
    elevations (nonfinite or no grid) go in ``unknown-band``. ``deepest_m`` is a
    positive-down depth from the survey alone, including water deeper than 300 ft.
    """
    elevation, support, water = np.asarray(elevation), np.asarray(support), np.asarray(water, dtype=bool)
    coarse = None if coarse is None else np.asarray(coarse)
    if (support.shape != elevation.shape or water.shape != elevation.shape
            or (coarse is not None and coarse.shape != elevation.shape)):
        raise ValueError('elevation, support, water and coarse must share one lattice')

    valid = _valid_elevation(elevation)
    surveyed = water & valid & (elevation <= 0)
    measured = surveyed & (support == 3)
    estimated = surveyed & (support != 3)
    unsurveyed = water & ~valid
    survey_bands = _depth_bands(elevation)
    if coarse is None:
        coarse_bands = (False, False)
        unknown = unsurveyed
    else:
        coarse_bands = _depth_bands(coarse)
        unknown = unsurveyed & ~np.isfinite(coarse)

    area = float(cell_area_m2)
    bands = {
        name: {
            'measured_m2': np.count_nonzero(survey_band & measured) * area,
            'estimated_m2': np.count_nonzero(survey_band & estimated) * area,
            'unsurveyed_m2': np.count_nonzero(coarse_band & unsurveyed) * area,
        }
        for name, survey_band, coarse_band in zip(('0-66ft', '66-300ft'), survey_bands, coarse_bands)
    }
    bands['unknown-band'] = {
        'measured_m2': 0.0,
        'estimated_m2': 0.0,
        'unsurveyed_m2': np.count_nonzero(unknown) * area,
    }
    return {
        'bands': bands,
        'deepest_m': -float(elevation[surveyed].min()) if surveyed.any() else None,
        'reaches_300ft': bool(np.any(surveyed & (elevation <= _ELEVATION_300FT))),
    }


def _depth_shortfall(elevation, water, coarse, area, result):
    """Use coarse depths to locate the gap, not as evidence of surveyed depth."""
    if result['reaches_300ft'] or coarse is None:
        return None

    start = result['deepest_m'] or 0.0
    mosaic_valid = _valid_elevation(elevation)
    coarse_water = _valid_elevation(coarse) & (coarse <= 0)
    if np.any(water & ~mosaic_valid & ~coarse_water):
        return None

    assessed = water & coarse_water & (coarse < -start)
    if np.any(assessed & mosaic_valid):
        return None

    # Compare in raster precision, as for the bands. The cell at the target
    # counts in both subsets, but only once in the assessed area.
    in_interval = np.count_nonzero(assessed & (coarse >= _ELEVATION_300FT)) * area
    at_or_beyond = np.count_nonzero(assessed & (coarse <= _ELEVATION_300FT)) * area
    if in_interval <= 0 or at_or_beyond <= 0:
        return None

    assessed_area = np.count_nonzero(assessed) * area
    return dict(status='unsurveyed', from_depth_m=start, to_depth_m=-_ELEVATION_300FT,
                assessed_m2=assessed_area, unsurveyed_m2=assessed_area,
                in_interval_m2=in_interval, at_or_beyond_target_m2=at_or_beyond)


def _water_geometries(region):
    # The zone output is depth-limited. Use the original water polygon pinned
    # as a zone *input*, including where neither elevation grid has coverage.
    zone = receipts.read_receipt(region.receipt_path('zone', 'public'))
    if zone is None or receipts.validate_receipt(zone, region.id, 'zone', 'public'):
        raise receipts.ReceiptError('no valid public zone receipt naming the region water')
    rows = [row for row in zone.get('inputs', []) if row['role'] == 'water']
    if len(rows) != 1:
        raise receipts.ReceiptError('expected one public zone water input')
    water = rows[0]
    data = region.resolve(water['path']).read_bytes()
    if receipts.sha256_bytes(data) != water['sha256']:
        raise receipts.ReceiptError('public zone water input changed')
    doc = json.loads(data)
    if doc['type'] != 'FeatureCollection':
        raise ValueError('expected a WGS84 water FeatureCollection')
    return [feature['geometry'] for feature in doc['features']]


def _read_report(region, mosaic, coarse_path):
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.vrt import WarpedVRT
    from rasterio.warp import transform_geom

    folder = 'mosaic/public'
    elevation_path = f'{folder}/elevation.tif'
    support_path = f'{folder}/support_class.tif'
    outputs = {row['path'] for row in mosaic['outputs']}
    if elevation_path not in outputs:
        raise receipts.ReceiptError('mosaic.public does not attest elevation.tif')
    geometries = _water_geometries(region)
    coarse = coarse_sha256 = None
    # Do not load external masks or georeferencing sidecars that weren't hashed.
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_PAM_ENABLED='NO', PROJ_NETWORK='OFF'):
        with rasterio.open(region.resolve(elevation_path), driver='GTiff') as grid:
            if grid.crs != rasterio.crs.CRS.from_epsg(3310) or grid.count != 1:
                raise ValueError('expected a single-band EPSG:3310 mosaic elevation grid')
            lattice = dict(crs=grid.crs, transform=grid.transform, width=grid.width, height=grid.height)
            elevation = grid.read(1, masked=True).astype('float32').filled(np.nan)
        water = geometry_mask(
            [transform_geom('EPSG:4326', lattice['crs'], geom) for geom in geometries],
            out_shape=elevation.shape, transform=lattice['transform'], invert=True,
        )
        # The producer omits support classes when no source provides them.
        # Counts are not classes, and an unreceipted leftover is not evidence.
        support = np.broadcast_to(0, elevation.shape)
        if support_path in outputs:
            with rasterio.open(region.resolve(support_path), driver='GTiff') as grid:
                if any(getattr(grid, k) != v for k, v in lattice.items()) or grid.count != 1:
                    raise ValueError('mosaic support must share the elevation lattice')
                support = grid.read(1, masked=True).filled(0)
        if coarse_path is not None:
            coarse_sha256 = receipts.sha256_file(coarse_path)
            with rasterio.open(coarse_path, driver='GTiff') as grid:
                if grid.crs is None or grid.count != 1:
                    raise ValueError('expected a georeferenced single-band coarse elevation grid')
                # Nearest cell: don't interpolate a depth band across a coarse
                # grid edge or invent a depth in a gap.
                with WarpedVRT(grid, **lattice, dtype='float32', nodata=np.nan) as aligned:
                    coarse = aligned.read(1, masked=True).filled(np.nan)
    t = lattice['transform']
    area = abs(t.a * t.e - t.b * t.d)
    result = depth_coverage(elevation, support, water, cell_area_m2=area, coarse=coarse)
    result['depth_shortfall'] = _depth_shortfall(elevation, water, coarse, area, result)
    return dict(result, region=region.id, mosaic_generation=mosaic['generation'], coarse_sha256=coarse_sha256)


def main(argv=None):
    """Write the standalone depth-coverage report; never run a release stage."""
    parser = argparse.ArgumentParser(prog='region.py depth-coverage', description=main.__doc__)
    parser.add_argument('--region', required=True, help='region whose public zone receipt names the water polygon')
    out = os.environ.get('SC_RELIEF_OUT') or None
    parser.add_argument('--out', default=out, required=out is None)
    parser.add_argument('--coarse', type=Path, help='optional local coarse elevation GeoTIFF in metres')
    args = parser.parse_args(argv)
    try:
        region = receipts.Region(args.out, args.region)
        verdict = receipts.check(region, 'mosaic', 'public')
        if not verdict.done:
            raise receipts.ReceiptError(f'mosaic.public not done ({verdict.state}: {verdict.reason})')
        report = _read_report(region, verdict.receipt, args.coarse)
        receipts.write_json_atomic(region.dir / 'coverage' / 'depth-coverage.json', report)
    except (receipts.ReceiptError, OSError, ValueError, KeyError) as exc:
        print(f'depth-coverage: {exc}', file=sys.stderr)
        return 1
    return 0
