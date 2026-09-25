"""Download and inspect original USGS DS781 GeoTIFF grids without inventing targets.

This is a review-stage, bounded native-raster scan. It never converts NAVD88
depth to MLLW, assumes a rectangular metadata footprint is fully measured, or
publishes a species-specific fishing location. Run with the optional survey GIS
dependencies in requirements-survey.txt.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
from urllib.request import Request, urlopen
import zipfile

import numpy as np
import rasterio
from rasterio.warp import transform_bounds
import shapefile

from discover_usgs_map_blocks import approved

MAX_ARCHIVE_BYTES = 300_000_000
MAX_TIFF_BYTES = 600_000_000
MAX_VAT_BYTES = 2_000_000


def parse_vat(raw, observed):
    """Read original raster value table; never infer substrate from a pixel number."""
    if not raw or len(raw) > MAX_VAT_BYTES:
        raise ValueError('Original raster value table is empty or oversized')
    reader = shapefile.Reader(dbf=BytesIO(raw))
    fields = [field[0].upper() for field in reader.fields[1:]]
    if not {'VALUE', 'COUNT', 'SUBSTRATE', 'SUBST_DESC'} <= set(fields):
        raise ValueError('Original raster value table lacks substrate definition columns')
    rows = {}
    for values in reader.records():
        item = dict(zip(fields, values))
        code = str(int(item['VALUE']))
        count = int(item['COUNT'])
        substrate = int(item['SUBSTRATE'])
        if (code in rows or count < 0 or not 1 <= substrate <= 5):
            raise ValueError('Original raster value table has duplicate or invalid class')
        rows[code] = {'value': int(code), 'count': count, 'substrate_class': substrate,
                      'substrate_description': str(item['SUBST_DESC']).strip()[:180]}
    if {key: row['count'] for key, row in rows.items()} != observed:
        raise ValueError('Original raster value table counts do not match native pixels')
    return sorted(rows.values(), key=lambda row: row['value'])


def download(url, path):
    if not approved(url) or '/data/' not in url or not url.endswith('.zip'):
        raise ValueError('Unreviewed USGS archive URL')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.part')
    try:
        with urlopen(Request(url, headers={'User-Agent':'SkipperCast native USGS grid review/1.0'}), timeout=45) as response, temp.open('wb') as out:
            if not approved(response.url):
                raise ValueError('USGS archive redirected outside reviewed host')
            total=0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError('USGS archive exceeds download bound')
                out.write(chunk)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def inspect_archive(path, record, description):
    with zipfile.ZipFile(path) as bundle:
        members=[info for info in bundle.infolist() if info.filename.lower().endswith('.tif') and not info.filename.startswith('__MACOSX/')]
        if len(members)>1:
            # Some original releases package separate 2 m and 5 m rasters.
            # Match the catalog's published resolution; never silently use
            # the first or the finer file as if it represented both products.
            expected='2m' if '2m/pixel' in description.lower() else '5m' if '5m/pixel' in description.lower() else None
            members=[info for info in members if expected and expected in info.filename.lower()]
        if len(members)!=1 or members[0].file_size > MAX_TIFF_BYTES or members[0].file_size <= 0:
            raise ValueError('USGS archive lacks one bounded resolution-matched GeoTIFF')
        member=members[0].filename
        vat_name = member + '.vat.dbf'
        vat_raw = bundle.read(vat_name) if vat_name in bundle.namelist() else None
    with rasterio.open(f'zip://{path.resolve()}!{member}') as raster:
        crs=raster.crs or record.get('metadata_projected_crs')
        if raster.count != 1 or not crs or raster.width <= 0 or raster.height <= 0:
            raise ValueError('USGS raster lacks one georeferenced data band')
        bound=transform_bounds(crs,'EPSG:4326',*raster.bounds,densify_pts=21)
        xml=record['bounds']
        # Metadata bounds and raster extents need not be identical, but gross
        # mismatches indicate a wrong archive or an unusable source binding.
        if not (bound[0] <= xml['eastbc'] and bound[2] >= xml['westbc'] and
                bound[1] <= xml['northbc'] and bound[3] >= xml['southbc']):
            raise ValueError('Native raster does not intersect its original XML bounds')
        valid=0
        minimum=float('inf')
        maximum=float('-inf')
        classes={}
        for _,window in raster.block_windows(1):
            data=raster.read(1,window=window,masked=True)
            values=data.compressed()
            if not len(values):
                continue
            values=values[np.isfinite(values)]
            if not len(values):
                continue
            valid+=len(values)
            minimum=min(minimum,float(values.min()))
            maximum=max(maximum,float(values.max()))
            if record['kind']=='seafloor_character':
                unique,counts=np.unique(values,return_counts=True)
                for code,count in zip(unique,counts):
                    if not float(code).is_integer() or len(classes)>100:
                        raise ValueError('Unexpected categorical class values')
                    key=str(int(code))
                    classes[key]=classes.get(key,0)+int(count)
        if not valid:
            raise ValueError('Native USGS raster contains no finite data')
        class_table = None
        class_table_status = None
        if record['kind']=='seafloor_character':
            class_table_status = 'missing-original-value-table' if vat_raw is None else 'verified'
            if vat_raw is not None:
                try:
                    class_table = parse_vat(vat_raw, classes)
                except (ValueError, shapefile.ShapefileException) as error:
                    class_table_status = 'unverified-original-value-table: ' + str(error)[:130]
        return {'native_width':raster.width,'native_height':raster.height,
                'native_crs':raster.crs.to_string() if raster.crs else str(crs),
                'crs_from_original_xml':raster.crs is None,'native_resolution':list(raster.res),
                'raster_bounds_wgs84':[round(v,7) for v in bound],
                'valid_pixels':int(valid),'total_pixels':raster.width*raster.height,
                'minimum_value':minimum,'maximum_value':maximum,
                'class_counts':classes if record['kind']=='seafloor_character' else None,
                'class_table_status':class_table_status,
                'original_class_table':class_table,
                'original_class_table_sha256':hashlib.sha256(vat_raw).hexdigest() if vat_raw else None,
                'nodata_value':float(raster.nodata) if raster.nodata is not None else None}


def inspect(blocks, metadata, cache, *, fetcher=download, max_workers=3):
    if blocks.get('scope')!='usgs-state-waters-map-block-links' or metadata.get('scope')!='usgs-state-waters-native-metadata':
        raise ValueError('Invalid USGS source inventory scope')
    reviewed={(row['block_id'],row['kind'],row['metadata_url']):row for row in metadata['records'] if row['status']=='ok'}
    tasks=[]
    for block in blocks['blocks']:
        for kind,products in block['products'].items():
            for product in products:
                key=(block['id'],kind,product['metadata_url'])
                if key in reviewed:
                    tasks.append((block['id'],kind,product,reviewed[key]))
    def one(task):
        ident,kind,product,record=task
        url=product['archive_url']
        if not approved(url) or f'/{ident}/data/' not in url:
            raise ValueError('Archive URL does not match USGS block')
        digest=hashlib.sha256(url.encode()).hexdigest()[:16]
        local=cache / f'{ident}-{kind}-{digest}.zip'
        if not local.is_file():
            fetcher(url,local)
        actual=hashlib.sha256(local.read_bytes()).hexdigest()
        return {'block_id':ident,'kind':kind,'archive_url':url,'archive_sha256':actual,
                'archive_bytes':local.stat().st_size,'metadata_sha256':record['xml_sha256'],
                'metadata_url':record['metadata_url'],'status':'ok',
                'surveyed_at':datetime.now(timezone.utc).isoformat(),
                **inspect_archive(local,record,product['description'])}
    rows=[]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        pending={pool.submit(one,task):task for task in tasks}
        for future in as_completed(pending):
            task=pending[future]
            try:rows.append(future.result())
            except (OSError,TimeoutError,ValueError,zipfile.BadZipFile,rasterio.errors.RasterioError) as error:
                ident,kind,product,record=task
                rows.append({'block_id':ident,'kind':kind,'archive_url':product['archive_url'],
                             'metadata_url':record['metadata_url'],'status':'failed','issue':str(error)[:180]})
    rows.sort(key=lambda row:(row['block_id'],row['kind'],row['archive_url']))
    issues=[row['archive_url'] for row in rows if row['status']!='ok']
    return {'schema_version':1,'scope':'usgs-state-waters-native-grid-audit',
            'collected_at':datetime.now(timezone.utc).isoformat(),
            'method':'Original USGS ZIP and native GeoTIFF pixel inspection. No NAVD88-to-MLLW conversion, no species habitat or closure clearance; no fishing targets published.',
            'fishing_target':False,'exportable':False,
            'product_count':len(rows),'inspected_count':len(rows)-len(issues),
            'health':{'status':'ok' if not issues else 'degraded','issues':issues},'products':rows}


def signature(report):
    return {'scope':report['scope'],'product_count':report['product_count'],
            'inspected_count':report['inspected_count'],
            'products':[{key:value for key,value in row.items() if key!='surveyed_at'}
                        for row in report['products']]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blocks',type=Path,required=True)
    parser.add_argument('--metadata',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=3)
    parser.add_argument('--block-id',action='append',help='Inspect selected original map blocks; repeat for more than one')
    parser.add_argument('--verify',type=Path,help='Fail if pinned native archive, grid or class-table evidence changed')
    args=parser.parse_args()
    if not 1<=args.workers<=6:raise ValueError('workers must be between 1 and 6')
    blocks=json.loads(args.blocks.read_text())
    metadata=json.loads(args.metadata.read_text())
    if args.block_id:
        wanted=set(args.block_id)
        selected=[block for block in blocks['blocks'] if block['id'] in wanted]
        if len(selected)!=len(wanted):raise ValueError('Unknown original USGS block ID')
        blocks={**blocks,'blocks':selected,'block_count':len(selected)}
        metadata={**metadata,'records':[row for row in metadata['records'] if row['block_id'] in wanted]}
    result=inspect(blocks,metadata,args.cache,max_workers=args.workers)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+'.tmp')
    temp.write_text(json.dumps(result,separators=(',',':'),ensure_ascii=False)+'\n')
    temp.replace(args.output)
    if args.verify and signature(result)!=signature(json.loads(args.verify.read_text())):
        raise SystemExit('Original USGS native grid or class-table evidence changed; review before promotion')
    print(f"{result['health']['status']}: {result['inspected_count']}/{result['product_count']} native USGS grids inspected")


if __name__=='__main__':main()
