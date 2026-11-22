"""Offline regional ocean masks using the reviewed north-B shoreline opening.

Also the receipted region stage ``region.py water --region ID --out OUT
--shoreline-manifest FILE [--region-config FILE] [--us-boundary FILE]``. It reads one admitted CUSP
custody manifest and only the tiles it lists as served (sha256-checked against
their rows; it never fetches), decodes their shoreline accuracies with the
merged importer, and writes ``water.geojson`` and its report ``water.json``.
An owner-reviewed US-waters polygon can clip the ocean; any remainder is
written as a no-survey feature in ``outside-us.geojson``.
"""

from importlib.util import module_from_spec, spec_from_file_location
import json
from math import ceil, floor, isfinite
from pathlib import Path
from typing import Iterable, cast

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon, box, mapping

from skippercast.paths import repo_root
from skippercast.platform import shoreline
from skippercast.relief import border, mosaic, receipts

_QUAD_SEGS = 8
_FRAME_GRID = 100_000
_FRAME_SEGMENT_DEG = 0.005
_OUTPUT_GRID = 0.000001

# Reviewed north-B builder (scratch/sc-map-goal/north-b-inputs/water/build_water.py:67,
# sha256 5b17edd6b5e48d8617d754dd8af157cefef4cf8e864026a6fb909ad8ac338a00). Its rule is
# CLOSE_M = max stated HOR_ACC (:16, :581); 18.0 is that maximum in all three north-B
# regions. The stage applies the rule per region and keeps the connectivity constant.
CLOSE_M = 18.0
CONNECT_M = 250.0
CUSP_SCRIPT = 'scripts/shoreline/import_cusp.py'
CODE_FILES = (CUSP_SCRIPT, 'skippercast.platform.shoreline', 'skippercast.relief.border')


def _project(geometry, transformer):
    return shapely.transform(geometry, transformer.transform, interleaved=False)


def _wgs84(geometry):
    xy = shapely.get_coordinates(geometry)
    return bool(np.isfinite(xy).all() and (np.abs(xy) <= [180, 90]).all())


def _frame_bounds(bounds):
    w, s, e, n = bounds
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("expected ordered WGS84 frame bounds")

    def snap(value, inward):
        scaled = value * _FRAME_GRID
        # Preserve points already on the grid despite binary floating point.
        nearest = round(scaled)
        cell = nearest if nearest / _FRAME_GRID == value else inward(scaled)
        return cell / _FRAME_GRID

    w, s, e, n = snap(w, ceil), snap(s, ceil), snap(e, floor), snap(n, floor)
    if not (w < e and s < n):
        raise ValueError("frame vanishes on the five-decimal grid")
    return w, s, e, n


def _project_frame(bounds, forward):
    w, s, e, n = bounds
    mid = (s + n) / 2
    # Include the seed as a vertex. Projecting it separately onto a chord of
    # a curved meridian can leave it slightly outside the projected frame.
    ring = LineString([(e, s), (e, n), (w, n), (w, mid), (w, s), (e, s)])
    east = LineString([(e, s), (e, n)])
    return (
        Polygon(_project(shapely.segmentize(ring, _FRAME_SEGMENT_DEG), forward)),
        _project(shapely.segmentize(east, _FRAME_SEGMENT_DEG), forward),
        _project(Point(w, mid), forward),
    )


def _west_part(geometry, seed):
    parts = [p for p in shapely.get_parts(geometry) if isinstance(p, Polygon) and not p.is_empty]
    west = [i for i, p in enumerate(parts) if p.distance(seed) < 1e-6]
    if len(west) != 1:
        raise ValueError("expected exactly one component at the west-frame seed")
    return parts.pop(west[0]), parts


def _line_parts(geometry):
    if isinstance(geometry, LineString) and geometry.length:
        yield geometry
    elif isinstance(geometry, (GeometryCollection, MultiLineString)):
        for part in geometry.geoms:
            yield from _line_parts(part)


