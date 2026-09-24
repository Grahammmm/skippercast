"""Cross-check original USGS camera windows against clear NOAA VR-BAG grids.

This is historical source corroboration. It never creates a fishing target.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import h5py
from pyproj import Transformer
import rasterio
from shapely.geometry import Point, Polygon, shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree

from scripts.audit_usgs_native_overlap import camera_accuracy
from scripts.audit_usgs_video_observations import load_archive, open_original_zip
from scripts.screen_vr_native_depth import fine_grid_rows
from skippercast.platform.bottom_targets import bag_metadata, sha256, vr_transform


def interior_camera_match(point, polygons, tree, margin_m=25):
    matches = [polygons[int(i)] for i in tree.query(point) if polygons[int(i)].covers(point)]
    if not matches:
        return 'outside_native_grid'
    if max(poly.boundary.distance(point) for poly in matches) < margin_m:
        return 'native_grid_edge_held'
    return 'native_grid_interior'


def inspect(record, region, snapshot, manifest, cache, video_cache, cruise):
    source = snapshot['sources']['mpas']
    data = source['data']
    features = data['geojson']['features']
    if source['status'] != 'ok' or data['feature_count'] != len(features) or len(features) < 100:
        raise ValueError('Incomplete CDFW MPA source')
    checked = datetime.fromisoformat(source['data_retrieved_at'].replace('Z', '+00:00'))
    if not 0 <= (datetime.now(timezone.utc) - checked).total_seconds() <= 36 * 3600:
        raise ValueError('Stale CDFW MPA source')
    mpa_digest = hashlib.sha256(json.dumps(data['geojson'], sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
    protected = unary_union([shape(f['geometry']) for f in features])
    video = load_archive(video_cache, cruise, manifest['archives'][cruise], manifest['base_url'], False)
    accuracy = camera_accuracy(video)
    reader = open_original_zip(video)
    url = record['url']
    path = cache / (record['survey_id'] + '-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.bag')
    if (record['status'] != 'ok' or not path.is_file()
            or path.stat().st_size != record['file_bytes'] or sha256(path) != record['file_sha256']):
        raise ValueError('Original BAG source changed')
    counts = Counter()
    classes = {'native_grid_edge_held': Counter(), 'native_grid_interior': Counter()}
    with rasterio.open(path) as raster, h5py.File(path) as handle:
        root = handle['BAG_root']
        metadata = bag_metadata(root['metadata'][:].tobytes().decode().rstrip('\0'), record['survey_id'])
        if metadata['metadata_sha256'] != record['metadata_sha256']:
            raise ValueError('Original BAG metadata changed')
        grids = root['varres_metadata'][:]
        indices = fine_grid_rows(grids)
        if len(indices) != record['refinement_grids_at_most_4m']:
            raise ValueError('Original fine-grid count changed')
        to_geo = Transformer.from_crs(raster.crs, 'EPSG:4326', always_xy=True)
        from_geo = Transformer.from_crs('EPSG:4326', raster.crs, always_xy=True)
        west, south, east, north = region['bounds']
        polygons = []
        for row, col in indices:
            item = grids[row, col]
            t = vr_transform(raster.bounds.left, raster.bounds.bottom,
                             raster.res[0], raster.res[1], int(row), int(col), item)
            x0, y0 = t.c, t.f - int(item['dimensions_y']) * float(item['resolution_y'])
            x1, y1 = t.c + int(item['dimensions_x']) * float(item['resolution_x']), t.f
            lon, lat = to_geo.transform((x0 + x1) / 2, (y0 + y1) / 2)
            if not (west <= lon < east and south <= lat < north):
                continue
            polygon = Polygon(((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
            if protected.intersects(transform(to_geo.transform, polygon)):
                continue
            polygons.append(polygon)
        tree = STRtree(polygons)
        for item in reader.iterShapeRecords():
            if not item.shape.points:
                continue
            lon, lat = item.shape.points[0]
            if not (west <= lon < east and south <= lat < north):
                continue
            row = item.record.as_dict()
            major = str(row.get('MAJOR_GEO') or '').strip().lower()
            if not major or protected.covers(Point(lon, lat)):
                continue
            counts['camera_bottom_windows_outside_mpa_in_region'] += 1
            point = Point(*from_geo.transform(lon, lat))
            status = interior_camera_match(point, polygons, tree)
            counts[status] += 1
            if status in classes:
                classes[status][major] += 1
    if sum(counts[key] for key in ('outside_native_grid', 'native_grid_edge_held',
                                   'native_grid_interior')) != counts['camera_bottom_windows_outside_mpa_in_region']:
        raise ValueError('A camera window was not classified')
    return {'schema_version': 1, 'scope': 'original-camera-vr-bag-mpa-overlap-review',
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'region_id': region['id'], 'survey_id': record['survey_id'],
            'bag_url': url, 'bag_sha256': record['file_sha256'],
            'video_cruise': cruise,
            'video_source_url': manifest['base_url'] + cruise + '_video_observations.zip',
            'video_archive_sha256': manifest['archives'][cruise],
            'video_position_accuracy': accuracy,
            'cdfw_mpa_source_url': data['source_url'],
            'cdfw_mpa_retrieved_at': source['data_retrieved_at'],
            'cdfw_mpa_geojson_sha256': mpa_digest,
            'counts': dict(counts),
            'matched_bottom_classes': {key: dict(value) for key, value in classes.items()},
            'method': 'Original camera positions are compared with complete fine-grid footprints outside all CDFW MPAs; observations less than 25 m inside a grid edge are held.',
            'limitations': ['Camera position accuracy is variable, on the order of 10 m; a single video window is not independent fishery evidence.',
                            'A match to a supergrid says only that the survey has a depth source there, not that the whole grid shares the observed bottom.',
                            'No current fish presence, legal permission, navigation clearance, fishing target or export follows.'],
            'fishing_target': False, 'exportable': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit', type=Path, required=True)
    p.add_argument('--survey-id', required=True)
    p.add_argument('--region', type=Path, required=True)
    p.add_argument('--cruise', required=True)
    p.add_argument('--mpas', type=Path, default=Path('var/qualification-current/coastal/latest.json'))
    p.add_argument('--manifest', type=Path, default=Path('catalog/usgs-video-cruises.json'))
    p.add_argument('--cache', type=Path, default=Path('var/noaa-native-cache'))
    p.add_argument('--video-cache', type=Path, default=Path('var/usgs-video-cache'))
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    files = json.loads(a.audit.read_text())['files']
    record = next((x for x in files if x.get('survey_id') == a.survey_id), None)
    if record is None:
        raise ValueError('Requested original BAG is unavailable')
    result = inspect(record, json.loads(a.region.read_text()), json.loads(a.mpas.read_text()),
                     json.loads(a.manifest.read_text()), a.cache, a.video_cache, a.cruise)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    print(result['region_id'], result['survey_id'], result['counts'], result['matched_bottom_classes'])


if __name__ == '__main__':
    main()
