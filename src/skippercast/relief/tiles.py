"""R5a: build the public relief archive and coverage sidecar."""
from contextlib import ExitStack
from importlib.util import module_from_spec, spec_from_file_location
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from skippercast.paths import repo_root
from skippercast.relief import mosaic, receipts, render_config
from skippercast.style import parity

SCOPES = ('public',)
UPSTREAM = ('select', 'mosaic:public')
# Give each layer its own atomic target so a rebuild never replaces sibling layers.
TARGET = 'layers/public/tiles'
SCRIPT = 'scripts/build_bathy_tiles.py'
CODE_FILES = (SCRIPT, 'skippercast.relief.mosaic', 'skippercast.relief.pmtiles_v3',
              'skippercast.relief.nearshore', 'skippercast.style', 'skippercast.style.parity',
              'skippercast.relief.render_config')
CHUNK = 512
VARIANT = 'medium'  # MB-01's fixed Deep ramp with medium relief


def elevation(ctx):
    return mosaic.upstream_file(ctx, 'mosaic.public', ctx.region.dir / 'mosaic/public/elevation.tif')


add_arguments = mosaic.add_region_config


def plan(ctx):
    native = mosaic.selected(ctx, 'native.json')
    inputs = [receipts.Input(mosaic.region_config(ctx), 'region'), receipts.Input(elevation(ctx), 'elevation'),
              receipts.Input(native, 'native')]
    inputs.extend(item for item, _ in mosaic.raster_refs(native, mosaic.read_json(native)))
    version, tokens = render_config.resolve_style(ctx.region.id)
    params = {'ramp': 'deep-fixed-v1', 'variant': VARIANT}
    sha = None
    if tokens is not None:
        params = {'engine': 'nearshore', 'baked': tokens.digest('baked')}
        index = mosaic.read_json(render_config.repo_root() / 'style/index.json')
        sha = index['versions'][version]['sha256']
    # Use the same verified tokens in build, even if the default moves after planning.
    ctx.tiles_style = (version, tokens, sha)
    return receipts.Plan(inputs, params)


def build(ctx, out):
    version, tokens, sha = ctx.tiles_style
    if tokens is None:
        return _legacy(ctx, out)
    from skippercast.relief.nearshore import ENGINE_EPOCH

    region = mosaic.read_json(mosaic.region_config(ctx))
    if region['id'] != ctx.region.id:
        raise receipts.ReceiptError('region config id differs from the requested region')
    native = mosaic.selected(ctx, 'native.json')
    rows = mosaic.read_json(native)
    mosaic.verify_rasters(mosaic.raster_refs(native, rows))
    cells = _render(elevation(ctx), native, rows, region['bounds'], out, ctx.region.id, tokens.view('baked'))
    return {'clip_bounds': region['bounds'], 'clip_status': 'applied', 'cell_m_by_grid': cells,
            'style': {'built_with': version, 'sha256': sha, 'baked': tokens.digest('baked')},
            'engine_digest': parity.engine_digest(), 'engine_epoch': ENGINE_EPOCH,
            'runtime': parity.engine_runtime()}


def _legacy(ctx, out):
    region = mosaic.read_json(mosaic.region_config(ctx))
    if region['id'] != ctx.region.id:
        raise receipts.ReceiptError('region config id differs from the requested region')
    native = mosaic.selected(ctx, 'native.json')
    rows = mosaic.read_json(native)
    mosaic.verify_rasters(mosaic.raster_refs(native, rows))
    help_text = mosaic.run_tool(SCRIPT, '--help', capture_output=True, text=True).stdout
    clip = '--clip-bounds' in help_text
    args = ['--source', elevation(ctx), '--output', out / 'relief.pmtiles', '--coverage-json', out / 'coverage.json',
            '--label', ctx.region.id, '--variant', VARIANT]
    if rows:  # The legacy reader rejects an empty list; the mosaic can supply background on its own.
        args.extend(('--native-manifest', native))
    if clip:
        args.extend(('--clip-bounds', *region['bounds']))
    else:
        # Before DL-3 the builder has no per-cell certification gate. Never request z16+ on it.
        args.extend(('--maxzoom', 15))
    mosaic.run_tool(SCRIPT, *args, cwd=native.parent)
    for filename in ('relief.pmtiles', 'coverage.json'):
        if not (out / filename).is_file():
            raise receipts.ReceiptError(f'tiles did not produce {filename}')
    return {'clip_bounds': region['bounds'] if clip else None,
            'clip_status': 'applied' if clip else 'builder has no --clip-bounds; capped at z15'}


