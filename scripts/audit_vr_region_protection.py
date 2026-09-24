"""Check original fine BAG supergrid footprints against fresh complete CDFW MPAs.

This is an exclusion/source review, not navigation, fishing permission or a target.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import h5py
from pyproj import Transformer
import rasterio
from shapely.geometry import Polygon, shape
from shapely.ops import unary_union

from scripts.screen_vr_native_depth import fine_grid_rows
from skippercast.platform.bottom_targets import bag_metadata, sha256, vr_transform


def classify_footprint(polygon, protected):
    if protected.covers(polygon):
        return 'fully_inside_mpa'
    if protected.intersects(polygon):
        return 'intersects_mpa'
    return 'outside_mpa'


def inspect(record, region, snapshot, cache):
    source = snapshot.get('sources', {}).get('mpas', {})
    data = source.get('data', {})
    features = data.get('geojson', {}).get('features', [])
    if (source.get('status') != 'ok' or data.get('feature_count') != len(features)
            or len(features) < 100 or record.get('status') != 'ok'
            or record.get('metadata_status') != 'mllw-product-uncertainty-reviewed-by-adapter'):
        raise ValueError('Original BAG or complete MPA snapshot unavailable')
    checked = datetime.fromisoformat(source['data_retrieved_at'].replace('Z', '+00:00'))
    if not 0 <= (datetime.now(timezone.utc) - checked).total_seconds() <= 36 * 3600:
        raise ValueError('CDFW MPA snapshot is stale')
    digest = hashlib.sha256(json.dumps(data['geojson'], sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()
    named_areas = [(item['properties'].get('NAME', 'Unlabeled MPA'), shape(item['geometry']))
                   for item in features]
    protected = unary_union([geometry for _, geometry in named_areas])
    url = record['url']
    path = cache / (record['survey_id'] + '-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.bag')
    if not path.is_file() or path.stat().st_size != record['file_bytes'] or sha256(path) != record['file_sha256']:
        raise ValueError('Original BAG bytes changed')
    counts = {'fine_grid_centers_in_region': 0, 'fully_inside_mpa': 0,
              'intersects_mpa': 0, 'outside_mpa': 0}
    names = {}
    with rasterio.open(path) as raster, h5py.File(path, 'r') as handle:
        root = handle['BAG_root']
        metadata = bag_metadata(root['metadata'][:].tobytes().decode().rstrip('\0'), record['survey_id'])
        if metadata['metadata_sha256'] != record['metadata_sha256']:
            raise ValueError('Original BAG metadata changed')
        grids = root['varres_metadata'][:]
        indices = fine_grid_rows(grids)
        if len(indices) != record['refinement_grids_at_most_4m']:
            raise ValueError('Original fine-grid count changed')
        to_geo = Transformer.from_crs(raster.crs, 'EPSG:4326', always_xy=True)
        west, south, east, north = region['bounds']
        for row, col in indices:
            item = grids[row, col]
            t = vr_transform(raster.bounds.left, raster.bounds.bottom,
                             raster.res[0], raster.res[1], int(row), int(col), item)
            x0, y0 = t.c, t.f - int(item['dimensions_y']) * float(item['resolution_y'])
            x1, y1 = t.c + int(item['dimensions_x']) * float(item['resolution_x']), t.f
            lon, lat = to_geo.transform((x0 + x1) / 2, (y0 + y1) / 2)
            if not (west <= lon < east and south <= lat < north):
                continue
            corners = [to_geo.transform(x, y) for x, y in
                       ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
            polygon = Polygon(corners)
            category = classify_footprint(polygon, protected)
            counts['fine_grid_centers_in_region'] += 1
            counts[category] += 1
            for name, geometry in named_areas:
                if geometry.intersects(polygon):
                    names[name] = names.get(name, 0) + 1
    if sum(counts[key] for key in ('fully_inside_mpa', 'intersects_mpa', 'outside_mpa')) != counts['fine_grid_centers_in_region']:
        raise ValueError('A fine grid was not classified')
    return {'schema_version': 1, 'scope': 'original-vr-bag-regional-mpa-review',
            'reviewed_at': datetime.now(timezone.utc).isoformat(),
            'region_id': region['id'], 'region_bounds': region['bounds'],
            'survey_id': record['survey_id'], 'bag_url': url,
            'bag_sha256': record['file_sha256'],
            'survey_report_url': record['source_report_url'],
            'cdfw_mpa_source_url': data['source_url'],
            'cdfw_mpa_retrieved_at': source['data_retrieved_at'],
            'cdfw_mpa_feature_count': len(features), 'cdfw_mpa_geojson_sha256': digest,
            'counts': counts, 'intersecting_mpa_names_and_grid_counts': names,
            'method': 'Native <=4 m supergrid centers inside exact package bounds; each complete supergrid footprint checked against the full official CDFW MPA snapshot.',
            'limitations': ['Grid centers are an assignment convention; footprints can cross a package boundary.',
                            'MPA intersection is a conservative fishing-target exclusion, not an interpretation of every legal take exception.',
                            'No fish habitat, fishing permission, safe route, current chart or bottom image follows from this review.'],
            'fishing_target': False, 'exportable': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--survey-id', required=True)
    parser.add_argument('--region', type=Path, required=True)
    parser.add_argument('--mpas', type=Path, default=Path('var/qualification-current/coastal/latest.json'))
    parser.add_argument('--cache', type=Path, default=Path('var/noaa-native-cache'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    files = json.loads(args.audit.read_text())['files']
    record = next((item for item in files if item.get('survey_id') == args.survey_id), None)
    if record is None:
        raise ValueError('Requested survey is absent from original BAG audit')
    packet = inspect(record, json.loads(args.region.read_text()),
                     json.loads(args.mpas.read_text()), args.cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(packet, separators=(',', ':')) + '\n')
    print(packet['region_id'], packet['survey_id'], packet['counts'])


if __name__ == '__main__':
    main()
