"""Audit exact USGS Cal DIG I v2 native files before any regional fishing use.

The output is source triage, not a fishing-target or chartplotter layer.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile

import numpy as np
from pyproj import CRS, Transformer
import rasterio
import shapefile


ROOT = Path(__file__).resolve().parents[1]


def file_hash(path):
    digest = sha256()
    with path.open('rb') as source:
        for part in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def acquire(kind, spec, cache, fetch):
    path = cache / f'Cal_DIG_I_v2_{"Bathymetry" if kind == "bathymetry" else "CMECS"}.zip'
    if not path.exists():
        if not fetch:
            raise FileNotFoundError(path)
        parsed = urlparse(spec['url'])
        if parsed.scheme != 'https' or parsed.hostname != 'cmgds.marine.usgs.gov':
            raise ValueError('Unreviewed USGS source host')
        cache.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix('.partial')
        try:
            request = Request(spec['url'], headers={'User-Agent': 'SkipperCast USGS original-data audit/1.0'})
            with urlopen(request, timeout=180) as response, partial.open('wb') as output:
                if response.status != 200 or urlparse(response.url).hostname != parsed.hostname:
                    raise ValueError('USGS archive redirected outside reviewed host')
                if int(response.headers.get('Content-Length', '-1')) != spec['bytes']:
                    raise ValueError('USGS archive size changed')
                while part := response.read(1024 * 1024):
                    output.write(part)
            if partial.stat().st_size != spec['bytes'] or file_hash(partial) != spec['sha256']:
                raise ValueError('Original USGS archive incomplete or changed')
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    if path.stat().st_size != spec['bytes'] or file_hash(path) != spec['sha256']:
        raise ValueError('Cached USGS archive does not match the pinned original')
    return path


def inspect_bathymetry(path, spec, manifest):
    with zipfile.ZipFile(path) as archive:
        member = archive.getinfo(spec['member'])
        if member.file_size > 1_000_000_000:
            raise ValueError('Original bathymetry GeoTIFF exceeds inspected size cap')
    address = f'zip://{path.resolve()}!{spec["member"]}'
    with rasterio.open(address) as grid:
        if (str(grid.crs) != manifest['expected_crs'] or list(grid.res) !=
                [manifest['expected_resolution_m']] * 2 or grid.count != 1):
            raise ValueError('Original bathymetry grid geometry changed')
        minimum, maximum = float('inf'), float('-inf')
        valid = within_200 = within_300 = 0
        for _, window in grid.block_windows(1):
            cells = grid.read(1, window=window, masked=True).compressed()
            if not cells.size:
                continue
            if not np.isfinite(cells).all():
                raise ValueError('Original bathymetry contains non-finite valid cells')
            valid += cells.size
            minimum = min(minimum, float(cells.min()))
            maximum = max(maximum, float(cells.max()))
            within_200 += int(np.count_nonzero((cells < 0) & (cells >= -60.96)))
            within_300 += int(np.count_nonzero((cells < 0) & (cells >= -91.44)))
        if not valid:
            raise ValueError('Original bathymetry has no measured cells')
        return {'archive_sha256': spec['sha256'], 'member': spec['member'],
                'crs': str(grid.crs), 'resolution_m': list(grid.res),
                'raster_bounds_native': list(grid.bounds),
                'valid_cells': int(valid), 'minimum_elevation_m': minimum,
                'maximum_elevation_m': maximum,
                'candidate_200ft_cells': within_200, 'candidate_300ft_cells': within_300,
                'depth_note': 'Negative elevations in the original source vertical reference are not charted MLLW depths.'}


def inspect_cmecs(path, spec):
    stem = spec['member_stem']
    with zipfile.ZipFile(path) as archive:
        for suffix in ('.shp', '.shx', '.dbf', '.prj'):
            archive.getinfo(stem + suffix)
        if archive.getinfo(stem + '.shp').file_size > 200_000_000:
            raise ValueError('Original CMECS geometry exceeds inspected size cap')
        source_crs = CRS.from_wkt(archive.read(stem + '.prj').decode())
        if source_crs.to_epsg() != 4269:
            raise ValueError('Original CMECS geographic datum changed')
        reader = shapefile.Reader(shp=io.BytesIO(archive.read(stem + '.shp')),
                                  shx=io.BytesIO(archive.read(stem + '.shx')),
                                  dbf=io.BytesIO(archive.read(stem + '.dbf')))
        fields = {item[0] for item in reader.fields[1:]}
        if not {'SubstrDesc', 'GeofrmDesc', 'BtcGrpDesc', 'Area'} <= fields:
            raise ValueError('Original CMECS attributes changed')
        count = Counter()
        area = defaultdict(float)
        for record in reader.iterRecords():
            row = record.as_dict()
            label = row['SubstrDesc']
            if not label or not isinstance(row['Area'], (float, int)) or row['Area'] < 0:
                raise ValueError('Original CMECS substrate or area is invalid')
            count[label] += 1
            area[label] += row['Area']
        if sum(count.values()) != len(reader):
            raise ValueError('Original CMECS records are incomplete')
        wgs84_bounds = Transformer.from_crs(source_crs, 'EPSG:4326', always_xy=True).transform_bounds(*reader.bbox)
        return {'archive_sha256': spec['sha256'], 'polygon_count': len(reader),
                'source_crs': 'EPSG:4269', 'bounds_geographic_nad83': list(reader.bbox),
                'bounds_wgs84': list(wgs84_bounds),
                'substrate_counts': dict(sorted(count.items())),
                'substrate_area_m2': {key: round(area[key], 2) for key in sorted(area)},
                'bedrock_polygons': count['Bedrock'],
                'interpretation': 'Historical video-supervised classes; polygon count is not a number of fishing locations.'}


def audit(manifest, cache, fetch=False):
    if manifest.get('schema_version') != 1 or manifest.get('id') != 'usgs-caldig-i-v2-2026':
        raise ValueError('Unexpected USGS Cal DIG manifest identity')
    archives = manifest['archives']
    bathy = inspect_bathymetry(acquire('bathymetry', archives['bathymetry'], cache, fetch),
                               archives['bathymetry'], manifest)
    cmecs = inspect_cmecs(acquire('cmecs', archives['cmecs'], cache, fetch), archives['cmecs'])
    return {'schema_version': 1, 'source_id': manifest['id'],
            'collected_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'release_url': manifest['release_url'], 'publication_date': manifest['publication_date'],
            'sector_ids': manifest['sector_ids'], 'source_use': 'deepwater habitat research context only',
            'bottom_target_status': 'not-qualified' if bathy['candidate_300ft_cells'] == 0 else 'needs-local-review',
            'reason': 'No native elevation cell within even a nominal 300-foot depth range.'
                      if bathy['candidate_300ft_cells'] == 0 else 'Native candidate cells need chart-datum and full legal review.',
            'bathymetry': bathy, 'cmecs': cmecs, 'rights': manifest['rights'],
            'limitations': manifest['limitations']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'catalog/usgs-caldig-v2.json')
    parser.add_argument('--cache', type=Path, default=ROOT / 'var/usgs-dig-cache')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/data/usgs-caldig-v2-native-review.json')
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    result = audit(json.loads(args.manifest.read_text()), args.cache, args.fetch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.partial')
    temporary.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    temporary.replace(args.output)
    print(json.dumps({'status': result['bottom_target_status'],
                      'valid_cells': result['bathymetry']['valid_cells'],
                      'polygons': result['cmecs']['polygon_count']}))


if __name__ == '__main__':
    main()
