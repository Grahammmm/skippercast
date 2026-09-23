"""HEAD-check original NOAA BAG links statewide; metadata only, no fishing claims.

The result is a bounded native-review queue. A URL, filename or Content-Length
does not establish datum, resolution, survey coverage, substrate or legal use.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen

from skippercast.platform.bottom_targets import source_url_allowed

MAX_REVIEW_BYTES = 160_000_000


def head(url):
    if not source_url_allowed(url) or not url.lower().endswith('.bag'):
        raise ValueError('BAG URL outside reviewed NOAA host/path')
    request = Request(url, method='HEAD', headers={'User-Agent':'SkipperCast NOAA BAG metadata inventory/1.0'})
    with urlopen(request, timeout=18) as response:
        if response.status != 200 or response.url != url:
            raise ValueError('BAG HEAD redirected or did not return 200')
        value=response.headers.get('Content-Length','')
        if not value.isascii() or not value.isdecimal() or not 0 < int(value) <= 2_000_000_000:
            raise ValueError('BAG Content-Length missing or outside inventory bound')
        return int(value), response.headers.get('Last-Modified')


def inventory(discovery, products, previous=None, *, now=None, fetcher=head):
    now=now or datetime.now(timezone.utc)
    if discovery.get('scope')!='noaa-bag-survey-discovery' or products.get('scope')!='noaa-survey-product-links':
        raise ValueError('Wrong NOAA input scope')
    if products.get('survey_count')!=len(products.get('surveys',[])) or discovery.get('sector_count')!=len(discovery.get('sectors',[])):
        raise ValueError('Incomplete NOAA source inventory')
    known={row['id']:row for row in products['surveys']}
    leads={lead['id'] for sector in discovery['sectors'] for lead in sector['surveys']}
    if leads!=set(known):
        raise ValueError('Survey IDs differ between discovery and product inventory')
    urls={}
    for survey in products['surveys']:
        for url in survey['products']['bag']:
            if not source_url_allowed(url) or f"/{survey['id']}/" not in url or not url.lower().endswith('.bag'):
                raise ValueError('Untrusted or mismatched NOAA BAG URL')
            urls[url]=survey['id']
    prior={row['url']:row for row in (previous or {}).get('files',[])}
    rows=[]
    def inspect(url):
        size,modified=fetcher(url)
        survey=known[urls[url]]
        # This is only a filename/report/size queue hint. Never a data approval.
        hint=('filename-MLLW-and-report; inspect-native-product' if 'MLLW' in url.rsplit('/',1)[-1].upper()
              and survey['products']['report'] and size<=MAX_REVIEW_BYTES else 'inspect-original-product')
        return {'survey_id':urls[url],'url':url,'bytes':size,'last_modified_http':modified,
                'status':'ok','checked_at':now.isoformat(),'native_review_hint':hint,'issue':None}
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending={pool.submit(inspect,url):url for url in sorted(urls)}
        for future in as_completed(pending):
            url=pending[future]
            try: rows.append(future.result())
            except (OSError,TimeoutError,ValueError) as error:
                old=prior.get(url)
                rows.append({**old,'status':'retained','issue':str(error)[:180]} if old else
                            {'survey_id':urls[url],'url':url,'bytes':None,'last_modified_http':None,
                             'status':'failed','checked_at':None,'native_review_hint':None,'issue':str(error)[:180]})
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
            'last_complete_scan_at':now.isoformat() if not issues else (previous or {}).get('last_complete_scan_at'),
            'method':'Bounded HEAD checks of exact catalog-linked NOAA BAG URLs. HTTP size, Last-Modified, report link and filename are triage only; no grid opened, source rights or fishing spot approved.',
            'survey_count':len(known),'file_count':len(rows),'accessible_file_count':sum(row['status']=='ok' for row in rows),
            'native_review_hint_count':sum(row['status']=='ok' and row['native_review_hint'].startswith('filename-MLLW') for row in rows),
            'health':{'status':'ok' if not issues else 'degraded','issues':issues},'sectors':sectors,'files':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discovery',type=Path,required=True)
    parser.add_argument('--products',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--previous',type=Path)
    parser.add_argument('--max-age-days',type=int,default=30)
    args=parser.parse_args()
    discovery=json.loads(args.discovery.read_text())
    products=json.loads(args.products.read_text())
    previous=json.loads(args.previous.read_text()) if args.previous and args.previous.is_file() else None
    now=datetime.now(timezone.utc)
    urls={url for row in products.get('surveys',[]) for url in row.get('products',{}).get('bag',[])}
    if previous and previous.get('health',{}).get('status')=='ok' and previous.get('last_complete_scan_at'):
        age=now-datetime.fromisoformat(previous['last_complete_scan_at'])
        if timedelta(0)<=age<timedelta(days=args.max_age_days) and urls=={row['url'] for row in previous.get('files',[])}:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_bytes(args.previous.read_bytes())
            print('Retained complete BAG HEAD inventory from '+previous['last_complete_scan_at'])
            return
    result=inventory(discovery,products,previous,now=now)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    tmp=args.output.with_suffix(args.output.suffix+'.tmp')
    tmp.write_text(json.dumps(result,separators=(',',':'),ensure_ascii=False)+'\n')
    tmp.replace(args.output)
    print(f"{result['health']['status']}: {result['accessible_file_count']}/{result['file_count']} BAG links accessible; {result['native_review_hint_count']} metadata review hints")


if __name__=='__main__':main()
