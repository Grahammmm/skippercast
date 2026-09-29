#!/usr/bin/env python3
"""Audit original Estero WGS84(G1150) ellipsoid cells against direct VDatum.

This is a nominal, block-center diagnostic. It never certifies a full 300 ft
footprint, product TPU, independent seabed registration, or fishing access.
"""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.windows import from_bounds
from shapely.geometry import shape

from research.scripts.audit_usgs_estero_2012_original import ARCHIVES, METADATA


ROOT = Path(__file__).resolve().parents[2]
API = 'https://vdatum.noaa.gov/vdatumweb/api/convert'
EPOCH = '2012.6'  # Approximate survey midpoint; output coordinate epoch unverified.
FEET_PER_METER = 3.280839895


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def check_inputs(blocks, archive, metadata):
    if (blocks.get('scope') != 'private-estero-nominal-research-blocks'
            or blocks.get('crs') != 'EPSG:32610'
            or len(blocks.get('features', [])) != 60
            or digest(archive) != ARCHIVES['WGS84_utm10_EsteroBay.zip']
            or digest(metadata) != METADATA['WGS84_metadata_EsteroBay.xml']):
        raise ValueError('Original WGS84 source or private research blocks changed')
    source = metadata.read_text(errors='replace')
    if ('<utmzone>10</utmzone>' not in source
            or '<horizdn>World Geodetic System 1984 (G1150)</horizdn>' not in source
            or '<altdatum>World Geodetic System 1984 (G1150)</altdatum>' not in source
            or 'WGS84 (G1150) ellipsoid' not in source):
        raise ValueError('Original source ellipsoid-height declaration changed')
    fingerprints = []
    for feature in blocks['features']:
        geom = shape(feature['geometry'])
        if (not geom.is_valid or abs(geom.area - 10_000) > 0.1
                or feature.get('properties', {}).get('band') not in ('200-250ft', '250-300ft')
                or feature['properties'].get('fishing_target') is not False):
            raise ValueError('Private research-block geometry changed')
        fingerprints.append((tuple(round(v, 3) for v in geom.bounds),
                             feature['properties']['band']))
    if len({bounds for bounds, _ in fingerprints}) != 60:
        raise ValueError('Duplicate private research footprints')
    return hashlib.sha256(json.dumps(sorted(fingerprints)).encode()).hexdigest()


def vdatum_point(x, y, *, get=None):
    lon, lat = Transformer.from_crs('EPSG:32610', 'EPSG:4326', always_xy=True).transform(x, y)
    params = {'region': 'westcoast', 's_x': f'{lon:.8f}', 's_y': f'{lat:.8f}',
              's_z': '0', 's_h_frame': 'WGS84_G1150', 's_coor': 'geo',
              's_v_frame': 'WGS84_G1150', 's_v_unit': 'm',
              't_h_frame': 'IGS14', 't_coor': 'geo', 't_v_frame': 'MLLW',
              't_v_unit': 'm', 'epoch_in': EPOCH, 'epoch_out': EPOCH}
    url = API + '?' + urlencode(params)
    if get is None:
        with urlopen(Request(url, headers={'Accept': 'application/json',
                                           'User-Agent': 'SkipperCast Estero original-datum audit/1.0'}),
                     timeout=25) as response:
            if response.status != 200 or 'json' not in response.headers.get('Content-Type', '').lower():
                raise ValueError('NOAA VDatum did not return HTTP 200 JSON')
            data = json.load(response)
    else:
        data = get(params)
    expected = {'region': 'WESTCOAST', 's_h_frame': 'WGS84_G1150',
                's_v_frame': 'WGS84_G1150', 't_h_frame': 'IGS14',
                't_v_frame': 'MLLW', 'epoch_in': EPOCH, 'epoch_out': EPOCH}
    if data.get('errorCode') is not None or any(data.get(k) != v for k, v in expected.items()):
        raise ValueError('NOAA VDatum rejected or changed the requested frame')
    try:
        values = [float(data[k]) for k in ('s_x', 's_y', 't_x', 't_y', 't_z', 'uncertainty')]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('NOAA VDatum result is incomplete') from exc
    sx, sy, tx, ty, offset, uncertainty = values
    if (not all(math.isfinite(v) for v in values) or abs(sx - lon) > 1e-5
            or abs(sy - lat) > 1e-5 or abs(tx - lon) > .01 or abs(ty - lat) > .01
            or not 20 < offset < 50 or not 0 < uncertainty < 5):
        raise ValueError('NOAA VDatum result has sentinel values or wrong coordinates')
    return {'longitude': round(lon, 8), 'latitude': round(lat, 8),
            'request_url': url, 'response': data, 'offset_m': offset,
            'transform_uncertainty_m': uncertainty}


