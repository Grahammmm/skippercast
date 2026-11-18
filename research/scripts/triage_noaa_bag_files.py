"""HEAD-check original NOAA BAG links statewide; metadata only, no fishing claims.

The result is a bounded native-review queue. A URL, filename or Content-Length
does not establish datum, resolution, survey coverage, substrate or legal use.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from skippercast.http import parse_retry_after
from skippercast.platform.bottom_targets import source_url_allowed

MAX_REVIEW_BYTES = 160_000_000
MAX_FILE_BYTES = 2_000_000_000
# NOAA's NCEI host answers bursts of HEADs with 429. A full rescan (427 files)
# must wait and retry instead of reporting the whole inventory as degraded.
RATE_LIMIT_ATTEMPTS = 5
RATE_LIMIT_MAX_WAIT = 60.0
WORKERS = 4


def head(url, *, opener=urlopen, sleep=time.sleep):
    if not source_url_allowed(url) or not url.lower().endswith('.bag'):
        raise ValueError('BAG URL outside reviewed NOAA host/path')
    request = Request(url, method='HEAD', headers={'User-Agent':'SkipperCast NOAA BAG metadata inventory/1.0'})
    for attempt in range(RATE_LIMIT_ATTEMPTS):
        try:
            return _head_once(request, url, opener)
        except HTTPError as error:
            if error.code != 429 or attempt == RATE_LIMIT_ATTEMPTS - 1:
                raise
            wait = parse_retry_after(error.headers.get('Retry-After') if error.headers else None)
            sleep(min(RATE_LIMIT_MAX_WAIT, wait if wait is not None else 2.0 * 2 ** attempt))
    raise AssertionError('unreachable')


def _head_once(request, url, opener):
    with opener(request, timeout=18) as response:
        if response.status != 200 or response.url != url:
            raise ValueError('BAG HEAD redirected or did not return 200')
        value=response.headers.get('Content-Length','')
        if not value.isascii() or not value.isdecimal() or not 0 < int(value) <= MAX_FILE_BYTES:
            raise ValueError('BAG Content-Length missing or outside inventory bound')
        return int(value), response.headers.get('Last-Modified')


def _check_count(document, key, expected, *, optional=False):
    if optional and key not in document:
        return
    count = document.get(key)
    if type(count) is not int or count != expected:
        raise ValueError(f'Incomplete NOAA source inventory: wrong {key}')


def _inputs(discovery, products):
    if (not isinstance(discovery, dict) or discovery.get('scope') != 'noaa-bag-survey-discovery'
            or not isinstance(products, dict) or products.get('scope') != 'noaa-survey-product-links'):
        raise ValueError('Wrong NOAA input scope')
    sectors, surveys = discovery.get('sectors'), products.get('surveys')
    if not isinstance(sectors, list) or not isinstance(surveys, list):
        raise ValueError('Incomplete NOAA source inventory')
    _check_count(discovery, 'sector_count', len(sectors))
    _check_count(products, 'survey_count', len(surveys))
    known = {row['id']: row['products'] for row in surveys}
    leads = {lead['id'] for sector in sectors for lead in sector['surveys']}
    if len(known) != len(surveys) or leads != set(known):
        raise ValueError('Survey IDs differ between discovery and product inventory')
    _check_count(discovery, 'distinct_survey_leads', len(leads), optional=True)
    # The producer counts surveys with each link type, not individual links.
    for kind in ('bag', 'report'):
        _check_count(products, f'{kind}_link_count', sum(bool(links[kind]) for links in known.values()), optional=True)
    urls = {}
    for survey_id, links in known.items():
        for url in links['bag']:
            if not source_url_allowed(url) or f'/{survey_id}/' not in url or not url.lower().endswith('.bag'):
                raise ValueError('Untrusted or mismatched NOAA BAG URL')
            if url in urls and urls[url] != survey_id:
                raise ValueError('Ambiguous NOAA BAG survey identity')
            urls[url] = survey_id
    return known, urls


def _fetch_rows(urls, prior, now, fetcher):
    rows = []

    def inspect(url):
        size, modified = fetcher(url)
        return {'survey_id':urls[url],'url':url,'bytes':size,'last_modified_http':modified,
                'status':'ok','checked_at':now.isoformat(),'issue':None}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        pending={pool.submit(inspect,url):url for url in sorted(urls)}
        for future in as_completed(pending):
            url=pending[future]
            try: rows.append(future.result())
            except (OSError,TimeoutError,ValueError) as error:
                old=prior.get(url)
                rows.append({**old,'status':'retained','issue':str(error)[:180]} if old else
                            {'survey_id':urls[url],'url':url,'bytes':None,'last_modified_http':None,
                             'status':'failed','checked_at':None,'issue':str(error)[:180]})
    return rows


def inventory(discovery, products, previous=None, *, now=None, fetcher=head, max_age_days=None):
    now = now or datetime.now(timezone.utc)
    known, urls = _inputs(discovery, products)
    previous = previous or {}
    scan_at, reason = _reusable_scan(previous, urls, now, max_age_days)
    if reason:
        print(f'previous scan ignored: {reason}', file=sys.stderr)
    if scan_at is not None:
        rows = [row.copy() for row in previous['files']]
    else:
        files = previous.get('files')
        prior = {row['url']: row for row in files if isinstance(row, dict)
                 and isinstance(row.get('url'), str) and row['url'] in urls
                 and row.get('survey_id') == urls[row['url']]} if isinstance(files, list) else {}
        rows = _fetch_rows(urls, prior, now, fetcher)

    for row in rows:
        # This is only a filename/report/size queue hint. Never a data approval.
        size = row.get('bytes')
        row['native_review_hint'] = None if type(size) is not int else (
            'filename-MLLW-and-report; inspect-native-product'
            if 'MLLW' in row['url'].rsplit('/', 1)[-1].upper()
            and known[row['survey_id']]['report'] and size <= MAX_REVIEW_BYTES else 'inspect-original-product'
        )
    rows.sort(key=lambda row:(row['survey_id'],row['url']))
    by_id={}
    for row in rows:by_id.setdefault(row['survey_id'],[]).append(row)
    sectors=[]
    for sector in discovery['sectors']:
        selected=[row for lead in sector['surveys'] for row in by_id.get(lead['id'],[])]
        sectors.append({'sector_id':sector['sector_id'],'survey_count':len(sector['surveys']),
                        'file_count':len(selected),'accessible_files':sum(row['status']=='ok' for row in selected),
                        'native_review_hints':sum(row['status']=='ok' and row['native_review_hint'].startswith('filename-MLLW') for row in selected)})
    issues=[row['url'] for row in rows if row['status']!='ok']
    return {'schema_version':1,'scope':'noaa-bag-head-inventory','collected_at':now.isoformat(),
            'last_complete_scan_at':scan_at if scan_at is not None else (
                previous.get('last_complete_scan_at') if issues else now.isoformat()),
            'method':'Bounded HEAD checks of exact catalog-linked NOAA BAG URLs. HTTP size, Last-Modified, report link and filename are triage only; no grid opened, source rights or fishing spot approved.',
            'survey_count':len(known),'file_count':len(rows),'accessible_file_count':sum(row['status']=='ok' for row in rows),
            'native_review_hint_count':sum(row['status']=='ok' and row['native_review_hint'].startswith('filename-MLLW') for row in rows),
            'health':{'status':'ok' if not issues else 'degraded','issues':issues},'sectors':sectors,'files':rows}


def _days(text):
    days=int(text) if re.fullmatch(r'[+-]?[0-9]+',text.strip()) else 0
    if not 1<=days<=365:raise argparse.ArgumentTypeError('must be a whole number of days from 1 to 365')
    return days


def _previous(path):
    try:previous=json.loads(path.read_text(encoding='utf-8')) if path and path.is_file() else {}  # is_file() can raise too
    except (OSError,ValueError):previous=None  # ValueError covers UnicodeDecodeError and JSONDecodeError
    return (previous or None,None) if isinstance(previous,dict) else (None,'unreadable')


def _scan_time(value, now):
    try:when=None if value is None else datetime.fromisoformat(value)
    except (TypeError,ValueError):return None,'bad scan time'
    if when is None or when.utcoffset() is None:return None,'scan time has no UTC offset' if when else 'no scan time'
    return (when,None) if when<=now else (None,'scan time is in the future')


def _reusable_scan(previous, urls, now, max_age_days):
    health = previous.get('health')
    if max_age_days is None or not isinstance(health, dict) or health.get('status') != 'ok':
        return None, None
    scan_at = previous.get('last_complete_scan_at')
    when, reason = _scan_time(scan_at, now)
    if when is None:
        return None, reason
    files = previous.get('files')
    if not isinstance(files, list) or not all(isinstance(row, dict) and isinstance(row.get('url'), str) for row in files):
        return None, 'files not a url list'
    if now - when >= timedelta(days=max_age_days) or urls.keys() != {row['url'] for row in files}:
        return None, None
    if (previous.get('scope') != 'noaa-bag-head-inventory' or len(files) != len(urls)
            or any(row.get('survey_id') != urls[row['url']] or row.get('status') != 'ok'
                   or type(row.get('bytes')) is not int or not 0 < row['bytes'] <= MAX_FILE_BYTES
                   or _scan_time(row.get('checked_at'), when)[0] is None for row in files)):
        return None, 'incompatible file evidence'
    return scan_at, None


def main(argv=None, *, fetcher=head):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discovery',type=Path,required=True)
    parser.add_argument('--products',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--previous',type=Path)
    parser.add_argument('--max-age-days',type=_days,default=30)
    args=parser.parse_args(argv)
    discovery=json.loads(args.discovery.read_text())
    products=json.loads(args.products.read_text())
    previous,reason=_previous(args.previous)
    now=datetime.now(timezone.utc)
    if reason:print(f'previous scan ignored: {reason}',file=sys.stderr)
    result=inventory(discovery,products,previous,now=now,fetcher=fetcher,max_age_days=args.max_age_days)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    tmp=args.output.with_suffix(args.output.suffix+'.tmp')
    tmp.write_text(json.dumps(result,separators=(',',':'),ensure_ascii=False)+'\n')
    tmp.replace(args.output)
    print(f"{result['health']['status']}: {result['accessible_file_count']}/{result['file_count']} BAG links accessible; {result['native_review_hint_count']} metadata review hints")


if __name__=='__main__':main()
