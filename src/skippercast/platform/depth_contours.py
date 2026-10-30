"""Publish a region's shelf depth contours from its reviewed survey grids (CI6-13).

scripts/build_depth_contours.py traces the contours from the region's
approved, bound bathymetry grids (the original survey GeoTIFFs at their
reviewed native cell size; each SHA-256 is recorded, not checked against a
pin) and writes catalog/depth-contours/<id>.geojson. The platform build
checks that file and writes its published form to
dist/regions/<id>/depth-contours.geojson, plus an overview form
(depth-contours-overview.geojson) that the Chart draws below
OVERVIEW_MAX_ZOOM. A region without an import publishes no contours.

The method, kept here so it is tested without the GIS stack:

- Depths are feet below the survey's own vertical datum. For the Morro Bay
  grids that datum is unverified: the GeoTIFFs declare none, and only the
  companion USGS report names MLLW. Every line says so; nothing here converts
  or certifies a datum.
- The 2 m grid is averaged into CELL_M blocks. A block counts only when every
  native cell inside it is valid water, so no block is filled, extended or
  interpolated across a survey gap: nothing creates coverage.
- `trace` runs marching squares over the block centres at every INTERVAL_FT
  multiple to SHELF_LIMIT_FT. A square draws only when its four corners are
  valid blocks, so lines stop where the reviewed grid stops.
- Where two surveys overlap, each block belongs to the first source in the
  region's bathymetry binding order that fully supports it; every line then
  comes from one survey and carries that survey's source, date and datum.
- The survey-edge lines outline each survey's supported blocks: where the
  contours stop because there is no reviewed grid beyond.

The published form groups lines by their exact properties into one
MultiLineString per (source, depth), so a click on any line reads its own
source, survey date and datum. Coordinates have 5 decimals (about 1 m).
"""
from datetime import date, timedelta
from pathlib import Path
import math
import re

from .contracts import atomic_json, read_json
from .shoreline import simplify

SCHEMA_VERSION = 1
INTERVAL_FT = 30
# Every INDEX_FT multiple is an index line: drawn heavier and labelled at lower zoom.
INDEX_FT = 150
# Shelf only (CI6-13): deeper contours wait for a reviewed deep-water grid (CI6-16).
SHELF_LIMIT_FT = 600
CELL_M = 16
DECIMALS = 5
FEET_PER_M = 3.28084
UNVERIFIED_DATUM = 'unverified source datum'
KINDS = ('contour', 'survey-edge')
# Size budgets (decoded bytes) for the two published forms; the build fails past them.
MAX_BYTES = 1_000_000
OVERVIEW_MAX_BYTES = 64_000
# At MapLibre zoom 11 (where the map opens) one pixel is about 31 m here, so 60 m is about 2 pixels.
OVERVIEW_TOLERANCE_M = 60
OVERVIEW_MIN_SPAN_M = 300
OVERVIEW_DECIMALS = 4
# web/map/depth-contours.ts DETAIL_ZOOM is the MapLibre zoom the full form loads from.
OVERVIEW_MAX_ZOOM = 12
# Age limit: the Chart withholds the contours once their oldest source review is this old (review_expires).
SOURCE_REVIEW_DAYS = 365
YEAR = re.compile(r'\d{4}(-\d{2}(-\d{2})?)?')
SHA256 = re.compile(r'[0-9a-f]{64}')


def levels(low_ft, high_ft, interval=INTERVAL_FT, limit=SHELF_LIMIT_FT):
    """The contour depths (ft) inside [low_ft, high_ft]: multiples of `interval`, at least one interval, at most `limit`."""
    first = max(interval, math.ceil(low_ft / interval) * interval)
    return list(range(first, min(limit, math.floor(high_ft / interval) * interval) + 1, interval))


