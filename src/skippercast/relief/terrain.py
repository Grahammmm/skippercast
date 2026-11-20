"""Build regional 3D terrain from the receipted public mosaic and optional native detail."""
from contextlib import ExitStack
import gzip
import json
import math
from pathlib import Path

from skippercast.relief import receipts

UPSTREAM = ('mosaic:public',)
TARGET = 'layers/terrain'
TILE_M = 4096  # RegionTile width in the native viewer.
MAX_SIZE = 1025
LAND_M = 3
MERCATOR_RADIUS_M = 6378137  # Match coast3d/grid.ts.


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def mosaic_files(ctx):
    needed = {'manifest.json', 'elevation.tif', 'contributor.tif'}
    found = {}
    for row in ctx.upstream['mosaic.public']['outputs']:
        path = ctx.region.resolve(row['path'])
        if path.name in needed:
            if path.name in found:
                raise receipts.ReceiptError(f'ambiguous mosaic output: {path.name}')
            found[path.name] = path
    if found.keys() != needed:
        raise receipts.ReceiptError('public mosaic receipt must bind manifest, elevation and contributor')
    return found


def native_entries(ctx):
    table = ctx.region.dir / 'select' / 'native.json'
    if not table.exists():
        return None, []
    # The real DL-5 mosaic receipt already depends on this exact select generation.
    # Only consume the native list from that selection, not an arbitrary leftover.
    if not any(u['stage'] == 'select' and u.get('scope') is None
               for u in ctx.upstream['mosaic.public']['upstream']):
        raise receipts.ReceiptError('native selection is not in the public mosaic chain')
    selected = receipts.read_receipt(ctx.region.receipt_path('select'))
    if not selected or not any(row['path'] == ctx.region.record(table) for row in selected['outputs']):
        raise receipts.ReceiptError('select receipt does not bind native.json')
    rows = read_json(table)
    if not isinstance(rows, list) or any(row.get('rights_class') != 'public' for row in rows):
        raise receipts.ReceiptError('expected a public native selection')
    return table, rows


def native_refs(table, row):
    for field, pin in (('path', 'sha256'), ('support_path', 'support_sha256')):
        if field == 'support_path' and row.get(field) is None:
            continue
        name = row[field]
        if not isinstance(name, str) or '://' in name or name.startswith('/vsi'):
            raise receipts.ReceiptError('native raster must be a local file')
        yield table.parent / Path(name).expanduser(), row[pin]


def plan(ctx):
    table, rows = native_entries(ctx)
    if table is None:
        return receipts.Plan()
    return receipts.Plan([receipts.Input(table, 'public-native-selection'), *(
        receipts.Input(path, f'native:{row["id"]}') for row in rows for path, _ in native_refs(table, row)
    )])


class Frame:
    """Viewer coordinates are scaled EPSG:3857 metres with south-positive z."""

    def __init__(self, bounds):
        west, south, east, north = bounds
        if not (-180 <= west < east <= 180 and -85 <= south < north <= 85):
            raise receipts.ReceiptError('invalid mosaic geographic bounds')
        self.origin = [(west + east) / 2, (south + north) / 2]
        self.scale = math.cos(math.radians(self.origin[1]))
        self.mx, self.my = self.project(*self.origin)
        w, n = self.project(west, north)
        e, s = self.project(east, south)
        self.bounds = ((w - self.mx) * self.scale, (self.my - n) * self.scale,
                       (e - self.mx) * self.scale, (self.my - s) * self.scale)

    @staticmethod
    def project(lon, lat):
        return (MERCATOR_RADIUS_M * math.radians(lon),
                MERCATOR_RADIUS_M * math.asinh(math.tan(math.radians(lat))))

    def mercator(self, x, z):
        return self.mx + x / self.scale, self.my - z / self.scale


def aligned(first, other):
    if (first.crs, first.transform, first.shape) != (other.crs, other.transform, other.shape):
        raise receipts.ReceiptError('elevation and companion raster must share one grid')


