"""Bounded native NOAA BAG scan for statewide MLLW depth-source review.

The BAG overview is used only to locate a survey and identify masks. Variable
resolution refinements, substrate, current rules and MPA exclusions require a
separate target compiler. This script produces no fishing waypoints.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from urllib.request import Request, urlopen

import h5py
import numpy as np
import rasterio
from rasterio.warp import transform_bounds

from skippercast.platform.bottom_targets import bag_metadata, source_url_allowed

DEFAULT_MAX_BYTES=20_000_000
# h5py/GDAL native readers can crash when different BAGs are opened in
# parallel. Downloads stay concurrent; native inspection is serialized.
NATIVE_READ_LOCK=threading.Lock()


def download(url,path,max_bytes):
    if not source_url_allowed(url) or not url.lower().endswith('.bag'):
        raise ValueError('Unreviewed NOAA BAG URL')
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.part')
    try:
        with urlopen(Request(url,headers={'User-Agent':'SkipperCast native NOAA BAG review/1.0'}),timeout=40) as response,temp.open('wb') as out:
            if response.url!=url:raise ValueError('NOAA BAG redirected')
            total=0
            while chunk:=response.read(1024*1024):
                total+=len(chunk)
                if total>max_bytes:raise ValueError('NOAA BAG exceeds download bound')
                out.write(chunk)
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)


def inspect_file(path,survey_id):
    with h5py.File(path,'r') as handle:
        root=handle['BAG_root']
        raw=root['metadata'][:].tobytes().decode('utf-8',errors='replace').rstrip('\0')
        try:
            meta=bag_metadata(raw,survey_id)
            metadata_status='mllw-product-uncertainty-reviewed-by-adapter'
            issue=None
        except ValueError as error:
            meta=None;metadata_status='requires-datum-or-uncertainty-review';issue=str(error)[:180]
        refinements=int(root['varres_refinements'].shape[-1]) if 'varres_refinements' in root else 0
        native_grids=native_cells=0
        native_min=native_max=None
        if 'varres_metadata' in root:
            grids=root['varres_metadata'][:]
            selected=((grids['dimensions_x']>0)&(grids['dimensions_y']>0)&
                      (grids['resolution_x']>0)&(grids['resolution_y']>0)&
                      (grids['resolution_x']<=4)&(grids['resolution_y']<=4))
            native_grids=int(np.count_nonzero(selected))
            if native_grids:
                native_cells=int(np.sum(grids['dimensions_x'][selected].astype('int64')*grids['dimensions_y'][selected].astype('int64')))
                native_min=float(min(grids['resolution_x'][selected].min(),grids['resolution_y'][selected].min()))
                native_max=float(max(grids['resolution_x'][selected].max(),grids['resolution_y'][selected].max()))
    with rasterio.open(path) as raster:
        if not raster.crs or raster.count<1:raise ValueError('BAG lacks georeferenced overview')
        bounds=transform_bounds(raster.crs,'EPSG:4326',*raster.bounds,densify_pts=21)
        valid=0;minimum=float('inf');maximum=float('-inf')
        for _,window in raster.block_windows(1):
            values=raster.read(1,window=window,masked=True).compressed()
            values=values[np.isfinite(values)]
            if len(values):
                valid+=len(values);minimum=min(minimum,float(values.min()));maximum=max(maximum,float(values.max()))
        if not valid:raise ValueError('BAG overview has no finite elevations')
        return {'raster_bounds_wgs84':[round(v,7) for v in bounds],
                'overview_width':raster.width,'overview_height':raster.height,
                'overview_resolution_m':[float(v) for v in raster.res],
                'overview_valid_cells':valid,'overview_total_cells':raster.width*raster.height,
                'overview_min_elevation_m':minimum,'overview_max_elevation_m':maximum,
                'variable_refinement_records':refinements,
                'refinement_grids_at_most_4m':native_grids,
                'refinement_cells_at_most_4m':native_cells,
                'refinement_resolution_range_m':[native_min,native_max] if native_grids else None,
                'metadata_status':metadata_status,'metadata_issue':issue,
                'vertical_datum':meta['vertical_datum'] if meta else None,
                'uncertainty_type':meta['uncertainty_type'] if meta else None,
                'survey_start':meta['survey_start'] if meta else None,
                'survey_end':meta['survey_end'] if meta else None,
                'metadata_sha256':meta['metadata_sha256'] if meta else hashlib.sha256(raw.encode()).hexdigest()}


def scan(inventory,products,cache,*,max_bytes=DEFAULT_MAX_BYTES,fetcher=download,max_workers=4,
         survey_ids=None):
    if inventory.get('scope')!='noaa-bag-head-inventory' or products.get('scope')!='noaa-survey-product-links':
        raise ValueError('Wrong NOAA source inventory scope')
    surveys={s['id']:s for s in products['surveys']}
    selected=[r for r in inventory['files'] if r['status']=='ok' and r['bytes']<=max_bytes
              and 'MLLW' in r['url'].upper() and (survey_ids is None or r['survey_id'] in survey_ids)]
    if survey_ids is not None and set(survey_ids) != {row['survey_id'] for row in selected}:
        raise ValueError('Requested survey has no accessible MLLW BAG within the selected bound')
    def one(row):
        url=row['url'];ident=row['survey_id']
        if ident not in surveys or url not in surveys[ident]['products']['bag']:
            raise ValueError('BAG does not match original survey catalog')
        local=cache/(ident+'-'+hashlib.sha256(url.encode()).hexdigest()[:16]+'.bag')
        if not local.is_file():fetcher(url,local,max_bytes)
        if local.stat().st_size!=row['bytes']:
            raise ValueError('NOAA BAG size changed since HEAD inventory')
        with NATIVE_READ_LOCK:
            native=inspect_file(local,ident)
        with local.open('rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
        return {'survey_id':ident,'url':url,'source_report_url':(surveys[ident]['products']['report'] or [None])[0],
                'file_sha256':digest,
                'file_bytes':local.stat().st_size,'status':'ok',
                'inspected_at':datetime.now(timezone.utc).isoformat(),
                **native}
    rows=[]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        pending={pool.submit(one,row):row for row in selected}
        for future in as_completed(pending):
            row=pending[future]
            try:rows.append(future.result())
            except (OSError,TimeoutError,ValueError,KeyError,TypeError) as error:
                rows.append({'survey_id':row['survey_id'],'url':row['url'],'status':'failed','issue':str(error)[:180]})
    rows.sort(key=lambda row:(row['survey_id'],row['url']))
    issues=[row['url'] for row in rows if row['status']!='ok']
    return {'schema_version':1,'scope':'noaa-original-bag-native-overview-audit',
            'collected_at':datetime.now(timezone.utc).isoformat(),
            'method':'Original bounded NOAA BAG downloads; embedded metadata, overview valid cells, WGS84 bounds and variable-resolution refinement metadata inspected. Individual refinement depth/uncertainty cells, substrate, legal depth and MPA geometry are not qualified by this audit.',
            'selection':'Original MLLW-named BAG files <= selected max_bytes; omitted files remain in BAG HEAD inventory.',
            'max_bytes':max_bytes,'file_count':len(rows),'inspected_count':len(rows)-len(issues),
            'mllw_metadata_count':sum(r.get('metadata_status')=='mllw-product-uncertainty-reviewed-by-adapter' for r in rows),
            'health':{'status':'ok' if not issues else 'degraded','issues':issues},'files':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('inventory','products','cache','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--max-bytes',type=int,default=DEFAULT_MAX_BYTES)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--survey-id',action='append',help='Review only these original survey IDs')
    args=parser.parse_args()
    if not 1<=args.workers<=8 or not 1<=args.max_bytes<=200_000_000:raise ValueError('Unsupported native BAG scan bound')
    if args.max_bytes>100_000_000 and not args.survey_id:
        raise ValueError('Large native BAG review requires explicit --survey-id selection')
    result=scan(json.loads(args.inventory.read_text()),json.loads(args.products.read_text()),args.cache,
                max_bytes=args.max_bytes,max_workers=args.workers,survey_ids=args.survey_id)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+'.tmp')
    temp.write_text(json.dumps(result,separators=(',',':'))+'\n')
    temp.replace(args.output)
    print(f"{result['health']['status']}: {result['inspected_count']}/{result['file_count']} original NOAA BAG overviews, {result['mllw_metadata_count']} MLLW/productUncert metadata")


if __name__=='__main__':main()