def _cross(grid, edge, level):
    """The crossing point of `level` on the edge between grid nodes, as (x, y) in column/row units."""
    (ra, ca), (rb, cb) = edge
    va, vb = grid[ra][ca], grid[rb][cb]
    t = (level - va) / (vb - va)
    return (ca + t * (cb - ca), ra + t * (rb - ra))


def _square_links(v, nodes, level):
    """The one or two segments `level` makes across a square, as pairs of edge keys (or none)."""
    above = [x >= level for x in v]
    if all(above) or not any(above):
        return ()
    edges = [tuple(sorted((nodes[i], nodes[(i + 1) % 4]))) for i in range(4)]
    crossed = [edges[i] for i in range(4) if above[i] != above[(i + 1) % 4]]
    if len(crossed) == 2:
        return ((crossed[0], crossed[1]),)
    # A saddle: corners top-left, top-right, bottom-right, bottom-left; edges top, right, bottom, left.
    top, right, bottom, left = edges
    if above[0] == (sum(v) / 4 >= level):
        # The top-left and bottom-right corners join through the centre: cut off the other two.
        return ((top, right), (bottom, left))
    return ((left, top), (right, bottom))


def _walk(links):
    """Chain the segment graph into lines: open lines from an end first, then closed rings, in key order."""
    seen, chains = set(), []
    starts = sorted(k for k, v in links.items() if len(v) == 1) + sorted(k for k, v in links.items() if len(v) != 1)
    for start in starts:
        if start in seen:
            continue
        chain, previous, here = [start], None, start
        seen.add(start)
        while True:
            step = [q for q in links[here] if q != previous and (q not in seen or (q == start and len(chain) > 2))]
            if not step:
                break
            previous, here = here, step[0]
            chain.append(here)
            if here == start:
                break
            seen.add(here)
        if len(chain) >= 2:
            chains.append(chain)
    return chains


def _clean_chain(points):
    """Drop consecutive duplicate coordinates and chains with no geometric extent.

    Compare exactly: short real lines survive, as does a ring's closing point.
    """
    clean = []
    for point in points:
        if not clean or point != clean[-1]:
            clean.append(point)
    return clean if len(clean) >= 2 else []


def trace(grid, depths):
    """Marching squares: {depth: lines} of each depth in `depths` across `grid` (rows of numbers, None where invalid).

    Points are (column, row) in grid units, node (r, c) at (c, r). A square draws only when all four
    corners are valid, so a line ends at the first square that touches a gap or the grid edge. A value
    equal to the depth counts as at or past it, so a line never runs through a node. Saddles are split
    by the mean of the four corners. A closed ring repeats its first point last. The output order is
    deterministic.
    """
    wanted = sorted(set(depths))
    links = {d: {} for d in wanted}
    rows, cols = len(grid), len(grid[0]) if grid else 0
    for r in range(rows - 1):
        upper, lower = grid[r], grid[r + 1]
        for c in range(cols - 1):
            v = (upper[c], upper[c + 1], lower[c + 1], lower[c])
            if None in v:
                continue
            low, high = min(v), max(v)
            crossing = [d for d in wanted if low < d <= high]
            if not crossing:
                continue
            nodes = ((r, c), (r, c + 1), (r + 1, c + 1), (r + 1, c))
            for d in crossing:
                graph = links[d]
                for p, q in _square_links(v, nodes, d):
                    graph.setdefault(p, []).append(q)
                    graph.setdefault(q, []).append(p)
    return {d: [points for chain in _walk(links[d])
                if (points := _clean_chain(_cross(grid, edge, d) for edge in chain))]
            for d in wanted}


def feature_lines(geometry):
    """The lines of a LineString or MultiLineString geometry."""
    return [geometry['coordinates']] if geometry['type'] == 'LineString' else geometry['coordinates']


