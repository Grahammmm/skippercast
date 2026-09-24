"""Measure native USGS bathymetry under MPA-screened habitat context.

Depths stay in the original vertical datum. This is a source-quality review,
not a legal depth, chart, route, catch or target-site qualification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import rasterio
from rasterio.mask import mask
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform


def audit(source, archive, context, video, *, context_name):
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != source['bathymetry_sha256']:
        raise ValueError('Original bathymetry digest changed')
    if source.get('bathymetry_vertical_datum') != 'NAVD88':
        raise ValueError('Expected reviewed NAVD88 source')
    if context.get('source_catalog_url') != 'https://cmgds.marine.usgs.gov/data/csmp/' or context.get('failed_blocks'):
        raise ValueError('Context source or original block review is incomplete')
    layer = next((item for item in video.get('layers', [])
                  if item['context_file'] == context_name), None)
    if not layer or layer['outline_count'] != len(context['features']):
        raise ValueError('Camera comparison does not match context outline count')
    hits = {row['outline_id']: row for row in layer['matched_outlines']}
    with zipfile.ZipFile(archive) as bundle:
        files = [name for name in bundle.namelist() if name.lower().endswith('.tif')]
        if len(files) != 1:
            raise ValueError('Expected one original bathymetry GeoTIFF')
    records = []
    with rasterio.open(f'zip://{archive.resolve()}!{files[0]}') as grid:
        if grid.count != 1 or not grid.crs or any(abs(res - 2) > .01 for res in grid.res):
            raise ValueError('Unexpected native bathymetry grid')
        project = Transformer.from_crs('EPSG:4326', grid.crs, always_xy=True).transform
        for feature in context['features']:
            ident = feature['properties']['id']
            if feature['properties'].get('fishing_target') is not False:
                raise ValueError('Expected research context, not a fishing target')
            polygon = transform(project, shape(feature['geometry']))
            try:
                clipped, _ = mask(grid, [mapping(polygon)], crop=True, filled=False)
                values = clipped[0].compressed()
                values = values[np.isfinite(values)]
            except ValueError:
                values = np.array([], dtype='float32')
            row = hits.get(ident, {})
            item = {'context_id': ident, 'native_measured_cells': int(values.size),
                    'historical_camera_interior_windows': row.get('interior_windows', 0),
                    'historical_rock_boulder_windows': row.get('rock_boulder_cobble_windows', 0),
                    'historical_rockfish_positive_windows': row.get('rockfish_positive_windows', 0),
                    'distinct_historical_transects': row.get('distinct_transects', 0),
                    'depth_qualified_for_target': False}
            if values.size:
                # Original raster values are NAVD88 elevations in meters. The
                # conversion to positive-down depth here changes sign only.
                depth = -values.astype('float64')
                item['depth_m_below_navd88'] = {
                    'minimum': round(float(depth.min()), 2),
                    'p10': round(float(np.percentile(depth, 10)), 2),
                    'median': round(float(np.median(depth)), 2),
                    'p90': round(float(np.percentile(depth, 90)), 2),
                    'maximum': round(float(depth.max()), 2)}
            records.append(item)
    return {'schema_version': 1, 'scope': 'original-usgs-bathymetry-vs-habitat-context',
            'audited_at': datetime.now(timezone.utc).isoformat(),
            'source_id': source['id'], 'bathymetry_url': source['bathymetry_url'],
            'bathymetry_sha256': digest, 'native_resolution_m': 2,
            'vertical_datum': 'NAVD88', 'mllw_conversion_reviewed': False,
            'product_uncertainty_grid_available': False,
            'context_outlines': len(records),
            'outlines_with_original_measured_cells': sum(bool(row['native_measured_cells']) for row in records),
            'outlines_with_historical_camera_evidence': sum(bool(row['historical_camera_interior_windows']) for row in records),
            'fishing_target': False, 'exportable': False,
            'limitations': 'NAVD88 depth is not MLLW depth. No per-cell uncertainty was supplied with this source; hydrographic survey dates vary. Context boundaries are generalized and camera positions are variable. No navigation, legal 200 ft fishing depth, present fish abundance or catch likelihood is inferred.',
            'outlines': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-id', default='offshore-monterey-character-2016')
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--context', type=Path, default=Path('dist/data/usgs-offshore-monterey-hard-context.geojson'))
    parser.add_argument('--video', type=Path, default=Path('dist/data/usgs-offshore-monterey-video-overlap.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    catalog = json.loads(Path('catalog/usgs-seafloor-sources.json').read_text())
    source = next((row for row in catalog['sources'] if row['id'] == args.source_id), None)
    if source is None:
        raise ValueError('Unknown reviewed USGS source')
    result = audit(source, args.archive, json.loads(args.context.read_text()),
                   json.loads(args.video.read_text()), context_name=args.context.name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(f"{result['outlines_with_original_measured_cells']}/{result['context_outlines']} outlines with native measured cells; zero fishing targets")


if __name__ == '__main__':
    main()
