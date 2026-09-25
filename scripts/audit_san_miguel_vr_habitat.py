"""Intersect original H13084 VR cells with original USGS San Miguel rock polygons."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import transform_bounds
from pyproj import Transformer
from pyproj import CRS
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree

from scripts.audit_san_miguel_original_habitat import read_usgs
from scripts.audit_san_miguel_naval_zone import danger_polygon
from scripts.screen_vr_native_depth import fine_grid_rows
from scripts.screen_vr_original_hard import exclusions
from skippercast.platform.bottom_targets import bag_metadata, cells_qualified, sha256, vr_transform


def review(manifest, usgs_cache, bag_cache, mpas, federal, hazards, report_cache, enc,
           naval_manifest, naval_receipt):
    source = manifest['usgs']
    noaa = manifest['noaa_variable']
    groups, usgs = read_usgs(usgs_cache / 'smighab.tgz', source)
    url = noaa['bag_url']
    if url != 'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H12001-H14000/H13084/BAG/H13084_MB_VR_MLLW.bag':
        raise ValueError('Unreviewed original variable-resolution BAG')
    path = bag_cache / ('H13084-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.bag')
    if path.stat().st_size != noaa['bag_bytes'] or sha256(path) != noaa['bag_sha256']:
        raise ValueError('Original NOAA VR BAG changed')
    totals = {'fine_supergrids_in_usgs_bbox': 0, 'measured_cells_in_bbox_grids': 0,
              'depth_uncertainty_eligible_cells_in_bbox_grids': 0,
              'hard_eligible_cells': 0, 'mixed_eligible_cells': 0,
              'fine_supergrids_with_hard_eligible_cells': 0,
              'hard_cells_after_exclusions': 0, 'mixed_cells_after_exclusions': 0,
              'hard_cells_after_enc_buffer': 0, 'mixed_cells_after_enc_buffer': 0,
              'hard_cells_after_naval_hold': 0, 'mixed_cells_after_naval_hold': 0}
    with rasterio.open(path) as bag, h5py.File(path, 'r') as handle:
        root = handle['BAG_root']
        metadata = bag_metadata(root['metadata'][:].tobytes().decode().rstrip('\0'), 'H13084')
        if metadata['metadata_sha256'] != noaa['metadata_sha256'] or metadata['vertical_datum'] != 'MLLW':
            raise ValueError('NOAA VR metadata or MLLW identity changed')
        if 'MLLW' not in bag.crs.to_wkt():
            raise ValueError('NOAA VR raster datum changed')
        to_native = Transformer.from_crs('EPSG:4269', bag.crs, always_xy=True).transform
        horizontal = CRS.from_user_input(bag.crs).sub_crs_list[0]
        if (enc.get('scope_id') != 'san-miguel-h13084-usgs-habitat'
                or enc.get('status') != 'charted-danger-screen-only'
                or len(enc.get('query_receipts', [])) != 18
                or len(enc.get('features', [])) < 100):
            raise ValueError('San Miguel ENC danger source is incomplete')
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(enc['checked_at'])).total_seconds()
        if not 0 <= age <= 36 * 3600:
            raise ValueError('San Miguel ENC danger source is stale')
        naval_age = (datetime.now(timezone.utc) - datetime.fromisoformat(naval_receipt['checked_at'])).total_seconds()
        if (not 0 <= naval_age <= 36 * 3600
                or naval_receipt.get('id') != naval_manifest['id']
                or naval_receipt.get('source_content_sha256') != naval_manifest['reviewed_content_sha256']
                or naval_receipt.get('operational_status_checked') is not False):
            raise ValueError('San Miguel naval danger-zone source is stale or changed')
        excluded, hazard_review = exclusions(
            {'survey_id': 'H13084', 'source_report_url': noaa['source_report_url']},
            horizontal, usgs['bbox'], mpas, federal, hazards, report_cache)
        to_chart = Transformer.from_crs('EPSG:4326', horizontal, always_xy=True).transform
        chart_danger = unary_union([transform(to_chart, shape(item['geometry']))
                                    for item in enc['features']]).buffer(100)
        naval_hold = transform(to_chart, danger_polygon(naval_manifest)).buffer(100)
        native_groups = {key: [transform(to_native, geometry) for geometry in groups[key]]
                         for key in ('h', 'm')}
        trees = {key: STRtree(native_groups[key]) for key in ('h', 'm')}
        bounds = transform_bounds('EPSG:4269', bag.crs, *usgs['bbox'], densify_pts=21)
        metadata_grid = root['varres_metadata'][:]
        refinement = root['varres_refinements']
        indices = fine_grid_rows(metadata_grid)
        if len(indices) != 9458:
            raise ValueError('Original H13084 fine-supergrid count changed')
        for row, col in indices:
            item = metadata_grid[row, col]
            nx, ny = int(item['dimensions_x']), int(item['dimensions_y'])
            dx, dy = float(item['resolution_x']), float(item['resolution_y'])
            if not (0 < nx <= 128 and 0 < ny <= 128):
                raise ValueError('Unexpected NOAA VR refinement dimensions')
            affine = vr_transform(bag.bounds.left, bag.bounds.bottom, *bag.res,
                                  int(row), int(col), item)
            west, south = affine.c, affine.f - ny * dy
            east, north = affine.c + nx * dx, affine.f
            if east < bounds[0] or west > bounds[2] or north < bounds[1] or south > bounds[3]:
                continue
            totals['fine_supergrids_in_usgs_bbox'] += 1
            offset = int(item['index'])
            if offset < 0 or offset + nx * ny > refinement.shape[1]:
                raise ValueError('NOAA refinement index outside file')
            values = refinement[0, offset:offset + nx * ny]
            depth = values['depth'].reshape(ny, nx)[::-1]
            uncertainty = values['depth_uncrt'].reshape(ny, nx)[::-1]
            measured = (np.isfinite(depth) & (depth < 0) & (depth > -3000)
                        & np.isfinite(uncertainty) & (uncertainty > 0) & (uncertainty < 100))
            eligible = cells_qualified(depth, uncertainty, max(dx, dy), limit_ft=200) & measured
            totals['measured_cells_in_bbox_grids'] += int(measured.sum())
            totals['depth_uncertainty_eligible_cells_in_bbox_grids'] += int(eligible.sum())
            if not eligible.any():
                continue
            cell = box(west, south, east, north)
            for code, label in (('h', 'hard'), ('m', 'mixed')):
                selected = [native_groups[code][int(i)] for i in trees[code].query(cell, predicate='intersects')]
                if not selected:
                    continue
                mask = rasterize(((mapping(geometry), 1) for geometry in selected),
                                 out_shape=(ny, nx), transform=affine, dtype='uint8').astype(bool)
                count = int(np.count_nonzero(mask & eligible))
                totals[f'{label}_eligible_cells'] += count
                retained = mask & eligible
                if count and excluded is not None and excluded.intersects(cell):
                    local = excluded.intersection(cell.buffer(max(dx, dy)))
                    blocked = rasterize([(mapping(local), 1)], out_shape=(ny, nx),
                                        transform=affine, dtype='uint8').astype(bool)
                    retained &= ~blocked
                totals[f'{label}_cells_after_exclusions'] += int(retained.sum())
                if retained.any() and chart_danger.intersects(cell):
                    local = chart_danger.intersection(cell.buffer(max(dx, dy)))
                    chart_blocked = rasterize([(mapping(local), 1)], out_shape=(ny, nx),
                                              transform=affine, dtype='uint8').astype(bool)
                    retained &= ~chart_blocked
                totals[f'{label}_cells_after_enc_buffer'] += int(retained.sum())
                if retained.any() and naval_hold.intersects(cell):
                    local = naval_hold.intersection(cell.buffer(max(dx, dy)))
                    naval_blocked = rasterize([(mapping(local), 1)], out_shape=(ny, nx),
                                              transform=affine, dtype='uint8').astype(bool)
                    retained &= ~naval_blocked
                totals[f'{label}_cells_after_naval_hold'] += int(retained.sum())
                if code == 'h':
                    totals['fine_supergrids_with_hard_eligible_cells'] += count > 0
    return {'schema_version': 1,
            'scope': 'san-miguel-original-usgs-habitat-noaa-vr-source-review',
            'reviewed_at': datetime.now(timezone.utc).isoformat(),
            'usgs_archive_url': source['archive_url'], 'usgs_archive_sha256': source['archive_sha256'],
            'usgs_original': usgs, 'usgs_source_year': source['source_year'],
            'noaa_survey_id': 'H13084', 'noaa_bag_url': url,
            'noaa_bag_sha256': noaa['bag_sha256'], 'noaa_metadata_sha256': noaa['metadata_sha256'],
            'noaa_survey_dates': [noaa['survey_start'], noaa['survey_end']],
            'noaa_source_report_url': noaa['source_report_url'],
            'noaa_source_report_sha256': hazard_review['report_sha256'],
            'historical_hazards_screened': len(hazard_review['hazards']),
            'cdfw_mpa_retrieved_at': mpas['sources']['mpas']['data_retrieved_at'],
            'noaa_federal_areas_retrieved_at': federal['retrieved_at'],
            'enc_danger_checked_at': enc['checked_at'],
            'enc_danger_features': len(enc['features']),
            'naval_danger_zone_source_url': naval_manifest['source_url'],
            'naval_danger_zone_source_sha256': naval_receipt['source_content_sha256'],
            'naval_danger_zone_checked_at': naval_receipt['checked_at'],
            'naval_operational_status_checked': False,
            'source_position_accuracy_m_order': source['reported_horizontal_accuracy_m_order'],
            'counts': totals, 'fishing_target': False, 'exportable': False,
            'limitations': [
                'Historical USGS habitat interpretations have approximately 10 m positional accuracy; no boulder size or present fish presence follows.',
                'Current complete CDFW MPA and NOAA federal GEA geometry plus pinned historical report hazards have 100 m screening buffers; these do not certify exact legal boundaries or chart clearance.',
                'Fresh NOAA ENC Direct danger features from 18 bounded queries have a 100 m research buffer; this is not chart completeness or navigation clearance.',
                'The full 33 CFR 334.1140 San Miguel naval danger zone has a 100 m conservative research hold. It is not a permanent no-fishing closure: scheduled firing/drop status requires a current Local Notice to Mariners or radio confirmation.',
                'Routes, protected-species, island-access and species-method restrictions remain unreviewed for exact positions.',
                'No fishing coordinates, drift lines or export geometry are published from this source review.'
            ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path('catalog/usgs-ofr0385-san-miguel.json'))
    parser.add_argument('--usgs-cache', type=Path, default=Path('var/usgs-ofr0385'))
    parser.add_argument('--bag-cache', type=Path, default=Path('var/noaa-native-cache'))
    parser.add_argument('--mpas', type=Path, default=Path('var/san-miguel-review-fresh/coastal/latest.json'))
    parser.add_argument('--federal', type=Path, default=Path('var/san-miguel-review-fresh/federal.json'))
    parser.add_argument('--hazards', type=Path, default=Path('catalog/noaa-survey-hazards.json'))
    parser.add_argument('--report-cache', type=Path, default=Path('var/noaa-native-cache'))
    parser.add_argument('--enc', type=Path, default=Path('var/review/enc-hazards-san-miguel-h13084.geojson'))
    parser.add_argument('--naval-manifest', type=Path, default=Path('catalog/san-miguel-naval-danger-zone.json'))
    parser.add_argument('--naval-receipt', type=Path, default=Path('var/review/san-miguel-naval-zone.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    result = review(manifest, args.usgs_cache, args.bag_cache,
                    json.loads(args.mpas.read_text()), json.loads(args.federal.read_text()),
                    json.loads(args.hazards.read_text()), args.report_cache,
                    json.loads(args.enc.read_text()),
                    json.loads(args.naval_manifest.read_text()),
                    json.loads(args.naval_receipt.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    if args.verify:
        expected = json.loads(args.verify.read_text())
        if stable(expected) != stable(result):
            raise SystemExit('Original San Miguel VR source review changed')
    print(json.dumps(result['counts']))


def stable(value):
    dynamic = {'reviewed_at', 'cdfw_mpa_retrieved_at', 'noaa_federal_areas_retrieved_at',
               'enc_danger_checked_at', 'naval_danger_zone_checked_at'}
    return {key: row for key, row in value.items() if key not in dynamic}


if __name__ == '__main__':
    main()
