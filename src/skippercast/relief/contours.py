"""R5b: trace the eligible selection into a disjoint, unpublished ft-v2 pair."""
from collections import Counter, defaultdict
import contextlib
from importlib.util import module_from_spec, spec_from_file_location
import json
import logging
import math

from skippercast.paths import repo_root
from skippercast.platform import depth_contours as dc
from skippercast.platform.contracts import atomic_json, load_catalogs, load_region, owner_display_cleared
from skippercast.relief import package, receipts, render_config

UPSTREAM = ('select', 'mosaic:public')
TARGET = 'layers/contours'
SCRIPT = 'scripts/build_depth_contours.py'
CODE_FILES = (SCRIPT, 'scripts/preflight_native_grid.py', 'skippercast.platform.depth_contours',
              'skippercast.platform.contracts', 'skippercast.relief.package', 'skippercast.style',
              'skippercast.relief.render_config')
MOSAIC = 'mosaic/public'

# Morro Bay's measured 10 m lattice is 130,452,268 cells. Larger regions that
# exceed this cap need to be split or use a future windowed trace.
CONTOUR_MAX_CELLS = 160_000_000
# A 7.68M-cell trace with two contributors and a feathered seam used ~57 B/cell
# of peak RSS above baseline; round up with at least 25% headroom.
TRACE_BYTES_PER_CELL = 80
MEMORY_FRACTION = 0.5


def _mem_available():
    """Return Linux MemAvailable in bytes, or None if it cannot be read."""
    try:
        with open('/proc/meminfo', encoding='ascii') as meminfo:
            for line in meminfo:
                if line.startswith('MemAvailable:'):
                    value, unit = line.split()[1:]
                    kib = int(value)
                    return kib * 1024 if unit == 'kB' and kib >= 0 else None
    except (OSError, ValueError):
        pass
    return None


def _admit_trace(cells):
    if cells > CONTOUR_MAX_CELLS:
        raise ValueError('contour mosaic exceeds the cell budget; use a smaller region window '
                         f'({cells:,} cells > {CONTOUR_MAX_CELLS:,} cells)')
    need = cells * TRACE_BYTES_PER_CELL
    available = _mem_available()
    if available is None:
        raise receipts.Held('contour trace cannot determine MemAvailable from /proc/meminfo')
    if need > MEMORY_FRACTION * available:
        raise receipts.Held(f'contour trace needs ~{need / 2**30:.2f} GiB, '
                            f'only {available / 2**30:.2f} GiB available '
                            f'({MEMORY_FRACTION:.0%} usable for the trace)')
    return available


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


def _metadata_refusal(source):
    if package._MBARI.search(package._lineage(source)):
        return 'MBARI lineage'
    rights = source.get('rights') or {}
    license_id = rights.get('license')
    if not isinstance(license_id, str) or not license_id.strip():
        return 'licence mismatch'
    # Same rule as the release policy (package._UNKNOWN_LICENSE): an unreviewed licence term is accepted only
    # where the owner's recorded G display decision clears the source.
    if license_id.strip().lower() in package._UNKNOWN_LICENSE and not owner_display_cleared(rights):
        return 'licence mismatch'
    return None


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
        reason = tool.public_refusal(ident, region, sources, selected=True)
        if row['rights_class'] != 'public':
            reason = 'not a public selector row'
        elif reason is None:
            reason = _metadata_refusal(sources[ident])
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
    version, tokens = render_config.resolve_style(ctx.region.id)
    params = {'set': dc.FT_V2, 'refused_sources': refused}
    ctx.contour_view = tokens.view('contours') if tokens is not None else None
    if ctx.contour_view is not None:
        digest = ctx.contour_view.digest('contours')
        entry = read(render_config.repo_root() / 'style/index.json')['versions'][version]
        ctx.contour_style = {'built_with': version, 'sha256': entry['sha256'], 'contours': digest}
        params.update(set=dc.FT_V3, contours=digest)
    return receipts.Plan(inputs, params)


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
        cells = height * width
        _admit_trace(cells)
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
                                          'attribution': src['rights']['attribution'], 'survey_date': dc.selected_survey_date(src),
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
                  'sources_omitted': dc.omitted_selected_sources({row['source_id'] for row, *_ in entries}, sources, listed),
                  'method': 'Native water blocks first, then attributed 10 m mosaic gaps outside blended seams.',
                  'limitations': 'Estimated display contours. Not for navigation. No datum conversion.'}
    return {'type': 'FeatureCollection', 'schema_version': dc.SCHEMA_VERSION, 'features': features,
            'provenance': provenance}, {'native_fallbacks': fallback, 'mosaic_gap_blocks': int(gaps.sum())}


