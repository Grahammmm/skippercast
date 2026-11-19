"""R5b: trace the eligible selection into a disjoint, unpublished ft-v2 pair."""
from collections import defaultdict
import contextlib
from importlib.util import module_from_spec, spec_from_file_location
import json

from skippercast.paths import repo_root
from skippercast.platform import depth_contours as dc
from skippercast.platform.contracts import atomic_json, load_catalogs, load_region
from skippercast.relief import receipts

UPSTREAM = ('select', 'mosaic:public')
TARGET = 'layers/contours'
SCRIPT = 'scripts/build_depth_contours.py'
CODE_FILES = (SCRIPT, 'scripts/preflight_native_grid.py', 'skippercast.platform.depth_contours',
              'skippercast.platform.contracts')
MOSAIC = 'mosaic/public'


def producer():
    spec = spec_from_file_location('build_depth_contours', repo_root() / SCRIPT)
    if spec is None or spec.loader is None:
        raise receipts.ReceiptError('contour producer not found in the checkout')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def attested(ctx, key, relative):
    if not any(r['path'] == relative for r in ctx.upstream[key]['outputs']):
        raise receipts.ReceiptError(f'{key} does not attest {relative}')
    return ctx.region.dir / relative


def read(path):
    return json.loads(path.read_bytes())


def plan(ctx):
    root = repo_root()
    if (ctx.region.dir / TARGET).resolve().is_relative_to(root.resolve()):
        raise receipts.ReceiptError('contour output must be outside the work tree')
    tool = producer()
    region = load_region(ctx.region.id, root)
    _, sources = load_catalogs(root)
    table = attested(ctx, 'select', 'select/sources.json')
    table_doc = read(table)
    rows = table_doc['sources']
    by_id = {r['id']: r for r in rows}
    native = read(attested(ctx, 'select', 'select/native.json'))
    if (table_doc['scope'] != 'public' or table_doc['schema_version'] != 1 or len(by_id) != len(rows)
            or any(row != by_id.get(row['id']) for row in native)):
        raise receipts.ReceiptError('inconsistent public selection manifests')
    manifest_path = attested(ctx, 'mosaic.public', f'{MOSAIC}/manifest.json')
    manifest = read(manifest_path)
    config = root / 'regions' / ctx.region.id / 'region.json'
    if (manifest['segment'] != ctx.region.id or manifest['region_sha256'] != receipts.sha256_file(config)
            or manifest['source_table_sha256'] != receipts.sha256_file(table)
            or manifest['units'] != 'm' or manifest['value_convention'] != 'elevation_positive_up'
            or {r['id']: r['sha256'] for r in manifest['sources']} != {r['id']: r['sha256'] for r in rows}):
        raise receipts.ReceiptError('mosaic does not match the current region and source selection')
    for name in ('elevation', 'contributor'):
        relative = f'{MOSAIC}/{name}.tif'
        attested(ctx, 'mosaic.public', relative)
        pin = next(r['sha256'] for r in ctx.upstream['mosaic.public']['outputs'] if r['path'] == relative)
        if manifest['outputs'][name]['sha256'] != pin:
            raise receipts.ReceiptError(f'mosaic manifest does not pin {name}')
    inputs = [receipts.Input(config, 'region'), receipts.Input(root / 'catalog/sources.json', 'registry')]
    entries, refused = [], []
    mosaic_rows = {r['id']: r for r in manifest['sources']}
    input_pins = {r['path']: r['sha256'] for r in ctx.upstream['select']['inputs']}
    for row in rows:
        ident, tile = row['source_id'], row['id']
        reason = tool.public_refusal(ident, region, sources)
        if row['rights_class'] != 'public':
            reason = 'not a public selector row'
        if reason:
            refused.append({'source_id': ident, 'selection_id': tile, 'reason': reason})
            continue
        value = row['path']
        if not isinstance(value, str) or '://' in value or value.startswith('/vsi'):
            raise receipts.ReceiptError('expected a local TIFF')
        grid = table.parent / value
        if grid.is_relative_to('/mnt/privatevault') or grid.suffix.lower() not in ('.tif', '.tiff'):
            raise receipts.ReceiptError('expected an admitted local TIFF')
        grid = grid.resolve()
        if grid.is_relative_to('/mnt/privatevault'):
            raise receipts.ReceiptError('expected an admitted local TIFF')
        sidecar = grid.with_name('sidecar.json') if row.get('support_path') is not None else None
        side_pin = input_pins.get(ctx.region.record(sidecar)) if sidecar is not None else None
        if sidecar is not None and side_pin is None:
            raise receipts.ReceiptError(f'{ident}: select receipt does not bind the original sidecar')
        # A normalised grid's support raster says which cells are measured rather than interpolated; native
        # detail is granted only there, so the raster must be a local file pinned by the selection row.
        support = None
        if sidecar is not None:
            value = row['support_path']
            support_pin = row.get('support_sha256')
            if (not isinstance(value, str) or '://' in value or value.startswith('/vsi')
                    or not isinstance(support_pin, str) or not dc.SHA256.fullmatch(support_pin)):
                raise receipts.ReceiptError(f'{ident}: selection row does not pin a local support raster')
            support = (table.parent / value).resolve()
            if support.is_relative_to('/mnt/privatevault') or not support.is_file():
                raise receipts.ReceiptError(f'{ident}: expected an admitted local support raster')
            if receipts.sha256_file(support) != support_pin:
                raise receipts.ReceiptError(f'{ident}: support raster hash differs from the selection')
        # R4 retains the winning code but runs on mixed source vertical references. Do not admit
        # edited offsets or reinterpret its samples as one shared vertical datum.
        if row['vertical_offset_m'] != 0 or mosaic_rows[tile]['vertical_offset_m'] != 0:
            raise receipts.ReceiptError(f'{ident}: unexpected mosaic vertical offset')
        inputs.append(receipts.Input(grid, f'grid:{tile}'))
        if sidecar is not None and support is not None:
            inputs.append(receipts.Input(sidecar, f'sidecar:{tile}'))
            inputs.append(receipts.Input(support, f'support:{tile}'))
        entries.append((row, grid, sidecar, side_pin, support))
    ctx.contour_job = (tool, region, sources, entries, {r['id'] for r in native}, manifest, manifest_path.parent)
    return receipts.Plan(inputs, {'set': 'ft-v2', 'refused_sources': refused})


