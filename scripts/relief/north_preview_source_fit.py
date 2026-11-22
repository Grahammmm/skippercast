#!/usr/bin/env python3
"""Classify North preview centers against explicitly supplied synthetic footprints.

Run from the checkout root with the survey extra installed:
    python -m scripts.relief.north_preview_source_fit footprints.json

The JSON object maps North release IDs to WGS84 (longitude, latitude) GeoJSON
Polygon or MultiPolygon geometries. Omit a region when its fixture is unavailable.
This is a center-only fixture check, not evidence of measured support, preview
window coverage, source rights, or release readiness.
"""

import argparse
import json
from pathlib import Path

from shapely.errors import GEOSException
from shapely.geometry import Point, shape

from scripts.relief.north_seam_windows import NORTH_RELEASES
from skippercast.relief import render_config
from skippercast.relief.package import decode_document


def _polygon(region, geometry):
    try:
        if not isinstance(geometry, dict) or geometry.get('type') not in ('Polygon', 'MultiPolygon'):
            raise ValueError('expected a GeoJSON Polygon or MultiPolygon')
        polygon = shape(geometry)
        if polygon.is_empty or not polygon.is_valid or polygon.has_z:
            raise ValueError('expected a valid, nonempty 2D polygon')
        west, south, east, north = polygon.bounds
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError('coordinates must be WGS84 longitude and latitude')
        return polygon
    except (GEOSException, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'{region}: invalid synthetic footprint: {exc}') from exc


def source_fit(footprints):
    """Report every recipe center; boundaries and holes do not count as inside."""
    if not isinstance(footprints, dict) or footprints.keys() - set(NORTH_RELEASES):
        raise ValueError('expected synthetic footprints keyed by North release ID')
    polygons = {region: _polygon(region, geom) for region, geom in footprints.items()}
    regions = {}
    for region in NORTH_RELEASES:
        polygon = polygons.get(region)
        rows = []
        for preview in render_config.previews(region):
            center = preview['center']
            if polygon is None:
                status = 'unavailable'
            else:
                status = 'inside' if polygon.contains(Point(*center)) else 'outside'
            rows.append({'id': preview['id'], 'center': center, 'status': status})
        regions[region] = rows
    return {
        'scope': 'Synthetic footprint geometry only; not evidence of measured support.',
        'regions': regions,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Classify North preview centers against synthetic footprints.')
    parser.add_argument('footprints', type=Path, help='local JSON of synthetic footprints only')
    args = parser.parse_args(argv)
    try:
        report = source_fit(decode_document(args.footprints.read_bytes()))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