def _buffer(geometry, radius):
    return geometry.buffer(radius, quad_segs=_QUAD_SEGS)


def _cut_east(ocean, frame, east, seed, lines, close_m, connect_m):
    if not ocean.intersects(east):
        return ocean, [], []

    # Re-open the clearance core at the larger radius, reconstruct it only
    # back to close_m, and remove only residual pieces that touch the east.
    # In particular this must not remove bays merely because they are narrow.
    west_core, _ = _west_part(frame.difference(_buffer(lines, connect_m)), seed)
    core = ocean.intersection(_buffer(west_core, connect_m - close_m))
    cut_pieces = [p for p in shapely.get_parts(ocean.difference(core)) if p.intersects(east)]
    cut_union = shapely.union_all(cut_pieces)
    kept, detached = _west_part(ocean.difference(cut_union), seed)
    if kept.intersects(east):
        raise ValueError("ocean still reaches the east frame after connectivity cuts")
    arcs = shapely.line_merge(kept.boundary.intersection(cut_union.buffer(0.5)))
    return kept, cut_pieces + detached, list(_line_parts(arcs))


def _position(point, inverse, decimals):
    return [round(v, decimals) for v in inverse.transform(point.x, point.y)]


def _displacement(shore_m, lines_m, cut_arcs_m, close_m, inverse):
    """Score the non-frame boundary in metres; listed cuts exempt flags, not the max."""
    bound = 2 * close_m
    cuts = shapely.union_all(cut_arcs_m)
    maximum = 0.0
    beyond = []
    for part in _line_parts(shore_m):
        steps = np.append(np.arange(0, part.length, 2.0), part.length)
        samples = shapely.line_interpolate_point(part, steps.tolist())
        distances = shapely.distance(samples, lines_m)
        maximum = max(maximum, float(distances.max()))
        outliers = samples[distances > bound + 0.5]
        if not cuts.is_empty:
            outliers = outliers[shapely.distance(outliers, cuts) > close_m + 1]
        beyond.extend(_position(p, inverse, 5) for p in outliers)
    return {
        "max_displacement_m": round(maximum, 2),
        "displacement_bound_m": bound,
        "unlisted_beyond_bound": sorted(beyond),
    }


def _output_polygon(ocean, frame_ll, inverse) -> Polygon | MultiPolygon:
    water = _project(ocean, inverse)
    if not water.is_valid:
        # Repair only projection artefacts of the derived polygon.
        water = shapely.union_all([
            p for p in shapely.get_parts(shapely.make_valid(water)) if isinstance(p, (Polygon, MultiPolygon))
        ])
    water = shapely.set_precision(water, _OUTPUT_GRID).intersection(frame_ll)
    polygons = [p for p in shapely.get_parts(water) if isinstance(p, Polygon) and p.area > 0]
    if not polygons:
        raise ValueError("empty ocean on the output grid")
    return cast(Polygon | MultiPolygon, shapely.orient_polygons(shapely.union_all(polygons).normalize()))