def trace_v3(job, view):
    tool, region, sources, entries, native_ids, _, _ = job
    listed, features, footprints = {}, [], {}
    for i, (row, path, sidecar, side_pin, support) in enumerate(entries):
        ident = row['source_id']
        source = sources[ident]
        convention = row['value_convention']
        if convention not in ('elevation_positive_up', 'depth_positive_down'):
            raise ValueError(f'{ident}: unknown value_convention {convention!r}')
        if receipts.sha256_file(path) != row['sha256']:
            raise ValueError(f'{ident}: selected grid hash changed')
        with tool.open_geotiff(path, normalized=True) as grid, contextlib.ExitStack() as stack:
            original, datum = row['sha256'], source.get('vertical_datum')
            measured = None
            if sidecar is not None:
                if receipts.sha256_file(sidecar) != side_pin or receipts.sha256_file(support) != row['support_sha256']:
                    raise ValueError(f'{ident}: selected sidecar or support hash changed')
                original, _, datum = tool.normalized_identity(ident, grid, sidecar, datum)
                tool.verify_support_binding(ident, sidecar, support)
                measured = stack.enter_context(tool.open_geotiff(support, normalized=True))
            if row['vertical_datum'] not in ('unstated', datum):
                raise ValueError(f'{ident}: selected datum differs from the reviewed original')
            common = {'source_id': ident, 'survey_date': dc.selected_survey_date(source),
                      'vertical_datum': datum or dc.UNVERIFIED_DATUM}
            certified = (row['id'] in native_ids and row.get('support_class_cap') == 3
                         and (row.get('max_zoom') or 0) >= 16)
            # The selection/sidecar checks above bind the original identity. A normalized
            # tile's resolution describes its output pixels, not the original sampling.
            map_key = 'native_resolution_m_by_original_sha256'
            if map_key in source:
                reviewed = source[map_key]
                native = (reviewed.get(original) if isinstance(reviewed, dict)
                          and 'native_resolution_m' not in source else None)
            else:
                native = source.get('native_resolution_m')
            if not (isinstance(native, (int, float)) and not isinstance(native, bool) and 0 < native < math.inf):
                logging.getLogger(__name__).warning(
                    '%s/%s: missing or invalid reviewed original native resolution; withholding ft-v3 contours',
                    ident, row['id'])
                native = None
            lines = list(tool.v3_grid(grid, region, view, common, native, support=measured, certified=certified,
                                      positive_down=convention == 'depth_positive_down'))
            # Every traceable tile of a survey adds its measured water to the survey's outline, even one that crosses
            # no contour level; a tile whose contours are withheld adds nothing.
            area = tool.v3_measured_support(grid, region, view, native, support=measured, certified=certified,
                                            positive_down=convention == 'depth_positive_down')
            if area is not None:
                footprints.setdefault(ident, []).append((common['vertical_datum'], area))
            if not lines:
                continue
            entry = listed.setdefault(ident, {**common, 'name': source['name'], 'url': source['documentation_url'],
                                              'attribution': source['rights']['attribution'], 'hashes': set(),
                                              'native_cell_m': grid.res[0]})
            if entry['vertical_datum'] != common['vertical_datum']:
                raise ValueError(f'{ident}: selected tiles disagree on vertical datum')
            entry['hashes'].add(original)
            entry['native_cell_m'] = max(entry['native_cell_m'], grid.res[0])
            for feature in lines:
                feature['id'] += f'-{i}'
            features.extend(lines)
    for entry in listed.values():
        hashes = sorted(entry.pop('hashes'))
        entry['sha256'] = hashes[0]
        if len(hashes) > 1:
            entry['original_sha256s'] = hashes
    omitted = dc.omitted_selected_sources({row['source_id'] for row, *_ in entries}, sources, listed)
    # Only surveys that draw contours bound them: a withheld or silent survey's water is not where they continue.
    edges = [({key: listed[ident][key] for key in ('source_id', 'survey_date', 'vertical_datum')},
              [area for datum, area in areas if datum == listed[ident]['vertical_datum']])
             for ident, areas in footprints.items() if ident in listed]
    features.extend(tool.v3_survey_edges(region, view, edges))
    return tool.v3_collection(region, view, features, list(listed.values()), omitted)


