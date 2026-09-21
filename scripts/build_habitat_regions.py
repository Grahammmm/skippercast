"""Polygonize contiguous, conservatively screened soft sediment from USGS rasters.

Usage: python scripts/build_habitat_regions.py /path/to/waypoint-research
Requires rasterio, numpy, scipy, shapely, pyproj. Raw rasters remain outside Git.
No convex hulls or bridges across rocks, missing survey coverage, or deep water.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.features import shapes, geometry_mask
from scipy.ndimage import binary_erosion, label
from shapely.geometry import shape, mapping
from shapely.ops import transform, unary_union
from pyproj import Transformer


def coarse(ds, grid, method, coverage=False):
    out = np.full(grid.shape, np.nan, dtype='float32')
    reproject(ds.read_masks(1) if coverage else rasterio.band(ds, 1), out,
              src_transform=ds.transform, src_crs=ds.crs,
              src_nodata=None if coverage else ds.nodata,
              dst_transform=grid.transform, dst_crs=grid.crs,
              dst_nodata=np.nan, resampling=method)
    return out


def rounded_geometry(poly,geo):
    g=mapping(transform(geo,poly))
    return {'type':g['type'],'coordinates':[[[round(x,6),round(y,6)] for x,y in ring] for ring in g['coordinates']]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('research', type=Path)
    args = parser.parse_args()
    sources = json.loads((args.research/'data/candidate-pool.json').read_text())['sources']
    utm = Transformer.from_crs(4326, 32610, always_xy=True).transform
    geo = Transformer.from_crs(32610, 4326, always_xy=True).transform
    closed = json.loads((args.research/'data/closed-area-screen.geojson').read_text())
    exclusion = transform(utm, shape(closed['features'][0]['geometry'])).buffer(505)
    records = []
    for src in sources:
        if src['key'] not in {'PointBuchon','MorroBay','PointEstero'}: continue
        with rasterio.open(args.research/src['analysis_file']) as grid:
            with rasterio.open(src['bath']) as bath:
                shallow = -coarse(bath, grid, Resampling.max)/.3048
                deep = -coarse(bath, grid, Resampling.min)/.3048
                valid_bath = coarse(bath, grid, Resampling.min, True) == 255
            with rasterio.open(src['substrate']) as substrate:
                soft = (coarse(substrate, grid, Resampling.min) == 1) & (coarse(substrate, grid, Resampling.max) == 1)
                valid_soft = coarse(substrate, grid, Resampling.min, True) == 255
            allowed = ~geometry_mask([mapping(exclusion)],grid.shape,grid.transform,invert=True,all_touched=True)
            for species, ceiling in [('halibut',100),('dungeness',195)]:
                mask = soft & valid_bath & valid_soft & allowed & (shallow >= 25) & (deep <= ceiling)
                # Set the outline back 20 m from any unsupported cell.
                mask = binary_erosion(mask,iterations=2)
                groups, count = label(mask)
                sizes = np.bincount(groups.ravel())
                # Retain real contiguous grounds >= 0.2 km², not isolated tiny pockets.
                keep = np.flatnonzero(sizes >= 2000)
                keep = keep[keep != 0]
                retained = np.isin(groups,keep)
                geoms = [shape(g) for g,v in shapes(retained.astype('uint8'),mask=retained,transform=grid.transform) if v]
                for poly in geoms:
                    inside = geometry_mask([mapping(poly)],grid.shape,grid.transform,invert=True)
                    # Inward buffer before simplification keeps the displayed outline conservative.
                    display = poly.buffer(-12).simplify(8,preserve_topology=True)
                    if display.is_empty: continue
                    records.append({'species':species,'geom':display,'source':src,
                                    'depth':[float(shallow[inside].min()),float(deep[inside].max())]})
                print(src['key'],species,len(geoms),round(retained.sum()/10000,2),'km2',flush=True)
    output=[]
    for species in ['halibut','dungeness']:
        relevant=[r for r in records if r['species']==species]
        merged=unary_union([r['geom'] for r in relevant])
        polygons = list(merged.geoms) if merged.geom_type=='MultiPolygon' else [merged]
        for poly in sorted(polygons,key=lambda g:g.area,reverse=True):
            if poly.is_empty or poly.area < 200000: continue
            contributing=[r for r in relevant if r['geom'].intersects(poly)]
            p=poly.representative_point(); lon,lat=geo(p.x,p.y)
            source_keys=sorted(set(r['source']['key'] for r in contributing))
            urls=sorted(set(r['source']['source_url'] for r in contributing))
            region='Estero Bay' if lat < 35.43 else 'Cayucos / Point Estero'
            if lat <35.3: region='Avila / Point Buchon'
            output.append({'id':f"{species.upper()}-AREA-{len(output)+1:02d}",
                'label':f'{region} '+('shallow sand & mud' if species=='halibut' else 'soft-bottom grounds'),
                'species':[species],'latitude':round(lat,6),'longitude':round(lon,6),
                'source_id':source_keys[0],'source_ids':source_keys,'source_url':urls[0],'source_urls':urls,
                'depth_ft':[round(min(r['depth'][0] for r in contributing),1),round(max(r['depth'][1] for r in contributing),1)],
                'soft_bottom_percent':100,'area_km2':round(poly.area/1e6,2),'geometry':rounded_geometry(poly,geo),
                'survey_year':2008,'datum':'MLLW','evidence':'Contiguous surveyed soft sediment. Holes and gaps exclude rock, missing coverage, depth exclusions and the dated closure buffer. Fish presence is unverified.'})
    target=Path(__file__).resolve().parents[1]/'dist/data/habitat-regions.json'
    target.write_text(json.dumps({'schema_version':1,'built_date':'2026-09-21','areas':output,
        'method':'Native bathymetry min/max and substrate min/max aggregated to 10 m. Every contributing cell must have full native coverage, class 1 throughout, and depths 25–100 ft for halibut or 25–195 ft for crab. Dated closures buffered 505 m; 20 m erosion plus 12 m inward buffer and 8 m simplification; connected regions >=0.2 km². No gap bridging or catch ranking.'},separators=(',',':'))+'\n')
    print('Published',len(output),'connected regions',target.stat().st_size,'bytes')

if __name__=='__main__': main()
