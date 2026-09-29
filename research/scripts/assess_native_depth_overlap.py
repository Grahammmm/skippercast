"""Prioritize original NOAA BAG surveys overlapping reviewed substrate context.

This 4 m screening report is a *lead*, not a new fishing target. Only BAGs with
MLLW/product-uncertainty metadata, <=4 m native overview, no variable-resolution
refinements, and matching cached SHA are considered. Actual target promotion
still needs native-cell outlines, terrain review, rules, hazards and QA.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from shapely.geometry import box, mapping, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from skippercast.platform.bottom_targets import cells_qualified

COASTS = ('northern', 'mendocino', 'san-francisco', 'central', 'southern')


def polygons(root, prefix, scope):
    features = []
    for coast in COASTS:
        packet = json.loads((root / f'{prefix}-{coast}.geojson').read_text())
        if packet.get('scope') != scope or packet.get('coast_id') != coast:
            raise ValueError(f'Wrong published {prefix} context shard: {coast}')
        for feature in packet['features']:
            if feature['properties'].get('fishing_target') is not False:
                raise ValueError('An unscreened target entered the overlap report')
            features.append((shape(feature['geometry']), feature['properties']))
    return features


def screen_one(row, cache, source_groups):
    if (row.get('status') != 'ok' or
        row.get('metadata_status') != 'mllw-product-uncertainty-reviewed-by-adapter' or
        max(row.get('overview_resolution_m', [float('inf')])) > 4 or
        row.get('variable_refinement_records') != 0):
        return None
    url = row['url']
    local = cache / (row['survey_id'] + '-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.bag')
    if not local.is_file() or hashlib.sha256(local.read_bytes()).hexdigest() != row['file_sha256']:
        raise ValueError('Original NOAA BAG is missing or its pinned digest changed: ' + row['survey_id'])
    bounds = box(*row['raster_bounds_wgs84'])
    nearby = {}
    for label, (index, geometries, properties) in source_groups.items():
        nearby[label] = [(geometries[int(i)], properties[int(i)]) for i in index.query(bounds)
                         if geometries[int(i)].intersects(bounds)]
    if not any(nearby.values()):
        return None
    with rasterio.open(local) as raster:
        if raster.count < 2 or not raster.crs:
            raise ValueError('Original BAG lacks elevation, uncertainty or CRS')
        width = max(1, round(raster.width * raster.res[0] / 4))
        height = max(1, round(raster.height * raster.res[1] / 4))
        elevation = raster.read(1, out_shape=(height, width), resampling=Resampling.nearest)
        uncertainty = raster.read(2, out_shape=(height, width), resampling=Resampling.nearest)
        eligible = cells_qualified(elevation, uncertainty, 4)
        if not np.any(eligible):
            return None
        affine = raster.transform * raster.transform.scale(raster.width / width, raster.height / height)
        to_grid = Transformer.from_crs(4326, raster.crs, always_xy=True).transform
        overlays = {}
        for label, candidates in nearby.items():
            if not candidates:
                continue
            projected = [mapping(transform(to_grid, geometry)) for geometry, _ in candidates]
            classified = rasterize(((geometry, 1) for geometry in projected),
                                   out_shape=(height, width), transform=affine, dtype='uint8')
            count = int(np.count_nonzero(eligible & (classified == 1)))
            if count:
                overlays[label] = {'qualified_4m_screen_cells': count,
                                   'approx_screen_area_m2': round(count * abs(affine.a * affine.e)),
                                   'intersecting_context_polygons': len(candidates)}
        if not overlays:
            return None
        return {'survey_id': row['survey_id'], 'url': url, 'source_report_url': row.get('source_report_url'),
                'file_sha256': row['file_sha256'], 'survey_start': row['survey_start'],
                'survey_end': row['survey_end'], 'vertical_datum': row['vertical_datum'],
                'uncertainty_type': row['uncertainty_type'],
                'native_overview_resolution_m': row['overview_resolution_m'],
                'screen_resolution_m': [abs(affine.a), abs(affine.e)],
                'valid_overview_cells': row['overview_valid_cells'], 'overlays': overlays}


def build(audit, context_dir, cache):
    if audit.get('scope') != 'noaa-original-bag-native-overview-audit':
        raise ValueError('Wrong NOAA native grid audit')
    source_groups = {}
    for label, prefix, scope in (
        ('usgs_original_class', 'usgs-hard-context', 'generalized-statewide-usgs-hard-bottom-context'),
        ('cdfw_predicted_class', 'cdfw-predicted-hard', 'cdfw-predicted-hard-substrate-context')):
        pairs = polygons(context_dir, prefix, scope)
        geometries = [geometry for geometry, _ in pairs]
        source_groups[label] = (STRtree(geometries), geometries, [props for _, props in pairs])
    rows = []
    for source in audit['files']:
        item = screen_one(source, cache, source_groups)
        if item:
            rows.append(item)
    rows.sort(key=lambda item: (-item['overlays'].get('usgs_original_class', {}).get('qualified_4m_screen_cells', 0),
                                -item['overlays'].get('cdfw_predicted_class', {}).get('qualified_4m_screen_cells', 0),
                                item['survey_id']))
    return {'schema_version': 1, 'scope': 'statewide-native-depth-substrate-overlap-leads',
            'screened_at': datetime.now(timezone.utc).isoformat(),
            'method': 'Original NOAA BAG elevation and product uncertainty, 4 m nearest-neighbor screen, intersected separately with USGS historical hard class and CDFW predicted hard class. 25–200 ft planning band, <=1 m supplied uncertainty and 2 m depth margin. No targets promoted.',
            'limitations': ['4 m screening can miss native detail; rerun at native cells before point placement.',
                            'CDFW hard class is a rugosity prediction, not verified rock.',
                            'Historical survey dates do not confirm present bottom or fish.',
                            'Season, MPAs, other closures, hazards and access need a fresh review.'],
            'input_bag_products': audit['file_count'], 'lead_products': len(rows),
            'usgs_overlap_products': sum('usgs_original_class' in item['overlays'] for item in rows),
            'cdfw_overlap_products': sum('cdfw_predicted_class' in item['overlays'] for item in rows),
            'leads': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, default=Path('var/noaa-native-audit.json'))
    parser.add_argument('--context-dir', type=Path, default=Path('dist/data'))
    parser.add_argument('--cache', type=Path, default=Path('var/noaa-native-cache'))
    parser.add_argument('--output', type=Path, default=Path('var/native-depth-overlap-leads.json'))
    args = parser.parse_args()
    result = build(json.loads(args.audit.read_text()), args.context_dir, args.cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    print(f"{result['lead_products']} BAG overlap leads; {result['usgs_overlap_products']} original-class, {result['cdfw_overlap_products']} predicted-class")
    for item in result['leads']:
        print(item['survey_id'], {k: v['qualified_4m_screen_cells'] for k, v in item['overlays'].items()})


if __name__ == '__main__':
    main()