def _json_bytes(value):
    # Same compact UTF-8 encoding as atomic_json, excluding the final LF.
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode())


def _line_group(feature):
    p = feature['properties']
    # Keep distinct zoom ranges even if contributors to one tier turn off at
    # different zooms (e.g. only some have an eligible finer tier).
    return p['source_id'], p['tier'], p['depth_ft'], p['minzoom'], p.get('maxzoom')


def _line_counts(document):
    counts = Counter()
    for feature in document['features']:
        if feature['properties'].get('kind') == 'contour':
            geometry = feature['geometry']
            counts[_line_group(feature)] += (1 if geometry['type'] == 'LineString'
                                             else len(geometry['coordinates']))
    return counts


def _with_features(document, features):
    return {**document, 'features': features, 'provenance': {**document['provenance'], 'features': len(features)}}


def _budget_error(filename, size, budget):
    return receipts.ReceiptError(f'{filename} exceeds its byte budget ({size} bytes, budget {budget} bytes)')


_PAIR_NAMES = ('contours.geojson', 'contours-overview.geojson')
# Regions whose ft-v3 pair may be fitted to the byte budget by retaining whole estimated lines. Morro Bay
# was first; the Central Coast release regions trace lidar-dense shelves (Cambria: 36 MB against a 3 MB
# budget) and otherwise stop the whole release chain at `contours`. Any other region still fails closed.
WHOLE_LINE_BUDGET_REGIONS = frozenset({
    'morro-bay', 'big-sur-coast', 'cambria-san-simeon', 'monterey-point-sur',
    'point-arguello-conception', 'santa-cruz-monterey-bay', 'south-big-sur-san-simeon'})


