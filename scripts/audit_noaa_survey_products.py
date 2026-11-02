"""Inventory linked NOAA survey products; never promote links to qualified bottom.

The catalog page can identify downloadable BAG grids and descriptive reports. It
does not establish the grid's local extent, datum, resolution, uncertainty,
substrate, or suitability for a fishing point.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

HOSTS = {'www.ngdc.noaa.gov', 'data.ngdc.noaa.gov', 'www.ncei.noaa.gov'}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            value = dict(attrs).get('href')
            if value:
                self.urls.append(value)


def fetch(url):
    request = Request(url, headers={'User-Agent': 'SkipperCast NOAA survey product inventory/1.0'})
    with urlopen(request, timeout=20) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError('NOAA catalog page exceeds size limit')
    return raw


def inspect(lead, *, now, fetcher=fetch):
    ident, page = lead['id'], lead['catalog_url']
    if urlsplit(page).scheme != 'https' or urlsplit(page).hostname not in HOSTS:
        raise ValueError('Unapproved NOAA catalog URL')
    raw = fetcher(page)
    parser = Links()
    parser.feed(raw.decode('utf-8', errors='replace'))
    products = {'bag': [], 'report': [], 'xyz': []}
    for href in parser.urls:
        url = urljoin(page, href)
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in HOSTS or f'/{ident}/' not in parts.path:
            continue
        path = parts.path.lower()
        kind = ('bag' if '/bag/' in path and path.endswith('.bag') else
                'report' if '/dr/' in path and path.endswith('.pdf') else
                'xyz' if '/gridded_data/' in path and path.endswith(('.txt.gz', '.xyz.gz')) else None)
        if kind and url not in products[kind] and len(products[kind]) < 20:
            products[kind].append(url)
    return {'id': ident, 'status': 'ok', 'retrieved_at': now.isoformat(),
            'catalog_url': page, 'catalog_sha256': hashlib.sha256(raw).hexdigest(),
            'products': products, 'issue': None}


def audit(discovery, previous=None, *, now=None, inspector=inspect):
    now = now or datetime.now(timezone.utc)
    leads = {lead['id']: lead for sector in discovery['sectors'] for lead in sector['surveys']}
    prior = {row['id']: row for row in (previous or {}).get('surveys', [])}
    rows = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(inspector, lead, now=now): ident for ident, lead in leads.items()}
        for future in as_completed(pending):
            ident = pending[future]
            try:
                rows.append(future.result())
            except (OSError, TimeoutError, ValueError, UnicodeError) as error:
                older = prior.get(ident)
                rows.append({**older, 'status': 'retained', 'issue': str(error)[:200]} if older else
                            {'id': ident, 'status': 'failed', 'retrieved_at': None,
                             'catalog_url': leads[ident]['catalog_url'], 'catalog_sha256': None,
                             'products': {'bag': [], 'report': [], 'xyz': []}, 'issue': str(error)[:200]})
    rows.sort(key=lambda row: row['id'])
    issues = [row['id'] for row in rows if row['status'] != 'ok']
    return {'schema_version': 1, 'scope': 'noaa-survey-product-links', 'collected_at': now.isoformat(),
            'last_complete_scan_at': now.isoformat() if not issues else (previous or {}).get('last_complete_scan_at'),
            'source': 'NOAA NCEI individual survey catalog pages',
            'method': 'Links found on an original NOAA page only. A BAG link is not a validated grid or fishing ground.',
            'survey_count': len(rows), 'bag_link_count': sum(bool(row['products']['bag']) for row in rows),
            'report_link_count': sum(bool(row['products']['report']) for row in rows),
            'health': {'status': 'ok' if not issues else 'degraded', 'issues': issues}, 'surveys': rows}


def _days(text):
    if not re.fullmatch(r'\s*[+-]?[0-9]+\s*', text) or not 1 <= int(text) <= 365:
        raise argparse.ArgumentTypeError('must be a whole number of days from 1 to 365')
    return int(text)


def _discovery(path):
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):  # covers UnicodeDecodeError and JSONDecodeError
        return None, 'discovery file is unreadable'
    if not isinstance(doc, dict) or doc.get('scope') != 'noaa-bag-survey-discovery':
        return None, 'discovery file is not a NOAA survey discovery object'
    if not isinstance(doc.get('sectors'), list) or not doc['sectors']:
        return None, 'discovery file has no sector list'
    for s, sector in enumerate(doc['sectors']):
        surveys = sector.get('surveys') if isinstance(sector, dict) else None
        if not isinstance(surveys, list):
            return None, f'sector {s} has no survey list'
        for n, lead in enumerate(surveys):
            if not isinstance(lead, dict) or not isinstance(lead.get('id'), str):
                return None, f'sector {s} lead {n} has no string id'
    return doc, None


def _previous(path):
    if not path:
        return None, None
    try:  # every filesystem touch is inside the handler: a stat/open error is 'unreadable', not a crash
        previous = json.loads(path.read_text(encoding='utf-8'))
        value = previous.get('last_complete_scan_at')
    except FileNotFoundError:  # no previous inventory yet: a plain first audit
        return None, None
    except (OSError, ValueError, AttributeError):  # not readable JSON, or not an object
        return None, 'unreadable'
    try:
        offset = datetime.fromisoformat(value).utcoffset()
    except (TypeError, ValueError):
        return None, 'no scan time' if value is None else 'bad scan time'
    if offset is None:
        return None, 'scan time has no UTC offset'
    if not isinstance(rows := previous.get('surveys'), list) or not all(isinstance(r, dict) and isinstance(r.get('id'), str) for r in rows):
        return None, 'no survey list'
    return previous, None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discovery', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--max-age-days', type=_days, default=30)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    discovery, reason = _discovery(args.discovery)
    if reason:
        print(f'audit refused: {reason}', file=sys.stderr)
        return 1
    previous, reason = _previous(args.previous)
    if reason:
        print(f'previous inventory ignored: {reason}', file=sys.stderr)
    ids = {lead['id'] for sector in discovery['sectors'] for lead in sector['surveys']}
    if previous and isinstance(previous.get('health'), dict) and previous['health'].get('status') == 'ok':
        age = now - datetime.fromisoformat(previous['last_complete_scan_at'])
        if timedelta(0) <= age < timedelta(days=args.max_age_days) and ids == {row['id'] for row in previous['surveys']}:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(args.previous.read_bytes())
            print('Retained complete NOAA product inventory from ' + previous['last_complete_scan_at'])
            return
    result = audit(discovery, previous, now=now)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + '.tmp')
    temporary.write_text(json.dumps(result, separators=(',', ':'), ensure_ascii=False) + '\n')
    temporary.replace(args.output)
    print(f"{result['health']['status']}: {result['bag_link_count']} BAG links, {result['report_link_count']} report links among {result['survey_count']} surveys")


if __name__ == '__main__':
    raise SystemExit(main())
