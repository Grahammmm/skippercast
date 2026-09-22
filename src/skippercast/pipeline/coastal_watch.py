"""Daily public coastal source watch. Retrieval never approves law or proves fish presence."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
import hashlib
import re
import subprocess
import tempfile
import ssl
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from pathlib import Path
from .collect import Client, source, stamp, age_hours
from ..platform.contracts import REPO, read_json, atomic_json
from ..platform.coasts import compile_coasts

MPA = 'https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query'


class CoastalClient(Client):
    def get(self, url, as_json=False, **kwargs):
        try:
            return super().get(url, as_json, **kwargs)
        except URLError as error:
            # macOS' system TLS store can complete CDFW's chain when Python cannot.
            # No redirects or relaxed TLS. Only these fixed, reviewed HTML documents qualify.
            allowed={r['rules_url'] for r in read_json(REPO/'catalog/coasts.json')['regions']}
            if url not in allowed or as_json or not isinstance(error.reason, ssl.SSLCertVerificationError): raise
            with tempfile.TemporaryDirectory() as folder:
                body=Path(folder)/'body';headers=Path(folder)/'headers'
                subprocess.run(['/usr/bin/curl','--fail','--silent','--show-error','--proto','=https','--max-time','25','--max-filesize','5000000','--dump-header',str(headers),'--output',str(body),url],check=True,capture_output=True,timeout=30)
                raw=body.read_bytes();head=headers.read_text()
                if len(raw)>5_000_000 or not re.search(r'^HTTP/\S+ 200\b',head,re.M) or 'text/html' not in head.lower(): raise ValueError('Invalid CDFW HTML response')
                self.requests.append({'url':url,'final_url':url,'retrieved_at':stamp(),'http_status':200,'bytes':len(raw),
                                      'sha256':hashlib.sha256(raw).hexdigest(),'transport':'system curl; TLS verified; redirects disabled'})
                return raw.decode('utf-8')


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.skip += 1
    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.skip = max(0, self.skip - 1)
    def handle_data(self, text):
        if not self.skip: self.parts.append(text)


def page_text(html):
    p = PageText(); p.feed(html)
    return ' '.join(' '.join(p.parts).split())


def parse_enso(html):
    text = page_text(html)
    status = re.search(r'ENSO Alert System Status:\s*((?:El Niño|La Niña) (?:Advisory|Watch)|Not Active|Final (?:El Niño|La Niña) Advisory)', text, re.I)
    date = re.search(r'\b(\d{1,2} [A-Za-z]+ 20\d{2})\b', text)
    if not status or not date: raise ValueError('NOAA advisory status or issue date absent')
    return {'status': status.group(1), 'published_date': datetime.strptime(date.group(1), '%d %B %Y').date().isoformat(),
            'date_precision': 'day', 'content_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'meaning': 'Equatorial Pacific climate context, not a California fish observation or local SST measurement.'}


def parse_rules(html, region):
    text = page_text(html)
    title = 'Current California Ocean Recreational Fishing Regulations - ' + region['name'] + ' Region'
    if title.lower() not in text.lower(): raise ValueError('Wrong regional regulation document')
    date = re.search(r'summary of current regulations was updated on ([A-Za-z]+ \d{1,2}, 20\d{2})', text, re.I)
    if not date: raise ValueError('CDFW summary update date absent')
    # Strip the site header/footer so unrelated menu changes do not trigger review.
    main = text[text.lower().index(title.lower()):].split('Marine Region (Region 7)')[0]
    return {'published_date': datetime.strptime(date.group(1), '%B %d, %Y').date().isoformat(),
            'content_sha256': hashlib.sha256(main.encode()).hexdigest(), 'permission_to_fish': None,
            'interpretation': 'Official document watch only. Date, method, depth, species and local closures still require the actual regulations.'}


def mpa_loader(client):
    count = client.get(MPA + '?' + urlencode({'where':'1=1','returnCountOnly':'true','f':'json'}), True).get('count')
    if not isinstance(count, int) or not 100 <= count <= 500: raise ValueError('Unexpected statewide MPA inventory')
    url = MPA + '?' + urlencode({'where':'1=1','outFields':'NAME,FULLNAME,Type,CCR','returnGeometry':'true','outSR':4326,'f':'geojson','resultRecordCount':1000})
    geo = client.get(url, True)
    if geo.get('exceededTransferLimit') or len(geo.get('features', [])) != count: raise ValueError('Incomplete statewide MPA boundaries')
    if any(f.get('geometry', {}).get('type') not in ('Polygon','MultiPolygon') or not isinstance(f.get('properties',{}).get('NAME'),str) for f in geo['features']):
        raise ValueError('Invalid MPA feature')
    return {'geojson':geo,'feature_count':count,'source_url':url}


def located_reports(coast, reports, now, policy):
    """Only location-bearing, recent observations can support a candidate. A port is not a position."""
    accepted = {}
    today = now.date()
    for report in reports:
        try:
            day = datetime.strptime(report['date'], '%Y-%m-%d').date()
            lon, lat = report['coordinates']
            w,s,e,n = coast['bounds']
            host = (urlsplit(report['source_url']).hostname or '').removeprefix('www.')
            if not (today-timedelta(days=policy['report_max_age_days']) <= day <= today and w <= lon <= e and s <= lat < n and host): continue
            if report.get('coordinate_role') != 'fishing-observation' or report.get('location_review') != 'reviewed': continue
            # Syndicated reports must carry their reviewed original publisher, not the mirror's domain.
            publisher=report.get('original_publisher_id')
            if not isinstance(publisher,str) or not publisher or report.get('publisher_review')!='reviewed' or urlsplit(report['source_url']).scheme!='https': continue
            for catch in report['catches']:
                ident = catch['species']
                if ident in coast['watch'] and isinstance(catch.get('count'), (int,float)) and catch['count'] > 0:
                    accepted.setdefault(ident, {})[(publisher,report['date'])] = {'date':report['date'],'url':report['source_url'],'publisher':publisher}
        except (TypeError, ValueError, KeyError): continue
    result=[]
    for ident in coast['watch']:
        evidence=list(accepted.get(ident, {}).values())
        supported = len({r['publisher'] for r in evidence}) >= policy['minimum_independent_sources'] and len({r['date'] for r in evidence}) >= policy['minimum_report_dates']
        result.append({'target':ident,'status':'recent-located-reports' if supported else 'watch-only','evidence':evidence[:10],
                       'catch_probability':None,'auto_add_to_qualified_map':False})
    return result


def collect(now=None, previous=None, reports=None, client_factory=CoastalClient):
    now=now or datetime.now(timezone.utc); previous=previous or {}; directory=compile_coasts()
    prior=previous.get('sources',{}) if previous.get('scope')=='california-coast-directory' else {}
    jobs=[('enso','NOAA ENSO advisory','page-watch',directory['enso_url'],1080,lambda c:parse_enso(c.get(directory['enso_url']))),
          ('mpas','CDFW statewide MPAs','boundaries',MPA,36,mpa_loader)]
    for r in directory['regions']:
        jobs.append((r['id']+'-rules','CDFW '+r['name'],'page-watch',r['rules_url'],36,lambda c,r=r:parse_rules(c.get(r['rules_url']),r)))
    def run(job):
        ident,name,kind,url,max_age,loader=job
        record=source(ident,name,kind,url,max_age,loader,now,prior.get(ident),client_factory)
        if ident=='enso' and record.get('data'):
            age=age_hours(record['data']['published_date']+'T00:00:00Z',now)
            if age is None or age < -24 or age > directory['policy']['enso_max_age_days']*24:
                record.update(status='stale',issue='Advisory issue date is outside the monthly freshness window')
        return ident,record
    with ThreadPoolExecutor(max_workers=4) as pool: sources=dict(pool.map(run,jobs))
    issues=[key for key,s in sources.items() if s['status']!='ok']
    return {'schema_version':1,'scope':'california-coast-directory','completed_at':stamp(now),'sources':sources,
            'regions':{r['id']:{'watch':located_reports(r,reports or [],now,directory['policy'])} for r in directory['regions']},
            'health':{'status':'degraded' if issues else 'ok','issues':issues},'policy':directory['policy']}


def run(output, previous_root=None, report_root=None):
    old=previous_root/'coastal/latest.json' if previous_root else None
    previous=read_json(old) if old and old.is_file() else None
    reports=[]
    if report_root:
        for p in report_root.glob('regions/*/latest.json'):
            feed=read_json(p)
            if feed.get('region_id')==p.parent.name: reports.extend(feed.get('reports',[]))
    data=collect(previous=previous,reports=reports)
    atomic_json(output/'coastal/latest.json',data)
    # Separate geometry keeps routine species/status downloads small.
    public={**data,'sources':{k:{**v,'data':{kk:vv for kk,vv in (v.get('data') or {}).items() if kk!='geojson'}} for k,v in data['sources'].items()}}
    atomic_json(output/'coastal/status.json',public)
    return data


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--previous-root',type=Path);parser.add_argument('--report-root',type=Path)
    a=parser.parse_args();data=run(a.output,a.previous_root,a.report_root)
    print(data['health'])