def mosaic_samples(elevation, contributor, feather):
    """A winning contributor cannot attribute values changed using its neighbours."""
    import numpy as np
    from scipy.ndimage import distance_transform_edt

    values = elevation.read(1, masked=True).filled(np.nan)
    codes = contributor.read(1, masked=True).filled(0)
    valid = np.isfinite(values) & (values < 0) & (values >= -3000) & (codes > 0)
    if feather:
        seams = np.zeros(codes.shape, dtype=bool)
        for a, b in ((np.s_[:, :-1], np.s_[:, 1:]), (np.s_[:-1, :], np.s_[1:, :])):
            edge = (codes[a] != codes[b]) & (codes[a] > 0) & (codes[b] > 0)
            seams[a] |= edge
            seams[b] |= edge
        if seams.any():
            valid &= (distance_transform_edt(~seams) + 0.5) * dc.V2_CELL_M >= feather
    return values, codes, valid


def native_blocks(tool, grid, lattice, offset, block):
    """Whole native-water blocks only, read in strips; no resampling or infilling."""
    import numpy as np
    from rasterio.windows import Window, from_bounds

    col, row, n = offset
    _, _, width, height = lattice
    coverage = from_bounds(*grid.bounds, transform=block)
    x, y = max(0, int(np.floor(coverage.col_off))), max(0, int(np.floor(coverage.row_off)))
    end_x = min(width, int(np.ceil(coverage.col_off + coverage.width)))
    end_y = min(height, int(np.ceil(coverage.row_off + coverage.height)))
    if x >= end_x:
        return
    for top in range(y, end_y, tool.STRIP_BLOCKS):
        bottom = min(top + tool.STRIP_BLOCKS, end_y)
        h, w = bottom - top, end_x - x
        window = Window(col + x * n, row + top * n, w * n, h * n)
        data = grid.read(1, window=window, boundless=True, masked=True).astype('float64').filled(np.nan)
        data[(data >= 0) | (data < -3000)] = np.nan
        yield np.s_[top:bottom, x:end_x], -data.reshape(h, n, w, n).mean(axis=(1, 3)) * dc.FEET_PER_M


