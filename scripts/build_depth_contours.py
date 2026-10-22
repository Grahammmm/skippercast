"""Trace a region's shelf depth contours from its reviewed survey grids (CI6-13).

Run on the processing host, with the survey stack (requirements-survey.txt):

    PYTHONPATH=src python scripts/build_depth_contours.py --region morro-bay \\
        --grid usgs-point-buchon=/path/Bathymetry_OffshorePointBuchon.tif \\
        --grid usgs-morro-bay=/path/Bathymetry_OffshoreMorroBay.tif \\
        --grid usgs-point-estero=/path/Bathymetry_OffshorePointEstero.tif

Each grid must be the original producer GeoTIFF of an approved bathymetry
source bound to the region (catalog/sources.json, regions/<id>/region.json).
Its SHA-256 is recorded in the output's provenance; local paths never reach
the output. The output is catalog/depth-contours/<id>.geojson; then rebuild the
platform (PYTHONPATH=src python -m skippercast.platform.build), which checks it
and publishes dist/regions/<id>/depth-contours*.geojson. The method is
described in src/skippercast/platform/depth_contours.py.
"""
import argparse
import hashlib
from pathlib import Path
import sys

import numpy as np
import rasterio
from rasterio import features as rio_features
from rasterio.transform import Affine
from rasterio.windows import Window
from pyproj import Transformer
from shapely import line_merge, unary_union
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from skippercast.platform.contracts import REPO, atomic_json, load_catalogs, load_region  # noqa: E402
from skippercast.platform import depth_contours as dc  # noqa: E402
from skippercast.coastal import vertical  # noqa: E402

STRIP_BLOCKS = 64
# Survey-edge display: outline simplification, and the shortest piece kept (a smaller gap still stops the lines).
EDGE_TOLERANCE_M = 12
EDGE_MIN_LENGTH_M = 200
CONTOUR_TOLERANCE_M = 3


