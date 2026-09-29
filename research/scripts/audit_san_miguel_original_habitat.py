"""Screen original USGS San Miguel habitat against NOAA MLLW depth cells."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tarfile

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.windows import Window, from_bounds, transform as window_transform
from rasterio.warp import transform_bounds
import shapefile
from shapely.geometry import shape
from shapely.ops import transform
from shapely.validation import make_valid
from pyproj import Transformer

from skippercast.platform.bottom_targets import cells_qualified, sha256


MEMBERS = {f's_mig/smighab.{ext}' for ext in ('shp', 'shx', 'dbf', 'txt')}


def read_usgs(path, record):
    if (path.stat().st_size != record['archive_bytes'] or sha256(path) != record['archive_sha256']
            or record['archive_url'] != 'https://pubs.usgs.gov/of/2003/0085/s_mig/smighab.tgz'):
        raise ValueError('Original USGS archive changed or source is unreviewed')
    with tarfile.open(path, 'r:gz') as bundle:
        if {item.name for item in bundle.getmembers()} != MEMBERS:
            raise ValueError('Original USGS members changed')
        data = {ext: bundle.extractfile(f's_mig/smighab.{ext}').read()
                for ext in ('shp', 'shx', 'dbf', 'txt')}
    metadata = data['txt'].decode('utf-8', errors='replace')
    if not all(text in metadata for text in (
            'BOTTOM_ID is h for hard bottom, m for mixed hard and soft bottom',
            'Accuracy of the horizontal coordinates is on the order of 10 m',
            'Use_Constraints: Not Suitable for navigation.')):
        raise ValueError('USGS semantics or positional limits changed')
    reader = shapefile.Reader(shp=io.BytesIO(data['shp']), shx=io.BytesIO(data['shx']),
                              dbf=io.BytesIO(data['dbf']))
    if reader.shapeType != shapefile.POLYGON or len(reader) < 100:
        raise ValueError('Original USGS geometry count or type changed')
    groups = {'h': [], 'm': [], 's': []}
    invalid_counts = {'h': 0, 'm': 0, 's': 0}
    for item in reader.iterShapeRecords():
        code = item.record.as_dict()['BOTTOM_ID'].lower()
        geometry = shape(item.shape.__geo_interface__)
        if code not in groups or geometry.is_empty:
            raise ValueError('Unknown or invalid original USGS habitat class')
        if not geometry.is_valid:
            invalid_counts[code] += 1
            geometry = make_valid(geometry)
            if geometry.is_empty or not geometry.is_valid:
                raise ValueError('Original USGS polygon cannot be repaired for source review')
        groups[code].append(geometry)
    return groups, {'polygon_count': len(reader), 'bbox': list(reader.bbox),
                    'metadata_sha256': hashlib.sha256(data['txt']).hexdigest(),
                    'invalid_source_polygons_repaired_for_review': invalid_counts}


def review(manifest, usgs_cache, bag_cache):
    if manifest.get('scope') != 'original-san-miguel-historical-habitat-native-depth-review-inputs':
        raise ValueError('Wrong source contract')
    usgs, noaa = manifest['usgs'], manifest['noaa_regular']
    groups, source = read_usgs(usgs_cache / 'smighab.tgz', usgs)
    url = noaa['bag_url']
    if (noaa['survey_id'] != 'W00320' or url !=
            'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/W00001-W02000/W00320/BAG/W00320_MB_4m_MLLW_1of3.bag'):
        raise ValueError('Unreviewed original NOAA BAG')
    bag_path = bag_cache / ('W00320-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.bag')
    if (bag_path.stat().st_size != noaa['bag_bytes'] or sha256(bag_path) != noaa['bag_sha256']):
        raise ValueError('Original NOAA BAG changed')
    with rasterio.open(bag_path) as bag:
        if bag.count < 2 or bag.res != (4.0, 4.0) or 'MLLW' not in bag.crs.to_wkt():
            raise ValueError('Expected 4 m MLLW BAG with uncertainty')
        bounds = transform_bounds('EPSG:4269', bag.crs, *source['bbox'], densify_pts=21)
        window = from_bounds(*bounds, transform=bag.transform).round_offsets().round_lengths()
        window = window.intersection(Window(0, 0, bag.width, bag.height))
        if not 0 < window.width * window.height <= 10_000_000:
            raise ValueError('USGS/NOAA overlap outside bounded window')
        elevation = bag.read(1, window=window)
        uncertainty = bag.read(2, window=window)
        measured = np.isfinite(elevation) & (elevation < 0) & (elevation > -3000)
        qualified = cells_qualified(elevation, uncertainty, 4, limit_ft=200)
        to_bag = Transformer.from_crs('EPSG:4269', bag.crs, always_xy=True).transform
        affine = window_transform(window, bag.transform)
        counts = {}
        for code in ('h', 'm', 's'):
            outlines = ((transform(to_bag, geometry), 1) for geometry in groups[code])
            mask = rasterize(outlines, out_shape=qualified.shape, transform=affine,
                             dtype='uint8').astype(bool)
            counts[code] = {'source_polygons': len(groups[code]),
                            'rasterized_noaa_cells': int(mask.sum()),
                            'measured_noaa_cells': int(np.count_nonzero(mask & measured)),
                            'depth_uncertainty_eligible_cells': int(np.count_nonzero(mask & qualified))}
    return {'schema_version': 1,
            'scope': 'san-miguel-original-usgs-habitat-noaa-depth-source-review',
            'reviewed_at': datetime.now(timezone.utc).isoformat(),
            'usgs_archive_url': usgs['archive_url'], 'usgs_archive_sha256': usgs['archive_sha256'],
            'usgs_source_year': usgs['source_year'], 'usgs_release_year': usgs['release_year'],
            'usgs_reported_horizontal_accuracy_m_order': usgs['reported_horizontal_accuracy_m_order'],
            'usgs_original': source,
            'noaa_bag_url': url, 'noaa_bag_sha256': noaa['bag_sha256'],
            'noaa_mllw_resolution_m': 4, 'overlap_window_cells': int(window.width * window.height),
            'noaa_measured_cells_in_window': int(measured.sum()),
            'noaa_shallowest_measured_elevation_m_mllw': round(float(elevation[measured].max()), 3) if measured.any() else None,
            'noaa_depth_uncertainty_eligible_cells_in_window': int(qualified.sum()),
            'substrate_classes': counts,
            'fishing_target': False, 'exportable': False,
            'limitations': [
                'The USGS polygons are historical hand interpretations of sidescan imagery with approximately 10 m positional accuracy, not current boulder measurements.',
                'The later NOAA MLLW depths do not validate the older substrate classes.',
                'Three original USGS polygons are topologically invalid; minimal geometry repair is applied only to count research overlap.',
                'Current MPAs, federal closures, chart hazards, navigation and method-specific access remain unscreened.'
            ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path('catalog/usgs-ofr0385-san-miguel.json'))
    parser.add_argument('--usgs-cache', type=Path, default=Path('var/usgs-ofr0385'))
    parser.add_argument('--bag-cache', type=Path, default=Path('var/noaa-native-cache'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    result = review(manifest, args.usgs_cache, args.bag_cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    if args.verify:
        expected = json.loads(args.verify.read_text())
        if {k: v for k, v in expected.items() if k != 'reviewed_at'} != {
                k: v for k, v in result.items() if k != 'reviewed_at'}:
            raise SystemExit('Original San Miguel source review changed')
    print(json.dumps({'classes': result['substrate_classes'], 'fishing_target': False}))


if __name__ == '__main__':
    main()