def ocean_polygon(
    lines: Iterable[tuple[LineString, float]],
    frame: tuple[float, float, float, float],
    *,
    close_m: float,
    connect_m: float,
) -> tuple[Polygon | MultiPolygon, dict]:
    """Return a WGS84 ocean polygon and its review report, without I/O.

    ``lines`` pairs each WGS84 LineString with its stated horizontal accuracy
    in metres. Supply the maximum of these accuracies as ``close_m`` and a
    connectivity radius ``connect_m`` at least that large.
    ``frame`` is (west, south, east, north) in WGS84; the method
    assumes the ocean contains its west midpoint and the east edge is inland.
    An ambiguous seed or an unresolved east leak is refused.

    Dropped components describe the clearance-stage polygons (WGS84 bounds
    and EPSG:3310 areas). Cut arcs describe the clearance-stage cut seams as
    WGS84 positions and metric lengths, before the final close_m dilation.
    Unlisted displacements are reported, not refused.
    """
    if not (isfinite(close_m) and isfinite(connect_m) and 0 < close_m <= connect_m):
        raise ValueError("expected finite radii with 0 < close_m <= connect_m")
    bounds = _frame_bounds(frame)
    raw, accuracies = [], []
    for line, accuracy in lines:
        if (not isinstance(line, LineString) or line.is_empty or shapely.get_coordinate_dimension(line) != 2
                or not _wgs84(line) or not line.length or not isfinite(accuracy) or accuracy <= 0):
            raise ValueError("expected nonempty 2D WGS84 shoreline and positive horizontal accuracy")
        raw.append(line)
        accuracies.append(accuracy)
    if not raw or max(accuracies) != close_m:
        raise ValueError("close_m must equal the maximum stated shoreline accuracy")

    forward = Transformer.from_crs(4326, 3310, always_xy=True)
    inverse = Transformer.from_crs(3310, 4326, always_xy=True)
    frame_ll = box(*bounds)
    frame_m, east, seed = _project_frame(bounds, forward)
    lines_m = _project(MultiLineString(raw), forward)
    # Erode against the shoreline, not against the frame; dilate only the
    # retained ocean component and clip the result back to the same frame.
    ocean, dropped = _west_part(frame_m.difference(_buffer(lines_m, close_m)), seed)
    ocean, cut_dropped, arcs = _cut_east(ocean, frame_m, east, seed, lines_m, close_m, connect_m)
    water = _output_polygon(_buffer(ocean, close_m).intersection(frame_m), frame_ll, inverse)

    cut_arcs = []
    for arc in arcs:
        arc = arc.normalize()
        cut_arcs.append({
            "from_lon_lat": _position(arc.interpolate(0), inverse, 6),
            "to_lon_lat": _position(arc.interpolate(1, normalized=True), inverse, 6),
            "mid_lon_lat": _position(arc.interpolate(0.5, normalized=True), inverse, 6),
            "length_m": round(arc.length, 1),
        })
    dropped_components = [{
        "bounds_wgs84": [round(v, 6) for v in _project(p, inverse).bounds],
        "area_m2_epsg3310": round(p.area, 1),
    } for p in dropped + cut_dropped]
    cut_arcs.sort(key=lambda a: (a["from_lon_lat"], a["to_lon_lat"], a["mid_lon_lat"], a["length_m"]))
    dropped_components.sort(key=lambda p: (p["bounds_wgs84"], p["area_m2_epsg3310"]))
    shore = shapely.line_merge(water.boundary.difference(frame_ll.boundary))
    return water, {
        "cut_arcs": cut_arcs,
        "components_dropped": dropped_components,
        **_displacement(_project(shore, forward), lines_m, arcs, close_m, inverse),
    }


def to_geojson(geometry: Polygon | MultiPolygon, region: str) -> dict:
    """Return a single-feature RFC 7946 collection for the zone loader."""
    if (not isinstance(geometry, (Polygon, MultiPolygon)) or geometry.is_empty
            or shapely.get_coordinate_dimension(geometry) != 2 or not _wgs84(geometry) or not geometry.is_valid):
        raise ValueError("expected a valid, nonempty 2D WGS84 Polygon or MultiPolygon")
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"region_id": region},
        "geometry": mapping(shapely.orient_polygons(geometry)),
    }]}


# --- region.py water ---------------------------------------------------------------------------

def add_arguments(parser):
    mosaic.add_region_config(parser)
    parser.add_argument('--shoreline-manifest', type=Path, required=True,
                        help='admitted CUSP custody manifest listing the held shoreline tiles')
    parser.add_argument('--us-boundary', type=Path, help='owner-reviewed US-waters polygon GeoJSON')