def _compact_morro(full, overview, budgets, sizes, view, drop_groups=False):
    """Reserve one original part per uncovered group before preferring wider parts.

    With ``drop_groups`` (the Central Coast regions) a group whose shortest whole line no longer fits is
    left out instead of failing the stage; Morro Bay keeps the refusal. Dropped groups show in the
    retention metrics.
    """
    # The ft-v3 projection keeps the original feature objects, unmodified.
    visible = {id(feature) for feature in overview['features']}
    pier = view['pier_view']['contours_tier']
    protected, candidates = {}, defaultdict(list)
    covered = set()
    overflow = next(_budget_error(name, size, cap) for name, size, cap in zip(_PAIR_NAMES, sizes, budgets)
                    if size > cap)
    for i, feature in enumerate(full['features']):
        p, geometry = feature['properties'], feature['geometry']
        if p.get('kind') == 'survey-edge' and geometry['type'] in ('LineString', 'MultiLineString'):
            # Where the measured grids stop is kept whole, like a protected contour, never thinned to fit.
            protected[i] = feature
            continue
        if p.get('kind') != 'contour' or geometry['type'] not in ('LineString', 'MultiLineString'):
            raise receipts.ReceiptError(f'{overflow}; cannot compact protected feature {feature.get("id")}')
        group = _line_group(feature)
        if (p.get('estimated') is not True or p['tier'] == pier or 'provenance' in p
                or geometry['type'] != 'MultiLineString'):
            protected[i] = feature
            covered.add(group)
            continue
        overhead = _json_bytes({**feature, 'geometry': {**geometry, 'coordinates': []}})
        for j, line in enumerate(geometry['coordinates']):
            xs, ys = zip(*line)
            span = max(max(xs) - min(xs), max(ys) - min(ys))
            candidates[group].append((-span, feature['id'], j, i, overhead + _json_bytes(line)))

    # Low-zoom groups first. Keep original feature order in the serialized pair.
    ranked = sorted((sorted(parts) for group, parts in candidates.items() if group not in covered),
                    key=lambda parts: (id(full['features'][parts[0][3]]) not in visible, parts[0][:4]))
    if not ranked and not protected:
        raise receipts.ReceiptError(f'{overflow}; no original contour lines to retain')

    # Start from exact protected output sizes; each new feature adds its encoded
    # bytes, the array comma (unless first), and any growth in the count field.
    floor_full = _with_features(full, list(protected.values()))
    floor_pair = (floor_full, dc.overview_contours(floor_full))
    used = [_json_bytes(document) + 1 for document in floor_pair]
    counts = [len(document['features']) for document in floor_pair]

    def check(index, group):
        if used[index] > budgets[index]:
            raise receipts.ReceiptError(f'{_budget_error(_PAIR_NAMES[index], used[index], budgets[index])}; '
                                        f'cannot retain group {group}')

    for k, document in enumerate(floor_pair):
        if used[k] > budgets[k]:
            groups = list(dict.fromkeys(_line_group(f) if f['properties'].get('kind') == 'contour' else f.get('id')
                                        for f in document['features']))
            check(k, f'protected {groups}')

    choices = []
    for parts in ranked:
        least = min(parts, key=lambda part: part[-1])
        _, _, _, i, cost = least
        indices = (1, 0) if id(full['features'][i]) in visible else (0,)
        adds = {k: cost + int(counts[k] > 0) + len(str(counts[k] + 1)) - len(str(counts[k])) for k in indices}
        if drop_groups and any(used[k] + adds[k] > budgets[k] for k in indices):
            continue  # this group's shortest whole line no longer fits: drop it (the retention metrics list it)
        for k in indices:
            used[k] += adds[k]
            counts[k] += 1
            check(k, _line_group(full['features'][i]))
        choices.append((parts, least, indices))
    if not choices and not protected:
        raise receipts.ReceiptError(f'{overflow}; no contour group fits the budget')

    # Share the remaining bytes among the groups, without spending a later
    # group's reserved minimum. Stable span/ID/part order breaks ties.
    remaining = [cap - size for cap, size in zip(budgets, used)]
    pending = [len(choices), sum(1 in indices for _, _, indices in choices)]
    for parts, least, indices in choices:
        ceiling = least[-1] + min(remaining[k] // pending[k] for k in indices)
        _, _, j, i, cost = next(part for part in parts if part[-1] <= ceiling)
        for k in indices:
            remaining[k] -= cost - least[-1]
            pending[k] -= 1
        feature = full['features'][i]
        geometry = feature['geometry']
        protected[i] = {**feature, 'geometry': {**geometry, 'coordinates': [geometry['coordinates'][j]]}}
    return _with_features(full, [protected[i] for i in sorted(protected)])


def _retention_metrics(before, after):
    original, retained = _line_counts(before), _line_counts(after)
    fields = ('source_id', 'tier', 'depth_ft', 'minzoom', 'maxzoom')
    return {'original_lines': sum(original.values()), 'retained_lines': sum(retained.values()),
            'original_groups': len({key[:3] for key in original}),
            'retained_groups': len({key[:3] for key in retained}),
            'dropped_lines_by_group': [dict(zip(fields, key), dropped=count - retained[key])
                                       for key, count in original.items() if count != retained[key]]}


def _selected_pair(collection, region, view):
    """The serializer boundary shared by the stage and the read-only replay."""
    overview = dc.overview_contours(collection)
    budgets = dc.size_budgets(collection)
    metrics = {}
    if (view is not None and region.get('id') in WHOLE_LINE_BUDGET_REGIONS
            and collection['provenance'].get('set') == dc.FT_V3):
        original = (collection, overview)
        sizes = tuple(_json_bytes(document) + 1 for document in original)
        compacted = any(size > cap for size, cap in zip(sizes, budgets))
        if compacted:
            collection = _compact_morro(collection, overview, budgets, sizes, view,
                                        drop_groups=region.get('id') != 'morro-bay')
            overview = dc.overview_contours(collection)
        metrics['compacted'] = compacted
        for name, before, after in zip(('full', 'overview'), original, (collection, overview)):
            metrics[name] = _retention_metrics(before, after)
    return collection, overview, budgets, metrics


def build(ctx, out):
    _, region, sources, entries, *_ = ctx.contour_job
    if not entries:
        raise receipts.Held('no selected source is cleared and bound for public contours')
    try:
        if ctx.contour_view is None:
            collection, metrics = trace(ctx.contour_job)
        else:
            collection = trace_v3(ctx.contour_job, ctx.contour_view)
            metrics = {'style': ctx.contour_style}
    except SystemExit as exc:
        raise receipts.ReceiptError(str(exc)) from None
    collection, overview, budgets, size_metrics = _selected_pair(collection, region, ctx.contour_view)
    metrics.update(size_metrics)
    selected = {row['source_id'] for row, *_ in entries}
    for filename, value, budget in zip(_PAIR_NAMES, (collection, overview), budgets):
        dc.check_selected_contours(value, region, sources, selected, view=ctx.contour_view)
        size = atomic_json(out / filename, value)['bytes']
        if size > budget:
            raise _budget_error(filename, size, budget)
    return metrics
