"""Compare original H11876 side-scan image with dated camera substrate labels.

This is a bounded source check, not a rock classifier or fishing-spot builder.
The original image is an uncalibrated 8-bit mosaic with black/no-data pixels.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.windows import Window

from scripts.audit_usgs_video_observations import open_original_zip


URL = ('https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H10001-H12000/'
       'H11876/TIFF/H11876_NGDC_SSS_1m.tif.gz')
SHA256 = 'fea036f596158b4f549ad86b83a8f66068637c24f848b867f3e772b8cf5f09e0'
RASTER_SHA256 = '4a22ac9711ff0e1d22d54934fc7f030a05302707e12cfba5823cd6a189821dc0'
PROJECTION_URL = URL.replace('.tif.gz', '.csproj.gz')
PROJECTION_SHA256 = 'aadcfbc568306107608b32c03284030d9b7144b4e00fd7a1dff699d4beba5fe7'
WORLD_FILE_URL = URL.replace('.tif.gz', '.tfw.gz')
WORLD_FILE_SHA256 = 'c4ecb6c1858af6f981f9bdb2ec4d136248f6bfbdbfe60f3ca0bf6de2f568bbdf'
LINES = {'119', '137'}
HARD = {'rock', 'boulder', 'cobble'}
SOFT = {'sand', 'mud'}


def summarize_patch(ds, x, y, radius_pixels=16):
    row, col = ds.index(x, y)
    if not (radius_pixels <= row < ds.height-radius_pixels and
            radius_pixels <= col < ds.width-radius_pixels):
        return None
    patch = ds.read(1, window=Window(col-radius_pixels, row-radius_pixels,
                                     2*radius_pixels+1, 2*radius_pixels+1))
    valid = patch[patch > 0]
    return {'valid_fraction': round(valid.size/patch.size, 3),
            'gray_median': round(float(np.median(valid)), 1) if valid.size else None,
            'gray_std': round(float(np.std(valid)), 1) if valid.size else None}


def audit(raster, gzip_original, projection_gzip, world_gzip, camera_zip, pair):
    if hashlib.sha256(gzip_original.read_bytes()).hexdigest() != SHA256:
        raise ValueError('Original NOAA side-scan file changed')
    if hashlib.sha256(raster.read_bytes()).hexdigest() != RASTER_SHA256:
        raise ValueError('Decompressed NOAA side-scan raster changed')
    if hashlib.sha256(projection_gzip.read_bytes()).hexdigest() != PROJECTION_SHA256:
        raise ValueError('Original NOAA projection sidecar changed')
    if hashlib.sha256(world_gzip.read_bytes()).hexdigest() != WORLD_FILE_SHA256:
        raise ValueError('Original NOAA world file changed')
    if not gzip.decompress(projection_gzip.read_bytes()).startswith(b'EPSG:26911,'):
        raise ValueError('Unexpected NOAA side-scan projection')
    if not gzip.decompress(world_gzip.read_bytes()).startswith(b'1.500000\r\n'):
        raise ValueError('Unexpected NOAA side-scan world-file scale')
    if hashlib.sha256(camera_zip.read_bytes()).hexdigest() != pair['camera_archive_sha256']:
        raise ValueError('Original USGS camera archive changed')
    if pair['survey_id'] != 'H11876' or len(pair['transects']) != 2:
        raise ValueError('Expected the reviewed two-transect H11876 pair')
    reader = open_original_zip(camera_zip.read_bytes())
    rows = []
    with rasterio.open(raster) as ds:
        if (ds.width, ds.height, ds.count, ds.dtypes[0]) != (4860, 11958, 1, 'uint8'):
            raise ValueError('Original side-scan raster dimensions or type changed')
        if abs(ds.transform.a - 1.5) > 1e-6 or abs(ds.transform.e + 1.5) > 1e-6:
            raise ValueError('Original side-scan pixel size changed')
        projection = Transformer.from_crs('EPSG:4326', 'EPSG:26911', always_xy=True)
        for index, record in enumerate(reader.iterRecords()):
            if str(record['LINE']) not in LINES:
                continue
            kind = str(record['MAJOR_GEO']).strip().lower()
            if kind not in HARD | SOFT:
                continue
            lon, lat = reader.shape(index).points[0]
            patch = summarize_patch(ds, *projection.transform(lon, lat))
            if patch:
                rows.append({'line': str(record['LINE']), 'label': kind, **patch})
        per_line = []
        for line in sorted(LINES):
            selected = [row for row in rows if row['line'] == line]
            by_class = {}
            for name, classes in [('camera_hard', HARD), ('camera_soft', SOFT)]:
                labeled = [r for r in selected if r['label'] in classes and r['valid_fraction'] >= .8]
                by_class[name] = {'patches': len(labeled),
                    'median_gray_value': round(float(np.median([r['gray_median'] for r in labeled])), 1) if labeled else None,
                    'median_local_gray_std': round(float(np.median([r['gray_std'] for r in labeled])), 1) if labeled else None}
            per_line.append({'line': line, 'camera_class_counts': dict(Counter(r['label'] for r in selected)),
                'patch_count': len(selected),
                'patches_with_at_least_80_percent_image_pixels': sum(r['valid_fraction'] >= .8 for r in selected),
                'exploratory_image_contrast': by_class})
        reviewed = []
        for transect in pair['transects']:
            for index in transect['camera_record_indices']:
                lon, lat = reader.shape(index).points[0]
                patch = summarize_patch(ds, *projection.transform(lon, lat))
                reviewed.append(patch is not None and patch['valid_fraction'] >= .8)
        return {'schema_version': 1, 'scope': 'h11876-original-sidescan-camera-context',
                'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'source_url': URL, 'source_sha256': SHA256,
                'raster_sha256': RASTER_SHA256,
                'projection_sidecar_url': PROJECTION_URL,
                'projection_sidecar_sha256': PROJECTION_SHA256,
                'world_file_url': WORLD_FILE_URL,
                'world_file_sha256': WORLD_FILE_SHA256,
                'camera_archive_url': pair['camera_archive_url'],
                'camera_archive_sha256': pair['camera_archive_sha256'],
                'survey_id': 'H11876', 'raster_pixels': [ds.width, ds.height],
                'actual_raster_pixel_size_m': [abs(ds.transform.a), abs(ds.transform.e)],
                'catalog_filename_claims_1m': True,
                'projection_verified_from_companion_csproj': 'EPSG:26911',
                'sampling_radius_m': 24, 'reviewed_rocky_windows_with_sidescan_coverage': sum(reviewed),
                'reviewed_rocky_window_count': len(reviewed), 'transects': per_line,
                'fishing_target': False, 'exportable': False,
                'limitations': [
                    'The filename says 1 m, but the inspected GeoTIFF transform and world file say 1.5 m pixels.',
                    'Gray values and local contrast are exploratory, uncalibrated mosaic display values; shadows, incidence and processing prevent classifying rock from brightness or texture alone.',
                    'Camera records are correlated along two 2011 transects, three years after the 2008 sonar survey; this small sample cannot establish a full hard-bottom footprint.',
                    'The source remains outside fishing targets, ratings, drifts, bottom illustrations and exports pending original footprint, current chart, MPA, rules and route review.']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raster', type=Path, default=Path('var/noaa-native-cache/H11876_NGDC_SSS_1m.tif'))
    p.add_argument('--compressed-original', type=Path, default=Path('var/noaa-native-cache/H11876_NGDC_SSS_1m.tif.gz'))
    p.add_argument('--projection-sidecar', type=Path, default=Path('var/noaa-native-cache/H11876_NGDC_SSS_1m.csproj.gz'))
    p.add_argument('--world-file', type=Path, default=Path('var/noaa-native-cache/H11876_NGDC_SSS_1m.tfw.gz'))
    p.add_argument('--camera', type=Path, default=Path('var/usgs-video-cache/c0111sc_video_observations.zip'))
    p.add_argument('--pairs', type=Path, default=Path('dist/data/noaa-statewide-regular-camera-review.json'))
    p.add_argument('--output', type=Path, default=Path('dist/data/h11876-original-sidescan-review.json'))
    args = p.parse_args()
    pairs = json.loads(args.pairs.read_text())['pair_reviews']
    pair, = [row for row in pairs if row['survey_id'] == 'H11876' and
             row['bag_url'].endswith('H11876_MB_2m_MLLW_2of5.bag')]
    result = audit(args.raster, args.compressed_original, args.projection_sidecar,
                   args.world_file, args.camera, pair)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    print(json.dumps({'transects': result['transects'], 'fishing_target': False}))


if __name__ == '__main__':
    main()
