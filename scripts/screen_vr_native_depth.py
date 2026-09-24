"""Screen original NOAA variable-resolution BAG cells throughout California.

This is a native-cell depth/uncertainty inventory, not substrate confirmation,
legal clearance, a fishing target, or a navigation product. Supergrids are
assigned to browse sectors by their centers for workload planning only.
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
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skippercast.platform.bottom_targets import (bag_metadata, cells_qualified,
    sha256, source_url_allowed, vr_transform)
from scripts.coastal_review_areas import containing_island, load_island_review_areas


def fine_grid_rows(metadata):
    if metadata.ndim != 2 or not {'index', 'dimensions_x', 'dimensions_y', 'resolution_x',
                                  'resolution_y', 'sw_corner_x', 'sw_corner_y'} <= set(metadata.dtype.names or ()):
        raise ValueError('Unsupported BAG variable-resolution metadata')
    return np.argwhere((metadata['dimensions_x'] > 0) & (metadata['resolution_x'] > 0)
                       & (metadata['resolution_x'] <= 4) & (metadata['resolution_y'] > 0)
                       & (metadata['resolution_y'] <= 4))


def native_counts(refinement, meta):
    nx, ny = int(meta['dimensions_x']), int(meta['dimensions_y'])
    dx, dy = float(meta['resolution_x']), float(meta['resolution_y'])
    if not (0 < nx <= 128 and 0 < ny <= 128 and 0 < dx <= 4 and 0 < dy <= 4):
        raise ValueError('Unsupported native supergrid shape or resolution')
    offset, count = int(meta['index']), nx * ny
    if offset < 0 or offset + count > refinement.shape[1]:
        raise ValueError('BAG supergrid index is outside refinements')
    values = refinement[0, offset:offset+count]
    if values.dtype.names is None or not {'depth', 'depth_uncrt'} <= set(values.dtype.names):
        raise ValueError('BAG refinement lacks depth and product uncertainty')
    depth, uncertainty = values['depth'], values['depth_uncrt']
    measured = (np.isfinite(depth) & (depth < 0) & (depth > -3000)
                & np.isfinite(uncertainty) & (uncertainty > 0) & (uncertainty < 100))
    eligible = cells_qualified(depth, uncertainty, max(dx, dy)) & measured
    return int(np.count_nonzero(measured)), int(np.count_nonzero(eligible))


def containing_sector(lon, lat, sectors):
    matches = [row['id'] for row in sectors if row['bounds'][0] <= lon < row['bounds'][2]
               and row['bounds'][1] <= lat < row['bounds'][3]]
    if len(matches) > 1:
        raise ValueError('Overlapping browse-sector request envelopes')
    return matches[0] if matches else None


def summarize_by_sector(files, sectors):
    rows = {sector['id']: {'sector_id': sector['id'], 'source_files_with_fine_grids': 0,
                          'source_files_with_eligible_cells': 0, 'fine_native_grids': 0,
                          'measured_native_cells': 0, 'depth_uncertainty_eligible_cells': 0}
            for sector in sectors}
    for source in files:
        if source['status'] != 'ok':
            continue
        for sector_id, counts in source['sectors'].items():
            item = rows[sector_id]
            item['source_files_with_fine_grids'] += 1
            item['source_files_with_eligible_cells'] += counts['depth_uncertainty_eligible_cells'] > 0
            for key in ('fine_native_grids', 'measured_native_cells',
                        'depth_uncertainty_eligible_cells'):
                item[key] += counts[key]
    return list(rows.values())


def summarize_by_region(files, regions):
    rows = summarize_by_sector(
        [{**row, 'sectors': row.get('regional_packages', {})} for row in files], regions)
    return [{'region_id': row.pop('sector_id'), **row} for row in rows]


def screen_file(record, sectors, cache, islands=(), regions=()):
    url = record['url']
    if (record.get('status') != 'ok' or
            record.get('metadata_status') != 'mllw-product-uncertainty-reviewed-by-adapter' or
            not source_url_allowed(url) or record.get('refinement_grids_at_most_4m', 0) <= 0):
        raise ValueError('Original fine-resolution MLLW BAG was not audited')
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
            raise ValueError('BAG horizontal CRS mismatch')
        if (raster.res[0] <= 0 or raster.res[1] <= 0 or
                root['elevation'].shape != (raster.height, raster.width) or
                root['varres_metadata'].shape != (raster.height, raster.width)):
            raise ValueError('BAG overview and supergrid indices disagree')
        metadata = root['varres_metadata'][:]
        refinements = root['varres_refinements']
        if (refinements.ndim != 2 or refinements.shape[0] != 1 or
                refinements.shape[1] != record['variable_refinement_records']):
            raise ValueError('Original refinement array changed')
        indices = fine_grid_rows(metadata)
        if len(indices) != record['refinement_grids_at_most_4m']:
            raise ValueError('Fine supergrid count changed from original audit')
        if root['tracking_list'].size or root['varres_tracking_list'].size:
            raise ValueError('Tracked/overridden BAG needs separate review')
        # Verify the coordinate convention against GDAL's independent BAG
        # supergrid reader, including unusual non-square native cells.
        for probe in sorted({0, len(indices)//2, len(indices)-1}):
            row, col = map(int, indices[probe])
            m = metadata[row, col]
            derived = vr_transform(raster.bounds.left, raster.bounds.bottom,
                                   raster.res[0], raster.res[1], row, col, m)
            nx, ny = int(m['dimensions_x']), int(m['dimensions_y'])
            bounds = [derived.c, derived.f-ny*float(m['resolution_y']),
                      derived.c+nx*float(m['resolution_x']), derived.f]
            with rasterio.open(f'BAG:{path}:supergrid:{row}:{col}') as gdal_grid:
                if (gdal_grid.shape != (ny, nx) or
                        not np.allclose(list(gdal_grid.bounds), bounds, rtol=0, atol=.001)):
                    raise ValueError('Native BAG geolocation differs from GDAL supergrid reader')
        to_geo = Transformer.from_crs(horizontal, 'EPSG:4326', always_xy=True)
        counts = {'fine_native_grids': 0, 'measured_native_cells': 0,
                  'depth_uncertainty_eligible_cells': 0, 'outside_sector_grids': 0}
        assigned = {}
        island_assigned = {}
        region_assigned = {}
        for row, col in indices:
            m = metadata[row, col]
            measured, eligible = native_counts(refinements, m)
            nx, ny = int(m['dimensions_x']), int(m['dimensions_y'])
            transform = vr_transform(raster.bounds.left, raster.bounds.bottom,
                                     raster.res[0], raster.res[1], int(row), int(col), m)
            lon, lat = to_geo.transform(transform.c + nx*float(m['resolution_x'])/2,
                                        transform.f - ny*float(m['resolution_y'])/2)
            # Package counts are independent of browse-sector assignment and
            # use each package's actual bounds, not a survey name or overview.
            for region in regions:
                west, south, east, north = region['bounds']
                if west <= lon < east and south <= lat < north:
                    bucket = region_assigned.setdefault(region['id'], {'fine_native_grids': 0,
                        'measured_native_cells': 0, 'depth_uncertainty_eligible_cells': 0})
                    bucket['fine_native_grids'] += 1
                    bucket['measured_native_cells'] += measured
                    bucket['depth_uncertainty_eligible_cells'] += eligible
            island = containing_island(lon, lat, islands)
            sector = None if island else containing_sector(lon, lat, sectors)
            if island:
                bucket = island_assigned.setdefault(island, {'fine_native_grids': 0,
                    'measured_native_cells': 0, 'depth_uncertainty_eligible_cells': 0})
                bucket['fine_native_grids'] += 1
                bucket['measured_native_cells'] += measured
                bucket['depth_uncertainty_eligible_cells'] += eligible
            elif sector is None:
                counts['outside_sector_grids'] += 1
            else:
                bucket = assigned.setdefault(sector, {'fine_native_grids': 0,
                    'measured_native_cells': 0, 'depth_uncertainty_eligible_cells': 0})
                bucket['fine_native_grids'] += 1
                bucket['measured_native_cells'] += measured
                bucket['depth_uncertainty_eligible_cells'] += eligible
            counts['fine_native_grids'] += 1
            counts['measured_native_cells'] += measured
            counts['depth_uncertainty_eligible_cells'] += eligible
        located = (sum(item['fine_native_grids'] for item in assigned.values())
                   + sum(item['fine_native_grids'] for item in island_assigned.values())
                   + counts['outside_sector_grids'])
        if located != counts['fine_native_grids']:
            raise ValueError('Original native grids were lost or double-counted in review areas')
    return {'survey_id': record['survey_id'], 'bag_url': url, 'bag_sha256': record['file_sha256'],
            'metadata_sha256': record['metadata_sha256'], 'source_report_url': record['source_report_url'],
            'survey_dates': [record['survey_start'], record['survey_end']],
            'status': 'ok', 'gdal_geolocation_probes': len({0, len(indices)//2, len(indices)-1}),
            'counts': counts, 'sectors': assigned, 'offshore_islands': island_assigned,
            'regional_packages': region_assigned}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit', type=Path, default=Path('var/noaa-native-audit-100mb-refined.json'))
    p.add_argument('--sectors', type=Path, default=Path('dist/data/coastal-sectors.json'))
    p.add_argument('--cache', type=Path, default=Path('var/noaa-native-cache'))
    p.add_argument('--regions', type=Path, default=Path('regions'))
    p.add_argument('--survey-id', action='append')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    audit = json.loads(a.audit.read_text())
    sectors = json.loads(a.sectors.read_text())['sectors']
    islands = load_island_review_areas()
    regions = [json.loads(path.read_text()) for path in sorted(a.regions.glob('*/region.json'))]
    if audit.get('scope') != 'noaa-original-bag-native-overview-audit' or len(sectors) < 19:
        raise ValueError('Wrong statewide BAG audit or incomplete sector inventory')
    selected = [r for r in audit['files'] if r.get('status') == 'ok'
                and r.get('metadata_status') == 'mllw-product-uncertainty-reviewed-by-adapter'
                and r.get('refinement_grids_at_most_4m', 0) > 0
                and (not a.survey_id or r['survey_id'] in a.survey_id)]
    if a.survey_id and set(a.survey_id) != {r['survey_id'] for r in selected}:
        raise ValueError('Requested survey has no audited fine-resolution BAG')
    rows = []
    for record in selected:
        try:
            result = screen_file(record, sectors, a.cache, islands, regions)
        except (OSError, ValueError, KeyError, TypeError) as error:
            result = {'survey_id': record['survey_id'], 'bag_url': record['url'],
                      'bag_sha256': record['file_sha256'], 'status': 'failed', 'issue': str(error)[:250]}
        rows.append(result)
        print(result['survey_id'], result['status'], result.get('counts', {}), flush=True)
    failed = [r['survey_id'] for r in rows if r['status'] != 'ok']
    output = {'schema_version': 1, 'scope': 'california-original-vr-native-depth-review',
              'screened_at': datetime.now(timezone.utc).isoformat(),
              'audit_collected_at': audit['collected_at'], 'upstream_audit_health': audit['health'],
              'status': 'degraded' if failed else 'ok',
              'failed_survey_ids': failed, 'survey_file_count': len(rows),
              'method': 'Original fine-resolution BAG refinement cells (<=4 m), MLLW and supplied product uncertainty. A grid center is assigned first to an approximate offshore-island review envelope, otherwise to one mainland browse sector; each regional package is counted separately against its actual bounds. Boundary grids may straddle envelopes.',
              'limitations': ['This is a depth/uncertainty workload inventory, not surveyed hard substrate, fish habitat, legal clearance, navigation data, or fishing coordinates.',
                              'Grid-center sector assignment is approximate and does not establish complete water coverage.',
                              'Offshore-island review boxes are approximate organizational envelopes, not shorelines or surveyed footprints.',
                              'Only audited MLLW files in the selected input audit are included; other, failed and unavailable files are gaps.',
                              'Package totals assign whole native supergrids by center. Cells near the package edge may fall outside its bounds; totals are workload counts, not exact within-package cell counts.',
                              'Original descriptive reports, current MPAs/GEAs, hazards, routes and local fishing rules require separate review.'],
              'sectors': summarize_by_sector(rows, sectors),
              'regional_packages': summarize_by_region(rows, regions),
              'offshore_islands': summarize_by_sector(
                  [{**row, 'sectors': row.get('offshore_islands', {})} for row in rows], islands),
              'files': rows}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    temp = a.output.with_suffix(a.output.suffix + '.tmp')
    temp.write_text(json.dumps(output, separators=(',', ':')) + '\n')
    temp.replace(a.output)
    if failed:
        raise SystemExit(f'{len(failed)} original BAG files failed native-cell screening')


if __name__ == '__main__':
    main()
