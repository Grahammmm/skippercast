"""Compile an inward, non-target Northern map layer from original VR BAG cells.

The original-cell screen owns datum, uncertainty, USGS class and historical
hazard gates. A 5 m display raster is only a browse generalization; erosion
and a second vector closure cut keep it inside the reviewed evidence.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from affine import Affine
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.warp import reproject, Resampling, transform_bounds
from scipy.ndimage import binary_erosion, label
from shapely import make_valid
from shapely.geometry import mapping, shape
from shapely.ops import transform as geometry_transform
from pyproj import CRS, Transformer

from scripts.qualify_regular_bag_hard import original_character
from scripts.screen_vr_original_hard import exclusions, screen
from scripts.build_native_hard_context import polygon_only


class DisplayMask:
    def __init__(self, bounds, cell_m=5):
        left=math.floor(bounds[0]/cell_m)*cell_m
        top=math.ceil(bounds[3]/cell_m)*cell_m
        self.transform=Affine(cell_m,0,left,0,-cell_m,top)
        self.width=math.ceil((bounds[2]-left)/cell_m)
        self.height=math.ceil((top-bounds[1])/cell_m)
        if not 0<self.width*self.height<=30_000_000:
            raise ValueError('Display raster outside bounded Cape source extent')
        self.array=np.zeros((self.height,self.width),dtype='uint8')
        self.sample_depth=np.full((self.height,self.width),np.nan,dtype='float32')
        self.crs=None
        self.used=0

    def add(self,mask,depth,transform,crs):
        if mask.shape!=depth.shape:
            raise ValueError('Accepted-cell mask and native depth must align')
        if self.crs is None:self.crs=CRS.from_user_input(crs)
        elif not self.crs.equals(CRS.from_user_input(crs),ignore_axis_order=True):
            raise ValueError('Original native grid CRS changed during screen')
        height,width=mask.shape
        x0,y1=transform @ (0,0)
        x1,y0=transform @ (width,height)
        c0=max(0,int(math.floor((x0-self.transform.c)/self.transform.a))-1)
        c1=min(self.width,int(math.ceil((x1-self.transform.c)/self.transform.a))+1)
        r0=max(0,int(math.floor((self.transform.f-y1)/self.transform.a))-1)
        r1=min(self.height,int(math.ceil((self.transform.f-y0)/self.transform.a))+1)
        if c0>=c1 or r0>=r1:return
        tile=np.zeros((r1-r0,c1-c0),dtype='uint8')
        reproject(source=mask.astype('uint8'),destination=tile,
                  src_transform=transform,src_crs=self.crs,
                  dst_transform=self.transform @ Affine.translation(c0,r0),dst_crs=self.crs,
                  resampling=Resampling.nearest)
        tile_depth=np.full(tile.shape,np.nan,dtype='float32')
        reproject(source=np.where(mask,depth,np.nan).astype('float32'),destination=tile_depth,
                  src_nodata=np.nan,dst_nodata=np.nan,
                  src_transform=transform,src_crs=self.crs,
                  dst_transform=self.transform @ Affine.translation(c0,r0),dst_crs=self.crs,
                  resampling=Resampling.nearest)
        np.maximum(self.array[r0:r1,c0:c1],tile,out=self.array[r0:r1,c0:c1])
        valid=(tile!=0)&np.isfinite(tile_depth)
        self.sample_depth[r0:r1,c0:c1][valid]=tile_depth[valid]
        self.used+=1


def compile_layer(mask,bag,source,mpas,federal,hazards,report_cache,screen_result,*,minimum_area_m2=2_500):
    if mask.crs is None or not mask.used:
        raise ValueError('No accepted original-cell masks reached the display compiler')
    source_bounds_wgs84=transform_bounds(mask.crs,'EPSG:4326',
        mask.transform.c,mask.transform.f-mask.height*mask.transform.a,
        mask.transform.c+mask.width*mask.transform.a,mask.transform.f,densify_pts=21)
    excluded,report=exclusions(bag,mask.crs,source_bounds_wgs84,
                               mpas,federal,hazards,report_cache)
    # Nearest-neighbor display pixels are only an approximation. Retreat 10 m
    # before vectorizing and 5 m after; a second closure cut protects edges.
    interior=binary_erosion(mask.array.astype(bool),iterations=2,border_value=0)
    components,count=label(interior)
    sizes=np.bincount(components.ravel(),minlength=count+1)
    keep=np.flatnonzero(sizes*mask.transform.a**2>=minimum_area_m2)
    keep=keep[keep!=0]
    largest_component_area_m2=int((sizes[1:].max() if count else 0)*mask.transform.a**2)
    selected=np.isin(components,keep)
    to_wgs=Transformer.from_crs(mask.crs,'EPSG:4326',always_xy=True).transform
    output=[]
    for geom,value in shapes(components.astype('int32'),mask=selected,transform=mask.transform):
        component_id=int(value)
        if component_id not in keep:continue
        samples=mask.sample_depth[components==component_id]
        samples=samples[np.isfinite(samples)]
        if len(samples)<20:
            continue
        relief=float(np.percentile(samples,95)-np.percentile(samples,5))
        if not math.isfinite(relief) or relief<0:
            raise ValueError('Invalid native-depth relief')
        original=polygon_only(shape(geom))
        if original.area<minimum_area_m2:continue
        candidate=polygon_only(original.buffer(-5))
        if candidate.is_empty:continue
        candidate=polygon_only(candidate.simplify(5,preserve_topology=True).intersection(candidate))
        if excluded is not None:
            candidate=polygon_only(candidate.difference(excluded))
        if candidate.is_empty:continue
        pieces=list(candidate.geoms) if candidate.geom_type=='MultiPolygon' else [candidate]
        for part in pieces:
            if part.is_empty or part.area<minimum_area_m2 or not part.is_valid:
                continue
            if excluded is not None and part.intersection(excluded).area>1e-5:
                raise ValueError('Display polygon crosses a protected or hazard exclusion')
            wgs=polygon_only(make_valid(geometry_transform(to_wgs,part)))
            if wgs.is_empty or not wgs.is_valid:
                raise ValueError('Display geometry is invalid after WGS84 transform')
            output.append((round(part.area),mapping(wgs),round(relief,2),int(len(samples))))
    output.sort(key=lambda row:-row[0])
    features=[{'type':'Feature','geometry':geom,'properties':{
        'id':f'cape-mendocino-native-hard-{i:03d}',
        'survey_id':bag['survey_id'],'survey_dates':[bag['survey_start'],bag['survey_end']],
        'noaa_bag_url':bag['url'],'noaa_bag_sha256':bag['file_sha256'],
        'survey_report_url':bag['source_report_url'],
        'usgs_release_id':source['release_id'],'usgs_metadata_urls':[source['metadata_url']],
        'approx_display_area_m2':area,'display_cell_m':mask.transform.a,
        'sampled_relief_5_95_m':relief,'display_depth_samples':sample_count,
        'relief_method':'5 m nearest native-depth samples in pre-vector component; 95th–5th percentile difference, historical structure only',
        'depth_screen_ft':[25,screen_result['maximum_planning_depth_ft']],
        'depth_range_kind':'screened-policy-not-local-depth-range',
        'fishing_target':False,'exportable':False,'legal_clearance':False,
        'fish_confirmed':False,'depth_qualified_for_target':False,
    }} for i,(area,geom,relief,sample_count) in enumerate(output,1)]
    return {'type':'FeatureCollection','schema_version':1,
            'scope':'northern-native-noaa-usgs-hard-bottom-context','coast_id':'northern',
            'compiled_at':datetime.now(timezone.utc).isoformat(),
            'source_review':'data/noaa-h11975-cape-mendocino-hard-depth-screen.json',
            'mpa_screened_at':mpas['sources']['mpas']['data_retrieved_at'],
            'federal_screened_at':federal['retrieved_at'],
            'historical_hazards_screened':len(report['hazards']),
            'display_cell_m':mask.transform.a,'minimum_display_area_m2':minimum_area_m2,
            'display_cells_after_inset':int(interior.sum()),
            'largest_component_area_m2':largest_component_area_m2,
            'components_meeting_minimum_before_vector_inset':int(len(keep)),
            'source_screen_counts':screen_result['counts'],
            'method':'Original H11975 BAG fine refinement cells and original USGS class-3 pixels screened at native resolution, generalized to 5 m display cells, eroded inward 10 m and 5 m after vectorization, then re-cut against fresh MPA, GEA and pinned historical rock-hazard exclusions.',
            'limitations':['Historical seabed context, not a fishing location or chart-quality bottom boundary.',
                           'Displayed polygons omit patches smaller than 2,500 m2 and may omit real habitat.',
                           'Depth screen is 25–200 ft planning policy, not a polygon-specific depth range.',
                           'Current charts, navigation, date-specific local rules and fish presence remain unreviewed.'],
            'features':features}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--survey-audit',type=Path,default=Path('var/noaa-h11975-native-audit.json'))
    p.add_argument('--usgs-audit',type=Path,default=Path('var/usgs-doi-native-audit-eureka.json'))
    p.add_argument('--usgs-metadata',type=Path,default=Path('var/usgs-doi-metadata-eureka.json'))
    p.add_argument('--usgs-release-id',default='P9U0SUGL')
    p.add_argument('--bag-cache',type=Path,default=Path('var/noaa-native-cache'))
    p.add_argument('--usgs-cache',type=Path,default=Path('var/usgs-doi-native-cache'))
    p.add_argument('--mpas',type=Path,default=Path('var/qualification-current/coastal/latest.json'))
    p.add_argument('--federal-areas',type=Path,default=Path('var/noaa-federal-areas.json'))
    p.add_argument('--hazards',type=Path,default=Path('catalog/noaa-survey-hazards.json'))
    p.add_argument('--report-cache',type=Path,default=Path('var/noaa-report-cache'))
    p.add_argument('--screen',type=Path,default=Path('dist/data/noaa-h11975-cape-mendocino-hard-depth-screen.json'))
    p.add_argument('--output',type=Path,default=Path('dist/data/cape-mendocino-native-hard-context.geojson'))
    a=p.parse_args()
    packet=json.loads(a.survey_audit.read_text())
    if packet.get('scope')!='noaa-original-bag-native-overview-audit' or packet['health']['status']!='ok' or len(packet['files'])!=1:
        raise ValueError('One healthy original VR BAG audit is required')
    bag=packet['files'][0]
    if bag['survey_id']!='H11975':raise ValueError('This bounded layer is for NOAA H11975 only')
    usgs=json.loads(a.usgs_audit.read_text());metadata=json.loads(a.usgs_metadata.read_text())
    source=next((row for row in usgs['products'] if row.get('release_id')==a.usgs_release_id
                 and row.get('kind')=='seafloor_character' and row.get('status')=='ok'),None)
    if source is None:raise ValueError('Original USGS class raster is unavailable')
    uri=original_character(source,a.usgs_cache,metadata)
    with rasterio.open(uri) as raster:
        bag_path=a.bag_cache/(bag['survey_id']+'-'+hashlib.sha256(bag['url'].encode()).hexdigest()[:16]+'.bag')
        with rasterio.open(bag_path) as original:
            horizontal=CRS.from_user_input(original.crs)
            if horizontal.is_compound:horizontal=horizontal.sub_crs_list[0]
            if horizontal.is_bound:horizontal=horizontal.source_crs
        bounds=transform_bounds(raster.crs,horizontal,*raster.bounds,densify_pts=21)
    mask=DisplayMask(bounds)
    mpas=json.loads(a.mpas.read_text());federal=json.loads(a.federal_areas.read_text())
    hazards=json.loads(a.hazards.read_text())
    result=screen(bag,source,metadata,a.bag_cache,a.usgs_cache,mpas,federal,
                  hazards,a.report_cache,mask_callback=mask.add)
    prior=json.loads(a.screen.read_text())
    for field in ('bag_sha256','usgs_archive_sha256','survey_report_sha256','counts'):
        if result[field]!=prior[field]:raise ValueError('Original cell screen differs from pinned receipt: '+field)
    layer=compile_layer(mask,bag,source,mpas,federal,hazards,a.report_cache,result)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    temp=a.output.with_suffix(a.output.suffix+'.tmp');temp.write_text(json.dumps(layer,separators=(',',':'))+'\n');temp.replace(a.output)
    print(len(layer['features']),'inward Northern research outlines; zero fishing targets')


if __name__=='__main__':main()
