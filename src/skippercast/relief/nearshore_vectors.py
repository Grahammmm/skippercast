"""Public relief-basis vectors for QA, not for the release or Chart."""
from contextlib import ExitStack
from functools import lru_cache
import math
from pathlib import Path

from skippercast.relief import mosaic, receipts, render_config, tiles
from skippercast.relief.tiles import assemble_windows

SCOPES = ('public',)
UPSTREAM = ('select', 'mosaic:public')
TARGET = 'layers/public/nearshore'
CODE_FILES = (*tiles.CODE_FILES, 'skippercast.relief.tiles')
add_arguments = mosaic.add_region_config
MAX_PILE_BYTES = 1_000_000
NO_CERT = 'no certified ≤1 m support (C7)'


def plan(ctx):
    version, tokens = render_config.resolve_style(ctx.region.id)
    baked = tokens.view('baked') if tokens is not None else None
    habitat = tokens.view('habitat') if tokens is not None else None
    del tokens
    digests = {group: view.digest(group) if view is not None else None
               for group, view in [('baked', baked), ('habitat', habitat)]}
    index = mosaic.read_json(render_config.repo_root() / 'style/index.json')
    ctx.vector_style = baked, habitat, dict(built_with=version, sha256=index['versions'][version].get('sha256'), **digests)
    piers = sorted(render_config.piers(ctx.region.id), key=lambda pier: pier['id'])
    ctx.vector_piers = piers
    native = mosaic.selected(ctx, 'native.json')
    inputs = [receipts.Input(mosaic.region_config(ctx), 'region'), receipts.Input(native, 'native'),
              receipts.Input(tiles.elevation(ctx), 'elevation')]
    inputs.extend(item for item, _ in mosaic.raster_refs(native, mosaic.read_json(native)))
    return receipts.Plan(inputs, dict(digests, piers=piers))


def pile_shapes(ds, lower, view, builder, *, native=True):
    """Stitch core polygons across chunk seams before assigning one peak per pile."""
    import numpy as np
    from rasterio.features import shapes
    from rasterio.windows import Window
    from scipy import ndimage
    from shapely import STRtree, union_all
    from shapely.geometry import Point, shape
    from skippercast.relief.nearshore import FT_PER_M

    if max(ds.res) > 2:
        return []
    polygons, peaks, points = [], [], []
    for x, y, w, h, core, valid, image in assemble_windows(ds, lower, view, builder, native=native):
        mask = image.piles()[0][core] & valid
        if not mask.any():
            continue
        labels, count = ndimage.label(mask)
        bpi = image.bpi()[core]
        where = ndimage.maximum_position(bpi, labels, np.arange(1, count + 1))
        transform = ds.window_transform(Window(x, y, w, h))
        for geom, label in shapes(labels, mask=mask, transform=transform):
            row, col = where[int(label) - 1]
            polygons.append(shape(geom))
            points.append(Point(*(transform * (col + .5, row + .5))))
            peaks.append((float(bpi[row, col]) * FT_PER_M, float(image.depth_ft[core][row, col])))
    if not polygons:
        return []
    tree = STRtree(points)
    merged = union_all(polygons)
    components = merged.geoms if merged.geom_type == 'MultiPolygon' else [merged]
    result = []
    for geom in components:
        best = min(tree.query(geom, predicate='covers'), key=lambda i: (-peaks[i][0], points[i].x, points[i].y))
        result.append((geom, points[best], *peaks[best]))
    return sorted(result, key=lambda part: (part[1].x, part[1].y))


