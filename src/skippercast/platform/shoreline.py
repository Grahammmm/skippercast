"""Publish a region's NOAA CUSP shoreline (FE-10, docs/plans/front-end/design.md § 11).

scripts/shoreline/import_cusp.py writes catalog/shoreline/<id>.geojson; the
platform build checks that every feature keeps its source date and NOAA
creator and lies inside the region, then writes the published form to
dist/regions/<id>/shoreline.geojson (schema_version 2). A region without an
import publishes no shoreline.

The published form (schema_version 2) carries the same lines and the same
source fields in about a third of the bytes, because the v2 map draws it at
first paint (scripts/startup-budget.json):

- Lines are grouped by their exact source properties: every import feature
  with one set of properties (which include its source_tile) becomes one line
  of a single MultiLineString feature carrying that set once. A click on any
  line still reads its own SOURCE_ID, dates, method and HOR_ACC.
- Coordinates are rounded to 5 decimals. The import's lines are NOAA's zoom-12
  display tiles, 4096 units a side (display_quantisation_m, about 1.96 m at
  35.85° N): one unit is 360 / 2^24 = 2.15e-5° of longitude and at least
  1.74e-5° of latitude across the region. A 5-decimal rounding moves a point at
  most 5e-6°, under half a unit, so every tile vertex keeps its own grid
  position (tests/unit/test_cusp_shoreline.py re-snaps them); 4 decimals
  (up to 5e-5°) would merge neighbouring vertices.

The overview form (#617, shoreline-overview.geojson, written by
skippercast.platform.startup_forms) is what the map draws below
OVERVIEW_MAX_ZOOM: each line simplified (Douglas-Peucker) to
OVERVIEW_TOLERANCE_M, and the closed rings narrower than OVERVIEW_MIN_RING_M
(single rocks, most under 10 m across) left out. At MapLibre zoom 11, where
the map opens, one pixel is about 31 m here: the tolerance moves the drawn line
under a third of a pixel and a dropped ring is under one pixel. Just below
zoom 12 (about 15.6 m a pixel, the worst case) those are about 0.6 and 1.3
pixels. Features, ids and properties are the published form's, so a click
reads the same source fields.
"""
from pathlib import Path
import json
import math
import re

from .contracts import atomic_json, read_json

DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
SCHEMA_VERSION = 2
DECIMALS = 5
OVERVIEW_TOLERANCE_M = 10
OVERVIEW_MIN_RING_M = 20
# web/map/coastline.ts SHORELINE_DETAIL_ZOOM is the MapLibre zoom the full form loads from.
OVERVIEW_MAX_ZOOM = 12


def check_shoreline(collection, region):
    """Raise ValueError unless the collection is a dated, NOAA-created, in-region CUSP extract."""
    provenance = collection.get('provenance') or {}
    if collection.get('type') != 'FeatureCollection' or provenance.get('region_id') != region['id']:
        raise ValueError(f"Shoreline for {region['id']} is not its CUSP FeatureCollection")
    if provenance.get('source_id') != 'noaa-cusp-shoreline' or provenance.get('features') != len(collection['features']):
        raise ValueError(f"Shoreline for {region['id']} has incomplete provenance")
    west, south, east, north = region['bounds']
    for feature in collection['features']:
        properties, geometry = feature.get('properties') or {}, feature.get('geometry') or {}
        if not DATE.fullmatch(str(properties.get('source_date'))) or properties.get('DAT_SET_CR') != 'NOAA':
            raise ValueError(f"Shoreline feature {feature.get('id')} lacks a source date or a NOAA creator")
        lines = {'LineString': [geometry.get('coordinates')], 'MultiLineString': geometry.get('coordinates')}.get(geometry.get('type'))
        if not lines or any(len(line) < 2 or any(not (west <= x <= east and south <= y <= north) for x, y in line)
                            for line in lines):
            raise ValueError(f"Shoreline feature {feature.get('id')} is not a line inside {region['id']}")


def feature_lines(geometry):
    """The lines of a LineString or MultiLineString geometry."""
    return [geometry['coordinates']] if geometry['type'] == 'LineString' else geometry['coordinates']


