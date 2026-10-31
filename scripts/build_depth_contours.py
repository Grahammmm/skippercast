"""Trace a region's shelf depth contours from its reviewed survey grids (CI6-13).

Run on the processing host, with the survey stack (requirements-survey.txt):

    PYTHONPATH=src python scripts/build_depth_contours.py --region morro-bay \\
        --grid usgs-point-buchon=/path/Bathymetry_OffshorePointBuchon.tif \\
        --grid usgs-morro-bay=/path/Bathymetry_OffshoreMorroBay.tif \\
        --grid usgs-point-estero=/path/Bathymetry_OffshorePointEstero.tif

Each grid must be the original producer GeoTIFF of an approved bathymetry
source bound to the region (catalog/sources.json, regions/<id>/region.json),
or for an `adapter: bag` source one regular NOAA BAG, named with its survey:
`--grid noaa-bag=/path/H12345_MB_2m.bag --bag-survey noaa-bag=H12345`.
Its SHA-256 is recorded in the output's provenance; local paths never reach
the output. The output is catalog/depth-contours/<id>.geojson (or --output PATH, outside the
work tree, for the same approved-only collection); then rebuild the
platform (PYTHONPATH=src python -m skippercast.platform.build), which checks it
and publishes dist/regions/<id>/depth-contours*.geojson. The method is
described in src/skippercast/platform/depth_contours.py.
"""
import argparse
from contextlib import ExitStack
import hashlib
import importlib.util
from pathlib import Path
import re
import sys

import numpy as np
import rasterio
from rasterio import features as rio_features
from rasterio.transform import Affine
from rasterio.warp import transform_bounds
from rasterio.windows import Window
from pyproj import CRS, Transformer
from shapely import line_merge, unary_union
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from skippercast.platform.contracts import REPO, atomic_json, load_catalogs, load_region  # noqa: E402
from skippercast.platform import depth_contours as dc  # noqa: E402
from skippercast.platform import seafloor_ec as ec  # noqa: E402

# EC5: a block's class index (-1 none) and, by the bitmask of the code classes (tens digits) in it, seafloor_ec.block_class.
CLASS_INDEX = {'measured': 0, 'filled': 1, 'verified': 2, 'unresolved': 3}
CLASS_LUT = np.array([CLASS_INDEX[ec.block_class([10 * k for k in range(6) if m >> k & 1])] if m else -1 for m in range(64)],
                     dtype='int8')
UNRESOLVED_CODES = [c for c in ec.CODES.values() if ec.CLASS_OF(c) == 'unresolved']
REASON_CODES = [[ec.CODES[f'unresolved-{r}']] if r != 'nodata' else [ec.CODES['nodata'], ec.CODES['masked-sentinel']]
                for r in ec.UNRESOLVED_REASONS]
EC_METHOD = (' Blocks carry the error-correction class of their native cells (measured, filled, verified) when a provenance '
             'grid was supplied; unresolved blocks are drawn as areas, never as contours.')

STRIP_BLOCKS = 64
# Survey-edge display: outline simplification, and the shortest piece kept (a smaller gap still stops the lines).
EDGE_TOLERANCE_M = 12
EDGE_MIN_LENGTH_M = 200
CONTOUR_TOLERANCE_M = 3
# P4's preflight (check_grid / Refused), loaded from beside this script: it imports nothing from seafloor/.
_spec = importlib.util.spec_from_file_location('preflight_native_grid', Path(__file__).with_name('preflight_native_grid.py'))
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)
USGS_DATUM = ' The original GeoTIFFs declare none; the companion USGS report (Open-File Report 2023-1064) names MLLW.'
BAG_DATUM = ' BAG surveys: the datum each BAG\'s metadata declares, copied as declared.'


