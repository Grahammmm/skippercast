"""Review original vertical-accuracy XML for all audited USGS bathymetry grids.

Preserve the publisher's exact statement and source hash. Textual accuracy is
never converted to a per-cell uncertainty or a fishing-depth qualification.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


MAX_XML = 1_500_000


def fetch(url):
    parsed = urlparse(url)
    allowed = ((parsed.netloc == 'pubs.usgs.gov' and
                parsed.path.startswith('/ds/781/') and '/metadata/' in parsed.path) or
               (parsed.netloc == 'cmgds.marine.usgs.gov' and
                (parsed.path.startswith('/data-releases/media/') or
                 parsed.path.startswith('/data/csmp/'))))
    if parsed.scheme != 'https' or not allowed or not parsed.path.endswith('.xml'):
        raise ValueError('Unreviewed USGS original metadata URL')
    for attempt in range(2):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'SkipperCast original accuracy audit/1.0'}),
                         timeout=25) as response:
                raw = response.read(MAX_XML + 1)
                if response.status != 200 or response.url != url or len(raw) > MAX_XML:
                    raise ValueError('Unexpected USGS original metadata response')
                return raw
        except (OSError, TimeoutError):
            if attempt:
                raise
            time.sleep(1)


def inspect(source, raw):
    if hashlib.sha256(raw).hexdigest() != source['metadata_sha256']:
        raise ValueError('Original USGS XML differs from pinned native ledger')
    root = ET.fromstring(raw)
    statement = ' '.join((root.findtext('.//vertaccr') or '').split())
    values = [' '.join((node.text or '').split()) for node in root.findall('.//vertacrv')]
    if any(len(text) > 2500 for text in [statement, *values]):
        raise ValueError('Unexpectedly long vertical-accuracy field')
    return {'source_id': source['id'], 'metadata_url': source['metadata_url'],
            'metadata_sha256': source['metadata_sha256'],
            'archive_sha256': source['archive_sha256'],
            'native_resolution_m': source['native_resolution_m'],
            'structured_vertical_datum_code': source['structured_vertical_datum_code'],
            'vertical_accuracy_statement': statement or None,
            'vertical_accuracy_values': values,
            'accuracy_evidence': ('structured_numeric' if values else
                                  'narrative_only' if statement else 'not_declared'),
            'per_cell_uncertainty_available': source['has_per_cell_product_uncertainty'],
            'depth_qualified_for_fishing': source['depth_qualified_for_fishing']}


def build(ledger, cache, *, fetch_missing=False, fetch_missing_only=False, workers=5):
    if (ledger.get('scope') != 'california-usgs-original-bathymetry-datum-ledger'
            or ledger.get('source_grid_count') != len(ledger.get('sources', []))):
        raise ValueError('Complete audited USGS native-grid ledger required')
    sources = ledger['sources']
    if len({row['metadata_url'] for row in sources}) != len(sources):
        raise ValueError('Duplicate original USGS bathymetry XML')
    cache.mkdir(parents=True, exist_ok=True)

    def one(source):
        path = cache / (hashlib.sha256(source['metadata_url'].encode()).hexdigest()[:16] + '.xml')
        access = 'cache_verified'
        issue = None
        cached_valid = (path.is_file() and
                        hashlib.sha256(path.read_bytes()).hexdigest() == source['metadata_sha256'])
        if fetch_missing and not (fetch_missing_only and cached_valid):
            try:
                raw = fetch(source['metadata_url'])
                path.write_bytes(raw)
                access = 'fetched'
            except (OSError, TimeoutError, ValueError) as error:
                issue = str(error)[:180]
                if not path.is_file():
                    return {'source_id': source['id'], 'metadata_url': source['metadata_url'],
                            'status': 'failed', 'issue': issue}
                raw = path.read_bytes()
                access = 'retained_after_fetch_failure'
        else:
            if not path.is_file():
                return {'source_id': source['id'], 'metadata_url': source['metadata_url'],
                        'status': 'failed', 'issue': 'Pinned original XML not cached'}
            raw = path.read_bytes()
        try:
            inspected = inspect(source, raw)
        except (ValueError, ET.ParseError) as error:
            return {'source_id': source['id'], 'metadata_url': source['metadata_url'],
                    'status': 'failed', 'issue': str(error)[:180]}
        return {**inspected, 'status': 'ok' if access != 'retained_after_fetch_failure' else 'retained',
                'access': access, 'issue': issue}

    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, row): row for row in sources}
        for future in as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: (row['source_id'], row['metadata_url']))
    issues = [row['metadata_url'] for row in rows if row['status'] != 'ok']
    return {'schema_version': 1, 'scope': 'california-usgs-original-bathymetry-accuracy-review',
            'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'status': 'ok' if not issues else 'degraded',
            'source_grid_count': len(sources),
            'fully_verified_source_count': sum(row['status'] == 'ok' for row in rows),
            'issues': issues,
            'fishing_target': False, 'exportable': False,
            'method': 'Reopen each original USGS bathymetry metadata XML at its ledger-pinned SHA-256 and retain the structured vertical-accuracy statement and values without converting narrative text into uncertainty.',
            'limitations': ['A narrative or single accuracy estimate is not a per-cell product uncertainty grid.',
                            'An accuracy floor such as "no less than 20 cm" cannot establish a <=1 m upper bound.',
                            'No source is promoted to an MLLW fishing target, chart, or navigation position.',
                            'A retained cache after failed HTTP access is marked degraded and does not count as a fresh source read.'],
            'sources': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path,
                        default=Path('dist/data/usgs-depth-datum-ledger.json'))
    parser.add_argument('--cache', type=Path,
                        default=Path('var/usgs-accuracy-xml-cache'))
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--fetch-missing', action='store_true',
                        help='Fetch only uncached or hash-invalid originals; cached hashes are still checked')
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--output', type=Path,
                        default=Path('dist/data/usgs-bathymetry-accuracy-review.json'))
    args = parser.parse_args()
    if args.fetch and args.fetch_missing:
        parser.error('Choose --fetch or --fetch-missing')
    result = build(json.loads(args.ledger.read_text()), args.cache,
                   fetch_missing=args.fetch or args.fetch_missing,
                   fetch_missing_only=args.fetch_missing)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(result, separators=(',', ':')) + '\n')
    temp.replace(args.output)
    print(result['fully_verified_source_count'], '/', result['source_grid_count'],
          'original USGS XML records verified')
    if args.strict and result['status'] != 'ok':
        raise SystemExit('Original USGS bathymetry accuracy audit degraded')


if __name__ == '__main__':
    main()
