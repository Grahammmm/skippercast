"""Compile dated USGS hard-substrate outlines for statewide *context* display.

Source class 3 (rugose rock/boulder) is decoded only where the block's original
XML explicitly defines it. Native pixels are generalized to 20 m and excluded
from the current CDFW MPA union. The result cannot become a waypoint, catch
forecast, legal-depth proof or navigation product.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import shapes
from shapely.geometry import shape, mapping
from shapely.ops import transform, unary_union
from pyproj import CRS, Transformer

DISPLAY_M = 20
MIN_PATCH_M2 = 5_000


def hard_class_review(record):
    definitions=' '.join(item['definition'] for item in record['substrate_definitions']).lower()
    legacy='class 3' in definitions and 'rock' in definitions and ('boulder' in definitions or 'rugose' in definitions)
    modern=any(item['code']=='3' and 'hard' in item['label'].lower() and
               ('boulder' in item['label'].lower() or 'bedrock' in item['label'].lower())
               for item in record.get('categorical_classes',[]))
    return legacy or modern


def mpa_union(snapshot):
    source=snapshot.get('sources',{}).get('mpas',{})
    data=source.get('data',{})
    geo=data.get('geojson',{})
    if source.get('status')!='ok' or geo.get('type')!='FeatureCollection' or len(geo.get('features',[]))<100 or geo.get('exceededTransferLimit'):
        raise ValueError('Current complete CDFW MPA geometry is required')
    age=datetime.now(timezone.utc)-datetime.fromisoformat(source['data_retrieved_at'].replace('Z','+00:00'))
    if not 0<=age.total_seconds()<=36*3600:
        raise ValueError('CDFW MPA geometry is stale')
    return unary_union([shape(f['geometry']) for f in geo['features']])


def compile_block(row, source, cache, excluded):
    if not hard_class_review(source):
        raise ValueError('Original USGS XML does not define class 3 hard seabed')
    url=row['archive_url']
    archive=cache/(row['block_id']+'-'+row['kind']+'-'+hashlib.sha256(url.encode()).hexdigest()[:16]+'.zip')
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=row['archive_sha256']:
        raise ValueError('USGS original raster digest differs from native audit')
    with zipfile.ZipFile(archive) as bundle:
        members=[x.filename for x in bundle.infolist() if x.filename.lower().endswith('.tif') and not x.filename.startswith('__MACOSX/')]
        if len(members)!=1:
            expected='2m' if '2m/pixel' in source['description'].lower() else '5m'
            members=[x for x in members if expected in x.lower()]
        if len(members)!=1:raise ValueError('Ambiguous original seafloor character grid')
        member=members[0]
    with rasterio.open(f'zip://{archive.resolve()}!{member}') as raster:
        crs=raster.crs or source.get('metadata_projected_crs')
        if raster.count!=1 or not crs or not CRS.from_user_input(crs).is_projected:
            raise ValueError('Unprojected or unsupported original seafloor grid')
        if not all(1.5<=x<=5.1 for x in raster.res):
            raise ValueError('Unexpected original class resolution')
        width=max(1,round(raster.width*raster.res[0]/DISPLAY_M))
        height=max(1,round(raster.height*raster.res[1]/DISPLAY_M))
        native=raster.read(1,out_shape=(height,width),resampling=Resampling.mode)
        # Codes add tens for depth zones and 50s for slope zones. The final
        # digit retains the reviewed substrate class; 0 is not hard seabed.
        direct=any(item['code']=='3' and ('boulder' in item['label'].lower() or 'bedrock' in item['label'].lower())
                   for item in source.get('categorical_classes',[]))
        selected=((native.astype('int64')==3) if direct else ((native.astype('int64')%10)==3)).astype('uint8')
        affine=raster.transform*raster.transform.scale(raster.width/width,raster.height/height)
        project=Transformer.from_crs(crs,'EPSG:4326',always_xy=True).transform
        candidates=[]
        for geometry,value in shapes(selected,mask=selected.astype(bool),transform=affine):
            if value!=1:continue
            polygon=shape(geometry)
            if polygon.area<MIN_PATCH_M2:continue
            polygon=polygon.simplify(DISPLAY_M/2,preserve_topology=True)
            if polygon.is_empty:continue
            wgs=transform(project,polygon)
            legal=wgs.difference(excluded)
            if legal.is_empty:continue
            parts=list(legal.geoms) if hasattr(legal,'geoms') else [legal]
            for part in parts:
                if part.geom_type!='Polygon' or part.is_empty:continue
                candidates.append((polygon.area,part))
        candidates.sort(key=lambda item:-item[0])
        return candidates


def build(blocks,metadata,audit,mpas,cache):
    if audit.get('scope')!='usgs-state-waters-native-grid-audit':raise ValueError('Invalid native USGS audit')
    indexed={(b['id'],kind,p['metadata_url']):p for b in blocks['blocks'] for kind,products in b['products'].items() for p in products}
    meta={(r['block_id'],r['kind'],r['metadata_url']):r for r in metadata['records'] if r['status']=='ok'}
    excluded=mpa_union(mpas)
    features=[]
    failures=[]
    for row in audit['products']:
        if row['kind']!='seafloor_character':continue
        key=(row['block_id'],row['kind'],row['metadata_url'])
        if row['status']!='ok' or key not in indexed or key not in meta:
            failures.append(row['block_id'])
            continue
        try:
            areas=compile_block(row,{**meta[key],**indexed[key]},cache,excluded)
        except (OSError,ValueError,zipfile.BadZipFile,rasterio.errors.RasterioError) as error:
            failures.append(row['block_id']+': '+str(error)[:100])
            continue
        for rank,(native_area,geometry) in enumerate(areas[:100],1):
            features.append({'type':'Feature','geometry':mapping(geometry),'properties':{
                'id':f"usgs-{row['block_id']}-{row['archive_sha256'][:8]}-{rank:03d}",'block_id':row['block_id'],
                'source_url':row['archive_url'],'metadata_url':row['metadata_url'],
                'source_file_sha256':row['archive_sha256'],'source_metadata_sha256':row['metadata_sha256'],
                'source_year':meta[key]['published_date'],'source_class':'Class 3 · hard, rugose rock/boulder',
                'approx_original_area_m2':round(native_area),'display_resolution_m':DISPLAY_M,
                'fishing_target':False,'exportable':False,'depth_qualified':False,
                'fish_confirmed':False,'mpa_screened_at':mpas['sources']['mpas']['data_retrieved_at']}})
    return {'type':'FeatureCollection','schema_version':1,'scope':'generalized-statewide-usgs-hard-bottom-context',
            'compiled_at':datetime.now(timezone.utc).isoformat(),'source':'USGS California State Waters Map Series (DS 781)',
            'source_catalog_url':'https://pubs.usgs.gov/ds/781/',
            'method':'Original categorical GeoTIFF class 3, mode resampled to 20 m, polygons >=5,000 m², largest 100 per reviewed map block, generalized and cut by complete current CDFW MPA polygons. Historical context only.',
            'limitations':['Map blocks are discontinuous and contain unsurveyed pixels.','Published outlines omit smaller hard patches and cannot mark exact rock edges.','Depth grids use separate datums; this layer is not depth-qualified.','No catch or legal access is inferred.'],
            'failed_blocks':sorted(set(failures)),'features':features}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('blocks','metadata','audit','mpas','cache','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=build(*(json.loads(getattr(args,name).read_text()) for name in ('blocks','metadata','audit','mpas')),args.cache)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+'.tmp')
    temp.write_text(json.dumps(result,separators=(',',':'))+'\n')
    temp.replace(args.output)
    print(f"{len(result['features'])} historical hard-bottom context polygons; {len(result['failed_blocks'])} held block(s); zero fishing targets")


if __name__=='__main__':main()