def sha256(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def native_offsets(grid, lattice):
    """The grid's native column and row at the lattice's top-left corner, and cells per block; refuses misaligned grids."""
    x0, y0, _, _ = lattice
    crs = horizontal_crs(grid)
    if not crs.is_projected or any(axis.unit_name != 'metre' for axis in crs.axis_info[:2]):
        raise ValueError(f'{grid.name}: expected a projected, metre-based survey grid')
    cell = grid.res[0]
    if abs(grid.res[0] - grid.res[1]) > 1e-9 or (dc.CELL_M / cell) % 1:
        raise ValueError(f'{grid.name}: square cells dividing {dc.CELL_M} m are required, got {grid.res}')
    col0, row0 = (x0 - grid.transform.c) / cell, (grid.transform.f - y0) / cell
    if abs(col0 - round(col0)) > 1e-6 or abs(row0 - round(row0)) > 1e-6:
        raise ValueError(f'{grid.name}: native cells do not align with the {dc.CELL_M} m lattice')
    return round(col0), round(row0), int(dc.CELL_M / cell)


def merged_blocks(grids, lattice, offsets, keys, ecs=None):
    """The grids merged cell by cell (the first grid with valid water wins each native cell) and averaged into CELL_M blocks.

    Returns (depth_ft, owner): depth is NaN for a block with any missing, land or nodata native cell; owner is
    the index of the grid supplying most of a valid block's cells (-1 elsewhere) within one group. Merging native cells
    first means a block straddling a seam between two surveys still counts, so a seam is never a gap. Cells merge only
    inside a group of one cell size and declared datum (`keys`). Across groups the first grid whose own block is fully
    valid wins and owns the block. Only if no grid is complete alone does the earliest contributing group win, credited
    to its majority supplier. A block complete in no one group is a gap; nothing is averaged across datums.

    With `ecs` (per grid None, or [provenance raster, optional shoal_hint raster]) every merged cell carries its EC code
    (measured without a raster), and an unresolved code takes its cell even where the value is not water: the code wins.
    Returns (depth_ft, owner, cls, reason, hint) then: cls the block's CLASS_INDEX (-1 none), reason the index in
    ec.UNRESOLVED_REASONS of an unresolved block's most frequent reason, hint its shallowest shoal hint (m, NaN elsewhere).
    An unresolved block has an owner but NaN depth.
    """
    _, _, width, height = lattice
    legacy, ecs = ecs is None, ecs or [None] * len(grids)
    groups = {}
    for i, key in enumerate(keys):
        groups.setdefault(key, []).append(i)
    depth = np.full((height, width), np.nan, dtype='float64')
    owner = np.full((height, width), -1, dtype='int8')
    cls, reason = np.full((height, width), -1, dtype='int8'), np.full((height, width), -1, dtype='int8')
    hint = np.full((height, width), np.nan)
    for by in range(0, height, STRIP_BLOCKS):
        rows = min(STRIP_BLOCKS, height - by)
        rank = np.full((rows, width), 2 * len(grids))
        for members in groups.values():
            n = offsets[members[0]][2]
            per_block = lambda a, how: how(a.reshape(rows, n, width, n), axis=(1, 3))  # noqa: E731
            merged = np.full((rows * n, width * n), np.nan, dtype='float64')
            source = np.full(merged.shape, -1, dtype='int8')
            code, shoal = np.zeros(merged.shape, dtype='uint8'), np.full(merged.shape, np.nan)
            complete = np.full((rows, width), len(grids))
            for i in members:
                col0, row0, _ = offsets[i]
                window = Window(col0, row0 + by * n, width * n, rows * n)
                values = grids[i].read(1, window=window, boundless=True, masked=True).filled(np.nan).astype('float64')
                water = np.isfinite(values) & (values < 0) & (values >= -3000)
                own_valid = water.reshape(rows, n, width, n).all(axis=(1, 3))
                complete[(complete == len(grids)) & own_valid] = i
                fill = water & (source < 0)
                codes = ecs[i] and ecs[i][0].read(1, window=window, boundless=True, fill_value=ec.CODES['nodata'])
                if ecs[i]:
                    fill |= np.isin(codes, UNRESOLVED_CODES) & (source < 0)
                    if not np.isin(codes[fill], list(ec.CODES.values())).all():
                        raise SystemExit(f'{grids[i].name}: provenance code not in seafloor_ec.CODES')
                    if len(ecs[i]) > 1:
                        shoal[fill] = ecs[i][1].read(1, window=window, boundless=True, fill_value=np.nan)[fill]
                merged[fill], source[fill] = values[fill], i
                code[fill] = codes[fill] if ecs[i] else ec.CODES['measured']
            blocks = merged.reshape(rows, n, width, n)
            valid = np.isfinite(blocks).all(axis=(1, 3))
            covered = per_block(source >= 0, np.all)  # without ecs every merged cell is water: covered == valid
            klass = CLASS_LUT[sum(per_block((code // 10 == k) & (source >= 0), np.any).astype('int64') << k for k in range(6))]
            counts = np.stack([(source == i).reshape(rows, n, width, n).sum(axis=(1, 3)) for i in members])
            first = np.array(members)[(counts > 0).argmax(axis=0)]
            # A complete individual grid outranks any group completed only by merging partial grids.
            priority = np.where(complete < len(grids), complete, len(grids) + first)
            take = covered & (priority < rank)
            good = take & valid & (klass != CLASS_INDEX['unresolved'])
            depth[by:by + rows][good] = (-blocks.sum(axis=(1, 3)) / (n * n) * dc.FEET_PER_M)[good]
            credited = np.array(members)[counts.argmax(axis=0)]
            if len(groups) > 1:
                credited = np.where(complete < len(grids), complete, credited)
            owner[by:by + rows][take] = credited[take]
            cls[by:by + rows][take] = klass[take]
            why = np.stack([per_block(np.isin(code, c) & (source >= 0), np.sum) for c in REASON_CODES]).argmax(axis=0)
            bad = take & (klass == CLASS_INDEX['unresolved'])
            reason[by:by + rows][bad] = why[bad]
            hint[by:by + rows][take] = np.fmax.reduce(shoal.reshape(rows, n, width, n).swapaxes(1, 2).reshape(rows, width, -1),
                                                      axis=2)[take]
            rank[take] = priority[take]
    return (depth, owner) if legacy else (depth, owner, cls, reason, hint)


def horizontal_crs(grid):
    """Use only the horizontal part for CRS comparisons and metre/projected gates."""
    if grid.crs is None:
        raise ValueError(f'{grid.name}: expected a projected, metre-based survey grid')
    crs = CRS.from_user_input(grid.crs.to_wkt())
    if crs.is_compound:
        crs = crs.sub_crs_list[0]
    # NOAA's legacy TOWGS84 WKT wraps the projected horizontal component
    # in a bound CRS. Grid units and coordinates belong to its source CRS.
    if crs.is_bound:
        crs = crs.source_crs
    return crs.to_2d()


def horizontal(grids):
    """The grids' one horizontal CRS label: today's str(crs), or the projected part of a compound (BAG) CRS."""
    found = []
    for g in grids:
        crs = horizontal_crs(g)
        found.append((crs, crs.to_string() if CRS(g.crs).is_compound else str(g.crs)))
    if any(h != found[0][0] for h, _ in found):
        raise ValueError('Every grid must share one projected CRS')
    return found[0][1]


def lattice_for(grids, clip):
    """The shared lattice (x0, y0, width, height) covering every grid inside `clip` (west, south, east, north, in the
    grids' CRS), its corner on the first grid's native cell edges."""
    bounds = [g.bounds for g in grids]
    west, south = max(min(b.left for b in bounds), clip[0]), max(min(b.bottom for b in bounds), clip[1])
    east, north = min(max(b.right for b in bounds), clip[2]), min(max(b.top for b in bounds), clip[3])
    # Phase: the first grid's own corner, stepped out in whole blocks (the other grids must share its cell edges).
    px, py = bounds[0].left, bounds[0].top
    x0 = px - np.ceil((px - west) / dc.CELL_M) * dc.CELL_M
    y0 = py + np.ceil((north - py) / dc.CELL_M) * dc.CELL_M
    width, height = int(np.ceil((east - x0) / dc.CELL_M)), int(np.ceil((y0 - south) / dc.CELL_M))
    if width < 1 or height < 1:
        raise SystemExit('The grids do not reach the region bounds')
    return float(x0), float(y0), width, height


def inside_blocks(transformer, lattice, bounds):
    """The blocks whose four corners lie inside the region's lon/lat bounds; only these are traced."""
    x0, y0, width, height = lattice
    xs, ys = np.meshgrid(x0 + np.arange(width + 1) * dc.CELL_M, y0 - np.arange(height + 1) * dc.CELL_M)
    lon, lat = transformer.transform(xs, ys)
    ok = (lon >= bounds[0]) & (lat >= bounds[1]) & (lon <= bounds[2]) & (lat <= bounds[3])
    return ok[:-1, :-1] & ok[:-1, 1:] & ok[1:, :-1] & ok[1:, 1:]


def bag_identity(ident, path, survey, reviewed):
    """A regular BAG's own survey date and declared vertical datum, read through the unchanged seafloor adapter
    (which refuses VR and wrong-survey files). The datum is copied as declared; nothing is converted."""
    from skippercast.seafloor.adapters import bag
    try:
        meta = bag.inspect_metadata(path, survey)
    except ValueError as err:
        raise SystemExit(f'{ident}: {err}')
    vertical, start = str(meta['vertical_wkt']), str(meta['survey_start'])
    if 'ellipsoid' in vertical.lower():
        raise SystemExit(f'{ident}: ellipsoid-referenced BAG; heights are not depths below a tidal datum')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', start[:10]):
        date = start[:10]
    elif re.fullmatch(r'\d{4}', start[:4]):
        date = start[:4]
    else:
        raise SystemExit(f'{ident}: BAG metadata gives no survey start date')
    # GDAL writes VERT_DATUM["unknown"] when a BAG declares none.
    named = re.search(r'VERT_DATUM\["([^"]*)"', vertical)
    datum = named.group(1) if named and named.group(1).strip().lower() not in ('', 'unknown') else dc.UNVERIFIED_DATUM
    return {'name': f'{reviewed["name"]} {survey}', 'survey_date': date, 'vertical_datum': datum, 'native_cell_m': None,
            'extra': {'survey_id': survey, 'vertical_datum_source': 'bag-metadata',
                      'bag_metadata_sha256': meta['metadata_sha256']}}


def open_grid(ident, path, survey):
    """Open a grid for reading: a GeoTIFF directly; a BAG (`survey` given) through the seafloor adapter."""
    if survey is None:
        return rasterio.open(path)
    from skippercast.seafloor.adapters import bag
    try:
        return bag.open_source(path, {'url': f'{survey}_original.bag'})
    except ValueError as err:
        raise SystemExit(f'{ident}: {err}')


def check_first_strip(ident, grid, lattice, offsets, datum, is_bag):
    """P4's check_grid on the grid's first strip window inside the lattice (native pixels), before any read."""
    col0, row0, n = offsets
    _, _, width, height = lattice
    by = max(0, -row0 // (STRIP_BLOCKS * n)) * STRIP_BLOCKS
    col, row = max(col0, 0), max(row0 + by * n, 0)
    window = [col, row, min(col0 + width * n, grid.width) - col,
              min(row0 + (by + min(STRIP_BLOCKS, height - by)) * n, grid.height) - row]
    # A BAG's one band read here is elevation; the adapter has already checked its two-band layout.
    crs = horizontal_crs(grid)
    meta = {'driver': grid.driver, 'count': 1 if is_bag else grid.count, 'crs_wkt': crs.to_wkt(),
            'crs_projected': crs.is_projected,
            'crs_linear_units': crs.axis_info[0].unit_name if crs.axis_info else '',
            'transform': list(grid.transform)[:6], 'width': grid.width, 'height': grid.height,
            'band_unit': (grid.units[0] if grid.units else None) or ''}
    try:
        preflight.check_grid(meta, window=window, vertical_datum=datum, vertical_unit='metre', vertical_sign='elevation-up')
    except preflight.Refused as err:
        raise SystemExit(f'{ident}: preflight refused: {err}')


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


def ec_paths(path):
    """A provenance raster and, when one sits beside it, its shoal_hint.tif."""
    hint = Path(path).with_name('shoal_hint.tif')
    return [Path(path)] + ([hint] if hint.is_file() else [])


def check_provenance(ident, grid, path):
    """The EC_VERSION of a grid's provenance raster, refused unless it (and any shoal hint) is on the grid's own lattice."""
    tags = []
    for p in ec_paths(path):
        with rasterio.open(p) as ds:
            if (ds.crs, ds.transform, ds.width, ds.height, ds.count) != (grid.crs, grid.transform, grid.width, grid.height, 1) \
                    or ds.dtypes[0] != ('uint8' if p == Path(path) else 'float32'):
                raise SystemExit(f'{ident}: provenance grid does not match the survey grid')
            tags.append(ds.tags().get('EC_VERSION'))
    if not tags[0]:
        raise SystemExit(f'{ident}: provenance grid has no EC_VERSION tag')
    return tags[0]


def class_runs(line, square):
    """A traced line (block units) cut into maximal runs by the class of the square each segment was traced in; runs
    share their cut point, so together they are the line."""
    out = []
    for a, b in zip(line, line[1:]):
        r, c = (min(int((a[k] + b[k]) / 2), square.shape[1 - k] - 1) for k in (1, 0))
        if out and out[-1][0] == square[r, c]:
            out[-1][1].append(b)
        else:
            out.append((square[r, c], [a, b]))
    return out


def geometry_points(geometry):
    rings = geometry['coordinates'] if geometry['type'] == 'MultiLineString' else [r for p in geometry['coordinates'] for r in p]
    return [pt for ring in rings for pt in ring]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--region', required=True)
    p.add_argument('--grid', action='append', required=True, metavar='SOURCE_ID=PATH')
    p.add_argument('--bag-survey', action='append', default=[], metavar='SOURCE_ID=SURVEY_ID',
                   help='The survey id of the one BAG file given for an adapter: bag source (required for each).')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--output', metavar='PATH', help='Write the approved-only collection to this file outside the work tree '
                       'instead of catalog/depth-contours/<id>.geojson. Cannot be combined with --held-output.')
    group.add_argument('--held-output', metavar='PATH', help='Trace candidate grids too, into this private file outside the '
                       'work tree, stamped publication_held (the platform build refuses it). Nothing is written to catalog/.')
    p.add_argument('--provenance', action='append', default=[], metavar='SOURCE_ID=PATH',
                   help='The EC provenance raster (uint8, EC_VERSION tag, same lattice) of a --grid GeoTIFF; a shoal_hint.tif '
                   'beside it is read too. Its blocks then carry their class (docs/seafloor-ec.md).')
    args = p.parse_args()
    held = args.held_output and Path(args.held_output).expanduser().resolve()
    output = args.output and Path(args.output).expanduser().resolve()
    repo = Path(REPO).resolve()
    if held and (held == repo or repo in held.parents):
        raise SystemExit(f'Held output must be outside the work tree: {held}')
    if output and (output == repo or repo in output.parents):
        raise SystemExit(f'Output must be outside the work tree: {output}')
    region = load_region(args.region)
    _, sources = load_catalogs()
    bound = region['source_bindings']['bathymetry']
    grids, surveys, provs = {}, {}, {}
    for pairs, items in ((grids, args.grid), (surveys, args.bag_survey), (provs, args.provenance)):
        for ident, value in (item.split('=', 1) for item in items):
            if ident in pairs:
                raise SystemExit(f'{ident} given twice; one file per source per build')
            pairs[ident] = value
    for ident in sorted(set(provs) - set(grids)):
        raise SystemExit(f'{ident}: --provenance is only for a source given with --grid')
    order = [ident for ident in bound if ident in grids]
    if set(grids) - set(order):
        raise SystemExit(f'Not bathymetry bindings of {region["id"]}: {sorted(set(grids) - set(order))}')
    # Every grid's approval is checked before any grid is opened or hashed.
    for ident in order:
        status, licence = sources[ident]['review_status'], (sources[ident].get('rights') or {}).get('license')
        if held and (status not in ('approved', 'candidate') or licence in (None, '', 'unresolved', 'dataset-review-needed')
                     or 'bathymetry' not in sources[ident]['needs']):
            raise SystemExit(f'{ident} cannot be traced, even held: {status}, licence {licence}')
        if not held and (status != 'approved' or 'bathymetry' not in sources[ident]['needs']):
            raise SystemExit(f'{ident} is not an approved bathymetry source')
    adapters = {ident: sources[ident].get('adapter', 'geotiff') for ident in order}
    kinds = set(adapters.values())
    for ident in order:
        if adapters[ident] not in ('geotiff', 'bag'):
            raise SystemExit(f'{ident}: adapter {adapters[ident]} is not a grid this builder reads')
        if adapters[ident] == 'bag' and ident not in surveys:
            raise SystemExit(f'{ident}: a bag source needs --bag-survey {ident}=SURVEY_ID')
        if adapters[ident] == 'bag' and ident in provs:
            raise SystemExit(f'{ident}: --provenance is for a GeoTIFF grid, not a bag source')
    for ident in sorted(set(surveys) - {i for i in order if adapters[i] == 'bag'}):
        raise SystemExit(f'{ident}: --bag-survey is only for a bag source given with --grid')
    # Each grid's identity: the reviewed catalog entry for a GeoTIFF; for a BAG its own metadata, never converted.
    identity = {}
    for ident in order:
        if adapters[ident] == 'bag':
            identity[ident] = bag_identity(ident, grids[ident], surveys[ident], sources[ident])
            continue
        native = sources[ident].get('native_resolution_m')
        with rasterio.open(grids[ident]) as grid:
            res = grid.res
            ec_version = check_provenance(ident, grid, provs[ident]) if ident in provs else None
        # The provenance labels each grid with the reviewed native cell; a resample must not carry that label.
        if not isinstance(native, (int, float)) or any(abs(r - native) > 1e-9 for r in res):
            raise SystemExit(f'{ident}: grid cell {res} differs from reviewed native_resolution_m {native}')
        identity[ident] = {'name': sources[ident]['name'], 'survey_date': str(sources[ident]['survey_year']),
                           'vertical_datum': sources[ident].get('vertical_datum') or dc.UNVERIFIED_DATUM,
                           'native_cell_m': native, 'extra': {'ec_version': ec_version} if ec_version else {}}
    hashes = {ident: sha256(grids[ident]) for ident in order}
    if len(set(hashes.values())) != len(hashes):
        raise SystemExit('Two --grid sources are the same file; each binding needs its own survey grid')
    with ExitStack() as stack:
        opened = [stack.enter_context(open_grid(ident, grids[ident], surveys.get(ident))) for ident in order]
        crs = horizontal(opened)
        # Reads are clipped to the region (plus one block): a coast-wide BAG is never read whole.
        west, south, east, north = transform_bounds('EPSG:4326', crs, *region['bounds'], densify_pts=21)
        lattice = lattice_for(opened, (west - dc.CELL_M, south - dc.CELL_M, east + dc.CELL_M, north + dc.CELL_M))
        offsets = [native_offsets(g, lattice) for g in opened]
        for ident, grid, offset in zip(order, opened, offsets):
            if adapters[ident] == 'bag':
                identity[ident]['native_cell_m'] = grid.res[0]
            check_first_strip(ident, grid, lattice, offset, identity[ident]['vertical_datum'], adapters[ident] == 'bag')
        keys = [(n, identity[ident]['vertical_datum']) for ident, (_, _, n) in zip(order, offsets)]
        ecs = [[stack.enter_context(rasterio.open(q)) for q in ec_paths(provs[ident])] if ident in provs else None
               for ident in order]
        depth, owner, cls, reason, hint = merged_blocks(opened, lattice, offsets, keys, ecs)
    x0, y0, _, _ = lattice
    block = Affine(dc.CELL_M, 0, x0, 0, -dc.CELL_M, y0)
    transformer = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
    # Blocks outside the region are not traced but stay in the union, so no survey edge is drawn along the clip.
    inside = inside_blocks(transformer, lattice, region['bounds'])
    # Unresolved blocks are left out of the union: survey edges run round them as round a gap (they are drawn as areas).
    unresolved = cls == CLASS_INDEX['unresolved']
    union = polygons((owner >= 0) & ~unresolved, block)
    # A square's class: block_class of its four corner blocks' classes (as bits 1 << (index + 1), the codes' tens digits).
    bit = np.where((cls >= 0) & ~unresolved, np.left_shift(2, cls.clip(0).astype('int64')), 0)
    square = np.array([*CLASS_INDEX, 'none'])[CLASS_LUT[bit[:-1, :-1] | bit[:-1, 1:] | bit[1:, :-1] | bit[1:, 1:]]]
    features, listed = [], []
    for i, ident in enumerate(order):
        reviewed, known = sources[ident], identity[ident]
        mine = (owner == i) & inside & ~unresolved
        survey_date = known['survey_date']
        entry = {'source_id': ident, 'name': known['name'], 'url': reviewed['documentation_url'],
                 'attribution': reviewed['rights']['attribution'], 'sha256': hashes[ident], 'survey_date': survey_date,
                 'vertical_datum': known['vertical_datum'], 'native_cell_m': known['native_cell_m'],
                 'supported_blocks': int(mine.sum()), **known['extra']}
        if ident in provs:
            entry['provenance_counts'] = {name: int(((owner == i) & inside & (cls == k)).sum()) for name, k in CLASS_INDEX.items()}
        listed.append(entry)
        if not mine.any():
            continue
        common = {'source_id': ident, 'survey_date': survey_date, 'vertical_datum': entry['vertical_datum']}
        own = np.where(mine, depth, np.nan)
        rows = [[None if not np.isfinite(v) else float(v) for v in row] for row in own]
        for d, lines in dc.trace(rows, dc.levels(float(np.nanmin(own)), float(np.nanmax(own)))).items():
            runs = {}
            for line in lines:
                for name, part in (class_runs(line, square) if provs else [('measured', line)]):
                    metres = [(x0 + (c + 0.5) * dc.CELL_M, y0 - (r + 0.5) * dc.CELL_M) for c, r in part]
                    ll = dedupe(to_lonlat(transformer, dc.simplify(metres, CONTOUR_TOLERANCE_M, (1.0, 1.0))))
                    if len(ll) >= 2:
                        runs.setdefault(str(name), []).append(ll)
            # One feature per class; a measured run keeps today's id, so an input without provenance keeps today's bytes.
            for name in (n for n in ec.PROVENANCE_CLASSES if runs.get(n)):
                features.append({'type': 'Feature', 'id': f'{ident}-{d}ft' + ('' if name == 'measured' else f'-{name}'),
                                 'geometry': {'type': 'MultiLineString', 'coordinates': runs[name]},
                                 'properties': {'kind': 'contour', 'depth_ft': d, 'index': d % dc.INDEX_FT == 0, **common,
                                                **({'provenance': name} if provs else {})}})
        # Where the contours stop: the outline of all the surveys' supported blocks together, each part credited to the
        # survey whose blocks it bounds. A seam between two surveys is not an edge: a reviewed grid continues there.
        edge = line_merge(polygons(mine, block).boundary.intersection(union.boundary))
        pieces = [g for g in getattr(edge, 'geoms', [edge]) if g.geom_type == 'LineString' and g.length >= EDGE_MIN_LENGTH_M]
        lines = sorted(ll for ll in (dedupe(to_lonlat(transformer, list(g.simplify(EDGE_TOLERANCE_M).coords))) for g in pieces) if len(ll) >= 2)
        if lines:
            features.append({'type': 'Feature', 'id': f'{ident}-edge', 'geometry': {'type': 'MultiLineString', 'coordinates': lines},
                             'properties': {'kind': 'survey-edge', **common}})
        # Unresolved blocks are areas, never contours: one MultiPolygon per reason, a conflict with its shallowest hint.
        for k, why in enumerate(ec.UNRESOLVED_REASONS):
            here = (owner == i) & inside & unresolved & (reason == k)
            if not here.any():
                continue
            area = polygons(here, block)
            props = {'kind': ec.UNRESOLVED_KIND, 'reason': why, 'blocks': int(here.sum())}
            if why == 'conflict' and np.isfinite(hint[here]).any():
                props[ec.SHOAL_HINT_KEY] = round(-float(np.nanmax(hint[here])) * dc.FEET_PER_M)
            features.append({'type': 'Feature', 'id': f'{ident}-unresolved-{why}', 'geometry': {'type': 'MultiPolygon', 'coordinates': [
                [dedupe(to_lonlat(transformer, list(ring.coords))) for ring in (g.exterior, *g.interiors)]
                for g in getattr(area, 'geoms', [area])]}, 'properties': {**props, **common}})
    empty = [entry['source_id'] for entry in listed if not entry['supported_blocks']]
    if empty:
        # A supplied grid that adds nothing (wrong sign, no water, fully overlapped) would look like full coverage.
        raise SystemExit(f'Supplied grids contribute no valid water block: {empty}')
    xs = [pt[0] for f in features for pt in geometry_points(f['geometry'])]
    ys = [pt[1] for f in features for pt in geometry_points(f['geometry'])]
    collection = {'type': 'FeatureCollection', 'schema_version': dc.SCHEMA_VERSION, 'provenance': {
        'region_id': region['id'], 'units': 'ft', 'interval_ft': dc.INTERVAL_FT, 'index_ft': dc.INDEX_FT,
        'shelf_limit_ft': dc.SHELF_LIMIT_FT, 'cell_m': dc.CELL_M, 'horizontal_crs': crs,
        'bounds': [min(xs), min(ys), max(xs), max(ys)], 'features': len(features), 'sources': listed,
        # The region's bound surveys not drawn here, with their catalog review_status (checked by dc.check_contours).
        'sources_omitted': dc.omitted_sources(region, sources, order),
        # Held mode (--held-output): private, never published; names the traced sources that are not approved.
        **({'publication_held': True, 'held_sources': [{'source_id': i, 'review_status': sources[i]['review_status']}
                                                       for i in order if sources[i]['review_status'] != 'approved']}
           if held else {}),
        'coordinate_decimals': dc.DECIMALS, 'simplify_tolerance_m': CONTOUR_TOLERANCE_M,
        'edge': {'tolerance_m': EDGE_TOLERANCE_M, 'min_length_m': EDGE_MIN_LENGTH_M,
                 'note': 'The outline of all the surveys\' supported blocks together; seams between surveys are not edges.'},
        'datum_note': 'Depths are below each survey\'s own vertical datum.' + (USGS_DATUM if 'geotiff' in kinds else '')
                      + (BAG_DATUM if 'bag' in kinds else '') + ' Not converted or certified.',
        'method': f'Native cells are merged in the region\'s binding order (the first survey with valid water wins each cell); '
                  f'each {dc.CELL_M} m block is their mean and counts only when all of them are valid water. Marching squares '
                  f'at every {dc.INTERVAL_FT} ft to {dc.SHELF_LIMIT_FT} ft draws only between four valid blocks of one survey '
                  '(the survey supplying most of each block), so lines stop where the reviewed grid stops.' + (EC_METHOD if provs else ''),
        'limitations': 'Not for navigation. Historical survey; the bottom can have changed. Display contours from averaged blocks, '
                       'not soundings or chart depths.'},
        'features': features}
    (dc.check_held_contours if held else dc.check_contours)(collection, region, sources)
    receipt = atomic_json(held or output or REPO / 'catalog/depth-contours' / f'{region["id"]}.geojson', collection)
    print({'features': len(features), **receipt, **({'held': True} if held else {}), 'sources': [(s['source_id'], s['sha256'][:12], s['supported_blocks']) for s in listed]})


if __name__ == '__main__':
    main()
