"""Discover original NCEI multibeam *survey leads* in bounded California sectors.

The ArcGIS feature geometry is a ship trackline, not a measured-bottom polygon.
This inventory cannot create fishing targets or qualify a depth or substrate.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SERVICE = 'https://gis.ngdc.noaa.gov/arcgis/rest/services/web_mercator/multibeam_dynamic/MapServer/0'
FIELDS = ('OBJECTID', 'SURVEY_ID', 'PLATFORM', 'SURVEY_YEAR', 'SOURCE', 'NGDC_ID',
          'DOWNLOAD_URL', 'START_TIME', 'END_TIME', 'INSTRUMENT', 'FILE_COUNT')


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def fetch_json(url, parameters=None, *, timeout=30):
    full = url + ('?' + urlencode(parameters) if parameters else '')
    request = Request(full, headers={'User-Agent': 'SkipperCast source discovery (public NOAA catalog)'})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f'NCEI HTTP {response.status}')
        body = response.read(8_000_001)
    if len(body) > 8_000_000:
        raise ValueError('NCEI response exceeds the bounded payload limit')
    result = json.loads(body)
    if 'error' in result:
        raise ValueError(f'NCEI ArcGIS error: {result["error"].get("code")}')
    return result


def validate_config(config, sectors):
    if config.get('schema_version') != 1 or config.get('scope') != 'california-ncei-multibeam-trackline-discovery':
        raise ValueError('Wrong multibeam discovery configuration')
    if config.get('service_url') != SERVICE:
        raise ValueError('The NCEI service identity changed')
    rows = {row['id']: row for row in sectors['sectors']}
    searches = config.get('searches', [])
    if len(searches) != len(rows) or {x['sector_id'] for x in searches} != set(rows):
        raise ValueError('Every California sector needs exactly one search envelope')
    for entry in searches:
        box = entry['bbox_wgs84']
        low, high = rows[entry['sector_id']]['latitude']
        if (len(box) != 4 or box[1] != low or box[3] != high
                or not (-126 <= box[0] < box[2] <= -116) or not (32 <= low < high <= 42)):
            raise ValueError(f'Invalid NCEI search envelope: {entry["sector_id"]}')


def validate_service(metadata):
    names = {x.get('name') for x in metadata.get('fields', [])}
    if (metadata.get('name') != 'Multibeam Bathymetric Surveys'
            or metadata.get('geometryType') != 'esriGeometryPolyline'
            or not set(FIELDS) <= names
            or not metadata.get('advancedQueryCapabilities', {}).get('supportsPagination')):
        raise ValueError('NCEI multibeam layer schema changed; review before reusing leads')


def normalize_feature(feature):
    row = feature.get('attributes', {})
    ident = row.get('OBJECTID')
    survey = row.get('SURVEY_ID')
    link = row.get('DOWNLOAD_URL')
    if not isinstance(ident, int) or ident <= 0 or not isinstance(survey, str) or not survey.strip():
        raise ValueError('NCEI feature is missing its original survey identity')
    if link is not None and (not isinstance(link, str) or urlsplit(link).scheme != 'https' or
                             urlsplit(link).hostname not in ('www.ngdc.noaa.gov', 'ngdc.noaa.gov', 'www.ncei.noaa.gov')):
        raise ValueError(f'Unexpected NCEI survey link: {ident}')
    year = row.get('SURVEY_YEAR')
    if year is not None and (not isinstance(year, (float, int)) or not 1900 <= year <= 2100):
        raise ValueError(f'Invalid NCEI survey year: {ident}')
    return {'object_id': ident, 'survey_id': survey.strip(), 'source_organization': row.get('SOURCE'),
            'platform': row.get('PLATFORM'), 'survey_year': int(year) if year is not None else None,
            'catalog_id': row.get('NGDC_ID'), 'survey_page_url': link,
            'start_time_unix_ms': row.get('START_TIME'), 'end_time_unix_ms': row.get('END_TIME'),
            'instrument': row.get('INSTRUMENT'), 'file_count': row.get('FILE_COUNT')}


def collect_sector(entry, *, get=fetch_json):
    box = entry['bbox_wgs84']
    query = SERVICE + '/query'
    common = {'f': 'json', 'where': '1=1', 'geometry': ','.join(map(str, box)),
              'geometryType': 'esriGeometryEnvelope', 'inSR': '4326',
              'spatialRel': 'esriSpatialRelIntersects'}
    count = get(query, {**common, 'returnCountOnly': 'true'}).get('count')
    ids = get(query, {**common, 'returnIdsOnly': 'true'}).get('objectIds')
    if not isinstance(count, int) or count < 0 or not isinstance(ids, list) or any(not isinstance(i, int) for i in ids):
        raise ValueError('NCEI count or object-ID response is incomplete')
    if len(ids) != count or len(set(ids)) != count:
        raise ValueError('NCEI count and unique object IDs disagree')
    rows = []
    for start in range(0, len(ids), 200):
        batch = ids[start:start + 200]
        response = get(query, {'f': 'json', 'where': '1=1', 'objectIds': ','.join(map(str, batch)),
                               'outFields': ','.join(FIELDS), 'returnGeometry': 'false'})
        if response.get('exceededTransferLimit'):
            raise ValueError('NCEI transfer limit truncated a survey batch')
        rows.extend(normalize_feature(feature) for feature in response.get('features', []))
    if {row['object_id'] for row in rows} != set(ids) or len(rows) != count:
        raise ValueError('NCEI survey batch omitted or duplicated an object ID')
    rows.sort(key=lambda row: (row['survey_year'] or 0, row['survey_id'], row['object_id']), reverse=True)
    return {'sector_id': entry['sector_id'], 'search_bbox_wgs84': box, 'trackline_matches': count,
            'surveys': rows}


def collect(config, sectors, *, get=fetch_json, only_sector=None):
    validate_config(config, sectors)
    metadata = get(SERVICE, {'f': 'pjson'})
    validate_service(metadata)
    schema_hash = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    searches = [x for x in config['searches'] if not only_sector or x['sector_id'] == only_sector]
    if not searches:
        raise ValueError('Unknown California sector')
    results = [collect_sector(entry, get=get) for entry in searches]
    survey_catalog = {}
    sector_results = []
    for result in results:
        sector_results.append({key: value for key, value in result.items() if key != 'surveys'} |
                              {'survey_object_ids': [row['object_id'] for row in result['surveys']]})
        for row in result['surveys']:
            old = survey_catalog.setdefault(row['object_id'], row)
            if old != row:
                raise ValueError(f'NCEI survey metadata changed across sectors: {row["object_id"]}')
    collected_at = utc_now()
    return {'schema_version': 1, 'scope': config['scope'], 'status': 'ok',
            'collected_at': collected_at, 'last_complete_scan_at': collected_at,
            'source_url': SERVICE, 'service_schema_sha256': schema_hash,
            'method': 'Complete ArcGIS count and unique ID audit per bounded sector envelope; then fetch original survey metadata by ID in batches. Trackline intersects are discovery leads, not surveyed polygons.',
            'limitations': config['notes'], 'sectors': sector_results,
            'survey_catalog': list(sorted(survey_catalog.values(), key=lambda row: row['object_id'])),
            'total_sector_associations': sum(row['trackline_matches'] for row in results),
            'unique_survey_object_ids': len(survey_catalog)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'catalog/ncei-multibeam-search.json')
    parser.add_argument('--sectors', type=Path, default=ROOT / 'catalog/coastal-sectors.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--only-sector')
    args = parser.parse_args()
    data = collect(json.loads(args.config.read_text()), json.loads(args.sectors.read_text()),
                   only_sector=args.only_sector)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temp.replace(args.output)
    print(json.dumps({'status': data['status'], 'sectors': len(data['sectors']),
                      'associations': data['total_sector_associations'],
                      'unique_surveys': data['unique_survey_object_ids']}))


if __name__ == '__main__':
    main()