def _builder():
    spec = spec_from_file_location('build_bathy_tiles', repo_root() / SCRIPT)
    if spec is None or spec.loader is None:
        raise receipts.ReceiptError('cannot load bathy tiles helper')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _depth(ds, window, builder, *, native=False, detail=None):
    import numpy as np

    data = ds.read(1, window=window, masked=True).astype('float32').filled(np.nan)
    if detail is not None:
        data[(detail.read(1, window=window, masked=True).filled(0) != 3) | (data < -builder.DETAIL_M)] = np.nan
    if native:
        data = builder.mask_native(data)
        data[data == builder.NODATA] = np.nan
    else:
        data[(data > builder.LAND_LIMIT_M) | (data == builder.NODATA)] = np.nan
    data[~np.isfinite(data)] = np.nan
    return data


def _aligned_depth(ds, transform, crs, shape, builder, *, native):
    import numpy as np
    from rasterio.transform import array_bounds
    from rasterio.warp import Resampling, reproject

    dest = np.full(shape, np.nan, dtype='float32')
    bounds = array_bounds(*shape, transform)
    window = builder.overlap_window(ds, bounds, crs, margin=2)
    if window is not None:
        reproject(_depth(ds, window, builder, native=native), dest,
                  src_transform=ds.window_transform(window), src_crs=ds.crs, src_nodata=np.nan,
                  dst_transform=transform, dst_crs=crs, dst_nodata=np.nan,
                  resampling=Resampling.bilinear, tolerance=0)
    return dest


def assemble_windows(ds, lower, baked, builder, *, native=False, detail=None, chunk=None):
    """Yield buffered engine windows and the original support mask of each output core."""
    import numpy as np
    from rasterio.transform import array_bounds
    from rasterio.windows import Window
    from skippercast.relief.nearshore import Nearshore

    chunk = CHUNK if chunk is None else chunk
    cell = ds.res[0]
    halo = math.ceil((baked['shading']['tile_buffer_m'] + (builder.FEATHER_M if lower else 0)) / cell)
    for y in range(0, ds.height, chunk):
        for x in range(0, ds.width, chunk):
            w, h = min(chunk, ds.width - x), min(chunk, ds.height - y)
            l, t = max(x - halo, 0), max(y - halo, 0)
            r, b = min(x + w + halo, ds.width), min(y + h + halo, ds.height)
            window = Window(l, t, r - l, b - t)
            z = _depth(ds, window, builder, native=native, detail=detail)
            core = np.s_[y - t:y - t + h, x - l:x - l + w]
            valid = np.isfinite(z[core]).copy()
            if not valid.any():
                continue
            if lower:
                # Include lower-tier elevations beyond the native dataset edges,
                # not just in its internal holes. The alpha mask is still native.
                left, top, right, bottom = x - halo, y - halo, x + w + halo, y + h + halo
                z = np.pad(z, ((t - top, bottom - b), (l - left, right - r)), constant_values=np.nan)
                window = Window(left, top, right - left, bottom - top)
                core = np.s_[halo:halo + h, halo:halo + w]
            transform = ds.window_transform(window)
            bounds = array_bounds(*z.shape, transform)
            sky_view_join = None
            if lower:
                elev = np.full(z.shape, builder.NODATA, dtype='float32')
                for other, is_native in lower:
                    coarser = _aligned_depth(other, transform, ds.crs, z.shape, builder, native=is_native)
                    if is_native:
                        elev, _ = builder.feather_tier(elev, coarser, cell)
                    else:
                        elev[np.isfinite(coarser)] = coarser[np.isfinite(coarser)]
                beneath = elev
                elev, weight = builder.feather_tier_with_weight(beneath, z, cell)
                if (weight[core] < 1).any():
                    # Only the sky-view factor joins. The feathered depth, piles,
                    # and native alpha still come from the original path.
                    sky_view_join = (Nearshore(np.where(beneath != builder.NODATA, beneath, np.nan),
                                              cell, bounds, baked), weight)
                z = np.where(elev != builder.NODATA, elev, np.nan)
            image = Nearshore(z, cell, bounds, baked, sky_view_join=sky_view_join)
            yield x, y, w, h, core, valid, image


