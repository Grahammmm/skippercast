"""Local C1 elevation/contributor rasters to contours and XYZ preview tiles.

No acquisition or publication. All outputs are NOT FOR NAVIGATION, review_required.
GDALContourGenerate is the same contour engine as gdal_contour; utility CLIs
are unnecessary. Source elevation is metres positive up; depths are feet down.
"""
from __future__ import annotations

import argparse
import ctypes as ct
import ctypes.util
import json
import math
from pathlib import Path
import tempfile

import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds
from shapely.geometry import shape, mapping, LineString, MultiLineString
from shapely.ops import unary_union, transform, linemerge
from pyproj import Transformer

LABEL = 'NOT FOR NAVIGATION; research preview; review_required'
FOOT = 0.3048
WORLD = 20037508.342789244


def levels(max_depth_ft):
    """Positive depth levels, excluding zero and levels beyond actual maximum."""
    if not math.isfinite(max_depth_ft) or max_depth_ft < 0:
        raise ValueError('Maximum depth must be finite and nonnegative')
    return list(range(10, min(600, math.floor(max_depth_ft)) + 1, 10)) + list(
        range(700, math.floor(max_depth_ft) + 1, 100))


class GDAL:
    """Typed bindings to GDAL/OGR's stable contour and vector utility APIs."""
    def __init__(self):
        bundled = sorted((Path(rasterio.__file__).parent.parent / 'rasterio.libs').glob('*gdal*'))
        library = str(bundled[0]) if bundled else ctypes.util.find_library('gdal')
        if not library:
            raise RuntimeError('GDAL shared library unavailable')
        self.lib = ct.CDLL(library)
        P, S, I, D = ct.c_void_p, ct.c_char_p, ct.c_int, ct.c_double
        signatures = {
            'GDALAllRegister': ([], None), 'GDALOpen': ([S, I], P),
            'GDALClose': ([P], None), 'GDALGetRasterBand': ([P, I], P),
            'OGRGetDriverByName': ([S], P), 'OGR_Dr_CreateDataSource': ([P, S, P], P),
            'OGR_DS_CreateLayer': ([P, S, P, I, P], P), 'OGR_DS_Destroy': ([P], None),
            'OGR_Fld_Create': ([S, I], P), 'OGR_Fld_Destroy': ([P], None),
            'OGR_L_CreateField': ([P, P, I], I),
            'GDALContourGenerate': ([P, D, D, I, ct.POINTER(D), I, D, P, I, I, P, P], I),
            'GDALOpenEx': ([S, ct.c_uint, P, P, P], P),
            'GDALVectorTranslateOptionsNew': ([ct.POINTER(S), P], P),
            'GDALVectorTranslateOptionsFree': ([P], None),
            'GDALVectorTranslate': ([S, P, I, ct.POINTER(P), P, ct.POINTER(I)], P),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.lib, name)
            fn.argtypes, fn.restype = args, result
        self.lib.GDALAllRegister()

    def contours(self, raster, destination, depth_levels, nodata):
        g = self.lib
        source = g.GDALOpen(str(raster).encode(), 0)
        driver = g.OGRGetDriverByName(b'GeoJSON')
        if not source or not driver:
            if source:
                g.GDALClose(source)
            raise RuntimeError('GDAL cannot open contour input/GeoJSON driver')
        target = g.OGR_Dr_CreateDataSource(driver, str(destination).encode(), None)
        if not target:
            g.GDALClose(source)
            raise RuntimeError('Cannot create raw contour dataset')
        try:
            layer = g.OGR_DS_CreateLayer(target, b'contours', None, 2, None)
            field = g.OGR_Fld_Create(b'elevation_m', 2)
            try:
                if not layer or g.OGR_L_CreateField(layer, field, 0):
                    raise RuntimeError('Cannot create elevation field')
            finally:
                g.OGR_Fld_Destroy(field)
            values = (ct.c_double * len(depth_levels))(*sorted(-x * FOOT for x in depth_levels))
            if g.GDALContourGenerate(g.GDALGetRasterBand(source, 1), 0, 0,
                                    len(values), values, 1, nodata, layer, -1, 0, None, None):
                raise RuntimeError('GDAL contour generation failed')
        finally:
            g.OGR_DS_Destroy(target)
            g.GDALClose(source)

    def mvt(self, source, destination, zoom):
        g = self.lib
        handle = g.GDALOpenEx(str(source).encode(), 4, None, None, None)
        if not handle:
            raise RuntimeError('Cannot open labelled GeoJSON')
        arguments = ['-f', 'MVT', '-dsco', f'MINZOOM={zoom}', '-dsco', f'MAXZOOM={zoom}',
                     '-dsco', 'COMPRESS=NO', '-nln', 'contours']
        args = (ct.c_char_p * (len(arguments) + 1))(*[x.encode() for x in arguments], None)
        opts = g.GDALVectorTranslateOptionsNew(args, None)
        result = None
        try:
            if not opts:
                raise RuntimeError('GDAL rejected MVT options')
            usage = ct.c_int()
            result = g.GDALVectorTranslate(str(destination).encode(), None, 1,
                                          (ct.c_void_p * 1)(handle), opts, ct.byref(usage))
            if not result or usage.value:
                raise RuntimeError('GDAL MVT conversion failed')
        finally:
            if result:
                g.GDALClose(result)
            if opts:
                g.GDALVectorTranslateOptionsFree(opts)
            g.GDALClose(handle)


