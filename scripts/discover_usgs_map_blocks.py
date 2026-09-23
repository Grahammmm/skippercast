"""Inventory original USGS California State Waters map-block products.

Catalog links are discovery evidence, not bathymetry or fishing locations. A
block enters the fishing atlas only after its native rasters, metadata, MPA
geometry, and relevant rules have been reviewed separately.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

INDEX = 'https://pubs.usgs.gov/ds/781/'
MAX_PAGE = 500_000


def approved(url):
    parts = urlsplit(url)
    return parts.scheme == 'https' and parts.hostname == 'pubs.usgs.gov' and parts.path.startswith('/ds/781/')


class CatalogParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'tr':
            self.row = []
        elif tag == 'td' and self.row is not None:
            self.cell = {'text': [], 'links': []}
        elif tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
            if self.cell is not None:
                self.cell['links'].append(attrs['href'])

    def handle_data(self, data):
        if self.cell is not None:
            self.cell['text'].append(data)

    def handle_endtag(self, tag):
        if tag == 'td' and self.cell is not None and self.row is not None:
            self.row.append(self.cell)
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None


def fetch(url):
    if not approved(url):
        raise ValueError('USGS URL outside reviewed catalog')
    request = Request(url, headers={'User-Agent': 'SkipperCast USGS map block inventory/1.0'})
    with urlopen(request, timeout=20) as response:
        if not approved(response.url):
            raise ValueError('USGS catalog redirected outside reviewed host')
        raw = response.read(MAX_PAGE + 1)
        if len(raw) > MAX_PAGE:
            raise ValueError('USGS catalog exceeds size limit')
        return raw


def catalog_urls(raw):
    parser = CatalogParser()
    parser.feed(raw.decode('utf-8', errors='replace'))
    links = []
    for href in parser.links:
        url = urljoin(INDEX, href)
        if approved(url) and '/data_catalog_' in urlsplit(url).path and urlsplit(url).path.endswith('.html') and '/video_observations/' not in url:
            if url not in links:
                links.append(url)
    return links


def inspect_catalog(url, raw, *, now):
    if not approved(url) or '/data_catalog_' not in url:
        raise ValueError('Invalid USGS map-block catalog URL')
    parser = CatalogParser()
    parser.feed(raw.decode('utf-8', errors='replace'))
    products = {}
    for row in parser.rows:
        if len(row) < 5:
            continue
        label = ' '.join(row[0]['text']).strip()
        lower = label.lower()
        kind = ('bathymetry' if lower.startswith('bathymetry (') else
                'seafloor_character' if lower.startswith('seafloor character (') else None)
        if not kind:
            continue
        metadata = [urljoin(url, href) for cell in row for href in cell['links'] if href.lower().endswith('.xml')]
        archives = [urljoin(url, href) for cell in row for href in cell['links'] if href.lower().endswith('.zip')]
        metadata = [item for item in metadata if approved(item) and '/metadata/' in item]
        archives = [item for item in archives if approved(item) and '/data/' in item]
        if metadata and archives:
            products.setdefault(kind, []).append({'description': label[:180], 'metadata_url': metadata[0], 'archive_url': archives[0]})
    block_id = urlsplit(url).path.split('/')[-2]
    return {'id': block_id, 'catalog_url': url, 'status': 'ok', 'checked_at': now.isoformat(),
            'catalog_sha256': hashlib.sha256(raw).hexdigest(), 'products': products, 'issue': None}


def discover(previous=None, *, now=None, fetcher=fetch):
    now = now or datetime.now(timezone.utc)
    raw = fetcher(INDEX)
    urls = catalog_urls(raw)
    if not urls:
        raise ValueError('USGS index contained no map-block catalogs')
    old = {row['catalog_url']: row for row in (previous or {}).get('blocks', [])}
    rows = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        pending = {pool.submit(fetcher, url): url for url in urls}
        for future in as_completed(pending):
            url = pending[future]
            try:
                rows.append(inspect_catalog(url, future.result(), now=now))
            except (OSError, TimeoutError, ValueError, UnicodeError) as error:
                prior = old.get(url)
                rows.append({**prior, 'status': 'retained', 'issue': str(error)[:180]} if prior else
                            {'id': urlsplit(url).path.split('/')[-2], 'catalog_url': url, 'status': 'failed',
                             'checked_at': None, 'catalog_sha256': None, 'products': {}, 'issue': str(error)[:180]})
    rows.sort(key=lambda row: row['id'])
    issues = [row['id'] for row in rows if row['status'] != 'ok']
    return {'schema_version': 1, 'scope': 'usgs-state-waters-map-block-links', 'collected_at': now.isoformat(),
            'last_complete_scan_at': now.isoformat() if not issues else (previous or {}).get('last_complete_scan_at'),
            'source_url': INDEX, 'index_sha256': hashlib.sha256(raw).hexdigest(),
            'method': 'Original USGS DS 781 map-block catalog links only. No native raster, extent, datum, substrate class, precision, license or fishing ground approved.',
            'block_count': len(rows),
            'bathymetry_blocks': sum(bool(row['products'].get('bathymetry')) for row in rows),
            'seafloor_character_blocks': sum(bool(row['products'].get('seafloor_character')) for row in rows),
            'health': {'status': 'ok' if not issues else 'degraded', 'issues': issues}, 'blocks': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--max-age-days', type=int, default=30)
    args = parser.parse_args()
    previous = json.loads(args.previous.read_text()) if args.previous and args.previous.is_file() else None
    now = datetime.now(timezone.utc)
    if previous and previous.get('health', {}).get('status') == 'ok' and previous.get('last_complete_scan_at'):
        age = now - datetime.fromisoformat(previous['last_complete_scan_at'])
        if timedelta(0) <= age < timedelta(days=args.max_age_days):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(args.previous.read_bytes())
            print('Retained complete USGS map-block catalog inventory from ' + previous['last_complete_scan_at'])
            return
    result = discover(previous, now=now)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + '.tmp')
    temp.write_text(json.dumps(result, separators=(',', ':'), ensure_ascii=False) + '\n')
    temp.replace(args.output)
    print(f"{result['health']['status']}: {result['block_count']} catalogs, {result['bathymetry_blocks']} bathymetry blocks, {result['seafloor_character_blocks']} character blocks")


if __name__ == '__main__':
    main()
