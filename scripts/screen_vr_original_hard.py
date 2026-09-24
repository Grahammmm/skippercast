"""Screen original NOAA VR refinement cells against original USGS hard class.

This is a source-evidence screen. It excludes current MPA/GEA snapshots and
historical survey hazards, but does not clear local rules or navigation and
therefore emits no fishing geometry.
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
from pyproj import Transformer
import rasterio
from rasterio.features import rasterize
from rasterio.warp import reproject, Resampling, transform_bounds
from scipy.ndimage import binary_erosion
from shapely.geometry import box, mapping, Point, shape
from shapely.ops import transform as geometry_transform, unary_union

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.qualify_regular_bag_hard import original_character
from scripts.screen_vr_native_depth import fine_grid_rows
from scripts.build_usgs_statewide_context import mpa_union
from skippercast.platform.bottom_targets import bag_metadata,cells_qualified,sha256,vr_transform


def exclusions(bag,horizontal,source_bounds_wgs84,mpas,federal,hazards,report_cache):
    """Project complete fresh closures and pinned historical DTON holds once."""
    review_box=box(*source_bounds_wgs84).buffer(.02)
    to_native=Transformer.from_crs('EPSG:4326',horizontal,always_xy=True).transform
    state=mpa_union(mpas).intersection(review_box)
    if (federal.get('scope')!='noaa-west-coast-groundfish-conservation-areas'
            or federal.get('status')!='ok' or len(federal.get('features',[]))<25):
        raise ValueError('Complete current NOAA federal area feed is required')
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(federal['retrieved_at'])).total_seconds()
    if not 0<=age<=36*3600:
        raise ValueError('NOAA federal area feed is stale')
    geas=[f for f in federal['features'] if f.get('properties',{}).get('area_type')=='GEA']
    if len(geas)<10 or not any('Cordell_Bank_20260623' in f['properties'].get('source_layer','') for f in geas):
        raise ValueError('Current NOAA federal GEA set is incomplete')
    federal_shapes=[shape(f['geometry']).intersection(review_box) for f in geas
                    if shape(f['geometry']).intersects(review_box)]
    review=next((r for r in hazards.get('surveys',[]) if r.get('survey_id')==bag['survey_id']),None)
    if hazards.get('scope')!='historical-noaa-survey-hazard-review' or not review:
        raise ValueError('Original NOAA survey report hazards are unreviewed')
    path=report_cache/(bag['survey_id']+'.pdf')
    if review['report_url']!=bag['source_report_url'] or not path.is_file() or sha256(path)!=review['report_sha256']:
        raise ValueError('Original NOAA descriptive report changed')
    shapes=[]
    if not state.is_empty:shapes.append(geometry_transform(to_native,state).buffer(100))
    shapes += [geometry_transform(to_native,g).buffer(100) for g in federal_shapes if not g.is_empty]
    for hazard in review['hazards']:
        radius=hazard['review_exclusion_radius_m']
        if not 0<radius<=1000:raise ValueError('Invalid historical DTON review radius')
        shapes.append(geometry_transform(to_native,Point(hazard['longitude'],hazard['latitude'])).buffer(radius))
    return unary_union(shapes) if shapes else None,review


def screen(bag,source,metadata,bag_cache,usgs_cache,mpas,federal,hazards,report_cache,*,limit_ft=200,mask_callback=None):
    if (bag.get('status')!='ok' or bag.get('metadata_status')!='mllw-product-uncertainty-reviewed-by-adapter'
            or bag.get('refinement_grids_at_most_4m',0)<=0):
        raise ValueError('Original NOAA fine VR BAG is missing or metadata-unreviewed')
    url=bag['url'];ident=bag['survey_id']
    path=bag_cache/(ident+'-'+hashlib.sha256(url.encode()).hexdigest()[:16]+'.bag')
    if not path.is_file() or path.stat().st_size!=bag['file_bytes'] or sha256(path)!=bag['file_sha256']:
        raise ValueError('Original NOAA BAG is missing or changed')
    uri=original_character(source,usgs_cache,metadata)
    with rasterio.open(uri) as class_raster,rasterio.open(path) as grid,h5py.File(path) as handle:
        if (class_raster.count!=1 or class_raster.nodata!=0 or class_raster.dtypes[0]!='uint8'
                or not all(1.5<=x<=5.1 for x in class_raster.res)):
            raise ValueError('Original USGS class coding or resolution changed')
        root=handle['BAG_root']
        original=bag_metadata(root['metadata'][:].tobytes().decode().rstrip('\0'),ident)
        if original['metadata_sha256']!=bag['metadata_sha256']:
            raise ValueError('Original NOAA BAG metadata changed')
        horizontal=CRS.from_wkt(original['horizontal_wkt'])
        if horizontal.is_bound:horizontal=horizontal.source_crs
        bag_crs=CRS.from_user_input(grid.crs)
        if bag_crs.is_compound:bag_crs=bag_crs.sub_crs_list[0]
        if bag_crs.is_bound:bag_crs=bag_crs.source_crs
        if not horizontal.equals(bag_crs,ignore_axis_order=True):
            raise ValueError('Original NOAA BAG horizontal CRS changed')
        source_bounds_wgs84=transform_bounds(class_raster.crs,'EPSG:4326',*class_raster.bounds,densify_pts=21)
        excluded,report_review=exclusions(bag,horizontal,source_bounds_wgs84,mpas,federal,hazards,report_cache)
        if root['tracking_list'].size or root['varres_tracking_list'].size:
            raise ValueError('Tracked BAG cells need separate review')
        M=root['varres_metadata'][:];V=root['varres_refinements']
        if M.shape!=(grid.height,grid.width) or V.shape[1]!=bag['variable_refinement_records']:
            raise ValueError('Original BAG refinement indexing changed')
        indices=fine_grid_rows(M)
        if len(indices)!=bag['refinement_grids_at_most_4m']:
            raise ValueError('Original fine-supergrid count changed')
        # h5py's refinement records are south-up; GDAL presents north-up. Verify
        # both cell orientation and transform before applying the substrate grid.
        for probe in sorted({0,len(indices)//2,len(indices)-1}):
            r,c=map(int,indices[probe]);item=M[r,c]
            nx,ny=int(item['dimensions_x']),int(item['dimensions_y']);offset=int(item['index'])
            values=V[0,offset:offset+nx*ny]['depth'].reshape(ny,nx)[::-1]
            transform=vr_transform(grid.bounds.left,grid.bounds.bottom,grid.res[0],grid.res[1],r,c,item)
            with rasterio.open(f'BAG:{path}:supergrid:{r}:{c}') as gdal:
                if (gdal.shape!=(ny,nx) or not np.allclose(values,gdal.read(1),equal_nan=True)
                        or not np.allclose(tuple(transform),tuple(gdal.transform),atol=.001,rtol=0)):
                    raise ValueError('Native BAG refinement alignment differs from GDAL')
        source_bounds=transform_bounds(class_raster.crs,horizontal,*class_raster.bounds,densify_pts=21)
        totals={'fine_supergrids':len(indices),'source_bbox_intersecting_fine_supergrids':0,
                'measured_cells_in_source_bbox_grids':0,'depth_uncertainty_eligible_cells_in_source_bbox_grids':0,
                'hard_cells_after_edge_inset':0,'joined_hard_depth_cells':0,
                'fine_supergrids_with_joined_cells':0,'joined_cells_after_mpa_gea_historical_dton':0,
                'fine_supergrids_after_exclusions':0}
        minimum=float('inf');maximum=float('-inf')
        for counter,(r,c) in enumerate(indices,1):
            item=M[r,c]
            nx,ny=int(item['dimensions_x']),int(item['dimensions_y'])
            dx,dy=float(item['resolution_x']),float(item['resolution_y'])
            if not 0<nx<=128 or not 0<ny<=128:
                raise ValueError('Unsupported original BAG supergrid dimensions')
            transform=vr_transform(grid.bounds.left,grid.bounds.bottom,grid.res[0],grid.res[1],int(r),int(c),item)
            west,south,east,north=transform.c,transform.f-ny*dy,transform.c+nx*dx,transform.f
            if east<source_bounds[0] or west>source_bounds[2] or north<source_bounds[1] or south>source_bounds[3]:
                continue
            totals['source_bbox_intersecting_fine_supergrids']+=1
            offset=int(item['index']);length=nx*ny
            if offset<0 or offset+length>V.shape[1]:
                raise ValueError('Original BAG refinement offset exceeds file')
            values=V[0,offset:offset+length]
            depth=values['depth'].reshape(ny,nx)[::-1]
            uncertainty=values['depth_uncrt'].reshape(ny,nx)[::-1]
            measured=(np.isfinite(depth)&(depth<0)&(depth>-3000)&np.isfinite(uncertainty)
                      &(uncertainty>0)&(uncertainty<100))
            eligible=cells_qualified(depth,uncertainty,max(dx,dy),limit_ft=limit_ft)&measured
            totals['measured_cells_in_source_bbox_grids']+=int(measured.sum())
            totals['depth_uncertainty_eligible_cells_in_source_bbox_grids']+=int(eligible.sum())
            if not np.any(eligible):continue
            placed=np.zeros((ny,nx),dtype='uint8')
            reproject(rasterio.band(class_raster,1),placed,src_nodata=0,
                      dst_transform=transform,dst_crs=horizontal,dst_nodata=0,
                      resampling=Resampling.nearest)
            hard=binary_erosion(placed.astype('int64')%10==3,iterations=2,border_value=0)
            totals['hard_cells_after_edge_inset']+=int(hard.sum())
            joined=hard&eligible
            count=int(joined.sum())
            totals['joined_hard_depth_cells']+=count
            if count:
                totals['fine_supergrids_with_joined_cells']+=1
                depths=-depth[joined]/.3048
                minimum=min(minimum,float(depths.min()));maximum=max(maximum,float(depths.max()))
                retained=joined
                if excluded is not None and excluded.intersects(box(west,south,east,north)):
                    local=excluded.intersection(box(west,south,east,north).buffer(max(dx,dy)))
                    mask=rasterize([(mapping(local),1)],out_shape=(ny,nx),transform=transform,
                                   dtype='uint8').astype(bool)
                    retained=joined&~mask
                kept=int(retained.sum())
                totals['joined_cells_after_mpa_gea_historical_dton']+=kept
                totals['fine_supergrids_after_exclusions']+=kept>0
                if kept and mask_callback is not None:
                    mask_callback(retained, depth, transform, horizontal)
            if counter%5000==0:print(ident,'screened',counter,'/',len(indices),flush=True)
        return {'schema_version':1,'scope':'original-vr-noaa-usgs-hard-depth-cell-screen',
                'screened_at':datetime.now(timezone.utc).isoformat(),
                'survey_id':ident,'bag_url':url,'bag_sha256':bag['file_sha256'],
                'bag_metadata_sha256':bag['metadata_sha256'],'survey_dates':[bag['survey_start'],bag['survey_end']],
                'source_report_url':bag['source_report_url'],
                'usgs_release_id':source['release_id'],'usgs_archive_url':source['archive_url'],
                'usgs_archive_sha256':source['archive_sha256'],
                'usgs_metadata_sha256':source['metadata_sha256'],
                'maximum_planning_depth_ft':limit_ft,
                'mpa_retrieved_at':mpas['sources']['mpas']['data_retrieved_at'],
                'federal_areas_retrieved_at':federal['retrieved_at'],
                'survey_report_sha256':report_review['report_sha256'],
                'historical_hazards_screened':len(report_review['hazards']),
                'method':'Original <=4 m NOAA MLLW/product-uncertainty refinement cells (north-up verified against GDAL) intersected with original USGS class-3 pixels inset by two native BAG cells. Current complete CDFW MPAs and NOAA GEAs have 100 m buffers; pinned original NOAA DTON rock positions are review exclusions. No cell interpolation.',
                'limitations':['This is a historical source screen, not mapped fishing geometry.',
                               'Two-cell inset at each supergrid boundary is conservative and may omit real hard substrate.',
                               'Current chart, species-specific local rules, routes and fish presence are not cleared.'],
                'fishing_target':False,'exportable':False,
                'counts':totals,'joined_depth_ft_range':[round(minimum,1),round(maximum,1)] if minimum!=float('inf') else None}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--survey-audit',type=Path,required=True)
    p.add_argument('--usgs-audit',type=Path,required=True)
    p.add_argument('--usgs-metadata',type=Path,required=True)
    p.add_argument('--usgs-release-id',required=True)
    p.add_argument('--bag-cache',type=Path,default=Path('var/noaa-native-cache'))
    p.add_argument('--usgs-cache',type=Path,default=Path('var/usgs-doi-native-cache'))
    p.add_argument('--mpas',type=Path,default=Path('var/qualification-current/coastal/latest.json'))
    p.add_argument('--federal-areas',type=Path,default=Path('var/noaa-federal-areas.json'))
    p.add_argument('--hazards',type=Path,default=Path('catalog/noaa-survey-hazards.json'))
    p.add_argument('--report-cache',type=Path,default=Path('var/noaa-report-cache'))
    p.add_argument('--limit-ft',type=int,default=200)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    packet=json.loads(a.survey_audit.read_text())
    if packet.get('scope')!='noaa-original-bag-native-overview-audit' or packet['health']['status']!='ok' or len(packet['files'])!=1:
        raise ValueError('Select one healthy original NOAA BAG audit')
    usgs=json.loads(a.usgs_audit.read_text());metadata=json.loads(a.usgs_metadata.read_text())
    source=next((row for row in usgs['products'] if row.get('release_id')==a.usgs_release_id
                 and row.get('kind')=='seafloor_character' and row.get('status')=='ok'),None)
    if not source:raise ValueError('Original USGS class source is unavailable')
    result=screen(packet['files'][0],source,metadata,a.bag_cache,a.usgs_cache,
                  json.loads(a.mpas.read_text()),json.loads(a.federal_areas.read_text()),
                  json.loads(a.hazards.read_text()),a.report_cache,limit_ft=a.limit_ft)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    temp=a.output.with_suffix(a.output.suffix+'.tmp');temp.write_text(json.dumps(result,separators=(',',':'))+'\n');temp.replace(a.output)
    print(result['survey_id'],result['counts'],flush=True)


if __name__=='__main__':main()
