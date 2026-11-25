"""Trace a region's shelf depth contours from its reviewed survey grids (CI6-13).

Run on the processing host, with the survey stack (requirements-survey.txt):

    PYTHONPATH=src python scripts/build_depth_contours.py --region morro-bay \\
        --grid usgs-point-buchon=/path/Bathymetry_OffshorePointBuchon.tif \\
        --grid usgs-morro-bay=/path/Bathymetry_OffshoreMorroBay.tif \\
        --grid usgs-point-estero=/path/Bathymetry_OffshorePointEstero.tif

Each grid must be an original producer GeoTIFF or a hash-bound normalised
GeoTIFF of an approved bathymetry source bound to the region
(catalog/sources.json, regions/<id>/region.json). For a normalised grid give
--normalized-sidecar SOURCE_ID=PATH; provenance retains the original digest. With
--set v2 its native detail also needs --normalized-support SOURCE_ID=PATH (the grid's
support.tif): only cells it marks measured are traced at native detail. The sidecar must
pin that file as outputs["support.tif"]; a missing pin or a different file is refused.
For an original `adapter: bag` source, supply one regular NOAA BAG named with its survey:
`--grid noaa-bag=/path/H12345_MB_2m.bag --bag-survey noaa-bag=H12345`.
Its SHA-256 is recorded in the output's provenance; local paths never reach
the output. The output is catalog/depth-contours/<id>.geojson (or --output PATH, outside the
work tree, for the same approved-only collection); then rebuild the
platform (PYTHONPATH=src python -m skippercast.platform.build), which checks it
and publishes dist/regions/<id>/depth-contours*.geojson. The method is
described in src/skippercast/platform/depth_contours.py.

--set v2 opts into zoom-tagged feet contours (300 ft shelf); v1 is the
unchanged default. --set v3 uses the region's kit tiers on native measured
support and requires --output or --held-output outside the work tree.
"""
import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

import numpy as np
import rasterio
from rasterio import features as rio_features
from rasterio.transform import Affine
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds
from pyproj import CRS, Transformer
from shapely import line_merge, unary_union
from shapely.geometry import LineString, shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from skippercast.platform.contracts import REPO, atomic_json, load_catalogs, load_region  # noqa: E402
from skippercast.platform.contracts import owner_display_cleared  # noqa: E402
from skippercast.platform import depth_contours as dc  # noqa: E402
from skippercast.platform import seafloor_ec as ec  # noqa: E402

# EC5: a block's class index (-1 none) and, by the bitmask of the code classes (tens digits) in it, seafloor_ec.block_class.
CLASS_INDEX = {'measured': 0, 'filled': 1, 'verified': 2, 'unresolved': 3}
CLASS_LUT = np.array([CLASS_INDEX[ec.block_class([10 * k for k in range(6) if m >> k & 1])] if m else -1 for m in range(64)],
                     dtype='int8')
UNRESOLVED_CODES = [c for c in ec.CODES.values() if ec.CLASS_OF(c) == 'unresolved']
# Native no-data and masked-sentinel cells; PAD fills a boundless read outside the raster (EC's own nodata, never a code).
NODATA_CODES, PAD = [ec.CODES['nodata'], ec.CODES['masked-sentinel']], 255
REASON_CODES = [[ec.CODES[f'unresolved-{r}']] if r != 'nodata' else NODATA_CODES for r in ec.UNRESOLVED_REASONS]
EC_METHOD = (' Blocks carry the error-correction class of their native cells (measured, filled, verified) when a provenance '
             'grid was supplied; unresolved blocks are drawn as areas, never as contours.')

STRIP_BLOCKS = 64
# Survey-edge display: outline simplification, and the shortest piece kept (a smaller gap still stops the lines).
EDGE_TOLERANCE_M = 12
EDGE_MIN_LENGTH_M = 200
CONTOUR_TOLERANCE_M = 3
V2_COARSE_TOLERANCE_M = 6
V2_DECIMALS = 6
NORMALIZED_DATUMS = {'MLLW', 'NAVD88', 'MSL', 'EGM2008', 'unstated', 'instantaneous_sea_level'}
# P4's preflight (check_grid / Refused), loaded from beside this script: it imports nothing from seafloor/.
_spec = importlib.util.spec_from_file_location('preflight_native_grid', Path(__file__).with_name('preflight_native_grid.py'))
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)
USGS_DATUM = ' The original GeoTIFFs declare none; the companion USGS report (Open-File Report 2023-1064) names MLLW.'
BAG_DATUM = ' BAG surveys: the datum each BAG\'s metadata declares, copied as declared.'


def sha256(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def public_refusal(ident, region, sources, *, explicit=True, selected=False):
    source = sources.get(ident) or {}
    rights = source.get('rights') or {}
    display = rights.get('public_display')
    if ((explicit or selected) and display != 'allowed') or display in ('private', 'excluded'):
        return 'not cleared for public display'
    owner_cleared = selected and owner_display_cleared(rights)
    if not owner_cleared and source.get('publication_allowed') is False:
        return 'publication_allowed is false'
    if (not owner_cleared and source.get('review_status') != 'approved') or 'bathymetry' not in source.get('needs', ()):
        return 'not an approved bathymetry source'
    if not selected and ident not in region['source_bindings']['bathymetry']:
        return 'not a static region bathymetry binding'
    return None


def normalized_identity(ident, grid, path, reviewed_datum):
    """Read only the R2 receipt fields needed to bind this derivative to its original."""
    try:
        side = json.loads(Path(path).read_text(encoding='utf-8'))
        original = side['original_sha256']
        digest = side['outputs']['grid.tif']
        datum = side['vertical_datum']
        if (side['schema'] != 'sc-relief-normalized/1' or side['units'] != 'm'
                or side['value_convention'] != 'elevation_positive_up'
                or datum not in NORMALIZED_DATUMS
                or not dc.SHA256.fullmatch(original) or not dc.SHA256.fullmatch(digest)):
            raise ValueError('expected a hash-bound normalised metre elevation grid')
        if (grid.driver != 'GTiff' or grid.count != 1 or grid.scales[0] != 1 or grid.offsets[0] != 0
                or grid.crs != rasterio.crs.CRS.from_user_input(side['crs'])
                or list(grid.shape) != side['shape'] or list(grid.transform)[:6] != side['transform']
                or any(abs(cell - side['resolution_m']) > 1e-9 for cell in grid.res)):
            raise ValueError('normalised sidecar geometry mismatch')
        if sha256(grid.name) != digest:
            raise ValueError('normalised grid hash mismatch')
        if datum != 'unstated' and reviewed_datum not in (None, dc.UNVERIFIED_DATUM, datum):
            raise ValueError('normalised datum differs from the reviewed original')
        return original, digest, datum if datum != 'unstated' else reviewed_datum
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise SystemExit(f'{ident}: invalid normalised sidecar: {exc}') from None


def verify_support_binding(ident, sidecar_path, support_path):
    """Refuse a support raster the normalised receipt does not pin: only the receipt's own support.tif may grant native detail."""
    try:
        pin = json.loads(Path(sidecar_path).read_text(encoding='utf-8'))['outputs'].get('support.tif')
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        pin = None
    if not isinstance(pin, str) or not dc.SHA256.fullmatch(pin):
        raise SystemExit(f'{ident}: the normalised sidecar does not pin outputs[\"support.tif\"], so no support raster can be trusted')
    if sha256(Path(support_path).expanduser()) != pin:
        raise SystemExit(f'{ident}: --normalized-support differs from the support.tif the normalised sidecar pins')


@contextmanager
def open_geotiff(path, *, normalized):
    if not normalized:
        with rasterio.open(path) as grid:
            yield grid
    else:
        # Keep the fence active through boundless reads, which can reopen the TIFF.
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_PAM_ENABLED='NO'), \
                rasterio.open(path, driver='GTiff', sharing=False) as grid:
            yield grid