def _bake(ds, lower, baked, outputs, builder, *, native=False, detail=None, chunk=None):
    """Bake at source spacing on a fixed grid. Halo elevations cannot add output support."""
    import numpy as np
    from rasterio.windows import Window
    from skippercast.relief.nearshore import to_bytes

    for x, y, w, h, core, valid, image in assemble_windows(
            ds, lower, baked, builder, native=native, detail=detail, chunk=chunk):
        for variant, output in outputs.items():
            rgba = np.zeros((4, h, w), dtype='uint8')
            rgba[:3, valid] = to_bytes(image.base(variant)[core])[valid].T
            rgba[3, valid] = 255
            output.write(rgba, window=Window(x, y, w, h))


def _tile(ds, z, x, y, builder):
    import numpy as np
    from rasterio.transform import array_bounds
    from rasterio.warp import Resampling, reproject

    transform, _ = builder.tile_grid(z, x, y, pad=0)
    size = builder.TILE
    window = builder.overlap_window(ds, array_bounds(size, size, transform), 'EPSG:3857', margin=2)
    if window is None:
        return None
    src = ds.read(window=window)
    if not src[3].any():
        return None
    dest = np.zeros((4, size, size), dtype='float32')
    mask = np.zeros((size, size), dtype='uint8')
    grid = dict(src_transform=ds.window_transform(window), src_crs=ds.crs,
                dst_transform=transform, dst_crs='EPSG:3857', tolerance=0)
    reproject(src[3], mask, **grid, resampling=Resampling.nearest)
    # RGB at invalid cells is already zero. Un-premultiply after bilinear resampling
    # to prevent black edges; a nearest validity mask forbids expansion into nodata.
    reproject(src, dest, **grid, resampling=Resampling.bilinear)
    valid = (mask != 0) & (dest[3] > 0)
    out = np.zeros((size, size, 4), dtype='uint8')
    out[valid, :3] = np.clip(np.rint(dest[:3, valid].T * (255 / dest[3, valid, None])), 0, 255).astype('uint8')
    out[valid, 3] = 255
    return out


def _mosaic_evidence(bg, background, z, x, y, builder):
    """Sample the masked mosaic at exact tile pixel centers, without blending."""
    import numpy as np
    from rasterio.warp import Resampling, reproject

    transform, _ = builder.tile_grid(z, x, y, pad=0)
    evidence = np.full((builder.TILE, builder.TILE), builder.NODATA, dtype=bg.dtype)
    reproject(bg, evidence, src_transform=background.transform, src_crs=background.crs,
              src_nodata=builder.NODATA, dst_transform=transform, dst_crs='EPSG:3857',
              dst_nodata=builder.NODATA, resampling=Resampling.nearest, tolerance=0)
    return evidence != builder.NODATA


