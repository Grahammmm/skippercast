"""Reconcile dated Cape camera windows with screened original H11975 cells.

This audits historical source agreement at camera centers, not fishing spots.
The original camera accuracy varies by roughly 10 m, so even a passing center
cannot establish a precise rock pile or a safe/legal fishing location.
"""

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

from pyproj import Transformer
from rasterio.features import rasterize
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import transform
from shapely.strtree import STRtree

from audit_usgs_native_overlap import MIN_INTERIOR_M, camera_accuracy
from audit_usgs_video_observations import load_archive, open_original_zip
from screen_vr_original_hard import screen


def camera_windows(context, manifest, cache):
    data = json.loads(context.read_text())
    if data.get('scope') != 'northern-nbs-usgs-hard-research-context':
        raise ValueError('Unexpected research context')
    if any(feature['properties'].get('fishing_target') is not False or
           feature['properties'].get('exportable') is not False for feature in data['features']):
        raise ValueError('Camera audit accepts research outlines only')
    to_m = Transformer.from_crs(4326, 3310, always_xy=True).transform
    polygons = [transform(to_m, shape(feature['geometry'])) for feature in data['features']]
    tree = STRtree(polygons)
    windows = []
    cruise = 'c210nc'
    raw = load_archive(cache, cruise, manifest['archives'][cruise], manifest['base_url'], False)
    camera_accuracy(raw)  # Hold if the original position-accuracy disclosure changes.
    for item in open_original_zip(raw).iterShapeRecords():
        if not item.shape.points or not item.record.as_dict().get('MAJOR_GEO'):
            continue
        lon, lat = item.shape.points[0]
        point = transform(to_m, Point(lon, lat))
        for index in tree.query(point):
            if polygons[index].contains(point) and polygons[index].boundary.distance(point) >= MIN_INTERIOR_M:
                windows.append((data['features'][index]['properties']['id'], lon, lat))
    return data, windows


