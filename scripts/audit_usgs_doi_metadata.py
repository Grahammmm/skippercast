"""Audit original XML metadata from newer USGS DS781 DOI releases."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from audit_usgs_map_metadata import parse_metadata, MAX_XML
from discover_usgs_doi_releases import official


def fetch(url):
    with urlopen(Request(url,headers={'User-Agent':'SkipperCast USGS original metadata review/1.0'}),timeout=25) as response:
        raw=response.read(MAX_XML+1)
        if len(raw)>MAX_XML:raise ValueError('USGS XML exceeds size limit')
        return response.url,raw


def audit(releases,previous=None,*,now=None,fetcher=fetch):
    now=now or datetime.now(timezone.utc)
    if releases.get('scope')!='usgs-state-waters-doi-product-links':raise ValueError('Wrong USGS DOI scope')
    tasks=[]
    for release in releases['releases']:
        ident=release['release_id'];landing=release['landing_url']
        if not landing:continue
        for product in release['products']:
            url=product['metadata_url']
            if not official(url,ident,landing):raise ValueError('Original XML URL outside reviewed DOI release')
            tasks.append((release,product))
    prior={r['metadata_url']:r for r in (previous or {}).get('records',[])}
    rows=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending={pool.submit(fetcher,p['metadata_url']):(r,p) for r,p in tasks}
        for future in as_completed(pending):
            release,product=pending[future]
            ident=release['release_id'];url=product['metadata_url']
            try:
                final,raw=future.result()
                if not official(final,ident,release['landing_url']):raise ValueError('USGS XML redirected outside reviewed DOI release')
                parsed=parse_metadata(url,raw,now=now)
                rows.append({'release_id':ident,'study_areas':release['study_areas'],'kind':product['kind'],
                             'archive_url':product['archive_url'],'filename':product['filename'],**parsed})
            except (OSError,TimeoutError,ValueError,ET.ParseError,TypeError) as error:
                old=prior.get(url)
                rows.append({**old,'status':'retained','issue':str(error)[:180]} if old else
                            {'release_id':ident,'study_areas':release['study_areas'],'kind':product['kind'],
                             'archive_url':product['archive_url'],'filename':product['filename'],
                             'metadata_url':url,'status':'failed','issue':str(error)[:180]})
    rows.sort(key=lambda row:(row['release_id'],row['kind'],row['filename']))
    issues=[row['metadata_url'] for row in rows if row['status']!='ok']
    return {'schema_version':1,'scope':'usgs-state-waters-doi-native-metadata',
            'collected_at':now.isoformat(),'last_complete_scan_at':now.isoformat() if not issues else (previous or {}).get('last_complete_scan_at'),
            'method':'Original CMGDS metadata XML linked from a USGS DOI release. Bounds and class descriptions are source evidence only, not surveyed-pixel or fishing coverage.',
            'record_count':len(rows),'verified_metadata_count':len(rows)-len(issues),
            'health':{'status':'ok' if not issues else 'degraded','issues':issues},'records':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--releases',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--previous',type=Path)
    parser.add_argument('--max-age-days',type=int,default=30)
    args=parser.parse_args()
    previous=json.loads(args.previous.read_text()) if args.previous and args.previous.is_file() else None
    now=datetime.now(timezone.utc)
    if previous and previous.get('health',{}).get('status')=='ok' and previous.get('last_complete_scan_at'):
        age=now-datetime.fromisoformat(previous['last_complete_scan_at'])
        if timedelta(0)<=age<timedelta(days=args.max_age_days):
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_bytes(args.previous.read_bytes())
            print('Retained complete USGS DOI metadata audit from '+previous['last_complete_scan_at']);return
    result=audit(json.loads(args.releases.read_text()),previous,now=now)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+'.tmp')
    temp.write_text(json.dumps(result,separators=(',',':'),ensure_ascii=False)+'\n')
    temp.replace(args.output)
    print(f"{result['health']['status']}: {result['verified_metadata_count']}/{result['record_count']} DOI XML records checked")


if __name__=='__main__':main()
