"""Test original NOAA VR-BAG supergrid footprints against an original USGS raster.

This resolves false survey-bounding-box leads. Intersection with the raster's
bounding box is still only a source lead, not hard substrate or fishing depth.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import h5py
import numpy as np
from pyproj import CRS
import rasterio
from rasterio.warp import transform_bounds

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.qualify_regular_bag_hard import original_character
from skippercast.platform.bottom_targets import bag_metadata, sha256, vr_transform


def inspect_bag(row,bag_cache,source_bounds,source_crs):
    if (row.get('status')!='ok' or row.get('metadata_status')!='mllw-product-uncertainty-reviewed-by-adapter'
            or row.get('variable_refinement_records',0)<=0):
        raise ValueError('Original NOAA variable BAG metadata is unreviewed')
    url=row['url'];ident=row['survey_id']
    path=bag_cache/(ident+'-'+hashlib.sha256(url.encode()).hexdigest()[:16]+'.bag')
    if not path.is_file() or path.stat().st_size!=row['file_bytes'] or sha256(path)!=row['file_sha256']:
        raise ValueError('Original NOAA BAG is missing or changed: '+ident)
    with rasterio.open(path) as raster,h5py.File(path) as handle:
        root=handle['BAG_root']
        original=bag_metadata(root['metadata'][:].tobytes().decode().rstrip('\0'),ident)
        if original['metadata_sha256']!=row['metadata_sha256']:
            raise ValueError('Original NOAA BAG metadata changed: '+ident)
        horizontal=CRS.from_wkt(original['horizontal_wkt'])
        if horizontal.is_bound:horizontal=horizontal.source_crs
        bag_crs=CRS.from_user_input(raster.crs)
        if bag_crs.is_compound:bag_crs=bag_crs.sub_crs_list[0]
        if bag_crs.is_bound:bag_crs=bag_crs.source_crs
        if not horizontal.equals(bag_crs,ignore_axis_order=True):
            raise ValueError('Original NOAA BAG horizontal CRS mismatch: '+ident)
        bounds=transform_bounds(source_crs,horizontal,*source_bounds,densify_pts=21)
        overview_intersects=not (raster.bounds.right<bounds[0] or raster.bounds.left>bounds[2]
                                  or raster.bounds.top<bounds[1] or raster.bounds.bottom>bounds[3])
        metadata=root['varres_metadata'][:]
        if metadata.shape!=(raster.height,raster.width):
            raise ValueError('BAG supergrid metadata shape changed: '+ident)
        indices=np.argwhere((metadata['dimensions_x']>0)&(metadata['dimensions_y']>0)
                            &(metadata['resolution_x']>0)&(metadata['resolution_y']>0))
        overlap=0;fine=0;capacity=0
        for r,c in indices:
            item=metadata[r,c]
            nx,ny=int(item['dimensions_x']),int(item['dimensions_y'])
            dx,dy=float(item['resolution_x']),float(item['resolution_y'])
            t=vr_transform(raster.bounds.left,raster.bounds.bottom,raster.res[0],raster.res[1],
                           int(r),int(c),item)
            west,south,east,north=t.c,t.f-ny*dy,t.c+nx*dx,t.f
            if east<bounds[0] or west>bounds[2] or north<bounds[1] or south>bounds[3]:continue
            overlap+=1;capacity+=nx*ny
            fine+=dx<=4 and dy<=4
        return {'survey_id':ident,'bag_url':url,'bag_sha256':row['file_sha256'],
                'metadata_sha256':row['metadata_sha256'],'source_report_url':row['source_report_url'],
                'survey_dates':[row['survey_start'],row['survey_end']],
                'original_supergrid_count':int(len(indices)),
                'overview_bbox_intersects_source':overview_intersects,
                'supergrid_footprints_intersect_source_bbox':overlap,
                'fine_supergrid_footprints_intersect_source_bbox':int(fine),
                'max_possible_refinement_cells_in_intersecting_grids':capacity}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--survey-audit',type=Path,action='append',required=True)
    p.add_argument('--usgs-audit',type=Path,required=True)
    p.add_argument('--usgs-metadata',type=Path,required=True)
    p.add_argument('--usgs-release-id',required=True)
    p.add_argument('--bag-cache',type=Path,default=Path('var/noaa-native-cache'))
    p.add_argument('--usgs-cache',type=Path,default=Path('var/usgs-doi-native-cache'))
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    usgs=json.loads(a.usgs_audit.read_text());metadata=json.loads(a.usgs_metadata.read_text())
    source=next((x for x in usgs['products'] if x.get('release_id')==a.usgs_release_id
                 and x.get('kind')=='seafloor_character' and x.get('status')=='ok'),None)
    if not source:raise ValueError('Requested original USGS class raster is unavailable')
    uri=original_character(source,a.usgs_cache,metadata)
    with rasterio.open(uri) as raster:
        source_bounds=list(raster.bounds);source_crs=raster.crs
        if raster.count!=1 or not source_crs:raise ValueError('Original USGS class raster is unlocated')
    rows=[]
    for path in a.survey_audit:
        packet=json.loads(path.read_text())
        if packet.get('scope')!='noaa-original-bag-native-overview-audit' or packet['health']['status']!='ok':
            raise ValueError('NOAA original BAG audit is missing or degraded')
        for row in packet['files']:
            rows.append(inspect_bag(row,a.bag_cache,source_bounds,source_crs))
    result={'schema_version':1,'scope':'original-vr-bag-usgs-source-footprint-audit',
            'reviewed_at':datetime.now(timezone.utc).isoformat(),
            'usgs_release_id':a.usgs_release_id,'usgs_class_url':source['archive_url'],
            'usgs_class_sha256':source['archive_sha256'],
            'usgs_metadata_sha256':source['metadata_sha256'],
            'method':'Original NOAA BAG supergrid rectangles intersected with original USGS class-raster extent in the verified native horizontal CRS.',
            'limitations':['A source bounding-box intersection is not a valid depth/substrate cell intersection.',
                           'Supergrid counts include empty or invalid cells; original refinement depths and uncertainty are a separate gate.',
                           'No fishing targets, navigation routes or legal permissions follow from this audit.'],
            'fishing_target':False,'exportable':False,'surveys':rows}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    temp=a.output.with_suffix(a.output.suffix+'.tmp');temp.write_text(json.dumps(result,separators=(',',':'))+'\n');temp.replace(a.output)
    for row in rows:print(row['survey_id'],row['supergrid_footprints_intersect_source_bbox'],
                          'fine',row['fine_supergrid_footprints_intersect_source_bbox'])


if __name__=='__main__':main()