def reconcile(context, manifest, video_cache, bag_audit, usgs_audit, usgs_metadata,
              bag_cache, usgs_cache, mpas, federal, hazards, report_cache):
    context_data, windows = camera_windows(context, manifest, video_cache)
    packet = json.loads(bag_audit.read_text())
    if packet.get('scope') != 'noaa-original-bag-native-overview-audit' or len(packet['files']) != 1:
        raise ValueError('Expected one original NOAA BAG')
    bag = packet['files'][0]
    if bag['survey_id'] != 'H11975':
        raise ValueError('This review requires H11975')
    sources = json.loads(usgs_audit.read_text())
    source = next(row for row in sources['products']
                  if row.get('release_id') == 'P9U0SUGL' and row.get('kind') == 'seafloor_character'
                  and row.get('status') == 'ok')
    # Projection is the original BAG's horizontal NAD83 UTM 10 CRS.
    native = Transformer.from_crs(4326, 'EPSG:26910', always_xy=True)
    points = [(outline, *native.transform(lon, lat)) for outline, lon, lat in windows]
    outlines = [transform(native.transform, shape(feature['geometry']))
                for feature in context_data['features']]
    outline_tree = STRtree(outlines)
    outline_counts = defaultdict(lambda: {'qualified_original_cells': 0,
                                           'qualified_original_cell_area_m2': 0.0})
    passing = set()
    depths = {}

    def collect(mask, depth, affine, horizontal):
        if horizontal.to_epsg() != 26910:
            raise ValueError('H11975 native projection changed')
        left, top = affine.c, affine.f
        dx, dy = affine.a, -affine.e
        footprint = box(left, top - mask.shape[0] * dy,
                        left + mask.shape[1] * dx, top)
        for index in outline_tree.query(footprint):
            index = int(index)
            outline = outlines[index]
            if not outline.intersects(footprint):
                continue
            inside = rasterize([(mapping(outline), 1)], out_shape=mask.shape,
                               transform=affine, dtype='uint8').astype(bool)
            count = int((mask & inside).sum())
            if count:
                ident = context_data['features'][index]['properties']['id']
                outline_counts[ident]['qualified_original_cells'] += count
                outline_counts[ident]['qualified_original_cell_area_m2'] += count * dx * dy
        for number, (_, x, y) in enumerate(points):
            col, row = int((x - left) // dx), int((top - y) // dy)
            if 0 <= row < mask.shape[0] and 0 <= col < mask.shape[1] and mask[row, col]:
                passing.add(number)
                depths[number] = round(float(-depth[row, col] / .3048), 1)

    receipt = screen(bag, source, json.loads(usgs_metadata.read_text()), bag_cache, usgs_cache,
                     json.loads(mpas.read_text()), json.loads(federal.read_text()),
                     json.loads(hazards.read_text()), report_cache, mask_callback=collect)
    counts = defaultdict(lambda: {'camera_windows': 0, 'centers_on_qualified_original_cells': 0,
                                   'qualified_center_depths_ft': []})
    for number, (outline, _, _) in enumerate(windows):
        counts[outline]['camera_windows'] += 1
        if number in passing:
            counts[outline]['centers_on_qualified_original_cells'] += 1
            counts[outline]['qualified_center_depths_ft'].append(depths[number])
    return {
        'schema_version': 1, 'scope': 'h11975-original-cells-vs-historical-camera-centers',
        'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'context_compiled_at': context_data['compiled_at'],
        'camera_archive_sha256': manifest['archives']['c210nc'],
        'camera_archive_url': manifest['base_url'] + 'c210nc_video_observations.zip',
        'bag_sha256': receipt['bag_sha256'], 'usgs_archive_sha256': receipt['usgs_archive_sha256'],
        'screened_mpa_at': receipt['mpa_retrieved_at'],
        'screened_federal_at': receipt['federal_areas_retrieved_at'],
        'minimum_display_interior_clearance_m': MIN_INTERIOR_M,
        'total_camera_windows': len(windows), 'centers_on_qualified_original_cells': len(passing),
        'outlines': [{'outline_id': feature['properties']['id'],
                      **counts[feature['properties']['id']],
                      'qualified_original_cells': outline_counts[feature['properties']['id']]['qualified_original_cells'],
                      'qualified_original_cell_area_m2': round(outline_counts[feature['properties']['id']]['qualified_original_cell_area_m2'], 1)}
                     for feature in context_data['features']],
        'fishing_target': False, 'exportable': False,
        'method': 'Each research outline and historical camera center is tested against original H11975 <=4 m measured BAG refinement cells that pass original USGS class-3 two-cell inset, 25–200 ft depth with 2 m margin and <=1 m uncertainty, and buffered current MPA/GEA plus original-report danger exclusions. Area is the sum of original qualified cell areas inside each outline, not a continuous mapped patch.',
        'limitations': ['Camera positions have highly variable accuracy near 10 m; a center-cell match does not verify the surrounding bottom.',
                        'No present-day fish, catch, safe route, current navigation chart or local species and gear rules are established.'],
    }


def main():
    root = Path('.')
    result = reconcile(
        root/'dist/data/northern-nbs-usgs-hard-research-context.geojson',
        json.loads((root/'catalog/usgs-video-cruises.json').read_text()),
        root/'var/usgs-video-cache', root/'var/noaa-h11975-native-audit.json',
        root/'var/usgs-doi-native-audit.json', root/'var/usgs-doi-metadata.json',
        root/'var/noaa-native-cache', root/'var/usgs-doi-native-cache',
        root/'var/qualification-current/coastal/latest.json', root/'var/noaa-federal-areas.json',
        root/'catalog/noaa-survey-hazards.json', root/'var/noaa-report-cache')
    output = root/'dist/data/h11975-original-camera-cell-review.json'
    output.write_text(json.dumps(result, indent=2)+'\n')
    print(result['total_camera_windows'], result['centers_on_qualified_original_cells'])


if __name__ == '__main__':
    main()