def plan(ctx):
    manifest = ctx.args.shoreline_manifest
    inputs = [receipts.Input(manifest, 'shoreline-manifest'), receipts.Input(mosaic.region_config(ctx), 'region')]
    # close_m follows from the listed tiles, which are inputs; build records the value it used.
    params = {'close_m': 'max stated HOR_ACC', 'connect_m': CONNECT_M}
    ctx.water_job = None
    if manifest.is_file():  # Otherwise the runner reports the missing input.
        data = manifest.read_bytes()
        try:
            doc = json.loads(data)
            rows = {row['tile']: row for row in doc['tiles']}
            served = [(tile, manifest.parent / row['path'], row['sha256'])
                      for tile, row in sorted(rows.items()) if row['status'] == 'served']
        except (ValueError, KeyError, TypeError) as exc:
            ctx.water_job = exc
        else:
            # Unavailable rows have no bytes by design: they are not inputs.
            ctx.water_job = (receipts.sha256_bytes(data), doc, rows, served)
            inputs.extend(receipts.Input(path, 'shoreline-tile') for _, path, _ in served)
    if ctx.args.us_boundary is not None:
        inputs.append(receipts.Input(ctx.args.us_boundary, 'us-boundary'))
    return receipts.Plan(inputs, params)


def _cusp():
    """The merged CUSP importer; the stage uses its decoder with held bytes, never its fetch."""
    spec = spec_from_file_location('import_cusp', repo_root() / CUSP_SCRIPT)
    assert spec is not None and spec.loader is not None  # A tracked file of this checkout.
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _accuracy(properties, feature_id):
    raw = properties.get('HOR_ACC')
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float('nan')
    if not (isfinite(value) and value > 0):
        raise receipts.Held(f'shoreline feature {feature_id} states no positive HOR_ACC: {raw!r}')
    return value


def _manifest_accuracies(cusp, held, frame_max):
    """Scan verified tile features before spatial clipping can discard them."""
    accuracies = set()
    support = None
    maximum = frame_max
    for tile, body in held.items():
        tile_id = tile.replace('/', '-')
        for layer in cusp.decode_tile(body):
            for index, feature in enumerate(layer['features']):
                if feature['type'] != 2:  # MVT LineString
                    continue
                accuracy = _accuracy(feature['properties'], f'cusp-{tile_id}-{index}')
                accuracies.add(accuracy)
                if accuracy > maximum:
                    maximum = accuracy
                    support = (tile, layer['extent'], feature['geometry'])
    return accuracies, support


def _reviewed_boundary(ctx):
    # Compare the exact bytes parsed by the loader with the runner's attempt pin.
    pending = receipts.read_receipt(ctx.region.receipt_path('water', ctx.scope))
    assert pending is not None  # The runner records the attempt before calling build.
    expected = next(row['sha256'] for row in pending['inputs'] if row['role'] == 'us-boundary')
    try:
        boundary, observed = border.load_boundary(ctx.args.us_boundary)
    except border.BorderError as exc:
        raise receipts.Held(str(exc)) from None
    if observed != expected:
        raise receipts.Held(f'SHA-256 mismatch for US-waters boundary: expected {expected}, observed {observed}')
    return boundary


