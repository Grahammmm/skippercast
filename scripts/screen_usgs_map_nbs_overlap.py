"""Cross-screen an original USGS map block against measured NOAA MLLW tiles.

Raster value-table labels, not numeric code guesses, identify the original
rugose-rock class. Results are source-quality receipts, never fishing marks.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds

from scripts.audit_nbs_modeling_tile import audit as audit_tile, contributors, qualified_mask, sha256
from scripts.queue_nbs_original_class_tiles import intersecting_scheme_rows
from scripts.qualify_regular_bag_hard import original_character


def source_row(audit, block_id, archive_sha256):
    if audit.get('scope') != 'usgs-state-waters-native-grid-audit' or audit.get('fishing_target') is not False:
        raise ValueError('Original USGS native-grid research audit required')
    rows = [row for row in audit['products'] if row.get('block_id') == block_id
            and row.get('archive_sha256') == archive_sha256
            and row.get('kind') == 'seafloor_character' and row.get('status') == 'ok']
    if len(rows) != 1:
        raise ValueError('Expected exactly one hash-pinned original class grid')
    row = rows[0]
    if row.get('class_table_status') != 'verified' or not row.get('original_class_table'):
        raise ValueError('Original raster value-table meanings are unverified')
    table = row['original_class_table']
    if {str(item['value']): item['count'] for item in table} != row['class_counts']:
        raise ValueError('Original raster value-table counts changed')
    codes = sorted(item['value'] for item in table if item['substrate_class'] == 3)
    if not codes:
        raise ValueError('Original table contains no explicit rugose rock/boulder class')
    return row, codes


def screen(native_audit, metadata, block_id, archive_sha256, scheme, nbs_cache, usgs_cache,
           *, fetch=False, max_tiles=40):
    row, codes = source_row(native_audit, block_id, archive_sha256)
    uri = original_character(row, usgs_cache, metadata)
    results = []
    with rasterio.open(uri) as original:
        if original.count != 1 or not original.crs or max(original.res) > 5.1:
            raise ValueError('Original USGS class raster is not a supported fine grid')
        bounds = transform_bounds(original.crs, 'EPSG:4326', *original.bounds, densify_pts=21)
        tile_rows = intersecting_scheme_rows(scheme, bounds, maximum=max_tiles)
        if not tile_rows:
            raise ValueError('No NOAA Modeling tiles intersect the original raster envelope')
        for lead in tile_rows:
            if not lead['GeoTIFF_Link'] or not lead['RAT_Link']:
                raise ValueError('NOAA tile is missing its original raster or contributor table')
            tile = lead['tile']
            receipt = audit_tile(scheme, tile, nbs_cache, fetch=fetch)
            source_rows = contributors(nbs_cache / f'{tile}.tiff.aux.xml')
            with rasterio.open(nbs_cache / f'{tile}.tiff') as raster:
                elevation, uncertainty, contributor = raster.read()
                qualified = qualified_mask(elevation, uncertainty, contributor, source_rows,
                                           resolution_m=max(raster.res))
                with WarpedVRT(original, crs=raster.crs, transform=raster.transform,
                               width=raster.width, height=raster.height,
                               resampling=Resampling.nearest, nodata=original.nodata) as aligned:
                    cells = aligned.read(1, masked=True)
                hard = ~np.ma.getmaskarray(cells) & np.isin(cells.data, codes)
                overlap = qualified & hard
                ids, counts = np.unique(contributor[overlap], return_counts=True)
            results.append({'tile': tile, 'raster_sha256': receipt['raster_sha256'],
                            'rat_sha256': receipt['rat_sha256'],
                            'qualified_measured_mllw_pixels': int(qualified.sum()),
                            'original_rock_class_pixels_at_tile_centers': int(hard.sum()),
                            'strict_measured_rock_overlap_pixels': int(overlap.sum()),
                            'source_survey_contributors': [
                                {'survey_id': source_rows[int(ident)]['source_survey_id'],
                                 'survey_date_end': source_rows[int(ident)]['survey_date_end'],
                                 'overlap_pixels': int(count)} for ident, count in zip(ids, counts)]})
    return {'schema_version': 1, 'scope': 'usgs-map-original-rock-versus-noaa-measured-mllw',
            'reviewed_at': datetime.now(timezone.utc).isoformat(),
            'block_id': block_id, 'original_archive_sha256': row['archive_sha256'],
            'original_metadata_sha256': row['metadata_sha256'],
            'original_class_table_sha256': row['original_class_table_sha256'],
            'original_rugose_rock_values': codes, 'noaa_scheme_sha256': sha256(scheme),
            'original_raster_envelope_wgs84': [round(value, 7) for value in bounds],
            'tile_count': len(results), 'tiles': results,
            'fishing_target': False, 'exportable': False,
            'limitations': [
                'Original video-supervised substrate classes are historical and correlated with their source sonar; rock-class pixels are not distinct reefs.',
                'NOAA Modeling is a test-and-evaluation product; only measured MLLW contributors with product uncertainty and the configured depth margin pass the screen.',
                'Tiles and source envelopes overlap and contain masked water. Pixel counts are not unique fishable acreage or a catch score.',
                'This screen does not check current MPAs, federal restrictions, chart hazards, routes, access, species rules or fish presence.',
            ]}


def signature(report):
    return {key: value for key, value in report.items() if key != 'reviewed_at'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--block-id', required=True)
    parser.add_argument('--archive-sha256', required=True)
    parser.add_argument('--scheme', type=Path, default=Path('var/nbs-cache/modeling-tile-scheme.gpkg'))
    parser.add_argument('--nbs-cache', type=Path, default=Path('var/nbs-cache'))
    parser.add_argument('--usgs-cache', type=Path, default=Path('var/usgs-native-cache'))
    parser.add_argument('--max-tiles', type=int, default=40)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    result = screen(json.loads(args.audit.read_text()), json.loads(args.metadata.read_text()),
                    args.block_id, args.archive_sha256, args.scheme, args.nbs_cache,
                    args.usgs_cache, fetch=args.fetch, max_tiles=args.max_tiles)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    if args.verify and signature(result) != signature(json.loads(args.verify.read_text())):
        raise SystemExit('Original rock/NOAA measured-depth overlap changed; review before promotion')
    print(json.dumps({'tiles': result['tile_count'],
                      'strict_overlap_pixels': sum(x['strict_measured_rock_overlap_pixels']
                                                   for x in result['tiles']),
                      'fishing_target': False}))


if __name__ == '__main__':
    main()
