"""Inspect original USGS DOI release rasters with their own XML metadata."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
import zipfile

import rasterio

from discover_usgs_doi_releases import official
from inspect_usgs_native_grids import inspect_archive, MAX_ARCHIVE_BYTES


def download(url,path,ident,landing):
    if not official(url,ident,landing) or not url.endswith('.zip'):
        raise ValueError('USGS archive outside reviewed DOI release')
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.part')
    try:
        with urlopen(Request(url,headers={'User-Agent':'SkipperCast native USGS DOI grid review/1.0'}),timeout=45) as response,temp.open('wb') as out:
            if not official(response.url,ident,landing):raise ValueError('USGS archive redirected outside reviewed DOI release')
            total=0
            while chunk:=response.read(1024*1024):
                total+=len(chunk)
                if total>MAX_ARCHIVE_BYTES:raise ValueError('USGS archive exceeds download bound')
                out.write(chunk)
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)


def inspect(releases,metadata,cache,*,fetcher=download,max_workers=3):
    if releases.get('scope')!='usgs-state-waters-doi-product-links' or metadata.get('scope')!='usgs-state-waters-doi-native-metadata':
        raise ValueError('Invalid USGS DOI source inventory')
    meta={row['metadata_url']:row for row in metadata['records'] if row['status']=='ok'}
    tasks=[]
    for release in releases['releases']:
        if release['status']!='ok':continue
        for product in release['products']:
            if product['kind'] not in {'bathymetry','seafloor_character'}:continue
            record=meta.get(product['metadata_url'])
            if record:tasks.append((release,product,record))
    def one(task):
        release,product,record=task
        ident=release['release_id'];url=product['archive_url']
        if not official(url,ident,release['landing_url']):raise ValueError('Unreviewed USGS DOI archive')
        digest=hashlib.sha256(url.encode()).hexdigest()[:16]
        local=cache/f'{ident}-{product["kind"]}-{digest}.zip'
        if not local.is_file():fetcher(url,local,ident,release['landing_url'])
        actual=hashlib.sha256(local.read_bytes()).hexdigest()
        description=product['filename'].replace('_2m_',' (2m/pixel) ').replace('_5m_',' (5m/pixel) ')
        return {'release_id':ident,'study_areas':release['study_areas'],'kind':product['kind'],
                'archive_url':url,'metadata_url':record['metadata_url'],'archive_sha256':actual,
                'archive_bytes':local.stat().st_size,'metadata_sha256':record['xml_sha256'],
                'status':'ok','surveyed_at':datetime.now(timezone.utc).isoformat(),
                **inspect_archive(local,record,description)}
    rows=[]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        pending={pool.submit(one,task):task for task in tasks}
        for future in as_completed(pending):
            release,product,record=pending[future]
            try:rows.append(future.result())
            except (OSError,TimeoutError,ValueError,zipfile.BadZipFile,rasterio.errors.RasterioError) as error:
                rows.append({'release_id':release['release_id'],'kind':product['kind'],
                             'archive_url':product['archive_url'],'metadata_url':record['metadata_url'],
                             'status':'failed','issue':str(error)[:180]})
    rows.sort(key=lambda row:(row['release_id'],row['kind'],row['archive_url']))
    issues=[row['archive_url'] for row in rows if row['status']!='ok']
    return {'schema_version':1,'scope':'usgs-state-waters-doi-native-grid-audit',
            'collected_at':datetime.now(timezone.utc).isoformat(),
            'method':'Original DOI-linked USGS ZIP and native GeoTIFF pixel inspection. Historical seabed evidence only; no depth-datum conversion, fish prediction or legal clearance.',
            'product_count':len(rows),'inspected_count':len(rows)-len(issues),
            'health':{'status':'ok' if not issues else 'degraded','issues':issues},'products':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('releases','metadata','cache','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--workers',type=int,default=3)
    args=parser.parse_args()
    if not 1<=args.workers<=6:raise ValueError('workers must be 1–6')
    result=inspect(json.loads(args.releases.read_text()),json.loads(args.metadata.read_text()),args.cache,max_workers=args.workers)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+'.tmp')
    temp.write_text(json.dumps(result,separators=(',',':'),ensure_ascii=False)+'\n')
    temp.replace(args.output)
    print(f"{result['health']['status']}: {result['inspected_count']}/{result['product_count']} DOI native grids inspected")


if __name__=='__main__':main()