def sha256(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def native_offsets(grid, lattice):
    """The grid's native column and row at the lattice's top-left corner, and cells per block; refuses misaligned grids."""
    x0, y0, _, _ = lattice
    if grid.crs is None or not grid.crs.is_projected or grid.crs.linear_units != 'metre':
        raise ValueError(f'{grid.name}: expected a projected, metre-based survey grid')
    cell = grid.res[0]
    if abs(grid.res[0] - grid.res[1]) > 1e-9 or (dc.CELL_M / cell) % 1:
        raise ValueError(f'{grid.name}: square cells dividing {dc.CELL_M} m are required, got {grid.res}')
    col0, row0 = (x0 - grid.transform.c) / cell, (grid.transform.f - y0) / cell
    if abs(col0 - round(col0)) > 1e-6 or abs(row0 - round(row0)) > 1e-6:
        raise ValueError(f'{grid.name}: native cells do not align with the {dc.CELL_M} m lattice')
    return round(col0), round(row0), int(dc.CELL_M / cell)


def require_contour_vertical(grid):
    """Refuse explicit metadata incompatible with this legacy elevation reader.

    Missing metadata retains the original producer metre/elevation convention;
    it does not establish a resolved vertical contract or certify a datum.
    Conversion requires the separate evidence-bound coastal.vertical path.
    Inspect both band/dataset tags and vertical CRS axes, not sample signs.
    """
    observed = vertical.from_raster(grid)
    if observed['conflicts']:
        raise ValueError(f'{grid.name}: conflicting vertical metadata: {observed["conflicts"]}')
    if observed['units'] not in (None, 'm'):
        raise ValueError(f'{grid.name}: contour grids require vertical units in metres')
    if observed['sign_hint'] not in (None, 'positive_up'):
        raise ValueError(f'{grid.name}: contour grids require positive-up elevation')


def merged_blocks(paths, lattice):
    """The grids merged cell by cell (the first grid with valid water wins each native cell) and averaged into CELL_M blocks.

    Returns (depth_ft, owner, crs): depth is NaN for a block with any missing, land or nodata native cell; owner is
    the index of the grid supplying most of a valid block's cells (-1 elsewhere). Merging native cells first means a
    block straddling a seam between two surveys still counts, so a seam is never a gap.
    """
    _, _, width, height = lattice
    grids = [rasterio.open(p) for p in paths]
    try:
        for grid in grids:
            require_contour_vertical(grid)
        offsets = [native_offsets(g, lattice) for g in grids]
        if len({n for _, _, n in offsets}) != 1 or len({str(g.crs) for g in grids}) != 1:
            raise ValueError('Every grid must share one projected CRS and cell size')
        n = offsets[0][2]
        depth = np.full((height, width), np.nan, dtype='float64')
        owner = np.full((height, width), -1, dtype='int8')
        for by in range(0, height, STRIP_BLOCKS):
            rows = min(STRIP_BLOCKS, height - by)
            merged = np.full((rows * n, width * n), np.nan, dtype='float64')
            source = np.full(merged.shape, -1, dtype='int8')
            for i, (grid, (col0, row0, _)) in enumerate(zip(grids, offsets)):
                window = Window(col0, row0 + by * n, width * n, rows * n)
                values = grid.read(1, window=window, boundless=True, masked=True).filled(np.nan).astype('float64')
                water = np.isfinite(values) & (values < 0) & (values >= -3000)
                fill = water & (source < 0)
                merged[fill], source[fill] = values[fill], i
            blocks = merged.reshape(rows, n, width, n)
            valid = np.isfinite(blocks).all(axis=(1, 3))
            depth[by:by + rows] = np.where(valid, -blocks.sum(axis=(1, 3)) / (n * n) * dc.FEET_PER_M, np.nan)
            counts = np.stack([(source == i).reshape(rows, n, width, n).sum(axis=(1, 3)) for i in range(len(grids))])
            owner[by:by + rows] = np.where(valid, counts.argmax(axis=0), -1)
        return depth, owner, str(grids[0].crs)
    finally:
        for g in grids:
            g.close()


def lattice_for(paths):
    """The shared lattice (x0, y0, width, height) covering every grid, its corner on the first grid's native cell edges."""
    bounds = []
    for path in paths:
        with rasterio.open(path) as g:
            bounds.append(g.bounds)
    west, south = min(b.left for b in bounds), min(b.bottom for b in bounds)
    east, north = max(b.right for b in bounds), max(b.top for b in bounds)
    # Phase: the first grid's own corner, stepped out in whole blocks (the other grids must share its cell edges).
    px, py = bounds[0].left, bounds[0].top
    x0 = px - np.ceil((px - west) / dc.CELL_M) * dc.CELL_M
    y0 = py + np.ceil((north - py) / dc.CELL_M) * dc.CELL_M
    return float(x0), float(y0), int(np.ceil((east - x0) / dc.CELL_M)), int(np.ceil((y0 - south) / dc.CELL_M))


def to_lonlat(transformer, points):
    xs, ys = transformer.transform([p[0] for p in points], [p[1] for p in points])
    return [[round(x, dc.DECIMALS), round(y, dc.DECIMALS)] for x, y in zip(xs, ys)]


def dedupe(line):
    out = [line[0]]
    for p in line[1:]:
        if p != out[-1]:
            out.append(p)
    return out


def polygons(mask, transform):
    return unary_union([shape(g) for g, _ in rio_features.shapes(mask.astype('uint8'), mask=mask, transform=transform)])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--region', required=True)
    p.add_argument('--grid', action='append', required=True, metavar='SOURCE_ID=PATH')
    args = p.parse_args()
    region = load_region(args.region)
    _, sources = load_catalogs()
    bound = region['source_bindings']['bathymetry']
    grids = dict(item.split('=', 1) for item in args.grid)
    order = [ident for ident in bound if ident in grids]
    if set(grids) - set(order):
        raise SystemExit(f'Not bathymetry bindings of {region["id"]}: {sorted(set(grids) - set(order))}')
    for ident in order:
        if sources[ident]['review_status'] != 'approved' or 'bathymetry' not in sources[ident]['needs']:
            raise SystemExit(f'{ident} is not an approved bathymetry source')
    lattice = lattice_for([grids[i] for i in order])
    x0, y0, _, _ = lattice
    block = Affine(dc.CELL_M, 0, x0, 0, -dc.CELL_M, y0)
    depth, owner, crs = merged_blocks([grids[i] for i in order], lattice)
    transformer = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
    union = polygons(owner >= 0, block)
    features, listed = [], []
    for i, ident in enumerate(order):
        reviewed = sources[ident]
        mine = owner == i
        survey_date = str(reviewed['survey_year'])
        entry = {'source_id': ident, 'name': reviewed['name'], 'url': reviewed['documentation_url'],
                 'attribution': reviewed['rights']['attribution'], 'sha256': sha256(grids[ident]), 'survey_date': survey_date,
                 'vertical_datum': reviewed.get('vertical_datum') or dc.UNVERIFIED_DATUM,
                 'native_cell_m': reviewed.get('native_resolution_m'), 'supported_blocks': int(mine.sum())}
        listed.append(entry)
        if not mine.any():
            continue
        common = {'source_id': ident, 'survey_date': survey_date, 'vertical_datum': entry['vertical_datum']}
        own = np.where(mine, depth, np.nan)
        rows = [[None if not np.isfinite(v) else float(v) for v in row] for row in own]
        for d, lines in dc.trace(rows, dc.levels(float(np.nanmin(own)), float(np.nanmax(own)))).items():
            out = []
            for line in lines:
                metres = [(x0 + (c + 0.5) * dc.CELL_M, y0 - (r + 0.5) * dc.CELL_M) for c, r in line]
                ll = dedupe(to_lonlat(transformer, dc.simplify(metres, CONTOUR_TOLERANCE_M, (1.0, 1.0))))
                if len(ll) >= 2:
                    out.append(ll)
            if out:
                features.append({'type': 'Feature', 'id': f'{ident}-{d}ft',
                                 'geometry': {'type': 'MultiLineString', 'coordinates': out},
                                 'properties': {'kind': 'contour', 'depth_ft': d, 'index': d % dc.INDEX_FT == 0, **common}})
        # Where the contours stop: the outline of all the surveys' supported blocks together, each part credited to the
        # survey whose blocks it bounds. A seam between two surveys is not an edge: a reviewed grid continues there.
        edge = line_merge(polygons(mine, block).boundary.intersection(union.boundary))
        pieces = [g for g in getattr(edge, 'geoms', [edge]) if g.geom_type == 'LineString' and g.length >= EDGE_MIN_LENGTH_M]
        lines = sorted(ll for ll in (dedupe(to_lonlat(transformer, list(g.simplify(EDGE_TOLERANCE_M).coords))) for g in pieces) if len(ll) >= 2)
        if lines:
            features.append({'type': 'Feature', 'id': f'{ident}-edge', 'geometry': {'type': 'MultiLineString', 'coordinates': lines},
                             'properties': {'kind': 'survey-edge', **common}})
    xs = [pt[0] for f in features for line in f['geometry']['coordinates'] for pt in line]
    ys = [pt[1] for f in features for line in f['geometry']['coordinates'] for pt in line]
    collection = {'type': 'FeatureCollection', 'schema_version': dc.SCHEMA_VERSION, 'provenance': {
        'region_id': region['id'], 'units': 'ft', 'interval_ft': dc.INTERVAL_FT, 'index_ft': dc.INDEX_FT,
        'shelf_limit_ft': dc.SHELF_LIMIT_FT, 'cell_m': dc.CELL_M, 'horizontal_crs': crs,
        'bounds': [min(xs), min(ys), max(xs), max(ys)], 'features': len(features), 'sources': listed,
        'coordinate_decimals': dc.DECIMALS, 'simplify_tolerance_m': CONTOUR_TOLERANCE_M,
        'edge': {'tolerance_m': EDGE_TOLERANCE_M, 'min_length_m': EDGE_MIN_LENGTH_M,
                 'note': 'The outline of all the surveys\' supported blocks together; seams between surveys are not edges.'},
        'datum_note': 'Depths are below each survey\'s own vertical datum. The original GeoTIFFs declare none; '
                      'the companion USGS report (Open-File Report 2023-1064) names MLLW. Not converted or certified.',
        'method': f'Native cells are merged in the region\'s binding order (the first survey with valid water wins each cell); '
                  f'each {dc.CELL_M} m block is their mean and counts only when all of them are valid water. Marching squares '
                  f'at every {dc.INTERVAL_FT} ft to {dc.SHELF_LIMIT_FT} ft draws only between four valid blocks of one survey '
                  '(the survey supplying most of each block), so lines stop where the reviewed grid stops.',
        'limitations': 'Not for navigation. Historical survey; the bottom can have changed. Display contours from averaged blocks, '
                       'not soundings or chart depths.'},
        'features': features}
    dc.check_contours(collection, region, sources)
    receipt = atomic_json(REPO / 'catalog/depth-contours' / f'{region["id"]}.geojson', collection)
    print({'features': len(features), **receipt, 'sources': [(s['source_id'], s['sha256'][:12], s['supported_blocks']) for s in listed]})


if __name__ == '__main__':
    main()
