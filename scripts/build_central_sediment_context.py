"""Compile official USGS central-coast sediment-thickness context.

The 50 m seismic interpretation is useful for broad geology review only.
No polygon from this adapter is a fishing target, depth check or waypoint.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.features import shapes
from rasterio.warp import transform_bounds
from scipy.ndimage import label
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_usgs_statewide_context import mpa_union


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def download_missing(url, path, expected_sha256, maximum_bytes):
    """Fetch a missing pinned original; changed provider bytes require review."""
    if path.is_file():
        if digest(path) != expected_sha256:
            raise ValueError('Existing original USGS download digest changed')
        return
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'www.sciencebase.gov':
        raise ValueError('Unapproved original USGS download host')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    size = 0
    h = hashlib.sha256()
    try:
        with urlopen(Request(url, headers={'User-Agent': 'SkipperCast-source-review/1.0'}), timeout=90) as source, temporary.open('wb') as target:
            if urlsplit(source.url).scheme != 'https':
                raise ValueError('Original USGS download redirected outside HTTPS')
            for block in iter(lambda: source.read(1024 * 1024), b''):
                size += len(block)
                if size > maximum_bytes:
                    raise ValueError('Original USGS download exceeded size bound')
                h.update(block)
                target.write(block)
        if h.hexdigest() != expected_sha256:
            raise ValueError('Original USGS provider bytes changed; human review required')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_source(manifest, archive, metadata):
    if (manifest.get('id') != 'usgs-point-sur-arguello-sediment-thickness-2019'
            or digest(archive) != manifest['archive_sha256']
            or digest(metadata) != manifest['metadata_sha256']):
        raise ValueError('Original USGS source or pinned metadata digest changed')
    root = ET.parse(metadata).getroot()
    checks = {
        './/idinfo/citation/citeinfo/pubdate': '2019',
        './/eainfo/detailed/attr/attrdomv/rdom/attrunit': 'meters',
        './/spref/horizsys/planar/gridsys/utm/utmzone': '10',
    }
    for path, expected in checks.items():
        if root.findtext(path) != expected:
            raise ValueError('Original USGS XML semantics changed: ' + path)
    if ('Sediment Thickness' not in root.findtext('.//idinfo/citation/citeinfo/title', '')
            or 'public domain' not in root.findtext('.//idinfo/useconst', '').lower()):
        raise ValueError('Original USGS publication/rights are unreviewed')
    with zipfile.ZipFile(archive) as bundle:
        name = manifest['raster_member']
        members = [item.filename for item in bundle.infolist() if item.filename.lower().endswith('.tif')]
        if members != [name] or hashlib.sha256(bundle.read(name)).hexdigest() != manifest['raster_sha256']:
            raise ValueError('Original USGS GeoTIFF member changed')


def thin_mask(values, nodata, maximum_m):
    data = np.asarray(values.data, dtype='float32')
    valid = ~np.ma.getmaskarray(values) & np.isfinite(data)
    if nodata is not None:
        valid &= data != nodata
    negative = valid & (data < 0)
    thin = valid & (data >= 0) & (data <= maximum_m)
    return thin, int(np.count_nonzero(negative)), int(np.count_nonzero(valid))


def polygon_parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == 'Polygon':
        return [geometry]
    if hasattr(geometry, 'geoms'):
        return [part for child in geometry.geoms for part in polygon_parts(child)]
    return []


def display_parts(original, excluded, minimum_area_m2):
    """Generalize source cells before applying the exact protected-area cut."""
    return [part for part in polygon_parts(original.simplify(50, preserve_topology=True).difference(excluded))
            if part.is_valid and part.area >= minimum_area_m2]


def build(manifest, archive, metadata, mpas, sectors):
    validate_source(manifest, archive, metadata)
    if mpas.get('scope') != 'california-coast-directory' or len(sectors) < 19:
        raise ValueError('Complete statewide MPA snapshot and sectors are required')
    excluded_geo = mpa_union(mpas)
    path = f"zip://{archive.resolve()}!{manifest['raster_member']}"
    with rasterio.open(path) as raster:
        if (raster.count != 1 or raster.crs != CRS.from_epsg(32610)
                or not all(abs(v - manifest['native_resolution_m']) < .001 for v in raster.res)
                or raster.width < 3000 or raster.height < 4000):
            raise ValueError('Original USGS raster grid/CRS changed')
        bounds_geo = transform_bounds(raster.crs, 'EPSG:4326', *raster.bounds, densify_pts=21)
        if not (-122.1 < bounds_geo[0] < -121.8 and 34.2 < bounds_geo[1] < 34.7
                and -120.3 < bounds_geo[2] < -119.9 and 36.1 < bounds_geo[3] < 36.6):
            raise ValueError('Original USGS raster bounds changed')
        values = raster.read(1, masked=True)
        thin, negative_count, valid_count = thin_mask(values, raster.nodata,
                                                       manifest['screening_threshold_m'])
        components, _ = label(thin)
        sizes = np.bincount(components.ravel())
        min_cells = math.ceil(manifest['minimum_display_area_m2'] / (raster.res[0] * raster.res[1]))
        retained = np.flatnonzero(sizes >= min_cells)
        retained = retained[retained != 0]
        selected = np.isin(components, retained)
        to_native = Transformer.from_crs('EPSG:4326', raster.crs, always_xy=True).transform
        to_geo = Transformer.from_crs(raster.crs, 'EPSG:4326', always_xy=True).transform
        local_mpas = excluded_geo.intersection(box(*bounds_geo).buffer(.02))
        excluded = transform(to_native, local_mpas).buffer(100) if not local_mpas.is_empty else box(0, 0, 0, 0)
        features = []
        for geometry, component in shapes(components.astype('int32'), mask=selected,
                                          transform=raster.transform):
            if component == 0 or component not in retained:
                continue
            original = shape(geometry)
            if original.area < manifest['minimum_display_area_m2']:
                continue
            # Simplify the broad raster edge first, then apply the unsimplified
            # protected-area exclusion so display geometry cannot reenter it.
            for part in display_parts(original, excluded, manifest['minimum_display_area_m2']):
                geographic = transform(to_geo, part)
                sector_ids = [s['id'] for s in sectors if geographic.intersects(box(*s['bounds']))]
                if not sector_ids:
                    continue
                features.append({'type': 'Feature', 'geometry': mapping(geographic), 'properties': {
                    'id': f'USGS-THIN-{len(features)+1:03d}',
                    'sector_ids': sector_ids, 'kind': 'estimated-thin-sediment',
                    'estimated_sediment_thickness_m': [0, manifest['screening_threshold_m']],
                    'approx_area_km2': round(part.area / 1e6, 3),
                    'native_resolution_m': manifest['native_resolution_m'],
                    'source_id': manifest['id'], 'fishing_target': False,
                    'exportable': False, 'depth_qualified': False, 'fish_confirmed': False}})
    return {'type': 'FeatureCollection', 'schema_version': 1,
            'scope': 'usgs-central-interpreted-sediment-context',
            'compiled_at': datetime.now(timezone.utc).isoformat(),
            'source': {'id': manifest['id'], 'publication_url': manifest['publication_url'],
                       'archive_url': manifest['archive_url'],
                       'archive_sha256': manifest['archive_sha256'],
                       'raster_sha256': manifest['raster_sha256'],
                       'metadata_url': manifest['metadata_url'],
                       'metadata_sha256': manifest['metadata_sha256'],
                       'publication_year': manifest['publication_year'],
                       'attribution': 'U.S. Geological Survey, Johnson and others (2019), DS 781'},
            'method': 'Original 50 m interpolated sediment-thickness raster; retain 0–2.5 m cells in connected patches >=0.5 km²; exclude negative interpolation artifacts; clip current complete CDFW MPAs with 100 m buffer; simplify display boundary at 50 m.',
            'screen': {'valid_source_cells': valid_count,
                       'negative_source_cells_excluded': negative_count,
                       'thin_cells_before_area_filter': int(np.count_nonzero(thin)),
                       'large_connected_components': len(retained),
                       'mpa_retrieved_at': mpas['sources']['mpas']['data_retrieved_at']},
            'limitations': manifest['limitations'] + [
                'Only a broad historical geology context layer. MPAs were screened at compilation; users must check current legal boundaries and method-specific restrictions.',
                'The layer never enters fishing scores, suggested points, plans or chartplotter exports.'],
            'features': features}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, default=Path('catalog/usgs-central-sediment-source.json'))
    p.add_argument('--archive', type=Path, default=Path('var/sediment-point-sur-arguello.zip'))
    p.add_argument('--metadata', type=Path, default=Path('var/sediment-point-sur-arguello-metadata.xml'))
    p.add_argument('--download-missing', action='store_true')
    p.add_argument('--mpas', type=Path, required=True)
    p.add_argument('--sectors', type=Path, default=Path('dist/data/coastal-sectors.json'))
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    manifest = json.loads(a.manifest.read_text())
    if a.download_missing:
        download_missing(manifest['archive_url'], a.archive, manifest['archive_sha256'], 20_000_000)
        download_missing(manifest['metadata_url'], a.metadata, manifest['metadata_sha256'], 1_000_000)
    result = build(manifest, a.archive, a.metadata,
                   json.loads(a.mpas.read_text()), json.loads(a.sectors.read_text())['sectors'])
    a.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = a.output.with_suffix(a.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    temporary.replace(a.output)
    print(json.dumps({'context_areas': len(result['features']), 'screen': result['screen']}))


if __name__ == '__main__':
    main()