def omitted_sources(region, sources, listed_ids):
    """The region's bound bathymetry surveys not in `listed_ids`, in binding order, each with its catalog review_status
    copied verbatim. A bound id missing from the catalog raises ValueError."""
    listed, omitted = set(listed_ids), []
    for ident in region['source_bindings']['bathymetry']:
        if ident in listed:
            continue
        if ident not in sources:
            raise ValueError(f"Bathymetry binding {ident} of {region['id']} is not in the source catalog")
        omitted.append({'source_id': ident, 'review_status': sources[ident]['review_status']})
    return omitted


def check_contours(collection, region, sources):
    """Raise ValueError unless `collection` is an in-region contour set from approved, bound survey grids.

    `sources` is the catalog by id. Every feature must name one of the region's approved bathymetry
    bindings with its survey date and vertical datum (the source entry also carries the grid hash);
    contours must be INTERVAL_FT multiples no deeper than SHELF_LIMIT_FT; every point must lie inside the region.
    """
    provenance = collection.get('provenance') or {}
    if collection.get('type') != 'FeatureCollection' or provenance.get('region_id') != region['id']:
        raise ValueError(f"Depth contours for {region['id']} are not its FeatureCollection")
    if provenance.get('features') != len(collection['features']) or provenance.get('interval_ft') != INTERVAL_FT:
        raise ValueError(f"Depth contours for {region['id']} have incomplete provenance")
    if provenance.get('shelf_limit_ft') != SHELF_LIMIT_FT or provenance.get('units') != 'ft':
        raise ValueError(f"Depth contours for {region['id']} do not state feet and the shelf limit")
    bound = set(region.get('source_bindings', {}).get('bathymetry', []))
    listed = {str(s.get('source_id')): s for s in provenance.get('sources', [])}
    for ident, entry in listed.items():
        reviewed = sources.get(ident) or {}
        if ident not in bound or reviewed.get('review_status') != 'approved' or 'bathymetry' not in reviewed.get('needs', []):
            raise ValueError(f"Depth contour source {ident} is not an approved bathymetry binding of {region['id']}")
        if not SHA256.fullmatch(str(entry.get('sha256'))) or not YEAR.fullmatch(str(entry.get('survey_date'))) \
                or not entry.get('vertical_datum'):
            raise ValueError(f"Depth contour source {ident} lacks its grid hash, survey date or datum")
    if 'sources_omitted' in provenance and provenance['sources_omitted'] != omitted_sources(region, sources, listed):
        raise ValueError(f"Depth contours for {region['id']} misstate the omitted bound surveys")
    west, south, east, north = region['bounds']
    for feature in collection['features']:
        p, geometry = feature.get('properties') or {}, feature.get('geometry') or {}
        if p.get('kind') not in KINDS or p.get('source_id') not in listed:
            raise ValueError(f"Depth contour {feature.get('id')} has no kind or an unlisted source")
        entry = listed[p['source_id']]
        if p.get('survey_date') != entry['survey_date'] or p.get('vertical_datum') != entry['vertical_datum']:
            raise ValueError(f"Depth contour {feature.get('id')} lacks its source's survey date or datum")
        if p['kind'] == 'contour':
            depth = p.get('depth_ft')
            if (not isinstance(depth, int) or isinstance(depth, bool) or depth <= 0 or depth % INTERVAL_FT
                    or depth > SHELF_LIMIT_FT or p.get('index') is not (depth % INDEX_FT == 0)):
                raise ValueError(f"Depth contour {feature.get('id')} is not a {INTERVAL_FT} ft shelf contour")
        lines = {'LineString': [geometry.get('coordinates')], 'MultiLineString': geometry.get('coordinates')}.get(geometry.get('type'))
        if not lines or any(len(line) < 2 or any(not (west <= x <= east and south <= y <= north) for x, y in line)
                            for line in lines):
            raise ValueError(f"Depth contour {feature.get('id')} is not a line inside {region['id']}")


