"""Intersect original NOAA regular BAG cells with original USGS hard class.

This produces a dated native-cell review layer, never fishing targets. Legal
access, federal closures, current fish presence, routes and navigation require
separate checks before any regional target can be published.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import numpy as np
from scipy.ndimage import binary_erosion, label, minimum, maximum
import rasterio
from rasterio.features import rasterize, shapes
from rasterio.warp import reproject, Resampling, transform_bounds
from shapely.geometry import box, mapping, shape, Point
from shapely.ops import transform
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_usgs_statewide_context import hard_class_review, mpa_union
from skippercast.platform.bottom_targets import bag_metadata, cells_qualified, sha256


def original_character(row, cache, metadata):
    """Return one original class raster only after archive and XML review."""
    if row.get('status') != 'ok' or row.get('kind') != 'seafloor_character':
        raise ValueError('An original USGS seafloor-character grid is required')
    record = next((x for x in metadata['records'] if x['block_id'] == row['block_id']
                   and x['kind'] == row['kind'] and x['metadata_url'] == row['metadata_url']
                   and x['status'] == 'ok'), None)
    if not record or record['xml_sha256'] != row['metadata_sha256'] or not hard_class_review(record):
        raise ValueError('Original USGS class-3 semantics or metadata digest are unreviewed')
    url = row['archive_url']
    path = cache / (row['block_id'] + '-' + row['kind'] + '-'
                    + hashlib.sha256(url.encode()).hexdigest()[:16] + '.zip')
    if not path.is_file() or sha256(path) != row['archive_sha256']:
        raise ValueError('Original USGS archive is missing or changed')
    with zipfile.ZipFile(path) as bundle:
        members = [x.filename for x in bundle.infolist() if x.filename.lower().endswith('.tif')
                   and not x.filename.startswith('__MACOSX/')]
        if len(members) != 1:
            raise ValueError('Ambiguous original USGS raster member')
    return f'zip://{path.resolve()}!{members[0]}'


def hard_mask_on_bag(rows, cache, metadata, *, shape_, transform_, crs):
    hard = np.zeros(shape_, dtype=bool)
    receipts = []
    for row in rows:
        uri = original_character(row, cache, metadata)
        with rasterio.open(uri) as source:
            if source.count != 1 or not source.crs or not all(1.5 <= x <= 5.1 for x in source.res):
                raise ValueError('Original USGS class raster resolution/CRS is unsupported')
            data = source.read(1, masked=True)
            class_three = (~np.ma.getmaskarray(data) & (data.data.astype('int64') % 10 == 3)).astype('uint8')
            placed = np.zeros(shape_, dtype='uint8')
            reproject(class_three, placed, src_transform=source.transform, src_crs=source.crs,
                      src_nodata=0, dst_transform=transform_, dst_crs=crs, dst_nodata=0,
                      resampling=Resampling.nearest)
            hard |= placed.astype(bool)
            receipts.append({'block_id': row['block_id'], 'archive_url': row['archive_url'],
                             'archive_sha256': row['archive_sha256'],
                             'metadata_url': row['metadata_url'],
                             'metadata_sha256': row['metadata_sha256'],
                             'original_resolution_m': list(source.res)})
    # A two-native-cell inset avoids treating source reprojection and class
    # boundary uncertainty as an exactly located rock edge.
    return binary_erosion(hard, iterations=2, border_value=0), receipts


def excluded_mpa_cells(snapshot, *, shape_, transform_, crs, geographic_bounds, clearance_m=100):
    complete = mpa_union(snapshot)  # Fails on stale or incomplete CDFW geometry.
    clipped = complete.intersection(box(*geographic_bounds).buffer(.02))
    if clipped.is_empty:
        return np.zeros(shape_, dtype=bool)
    projected = transform(Transformer.from_crs('EPSG:4326', crs, always_xy=True).transform, clipped)
    return rasterize([(mapping(projected.buffer(clearance_m)), 1)], out_shape=shape_,
                     transform=transform_, dtype='uint8').astype(bool)


def excluded_federal_gea_cells(snapshot, *, shape_, transform_, crs, geographic_bounds, clearance_m=100):
    if (snapshot.get('scope') != 'noaa-west-coast-groundfish-conservation-areas' or
            snapshot.get('status') != 'ok' or len(snapshot.get('features', [])) < 25):
        raise ValueError('Complete current NOAA federal area geometry is required')
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(snapshot['retrieved_at'])).total_seconds()
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError('NOAA federal area retrieval timestamp is invalid') from error
    if not 0 <= age <= 36 * 3600:
        raise ValueError('NOAA federal area geometry is stale')
    geas = [f for f in snapshot['features'] if f.get('properties', {}).get('area_type') == 'GEA']
    if len(geas) < 10 or not any('Cordell_Bank_20260623' in f['properties'].get('source_layer', '') for f in geas):
        raise ValueError('Current Cordell Bank or other federal exclusion geometry is missing')
    survey = box(*geographic_bounds).buffer(.02)
    to_native = Transformer.from_crs('EPSG:4326', crs, always_xy=True).transform
    outlines = []
    for feature in geas:
        geom = shape(feature['geometry'])
        if not geom.is_valid or geom.is_empty:
            raise ValueError('Invalid NOAA federal exclusion polygon')
        if geom.intersects(survey):
            outlines.append((mapping(transform(to_native, geom).buffer(clearance_m)), 1))
    return (rasterize(outlines, out_shape=shape_, transform=transform_, dtype='uint8').astype(bool)
            if outlines else np.zeros(shape_, dtype=bool))


def excluded_report_hazards(survey_id, registry, report_cache, *, shape_, transform_, crs):
    review = next((x for x in registry.get('surveys', []) if x.get('survey_id') == survey_id), None)
    if registry.get('scope') != 'historical-noaa-survey-hazard-review' or not review:
        raise ValueError('Original survey hazard report has not been reviewed')
    url = review['report_url']
    if not url.startswith('https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/'):
        raise ValueError('Unreviewed NOAA report URL')
    path = report_cache / (survey_id + '.pdf')
    if not path.is_file() or sha256(path) != review['report_sha256']:
        raise ValueError('Original NOAA descriptive report is missing or changed')
    for supporting in review.get('supporting_reports', []):
        supporting_url = supporting['url']
        if not supporting_url.startswith('https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/'):
            raise ValueError('Unreviewed supporting NOAA report URL')
        supporting_path = report_cache / (supporting['survey_id'] + '.pdf')
        if not supporting_path.is_file() or sha256(supporting_path) != supporting['sha256']:
            raise ValueError('Supporting NOAA descriptive report is missing or changed')
    to_native = Transformer.from_crs('EPSG:4326', crs, always_xy=True).transform
    outlines = []
    for hazard in review['hazards']:
        lon, lat, radius = hazard['longitude'], hazard['latitude'], hazard['review_exclusion_radius_m']
        if not (-125 <= lon <= -117 and 32 <= lat <= 42 and 0 < radius <= 1000):
            raise ValueError('Invalid reviewed California hazard position/radius')
        outlines.append((mapping(transform(to_native, Point(lon, lat)).buffer(radius)), 1))
    mask = (rasterize(outlines, out_shape=shape_, transform=transform_, dtype='uint8').astype(bool)
            if outlines else np.zeros(shape_, dtype=bool))
    return mask, review


def compile_review(bag_row, usgs_rows, usgs_metadata, mpa_snapshot, federal_snapshot, hazard_registry,
                   bag_cache, usgs_cache, report_cache,
                   *, minimum_area_m2=2500, limit_ft=200):
    if (bag_row.get('status') != 'ok' or bag_row.get('metadata_status') != 'mllw-product-uncertainty-reviewed-by-adapter'
            or bag_row.get('variable_refinement_records') != 0
            or max(bag_row.get('overview_resolution_m', [float('inf')])) > 4):
        raise ValueError('A strict regular-resolution original MLLW BAG is required')
    url = bag_row['url']
    bag = bag_cache / (bag_row['survey_id'] + '-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.bag')
    if not bag.is_file() or sha256(bag) != bag_row['file_sha256']:
        raise ValueError('Original NOAA BAG is missing or its digest changed')
    with rasterio.open(bag) as raster:
        if raster.count < 2 or raster.res[0] != raster.res[1] or raster.res[0] > 4:
            raise ValueError('Original NOAA BAG lacks supported native elevation/uncertainty bands')
        # A BAG CRS contains a vertical axis. Its horizontal WKT is checked
        # against the embedded metadata and used for two-dimensional overlays.
        import h5py
        with h5py.File(bag, 'r') as h:
            root = h['BAG_root']
            xml = root['metadata'][:].tobytes().decode('utf-8').rstrip('\0')
            tracked = root['tracking_list'][:] if 'tracking_list' in root else []
        original = bag_metadata(xml, bag_row['survey_id'])
        if original['metadata_sha256'] != bag_row['metadata_sha256']:
            raise ValueError('Embedded BAG metadata digest changed')
        from pyproj import CRS
        horizontal = CRS.from_wkt(original['horizontal_wkt'])
        if horizontal.is_bound:
            horizontal = horizontal.source_crs
        bag_crs = CRS.from_user_input(raster.crs)
        if bag_crs.is_compound:
            bag_crs = bag_crs.sub_crs_list[0]
        if bag_crs.is_bound:
            bag_crs = bag_crs.source_crs
        if not horizontal.equals(bag_crs, ignore_axis_order=True):
            raise ValueError('BAG horizontal CRS mismatch')
        grid_shape = (raster.height, raster.width)
        hard, source_receipts = hard_mask_on_bag(usgs_rows, usgs_cache, usgs_metadata,
                                                 shape_=grid_shape, transform_=raster.transform, crs=horizontal)
        if not np.any(hard):
            raise ValueError('No original USGS class-3 cells intersect the original BAG')
        geographic_bounds = transform_bounds(horizontal, 'EPSG:4326', *raster.bounds, densify_pts=21)
        excluded = excluded_mpa_cells(mpa_snapshot, shape_=grid_shape, transform_=raster.transform,
                                      crs=horizontal, geographic_bounds=geographic_bounds)
        federal = excluded_federal_gea_cells(federal_snapshot, shape_=grid_shape,
                                              transform_=raster.transform, crs=horizontal,
                                              geographic_bounds=geographic_bounds)
        hazards, hazard_review = excluded_report_hazards(bag_row['survey_id'], hazard_registry, report_cache,
                                                          shape_=grid_shape, transform_=raster.transform, crs=horizontal)
        elevation = raster.read(1)
        uncertainty = raster.read(2)
        tracked_changes = []
        for record in tracked:
            north_row = raster.height - 1 - int(record['row'])
            col = int(record['col'])
            if not 0 <= north_row < raster.height or not 0 <= col < raster.width:
                raise ValueError('BAG tracking record lies outside the original grid')
            tracked_changes.append(abs(float(elevation[north_row, col]) - float(record['depth'])))
        qualified = cells_qualified(elevation, uncertainty, raster.res[0], limit_ft=limit_ft)
        support = hard & qualified & ~excluded & ~federal & ~hazards
        native_labels, count = label(support)
        sizes = np.bincount(native_labels.ravel())
        minimum_cells = int(np.ceil(minimum_area_m2 / (raster.res[0] * raster.res[1])))
        retained = np.flatnonzero(sizes >= minimum_cells)
        retained = retained[retained != 0]
        polygon_mask = np.isin(native_labels, retained)
        retained_set = set(map(int, retained))
        depth_min = minimum(-elevation, labels=native_labels, index=retained)
        depth_max = maximum(-elevation, labels=native_labels, index=retained)
        error_max = maximum(uncertainty, labels=native_labels, index=retained)
        summary = {int(component): (float(lo), float(hi), float(error))
                   for component, lo, hi, error in zip(retained, depth_min, depth_max, error_max)}
        polygons = []
        to_geo = Transformer.from_crs(horizontal, 'EPSG:4326', always_xy=True).transform
        for geometry, component in shapes(native_labels, mask=polygon_mask, transform=raster.transform):
            component = int(component)
            if component not in retained_set:
                continue
            native = shape(geometry)
            if native.area < minimum_area_m2:
                continue
            lo, hi, error = summary[component]
            polygons.append({'type': 'Feature', 'geometry': mapping(transform(to_geo, native)),
                             'properties': {'component': component, 'native_cells': int(sizes[component]),
                                            'area_m2': round(float(native.area)),
                                            'depth_ft_range': [round(lo / .3048, 1), round(hi / .3048, 1)],
                                            'max_product_uncertainty_m': round(error, 3),
                                            'fishing_target': False, 'exportable': False,
                                            'legal_clearance': False, 'fish_confirmed': False}})
        polygons.sort(key=lambda f: -f['properties']['area_m2'])
        return {'type': 'FeatureCollection', 'schema_version': 1, 'scope': 'native-noaa-usgs-hard-bottom-review',
                'compiled_at': datetime.now(timezone.utc).isoformat(),
                'survey_id': bag_row['survey_id'], 'noaa_bag_url': url,
                'noaa_bag_sha256': bag_row['file_sha256'], 'noaa_metadata_sha256': bag_row['metadata_sha256'],
                'survey_dates': [bag_row['survey_start'], bag_row['survey_end']],
                'usgs_sources': source_receipts,
                'survey_report_url': hazard_review['report_url'],
                'survey_report_sha256': hazard_review['report_sha256'],
                'historical_hazards_screened': hazard_review['hazards'],
                'cdfw_mpa_retrieved_at': mpa_snapshot['sources']['mpas']['data_retrieved_at'],
                'noaa_federal_areas_retrieved_at': federal_snapshot['retrieved_at'],
                'native_resolution_m': list(raster.res), 'minimum_area_m2': minimum_area_m2,
                'maximum_planning_depth_ft': limit_ft, 'mpa_clearance_m': 100,
                'bag_tracking_history': {'original_values_before_manual_edits': len(tracked),
                                         'depth_values_changed_in_current_grid': sum(delta > 0.001 for delta in tracked_changes),
                                         'maximum_depth_revision_m': round(max(tracked_changes, default=0), 3)},
                'method': 'Original NOAA MLLW/product-uncertainty cells AND original USGS class-3 cells, with a two-native-cell class edge inset, 100 m CDFW MPA and NOAA GEA buffers, and reviewed historical DTON holds. No interpolation creates a fishable cell.',
                'limitations': ['Historical depth and substrate do not confirm present fish or individual boulder size.',
                                'The BAG tracking list holds pre-edit node values; the current grid includes manual hydrographer edits.',
                                'Federal and other local closures, current hazards, routes and current legal rules are not cleared.',
                                'This review geometry is not a navigation chart or a fishing waypoint.'],
                'counts': {'hard_cells_after_inset': int(np.count_nonzero(hard)),
                           'depth_uncertainty_qualified_cells': int(np.count_nonzero(qualified)),
                           'hard_depth_cells_after_mpa_gea_historical_hazard_screen': int(np.count_nonzero(support)),
                           'retained_components': len(polygons)},
                'features': polygons}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--survey-id', required=True)
    parser.add_argument('--bag-filename', required=True)
    parser.add_argument('--usgs-block', action='append', required=True)
    parser.add_argument('--bag-audit', type=Path, default=Path('var/noaa-native-audit-100mb-refined.json'))
    parser.add_argument('--usgs-audit', type=Path, default=Path('var/usgs-native-audit.json'))
    parser.add_argument('--usgs-metadata', type=Path, default=Path('var/usgs-map-metadata.json'))
    parser.add_argument('--mpas', type=Path, default=Path('var/qualification-current/coastal/latest.json'))
    parser.add_argument('--federal-areas', type=Path, default=Path('var/noaa-federal-areas.json'))
    parser.add_argument('--hazards', type=Path, default=Path('catalog/noaa-survey-hazards.json'))
    parser.add_argument('--bag-cache', type=Path, default=Path('var/noaa-native-cache'))
    parser.add_argument('--usgs-cache', type=Path, default=Path('var/usgs-native-cache'))
    parser.add_argument('--report-cache', type=Path, default=Path('var/noaa-report-cache'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    bag_audit = json.loads(args.bag_audit.read_text())
    usgs_audit = json.loads(args.usgs_audit.read_text())
    bag_row = next((x for x in bag_audit['files'] if x['survey_id'] == args.survey_id
                    and x['url'].endswith('/' + args.bag_filename)), None)
    selected = [x for x in usgs_audit['products'] if x.get('block_id') in args.usgs_block
                and x.get('kind') == 'seafloor_character' and x.get('status') == 'ok']
    if not bag_row or {x['block_id'] for x in selected} != set(args.usgs_block):
        raise ValueError('Missing exact audited NOAA BAG or original USGS source block')
    result = compile_review(bag_row, selected, json.loads(args.usgs_metadata.read_text()),
                            json.loads(args.mpas.read_text()), json.loads(args.federal_areas.read_text()),
                            json.loads(args.hazards.read_text()),
                            args.bag_cache, args.usgs_cache, args.report_cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    temp.replace(args.output)
    print(result['survey_id'], result['counts'])


if __name__ == '__main__':
    main()