def trace(job):
    import numpy as np
    from pyproj import Transformer
    from rasterio.transform import Affine

    tool, region, sources, entries, native_ids, manifest, mosaic = job
    with tool.open_geotiff(mosaic / 'elevation.tif', normalized=True) as e, \
            tool.open_geotiff(mosaic / 'contributor.tif', normalized=True) as c:
        block, crs = e.transform, e.crs
        height, width = e.shape
        if (crs is None or not crs.is_projected or crs.linear_units != 'metre'
                or (block.a, block.b, block.d, block.e) != (dc.V2_CELL_M, 0, 0, -dc.V2_CELL_M)
                or (crs, block, e.shape) != (c.crs, c.transform, c.shape)
                or c.dtypes != ('uint16',) or e.dtypes != ('float32',)):
            raise ValueError('mosaic elevation and contributor must share the 10 m projected lattice')
        if height * width > tool.preflight.MAX_PIXELS:
            raise ValueError('contour mosaic exceeds the cell budget; use a smaller region window')
        feather = manifest['seam_feather']['feather_m']
        if not 0 <= feather <= 200:
            raise ValueError('invalid mosaic seam feather')
        values, codes, valid = mosaic_samples(e, c, feather)
    code_by_id = {r['id']: r['code'] for r in manifest['sources']}
    if len(set(code_by_id.values())) != len(code_by_id) or not set(np.unique(codes)) <= {0, *code_by_id.values()}:
        raise ValueError('mosaic contributor codes are missing or ambiguous')
    lattice = (block.c, block.f, width, height)
    xy = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
    inside = tool.inside_blocks(xy, lattice, region['bounds'], dc.V2_CELL_M)
    depth = np.full((height, width), np.nan, dtype='float32')
    owner = np.full(depth.shape, -1, dtype='int32')
    identities, aligned, fallback = {}, {}, []
    code_to_owner = {code_by_id[row['id']]: i for i, (row, *_paths) in enumerate(entries)}
    for i, (row, path, sidecar, side_pin, support) in enumerate(entries):
        ident = row['source_id']
        source = sources[ident]
        datum = source.get('vertical_datum')
        if receipts.sha256_file(path) != row['sha256']:
            raise ValueError(f'{ident}: selected grid hash changed')
        if support is not None and receipts.sha256_file(support) != row['support_sha256']:
            raise ValueError(f'{ident}: selected support raster hash changed')
        with tool.open_geotiff(path, normalized=True) as grid:
            original, declared = row['sha256'], datum
            if sidecar is not None:
                if receipts.sha256_file(sidecar) != side_pin:
                    raise ValueError(f'{ident}: selected sidecar hash changed')
                original, _, declared = tool.normalized_identity(ident, grid, sidecar, datum)
            if row['vertical_datum'] not in ('unstated', declared):
                raise ValueError(f'{ident}: selected datum differs from the reviewed original')
            identities[i] = original, declared or dc.UNVERIFIED_DATUM
            if row['id'] not in native_ids:
                continue
            try:
                if (grid.crs != crs or grid.transform.b or grid.transform.d or grid.transform.a <= 0
                        or grid.transform.e >= 0 or row['value_convention'] != 'elevation_positive_up'):
                    raise ValueError('not on the mosaic lattice')
                offset = tool.native_offsets(grid, lattice, dc.V2_CELL_M)
            except ValueError:
                fallback.append({'source_id': ident, 'selection_id': row['id'], 'reason': 'native grid not aligned to mosaic'})
                continue
            aligned[i] = offset, grid.res[0]
            for part, data in native_blocks(tool, grid, lattice, offset, block):
                take = (owner[part] < 0) & inside[part] & np.isfinite(data)
                owner[part][take], depth[part][take] = i, data[take]
    native_water = owner >= 0
    # Refused contributors cannot create a contour or affect an admitted tile at a feathered seam.
    lookup = np.full(65536, -1, dtype='int32')
    for code, i in code_to_owner.items():
        lookup[code] = i
    eligible = lookup[codes]
    gaps = ~native_water & inside & valid & (eligible >= 0)
    owner[gaps], depth[gaps] = eligible[gaps], -values[gaps] * dc.FEET_PER_M
    runs, listed = defaultdict(list), {}
    for i in np.unique(owner[owner >= 0]):
        row, path, _, _, support = entries[i]
        ident, (original, datum) = row['source_id'], identities[i]
        src = sources[ident]
        entry = listed.setdefault(ident, {'source_id': ident, 'name': src['name'], 'url': src['documentation_url'],
                                          'attribution': src['rights']['attribution'], 'survey_date': str(src['survey_year']),
                                          'vertical_datum': datum, 'native_cell_m': None, 'supported_blocks': 0,
                                          'original_sha256s': set()})
        if datum != entry['vertical_datum']:
            raise ValueError(f'{ident}: selected tiles disagree on vertical datum')
        mine = owner == i
        entry['supported_blocks'] += int(mine.sum())
        entry['original_sha256s'].add(original)
        detail, reviewed = None, src.get('native_resolution_m')
        if i in aligned and type(reviewed) in (int, float) and 0 < reviewed <= dc.V2_NATIVE_MAX_CELL_M:
            offset, cell = aligned[i]
            if cell <= dc.V2_NATIVE_MAX_CELL_M and (native_cover := mine & native_water).any():
                with tool.open_geotiff(path, normalized=True) as grid, contextlib.ExitStack() as stack:
                    measured = stack.enter_context(tool.open_geotiff(support, normalized=True)) if support is not None else None
                    detail = tool.v2_native(grid, offset, native_cover, None, measured)
                # Native detail only where measured support exists; claim the cell size only if some did.
                if detail is not None and detail[2] is not None:
                    entry['native_cell_m'] = max(cell, reviewed, entry['native_cell_m'] or 0)
        rr, = np.nonzero(mine.any(axis=1))
        cc, = np.nonzero(mine.any(axis=0))
        y, x = rr[0], cc[0]
        box = np.s_[y:rr[-1] + 1, x:cc[-1] + 1]
        own = np.where(mine[box], depth[box], np.nan)
        for d, start, stop, _, lines in tool.v2_contour_runs(own, block @ Affine.translation(x, y), detail, xy, None):
            runs[ident, d, start, stop].extend(lines)
    if not listed:
        raise receipts.Held('no eligible source contributes valid water inside the region')
    features = []
    for (ident, d, start, stop), lines in runs.items():
        entry = listed[ident]
        suffix = '-native' if start >= dc.V2_NATIVE_ZOOM else '-overview' if stop is not None else ''
        features.append({'type': 'Feature', 'id': f'{ident}-{d}ft{suffix}',
                         'geometry': {'type': 'MultiLineString', 'coordinates': lines},
                         'properties': {'kind': 'contour', 'source_id': ident, 'depth_ft': d, 'minzoom': start,
                                        'index': d in dc.V2_INDEX_FT, 'estimated': True,
                                        'survey_date': entry['survey_date'], 'vertical_datum': entry['vertical_datum'],
                                        **({'maxzoom': stop} if stop is not None else {})}})
    for entry in listed.values():
        hashes = sorted(entry.pop('original_sha256s'))
        entry['sha256'] = hashes[0]
        if len(hashes) > 1:
            entry['original_sha256s'] = hashes
    provenance = {'region_id': region['id'], 'bounds': region['bounds'], 'units': 'ft', 'set': dc.FT_V2,
                  'intervals': dc.v2_intervals(), 'index_depths_ft': list(dc.V2_INDEX_FT),
                  'shelf_limit_ft': dc.V2_SHELF_LIMIT_FT, 'cell_m': dc.V2_CELL_M, 'horizontal_crs': str(crs),
                  'features': len(features), 'sources': list(listed.values()), 'coordinate_decimals': tool.V2_DECIMALS,
                  'sources_omitted': dc.omitted_sources(region, sources, listed),
                  'method': 'Native water blocks first, then attributed 10 m mosaic gaps outside blended seams.',
                  'limitations': 'Estimated display contours. Not for navigation. No datum conversion.'}
    return {'type': 'FeatureCollection', 'schema_version': dc.SCHEMA_VERSION, 'features': features,
            'provenance': provenance}, {'native_fallbacks': fallback, 'mosaic_gap_blocks': int(gaps.sum())}


def build(ctx, out):
    _, region, sources, entries, *_ = ctx.contour_job
    if not entries:
        raise receipts.Held('no selected source is cleared and bound for public contours')
    try:
        collection, metrics = trace(ctx.contour_job)
    except SystemExit as exc:
        raise receipts.ReceiptError(str(exc)) from None
    overview = dc.overview_contours(collection)
    for filename, value, budget in (('contours.geojson', collection, dc.MAX_BYTES),
                                     ('contours-overview.geojson', overview, dc.OVERVIEW_MAX_BYTES)):
        dc.check_contours(value, region, sources)
        if atomic_json(out / filename, value)['bytes'] > budget:
            raise receipts.ReceiptError(f'{filename} exceeds its byte budget')
    return metrics