def slim_shoreline(collection):
    """The published form of a checked import: one MultiLineString per distinct property set, 5-decimal coordinates."""
    groups = {}
    for feature in collection['features']:
        key = json.dumps(feature['properties'], sort_keys=True, ensure_ascii=False)
        group = groups.setdefault(key, {'properties': feature['properties'], 'lines': []})
        group['lines'] += [[[round(x, DECIMALS), round(y, DECIMALS)] for x, y in line] for line in feature_lines(feature['geometry'])]
    features, per_tile = [], {}
    for group in groups.values():
        tile = str(group['properties'].get('source_tile', 'region')).replace('/', '-')
        per_tile[tile] = per_tile.get(tile, -1) + 1
        features.append({'type': 'Feature', 'id': f'cusp-{tile}-{per_tile[tile]}',
                         'geometry': {'type': 'MultiLineString', 'coordinates': group['lines']},
                         'properties': group['properties']})
    provenance = {**collection['provenance'], 'features': len(features),
                  'source_features': len(collection['features']), 'coordinate_decimals': DECIMALS,
                  'published_form': 'Import features with identical source properties are one MultiLineString '
                                    'feature; each line keeps those properties. Coordinates are rounded to 5 decimals, '
                                    'under half the zoom-12 tile unit, so every tile vertex keeps its grid position.'}
    return {'type': 'FeatureCollection', 'schema_version': SCHEMA_VERSION, 'provenance': provenance, 'features': features}


def publish_shoreline(root, region, output):
    """Write the checked import's published form to output/shoreline.geojson; remove a stale copy when there is none."""
    source, target = Path(root) / 'catalog/shoreline' / f"{region['id']}.geojson", Path(output) / 'shoreline.geojson'
    if not source.is_file():
        target.unlink(missing_ok=True)
        return None
    collection = read_json(source)
    check_shoreline(collection, region)
    published = slim_shoreline(collection)
    check_shoreline(published, region)
    atomic_json(target, published)
    return f"regions/{region['id']}/shoreline.geojson"


def _metres(latitude):
    """Metres per degree of longitude and latitude near `latitude` (a local equirectangular scale)."""
    return 111_320 * math.cos(math.radians(latitude)), 110_540


def simplify(line, tolerance, scale):
    """Douglas-Peucker: the vertices of `line` needed to stay within `tolerance` metres of it."""
    if len(line) < 3:
        return [list(p) for p in line]
    kx, ky = scale
    xy = [(x * kx, y * ky) for x, y in line]
    keep, stack = {0, len(line) - 1}, [(0, len(line) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = xy[a], xy[b]
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        far, at = -1.0, -1
        for i in range(a + 1, b):
            px, py = xy[i]
            t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
            d = math.hypot(px - ax - t * dx, py - ay - t * dy)
            if d > far:
                far, at = d, i
        if far > tolerance:
            keep.add(at)
            stack += [(a, at), (at, b)]
    return [list(line[i]) for i in sorted(keep)]


def _span(line, scale):
    kx, ky = scale
    return max((max(x for x, _ in line) - min(x for x, _ in line)) * kx, (max(y for _, y in line) - min(y for _, y in line)) * ky)


def overview_shoreline(published, source):
    """The overview form of a published shoreline (see the module notes); `source` is its derived_from block."""
    west, south, east, north = published['provenance']['bounds']
    scale = _metres((south + north) / 2)
    features = []
    for feature in published['features']:
        lines = [simplify(line, OVERVIEW_TOLERANCE_M, scale) for line in feature_lines(feature['geometry'])
                 if not (line[0] == line[-1] and _span(line, scale) < OVERVIEW_MIN_RING_M)]
        if lines:
            features.append({**feature, 'geometry': {'type': 'MultiLineString', 'coordinates': lines}})
    provenance = {**published['provenance'], 'features': len(features),
                  'overview': {'tolerance_m': OVERVIEW_TOLERANCE_M, 'min_ring_m': OVERVIEW_MIN_RING_M, 'max_zoom': OVERVIEW_MAX_ZOOM,
                               'note': 'Drawn below max_zoom only; the full published shoreline loads at and above it.'}}
    return {'type': 'FeatureCollection', 'schema_version': SCHEMA_VERSION, 'startup_form': 'shoreline-overview',
            'derived_from': source, 'provenance': provenance, 'features': features}
