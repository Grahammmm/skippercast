"""Publish reviewed NOAA/USGS original-cell intersections as context, never targets.

The original survey screen lives in qualify_regular_bag_hard.py. This stage
checks its receipts, removes survey overlap, re-screens current MPAs and GEAs,
and makes a lightweight browse polygon. It cannot establish legal clearance.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from pyproj import Transformer
from shapely import set_precision, make_valid
from shapely.geometry import mapping, shape, GeometryCollection
from shapely.ops import transform, unary_union

from scripts.build_usgs_statewide_context import mpa_union


TO_METERS = Transformer.from_crs('EPSG:4326', 'EPSG:32610', always_xy=True).transform
TO_WGS84 = Transformer.from_crs('EPSG:32610', 'EPSG:4326', always_xy=True).transform
EXPECTED = {'H11732', 'H11733', 'H11734', 'H11735', 'H11738', 'H12109', 'H12111'}


def polygon_only(geometry):
    if geometry.is_empty:
        return GeometryCollection()
    if geometry.geom_type in {'Polygon', 'MultiPolygon'}:
        return geometry
    pieces = [part for part in getattr(geometry, 'geoms', []) if part.geom_type in {'Polygon', 'MultiPolygon'}]
    return unary_union(pieces) if pieces else GeometryCollection()


def federal_union(data):
    if data.get('scope') != 'noaa-west-coast-groundfish-conservation-areas' or data.get('status') != 'ok' or len(data.get('features', [])) < 25:
        raise ValueError('Complete NOAA federal-area snapshot required')
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(data['retrieved_at'].replace('Z', '+00:00'))).total_seconds()
    if not 0 <= age <= 36 * 3600:
        raise ValueError('NOAA federal-area snapshot is stale')
    geas = [f for f in data['features'] if f.get('properties', {}).get('area_type') == 'GEA']
    if len(geas) < 10 or not any('Cordell_Bank_20260623' in f['properties'].get('source_layer', '') for f in geas):
        raise ValueError('NOAA GEA set is incomplete')
    return unary_union([shape(f['geometry']) for f in geas])


def compile_context(reviews, summary, mpa_snapshot, federal_snapshot, *, expected=EXPECTED,
                    coast_id='san-francisco', source_review='data/noaa-native-hard-review-summary.json'):
    if summary.get('scope') != 'native-noaa-usgs-review-summary':
        raise ValueError('Expected original-cell review summary')
    rows = {r['survey_id']: r for r in summary['surveys']}
    if set(rows) != set(expected) or set(reviews) != set(expected):
        raise ValueError('The bounded survey review is incomplete')
    mpa = mpa_union(mpa_snapshot)
    federal = federal_union(federal_snapshot)
    exclusion = set_precision(transform(TO_METERS, unary_union([mpa, federal])).buffer(100), 0.1)
    accepted = None
    output = []
    for ident in sorted(expected):
        review, row = reviews[ident], rows[ident]
        if (review.get('scope') != 'native-noaa-usgs-hard-bottom-review' or review.get('survey_id') != ident
                or len(review.get('features', [])) != row['counts']['retained_components']
                or review['noaa_bag_sha256'] != row['noaa_bag_sha256']
                or review['survey_report_sha256'] != row['survey_report_sha256']
                or review['maximum_planning_depth_ft'] != 200
                or review['usgs_sources'] != row['usgs_sources']):
            raise ValueError('Original review does not match pinned source receipts: ' + ident)
        for item in review['features']:
            props = item['properties']
            if (props.get('fishing_target') is not False or props.get('exportable') is not False
                    or props.get('legal_clearance') is not False or props.get('fish_confirmed') is not False
                    or props['depth_ft_range'][1] > 200):
                raise ValueError('Review geometry has an unsupported target or depth claim')
            original = set_precision(transform(TO_METERS, shape(item['geometry'])), 0.1)
            if not original.is_valid or original.is_empty:
                raise ValueError('Invalid original review geometry')
            # Simplification can expand an edge: intersect it with the original,
            # then remove present-day closures and previously published overlap.
            simplified = set_precision(original.simplify(8, preserve_topology=True), 0.1)
            polygon = polygon_only(simplified.intersection(original, grid_size=0.1))
            if polygon.is_empty:
                continue
            polygon = polygon_only(polygon.difference(exclusion, grid_size=0.1))
            if accepted is not None:
                polygon = polygon_only(polygon.difference(accepted, grid_size=0.1))
            if polygon.is_empty or polygon.area < 2500:
                continue
            accepted = polygon if accepted is None else accepted.union(polygon)
            # The GIS review perimeter is jagged at native 1–2 m cells. Make
            # a smaller display-only interior, never expanding into a closure
            # or claiming the chart shows a precise reef edge.
            display = polygon.simplify(15, preserve_topology=True)
            for _ in range(6):
                display = polygon_only(display.buffer(-7.5))
                if display.is_empty or display.covered_by(polygon):
                    break
            if display.is_empty or not display.covered_by(polygon):
                continue
            wgs = polygon_only(make_valid(transform(TO_WGS84, display)))
            if wgs.is_empty or not wgs.is_valid:
                raise ValueError('Display geometry failed WGS84 validity check')
            output.append({'type': 'Feature', 'geometry': mapping(wgs), 'properties': {
                'id': f"native-hard-{ident}-{props['component']}", 'survey_id': ident,
                'depth_ft_range': props['depth_ft_range'],
                'max_product_uncertainty_m': props['max_product_uncertainty_m'],
                'approx_display_area_m2': round(display.area),
                'native_resolution_m': review['native_resolution_m'],
                'survey_dates': review['survey_dates'],
                'noaa_bag_url': review['noaa_bag_url'],
                'noaa_bag_sha256': review['noaa_bag_sha256'],
                'survey_report_url': review['survey_report_url'],
                'usgs_metadata_urls': [s['metadata_url'] for s in review['usgs_sources']],
                'fishing_target': False, 'exportable': False, 'legal_clearance': False,
                'fish_confirmed': False, 'depth_qualified_for_target': False,
            }})
    return {'type': 'FeatureCollection', 'schema_version': 1,
            'scope': f'{coast_id}-native-noaa-usgs-hard-bottom-context',
            'compiled_at': datetime.now(timezone.utc).isoformat(),
            'coast_id': coast_id, 'source_review': source_review,
            'mpa_screened_at': mpa_snapshot['sources']['mpas']['data_retrieved_at'],
            'federal_screened_at': federal_snapshot['retrieved_at'],
            'method': 'Historical original NOAA BAG 1–2 m MLLW depth and supplied uncertainty intersected with original USGS hard class; survey hazards, complete current MPAs and GEAs screened with 100 m planning clearance. Display geometry simplified inward and overlap removed.',
            'limitations': ['Historical seabed context only; current fish presence, exact legal access, YRCA applicability, charts, hazards and route remain unverified.',
                            'No fishing targets, score contribution, drifts or chartplotter exports.',
                            'The MPA and GEA screen is a compilation-time snapshot; recheck current boundaries and rules.'],
            'features': output}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reviews', type=Path, default=Path('var'))
    p.add_argument('--summary', type=Path, default=Path('dist/data/noaa-native-hard-review-summary.json'))
    p.add_argument('--mpas', type=Path, default=Path('var/live-coastal-latest.json'))
    p.add_argument('--federal', type=Path, default=Path('dist/data/noaa-federal-areas.json'))
    p.add_argument('--output', type=Path, default=Path('dist/data/sf-native-hard-context.geojson'))
    p.add_argument('--survey-id', action='append', dest='survey_ids')
    p.add_argument('--coast-id', default='san-francisco')
    p.add_argument('--source-review', default='data/noaa-native-hard-review-summary.json')
    args = p.parse_args()
    expected = set(args.survey_ids) if args.survey_ids else EXPECTED
    reviews = {ident: json.loads((args.reviews / f'review-{ident.lower()}-native-hard.geojson').read_text()) for ident in expected}
    result = compile_context(reviews, json.loads(args.summary.read_text()), json.loads(args.mpas.read_text()),
                             json.loads(args.federal.read_text()), expected=expected,
                             coast_id=args.coast_id, source_review=args.source_review)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + '.tmp')
    tmp.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    tmp.replace(args.output)
    print(f"{len(result['features'])} context polygons, 0 fishing targets")


if __name__ == '__main__':
    main()
