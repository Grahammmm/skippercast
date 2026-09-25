"""Rank Bodega original-grid hard-bottom research outlines by measured relief.

The output is a review queue, not fishing positions. It reuses the published
uncalibrated terrain rubric but cannot clear legal access, routes or catches.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from shapely.geometry import box, shape
from shapely.ops import transform

from skippercast.platform.bottom_targets import cells_qualified, terrain_metrics
from skippercast.platform.contracts import REPO, atomic_json


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def audit(root=REPO):
    root = Path(root)
    region = json.loads((root / 'regions/bodega-point-reyes/region.json').read_text())
    if region['status'] != 'preview' or region['id'] != 'bodega-point-reyes':
        raise ValueError('Expected Bodega research-only preview')
    context_path = root / 'dist/data/sf-native-hard-context.geojson'
    context_raw = context_path.read_bytes()
    context = json.loads(context_raw)
    enc = json.loads((root / 'dist/data/bodega-native-enc-scope-review.json').read_text())
    if (enc['source_context_sha256'] != hashlib.sha256(context_raw).hexdigest()
            or enc['research_outlines_in_region'] != 74
            or enc['outlined_footprints_covered_by_all_scopes'] != 74
            or enc['status'] != 'research-screen-only'):
        raise ValueError('Original context and bounded chart receipt differ')
    enc_checked = datetime.fromisoformat(enc['audited_at'].replace('Z', '+00:00'))
    if not 0 <= (datetime.now(timezone.utc) - enc_checked).total_seconds() <= 36 * 3600:
        raise ValueError('Bodega chart-danger research receipt is stale')
    fishing = box(*region['fishing_bounds'])
    candidates = []
    for feature in context['features']:
        footprint = shape(feature['geometry']).intersection(fishing)
        if footprint.is_empty:
            continue
        props = feature['properties']
        if (props.get('fishing_target') is not False or props.get('exportable') is not False
                or props.get('native_resolution_m') != [2.0, 2.0]):
            raise ValueError('Unexpected promoted or non-2 m research outline')
        candidates.append((props, footprint))
    if len(candidates) != 74:
        raise ValueError('Original Bodega outline count changed')
    expected = {props['noaa_bag_sha256'] for props, _ in candidates}
    cache = {}
    for path in sorted((root / 'var/noaa-native-cache').glob('H117*.bag')):
        value = digest(path)
        if value in expected:
            if value in cache:
                raise ValueError('Duplicate original BAG digest in cache')
            cache[value] = path
    if set(cache) != expected:
        raise ValueError('One or more exact original BAG grids are unavailable')
    metrics = []
    for props, geographic_footprint in candidates:
        path = cache[props['noaa_bag_sha256']]
        with rasterio.open(path) as ds:
            crs = CRS.from_wkt(ds.crs.to_wkt())
            parts = crs.sub_crs_list
            if (ds.driver != 'BAG' or ds.count != 2 or ds.res != (2.0, 2.0)
                    or len(parts) != 2 or parts[1].to_epsg() != 5866
                    or 'utm zone 10' not in parts[0].name.lower()):
                raise ValueError('Original BAG geometry or datum changed')
            footprint = transform(Transformer.from_crs('EPSG:4326', parts[0],
                                                        always_xy=True).transform,
                                  geographic_footprint)
            windows = from_bounds(*footprint.bounds, transform=ds.transform)
            window = windows.round_offsets().round_lengths()
            depth = ds.read(1, window=window)
            uncertainty = ds.read(2, window=window)
            affine = ds.window_transform(window)
            inside = geometry_mask([footprint], out_shape=depth.shape,
                                   transform=affine, invert=True)
            qualified = cells_qualified(depth, uncertainty, 2) & inside
            area_m2 = footprint.area
            if area_m2 < 2500:
                status = 'held-small-display'
                result = None
                depth_stats = None
            elif qualified.sum() < 20 or not qualified.all(where=inside):
                # A displayed patch must remain wholly supported by qualified
                # original measured cells; otherwise it stays a held research lead.
                status = 'held-native-cell-gap'
                result = None
                depth_stats = None
            else:
                yy, xx = np.where(qualified)
                east = affine.c + (xx + .5) * affine.a
                north = affine.f + (yy + .5) * affine.e
                result = terrain_metrics(east, north, depth[qualified],
                                         np.full(len(east), 2.0),
                                         hard_area_m2=area_m2)
                sampled_ft = -depth[qualified].astype('float64') / .3048
                if not np.isfinite(sampled_ft).all() or np.any((sampled_ft < 25) | (sampled_ft > 200)):
                    raise ValueError('Original Bodega depth escaped the 25–200 ft cell screen')
                depth_stats = {'minimum': round(float(sampled_ft.min()), 1),
                               'p05': round(float(np.percentile(sampled_ft, 5)), 1),
                               'median': round(float(np.median(sampled_ft)), 1),
                               'p95': round(float(np.percentile(sampled_ft, 95)), 1),
                               'maximum': round(float(sampled_ft.max()), 1)}
                status = 'terrain-reviewed'
            metrics.append({'context_id': props['id'], 'survey_id': props['survey_id'],
                            'original_bag_sha256': props['noaa_bag_sha256'],
                            'display_area_m2': round(area_m2),
                            'native_cells_inside_display': int(inside.sum()),
                            'qualified_native_cells': int(qualified.sum()),
                            'status': status, 'terrain': result,
                            'sampled_original_depth_ft': depth_stats})
    danger_ids = {row['context_id'] for row in enc['outlines_near_selected_charted_dangers']}
    if not danger_ids <= {row['context_id'] for row in metrics}:
        raise ValueError('Chart receipt references a missing research outline')
    for row in metrics:
        row['near_selected_charted_danger'] = row['context_id'] in danger_ids
    metrics.sort(key=lambda row: (row['terrain']['habitat_score'] if row['terrain'] else -1,
                                  row['display_area_m2']), reverse=True)
    return {'schema_version': 1, 'scope': 'bodega-original-native-hard-terrain-research-queue',
            'region_id': region['id'], 'source_context_sha256': hashlib.sha256(context_raw).hexdigest(),
            'enc_screen_audited_at': enc['audited_at'], 'reviewed_outlines': len(metrics),
            'grades': {grade: sum(row['terrain'] is not None and
                                  row['terrain']['habitat_grade'] == grade for row in metrics)
                       for grade in ('A', 'B', 'C')},
            'unranked_outlines': sum(row['terrain'] is None for row in metrics),
            'hold_reasons': {reason: sum(row['status'] == reason for row in metrics)
                             for reason in ('held-small-display', 'held-native-cell-gap')},
            'charted_danger_proximity_holds': len(danger_ids),
            'rows': metrics, 'status': 'research-ranking-only',
            'limitations': ('The score compares measured terrain relief, complexity and mapped hard area; '
                            'it is not calibrated to catches. A historical USGS hard class and NOAA BAG '
                            'do not establish current fish, chart route, harbor access, legal permission '
                            'or exact boulder dimensions. Selected ENC danger layers do not clear a '
                            'navigation route. No row is a fishing target, recommendation or export.')}


if __name__ == '__main__':
    result = audit()
    atomic_json(REPO / 'dist/data/bodega-native-hard-terrain-review.json', result)
    print(json.dumps({'reviewed': result['reviewed_outlines'], 'grades': result['grades'],
                      'holds': result['hold_reasons']}))