def parts(geometry):
    if geometry.geom_type == 'LineString':
        yield geometry
    elif hasattr(geometry, 'geoms'):
        for item in geometry.geoms:
            yield from parts(item)


def clipped_parts(line, mask):
    """Rejoin clip fragments at a closed ring's arbitrary start/end vertex.

    Extract only linework (intersection may also contain points), then merge
    exactly shared endpoints. Do not snap or relax the boundary guard.
    """
    segments = [segment for segment in parts(line.intersection(mask)) if not segment.is_empty]
    if segments:
        yield from parts(linemerge(segments))


def tile_range(bounds, zoom):
    span = 2 * WORLD / (2 ** zoom)
    west, south, east, north = bounds
    limit = 2 ** zoom - 1
    x0, x1 = [min(limit, max(0, math.floor((v + WORLD) / span))) for v in (west, east)]
    y0, y1 = [min(limit, max(0, math.floor((WORLD - v) / span))) for v in (north, south)]
    return [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


def simplify_contours(lines, tolerance):
    """Preserve topology BETWEEN contours as well as within each contour.

    Independent Douglas-Peucker calls can move close depth bands across one
    another. GEOS preserves their joint topology when given one collection;
    component order and endpoints are retained for the parallel depth labels.
    """
    simplified = MultiLineString(lines).simplify(tolerance, preserve_topology=True)
    result = list(simplified.geoms)
    if len(result) != len(lines):
        raise ValueError('Contour simplification changed component count')
    return result


def nearest_terrain(values, valid, source_affine, source_crs, tile_affine):
    """Exact inverse projection of XYZ pixel centres, without warp approximation.

    Floor maps pixel-corner coordinates to the containing source pixel, whose
    centre is the nearest centre. Unsupported and outside pixels stay nodata.
    This does not interpolate, fill holes, or imply source/datum accuracy.
    """
    rows, cols = np.indices((256, 256), dtype='float64')
    x = tile_affine.a * (cols + 0.5) + tile_affine.c
    y = tile_affine.e * (rows + 0.5) + tile_affine.f
    project = Transformer.from_crs('EPSG:3857', source_crs, always_xy=True)
    sx, sy = project.transform(x, y)
    inverse = ~source_affine
    cc = inverse.a * sx + inverse.b * sy + inverse.c
    rr = inverse.d * sx + inverse.e * sy + inverse.f
    inside = (np.isfinite(cc) & np.isfinite(rr) & (cc >= 0) & (rr >= 0)
              & (cc < values.shape[1]) & (rr < values.shape[0]))
    r, c = np.floor(rr[inside]).astype('int64'), np.floor(cc[inside]).astype('int64')
    warped = np.full((256, 256), -999999, dtype='float32')
    warped[inside] = np.where(valid[r, c], values[r, c], -999999)
    return warped


def build(elevation, contributor, manifest, output, *, zoom=10, max_cells=4_000_000, max_tiles=64):
    """Build bounded local preview. Manifest uses C1 sources[].code/resolution_m."""
    if not isinstance(zoom, int) or not 0 <= zoom <= 18:
        raise ValueError('Zoom must be an integer in 0..18')
    for path in (elevation, contributor):
        if '://' in str(path) or str(path).startswith('/vsi') or Path(path).suffix.lower() not in {'.tif', '.tiff'}:
            raise ValueError('Only local GeoTIFF inputs supported')
    output = Path(output)
    if output.exists():
        raise FileExistsError('Use a fresh output directory')
    metadata = json.loads(Path(manifest).read_text())
    sources = {}
    for row in metadata['sources']:
        code, resolution = row['code'], row['resolution_m']
        if not isinstance(code, int) or code <= 0 or code in sources or not math.isfinite(resolution) or resolution <= 0:
            raise ValueError('Invalid source code/resolution')
        sources[code] = row
    with rasterio.open(elevation) as grid, rasterio.open(contributor) as codes:
        if grid.driver != 'GTiff' or codes.driver != 'GTiff':
            raise ValueError('GeoTIFF required')
        if (grid.crs != codes.crs or grid.transform != codes.transform or grid.shape != codes.shape
                or not grid.crs or not grid.crs.is_projected or grid.crs.linear_units != 'metre'
                or grid.transform.b != 0 or grid.transform.d != 0):
            raise ValueError('Aligned projected metre grids required')
        if grid.width * grid.height > max_cells:
            raise ValueError('Raster exceeds preview cell cap')
        values, ids = grid.read(1), codes.read(1)
        valid = (grid.read_masks(1) > 0) & np.isfinite(values) & (codes.read_masks(1) > 0) & (ids > 0)
        if not valid.any():
            raise ValueError('No supported finite elevation cells')
        if set(int(x) for x in np.unique(ids[valid])) - sources.keys():
            raise ValueError('Contributor code missing from source manifest')
        depths = levels(max(0, -float(values[valid].min()) / FOOT))
        if not depths:
            raise ValueError('No 10-foot depth contours in raster')
        mercator = transform_bounds(grid.crs, 'EPSG:3857', *grid.bounds, densify_pts=21)
        tiles = tile_range(mercator, zoom)
        if len(tiles) > max_tiles:
            raise ValueError('Terrain tile cap exceeded')
        masks = {}
        for geom, code in shapes(np.where(valid, ids, 0).astype('int32'), transform=grid.transform):
            if code:
                masks.setdefault(int(code), []).append(shape(geom))
        masks = {code: unary_union(polygons) for code, polygons in masks.items()}
        tolerance = min(grid.res) / 2
        project = Transformer.from_crs(grid.crs, 'EPSG:4326', always_xy=True).transform
        output.mkdir(parents=True)
        engine = GDAL()
        features = []
        with tempfile.TemporaryDirectory(dir=output) as temporary:
            temporary = Path(temporary)
            clean = temporary / 'supported.tif'
            profile = grid.profile.copy()
            profile.update(count=1, dtype='float32', nodata=-999999)
            with rasterio.open(clean, 'w', **profile) as target:
                target.write(np.where(valid, values, -999999).astype('float32'), 1)
            raw = temporary / 'raw.geojson'
            engine.contours(clean, raw, depths, -999999)
            by_source = {code: [] for code in masks}
            for feature in json.loads(raw.read_text())['features']:
                line = shape(feature['geometry'])
                depth = round(-feature['properties']['elevation_m'] / FOOT)
                for code, mask in masks.items():
                    for segment in clipped_parts(line, mask):
                        if segment.length:
                            by_source[code].append((depth, segment))
            for code, entries in by_source.items():
                if not entries:
                    continue
                mask = masks[code]
                simplified = simplify_contours([line for _, line in entries], tolerance)
                for (depth, _), segment in zip(entries, simplified):
                    # Final clip prevents simplification chords spanning holes.
                    for clipped in clipped_parts(segment, mask):
                        if clipped.length == 0:
                            continue
                        if not clipped.is_simple or not clipped.is_valid:
                            raise ValueError('Non-simple contour refused')
                        if not clipped.is_closed:
                            for endpoint in (clipped.coords[0], clipped.coords[-1]):
                                if LineString([endpoint, endpoint]).distance(mask.boundary) > tolerance * 1e-5:
                                    raise ValueError('Open contour not clipped at contributor boundary')
                        properties = dict(depth_ft=depth, depth_m=depth * FOOT,
                                          depth_band='0-600ft' if depth <= 600 else '600ft+',
                                          interval_ft=10 if depth <= 600 else 100,
                                          source_code=code, source_id=sources[code]['id'],
                                          source_resolution_m=sources[code]['resolution_m'],
                                          navigation=LABEL)
                        features.append(dict(type='Feature', properties=properties,
                                             geometry=mapping(transform(project, clipped))))
        if not features:
            raise ValueError('No supported contour lines generated')
        geojson = output / 'contours.geojson'
        geojson.write_text(json.dumps(dict(type='FeatureCollection', features=features), allow_nan=False) + '\n')
        engine.mvt(geojson, output / 'vector', zoom)
        terrain = output / 'terrain'
        span = 2 * WORLD / (2 ** zoom)
        for x, y in tiles:
            west, north = -WORLD + x * span, WORLD - y * span
            affine = from_bounds(west, north - span, west + span, north, 256, 256)
            warped = nearest_terrain(values, valid, grid.transform, grid.crs, affine)
            supported = warped != -999999
            encoded = np.rint((warped.astype('float64') + 10000) * 10)
            if ((encoded[supported] < 0) | (encoded[supported] > 16777215)).any():
                raise ValueError('Elevation outside terrain-RGB range')
            encoded = np.where(supported, encoded, 0).astype('uint32')
            rgba = np.stack([(encoded >> 16) & 255, (encoded >> 8) & 255,
                             encoded & 255, supported * 255]).astype('uint8')
            tile = terrain / str(zoom) / str(x) / f'{y}.png'
            tile.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(tile, 'w', driver='PNG', width=256, height=256, count=4, dtype='uint8') as target:
                target.write(rgba)
        result = dict(schema_version=1, status='review_required', navigation=LABEL,
                      contour_features=len(features), levels_ft=depths, simplify_m=tolerance,
                      zoom=zoom, terrain_tiles=len(tiles), value_convention='elevation_positive_up',
                      terrain_encoding='elevation_m = -10000 + (R*65536+G*256+B)*0.1; alpha=0 unsupported',
                      terrain_sampling='exact inverse-projected XYZ pixel centres; nearest source cell',
                      simplification='joint topology-preserving per contributor; half-cell tolerance',
                      contour_crs='EPSG:4326', tile_scheme='XYZ',
                      terrain_template='terrain/{z}/{x}/{y}.png', vector_template='vector/{z}/{x}/{y}.pbf',
                      limitations=['Synthetic/local preview only; no datum reconciliation or seam acceptance.'])
        (output / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('elevation', 'contributor', 'manifest', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--zoom', type=int, default=10)
    parser.add_argument('--max-cells', type=int, default=4_000_000)
    parser.add_argument('--max-tiles', type=int, default=64)
    print(json.dumps(build(**vars(parser.parse_args()))))


if __name__ == '__main__':
    main()
