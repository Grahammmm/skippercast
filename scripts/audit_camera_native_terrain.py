"""Measure original BAG terrain near reviewed historical camera windows.

Values are grouped by transect without positions. They describe measured
seabed shape in dated data, not a mapped rock polygon or fishing target.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from math import atan, degrees, hypot
from pathlib import Path

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.windows import Window

from scripts.audit_regular_bag_camera import reviewed_archive
from scripts.audit_usgs_video_observations import open_original_zip
from skippercast.platform.bottom_targets import cells_qualified


def fit_terrain(elevation: np.ndarray, uncertainty: np.ndarray, dx: np.ndarray,
                dy: np.ndarray, within: np.ndarray, *, resolution_m: float) -> dict:
    qualified = cells_qualified(elevation, uncertainty, resolution_m) & within
    support = int(np.count_nonzero(qualified))
    available = int(np.count_nonzero(within))
    if available < 100 or support / available < 0.9:
        raise ValueError('Original 25 m depth/uncertainty neighborhood is incomplete')
    terrain = elevation[qualified].astype('float64')
    design = np.column_stack((dx[qualified], dy[qualified], np.ones(support)))
    coefficients, _, rank, _ = np.linalg.lstsq(design, terrain, rcond=None)
    if rank != 3:
        raise ValueError('Original terrain plane cannot be fitted')
    residual = terrain - design @ coefficients
    return {
        'qualified_native_cells': support,
        'qualified_fraction': round(support / available, 4),
        'local_depth_m_mllw_range': [round(float(-terrain.max()), 2),
                                     round(float(-terrain.min()), 2)],
        'raw_p95_p05_relief_m': round(float(np.percentile(terrain, 95) -
                                            np.percentile(terrain, 5)), 3),
        'detrended_p95_p05_relief_m': round(float(np.percentile(residual, 95) -
                                                  np.percentile(residual, 5)), 3),
        'fitted_plane_slope_degrees': round(degrees(atan(hypot(*coefficients[:2]))), 2),
    }


def sample(raster, lon: float, lat: float, projector: Transformer, *, radius_m=25) -> dict:
    x, y = projector.transform(lon, lat)
    row, col = raster.index(x, y)
    pad = int(np.ceil(radius_m / min(raster.res))) + 1
    if row < pad or col < pad or row + pad >= raster.height or col + pad >= raster.width:
        raise ValueError('Camera window touches original BAG edge')
    window = Window(col - pad, row - pad, 2 * pad + 1, 2 * pad + 1)
    elevation = raster.read(1, window=window)
    uncertainty = raster.read(2, window=window)
    offsets = np.arange(-pad, pad + 1)
    dx = np.broadcast_to(offsets[None, :] * raster.res[0], elevation.shape)
    dy = np.broadcast_to(offsets[:, None] * raster.res[1], elevation.shape)
    within = dx * dx + dy * dy <= radius_m * radius_m
    return fit_terrain(elevation, uncertainty, dx, dy, within,
                       resolution_m=max(raster.res))


def audit(pair: dict, bag_audit: dict, bag_cache: Path, camera_cache: Path,
          *, source_review: str | None = None) -> dict:
    if not pair.get('survey_hold') or not pair.get('transects') or not pair.get('survey_id'):
        raise ValueError('Exact held original-camera review is required')
    bag_record, bag_path = reviewed_archive(bag_audit, pair['survey_id'], bag_cache,
                                             bag_url=pair['bag_url'])
    if bag_record['file_sha256'] != pair['bag_sha256']:
        raise ValueError('Original BAG identity differs from camera review')
    archive = camera_cache / (pair['cruise'] + '_video_observations.zip')
    raw = archive.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pair['camera_archive_sha256']:
        raise ValueError('Original camera archive changed')
    reader = open_original_zip(raw)
    rows = []
    with rasterio.open(bag_path) as raster:
        if (raster.count != 2 or min(raster.res) <= 0 or max(raster.res) > 4
                or abs(raster.res[0] - raster.res[1]) > 1e-6):
            raise ValueError('Expected original fine regular depth and uncertainty bands')
        projector = Transformer.from_crs('EPSG:4326', raster.crs, always_xy=True)
        for transect in pair['transects']:
            metrics = []
            for index in transect['camera_record_indices']:
                original = reader.record(index).as_dict()
                if str(original.get('MAJOR_GEO') or '').lower() not in {'rock', 'boulder', 'cobble'}:
                    raise ValueError('Original camera bottom class changed')
                lon, lat = reader.shape(index).points[0]
                metrics.append(sample(raster, lon, lat, projector))
            if len(metrics) != transect['window_count']:
                raise ValueError('Camera count changed')
            rows.append({
                'date': transect['date'], 'line': transect['line'],
                'historical_camera_windows': len(metrics),
                'camera_bottom_classes': transect['bottom_classes'],
                'historical_rockfish_visual_windows': transect['rockfish_positive_windows'],
                'measured_depth_m_mllw_range': [
                    min(x['local_depth_m_mllw_range'][0] for x in metrics),
                    max(x['local_depth_m_mllw_range'][1] for x in metrics)],
                'native_cell_support_min': min(x['qualified_native_cells'] for x in metrics),
                'native_cell_fraction_min': min(x['qualified_fraction'] for x in metrics),
                'raw_p95_p05_relief_m_range': [
                    min(x['raw_p95_p05_relief_m'] for x in metrics),
                    max(x['raw_p95_p05_relief_m'] for x in metrics)],
                'detrended_p95_p05_relief_m_range': [
                    min(x['detrended_p95_p05_relief_m'] for x in metrics),
                    max(x['detrended_p95_p05_relief_m'] for x in metrics)],
                'fitted_plane_slope_degrees_range': [
                    min(x['fitted_plane_slope_degrees'] for x in metrics),
                    max(x['fitted_plane_slope_degrees'] for x in metrics)],
            })
    return {
        'schema_version': 1,
        'scope': 'held-original-camera-native-terrain-research',
        'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'survey_id': pair['survey_id'],
        'bag_url': pair['bag_url'], 'bag_sha256': pair['bag_sha256'],
        'camera_archive_url': pair['camera_archive_url'],
        'camera_archive_sha256': pair['camera_archive_sha256'],
        'source_camera_review': source_review,
        'native_cell_m': list(raster.res),
        'method': 'Each historical camera point: fit a plane to qualified original native MLLW elevation cells in a 25 m circle, then report 5th–95th percentile relief before and after detrending. Aggregate by transect, never by a claimed reef boundary.',
        'transects': rows,
        'fishing_target': False, 'exportable': False,
        'limitations': [
            'Camera position accuracy varies on the order of 10 m; overlapping windows on a transect are correlated.',
            'Depth qualification is based on the supplied product uncertainty and a 2 m planning margin; it is not navigation clearance.',
            'Detrended relief is physical morphology, not direct substrate, fish abundance, bottom image or a calibrated bite score.',
            'Exact rock extent, historical survey gaps, HCell/ENC hazards, federal and CDFW closures, route, access and rules remain separate promotion gates.',
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pairs', required=True, type=Path)
    p.add_argument('--survey-id', required=True)
    p.add_argument('--bag-url', required=True)
    p.add_argument('--source-review', help='Optional public coordinate-free review reference')
    p.add_argument('--audit', type=Path, default=Path('var/noaa-native-audit-100mb-refined.json'))
    p.add_argument('--bag-cache', type=Path, default=Path('var/noaa-native-cache'))
    p.add_argument('--camera-cache', type=Path, default=Path('var/usgs-video-cache'))
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    packet = json.loads(a.pairs.read_text())
    matching = [row for row in packet['pair_reviews']
                if row['survey_id'] == a.survey_id and row['bag_url'] == a.bag_url]
    if len(matching) != 1:
        raise ValueError('Expected one exact original BAG/camera pair')
    result = audit(matching[0], json.loads(a.audit.read_text()), a.bag_cache, a.camera_cache,
                   source_review=a.source_review)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = a.output.with_suffix(a.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(a.output)
    print(json.dumps({'transects': len(result['transects']),
                      'windows': sum(row['historical_camera_windows'] for row in result['transects']),
                      'fishing_target': result['fishing_target']}))


if __name__ == '__main__':
    main()