def _render(source, manifest, rows, bounds, out, label, baked):
    import numpy as np
    import rasterio
    from rasterio.warp import transform_bounds
    from skippercast.relief.pmtiles_v3 import write_pmtiles

    builder = _builder()
    west, south, east, north = bounds
    if not (-180 <= west < east <= 180 and -85.05112878 <= south < north <= 85.05112878):
        raise ValueError('clip bounds must be ordered W S E N within Web Mercator')
    clip = transform_bounds('EPSG:4326', 'EPSG:3857', *bounds)
    tiles, by_zoom = {}, {}
    with TemporaryDirectory(dir=out) as scratch, ExitStack() as stack:
        scratch = Path(scratch)
        if rows:
            records = [dict(row) for row in rows]
            for row in records:
                for key in ('path', 'support_path'):
                    if row.get(key) is not None:
                        row[key] = str(manifest.parent / Path(row[key]).expanduser())
            resolved = scratch / 'native.json'
            resolved.write_bytes(receipts.canonical(records))
            sources = builder.load_native_manifest(resolved)
        else:
            sources = []
        background = stack.enter_context(rasterio.open(source))
        if background.crs.to_epsg() != 3310 or background.count != 1:
            raise ValueError('expected one mosaic band in EPSG:3310')
        bg = _depth(background, None, builder)
        bg[~np.isfinite(bg)] = builder.NODATA
        grids = [(None, background)] + [(s, stack.enter_context(rasterio.open(s['path']))) for s in sources]
        lower, products, cells = [], [], {}
        for i, (row, ds) in enumerate(grids):
            cell = ds.res[0]
            transform = ds.transform
            if (transform.a <= 0 or transform.e >= 0 or transform.b or transform.d
                    or not math.isclose(cell, ds.res[1], rel_tol=1e-6)):
                raise ValueError('nearshore expects north-up square cells')
            cells['mosaic' if row is None else f'native:{row["id"]}'] = cell
            cap = 13 if row is None else min(builder.source_maxzoom(row), baked.native_max_zoom(cell))

            profile = dict(driver='GTiff', width=ds.width, height=ds.height, count=4, dtype='uint8',
                           transform=ds.transform, crs=ds.crs, tiled=True, compress='deflate')
            variants = ['overview', 'closeup'] if row is not None and cell <= 2 and cap >= 15 else ['overview']
            paths = {v: scratch / f'{i}-{v}.tif' for v in variants}
            with ExitStack() as writers:
                outputs = {v: writers.enter_context(rasterio.open(path, 'w', **profile)) for v, path in paths.items()}
                _bake(ds, lower if row is not None else (), baked, outputs, builder, native=row is not None)
            if row is not None and cap > 15 and builder.has_support(row):
                # Certified zooms cannot use the feather's estimated elevations. This is the
                # same closeup style on a masked, unblended grid, not a third look.
                paths['certified'] = scratch / f'{i}-certified.tif'
                with rasterio.open(row['support_path']) as cert, rasterio.open(paths['certified'], 'w', **profile) as dst:
                    if (cert.count != 1 or cert.dtypes[0] != 'uint8' or cert.shape != ds.shape
                            or cert.crs != ds.crs or cert.transform != ds.transform):
                        raise ValueError('support grid must be aligned with native elevation and single-band uint8')
                    _bake(ds, (), baked, {'closeup': dst}, builder, native=True, detail=cert)
            lower.append((ds, row is not None))
            products.append((row, cap, {v: stack.enter_context(rasterio.open(path)) for v, path in paths.items()}))
        top = max(cap if 'certified' in images else min(cap, 15) for _, cap, images in products)
        for z in range(builder.MINZOOM, top + 1):
            use = [(row, images) for row, cap, images in products if z <= cap and (row is None) == (z <= 13)]
            bx, by = builder.tile_range(bounds, z)
            candidates = {}
            for row, images in use:
                overview = images['overview']
                image = images.get('certified') if z > 15 else images.get('closeup', overview) if z >= 15 else overview
                footprint = row['bounds'] if row else transform_bounds(overview.crs, 'EPSG:4326', *overview.bounds, densify_pts=21)
                xs, ys = builder.tile_range(footprint, z)
                for x in range(max(xs.start, bx.start), min(xs.stop, bx.stop)):
                    for y in range(max(ys.start, by.start), min(ys.stop, by.stop)):
                        candidates.setdefault((x, y), []).append((row, image))
            support, count, omitted = {}, 0, 0
            for (x, y), eligible in sorted(candidates.items()):
                region = builder.tile_core_region(z, x, y, clip)
                rgba = np.zeros((builder.TILE, builder.TILE, 4), dtype='uint8')
                measured = np.zeros(rgba.shape[:2], dtype=bool)
                native_core = np.zeros_like(measured)
                used = []
                has_evidence = _mosaic_evidence(bg, background, z, x, y, builder) if z > 13 else None
                if z > 15:
                    background_core, _ = builder.warp_window(bg, background.transform, background.crs, z, x, y, pad=0)
                for row, image in eligible:
                    tile = _tile(image, z, x, y, builder) if image is not None else None
                    pixels = region & (tile[..., 3] != 0) if tile is not None else np.zeros_like(measured)
                    if z > 15:
                        cert = np.zeros_like(measured, dtype='uint8')
                        raw, _ = builder.warp_native(row, z, x, y, 0, builder.DETAIL_M, certified=cert)
                        valid = region & (raw != builder.NODATA)
                        native_core |= valid
                        measured[valid] = (cert[valid] == 1) & pixels[valid]
                        pixels &= valid
                    if has_evidence is not None:
                        # Clip paint without changing the certification test above.
                        pixels &= has_evidence
                    if tile is not None and pixels.any():
                        rgba[pixels] = tile[pixels]
                        if row is not None:
                            used.append(row)
                if z > 15:
                    if not native_core.any():
                        continue
                    if ((native_core | (background_core != builder.NODATA)) & region & ~measured).any():
                        omitted += 1
                        continue
                if not rgba[..., 3].any():
                    continue
                tiles[z, x, y] = builder.encode_png(rgba)
                count += 1
                for row in used:
                    entry = support.setdefault(row['id'], dict(id=row['id'], resolution_m=row['resolution_m'], tiles=0))
                    entry['tiles'] += 1
            by_zoom[str(z)] = dict(tiles=count, omitted_uncertified=omitted,
                                   limit_m=builder.DETAIL_M if z > 15 else builder.SHALLOW_M,
                                   sources=sorted(support.values(), key=lambda s: (s['resolution_m'], s['id'])))
        if not tiles:
            raise ValueError('no survey support in requested zoom range')
        minzoom, maxzoom = min(t[0] for t in tiles), max(t[0] for t in tiles)
        coverage = builder.coverage(bg, background.res, sources if maxzoom > 13 else [], bounds)
    center = ((west + east) / 2, (south + north) / 2)
    # Do not stamp a producer version or full-style hash into archive bytes: only
    # the baked style can affect those bytes, and the receipt owns provenance.
    fields = ('id', 'resolution_m', 'survey_id', 'survey_dates', 'vertical_datum', 'source_url',
              'source_file', 'archive_sha256', 'depth_semantics', 'release_date')
    metadata = dict(name=f'SkipperCast {label} seafloor (Nearshore)', format='png', type='baselayer', version='1',
                    description='Styled public bathymetry, nominal survey datums; NOT FOR NAVIGATION.',
                    attribution='Survey sources: ' + ', '.join(row.get('survey_id', row['id']) for row in sources)
                    if sources else 'Public bathymetric surveys (via SkipperCast)',
                    minzoom=minzoom, maxzoom=maxzoom, bounds=bounds, center=[*center, 10],
                    native_sources=[{k: row[k] for k in fields if k in row} for row in sources],
                    shallow_limit_m=builder.SHALLOW_M, feather_m=builder.FEATHER_M if sources else 0,
                    native_support_by_zoom=by_zoom, detail_coverage=coverage)
    write_pmtiles(out / 'relief.pmtiles', tiles.items(), metadata=metadata, bounds=bounds,
                  minzoom=minzoom, maxzoom=maxzoom, center=(10, *center))
    (out / 'coverage.json').write_bytes(receipts.canonical(dict(coverage, archive='relief.pmtiles')) + b'\n')
    return cells
