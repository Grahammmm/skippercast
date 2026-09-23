"""Discover NOAA BAG survey leads for every California coastal sector.

This is catalog discovery, not bathymetric ingestion or fishing-ground qualification.
The ArcGIS service's intersecting footprint cannot establish native resolution, datum,
uncertainty, substrate, redistribution rights for derivatives, or actual target coverage.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SERVICE = 'https://gis.ngdc.noaa.gov/arcgis/rest/services/web_mercator/nos_hydro_dynamic/MapServer/0/query'
FIELDS = 'SURVEY_ID,LOCALITY,SURVEY_YEAR,BAGS_EXIST,DOWNLOAD_URL'
SURVEY_ID = re.compile(r'^[A-Z][0-9]{5}$')


def fetch(url):
    request = Request(url, headers={'User-Agent': 'SkipperCast survey catalog discovery/1.0'})
    with urlopen(request, timeout=25) as response:
        raw = response.read(3_000_001)
        if len(raw) > 3_000_000:
            raise ValueError('NOAA survey response exceeds bounded size')
    return raw


def scan(sectors, previous=None, *, now=None, fetcher=fetch):
    now = now or datetime.now(timezone.utc)
    prior = {row['sector_id']: row for row in (previous or {}).get('sectors', [])}
    rows = []
    for sector in sectors:
        west, south, east, north = sector['bounds']
        query = {'where': '1=1', 'geometry': f'{west},{south},{east},{north}',
                 'geometryType': 'esriGeometryEnvelope', 'inSR': '4326',
                 'spatialRel': 'esriSpatialRelIntersects', 'outFields': FIELDS,
                 'returnGeometry': 'false', 'f': 'json'}
        url = SERVICE + '?' + urlencode(query)
        try:
            raw = fetcher(url)
            data = json.loads(raw)
            if data.get('error') or data.get('exceededTransferLimit') or not isinstance(data.get('features'), list):
                raise ValueError('NOAA survey query failed or returned an incomplete page')
            if len(data['features']) >= 2000:
                raise ValueError('NOAA survey page reached the service record limit')
            surveys = {}
            for feature in data['features']:
                item = feature.get('attributes') or {}
                ident = item.get('SURVEY_ID')
                if not isinstance(ident, str) or not SURVEY_ID.fullmatch(ident) or item.get('BAGS_EXIST') != 'Y':
                    continue
                source_url = item.get('DOWNLOAD_URL')
                if not isinstance(source_url, str) or urlsplit(source_url).scheme != 'https' or urlsplit(source_url).hostname not in {'www.ngdc.noaa.gov', 'www.ncei.noaa.gov'}:
                    continue
                year = item.get('SURVEY_YEAR')
                surveys[ident] = {'id': ident, 'year': year if isinstance(year, int) and 1800 <= year <= now.year else None,
                                  'locality': str(item.get('LOCALITY') or '')[:160], 'catalog_url': source_url}
            rows.append({'sector_id': sector['id'], 'status': 'ok', 'retrieved_at': now.isoformat(),
                         'request_url': url, 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                         'surveys': sorted(surveys.values(), key=lambda item: item['id']), 'issue': None})
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            older = prior.get(sector['id'])
            rows.append({'sector_id': sector['id'], 'status': 'retained' if older and older.get('surveys') else 'failed',
                         'retrieved_at': older.get('retrieved_at') if older else None,
                         'request_url': url, 'raw_sha256': older.get('raw_sha256') if older else None,
                         'surveys': older.get('surveys', []) if older else [], 'issue': str(error)[:250]})
    failures = [row['sector_id'] for row in rows if row['status'] != 'ok']
    complete = not failures
    distinct = {item['id'] for row in rows for item in row['surveys']}
    return {'schema_version': 1, 'scope': 'noaa-bag-survey-discovery', 'collected_at': now.isoformat(),
            'last_complete_scan_at': now.isoformat() if complete else (previous or {}).get('last_complete_scan_at'),
            'source_url': SERVICE.rsplit('/query', 1)[0],
            'method': 'Survey polygon intersects an approximate browsing sector. This is a catalog lead, not a verified BAG grid, seafloor feature, fishing spot or complete survey inventory.',
            'sector_count': len(sectors), 'distinct_survey_leads': len(distinct),
            'health': {'status': 'ok' if complete else 'degraded', 'issues': failures}, 'sectors': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--max-age-days', type=int, default=30)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    previous = json.loads(args.previous.read_text()) if args.previous and args.previous.is_file() else None
    if previous and previous.get('health', {}).get('status') == 'ok' and previous.get('last_complete_scan_at'):
        age = now - datetime.fromisoformat(previous['last_complete_scan_at'])
        if timedelta(0) <= age < timedelta(days=args.max_age_days):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(args.previous.read_bytes())
            print('Retained complete NOAA discovery from ' + previous['last_complete_scan_at'])
            return
    sectors = json.loads((ROOT / 'dist/data/coastal-sectors.json').read_text())['sectors']
    result = scan(sectors, previous, now=now)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, separators=(',', ':'), ensure_ascii=False) + '\n')
    temporary.replace(args.output)
    print(f"{result['health']['status']}: {result['distinct_survey_leads']} distinct survey leads across {len(sectors)} sectors")


if __name__ == '__main__':
    main()
