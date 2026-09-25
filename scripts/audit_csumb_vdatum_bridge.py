"""Probe NOAA VDatum for inspected CSUMB grids without converting their depths.

The original ArcInfo grid identifies NAD83/UTM10 and NAVD88 GEOID09, but does
not establish a horizontal realization or epoch. NOAA's West Coast tidal API
requires NAD83_2011. These point probes cannot bridge that missing identity.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API = 'https://vdatum.noaa.gov/vdatumweb/api/convert'
EXPECTED_IDS = {'csumb-scc-block04', 'csumb-scc-block05', 'csumb-scc-block06',
                'csumb-bss-block01', 'csumb-bss-block02', 'csumb-bss-block12', 'csumb-bss-block13'}


def request(lon, lat, frame, get=None):
    params = {'region': 'westcoast', 's_x': f'{lon:.7f}', 's_y': f'{lat:.7f}',
              's_z': '0', 's_h_frame': frame, 's_coor': 'geo',
              's_v_frame': 'NAVD88', 's_v_geoid': 'geoid09',
              's_v_elevation': 'height', 's_v_unit': 'm',
              't_h_frame': 'IGS14', 't_coor': 'geo',
              't_v_frame': 'MLLW', 't_v_elevation': 'height', 't_v_unit': 'm'}
    url = API + '?' + urlencode(params)
    if get is None:
        with urlopen(Request(url, headers={'Accept': 'application/json',
                                           'User-Agent': 'SkipperCast datum-source-review/1.0'}),
                     timeout=25) as response:
            if response.status != 200 or 'json' not in response.headers.get('Content-Type', '').lower():
                raise ValueError('VDatum did not return HTTP 200 JSON')
            raw = response.read(100_001)
        if len(raw) > 100_000:
            raise ValueError('VDatum response exceeded bound')
        payload = json.loads(raw)
    else:
        payload = get(params)
        raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    if not isinstance(payload, dict):
        raise ValueError('VDatum response is not a JSON object')
    return url, hashlib.sha256(raw).hexdigest(), payload


def assess(payload, lon, lat, frame):
    if payload.get('errorCode') is not None:
        return {'status': 'api_rejected', 'error_code': payload['errorCode'],
                'reason': str(payload.get('message', ''))[:180]}
    expected = {'region': 'WESTCOAST', 's_h_frame': frame, 's_v_frame': 'NAVD88',
                's_v_geoid': 'geoid09', 's_v_unit': 'm', 't_h_frame': 'IGS14',
                't_v_frame': 'MLLW', 't_v_unit': 'm'}
    if any(payload.get(key) != value for key, value in expected.items()):
        return {'status': 'invalid_response', 'reason': 'datum_echo_mismatch'}
    try:
        sx, sy = float(payload['s_x']), float(payload['s_y'])
        tx, ty = float(payload['t_x']), float(payload['t_y'])
        offset, uncertainty = float(payload['t_z']), float(payload['uncertainty'])
    except (KeyError, TypeError, ValueError):
        return {'status': 'unavailable', 'reason': 'missing_numeric_result'}
    if (not all(math.isfinite(v) for v in (sx, sy, tx, ty, offset, uncertainty))
            or abs(sx - lon) > 1e-5 or abs(sy - lat) > 1e-5
            or abs(tx - lon) > 0.01 or abs(ty - lat) > 0.01
            or offset <= -1e5 or abs(offset) > 20 or not 0 < uncertainty <= 20):
        return {'status': 'unavailable', 'reason': 'sentinel_or_coordinate_error'}
    return {'status': 'sample_available', 'offset_m': offset,
            'vdatum_uncertainty_m': uncertainty}


def compile_review(source_reviews, *, get=None):
    if (len(source_reviews) != 2
            or {review.get('scope') for review in source_reviews} != {
                'original-csumb-scc-native-grid-review', 'original-csumb-bss-native-grid-review'}):
        raise ValueError('Expected inspected SCC and BSS CSUMB grids')
    rows = [row for review in source_reviews for row in review.get('sources', [])]
    if len(rows) != len(EXPECTED_IDS) or {row.get('source_id') for row in rows} != EXPECTED_IDS:
        raise ValueError('Expected all inspected SCC and BSS blocks')
    samples = []
    for row in sorted(rows, key=lambda row: row['source_id']):
        bathy = row['bathymetry']
        if (row['native_vertical_datum'] != 'NAVD88 Geoid09'
                or bathy['crs'] != 'EPSG:26910' or bathy['resolution_m'] not in ([2.0, 2.0], [5.0, 5.0])
                or bathy['valid_cells'] <= 0 or not row['archive_sha256']):
            raise ValueError('CSUMB source CRS, resolution or archive identity changed')
        west, south, east, north = bathy['valid_cell_envelope_wgs84']
        lon, lat = round((west + east) / 2, 7), round((south + north) / 2, 7)
        url, digest, payload = request(lon, lat, 'NAD83_2011', get=get)
        samples.append({'source_id': row['source_id'], 'archive_sha256': row['archive_sha256'],
                        'sample_kind': 'raster-envelope-midpoint-not-verified-valid-cell',
                        'longitude': lon, 'latitude': lat, 'request_url': url,
                        'response_sha256': digest, **assess(payload, lon, lat, 'NAD83_2011')})
    first = samples[0]
    url, digest, payload = request(first['longitude'], first['latitude'], 'NAD83_1986', get=get)
    comparison = {'source_id': first['source_id'], 'request_url': url,
                  'response_sha256': digest,
                  **assess(payload, first['longitude'], first['latitude'], 'NAD83_1986')}
    return {'schema_version': 1, 'scope': 'csumb-original-navd88-geoid09-vdatum-bridge-review',
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'source_reviews': ['data/csumb-scc-native-source-review.json',
                               'data/csumb-bss-native-source-review.json'],
            'service_documentation_url': 'https://vdatum.noaa.gov/docs/services.html',
            'source_horizontal_crs': 'EPSG:26910 (NAD83 / UTM zone 10N)',
            'source_horizontal_realization_verified': False,
            'source_vertical_datum': 'NAVD88 Geoid09',
            'requested_tidal_horizontal_frame': 'IGS14',
            'samples': samples, 'alternative_horizontal_frame_probe': comparison,
            'mllw_raster_converted': False, 'depth_qualified': False,
            'fishing_target': False, 'exportable': False,
            'limitations': [
                'The native source identifies NAD83 / UTM 10 but not its realization or coordinate epoch; NAD83_2011 point results cannot yet be applied to those source pixels.',
                'A raster-envelope midpoint is not guaranteed to lie on a measured source cell, and point offsets cannot define a datum-correction field across the surveyed grids.',
                'VDatum uncertainty describes the transformation, not the original bathymetry product error; the source has no per-cell uncertainty band.',
                'Original substrate, MPAs, other closures, charts, routes, date-specific rules and fish evidence remain independent gates.',
            ]}


def stable(report):
    return {key: value for key, value in report.items() if key != 'checked_at'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scc-review', type=Path,
                        default=Path('dist/data/csumb-scc-native-source-review.json'))
    parser.add_argument('--bss-review', type=Path,
                        default=Path('dist/data/csumb-bss-native-source-review.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    result = compile_review([json.loads(args.scc_review.read_text()),
                             json.loads(args.bss_review.read_text())])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    if args.verify and stable(result) != stable(json.loads(args.verify.read_text())):
        raise SystemExit('VDatum or source identity changed; review before publishing')
    print(json.dumps({'samples': len(result['samples']),
                      'available': sum(x['status'] == 'sample_available' for x in result['samples']),
                      'depth_qualified': False}))


if __name__ == '__main__':
    main()
