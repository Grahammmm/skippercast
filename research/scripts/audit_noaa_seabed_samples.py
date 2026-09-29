"""Audit NOAA/NOS historical seabed descriptions across California browse sectors.

The raw official point responses stay under var/. The public result contains
sector aggregates only, never candidate fishing coordinates or reef grades.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

BASE = 'https://gis.ngdc.noaa.gov/arcgis/rest/services/web_mercator/nos_seabed_dynamic/MapServer/0'
METADATA = 'https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ngdc.mgg.geology%3AG10163'
CALIFORNIA = (-125.4, 32.5343, -116.95, 42.0)
FIELDS = ('OBJECTID', 'SURVEY', 'SAMPLE', 'LAT', 'LON', 'BEGIN_OBSTIM', 'DESCRP',
          'NATSUR', 'NATQUA', 'SOURCE', 'SORDAT')
PAGE_SIZE = 2000


def fetch(url: str) -> tuple[dict, str, bytes]:
    if not url.startswith(BASE + '?') and not url.startswith(BASE + '/query?'):
        raise ValueError('Unreviewed NOAA seabed URL')
    request = urllib.request.Request(url, headers={'User-Agent': 'SkipperCast historical seabed audit/1.0'})
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status != 200 or response.url != url:
            raise ValueError('NOAA seabed service redirected or failed')
        raw = response.read(20_000_001)
    if not raw or len(raw) > 20_000_000:
        raise ValueError('NOAA seabed response empty or oversized')
    packet = json.loads(raw)
    if 'error' in packet:
        raise ValueError('NOAA seabed service error: ' + str(packet['error'])[:180])
    return packet, hashlib.sha256(raw).hexdigest(), raw


def request_url(*, count=False, offset=0) -> str:
    common = {'where': '1=1', 'geometry': ','.join(map(str, CALIFORNIA)),
              'geometryType': 'esriGeometryEnvelope', 'inSR': '4326',
              'spatialRel': 'esriSpatialRelIntersects'}
    if count:
        common.update(returnCountOnly='true', f='json')
    else:
        common.update(outFields=','.join(FIELDS), returnGeometry='true', outSR='4326',
                      orderByFields='OBJECTID ASC', resultOffset=str(offset),
                      resultRecordCount=str(PAGE_SIZE), f='geojson')
    return BASE + '/query?' + urllib.parse.urlencode(common)


def verify_service(metadata: dict) -> None:
    fields = {row['name'] for row in metadata.get('fields', [])}
    if (metadata.get('name') != 'NOS Seabed Type' or
            metadata.get('geometryType') != 'esriGeometryPoint' or
            not set(FIELDS) <= fields or
            metadata.get('maxRecordCount', 0) < PAGE_SIZE or
            not metadata.get('advancedQueryCapabilities', {}).get('supportsPagination')):
        raise ValueError('NOAA seabed schema or paging capability changed')


def validate_pages(pages: list[dict], expected_count: int) -> list[dict]:
    rows = []
    ids = set()
    for page_index, page in enumerate(pages):
        features = page.get('features')
        expected_page_size = min(PAGE_SIZE, expected_count - page_index * PAGE_SIZE)
        if (page.get('type') != 'FeatureCollection' or not isinstance(features, list)
                or len(features) != expected_page_size
                or (page.get('exceededTransferLimit') and page_index == len(pages) - 1)):
            raise ValueError('Incomplete NOAA seabed page')
        for feature in features:
            props = feature.get('properties', {})
            geometry = feature.get('geometry', {})
            ident = props.get('OBJECTID')
            point = geometry.get('coordinates')
            if (type(ident) is not int or ident in ids or geometry.get('type') != 'Point' or
                    not isinstance(point, list) or len(point) != 2 or
                    not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in point) or
                    not (CALIFORNIA[0] <= point[0] <= CALIFORNIA[2] and
                         CALIFORNIA[1] <= point[1] <= CALIFORNIA[3])):
                raise ValueError('Invalid or duplicate NOAA seabed observation')
            ids.add(ident)
            rows.append(feature)
    if len(rows) != expected_count:
        raise ValueError('NOAA seabed pages do not match the bounded count')
    return rows


def sector_for(lon: float, lat: float, sectors: list[dict]) -> str | None:
    matches = [row['id'] for row in sectors if row['bounds'][0] <= lon <= row['bounds'][2]
               and row['bounds'][1] <= lat < row['bounds'][3]]
    if len(matches) > 1:
        raise ValueError('California browse sectors overlap at a seabed sample')
    return matches[0] if matches else None


def summarize(features: list[dict], sectors: list[dict], *, checked_at: str,
              metadata_sha: str, count_sha: str, page_shas: list[str]) -> dict:
    by_sector = {row['id']: [] for row in sectors}
    outside = 0
    for feature in features:
        lon, lat = feature['geometry']['coordinates']
        sector = sector_for(lon, lat, sectors)
        if sector is None:
            outside += 1
        else:
            by_sector[sector].append(feature['properties'])
    rows = []
    review_year = datetime.fromisoformat(checked_at.replace('Z', '+00:00')).year
    for sector in sectors:
        records = by_sector[sector['id']]
        coded = Counter(str(p['NATSUR']).strip().lower() for p in records if p.get('NATSUR'))
        rock_words = sum(bool(re.search(r'\b(rock|boulder|cobble|bedrock)\b',
                                        str(p.get('DESCRP') or ''), re.I)) for p in records)
        years = []
        implausible_dates = 0
        for p in records:
            ms = p.get('BEGIN_OBSTIM') or p.get('SORDAT')
            if isinstance(ms, (int, float)) and not isinstance(ms, bool):
                try:
                    year = datetime.fromtimestamp(ms / 1000, timezone.utc).year
                    if 1800 <= year <= review_year:
                        years.append(year)
                    else:
                        implausible_dates += 1
                except (OverflowError, OSError, ValueError):
                    implausible_dates += 1
        rows.append({'sector_id': sector['id'], 'historical_sample_count': len(records),
                     'nature_code_counts': dict(sorted(coded.items())),
                     'uncurated_description_rock_word_count': rock_words,
                     'dated_sample_count': len(years),
                     'implausible_date_count': implausible_dates,
                     'observation_year_range': [min(years), max(years)] if years else None,
                     'source_record_counts': dict(sorted(Counter(str(p.get('SOURCE') or 'unrecorded')
                                                              for p in records).items()))})
    return {'schema_version': 1, 'scope': 'california-historical-nos-seabed-sample-sector-audit',
            'source_url': BASE, 'metadata_url': METADATA, 'retrieved_at': checked_at,
            'service_metadata_sha256': metadata_sha, 'bounded_count_sha256': count_sha,
            'page_sha256': page_shas, 'bounded_original_sample_count': len(features),
            'assigned_to_browse_sector_count': len(features) - outside,
            'outside_browse_sectors_count': outside, 'sectors': rows,
            'fishing_target': False, 'exportable': False,
            'limitations': [
                'These are sparse historical point descriptions from varied source surveys, not complete substrate coverage or reef polygons.',
                'NATSUR codes and uncurated description words are reported separately; a word match is not an independently reviewed bottom class.',
                'A browse-sector latitude band may include harbors, bays or offshore water; counts do not establish local fishing habitat or fish presence.',
                'Service retrieval time is not observation time or a scientific issue time. Missing dates and codes stay missing.',
                'Future or otherwise implausible source dates are excluded from year ranges and counted separately.',
                'No fishing coordinate, depth, MPA or route clearance, species rating or export follows from this audit.'
            ]}


def audit(sectors: list[dict], raw_dir: Path) -> dict:
    metadata, metadata_sha, _ = fetch(BASE + '?f=pjson')
    verify_service(metadata)
    count_packet, count_sha, _ = fetch(request_url(count=True))
    count = count_packet.get('count')
    if type(count) is not int or not 0 <= count <= 100_000:
        raise ValueError('Missing or unexpected California seabed count')
    raw_dir.mkdir(parents=True, exist_ok=True)
    pages, shas = [], []
    for offset in range(0, count, PAGE_SIZE):
        page, digest, raw = fetch(request_url(offset=offset))
        (raw_dir / f'page-{offset:05d}.geojson').write_bytes(raw)
        pages.append(page)
        shas.append(digest)
    records = validate_pages(pages, count)
    return summarize(records, sectors, checked_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                     metadata_sha=metadata_sha, count_sha=count_sha, page_shas=shas)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sectors', type=Path, default=Path('dist/data/coastal-sectors.json'))
    parser.add_argument('--raw-dir', type=Path, default=Path('var/review/noaa-seabed-samples'))
    parser.add_argument('--output', type=Path, default=Path('var/review/noaa-seabed-samples-sector-review.json'))
    parser.add_argument('--baseline', type=Path, help='Fail after writing a review artifact when original pages change')
    args = parser.parse_args()
    if not args.raw_dir.resolve().is_relative_to(Path('var').resolve()):
        raise ValueError('Raw seabed observations must stay under var/')
    packet = json.loads(args.sectors.read_text())
    report = audit(packet['sectors'], args.raw_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(report, indent=2) + '\n')
    temp.replace(args.output)
    print(json.dumps({'samples': report['bounded_original_sample_count'],
                      'assigned': report['assigned_to_browse_sector_count'],
                      'sectors_with_samples': sum(row['historical_sample_count'] > 0 for row in report['sectors'])}))
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        if (baseline.get('bounded_original_sample_count') != report['bounded_original_sample_count']
                or baseline.get('page_sha256') != report['page_sha256']):
            raise SystemExit('NOAA seabed sample content changed; review before updating the published sector summary')


if __name__ == '__main__':
    main()