def pier_features(z, transform, xy, crs, row, source_id, view, *, water=None):
    """Resolve the deepest observed vertex and clip each radius to actual water cells."""
    import numpy as np
    from rasterio.features import shapes
    from rasterio.transform import rowcol
    from shapely import union_all
    from shapely.geometry import LineString, MultiLineString, Point, shape
    from skippercast.relief.nearshore import FT_PER_M

    water = (np.isfinite(z) & (z < 0)) if water is None else water
    rr, cc = rowcol(transform, *zip(*xy))
    candidates = [(float(z[r, c]), i) for i, (r, c) in enumerate(zip(rr, cc))
                  if 0 <= r < z.shape[0] and 0 <= c < z.shape[1] and water[r, c]]
    if not candidates:
        return None
    depth, end = min(candidates)
    center = Point(xy[end])
    props = dict(pier_id=row['id'], source_id=source_id)
    pier = _feature(LineString(xy[::-1] if end == 0 else xy), crs,
                    dict(props, name=row['name'], seaward_end=_feature(center, crs, {})['geometry']['coordinates'],
                         end_depth_ft=round(-depth * FT_PER_M, 3)))
    settings = view['pier_view']['cast_arcs']
    if settings['clip'] != 'water cells only':
        raise receipts.ReceiptError('unsupported cast-arc clip rule')
    water_area = union_all([shape(g) for g, _ in shapes(water.astype('uint8'), mask=water, transform=transform)])
    arcs = []
    for index, radius in enumerate(settings['radii_m']):
        ring = LineString(center.buffer(radius, quad_segs=180).exterior.coords)
        clipped = ring.intersection(water_area)
        parts = clipped.geoms if hasattr(clipped, 'geoms') else [clipped]
        lines = [part for part in parts if part.geom_type == 'LineString' and not part.is_empty]
        geometry = lines[0] if len(lines) == 1 else MultiLineString(lines)
        arcs.append(_feature(geometry, crs, dict(props, radius_m=radius, radius_index=index)))
    return pier, arcs


def _certified_pier(ds, source, row, baked, habitat, builder):
    import numpy as np
    import rasterio
    from rasterio.warp import transform
    from rasterio.windows import Window
    from shapely.geometry import LineString

    settings = habitat['pier_view']
    if (max(ds.res) > min(1, settings['max_cell_m']) or not builder.has_support(source)
            or min(builder.source_maxzoom(source), baked.native_max_zoom(ds.res[0])) < 16):
        return None
    xy = list(zip(*transform('EPSG:4326', ds.crs, *zip(*row['coordinates']))))
    line = LineString(xy)
    midpoint = line.interpolate(.5, normalized=True)
    half = settings['window_m'] / 2
    # Cover the configured square, plus the whole pier if its endpoints extend beyond it.
    left, bottom, right, top = line.bounds
    c0, r0 = ~ds.transform * (min(left, midpoint.x-half), max(top, midpoint.y+half))
    c1, r1 = ~ds.transform * (max(right, midpoint.x+half), min(bottom, midpoint.y-half))
    c0, r0, c1, r1 = math.floor(c0), math.floor(r0), math.ceil(c1), math.ceil(r1)
    if c0 < 0 or r0 < 0 or c1 > ds.width or r1 > ds.height or c1 <= c0 or r1 <= r0:
        return None
    window = Window(c0, r0, c1-c0, r1-r0)
    with rasterio.open(source['support_path']) as support:
        if (support.count != 1 or support.dtypes[0] != 'uint8' or support.shape != ds.shape
                or support.crs != ds.crs or support.transform != ds.transform):
            raise ValueError('support grid must be aligned with native elevation and single-band uint8')
        measured = support.read(1, window=window, masked=True).filled(0) == 3
    z = ds.read(1, window=window, masked=True).astype('float32').filled(np.nan)
    wet = z < 0
    # Known dry cells can clip arcs, but unknown or estimated water cannot certify a window.
    if not np.isfinite(z).all() or not (measured[wet] & (z[wet] >= -builder.DETAIL_M)).all():
        return None
    return pier_features(z, ds.window_transform(window), xy, ds.crs, row, source['id'], habitat)


@lru_cache(maxsize=32)
def _project(crs, target):
    from pyproj import Transformer

    return Transformer.from_crs(crs, target, always_xy=True).transform


def _feature(geometry, crs, properties):
    from shapely.geometry import mapping
    from shapely.ops import transform

    return dict(type='Feature', geometry=mapping(transform(_project(crs, 4326), geometry)), properties=properties)


def _collection(features):
    return receipts.canonical(dict(type='FeatureCollection', features=features))