def source_cells(blocks, archive, points):
    member = 'wgs84_utm10_esterobay.asc'
    path = f'/vsizip/{archive.resolve()}/{member}'
    totals = defaultdict(lambda: {'blocks': 0, 'valid_source_cells': 0,
                                   'nominal_center_offset_200_300ft_cells': 0,
                                   'source_ellipsoid_min_m': None, 'source_ellipsoid_max_m': None})
    private = []
    with rasterio.open(path) as grid:
        if (grid.shape != (16020, 11456) or tuple(grid.res) != (2.0, 2.0)
                or grid.nodata != -9999 or grid.bounds.left != 665810
                or grid.bounds.bottom != 3900238):
            raise ValueError('Original WGS84 ASCII grid layout changed')
        for index, (feature, point) in enumerate(zip(blocks['features'], points)):
            bounds = shape(feature['geometry']).bounds
            window = from_bounds(*bounds, transform=grid.transform).round_offsets().round_lengths()
            vals = grid.read(1, window=window, masked=True).compressed()
            band = feature['properties']['band']
            row = totals[band]
            row['blocks'] += 1
            row['valid_source_cells'] += int(vals.size)
            if vals.size:
                depths_ft = -(vals.astype('float64') + point['offset_m']) * FEET_PER_METER
                nominal = int(np.count_nonzero((depths_ft >= 200) & (depths_ft < 300)))
                row['nominal_center_offset_200_300ft_cells'] += nominal
                lo, hi = float(np.min(vals)), float(np.max(vals))
                row['source_ellipsoid_min_m'] = lo if row['source_ellipsoid_min_m'] is None else min(lo, row['source_ellipsoid_min_m'])
                row['source_ellipsoid_max_m'] = hi if row['source_ellipsoid_max_m'] is None else max(hi, row['source_ellipsoid_max_m'])
            else:
                nominal = 0
            private.append({'block_index': index, 'band': band,
                            'valid_source_cells': int(vals.size),
                            'nominal_center_offset_200_300ft_cells': nominal,
                            'vdatum': point})
    return dict(sorted(totals.items())), private


def audit(blocks, archive, metadata, *, get=None):
    block_fingerprint = check_inputs(blocks, archive, metadata)
    centers = [shape(f['geometry']).centroid for f in blocks['features']]
    with ThreadPoolExecutor(max_workers=4) as pool:
        points = list(pool.map(lambda p: vdatum_point(p.x, p.y, get=get), centers))
    bands, private = source_cells(blocks, archive, points)
    offsets = [p['offset_m'] for p in points]
    errors = [p['transform_uncertainty_m'] for p in points]
    report = {'schema_version': 1, 'scope': 'estero-2012-original-wgs84-direct-vdatum-research',
              'checked_at': datetime.now(timezone.utc).isoformat(),
              'source_url': 'https://pubs.usgs.gov/of/2013/1225/data/WGS84_utm10_EsteroBay.zip',
              'metadata_url': 'https://pubs.usgs.gov/of/2013/1225/metadata/WGS84_metadata_EsteroBay.xml',
              'source_archive_sha256': ARCHIVES['WGS84_utm10_EsteroBay.zip'],
              'source_metadata_sha256': METADATA['WGS84_metadata_EsteroBay.xml'],
              'private_block_fingerprint': block_fingerprint,
              'source_horizontal_frame': 'WGS84(G1150) / UTM zone 10N (metadata)',
              'source_vertical_frame': 'WGS84(G1150) ellipsoid height (metadata)',
              'api_target': 'IGS14 / MLLW',
              'api_epoch_assumption': EPOCH,
              'sample_kind': 'one VDatum point at the center of each 100 m research block',
              'sample_count': len(points),
              'offset_m': {'minimum': min(offsets), 'maximum': max(offsets)},
              'vdatum_transform_uncertainty_m': {'minimum': min(errors), 'maximum': max(errors)},
              'by_prior_nominal_band': bands,
              'source_product_upper_uncertainty_verified': False,
              'full_cellwise_mllw_surface_verified': False,
              'independent_habitat_registration_verified': False,
              'qualified_waypoints': 0, 'fishing_target': False, 'exportable': False,
              'limitations': [
                  'The original USGS WGS84(G1150) ellipsoid-height grid can be queried directly through NOAA VDatum, avoiding the separate NAD83(CORS96) raster bridge.',
                  'The 2012.6 API epoch is a survey-midpoint assumption; the source raster does not specify a per-pixel coordinate epoch.',
                  'One VDatum offset per 100 m block provides nominal cell counts only, not a validated correction at every populated 2 m cell or its upper error.',
                  'VDatum transformation uncertainty and within-cell sounding spread do not establish the original CARIS bathymetry total propagated uncertainty.',
                  'The 2008 independent character raster still needs a horizontal registration-error analysis against these 2012 WGS84 cells.',
                  'Full legal, MPA, chart, route and current species checks are separate release gates; these research blocks are not fishing targets.',
              ]}
    return report, {'checked_at': report['checked_at'], 'scope': 'private-estero-direct-vdatum-blocks',
                    'blocks': private}


def stable(report):
    return {k: v for k, v in report.items() if k != 'checked_at'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--blocks', type=Path, default=ROOT / 'var/review/estero-nominal-research-blocks.geojson')
    p.add_argument('--archive', type=Path, default=ROOT / 'var/review/estero-bay-2012/WGS84_utm10_EsteroBay.zip')
    p.add_argument('--metadata', type=Path, default=ROOT / 'var/review/estero-bay-2012/WGS84_metadata_EsteroBay.xml')
    p.add_argument('--output', type=Path, default=ROOT / 'research/receipts/estero-wgs84-direct-vdatum-review.json')
    p.add_argument('--private', type=Path, default=ROOT / 'var/review/estero-wgs84-direct-vdatum-blocks.json')
    p.add_argument('--verify', type=Path)
    args = p.parse_args()
    report, private = audit(json.loads(args.blocks.read_text()), args.archive, args.metadata)
    if args.verify and stable(report) != stable(json.loads(args.verify.read_text())):
        raise SystemExit('Original Estero direct VDatum evidence changed; review before publishing')
    for path in (args.output, args.private):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    args.private.write_text(json.dumps(private, indent=2) + '\n')
    print(json.dumps({'samples': report['sample_count'],
                      'qualified_waypoints': report['qualified_waypoints']}))


if __name__ == '__main__':
    main()
