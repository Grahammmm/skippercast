"""Discover newer USGS DS781 DOI releases omitted by the legacy HTML catalogs.

Only official DOI links in the DS781 index are followed. Files must live under
the same official CMGDS release path. This publishes source links, not habitat.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from discover_usgs_map_blocks import INDEX

DOI = re.compile(r'^https://doi\.org/10\.5066/([A-Z0-9]+)$')
MAX_PAGE=1_500_000
ADDITIONAL=Path('catalog/usgs-additional-doi-releases.json')


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__();self.items=[];self.current=None
    def handle_starttag(self,tag,attrs):
        if tag=='a':
            href=dict(attrs).get('href')
            if href:self.current=[href,[]]
    def handle_data(self,data):
        if self.current is not None:self.current[1].append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.current is not None:
            self.items.append((self.current[0],' '.join(self.current[1]).strip()))
            self.current=None


def index_dois(raw):
    parser=Anchors();parser.feed(raw.decode('utf-8',errors='replace'))
    releases={}
    for href,label in parser.items:
        match=DOI.fullmatch(href)
        if match and label.startswith('California State Waters Map Series Data Catalog'):
            entry=releases.setdefault(match.group(1),{'doi':href,'study_areas':[]})
            entry['study_areas'].append(label.split('—',1)[-1].strip()[:150])
    return releases


def with_reviewed_additions(entries, additions):
    """Include official releases omitted or mislinked by the DS781 HTML index."""
    if additions.get('schema_version') != 1 or additions.get('scope') != 'reviewed-usgs-ds781-doi-additions':
        raise ValueError('Unreviewed USGS DOI additions')
    result={ident:{**entry} for ident,entry in entries.items()}
    for row in additions['releases']:
        doi=row['doi'];match=DOI.fullmatch(doi)
        page=urlsplit(row['official_source_page'])
        if (not match or page.scheme!='https' or page.hostname!='www.usgs.gov'
                or not page.path.startswith('/data/') or not row.get('study_area') or not row.get('reason')):
            raise ValueError('USGS DOI addition lacks a reviewed official release page')
        ident=match.group(1)
        previous=result.get(ident)
        if previous and previous['doi']!=doi:
            raise ValueError('USGS DOI identity conflicts with the DS781 index: '+ident)
        result[ident]={'doi':doi,'study_areas':list(dict.fromkeys([
                           *(previous['study_areas'] if previous else []),row['study_area']])),
                       'official_source_page':row['official_source_page'],
                       'discovery_note':row['reason']}
    return result


def official(url,ident,landing=None):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname!='cmgds.marine.usgs.gov' or p.port not in (None,443):return False
    if p.path.startswith('/data-releases/'):
        return f'/10.5066-{ident}/' in p.path and (p.path.startswith('/data-releases/media/') or p.path.startswith('/data-releases/datarelease/'))
    if p.path.startswith('/data/csmp/'):
        if landing is None:return p.path.endswith('.html') and '/data_catalog_' in p.path
        prefix=urlsplit(landing).path.rsplit('/',1)[0]+'/'
        return p.path.startswith(prefix) and p.path[len(prefix):].startswith(('data/','metadata/'))
    return False


def fetch(url):
    request=Request(url,headers={'User-Agent':'SkipperCast USGS DOI release discovery/1.0'})
    with urlopen(request,timeout=30) as response:
        raw=response.read(MAX_PAGE+1)
        if len(raw)>MAX_PAGE:raise ValueError('USGS DOI release page exceeds size limit')
        return response.url,raw


def inspect(entry,*,now,fetcher=fetch):
    ident=entry['doi'].rsplit('/',1)[-1]
    landing,raw=fetcher(entry['doi'])
    if not official(landing,ident):raise ValueError('DOI did not resolve to reviewed USGS release')
    parser=Anchors();parser.feed(raw.decode('utf-8',errors='replace'))
    links={}
    for href,_ in parser.items:
        url=urljoin(landing,href)
        if not official(url,ident,landing):continue
        base=urlsplit(url).path.rsplit('/',1)[-1]
        if base.lower().endswith(('.zip','.xml')):links[base]=url
    products=[]
    for base,url in links.items():
        if not base.lower().endswith('.zip'):continue
        kind=('seafloor_character' if base.lower().startswith('seafloorcharacter_') else
              'bathymetry' if base.lower().startswith('bathymetry_') else
              'cmecs' if base.lower().startswith('cmecs_') else None)
        if not kind:continue
        stem=base[:-4]
        xml=next((value for filename,value in links.items() if filename.lower() in {(stem+'_metadata.xml').lower(),(stem+'.xml').lower()}),None)
        if xml:products.append({'kind':kind,'archive_url':url,'metadata_url':xml,'filename':base})
    products.sort(key=lambda row:(row['kind'],row['filename']))
    return {'doi':entry['doi'],'release_id':ident,'study_areas':entry['study_areas'],
            'official_source_page':entry.get('official_source_page'),
            'discovery_note':entry.get('discovery_note'),'landing_url':landing,
            'landing_sha256':hashlib.sha256(raw).hexdigest(),'checked_at':now.isoformat(),
            'status':'ok','products':products,'issue':None}


def discover(previous=None,*,now=None,fetcher=fetch,additions=None):
    now=now or datetime.now(timezone.utc)
    final,raw=fetcher(INDEX)
    if final!=INDEX:raise ValueError('USGS DS781 index unexpectedly redirected')
    entries=index_dois(raw)
    if len(entries)<10:raise ValueError('USGS DS781 index omitted expected DOI releases')
    if additions is not None:entries=with_reviewed_additions(entries,additions)
    additional_sha256=(hashlib.sha256(json.dumps(additions,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                       if additions is not None else None)
    old={row['release_id']:row for row in (previous or {}).get('releases',[])}
    rows=[]
    with ThreadPoolExecutor(max_workers=5) as pool:
        pending={pool.submit(inspect,entry,now=now,fetcher=fetcher):ident for ident,entry in entries.items()}
        for future in as_completed(pending):
            ident=pending[future]
            try:rows.append(future.result())
            except (OSError,TimeoutError,ValueError,UnicodeError) as error:
                prior=old.get(ident)
                rows.append({**prior,'status':'retained','issue':str(error)[:180]} if prior else
                            {'doi':entries[ident]['doi'],'release_id':ident,'study_areas':entries[ident]['study_areas'],
                             'landing_url':None,'landing_sha256':None,'checked_at':None,'status':'failed','products':[],
                             'issue':str(error)[:180]})
    rows.sort(key=lambda row:row['release_id'])
    issues=[row['release_id'] for row in rows if row['status']!='ok']
    return {'schema_version':1,'scope':'usgs-state-waters-doi-product-links','collected_at':now.isoformat(),
            'last_complete_scan_at':now.isoformat() if not issues else (previous or {}).get('last_complete_scan_at'),
            'index_url':INDEX,'index_sha256':hashlib.sha256(raw).hexdigest(),
            'additional_sha256':additional_sha256,
            'method':'Official DS781 DOI links plus separately reviewed official USGS release-page additions resolved to matching CMGDS pages; original archive and XML links only. No native raster or fishing area approved.',
            'release_count':len(rows),'product_count':sum(len(row['products']) for row in rows),
            'health':{'status':'ok' if not issues else 'degraded','issues':issues},'releases':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--previous',type=Path)
    parser.add_argument('--max-age-days',type=int,default=30)
    parser.add_argument('--additional',type=Path,default=ADDITIONAL)
    args=parser.parse_args()
    old=json.loads(args.previous.read_text()) if args.previous and args.previous.is_file() else None
    additions=json.loads(args.additional.read_text()) if args.additional.is_file() else None
    additional_sha256=(hashlib.sha256(json.dumps(additions,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                       if additions is not None else None)
    now=datetime.now(timezone.utc)
    if (old and old.get('health',{}).get('status')=='ok' and old.get('last_complete_scan_at')
            and old.get('additional_sha256')==additional_sha256):
        age=now-datetime.fromisoformat(old['last_complete_scan_at'])
        if timedelta(0)<=age<timedelta(days=args.max_age_days):
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_bytes(args.previous.read_bytes())
            print('Retained complete USGS DOI inventory from '+old['last_complete_scan_at']);return
    result=discover(old,now=now,additions=additions)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+'.tmp')
    temp.write_text(json.dumps(result,separators=(',',':'),ensure_ascii=False)+'\n')
    temp.replace(args.output)
    print(f"{result['health']['status']}: {result['release_count']} DOI releases, {result['product_count']} linked native products")


if __name__=='__main__':main()