def samples(frame, x, z, dx, dz, size, elevation, companion, *, contributor=False):
    """Nearest numeric values; conservative validity across each vertex footprint.

    Each triangle is covered by the half-step squares around its three vertices.
    At coarse LODs test all source cells in the enclosing source-pixel rectangle,
    not just the nearest cell (which would jump over sub-grid holes). Work in
    blocks so the full-resolution regional raster is never loaded in memory.
    """
    import numpy as np
    from pyproj import Transformer
    from rasterio.windows import Window

    inverse = ~elevation.transform
    transform = Transformer.from_crs('EPSG:3857', elevation.crs, always_xy=True)
    # With a CRS change, sample each edge's midpoint too, and round out by
    # 0.01 pixel for curvature/rounding on these small California footprints.
    padding = 0 if elevation.crs.to_epsg() == 3857 else 0.01
    offsets = (-0.5, 0, 0.5) if padding else (-0.5, 0.5)
    values = np.full((size, size), np.nan, dtype=np.float32)
    codes = np.zeros((size, size), dtype=np.uint16)

    def pixel(cx, cz):
        mx, my = frame.mercator(cx, cz)
        return inverse @ transform.transform(mx, my)

    for j in range(0, size, 64):
        for i in range(0, size, 64):
            a = slice(j, min(j + 64, size))
            b = slice(i, min(i + 64, size))
            iz, ix = np.mgrid[a, b]
            cols, rows = pixel(x + ix * dx, z + iz * dz)
            corners = [pixel(x + (ix + ox) * dx, z + (iz + oz) * dz)
                       for oz in offsets for ox in offsets]
            low, high = np.min(corners, axis=0), np.max(corners, axis=0)
            # Tolerate sub-nanopixel noise at coincident edges in EPSG:3857.
            c0, r0 = np.floor(low - padding + 1e-8).astype(np.int64)
            c1, r1 = np.ceil(high + padding - 1e-8).astype(np.int64)
            inside = (r0 >= 0) & (c0 >= 0) & (r1 <= elevation.height) & (c1 <= elevation.width)
            if not inside.any():
                continue
            r0, c0, r1, c1 = (v[inside] for v in (r0, c0, r1, c1))
            top, left = r0.min(), c0.min()
            window = Window(left, top, c1.max() - left, r1.max() - top)
            depth = elevation.read(1, window=window, masked=True)
            valid = ~np.ma.getmaskarray(depth) & np.isfinite(depth.data)
            if elevation.nodata is not None:
                valid &= depth.data != elevation.nodata
            support = companion.read(1, window=window, masked=True).filled(0) if companion is not None else None
            if support is not None:
                valid &= support > 0
            # Integral image answers arbitrary rectangular validity queries in O(1).
            missing = np.zeros((valid.shape[0] + 1, valid.shape[1] + 1), dtype=np.int32)
            missing[1:, 1:] = np.cumsum(np.cumsum(~valid, axis=0, dtype=np.int32), axis=1, dtype=np.int32)
            r0, r1, c0, c1 = r0 - top, r1 - top, c0 - left, c1 - left
            clear = missing[r1, c1] + missing[r0, c0] == missing[r1, c0] + missing[r0, c1]
            r = np.floor(rows[inside][clear]).astype(np.int64) - top
            c = np.floor(cols[inside][clear]).astype(np.int64) - left
            dest = (iz[inside][clear], ix[inside][clear])
            values[dest] = depth.data[r, c]
            if contributor and support is not None:
                codes[dest] = support[r, c]
    return values, codes


def write_grid(out, region_id, name, values, ids) -> dict:
    path = out / f'{name}.bin.gz'
    # Float32 LE row-major plane, then one source byte per vertex. Zero source
    # is the validity mask; its finite elevation placeholder is not sea level.
    with path.open('wb') as file, gzip.GzipFile(filename='', fileobj=file, mode='wb', mtime=0) as stream:
        stream.write(values.astype('<f4', copy=False).tobytes())
        stream.write(ids.tobytes())
    return dict(url=f'/data/relief/{region_id}/terrain/{path.name}',
                sha256=receipts.sha256_file(path), bytes=path.stat().st_size,
                encoding='gzip', decodedBytes=values.size * 5, size=values.shape[0])