def build(ctx, out_dir):
    boundary = _reviewed_boundary(ctx) if ctx.args.us_boundary is not None else None
    job, region_id = ctx.water_job, ctx.region.id
    if isinstance(job, Exception):
        raise ValueError(f'unreadable shoreline manifest: {type(job).__name__}: {job}')
    manifest_sha, doc, rows, served = job
    config = mosaic.read_json(mosaic.region_config(ctx))
    if config['id'] != region_id:
        raise receipts.ReceiptError('region config id differs from the requested region')
    bounds = config['bounds']
    entry = doc.get('regions', {}).get(region_id)
    covered = entry.get('bounds') if isinstance(entry, dict) else None
    if not (isinstance(covered, list) and len(covered) == 4 and covered[0] <= bounds[0]
            and covered[1] <= bounds[1] and bounds[2] <= covered[2] and bounds[3] <= covered[3]):
        raise receipts.Held(f'shoreline manifest does not cover region {region_id}: '
                            f'manifest bounds {covered}, region bounds {bounds}')

    held, pins = {}, []
    for tile, path, expected in served:
        data = path.read_bytes()
        observed = receipts.sha256_bytes(data)
        if observed != expected:
            raise receipts.Held(f'SHA-256 mismatch for shoreline tile {tile}: expected {expected}, observed {observed}')
        held[tile] = data
        pins.append({'tile': tile, 'sha256': expected})

    cusp = _cusp()
    frame = _frame_bounds(bounds)
    needed = ['/'.join(map(str, tile)) for tile in cusp.tiles_for(frame)]
    unavailable = {tile for tile, row in rows.items() if row['status'] == 'unavailable'}
    unlisted = [tile for tile in needed if tile not in held and tile not in unavailable]
    if unlisted:
        raise receipts.Held(f'shoreline manifest lists no served or unavailable row for frame tiles {unlisted}')

    # As the reviewed builder: the importer's extract, then the platform check and published form.
    collection = cusp.extract(region_id, frame, get=lambda tile: held.get('/'.join(map(str, tile))))
    frame_region = {'id': region_id, 'bounds': frame}
    shoreline.check_shoreline(collection, frame_region)
    published = shoreline.slim_shoreline(collection)
    shoreline.check_shoreline(published, frame_region)
    frame_accuracies = [_accuracy(feature['properties'], feature['id']) for feature in published['features']]
    lines = [(line, accuracy) for feature, accuracy in zip(published['features'], frame_accuracies)
             for line in map(LineString, shoreline.feature_lines(feature['geometry'])) if line.length]
    frame_max = max((accuracy for _, accuracy in lines), default=0.0)
    accuracies, support = _manifest_accuracies(cusp, held, frame_max)
    close_m = max(accuracies, default=0.0)
    if close_m > CONNECT_M:
        raise receipts.Held(f'maximum stated HOR_ACC {close_m} m exceeds connect_m {CONNECT_M} m')
    if not lines:
        raise receipts.Held(f'no shoreline lines in the frame of region {region_id}')
    if support is not None:
        # The public API requires the maximum to be carried by real shoreline.
        # Keep the frame extract and include the source feature supplying the higher radius.
        tile, extent, geometry = support
        z, x, y = map(int, tile.split('/'))
        for points in cusp.lines(geometry):
            line = LineString([(cusp.tile_lon(x + px / extent, z), cusp.tile_lat(y + py / extent, z))
                               for px, py in points])
            if line.length:
                lines.append((line, close_m))
    try:
        water, report = ocean_polygon(lines, frame, close_m=close_m, connect_m=CONNECT_M)
    except ValueError as exc:  # For example no west-connected ocean, or an east leak after the cuts.
        raise receipts.Held(str(exc)) from None

    if boundary is not None:
        # The shoreline report still scores the original coast, not the jurisdiction seam.
        water, outside = border.clip_to_us(water, boundary)
        no_survey = border.no_survey(outside)
        if no_survey is not None:
            (out_dir / 'outside-us.geojson').write_bytes(receipts.canonical(no_survey) + b'\n')

    geojson = {'type': 'FeatureCollection', 'features': []} if water.is_empty else to_geojson(water, region_id)
    (out_dir / 'water.geojson').write_bytes(receipts.canonical(geojson) + b'\n')
    (out_dir / 'water.json').write_bytes(receipts.canonical({
        'region': region_id, 'region_bounds_wgs84': bounds, 'frame_wgs84': list(frame),
        'close_m': close_m, 'connect_m': CONNECT_M, 'hor_acc_values_m': sorted(accuracies),
        'unavailable_tiles': sorted(unavailable),
        'report': report, 'inputs': {'manifest_sha256': manifest_sha, 'tiles': pins},
    }) + b'\n')
    beyond = report['unlisted_beyond_bound']
    if beyond:
        # The runner keeps out_dir, with water.json and its report, as the held attempt's failed_dir.
        raise receipts.Held(f"{len(beyond)} boundary samples lie beyond {report['displacement_bound_m']} m "
                            f"of the shoreline and are not at a listed cut")
    return {'close_m': close_m, 'connect_m': CONNECT_M}
