"""Verify an anthropogenic hard-bottom hold against pinned original raster cells.

This is a source-classification audit, never a fishing target or navigation aid.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import zipfile

import h5py
import numpy as np
from pyproj import Transformer
from pyproj import CRS
import rasterio
from scipy.ndimage import label
import shapefile
from shapely.geometry import Point, shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_usgs_doi_context import reviewed_holds
from scripts.qualify_regular_bag_hard import hard_mask_on_bag
from skippercast.platform.bottom_targets import bag_metadata, cells_qualified, sha256


def original_cmecs_geoforms(ident,hold,metadata,cache):
    """Verify original vector archive and identify the geoform at held centroids."""
    entry=hold['cmecs_archive']
    row=next((record for record in metadata['records'] if record.get('release_id')==ident
              and record.get('kind')=='cmecs' and record.get('status')=='ok'),None)
    if not row or row['xml_sha256']!=entry['metadata_sha256']:
        raise ValueError('Pinned original USGS CMECS metadata is missing or changed')
    path=cache/(ident+'-cmecs-original.zip')
    if not path.is_file() or sha256(path)!=entry['sha256']:
        raise ValueError('Pinned original USGS CMECS vector archive is missing or changed')
    with zipfile.ZipFile(path) as bundle:
        names=bundle.namelist()
        members={suffix:[name for name in names if name.lower().endswith(suffix)]
                 for suffix in ('.shp','.shx','.dbf','.prj')}
        if any(len(options)!=1 for options in members.values()):
            raise ValueError('Original USGS CMECS archive lacks one unambiguous shapefile')
        reader=shapefile.Reader(shp=BytesIO(bundle.read(members['.shp'][0])),
                                shx=BytesIO(bundle.read(members['.shx'][0])),
                                dbf=BytesIO(bundle.read(members['.dbf'][0])))
        crs=CRS.from_wkt(bundle.read(members['.prj'][0]).decode('utf-8'))
        if crs.to_epsg()!=32610:
            raise ValueError('USGS CMECS vector projection changed')
        to_native=Transformer.from_crs('EPSG:4326',crs,always_xy=True)
        points=[]
        for centroid in hold['candidate_centroids']:
            east,north=to_native.transform(centroid['longitude'],centroid['latitude'])
            point=Point(east,north);nearest=(float('inf'),None)
            for index,record in enumerate(reader.iterShapeRecords()):
                data=record.record.as_dict()
                if data.get('GeofrmDesc')!='Jetty':
                    continue
                west,south,east_bound,north_bound=record.shape.bbox
                if not west-30<=east<=east_bound+30 or not south-30<=north<=north_bound+30:
                    continue
                distance=shape(record.shape.__geo_interface__).distance(point)
                if distance<nearest[0]:nearest=(distance,index)
            if nearest[0]>30:
                raise ValueError('Original CMECS no longer identifies a nearby jetty for '+centroid['id'])
            points.append({'candidate_id':centroid['id'],'nearest_geoform':'Jetty',
                           'nearest_geoform_distance_m':round(nearest[0],2),
                           'original_vector_record':nearest[1]})
    return {'archive_url':entry['url'],'archive_sha256':entry['sha256'],
            'metadata_sha256':entry['metadata_sha256'],'native_crs':crs.to_string(),
            'candidate_centroid_checks':points}


def audit(ident,hold,audit_packet,usgs_packet,metadata,bag_cache,usgs_cache,report_cache):
    source=next((row for row in usgs_packet['products'] if row.get('release_id')==ident
                 and row.get('kind')=='seafloor_character' and row.get('status')=='ok'),None)
    if not source or source['archive_sha256']!=hold['source_archive_sha256']:
        raise ValueError('Pinned original USGS class source is missing or changed')
    geoforms=original_cmecs_geoforms(ident,hold,metadata,usgs_cache)
    station=hold['landmark'];results=[]
    for product in hold['survey_products']:
        survey=product['survey_id'];name=product['bag_filename']
        row=next((item for item in audit_packet['files'] if item.get('survey_id')==survey
                  and item.get('url','').endswith('/'+name)),None)
        if not row or row.get('metadata_status')!='mllw-product-uncertainty-reviewed-by-adapter':
            raise ValueError('Pinned original NOAA BAG is unavailable or metadata-unreviewed: '+name)
        path=bag_cache/(survey+'-'+hashlib.sha256(row['url'].encode()).hexdigest()[:16]+'.bag')
        report=report_cache/(survey+'.pdf')
        if not path.is_file() or sha256(path)!=row['file_sha256']:
            raise ValueError('Pinned NOAA BAG changed: '+name)
        if not report.is_file() or sha256(report)!=product['report_sha256']:
            raise ValueError('Pinned NOAA descriptive report changed: '+survey)
        with h5py.File(path,'r') as bag:
            xml=bag['BAG_root']['metadata'][:].tobytes().decode('utf-8').rstrip('\0')
        if bag_metadata(xml,survey)['metadata_sha256']!=row['metadata_sha256']:
            raise ValueError('Original BAG metadata changed: '+name)
        with rasterio.open(path) as grid:
            if grid.count<2 or max(grid.res)>4:
                raise ValueError('Original BAG resolution/bands unsupported: '+name)
            hard,receipts=hard_mask_on_bag([source],usgs_cache,metadata,
                                           shape_=(grid.height,grid.width),
                                           transform_=grid.transform,crs=grid.crs)
            elevation=grid.read(1)
            qualified=cells_qualified(elevation,grid.read(2),grid.res[0],limit_ft=200)
            joined=hard & qualified
            components,count=label(joined)
            sizes=np.bincount(components.ravel())
            top=np.argsort(sizes[1:])[-3:][::-1]+1 if len(sizes)>1 else []
            to_native=Transformer.from_crs('EPSG:4326',grid.crs,always_xy=True)
            east,north=to_native.transform(station['longitude'],station['latitude'])
            areas=[]
            for index in top:
                rows,cols=np.where(components==index)
                x,y=grid.xy(float(rows.mean()),float(cols.mean()))
                depth=-elevation[rows,cols]/.3048
                areas.append({'native_cells':int(sizes[index]),
                              'area_m2':int(round(sizes[index]*grid.res[0]*grid.res[1])),
                              'centroid_distance_to_landmark_m':int(round(np.hypot(x-east,y-north))),
                              'depth_ft_range':[round(float(depth.min()),1),round(float(depth.max()),1)]})
            results.append({'survey_id':survey,'bag_filename':name,'bag_url':row['url'],
                            'bag_sha256':row['file_sha256'],'bag_metadata_sha256':row['metadata_sha256'],
                            'report_url':row['source_report_url'],
                            'report_sha256':product['report_sha256'],
                            'survey_dates':[row['survey_start'],row['survey_end']],
                            'native_resolution_m':list(grid.res),
                            'hard_cells_after_class_edge_inset':int(hard.sum()),
                            'depth_uncertainty_eligible_cells':int(qualified.sum()),
                            'joined_hard_depth_cells':int(joined.sum()),
                            'joined_components':int(count),'largest_components':areas,
                            'usgs_source':receipts[0]})
    return {'schema_version':1,'scope':'original-cell-anthropogenic-hard-context-review',
            'reviewed_at':datetime.now(timezone.utc).isoformat(),
            'release_id':ident,'disposition':hold['disposition'],
            'reason':hold['reason'],'landmark':station,'evidence_urls':hold['evidence_urls'],
            'original_cmecs_geoform_review':geoforms,
            'method':'Original USGS class-3 cells inset by two native cells intersected with original NOAA MLLW product-uncertainty-qualified depth cells. Largest joined-component distances are measured to the reviewed landmark in BAG projected coordinates.',
            'limitations':['Proximity to a jetty is a conservative source hold, not a classification of each raster cell.',
                           'Historical grids and reports do not establish current channel shape, navigation clearance or fish presence.',
                           'No components in this file are fishing targets, routes, or exportable points.'],
            'fishing_target':False,'exportable':False,'products':results}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-id',required=True)
    parser.add_argument('--holds',type=Path,default=Path('catalog/usgs-context-holds.json'))
    parser.add_argument('--bag-audit',type=Path,default=Path('var/noaa-native-audit-100mb-refined.json'))
    parser.add_argument('--usgs-audit',type=Path,required=True)
    parser.add_argument('--usgs-metadata',type=Path,required=True)
    parser.add_argument('--bag-cache',type=Path,default=Path('var/noaa-native-cache'))
    parser.add_argument('--usgs-cache',type=Path,default=Path('var/usgs-doi-native-cache'))
    parser.add_argument('--report-cache',type=Path,default=Path('var/noaa-report-cache'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    holds=reviewed_holds(json.loads(args.holds.read_text()))
    if args.release_id not in holds or 'landmark' not in holds[args.release_id] or not holds[args.release_id].get('survey_products'):
        raise ValueError('Release lacks a reviewed landmark/original-survey hold')
    result=audit(args.release_id,holds[args.release_id],json.loads(args.bag_audit.read_text()),
                 json.loads(args.usgs_audit.read_text()),json.loads(args.usgs_metadata.read_text()),
                 args.bag_cache,args.usgs_cache,args.report_cache)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+'.tmp')
    temp.write_text(json.dumps(result,separators=(',',':'))+'\n')
    temp.replace(args.output)
    print(result['release_id'],[(p['bag_filename'],p['joined_hard_depth_cells']) for p in result['products']])


if __name__=='__main__':main()