def native_offsets(grid, lattice, block_m=dc.CELL_M):
    """The grid's native column and row at the lattice's top-left corner, and cells per block; refuses misaligned grids."""
    x0, y0, _, _ = lattice
    crs = horizontal_crs(grid)
    if not crs.is_projected or any(axis.unit_name != 'metre' for axis in crs.axis_info[:2]):
        raise ValueError(f'{grid.name}: expected a projected, metre-based survey grid')
    cell = grid.res[0]
    if abs(grid.res[0] - grid.res[1]) > 1e-9 or (block_m / cell) % 1:
        raise ValueError(f'{grid.name}: square cells dividing {block_m} m are required, got {grid.res}')
    col0, row0 = (x0 - grid.transform.c) / cell, (grid.transform.f - y0) / cell
    if abs(col0 - round(col0)) > 1e-6 or abs(row0 - round(row0)) > 1e-6:
        raise ValueError(f'{grid.name}: native cells do not align with the {block_m} m lattice')
    return round(col0), round(row0), int(block_m / cell)


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
    prefer_complete = len(groups) > 1
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
            complete, named = np.full((rows, width), len(grids)), []
            for i in members:
                col0, row0, _ = offsets[i]
                window = Window(col0, row0 + by * n, width * n, rows * n)
                values = grids[i].read(1, window=window, boundless=True, masked=True).filled(np.nan).astype('float64')
                water = np.isfinite(values) & (values < 0) & (values >= -3000)
                own_valid = water.reshape(rows, n, width, n).all(axis=(1, 3))
                first_complete = (complete == len(grids)) & own_valid
                complete[first_complete] = i
                replace_partial = prefer_complete and first_complete.any()
                fill = water & (source < 0)
                codes = ecs[i] and ecs[i][0].read(1, window=window, boundless=True, fill_value=PAD)
                if ecs[i]:
                    named.append((i, codes))
                    fill |= np.isin(codes, UNRESOLVED_CODES) & (source < 0)
                # Across groups a complete grid wins as a unit: replace any earlier partial cells and their EC data.
                if replace_partial:
                    fill.reshape(rows, n, width, n)[:] |= first_complete[:, None, :, None]
                if ecs[i] and not np.isin(codes[fill], list(ec.CODES.values())).all():
                    raise SystemExit(f'{grids[i].name}: provenance code not in seafloor_ec.CODES')
                if ecs[i] and len(ecs[i]) > 1:
                    shoal[fill] = ecs[i][1].read(1, window=window, boundless=True, fill_value=np.nan)[fill]
                elif replace_partial:
                    shoal[fill] = np.nan
                merged[fill], source[fill] = values[fill], i
                code[fill] = codes[fill] if ecs[i] else ec.CODES['measured']
            # A no-data or masked cell its own grid names (never padding) takes what no grid gave water: in a block with
            # other evidence it marks the block unresolved, not a gap; a block with nothing else stays a gap.
            real = per_block(source >= 0, np.any)
            for i, codes in named:
                fill = np.isin(codes, NODATA_CODES) & (source < 0)
                source[fill], code[fill] = i, codes[fill]
            blocks = merged.reshape(rows, n, width, n)
            valid = np.isfinite(blocks).all(axis=(1, 3))
            covered = per_block(source >= 0, np.all) & real  # without ecs every merged cell is water: covered == valid
            klass = CLASS_LUT[sum(per_block((code // 10 == k) & (source >= 0), np.any).astype('int64') << k for k in range(6))]
            counts = np.stack([(source == i).reshape(rows, n, width, n).sum(axis=(1, 3)) for i in members])
            first = np.array(members)[(counts > 0).argmax(axis=0)]
            # A complete individual grid outranks any group completed only by merging partial grids.
            priority = np.where(complete < len(grids), complete, len(grids) + first)
            take = covered & (priority < rank)
            unresolved = klass == CLASS_INDEX['unresolved']
            # A better-ranked group replaces the entire result, including absent depth or reason.
            depth[by:by + rows][take] = np.where(valid & ~unresolved,
                                                -blocks.sum(axis=(1, 3)) / (n * n) * dc.FEET_PER_M, np.nan)[take]
            credited = np.array(members)[counts.argmax(axis=0)]
            owner[by:by + rows][take] = credited[take]
            cls[by:by + rows][take] = klass[take]
            why = np.stack([per_block(np.isin(code, c) & (source >= 0), np.sum) for c in REASON_CODES]).argmax(axis=0)
            reason[by:by + rows][take] = np.where(unresolved, why, -1)[take]
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


def lattice_for(grids, clip, block_m=dc.CELL_M):
    """The shared lattice (x0, y0, width, height) covering every grid inside `clip` (west, south, east, north, in the
    grids' CRS), its corner on the first grid's native cell edges."""
    bounds = [g.bounds for g in grids]
    west, south = max(min(b.left for b in bounds), clip[0]), max(min(b.bottom for b in bounds), clip[1])
    east, north = min(max(b.right for b in bounds), clip[2]), min(max(b.top for b in bounds), clip[3])
    # Phase: the first grid's own corner, stepped out in whole blocks (the other grids must share its cell edges).
    px, py = bounds[0].left, bounds[0].top
    x0 = px - np.ceil((px - west) / block_m) * block_m
    y0 = py + np.ceil((north - py) / block_m) * block_m
    width, height = int(np.ceil((east - x0) / block_m)), int(np.ceil((y0 - south) / block_m))
    if width < 1 or height < 1:
        raise SystemExit('The grids do not reach the region bounds')
    return float(x0), float(y0), width, height


def inside_blocks(transformer, lattice, bounds, block_m=dc.CELL_M):
    """The blocks whose four corners lie inside the region's lon/lat bounds; only these are traced."""
    x0, y0, width, height = lattice
    xs, ys = np.meshgrid(x0 + np.arange(width + 1) * block_m, y0 - np.arange(height + 1) * block_m)
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


def to_lonlat(transformer, points, decimals=dc.DECIMALS):
    xs, ys = transformer.transform([p[0] for p in points], [p[1] for p in points])
    return [[round(x, decimals), round(y, decimals)] for x, y in zip(xs, ys)]


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
    """The EC_VERSION of a grid's provenance raster, refused unless it (and any shoal hint) is a GeoTIFF on the grid's own
    lattice. Only the header is opened: no pixel is read and nothing is hashed before this passes."""
    tags = []
    for p in ec_paths(path):
        with rasterio.open(p) as ds:
            if ds.driver != 'GTiff':
                raise SystemExit(f'{ident}: provenance grid must be a GeoTIFF, got {ds.driver}')
            if (ds.crs, ds.transform, ds.width, ds.height, ds.count) != (grid.crs, grid.transform, grid.width, grid.height, 1) \
                    or ds.dtypes[0] != ('uint8' if p == Path(path) else 'float32'):
                raise SystemExit(f'{ident}: provenance grid does not match the survey grid')
            tags.append(ds.tags().get('EC_VERSION'))
    if not tags[0]:
        raise SystemExit(f'{ident}: provenance grid has no EC_VERSION tag')
    return tags[0]


def class_runs(line, cells, square):
    """A traced line (block units) cut into maximal runs by the class of the square that traced each segment (`cells`
    from dc.trace(..., squares=True), so a segment on an edge two squares share keeps its own); runs share their cut
    point, so together they are the line."""
    out = []
    for a, b, (r, c) in zip(line, line[1:], cells):
        if out and out[-1][0] == square[r, c]:
            out[-1][1].append(b)
        else:
            out.append((square[r, c], [a, b]))
    return out


def geometry_points(geometry):
    rings = geometry['coordinates'] if geometry['type'] == 'MultiLineString' else [r for p in geometry['coordinates'] for r in p]
    return [pt for ring in rings for pt in ring]


UNKNOWN_SUPPORT = 2
MEASURED_SUPPORT = 3  # support raster class for a measured (not interpolated/unknown) native cell


def v2_native(grid, offset, mine, provenance, support=None):
    """Native depth and the footprint of traceable squares. Never resample or use known EC fills.

    `support` is an open uint8 support raster aligned cell for cell with `grid`; only cells it marks
    measured (class 3, not masked) can carry native detail."""
    col, row, n = offset
    rows, = np.nonzero(mine.any(axis=1))
    cols, = np.nonzero(mine.any(axis=0))
    x, y = max(0, col + int(cols[0]) * n), max(0, row + int(rows[0]) * n)
    w = min(grid.width, col + (int(cols[-1]) + 1) * n) - x
    h = min(grid.height, row + (int(rows[-1]) + 1) * n) - y
    if w <= 0 or h <= 0:
        return None
    if w * h > preflight.MAX_PIXELS:
        raise SystemExit(f'{grid.name}: v2 native window exceeds {preflight.MAX_PIXELS} pixels; use a smaller region window')
    window = Window(x, y, w, h)
    values = grid.read(1, window=window, masked=True).astype('float64').filled(np.nan)
    valid = np.isfinite(values) & (values < 0) & (values >= -3000)
    valid &= mine[((y - row) + np.arange(h))[:, None] // n, ((x - col) + np.arange(w))[None, :] // n]
    if provenance:
        codes = provenance[0].read(1, window=window, masked=True)
        valid &= codes.filled(PAD) == ec.CODES['measured']
    if support is not None:
        if (support.count != 1 or support.dtypes[0] != 'uint8' or support.shape != grid.shape
                or support.crs != grid.crs or support.transform != grid.transform):
            raise SystemExit(f'{grid.name}: support raster must be single-band uint8 aligned with the native grid')
        valid &= (support.read(1, window=window) == MEASURED_SUPPORT) & (support.read_masks(1, window=window) != 0)
    transform = grid.window_transform(window)
    squares = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & valid[1:, 1:]
    footprint = polygons(squares, transform @ Affine.translation(0.5, 0.5)) if squares.any() else None
    return np.where(valid, -values * dc.FEET_PER_M, np.nan), transform, footprint


def v2_smooth(depth):
    """Smooth the 10 m surface (sigma 1.2 cells) without reaching across missing cells or source boundaries."""
    from scipy.ndimage import gaussian_filter, minimum_filter

    valid = np.isfinite(depth)
    interior = minimum_filter(valid, size=11, mode='constant', cval=False)  # full Gaussian kernel
    return np.where(interior, gaussian_filter(np.where(valid, depth, 0), sigma=1.2, radius=5), depth)


def line_parts(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type == 'LineString':
        yield geometry
    else:
        for part in getattr(geometry, 'geoms', ()):
            yield from line_parts(part)


def _v3_shoal_safe(original, short, unknown, depth, level, tf, lonlat):
    """Keep a shortcut only if it cannot move a raw unknown-support shoal across the line."""
    from shapely import intersects_xy, transform
    from shapely.ops import polygonize

    x0, y0, x1, y1 = original.bounds
    sx0, sy0, sx1, sy1 = short.bounds
    # Restrict centre indices to the joint projected bounds plus one cell.
    centres = tf @ Affine.translation(0.5, 0.5)
    to_index = ~centres
    cell = tf.a
    left, top = to_index @ (min(x0, sx0) - cell, max(y1, sy1) + cell)
    right, bottom = to_index @ (max(x1, sx1) + cell, min(y0, sy0) - cell)
    col0, row0 = max(0, int(np.ceil(left))), max(0, int(np.ceil(top)))
    cols = slice(col0, int(np.floor(right)) + 1)
    rows = slice(row0, int(np.floor(bottom)) + 1)
    rr, cc = np.nonzero(unknown[rows, cols] & (depth[rows, cols] < level))
    orig_ll = transform(original, lonlat.transform, interleaved=False)
    short_ll = transform(short, lonlat.transform, interleaved=False)
    # The caller pairs parts before simplifying, including parts cut at a
    # block seam. They must keep their endpoints (including a ring's start).
    if (short_ll.geom_type != 'LineString' or short_ll.is_empty
            or (orig_ll.coords[0], orig_ll.coords[-1]) != (short_ll.coords[0], short_ll.coords[-1])):
        return original
    if not rr.size:
        return short

    x, y = lonlat.transform(*(centres @ (cc + col0, rr + row0)))
    # Compare before the lon/lat clip: clipping can open the faces between
    # the two lines and make a shoal on the inside of the clip undetectable.
    if intersects_xy(short_ll, x, y).any() or any(
            intersects_xy(face, x, y).any() for face in polygonize(unary_union([orig_ll, short_ll]))):
        return original
    return short


def _v3_block_lines(grid, window, levels_by_tier, pier_index, cell, *, support, provenance, positive_down,
                    core, lonlat):
    """Trace a bounded read, returning projected lines owned by its core."""
    from scipy.ndimage import gaussian_filter, minimum_filter
    from shapely.geometry import box

    tf = grid.window_transform(window)
    values = grid.read(1, window=window, masked=True).astype('float64').filled(np.nan)
    if positive_down:
        values = -values
    water = np.isfinite(values) & (values < 0) & (values >= -3000)
    if provenance is not None:
        water &= provenance.read(1, window=window, masked=True).filled(PAD) == ec.CODES['measured']
    measured = usable = water
    unknown = None
    if support is not None:
        classes = support.read(1, window=window, masked=True).filled(0)
        measured = water & (classes == MEASURED_SUPPORT)
        unknown = water & (classes == UNKNOWN_SUPPORT)
        if unknown.any():
            usable = measured | unknown
        else:
            usable, unknown = measured, None
    depth = -values * dc.FEET_PER_M
    footprints = {}
    clip = None
    if core is not None:
        left, bottom, right, top = rasterio.windows.bounds(core, grid.transform)
        # GEOS boxes are closed. Remove line overlaps on the right and bottom
        # edges, but keep crossing endpoints to join to the adjacent core.
        clip = box(left, bottom, right, top), LineString([(left, bottom), (right, bottom), (right, top)])
    for i, (sigma, radius, levels) in enumerate(levels_by_tier):
        pier = i == pier_index
        valid = measured if pier else usable
        key = pier and unknown is not None  # Both tiers share a footprint if there are no unknown cells.
        if key not in footprints:
            squares = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & valid[1:, 1:]
            footprints[key] = polygons(squares, tf @ Affine.translation(0.5, 0.5)) if squares.any() else None
        footprint = footprints[key]
        if footprint is None:
            continue
        interior = minimum_filter(valid, size=2 * radius + 1, mode='constant', cval=False)
        smooth = gaussian_filter(np.where(valid, depth, 0), sigma, radius=radius)
        if not pier and unknown is not None:
            np.minimum(smooth, depth, out=smooth, where=unknown)
        rows = np.where(valid, np.where(interior, smooth, depth), None).tolist()
        for level, lines in dc.trace(rows, levels).items():
            pieces = []
            for line in lines:
                if clip is None:
                    raw = LineString([tf @ (c + 0.5, r + 0.5) for c, r in line])
                else:
                    # Map on the same native lattice in every block, so the
                    # common segments intersect the seam at the same points.
                    raw = LineString([grid.transform @ (window.col_off + c + 0.5, window.row_off + r + 0.5)
                                      for c, r in line])
                    raw = raw.intersection(clip[0]).difference(clip[1])
                for original in line_parts(raw):
                    short = original.simplify(min(cell, CONTOUR_TOLERANCE_M))
                    safe = short if footprint.covers(short) else original
                    if not pier and unknown is not None and safe is not original:
                        safe = _v3_shoal_safe(original, safe, unknown, depth, level, tf, lonlat)
                    pieces.append(safe)
            if pieces:
                yield (i, level), pieces


def v3_grid(grid, region, view, common, native_cell, *, support=None, certified=False, provenance=None,
            positive_down=False, block_max_pixels=None):
    """Trace on one native lattice, with no mosaic/resampling fallback."""
    from shapely import transform as transform_geometry
    from shapely.geometry import MultiLineString, box

    crs = horizontal_crs(grid)
    cell = grid.res[0]
    if (not crs.is_projected or any(a.unit_name != 'metre' for a in crs.axis_info[:2])
            or (grid.transform.b, grid.transform.d, grid.transform.a, grid.transform.e) != (0, 0, cell, -cell)
            or grid.scales[0] != 1 or grid.offsets[0] != 0):
        raise ValueError('ft-v3 requires a north-up native metre lattice and unscaled elevations')
    # Do not draw from an upsampled grid, even at a coarser tier. Unknown native resolution is not evidence.
    if type(native_cell) not in (int, float) or not 0 < native_cell <= cell + 1e-9:
        return
    tiers = list(dc.v3_tiers(view, cell, certified=certified and support is not None))
    if not tiers:
        return
    clip = from_bounds(*transform_bounds('EPSG:4326', crs, *region['bounds'], densify_pts=21), transform=grid.transform)
    x, y = max(0, int(np.floor(clip.col_off))), max(0, int(np.floor(clip.row_off)))
    w = min(grid.width, int(np.ceil(clip.col_off + clip.width))) - x
    h = min(grid.height, int(np.ceil(clip.row_off + clip.height))) - y
    if w < 2 or h < 2:
        return
    cap = preflight.MAX_PIXELS if block_max_pixels is None else min(preflight.MAX_PIXELS, block_max_pixels)
    refusal = f'ft-v3 native window exceeds {cap} pixels; use a smaller region window'
    levels_by_tier = []
    for tier, _ in tiers:
        sigma = tier['sigma_m'] / cell
        levels_by_tier.append((sigma, round(4 * sigma), dc.v3_levels(tier)))
    halo = max(radius for _, radius, _ in levels_by_tier) + 2
    whole = Window(x, y, w, h)
    blocked = w * h > cap
    # Even a one-cell core at maximum overlap must fit. Refuse before any
    # read, rather than discovering that an interior block cannot be traced.
    if blocked and min(w, 2 * halo + 1) * min(h, 2 * halo + 1) > cap:
        raise ValueError(refusal)
    if support is not None:
        if (support.count != 1 or support.dtypes[0] != 'uint8' or support.shape != grid.shape
                or support.crs != grid.crs or support.transform != grid.transform):
            raise ValueError('support raster must be single-band uint8 aligned with the native grid')

    def windows(col, row, end_col, end_row):
        # Bisect the longer core dimension until its clipped halo fits. This
        # also handles narrow windows whose useful blocks are strips.
        left, top = max(x, col - halo), max(y, row - halo)
        right, bottom = min(x + w, end_col + halo), min(y + h, end_row + halo)
        if (right - left) * (bottom - top) <= cap:
            yield Window(left, top, right - left, bottom - top), Window(col, row, end_col - col, end_row - row)
        elif end_col - col >= end_row - row:
            mid = (col + end_col) // 2
            yield from windows(col, row, mid, end_row)
            yield from windows(mid, row, end_col, end_row)
        else:
            mid = (row + end_row) // 2
            yield from windows(col, row, end_col, mid)
            yield from windows(col, mid, end_col, end_row)

    lonlat = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
    pier_index = next((i for i, (tier, _) in enumerate(tiers) if tier['name'] == view['pier_view']['contours_tier']), None)

    def trace(window, core):
        if window.width * window.height > cap:
            raise ValueError(refusal)
        return _v3_block_lines(grid, window, levels_by_tier, pier_index, cell, support=support, provenance=provenance,
                               positive_down=positive_down, core=core, lonlat=lonlat)

    if blocked:
        runs = {}
        for window, core in windows(x, y, x + w, y + h):
            for key, pieces in trace(window, core):
                runs.setdefault(key, []).extend(pieces)
        groups = ((key, runs.pop(key)) for key in sorted(runs))
    else:
        groups = trace(whole, None)

    clip_ll = box(*region['bounds'])
    for (i, level), lines in groups:
        tier, stop = tiers[i]
        if blocked:
            lines = line_parts(line_merge(MultiLineString(lines)))
        coords = []
        for safe in lines:
            ll = transform_geometry(safe, lonlat.transform, interleaved=False)
            for piece in line_parts(ll.intersection(clip_ll)):
                points = dedupe([list(pt) for pt in piece.coords])
                if len(points) >= 2:
                    coords.append(points)
        if coords:
            yield {'type': 'Feature', 'id': f"{common['source_id']}-{level}ft-{tier['name']}",
                   'geometry': {'type': 'MultiLineString', 'coordinates': coords},
                   'properties': {**common, 'kind': 'contour', 'estimated': True, 'native_cell_m': cell,
                                  'depth_ft': level, 'tier': tier['name'], 'index': levels_by_tier[i][2][level],
                                  'minzoom': tier['min_zoom'], **({'maxzoom': stop} if stop is not None else {})}}


V3_EDGE_NOTE = ('Where the measured survey grids stop: one outline of the contributing surveys\' measured water together, '
                'each part credited to the first survey (in order) it bounds; a seam or a gap narrower than the tolerance '
                'between surveys is not an edge. A cell counts only as valid water that its own evidence calls measured '
                '(an EC measured code and support class 3 where the grid carries them); unknown or interpolated support never '
                'counts. Native cells are grouped into blocks of at most half the tolerance; a block counts when at least half '
                'of its cells count. The outline along the region clip is not an edge.')


def v3_edge_block(cell):
    """Native cells per side of an edge block: at most half the edge tolerance, at least one cell."""
    return max(1, int(EDGE_TOLERANCE_M / 2 // cell))


def v3_measured_support(grid, region, view, native_cell, *, support=None, certified=False, provenance=None,
                        positive_down=False, block_max_pixels=None):
    """The grid's demonstrably measured water near the region, as (crs, polygon in that crs), or None.

    Only a grid v3_grid would trace counts (the same native-resolution and tier gates). A cell is measured when it is
    valid water and, where the grid carries evidence, its EC code is `measured` and its support class is 3; unknown or
    interpolated cells never count, so a normalized grid without its support raster has no outline here. Cells are
    grouped into v3_edge_block() blocks on the read window and a block counts when at least half of its cells inside
    the grid count. The read window is the region plus a margin, clipped to the grid, so the window's own border lies
    outside the region and never becomes an edge. Reads are row strips within the native pixel cap.
    """
    from shapely.geometry import box

    crs = horizontal_crs(grid)
    cell = grid.res[0]
    if (not crs.is_projected or any(a.unit_name != 'metre' for a in crs.axis_info[:2])
            or (grid.transform.b, grid.transform.d, grid.transform.a, grid.transform.e) != (0, 0, cell, -cell)
            or grid.scales[0] != 1 or grid.offsets[0] != 0):
        raise ValueError('ft-v3 requires a north-up native metre lattice and unscaled elevations')
    if type(native_cell) not in (int, float) or not 0 < native_cell <= cell + 1e-9:
        return None
    if not list(dc.v3_tiers(view, cell, certified=certified and support is not None)):
        return None
    if support is not None and (support.count != 1 or support.dtypes[0] != 'uint8' or support.shape != grid.shape
                                or support.crs != grid.crs or support.transform != grid.transform):
        raise ValueError('support raster must be single-band uint8 aligned with the native grid')
    n = v3_edge_block(cell)
    margin = 2 * n + int(np.ceil(2 * EDGE_TOLERANCE_M / cell))
    clip = from_bounds(*transform_bounds('EPSG:4326', crs, *region['bounds'], densify_pts=21), transform=grid.transform)
    x, y = max(0, int(np.floor(clip.col_off)) - margin), max(0, int(np.floor(clip.row_off)) - margin)
    w = min(grid.width, int(np.ceil(clip.col_off + clip.width)) + margin) - x
    h = min(grid.height, int(np.ceil(clip.row_off + clip.height)) + margin) - y
    if w < 1 or h < 1:
        return None
    cap = preflight.MAX_PIXELS if block_max_pixels is None else min(preflight.MAX_PIXELS, block_max_pixels)
    if n * w > cap:
        raise ValueError(f'ft-v3 native window exceeds {cap} pixels; use a smaller region window')
    step = max(n, (cap // w) // n * n)
    parts = []
    for top in range(y, y + h, step):
        window = Window(x, top, w, min(step, y + h - top))
        values = grid.read(1, window=window, masked=True).astype('float64').filled(np.nan)
        if positive_down:
            values = -values
        counted = np.isfinite(values) & (values < 0) & (values >= -3000)
        if provenance is not None:
            counted &= provenance.read(1, window=window, masked=True).filled(PAD) == ec.CODES['measured']
        if support is not None:
            counted &= support.read(1, window=window, masked=True).filled(0) == MEASURED_SUPPORT
        if not counted.any():
            continue
        rows, cols = counted.shape
        shape = (-(-rows // n), n, -(-cols // n), n)
        padded = np.zeros((shape[0] * n, shape[2] * n), dtype='int32')
        padded[:rows, :cols] = counted
        inside = np.zeros_like(padded)
        inside[:rows, :cols] = 1
        hits, cells = padded.reshape(shape).sum(axis=(1, 3)), inside.reshape(shape).sum(axis=(1, 3))
        blocks = (hits > 0) & (2 * hits >= cells)
        if not blocks.any():
            continue
        # A part block on the window's right or bottom edge must not reach past the cells it was counted from.
        area = polygons(blocks, grid.window_transform(window) @ Affine.scale(n))
        parts.append(area.intersection(box(*rasterio.windows.bounds(window, grid.transform))))
    if not parts:
        return None
    # Strips share exact lattice edges; the millimetre grid only removes floating-point noise along them.
    return crs, unary_union(parts, grid_size=1e-3)


def v3_survey_edges(region, view, footprints):
    """survey-edge features from [(common, [(crs, polygon), ...]), ...] in source order.

    The edge is the outline of all the surveys' measured water together: the union is closed by half the edge tolerance
    so a seam or a gap narrower than the tolerance between surveys is not an edge. Each part is credited to the first
    survey whose measured water lies within the tolerance of it. Parts outside the region (including the read margin's
    own border) are cut away; parts shorter than EDGE_MIN_LENGTH_M are dropped; the rest are simplified to
    EDGE_TOLERANCE_M and rounded to dc.DECIMALS. Properties follow the client's ft-v3 rule for a non-contour line:
    the style's first tier's min_zoom, index false and no maxzoom.
    """
    import shapely
    from shapely.geometry import box

    footprints = [(common, parts) for common, parts in footprints if parts]
    if not footprints:
        return []
    west, south, east, north = region['bounds']
    local = CRS.from_proj4(f'+proj=aeqd +lat_0={(south + north) / 2} +lon_0={(west + east) / 2} '
                           '+datum=WGS84 +units=m +no_defs')
    to_lonlat_t = Transformer.from_crs(local, 'EPSG:4326', always_xy=True)
    projections = {}

    def project(crs, geometry):
        key = CRS.from_user_input(crs).to_wkt()
        if key not in projections:
            projections[key] = Transformer.from_crs(crs, local, always_xy=True)
        return shapely.transform(geometry, projections[key].transform, interleaved=False)

    surveys = [(common, unary_union([project(crs, polygon) for crs, polygon in parts])) for common, parts in footprints]
    half = EDGE_TOLERANCE_M / 2
    union = unary_union([area for _, area in surveys]).buffer(half, quad_segs=2).buffer(-half, quad_segs=2)
    # Keep coordinates strictly inside the region so rounding cannot move an endpoint across its bounds.
    eps = 10 ** -dc.DECIMALS
    inner = shapely.segmentize(box(west + eps, south + eps, east - eps, north - eps), 0.001)
    outline = union.boundary.intersection(project('EPSG:4326', inner))
    taken, features = None, []
    first_zoom = view['contours']['tiers'][0]['min_zoom']
    for common, area in surveys:
        zone = area.buffer(EDGE_TOLERANCE_M, quad_segs=2)
        mine = zone if taken is None else zone.difference(taken)
        taken = zone if taken is None else taken.union(zone)
        merged = line_merge(unary_union(list(line_parts(outline.intersection(mine)))))
        lines = []
        for piece in line_parts(merged):
            if piece.length < EDGE_MIN_LENGTH_M:
                continue
            points = to_lonlat(to_lonlat_t, list(piece.simplify(EDGE_TOLERANCE_M).coords), dc.DECIMALS)
            points = dedupe([[min(max(x, west), east), min(max(y, south), north)] for x, y in points])
            if len(points) >= 2:
                lines.append(points)
        if lines:
            features.append({'type': 'Feature', 'id': f"{common['source_id']}-edge",
                             'geometry': {'type': 'MultiLineString', 'coordinates': sorted(lines)},
                             'properties': {**common, 'kind': 'survey-edge', 'minzoom': first_zoom, 'index': False}})
    return features


def v3_collection(region, view, features, sources, omitted):
    provenance = {'region_id': region['id'], 'bounds': region['bounds'], 'units': 'ft', 'set': dc.FT_V3,
                  'contours': view.digest('contours'), 'shelf_limit_ft': dc.V2_SHELF_LIMIT_FT,
                  'features': len(features), 'sources': sources, 'sources_omitted': omitted,
                  'method': ('Marching squares on Gaussian-smoothed native water cells (measured or unknown '
                             'support; unknown-support cells never drawn deeper than their own value); no resampling.'),
                  'limitations': 'Estimated display contours. Not for navigation. No datum conversion.'}
    if any(f['properties'].get('kind') == 'survey-edge' for f in features):
        provenance['edge'] = {'tolerance_m': EDGE_TOLERANCE_M, 'min_length_m': EDGE_MIN_LENGTH_M, 'note': V3_EDGE_NOTE}
    return {'type': 'FeatureCollection', 'schema_version': dc.SCHEMA_VERSION, 'features': features,
            'provenance': provenance}


def v3_cli(region, sources, order, opened, identity, hashes, supports, provs, held):
    from skippercast.relief.render_config import resolve_style

    _, style = resolve_style(region['id'])
    if style is None:
        raise SystemExit('--set v3 needs a kit render style')
    view = style.view('contours')
    features, listed, footprints = [], [], []
    with ExitStack() as stack:
        for ident, grid in zip(order, opened):
            source, known = sources[ident], identity[ident]
            common = {'source_id': ident, 'survey_date': known['survey_date'], 'vertical_datum': known['vertical_datum']}
            measured = stack.enter_context(open_geotiff(supports[ident], normalized=True)) if ident in supports else None
            ec_grid = stack.enter_context(rasterio.open(provs[ident])) if ident in provs else None
            # Standalone inputs have no attested selector row or native zoom eligibility.
            # A pinned support raster alone cannot certify pier contours; the receipt-backed
            # relief contour stage supplies certification from its attested selection.
            lines = list(v3_grid(grid, region, view, common, known['native_cell_m'], support=measured,
                                 certified=False, provenance=ec_grid))
            if lines:
                listed.append({**common, 'name': known['name'], 'url': source['documentation_url'],
                               'attribution': source['rights']['attribution'], 'sha256': hashes[ident],
                               'native_cell_m': grid.res[0]})
                features.extend(lines)
                area = v3_measured_support(grid, region, view, known['native_cell_m'], support=measured,
                                           certified=False, provenance=ec_grid)
                footprints.append((common, [area] if area is not None else []))
    features.extend(v3_survey_edges(region, view, footprints))
    doc = v3_collection(region, view, features, listed, dc.omitted_sources(region, sources, (s['source_id'] for s in listed)))
    if held:
        doc['provenance'].update(publication_held=True, held_sources=dc.held_sources(doc, sources))
        dc.check_held_contours(doc, region, sources, view=view)
    else:
        dc.check_contours(doc, region, sources)
    return doc


def v2_contour_runs(depth, block, native, transformer, square):
    """Yield depth, zoom range, EC class and lines; native replaces coarse only on its supported footprint."""
    native_depth, native_transform, support = native if native is not None else (None, None, None)
    coarse_valid = np.isfinite(depth)
    squares = coarse_valid[:-1, :-1] & coarse_valid[:-1, 1:] & coarse_valid[1:, :-1] & coarse_valid[1:, 1:]
    coarse_support = polygons(squares, block @ Affine.translation(0.5, 0.5)) if squares.any() else None
    fallback = coarse_support.difference(support) if coarse_support is not None and support is not None else coarse_support
    for is_native, values, transform, domain, tolerance in (
            (False, v2_smooth(depth), block, coarse_support, V2_COARSE_TOLERANCE_M),
            (True, native_depth, native_transform, support, CONTOUR_TOLERANCE_M)):
        if domain is None or values is None or transform is None:
            continue
        rows = np.where(np.isfinite(values), values, None).tolist()
        classes = square if not is_native else None
        levels = [d for d, z in dc.V2_MINZOOM.items() if is_native or z < dc.V2_NATIVE_ZOOM]
        for d, lines in dc.trace(rows, levels, squares=classes is not None).items():
            start = dc.V2_MINZOOM[d]
            runs = {}
            for line in lines:
                for name, part in (class_runs(line[0], line[1], classes) if classes is not None else [('measured', line)]):
                    original = LineString([transform @ (c + 0.5, r + 0.5) for c, r in part])
                    if not is_native and support is not None:
                        pieces = [(original.difference(support), None, fallback),
                                  (original.intersection(support), dc.V2_NATIVE_ZOOM, support)]
                    else:
                        pieces = [(original, None, domain)]
                    for geometry, stop, allowed in pieces:
                        for piece in line_parts(geometry):
                            short = piece.simplify(tolerance)
                            safe = short if allowed is not None and allowed.covers(short) else piece
                            ll = dedupe(to_lonlat(transformer, list(safe.coords), V2_DECIMALS))
                            if len(ll) >= 2:
                                runs.setdefault((stop, name), []).append(ll)
            for (stop, name), lines in runs.items():
                yield d, max(start, dc.V2_NATIVE_ZOOM) if is_native else start, stop, name, lines


def v1_contour_runs(own, x0, y0, transformer, square):
    rows = [[None if not np.isfinite(v) else float(v) for v in row] for row in own]
    for d, lines in dc.trace(rows, dc.levels(float(np.nanmin(own)), float(np.nanmax(own))), squares=square is not None).items():
        runs = {}
        for line in lines:
            for name, part in (class_runs(line[0], line[1], square) if square is not None else [('measured', line)]):
                metres = [(x0 + (c + 0.5) * dc.CELL_M, y0 - (r + 0.5) * dc.CELL_M) for c, r in part]
                ll = dedupe(to_lonlat(transformer, dc.simplify(metres, CONTOUR_TOLERANCE_M, (1.0, 1.0))))
                if len(ll) >= 2:
                    runs.setdefault(str(name), []).append(ll)
        for name in (n for n in ec.PROVENANCE_CLASSES if runs.get(n)):
            yield d, name, runs[name]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--region', required=True)
    p.add_argument('--set', choices=('v1', 'v2', 'v3'), default='v1', help='Feet contour set (default: v1).')
    p.add_argument('--clip', nargs=4, type=float, metavar=('W', 'S', 'E', 'N'), help='Bound a held ft-v3 run to a smaller lon/lat window.')
    p.add_argument('--grid', action='append', required=True, metavar='SOURCE_ID=PATH')
    p.add_argument('--normalized-sidecar', action='append', default=[], metavar='SOURCE_ID=PATH',
                   help='The R2 sidecar.json for a --grid normalised GeoTIFF.')
    p.add_argument('--normalized-support', action='append', default=[], metavar='SOURCE_ID=PATH',
                   help='The support.tif (uint8, class 3 = measured) aligned with a --normalized-sidecar grid; required for '
                   'its z14+ native detail, which is drawn only over measured cells.')
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
    v2 = args.set == 'v2'
    block_m = dc.V2_CELL_M if v2 else dc.CELL_M
    decimals = V2_DECIMALS if v2 else dc.DECIMALS
    held = args.held_output and Path(args.held_output).expanduser().resolve()
    output = args.output and Path(args.output).expanduser().resolve()
    repo = Path(REPO).resolve()
    if held and (held == repo or repo in held.parents):
        raise SystemExit(f'Held output must be outside the work tree: {held}')
    if output and (output == repo or repo in output.parents):
        raise SystemExit(f'Output must be outside the work tree: {output}')
    region = load_region(args.region)
    if args.clip is not None:
        w, s, e, n = region['bounds']
        a, b, c, d = args.clip
        if args.set != 'v3' or not held or not (w <= a < c <= e and s <= b < d <= n):
            p.error('--clip requires --set v3, --held-output and a window inside the region')
        region = {**region, 'bounds': args.clip}
    _, sources = load_catalogs()
    bound = region['source_bindings']['bathymetry']
    grids, surveys, provs, sidecars, supports = {}, {}, {}, {}, {}
    for pairs, items in ((grids, args.grid), (surveys, args.bag_survey), (provs, args.provenance),
                         (sidecars, args.normalized_sidecar), (supports, args.normalized_support)):
        for ident, value in (item.split('=', 1) for item in items):
            if ident in pairs:
                raise SystemExit(f'{ident} given twice; one file per source per build')
            pairs[ident] = value
    for ident in sorted(set(provs) - set(grids)):
        raise SystemExit(f'{ident}: --provenance is only for a source given with --grid')
    if set(sidecars) - set(grids):
        raise SystemExit('--normalized-sidecar is only for a source given with --grid')
    if set(supports) - set(sidecars):
        raise SystemExit('--normalized-support is only for a source given with --grid and --normalized-sidecar')
    for ident, value in supports.items():
        if '://' in value or value.startswith('/vsi') or not Path(value).expanduser().is_file():
            raise SystemExit(f'{ident}: --normalized-support must be an existing local file')
        verify_support_binding(ident, sidecars[ident], value)
    order = [ident for ident in bound if ident in grids]
    if set(grids) - set(order):
        raise SystemExit(f'Not bathymetry bindings of {region["id"]}: {sorted(set(grids) - set(order))}')
    # Every grid's approval is checked before any grid is opened or hashed.
    for ident in order:
        source = sources[ident]
        rights = source.get('rights') or {}
        status, licence = source['review_status'], rights.get('license')
        display = rights.get('public_display')
        if display == 'excluded':
            raise SystemExit(f'{ident} is not cleared for public display')
        if held and (status not in ('approved', 'candidate') or licence in (None, '', 'unresolved', 'dataset-review-needed')
                     or 'bathymetry' not in sources[ident]['needs']):
            raise SystemExit(f'{ident} cannot be traced, even held: {status}, licence {licence}')
        # Original and normalised grids alike need an affirmative public_display: 'allowed'; silence is not clearance.
        if not held and (reason := public_refusal(ident, region, sources)):
            raise SystemExit(f'{ident} is {reason}')
    adapters = {ident: 'geotiff' if ident in sidecars else sources[ident].get('adapter', 'geotiff')
                for ident in order}
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
    identity, original_hashes, grid_hashes = {}, {}, {}
    for ident in order:
        if adapters[ident] == 'bag':
            identity[ident] = bag_identity(ident, grids[ident], surveys[ident], sources[ident])
            continue
        reviewed = sources[ident]
        native, datum = reviewed.get('native_resolution_m'), reviewed.get('vertical_datum')
        with open_geotiff(grids[ident], normalized=ident in sidecars) as grid:
            res = grid.res
            if ident in sidecars:
                original_hashes[ident], grid_hashes[ident], datum = normalized_identity(ident, grid, sidecars[ident], datum)
            ec_version = check_provenance(ident, grid, provs[ident]) if ident in provs else None
        # The provenance labels each grid with the reviewed native cell; a resample must not carry that label.
        if ident not in sidecars and (not isinstance(native, (int, float)) or any(abs(r - native) > 1e-9 for r in res)):
            raise SystemExit(f'{ident}: grid cell {res} differs from reviewed native_resolution_m {native}')
        if ident in sidecars:
            # Reprojection must not upgrade the original source's detail eligibility.
            native = max(res[0], native) if isinstance(native, (int, float)) else None
        identity[ident] = {'name': reviewed['name'], 'survey_date': str(reviewed['survey_year']),
                           'vertical_datum': datum or dc.UNVERIFIED_DATUM,
                           'native_cell_m': native, 'extra': {'ec_version': ec_version} if ec_version else {}}
    hashes = {ident: original_hashes[ident] if ident in sidecars else sha256(grids[ident]) for ident in order}
    if len(set(hashes.values())) != len(hashes) or len({grid_hashes.get(i, hashes[i]) for i in order}) != len(order):
        raise SystemExit('Two --grid sources are the same file; each binding needs its own survey grid')
    with ExitStack() as stack:
        opened = [stack.enter_context(open_geotiff(grids[ident], normalized=True) if ident in sidecars
                                      else open_grid(ident, grids[ident], surveys.get(ident))) for ident in order]
        if args.set == 'v3':
            if not (held or output):
                p.error('--set v3 requires an explicit output outside the work tree')
            for ident, grid in zip(order, opened):
                if adapters[ident] == 'bag':
                    identity[ident]['native_cell_m'] = grid.res[0]
                elif ident in sidecars and ident not in supports:
                    p.error(f'{ident}: ft-v3 normalized input needs --normalized-support')
            doc = v3_cli(region, sources, order, opened, identity, hashes, supports, provs, held)
            print(atomic_json(held or output, doc))
            return
        crs = horizontal(opened)
        # Reads are clipped to the region (plus one block): a coast-wide BAG is never read whole.
        west, south, east, north = transform_bounds('EPSG:4326', crs, *region['bounds'], densify_pts=21)
        lattice = lattice_for(opened, (west - block_m, south - block_m, east + block_m, north + block_m), block_m)
        offsets = [native_offsets(g, lattice, block_m) for g in opened]
        for ident, grid, offset in zip(order, opened, offsets):
            if adapters[ident] == 'bag':
                identity[ident]['native_cell_m'] = grid.res[0]
            check_first_strip(ident, grid, lattice, offset, identity[ident]['vertical_datum'], adapters[ident] == 'bag')
        keys = [(n, identity[ident]['vertical_datum']) for ident, (_, _, n) in zip(order, offsets)]
        ecs = [[stack.enter_context(rasterio.open(q)) for q in ec_paths(provs[ident])] if ident in provs else None
               for ident in order]
        depth, owner, cls, reason, hint = merged_blocks(opened, lattice, offsets, keys, ecs)
        x0, y0, _, _ = lattice
        block = Affine(block_m, 0, x0, 0, -block_m, y0)
        transformer = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
        # Blocks outside the region are not traced but stay in the union: no survey edge along the clip.
        inside = inside_blocks(transformer, lattice, region['bounds'], block_m)
        eligible = [i for i, g in enumerate(opened) if v2 and g.res[0] <= dc.V2_NATIVE_MAX_CELL_M
                    and (order[i] not in sidecars or (identity[order[i]]['native_cell_m'] or float('inf')) <= dc.V2_NATIVE_MAX_CELL_M)
                    and ((owner == i) & inside & np.isfinite(depth)).any()]
        # A normalised grid's support raster says which cells are measured rather than interpolated; native detail is
        # granted only there (as in the region stage), so a normalised source cannot draw it without that evidence.
        for i in eligible:
            if order[i] in sidecars and order[i] not in supports:
                raise SystemExit(f'{order[i]}: native detail from a normalised grid needs --normalized-support {order[i]}=PATH '
                                 '(its support raster; interpolated cells are never traced at native detail)')
        def bound_support(exit_stack, ident):
            # Re-checked at open time so the bytes traced are the bytes the receipt pins.
            if ident not in supports:
                return None
            verify_support_binding(ident, sidecars[ident], supports[ident])
            return exit_stack.enter_context(open_geotiff(supports[ident], normalized=True))

        native = {i: v2_native(opened[i], offsets[i], (owner == i) & inside & np.isfinite(depth), ecs[i],
                               bound_support(stack, order[i]))
                  for i in eligible}
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
        common = {'source_id': ident, 'survey_date': survey_date, 'vertical_datum': entry['vertical_datum']}
        ancillary = {**common, 'minzoom': 8, 'index': False} if v2 else common
        # Unresolved blocks are areas, never contours: one MultiPolygon per reason, a conflict with its shallowest hint.
        # They are drawn whether or not the source also has valid water, so an all-unresolved source still shows.
        for k, why in enumerate(ec.UNRESOLVED_REASONS):
            here = (owner == i) & inside & unresolved & (reason == k)
            if not here.any():
                continue
            area = polygons(here, block)
            props = {'kind': ec.UNRESOLVED_KIND, 'reason': why, 'blocks': int(here.sum())}
            if why == 'conflict' and np.isfinite(hint[here]).any():
                props[ec.SHOAL_HINT_KEY] = round(-float(np.nanmax(hint[here])) * dc.FEET_PER_M)
            features.append({'type': 'Feature', 'id': f'{ident}-unresolved-{why}', 'geometry': {'type': 'MultiPolygon', 'coordinates': [
                [dedupe(to_lonlat(transformer, list(ring.coords), decimals)) for ring in (g.exterior, *g.interiors)]
                for g in getattr(area, 'geoms', [area])]}, 'properties': {**props, **ancillary}})
        if not mine.any():
            continue
        own = np.where(mine, depth, np.nan)
        if v2:
            for d, start, stop, name, lines in v2_contour_runs(own, block, native.pop(i, None), transformer, square if provs else None):
                variant = '-native' if start >= dc.V2_NATIVE_ZOOM else '-overview' if stop is not None else ''
                features.append({'type': 'Feature', 'id': f'{ident}-{d}ft{variant}' + ('' if name == 'measured' else f'-{name}'),
                                 'geometry': {'type': 'MultiLineString', 'coordinates': lines},
                                 'properties': {'kind': 'contour', 'depth_ft': d, 'index': d in dc.V2_INDEX_FT,
                                                'minzoom': start, 'estimated': True,
                                                **({'maxzoom': stop} if stop is not None else {}), **common,
                                                **({'provenance': name} if provs else {})}})
        else:
            for d, name, lines in v1_contour_runs(own, x0, y0, transformer, square if provs else None):
                features.append({'type': 'Feature', 'id': f'{ident}-{d}ft' + ('' if name == 'measured' else f'-{name}'),
                                 'geometry': {'type': 'MultiLineString', 'coordinates': lines},
                                 'properties': {'kind': 'contour', 'depth_ft': d, 'index': d % dc.INDEX_FT == 0, **common,
                                                **({'provenance': name} if provs else {})}})
        # Where the contours stop: the outline of all the surveys' supported blocks together, each part credited to the
        # survey whose blocks it bounds. A seam between two surveys is not an edge: a reviewed grid continues there.
        edge = line_merge(polygons(mine, block).boundary.intersection(union.boundary))
        pieces = [g for g in getattr(edge, 'geoms', [edge]) if g.geom_type == 'LineString' and g.length >= EDGE_MIN_LENGTH_M]
        lines = sorted(ll for ll in (dedupe(to_lonlat(transformer, list(g.simplify(EDGE_TOLERANCE_M).coords), decimals)) for g in pieces) if len(ll) >= 2)
        if lines:
            features.append({'type': 'Feature', 'id': f'{ident}-edge', 'geometry': {'type': 'MultiLineString', 'coordinates': lines},
                             'properties': {'kind': 'survey-edge', **ancillary}})
    # A supplied grid that adds nothing (wrong sign, no water, fully overlapped) would look like full coverage; one whose
    # only blocks are unresolved still contributes its areas.
    empty = [e['source_id'] for e in listed if not e['supported_blocks'] and not e.get('provenance_counts', {}).get('unresolved')]
    if empty:
        raise SystemExit(f'Supplied grids contribute no valid water block: {empty}')
    xs = [pt[0] for f in features for pt in geometry_points(f['geometry'])]
    ys = [pt[1] for f in features for pt in geometry_points(f['geometry'])]
    collection = {'type': 'FeatureCollection', 'schema_version': dc.SCHEMA_VERSION, 'provenance': {
        'region_id': region['id'], 'units': 'ft',
        **({'set': dc.FT_V2, 'intervals': dc.v2_intervals(), 'index_depths_ft': list(dc.V2_INDEX_FT)} if v2
           else {'interval_ft': dc.INTERVAL_FT, 'index_ft': dc.INDEX_FT}),
        'shelf_limit_ft': dc.V2_SHELF_LIMIT_FT if v2 else dc.SHELF_LIMIT_FT, 'cell_m': block_m, 'horizontal_crs': crs,
        'bounds': region['bounds'] if v2 and not features else [min(xs), min(ys), max(xs), max(ys)],
        'features': len(features), 'sources': listed,
        # The region's bound surveys not drawn here, with their catalog review_status (checked by dc.check_contours).
        'sources_omitted': dc.omitted_sources(region, sources, order),
        # Held mode (--held-output): private, never published; names the traced sources that are not approved.
        **({'publication_held': True, 'held_sources': [{'source_id': i, 'review_status': sources[i]['review_status']}
                                                       for i in order if sources[i]['review_status'] != 'approved']}
           if held else {}),
        'coordinate_decimals': decimals, 'simplify_tolerance_m': V2_COARSE_TOLERANCE_M if v2 else CONTOUR_TOLERANCE_M,
        'edge': {'tolerance_m': EDGE_TOLERANCE_M, 'min_length_m': EDGE_MIN_LENGTH_M,
                 'note': 'The outline of all the surveys\' supported blocks together; seams between surveys are not edges.'},
        'datum_note': 'Depths are below each survey\'s own vertical datum.' + (USGS_DATUM if 'geotiff' in kinds and not sidecars else '')
                      + (BAG_DATUM if 'bag' in kinds else '') + ' Not converted or certified.',
        'method': f'Native cells are merged in the region\'s binding order (the first survey with valid water wins each cell); '
                  f'each {dc.CELL_M} m block is their mean and counts only when all of them are valid water. Marching squares '
                  f'at every {dc.INTERVAL_FT} ft to {dc.SHELF_LIMIT_FT} ft draws only between four valid blocks of one survey '
                  '(the survey supplying most of each block), so lines stop where the reviewed grid stops.' + (EC_METHOD if provs else ''),
        'limitations': 'Not for navigation. Historical survey; the bottom can have changed. Display contours from averaged blocks, '
                       'not soundings or chart depths.'},
        'features': features}
    if v2:
        collection['provenance']['method'] = (
            'Marching squares on valid 10 m mean blocks, smoothed at sigma 1.2 cells within supported neighborhoods. '
            'At z14 reviewed grids of 2 m or finer replace the coarse geometry only on their supported squares. '
            'At z15 those grids add 5, 15 and 25 ft. These display lines are estimates, not certified measurements.'
            + (EC_METHOD if provs else ''))
    (dc.check_held_contours if held else dc.check_contours)(collection, region, sources)
    receipt = atomic_json(held or output or REPO / 'catalog/depth-contours' / f'{region["id"]}.geojson', collection)
    print({'features': len(features), **receipt, **({'held': True} if held else {}), 'sources': [(s['source_id'], s['sha256'][:12], s['supported_blocks']) for s in listed]})


if __name__ == '__main__':
    main()
