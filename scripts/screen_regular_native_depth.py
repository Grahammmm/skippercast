"""Count original regular NOAA BAG depth cells by California browse sector.

This is a source-coverage and depth/uncertainty screen, never a fishing spot,
substrate classification, legal clearance, or navigation product. Every valid
native cell is assigned by its transformed center, not by a survey bounding box.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import h5py
import numpy as np
from pyproj import CRS, Transformer
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from skippercast.platform.bottom_targets import bag_metadata, cells_qualified, sha256, source_url_allowed


def regular_audited_rows(audit):
    return [row for row in audit['files'] if row.get('status') == 'ok'
            and row.get('metadata_status') == 'mllw-product-uncertainty-reviewed-by-adapter'
            and row.get('variable_refinement_records') == 0
            and len(row.get('overview_resolution_m', [])) == 2
            and max(row['overview_resolution_m']) <= 4]


def count_sector_cells(lon, lat, measured, eligible, sectors):
    """Assign cell centers once; report valid data outside browse envelopes."""
    if not (lon.shape == lat.shape == measured.shape == eligible.shape):
        raise ValueError('Native coordinate and mask shapes differ')
    assigned = np.zeros(measured.shape, dtype=bool)
    counts = {}
    for sector in sectors:
        west, south, east, north = sector['bounds']
        inside = ((lon >= west) & (lon < east) & (lat >= south) & (lat < north) & measured)
        if np.any(inside & assigned):
            raise ValueError('Browse sector envelopes overlap over original cells')
        assigned |= inside
        valid_count = int(np.count_nonzero(inside))
        eligible_count = int(np.count_nonzero(inside & eligible))
        if valid_count:
            counts[sector['id']] = {'measured_native_cells': valid_count,
                                    'depth_uncertainty_eligible_cells': eligible_count}
    return counts, int(np.count_nonzero(measured & ~assigned))


def screen_file(record, sectors, cache):
    url = record['url']
    if not source_url_allowed(url):
        raise ValueError('Original NOAA BAG URL was not approved')
    path = cache / (record['survey_id'] + '-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.bag')
    if not path.is_file() or path.stat().st_size != record['file_bytes'] or sha256(path) != record['file_sha256']:
        raise ValueError('Original BAG size or digest changed')
    with rasterio.open(path) as raster, h5py.File(path, 'r') as h:
        root = h['BAG_root']
        original = bag_metadata(root['metadata'][:].tobytes().decode().rstrip('\0'), record['survey_id'])
        if original['metadata_sha256'] != record['metadata_sha256']:
            raise ValueError('Original BAG metadata digest changed')
        horizontal = CRS.from_wkt(original['horizontal_wkt'])
        if horizontal.is_bound:
            horizontal = horizontal.source_crs
        raster_crs = CRS.from_user_input(raster.crs)
        if raster_crs.is_compound:
            raster_crs = raster_crs.sub_crs_list[0]
        if raster_crs.is_bound:
            raster_crs = raster_crs.source_crs
        if not horizontal.equals(raster_crs, ignore_axis_order=True):
            raise ValueError('Original BAG horizontal CRS differs from GDAL')
        if (raster.count < 2 or raster.res[0] <= 0 or raster.res[1] <= 0
                or max(raster.res) > 4 or root['elevation'].shape != (raster.height, raster.width)
                or root['uncertainty'].shape != (raster.height, raster.width)
                or ('varres_refinements' in root and root['varres_refinements'].size)):
            raise ValueError('Original BAG is not a supported regular native grid')
        to_geo = Transformer.from_crs(horizontal, 'EPSG:4326', always_xy=True)
        totals = {'overview_finite_elevation_cells': 0, 'measured_native_cells': 0,
                  'depth_uncertainty_eligible_cells': 0,
                  'measured_outside_browse_sectors': 0, 'tracked_soundings': int(root['tracking_list'].size)}
        assigned = {}
        for _, window in raster.block_windows(1):
            depth_masked = raster.read(1, window=window, masked=True)
            depth = depth_masked.data
            uncertainty = raster.read(2, window=window)
            overview_valid = (~np.ma.getmaskarray(depth_masked) & np.isfinite(depth))
            totals['overview_finite_elevation_cells'] += int(np.count_nonzero(overview_valid))
            measured = (overview_valid & (depth < 0) & (depth > -3000)
                        & np.isfinite(uncertainty) & (uncertainty > 0) & (uncertainty < 100))
            if not np.any(measured):
                continue
            eligible = measured & cells_qualified(depth, uncertainty, max(raster.res))
            rows, cols = np.indices(depth.shape)
            cols = cols + int(window.col_off)
            rows = rows + int(window.row_off)
            xy = raster.transform * (cols + .5, rows + .5)
            lon, lat = to_geo.transform(xy[0], xy[1])
            placed, outside = count_sector_cells(lon, lat, measured, eligible, sectors)
            totals['measured_native_cells'] += int(np.count_nonzero(measured))
            totals['depth_uncertainty_eligible_cells'] += int(np.count_nonzero(eligible))
            totals['measured_outside_browse_sectors'] += outside
            for sector_id, values in placed.items():
                bucket = assigned.setdefault(sector_id, {'measured_native_cells': 0,
                    'depth_uncertainty_eligible_cells': 0})
                for key, value in values.items():
                    bucket[key] += value
        if totals['overview_finite_elevation_cells'] != record['overview_valid_cells']:
            raise ValueError('Native valid cell count changed from original audit')
    return {'survey_id': record['survey_id'], 'bag_url': url, 'bag_sha256': record['file_sha256'],
            'metadata_sha256': record['metadata_sha256'], 'source_report_url': record['source_report_url'],
            'survey_dates': [record['survey_start'], record['survey_end']], 'status': 'ok',
            'native_resolution_m': list(raster.res), 'counts': totals, 'sectors': assigned}


def summarize_by_sector(files, sectors):
    rows = {s['id']: {'sector_id': s['id'], 'source_files_with_measured_cells': 0,
                      'source_files_with_eligible_cells': 0, 'measured_native_cells': 0,
                      'depth_uncertainty_eligible_cells': 0} for s in sectors}
    for source in files:
        if source['status'] != 'ok':
            continue
        for sector_id, counts in source['sectors'].items():
            target = rows[sector_id]
            target['source_files_with_measured_cells'] += 1
            target['source_files_with_eligible_cells'] += counts['depth_uncertainty_eligible_cells'] > 0
            for key in ('measured_native_cells', 'depth_uncertainty_eligible_cells'):
                target[key] += counts[key]
    return list(rows.values())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit', type=Path, default=Path('var/noaa-native-audit-100mb-refined.json'))
    p.add_argument('--sectors', type=Path, default=Path('dist/data/coastal-sectors.json'))
    p.add_argument('--cache', type=Path, default=Path('var/noaa-native-cache'))
    p.add_argument('--survey-id', action='append')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    audit = json.loads(a.audit.read_text())
    sectors = json.loads(a.sectors.read_text())['sectors']
    if audit.get('scope') != 'noaa-original-bag-native-overview-audit' or len(sectors) < 19:
        raise ValueError('Wrong statewide BAG audit or incomplete sector inventory')
    selected = [r for r in regular_audited_rows(audit)
                if not a.survey_id or r['survey_id'] in a.survey_id]
    if a.survey_id and set(a.survey_id) != {r['survey_id'] for r in selected}:
        raise ValueError('Requested survey has no audited regular BAG')
    files = []
    for record in selected:
        try:
            result = screen_file(record, sectors, a.cache)
        except (OSError, ValueError, KeyError, TypeError) as error:
            result = {'survey_id': record['survey_id'], 'bag_url': record['url'],
                      'bag_sha256': record['file_sha256'], 'status': 'failed', 'issue': str(error)[:250]}
        files.append(result)
        print(record['survey_id'], result['status'], result.get('counts', {}), flush=True)
    failed = [r['survey_id'] for r in files if r['status'] != 'ok']
    output = {'schema_version': 1, 'scope': 'california-original-regular-native-depth-review',
              'screened_at': datetime.now(timezone.utc).isoformat(),
              'audit_collected_at': audit['collected_at'], 'upstream_audit_health': audit['health'],
              'status': 'degraded' if failed else 'ok', 'failed_survey_ids': failed,
              'survey_file_count': len(files),
              'method': 'Original <=4 m regular BAG depth and uncertainty cells, transformed to WGS84 and assigned by cell center to one browse sector. MLLW/product-uncertainty metadata and original file digest checked.',
              'limitations': ['Depth and uncertainty alone are not hard substrate, fish habitat, legal clearance, safe navigation or fishing coordinates.',
                              'Counts include overlapping historical surveys and cannot be summed as unique seafloor coverage.',
                              'Only audited MLLW files <=100 MB are included; larger, failed and unavailable files are gaps.',
                              'Descriptive reports, MPAs, federal exclusions, hazards, routes and local rules require separate review.'],
              'sectors': summarize_by_sector(files, sectors), 'files': files}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    temp = a.output.with_suffix(a.output.suffix + '.tmp')
    temp.write_text(json.dumps(output, separators=(',', ':')) + '\n')
    temp.replace(a.output)
    if failed:
        raise SystemExit(f'{len(failed)} original regular BAG files failed native-cell screening')


if __name__ == '__main__':
    main()
