"""Read original USGS map-block XML bounds and substrate definitions.

Metadata bounds are discovery coverage only; they do not mean all pixels in a
rectangle are surveyed or that a fishing location has been validated.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from discover_usgs_map_blocks import approved

MAX_XML = 1_500_000


def fetch(url):
    if not approved(url) or '/metadata/' not in url or not url.endswith('.xml'):
        raise ValueError('USGS XML URL outside reviewed catalog')
    with urlopen(Request(url, headers={'User-Agent':'SkipperCast USGS metadata audit/1.0'}), timeout=20) as response:
        if not approved(response.url):
            raise ValueError('USGS XML redirected outside reviewed host')
        raw=response.read(MAX_XML+1)
        if len(raw)>MAX_XML:
            raise ValueError('USGS XML exceeds size limit')
    return raw


def parse_metadata(url, raw, *, now):
    root=ET.fromstring(raw)
    bound=root.find('.//bounding')
    if bound is None:
        raise ValueError('USGS XML lacks geographic bounding box')
    box={key:float(bound.findtext(key)) for key in ('westbc','eastbc','southbc','northbc')}
    if not (-180<=box['westbc']<box['eastbc']<=180 and -90<=box['southbc']<box['northbc']<=90):
        raise ValueError('Invalid USGS geographic bounds')
    definitions=[]
    categorical=[]
    for attr in root.findall('.//attr'):
        name=(attr.findtext('attrlabl') or '').strip()
        if name.upper() in {'SUBSTRATE','SUBST_DESC','FULL_DESC'}:
            definitions.append({'field':name,'definition':(attr.findtext('attrdef') or '').strip()[:1800]})
        if name.upper() in {'VALUE','CLASS','SUBSTRATE'}:
            for domain in attr.findall('.//edom'):
                code=(domain.findtext('edomv') or '').strip()
                label=(domain.findtext('edomvd') or '').strip()
                if code and label:categorical.append({'field':name,'code':code[:30],'label':label[:250]})
    projection=(root.findtext('.//mapprojn') or '').strip()
    horizontal=(root.findtext('.//horizdn') or '').strip()
    # Explicit metadata-backed fallback for a few USGS TIFFs missing embedded
    # CRS. No location-derived or filename-derived CRS guess is allowed.
    projected_crs='EPSG:32611' if projection=='WGS 1984 UTM Zone 11N' and horizontal=='D WGS 1984' else None
    return {'metadata_url':url,'status':'ok','checked_at':now.isoformat(),'xml_sha256':hashlib.sha256(raw).hexdigest(),
            'bounds':box,'title':(root.findtext('.//title') or '').strip()[:200],
            'published_date':(root.findtext('.//pubdate') or '').strip()[:20],
            'native_projection_name':projection,'native_horizontal_datum':horizontal,
            'metadata_projected_crs':projected_crs,
            'substrate_definitions':definitions,'categorical_classes':categorical,'issue':None}


def audit(blocks, previous=None, *, now=None, fetcher=fetch):
    now=now or datetime.now(timezone.utc)
    if blocks.get('scope')!='usgs-state-waters-map-block-links' or blocks.get('block_count')!=len(blocks.get('blocks',[])):
        raise ValueError('Invalid USGS map-block inventory')
    targets={}
    for block in blocks['blocks']:
        for kind,products in block['products'].items():
            if kind in {'bathymetry','seafloor_character'}:
                for item in products:
                    url=item['metadata_url']
                    if not approved(url) or f"/{block['id']}/metadata/" not in url:
                        raise ValueError('USGS metadata URL does not match block')
                    targets[url]=(block['id'],kind)
    prior={row['metadata_url']:row for row in (previous or {}).get('records',[])}
    rows=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending={pool.submit(fetcher,url):url for url in targets}
        for future in as_completed(pending):
            url=pending[future]
            ident,kind=targets[url]
            try:
                rows.append({'block_id':ident,'kind':kind,**parse_metadata(url,future.result(),now=now)})
            except (OSError,TimeoutError,ValueError,ET.ParseError,TypeError) as error:
                older=prior.get(url)
                rows.append({**older,'status':'retained','issue':str(error)[:180]} if older else
                            {'block_id':ident,'kind':kind,'metadata_url':url,'status':'failed','checked_at':None,
                             'xml_sha256':None,'bounds':None,'substrate_definitions':[],'issue':str(error)[:180]})
    rows.sort(key=lambda row:(row['block_id'],row['kind']))
    issues=[row['metadata_url'] for row in rows if row['status']!='ok']
    return {'schema_version':1,'scope':'usgs-state-waters-native-metadata','collected_at':now.isoformat(),
            'last_complete_scan_at':now.isoformat() if not issues else (previous or {}).get('last_complete_scan_at'),
            'method':'Original USGS XML descriptions and bounding rectangles. Bounds do not imply complete pixel coverage; raster values, depth datum and legal clearance require later native review.',
            'record_count':len(rows),'verified_metadata_count':sum(row['status']=='ok' for row in rows),
            'health':{'status':'ok' if not issues else 'degraded','issues':issues},'records':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blocks',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--previous',type=Path)
    parser.add_argument('--max-age-days',type=int,default=30)
    args=parser.parse_args()
    blocks=json.loads(args.blocks.read_text())
    previous=json.loads(args.previous.read_text()) if args.previous and args.previous.is_file() else None
    now=datetime.now(timezone.utc)
    if previous and previous.get('health',{}).get('status')=='ok' and previous.get('last_complete_scan_at'):
        age=now-datetime.fromisoformat(previous['last_complete_scan_at'])
        if timedelta(0)<=age<timedelta(days=args.max_age_days):
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_bytes(args.previous.read_bytes())
            print('Retained complete USGS metadata audit from '+previous['last_complete_scan_at'])
            return
    result=audit(blocks,previous,now=now)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+'.tmp')
    temp.write_text(json.dumps(result,separators=(',',':'),ensure_ascii=False)+'\n')
    temp.replace(args.output)
    print(f"{result['health']['status']}: {result['verified_metadata_count']}/{result['record_count']} original XML records with geographic bounds")


if __name__=='__main__':main()