def build(ctx, out):
    import numpy as np
    import rasterio
    from rasterio.warp import transform_bounds

    paths = mosaic_files(ctx)
    manifest = read_json(paths['manifest.json'])
    if (manifest['segment'], manifest['units'], manifest['value_convention']) != (
            ctx.region.id, 'm', 'elevation_positive_up'):
        raise receipts.ReceiptError('unexpected public mosaic identity or elevation convention')
    frame = Frame(manifest['bounds_wgs84'])
    table, rows = native_entries(ctx)
    sources, inventory = [], {}

    def source_code(row):
        if row['rights_class'] != 'public':
            raise receipts.ReceiptError('non-public terrain source')
        label, datum = row.get('label', 'estimated'), row['vertical_datum']
        identity = row.get('source_id', row['id'])
        key = identity, row['resolution_m'], datum, label
        if key not in inventory:
            code = len(sources) + 1
            if code > 255:
                raise receipts.ReceiptError('more than 255 distinct terrain sources')
            url = row.get('url') or row.get('citation') or ''
            sources.append(dict(id=code, sourceId=identity, label=f'{identity} ({label})', kind='estimate',
                                resolutionM=row['resolution_m'], datum=datum, sourceDate=row.get('source_date') or '',
                                url=url if url.startswith(('https://', 'http://')) else ''))
            inventory[key] = code
        return inventory[key]

    lookup = np.zeros(65536, dtype=np.uint8)
    for row in manifest['sources']:
        lookup[row['code']] = source_code(row)
    native = []
    for row in rows:  # selector priority, not filename order
        refs = list(native_refs(table, row))
        for path, pin in refs:
            if receipts.sha256_file(path) != pin:
                raise receipts.ReceiptError(f'native raster hash changed: {row["id"]}')
        if row['units'] != 'm' or row['value_convention'] not in {'elevation_positive_up', 'depth_positive_down'}:
            raise receipts.ReceiptError('invalid native elevation convention')
        with rasterio.open(refs[0][0]) as grid:
            w, s, e, n = transform_bounds(grid.crs, 'EPSG:3857', *grid.bounds)
        native.append((row, refs, source_code(row), (w, s, e, n)))

    with rasterio.open(paths['elevation.tif']) as elevation, rasterio.open(paths['contributor.tif']) as contributor:
        aligned(elevation, contributor)
        west, north, east, south = frame.bounds

        def sample(x, z, dx, dz, size):
            heights, ids = samples(frame, x, z, dx, dz, size, elevation, contributor, contributor=True)
            codes = lookup[ids]
            if np.any((ids != 0) & (codes == 0)):
                raise receipts.ReceiptError('unknown mosaic contributor code')
            # The mosaic raster and the last square tiles can extend past the region box.
            codes[:, x + np.arange(size) * dx > east + 1e-8] = 0
            codes[z + np.arange(size) * dz > south + 1e-8, :] = 0
            heights[codes == 0] = 0
            return heights, codes

        def write(name, values, ids):
            return write_grid(out, ctx.region.id, name, values, ids)

        width, height = east - west, south - north
        size = min(MAX_SIZE, math.ceil(max(width, height) / 32) + 1)
        dx, dz = width / (size - 1), height / (size - 1)
        overview = write('overview', *sample(west, north, dx, dz, size))
        overview.update(x=west, z=north, dx=dx, dz=dz)
        cols, rows = math.ceil(width / TILE_M), math.ceil(height / TILE_M)
        tiles = []
        for j in range(rows):
            for i in range(cols):
                x, z = west + i * TILE_M, north + j * TILE_M
                name = f'tile-{i}-{j}'
                lods = []
                for spacing in (32, 16):
                    values, ids = sample(x, z, spacing, spacing, TILE_M // spacing + 1)
                    if ids.any():
                        lods.append(dict(write(f'{name}-{spacing}', values, ids), spacing=spacing))
                mx0, my1 = frame.mercator(x, z)
                mx1, my0 = frame.mercator(x + TILE_M, z + TILE_M)
                overlaps = [(row, refs, code) for row, refs, code, (w, s, e, n) in native
                            if w < mx1 and e > mx0 and s < my1 and n > my0]
                if overlaps:
                    spacing = 4
                    size = TILE_M // spacing + 1
                    values, ids = sample(x, z, spacing, spacing, size)
                    remaining = (ids != 0) & (values <= LAND_M)
                    added = False
                    for row, refs, code in overlaps:
                        if not remaining.any():
                            break
                        with ExitStack() as stack:
                            grid = stack.enter_context(rasterio.open(refs[0][0]))
                            support = stack.enter_context(rasterio.open(refs[1][0])) if len(refs) > 1 else None
                            if support is not None:
                                aligned(grid, support)
                            detail, _ = samples(frame, x, z, spacing, spacing, size, grid, support)
                        if row['value_convention'] == 'depth_positive_down':
                            detail *= -1
                        detail += row.get('vertical_offset_m', 0)
                        use = remaining & np.isfinite(detail) & (detail <= LAND_M)
                        values[use], ids[use] = detail[use], code
                        remaining[use] = False
                        added |= bool(use.any())
                    if added:
                        lods.append(dict(write(f'{name}-{spacing}', values, ids), spacing=spacing))
                if lods:
                    tiles.append(dict(x=x, z=z, width=TILE_M, lods=lods))
    result = dict(schemaVersion=1, origin=frame.origin, nodataSourceId=0,
                  bounds=[west, north, west + cols * TILE_M, north + rows * TILE_M],
                  overview=overview, tiles=tiles, harborTiles=[], imagery=[], sources=sources, waterReferenceM=0)
    (out / 'manifest.json').write_bytes(receipts.canonical(result) + b'\n')