def overview_contours(collection, tolerance_m=OVERVIEW_TOLERANCE_M):
    """The overview form: each line simplified to `tolerance_m` and rounded to OVERVIEW_DECIMALS; a line spanning
    less than OVERVIEW_MIN_SPAN_M (a ring round a single pinnacle, a stub at a survey edge) is left out. Same features
    and properties; the full form, loaded from OVERVIEW_MAX_ZOOM, keeps every line."""
    west, south, east, north = collection['provenance']['bounds']
    scale = (111_320 * math.cos(math.radians((south + north) / 2)), 110_540)
    features = []
    for feature in collection['features']:
        lines = []
        for line in feature_lines(feature['geometry']):
            short = [[round(x, OVERVIEW_DECIMALS), round(y, OVERVIEW_DECIMALS)] for x, y in simplify(line, tolerance_m, scale)]
            short = [p for i, p in enumerate(short) if i == 0 or p != short[i - 1]]
            xs, ys = [p[0] * scale[0] for p in short], [p[1] * scale[1] for p in short]
            if len(short) >= 2 and max(max(xs) - min(xs), max(ys) - min(ys)) >= OVERVIEW_MIN_SPAN_M \
                    and not (short[0] == short[-1] and len(short) < 4):
                lines.append(short)
        if lines:
            features.append({**feature, 'geometry': {'type': 'MultiLineString', 'coordinates': lines}})
    provenance = {**collection['provenance'], 'features': len(features), 'coordinate_decimals': OVERVIEW_DECIMALS,
                  'overview': {'tolerance_m': tolerance_m, 'min_span_m': OVERVIEW_MIN_SPAN_M, 'max_zoom': OVERVIEW_MAX_ZOOM,
                               'note': 'Drawn below max_zoom only; the full contours load at and above it.'}}
    return {**collection, 'provenance': provenance, 'features': features}


def review_expires(collection, sources):
    """The date the published contours are withheld from: SOURCE_REVIEW_DAYS after the oldest source review."""
    reviewed = []
    for entry in collection['provenance']['sources']:
        stamp = str((sources.get(entry['source_id']) or {}).get('reviewed_at', ''))
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', stamp[:10]):
            raise ValueError(f"Depth contour source {entry['source_id']} has no review date")
        reviewed.append(date.fromisoformat(stamp[:10]))
    return (min(reviewed) + timedelta(days=SOURCE_REVIEW_DAYS)).isoformat()


def publish_depth_contours(root, region, output, sources):
    """Write the checked import and its overview form to `output`; remove stale copies when there is none.

    Both forms carry `review_expires`, the date the Chart withholds them from (the layer's age limit), and
    `sources_omitted`, the region's bound surveys the file does not draw, with their catalog review_status.
    Returns the published paths (full, overview) or None. Raises ValueError when a form is over its byte budget.
    """
    source = Path(root) / 'catalog/depth-contours' / f"{region['id']}.geojson"
    full, overview = Path(output) / 'depth-contours.geojson', Path(output) / 'depth-contours-overview.geojson'
    if not source.is_file():
        full.unlink(missing_ok=True)
        overview.unlink(missing_ok=True)
        return None
    collection = read_json(source)
    check_contours(collection, region, sources)
    collection = {**collection, 'provenance': {**collection['provenance'], 'review_expires': review_expires(collection, sources),
                                               'review_days': SOURCE_REVIEW_DAYS, 'sources_omitted': omitted_sources(
                                                   region, sources, [s['source_id'] for s in collection['provenance']['sources']])}}
    light = overview_contours(collection)
    check_contours(light, region, sources)
    for path, value, budget in ((full, collection, MAX_BYTES), (overview, light, OVERVIEW_MAX_BYTES)):
        receipt = atomic_json(path, value)
        if receipt['bytes'] > budget:
            path.unlink()
            raise ValueError(f"{path.name} for {region['id']} is {receipt['bytes']} bytes, over its {budget}-byte budget")
    return f"regions/{region['id']}/depth-contours.geojson", f"regions/{region['id']}/depth-contours-overview.geojson"