def _piles_and_peaks(records, view):
    from scipy.spatial import cKDTree

    if not records:
        return _collection([]), _collection([])
    labels = view['rock_piles']['label']
    from skippercast.relief.nearshore import FT_PER_M

    candidates = []
    for i, (_, point, height, _, ds, source_id) in enumerate(records):
        if ds.res[0] <= labels['max_cell_m'] and height >= labels['min_peak_m'] * FT_PER_M:
            projected = _project(ds.crs, 3310)(point.x, point.y)
            candidates.append((height, i, projected, _feature(point, ds.crs, dict(
                height_ft=round(height, 3), basis='relief', label=f'+{height:.0f} ft', source_id=source_id))))
    candidates.sort(key=lambda row: (-row[0], row[1]))
    suppressed, peaks = set(), []
    if candidates:
        tree = cKDTree([p[2] for p in candidates])
        for j, (_, _, xy, feat) in enumerate(candidates):
            if j not in suppressed:
                peaks.append(feat)
                suppressed.update(tree.query_ball_point(xy, labels['nms_m']))
    peak_bytes = _collection(peaks)
    for tolerance in (.25, .5):
        piles = []
        for i, (geom, _, height, depth, ds, source_id) in enumerate(records, 1):
            simplified = geom.simplify(ds.res[0] * tolerance, preserve_topology=True)
            piles.append(_feature(simplified, ds.crs, dict(id=i, height_ft=round(height, 3), depth_ft=round(depth, 3),
                                                          area_m2=round(geom.area, 3), basis='relief', source_id=source_id)))
        pile_bytes = _collection(piles)
        if len(pile_bytes) + len(peak_bytes) <= MAX_PILE_BYTES:
            return pile_bytes, peak_bytes
    raise receipts.ReceiptError(f'{len(records)} piles + peaks require {len(pile_bytes) + len(peak_bytes)} bytes; '
                                f'budget {MAX_PILE_BYTES} exceeded at half-cell simplification (no piles dropped)')


def build(ctx, out):
    import rasterio

    baked, habitat, provenance = ctx.vector_style
    rows = ctx.vector_piers
    region = mosaic.read_json(mosaic.region_config(ctx))
    if region['id'] != ctx.region.id:
        raise receipts.ReceiptError('region config id differs from the requested region')
    native = mosaic.selected(ctx, 'native.json')
    sources = mosaic.read_json(native)
    mosaic.verify_rasters(mosaic.raster_refs(native, sources))
    statuses = {row['id']: dict(status='skipped', reason=(
        'no pier geometry: osm_way only (held-extract reader not admitted)' if 'coordinates' not in row
        else NO_CERT if habitat is not None else 'legacy style has no pier view')) for row in rows}
    records, piers, arcs = [], [], []
    if baked is not None and sources:
        builder = tiles._builder()
        with ExitStack() as stack:
            lower = [(stack.enter_context(rasterio.open(tiles.elevation(ctx))), False)]
            grids = []
            for source in sorted(sources, key=lambda s: (-s['resolution_m'], s['id'])):
                source = dict(source)
                for key in ('path', 'support_path'):
                    if source.get(key) is not None:
                        source[key] = native.parent / Path(source[key]).expanduser()
                ds = stack.enter_context(rasterio.open(source['path']))
                if (ds.count != 1 or not ds.crs.is_projected or not math.isclose(ds.crs.linear_units_factor[1], 1)
                        or ds.transform.a <= 0 or ds.transform.e >= 0 or ds.transform.b or ds.transform.d
                        or not math.isclose(*ds.res, rel_tol=1e-6)):
                    raise ValueError('expected a single-band, north-up square native metre grid')
                records.extend((*pile, ds, source['id']) for pile in pile_shapes(ds, lower, baked, builder))
                lower.append((ds, True))
                grids.append((ds, source))
            for row in rows:
                if 'coordinates' not in row:
                    continue
                for ds, source in reversed(grids):
                    result = _certified_pier(ds, source, row, baked, habitat, builder)
                    if result is not None:
                        pier, rings = result
                        piers.append(pier)
                        arcs.extend(rings)
                        statuses[row['id']] = dict(status='produced', reason=None)
                        break
    piles, peaks = _piles_and_peaks(records, habitat)
    products = {'piles.geojson': piles, 'peaks.geojson': peaks,
                'pier.geojson': _collection(piers), 'arcs.geojson': _collection(arcs)}
    for name, data in products.items():
        (out / name).write_bytes(data)
    return dict(style=provenance, pier_view=statuses, piles_total=len(records),
                piles_by_basis={'relief': len(records)}, bytes={name: len(data) for name, data in products.items()})
