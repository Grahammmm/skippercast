"""Compile one reviewed USGS classified raster into generalized context polygons.

This optional GIS adapter needs rasterio, numpy, shapely, and pyproj. It never
publishes fishing targets, legal depth, or invented boulder descriptions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def compile_context(source, archive, output):
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.features import shapes
    from rasterio.io import MemoryFile
    from shapely.geometry import shape, mapping
    from shapely.ops import transform
    from pyproj import Transformer

    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != source['character_sha256']:
        raise ValueError('Original USGS raster digest changed; review source before importing')
    with zipfile.ZipFile(archive) as bundle:
        members = [name for name in bundle.namelist() if name.lower().endswith('.tif')]
        if len(members) != 1:
            raise ValueError('Expected exactly one original class GeoTIFF')
        raw = bundle.read(members[0])
    with MemoryFile(raw) as mem, mem.open() as raster:
        native = source['native_class_resolution_m']
        if raster.count != 1 or not raster.crs or not raster.crs.is_projected or any(abs(r-native)>.01 for r in raster.res):
            raise ValueError('Unexpected source grid, CRS or native resolution')
        cell = source['display_resolution_m']
        if cell < native or cell/native > 20:
            raise ValueError('Unsupported display generalization')
        width, height = round(raster.width*native/cell), round(raster.height*native/cell)
        values = raster.read(1, out_shape=(height,width), resampling=Resampling.mode)
        if not set(np.unique(values)) <= {0,1,2,3}:
            raise ValueError('Unreviewed seafloor class code')
        affine = raster.transform * raster.transform.scale(raster.width/width, raster.height/height)
        selected = (values == source['class']).astype('uint8')
        project = Transformer.from_crs(raster.crs, 'EPSG:4326', always_xy=True).transform
        candidates = []
        for geometry, value in shapes(selected, mask=selected.astype(bool), transform=affine):
            if value != 1:
                continue
            polygon = shape(geometry)
            if polygon.area < source['minimum_display_area_m2']:
                continue
            polygon = polygon.simplify(cell/2, preserve_topology=True)
            if polygon.is_empty or not polygon.is_valid:
                continue
            candidates.append((polygon.area, transform(project, polygon)))
        candidates.sort(key=lambda entry: -entry[0])
        features = []
        for index, (area, polygon) in enumerate(candidates,1):
            features.append({'type':'Feature','geometry':mapping(polygon),'properties':{
                'id':f"{source['id']}-{index:03d}", 'name':source['class_name'],
                'source_id':source['id'], 'source_url':source['data_release_url'],
                'source_year':source['source_year'], 'class_code':source['class'],
                'source_area_m2':round(area), 'native_resolution_m':native,
                'display_resolution_m':cell, 'fishing_target':False,
                'exportable':False, 'depth_qualified':False,
                'fish_confirmed':False}})
    payload={'type':'FeatureCollection','schema_version':1,'scope':'generalized-seafloor-character-context',
             'source_id':source['id'],'sector_id':source['sector_id'],
             'source_url':source['data_release_url'],'source_file_sha256':actual,
             'method':f"Mode resampling of {native} m source class to {cell} m display cells; polygons below {source['minimum_display_area_m2']} m² omitted; simplified by {cell/2:g} m in source projection.",
             'rights':source['rights'],'limitations':source['limitations'],
             'features':features}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(payload,separators=(',',':'))+'\n')
    return len(features)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-id',required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    catalog=json.loads((Path(__file__).resolve().parents[1]/'catalog/usgs-seafloor-sources.json').read_text())
    source=next((row for row in catalog['sources'] if row['id']==args.source_id),None)
    if not source:raise ValueError('Unknown reviewed USGS source')
    count=compile_context(source,args.archive,args.output)
    print(f'{count} generalized historical context polygons; zero fishing targets')


if __name__=='__main__':main()
