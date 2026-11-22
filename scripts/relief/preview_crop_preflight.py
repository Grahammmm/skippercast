"""Check configured Central Coast preview squares against a local package footprint.

Run from the repo root with ``python -m scripts.relief.preview_crop_preflight
--region REGION [--footprint FOOTPRINT.geojson]``. The footprint is a WGS84
(lon, lat) GeoJSON Polygon or MultiPolygon, optionally wrapped in a Feature.
The configured size is the full side of the square in WGS84 / UTM zone 10N.
Shortfall reports uncovered area and the length outside the footprint on each
crop edge. This does not check wet pixels or run a render stage.
Exit 0 if all crops fit, 1 for shortfall, 2 for unknown or bad input.
"""

import argparse
from pathlib import Path

from pyproj import Transformer
from pyproj.exceptions import ProjError
from shapely import from_geojson, transform
from shapely.errors import GEOSException
from shapely.geometry import LineString, box

from scripts.relief.central_camera_bounds import REGIONS
from skippercast.paths import repo_root
from skippercast.relief import render_config


def _metric_footprint(path, projection):
    if path is None:
        return None
    try:
        footprint = from_geojson(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    if footprint.geom_type not in ('Polygon', 'MultiPolygon') or footprint.is_empty or not footprint.is_valid:
        raise ValueError('expected a nonempty, valid Polygon or MultiPolygon')
    west, south, east, north = footprint.bounds
    if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
        raise ValueError('expected WGS84 longitude/latitude coordinates')
    # Densify lon/lat edges before projection instead of replacing long curved
    # projected edges with a single chord. Retain holes and separate polygons.
    metric = transform(footprint.segmentize(0.001), projection.transform, interleaved=False)
    if not metric.is_valid:
        raise ValueError('footprint does not project to a valid Central Coast polygon')
    return metric


def _check_camera(preview, footprint, projection):
    if footprint is None:
        return 'UNKNOWN', 'footprint missing; uncovered_m2=unknown; edge_shortfall_m=unknown'
    x, y = projection.transform(*preview['center'], errcheck=True)
    half = preview['size_m'] / 2
    west, south, east, north = x - half, y - half, x + half, y + half
    crop = box(west, south, east, north)
    if footprint.covers(crop):
        return 'CONTAINED', 'uncovered_m2=0; edge_shortfall_m=0'

    sw, se, ne, nw = (west, south), (east, south), (east, north), (west, north)
    edges = {'west': (sw, nw), 'south': (sw, se), 'east': (se, ne), 'north': (nw, ne)}
    # Edge shortfall is the length outside the footprint on each side, not a
    # distance to the footprint's bounding box. Area also exposes interior holes.
    lengths = ','.join(f'{side}:{LineString(edge).difference(footprint).length:.6g}'
                       for side, edge in edges.items())
    area = crop.difference(footprint).area
    return 'SHORTFALL', f'uncovered_m2={area:.6g}; edge_shortfall_m={lengths}'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region', choices=REGIONS, required=True)
    parser.add_argument('--footprint', type=Path)
    args = parser.parse_args(argv)
    if not (repo_root() / 'regions' / args.region / 'render.json').is_file():
        parser.error(f'{args.region}: missing render.json')
    previews = render_config.previews(args.region)
    # UTM zone 10N gives the Central Coast a common metre grid. The configured
    # size is the full side of a grid-aligned square; zoom does not change it.
    projection = Transformer.from_crs('EPSG:4326', 'EPSG:32610', always_xy=True)
    try:
        footprint = _metric_footprint(args.footprint, projection)
    except (OSError, ValueError, GEOSException, ProjError) as exc:
        parser.error(f'invalid package footprint: {exc}')

    result = 2 if footprint is None else 0
    for preview in previews:
        status, details = _check_camera(preview, footprint, projection)
        print(f"{status} {args.region}/{preview['id']} {details}")
        if status == 'SHORTFALL':
            result = 1
    return result


if __name__ == '__main__':
    raise SystemExit(main())
