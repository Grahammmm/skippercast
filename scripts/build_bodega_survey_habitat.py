"""Publish only terrain-reviewed Bodega–Point Reyes original hard-bottom context.

The result is a survey-habitat layer, never a fishing target, score, drift or
chartplotter waypoint. A selected ENC danger screen is not navigation clearance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from shapely.geometry import shape


def build(source, raw, terrain, region):
    if (source.get('scope') != 'sf-native-noaa-usgs-hard-bottom-context'
            or terrain.get('scope') != 'bodega-original-native-hard-terrain-research-queue'
            or terrain.get('region_id') != region.get('id')
            or region.get('id') != 'bodega-point-reyes'
            or terrain.get('source_context_sha256') != hashlib.sha256(raw).hexdigest()
            or terrain.get('status') != 'research-ranking-only'
            or region.get('status') != 'preview'):
        raise ValueError('Bodega original-cell source and review do not match')
    rows = terrain['rows']
    if len(rows) != terrain['reviewed_outlines'] or len({r['context_id'] for r in rows}) != len(rows):
        raise ValueError('Bodega terrain review is incomplete or duplicated')
    selected = {r['context_id']: r for r in rows if r['status'] == 'terrain-reviewed'
                and r['near_selected_charted_danger'] is False}
    west, south, east, north = region['fishing_bounds']
    output = []
    for feature in source['features']:
        p = feature['properties']
        row = selected.get(p['id'])
        if row is None:
            continue
        geom = shape(feature['geometry'])
        x0, y0, x1, y1 = geom.bounds
        if (not geom.is_valid or geom.is_empty or
                not (west <= x0 <= x1 <= east and south <= y0 <= y1 <= north) or
                p['fishing_target'] is not False or p['exportable'] is not False or
                p['legal_clearance'] is not False or p['depth_qualified_for_target'] is not False or
                row['survey_id'] != p['survey_id'] or row['original_bag_sha256'] != p['noaa_bag_sha256'] or
                row['qualified_native_cells'] <= 0 or row['terrain']['habitat_grade'] != 'C'):
            raise ValueError('Bodega research outline has an unsupported claim or bounds')
        point = geom.representative_point()
        output.append({'type': 'Feature', 'geometry': feature['geometry'], 'properties': {
            'id': p['id'], 'name': f'Point Reyes–Bodega · surveyed hard-bottom context {len(output)+1:02d}',
            'habitat_kind': 'rock', 'species_ids': ['reef'],
            'latitude': round(point.y, 7), 'longitude': round(point.x, 7),
            'bounds': [round(v, 7) for v in geom.bounds],
            'area_km2': round(p['approx_display_area_m2'] / 1_000_000, 5),
            'source_id': f'noaa-{p["survey_id"].lower()}-usgs-hard-class',
            'source_url': p['usgs_metadata_urls'][0],
            'source_links': [{'title': 'Original NOAA depth grid', 'url': p['noaa_bag_url']},
                             {'title': 'NOAA survey report', 'url': p['survey_report_url']}],
            'source_date': p['survey_dates'][0][:4],
            'survey_cell_m': max(p['native_resolution_m']),
            'vertical_datum': 'NOAA original BAG depth below MLLW',
            'depth_screened': True, 'depth_qualified': False,
            'depth_note': 'Historical original cells passed the 25–200 ft planning screen. A component-wide depth range cannot establish the depth of each point in this display outline.',
            'view_relief_m': row['terrain']['relief_90_percent_m'],
            'qualified_original_cells': row['qualified_native_cells'],
            'limitations': 'Historical original-grid hard-bottom research. The terrain grade is uncalibrated to fish or catch, so this outline has no fishing rank. Display edges are inset; selected chart-danger proximity was checked, but the current chart, route, harbor, exact legal access and fish presence are not cleared.',
            'evidence_kind': 'original-grid-and-usgs-class-historical-context',
            'catch_evidence': False, 'charter_evidence': False, 'quality_grade': None,
            'fishing_target': False, 'fishing_export': False, 'bottom_view': False,
        }})
    if len(output) != len(selected) or len(output) != 17:
        raise ValueError('Bodega screened research outline count changed')
    return {'type': 'FeatureCollection', 'schema_version': 1,
            'region_id': region['id'], 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'source_context_sha256': terrain['source_context_sha256'],
            'terrain_reviewed_at': terrain['enc_screen_audited_at'],
            'transformation_version': 'bodega-native-hard-to-preview-v1',
            'features': output,
            'summary': {'historical_research_outlines': len(output), 'fishing_targets': 0},
            'source': {'attribution': 'NOAA original MLLW BAG and USGS seafloor-character class',
                       'limitations': 'Historical research context only; no current catch, chart-route or legal clearance.'}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path('dist/data/sf-native-hard-context.geojson'))
    p.add_argument('--terrain', type=Path, default=Path('dist/data/bodega-native-hard-terrain-review.json'))
    p.add_argument('--region', type=Path, default=Path('regions/bodega-point-reyes/region.json'))
    p.add_argument('--output', type=Path, default=Path('dist/regions/bodega-point-reyes/survey-habitat.geojson'))
    a = p.parse_args()
    raw = a.source.read_bytes()
    result = build(json.loads(raw), raw, json.loads(a.terrain.read_text()), json.loads(a.region.read_text()))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    print(result['summary'])


if __name__ == '__main__':
    main()
