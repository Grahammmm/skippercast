"""Adapt a reviewed original-grid hard-bottom context to a regional preview.

The output is historical survey habitat only. It has no target point, spot
rating, legal clearance, bottom image, drift, or chartplotter export.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from shapely.geometry import shape


def build(source, source_bytes, region, depth_review):
    if (source.get('scope') != 'northern-native-noaa-usgs-hard-bottom-context'
            or source.get('coast_id') != 'northern' or len(source.get('features', [])) < 100
            or region.get('id') != 'humboldt-bay-cape-mendocino'
            or region.get('status') != 'preview'):
        raise ValueError('Reviewed Northern native hard-bottom context and preview region required')
    west, south, east, north = region['fishing_bounds']
    if (depth_review.get('scope') != 'h11975-research-outline-original-depth-distributions'
            or depth_review.get('context_sha256') != hashlib.sha256(source_bytes).hexdigest()
            or depth_review.get('outline_count') != len(source['features'])):
        raise ValueError('Original-cell depth review does not match research outlines')
    depth_rows = {row['id']: row for row in depth_review['outlines']}
    if len(depth_rows) != len(source['features']):
        raise ValueError('Missing or duplicate original-cell depth reviews')
    features = []
    seen = set()
    for item in source['features']:
        p = item['properties']
        if (p['id'] in seen or p.get('survey_id') != 'H11975'
                or p.get('fishing_target') is not False
                or p.get('exportable') is not False
                or p.get('legal_clearance') is not False
                or p.get('depth_qualified_for_target') is not False
                or p.get('depth_range_kind') != 'screened-policy-not-local-depth-range'):
            raise ValueError('A source outline is unreviewed or asserts a fishing target')
        seen.add(p['id'])
        geom = shape(item['geometry'])
        if not geom.is_valid or geom.is_empty:
            raise ValueError('Invalid native-depth research outline')
        x0, y0, x1, y1 = geom.bounds
        if not (west <= x0 <= x1 <= east and south <= y0 <= y1 <= north):
            raise ValueError('Source outline crosses the regional fishing extent')
        point = geom.representative_point()
        metadata = p['usgs_metadata_urls']
        if len(metadata) != 1 or not metadata[0].startswith('https://cmgds.marine.usgs.gov/'):
            raise ValueError('Original USGS source metadata missing')
        if not p['noaa_bag_url'].startswith('https://data.ngdc.noaa.gov/'):
            raise ValueError('Original NOAA depth source missing')
        if p['noaa_bag_sha256'] != depth_review['bag_sha256']:
            raise ValueError('Original depth review names a different BAG')
        row = depth_rows[p['id']]
        depths = row['sampled_original_depth_ft']
        ordered = [depths[k] for k in ('minimum', 'p05', 'median', 'p95', 'maximum')]
        if (row['fishing_target'] is not False or row['exportable'] is not False
                or row['qualified_original_cells'] <= 0
                or row['qualified_original_cell_area_m2'] <= 0
                or not 25 <= ordered[0] <= ordered[1] <= ordered[2] <= ordered[3] <= ordered[4] <= 200):
            raise ValueError('Invalid or overclaimed original-cell depth distribution')
        features.append({'type': 'Feature', 'geometry': item['geometry'], 'properties': {
            'id': p['id'], 'name': f"Cape Mendocino · surveyed hard-bottom context {len(features)+1:03d}",
            'habitat_kind': 'rock', 'species_ids': ['reef'],
            'latitude': round(point.y, 7), 'longitude': round(point.x, 7),
            'bounds': [round(v, 7) for v in geom.bounds],
            'area_km2': round(p['approx_display_area_m2']/1_000_000, 5),
            'source_id': 'usgs-offshore-cape-mendocino-noaa-h11975',
            'source_url': metadata[0],
            'source_links': [{'title': 'Original NOAA depth grid', 'url': p['noaa_bag_url']},
                             {'title': 'NOAA survey report', 'url': p['survey_report_url']}],
            'source_date': '2008–2009', 'publication_date': '2023',
            'native_source_codes': ['USGS seafloor-character class 3'],
            'native_resolution_m': None, 'survey_cell_m': p['display_cell_m'],
            'vertical_datum': 'NOAA original BAG depth below MLLW',
            'depth_screened': True, 'depth_qualified': False,
            'depth_screen_limit_ft': p['depth_screen_ft'][1],
            'depth_note': 'Original eligible 2008–2009 cells sampled inside this inset display outline; the measured distribution does not clear every point, a route or the current chart.',
            'sampled_original_depth_ft': depths,
            'qualified_original_cells': row['qualified_original_cells'],
            'qualified_original_cell_area_m2': row['qualified_original_cell_area_m2'],
            'view_relief_m': p['sampled_relief_5_95_m'],
            'limitations': 'Historical 2008–2009 bottom. Display edges are deliberately inset and do not trace exact rock boundaries. Relief is sampled from a 5 m display raster, not a boulder-size estimate. Current chart, route, MPA and date/method rules remain unverified for fishing.',
            'evidence_kind': 'original-grid-and-usgs-class-historical-context',
            'catch_evidence': False, 'charter_evidence': False, 'quality_grade': None,
            'fishing_target': False, 'fishing_export': False, 'bottom_view': False,
        }})
    return {'type': 'FeatureCollection', 'schema_version': 1,
            'region_id': region['id'], 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'source_context_sha256': hashlib.sha256(source_bytes).hexdigest(),
            'depth_review_scope': depth_review['scope'],
            'depth_reviewed_at': depth_review['reviewed_at'],
            'transformation_version': 'native-hard-context-to-preview-v2',
            'features': features,
            'summary': {'historical_research_outlines': len(features), 'fishing_targets': 0},
            'source': {'attribution': 'NOAA original H11975 MLLW BAG and USGS Offshore Cape Mendocino seafloor character',
                       'limitations': 'Survey habitat context only. These polygons have no current legal, route, chart or fish-presence clearance.'}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path('dist/data/cape-mendocino-native-hard-context.geojson'))
    p.add_argument('--region', type=Path, default=Path('regions/humboldt-bay-cape-mendocino/region.json'))
    p.add_argument('--depth-review', type=Path, default=Path('dist/data/h11975-research-outline-original-depths.json'))
    p.add_argument('--output', type=Path, default=Path('dist/regions/humboldt-bay-cape-mendocino/survey-habitat.geojson'))
    a = p.parse_args()
    raw = a.source.read_bytes()
    result = build(json.loads(raw), raw, json.loads(a.region.read_text()), json.loads(a.depth_review.read_text()))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    print(result['summary'])


if __name__ == '__main__':
    main()
