#!/usr/bin/env python3
"""Select cross-region seam QA candidates from explicit saved fixture files.

The wire labels are properties.tier (including explicit "none"), as used by
web/map/survey-detail.ts and survey-detail-tap.ts. Grid size, source and date
are not used to relabel or qualify a footprint. No label winner is selected.
"""

import argparse
import json
import math
from collections import defaultdict
from functools import partial
from pathlib import Path

from pyproj import Transformer
from pyproj.exceptions import ProjError
from shapely import intersection, transform, union_all
from shapely.errors import ShapelyError
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

AREA_CRS = 'EPSG:3310'
TIERS = frozenset({'1m-measured', '2m', '5m', 'estimated', 'none'})


def _valid_ring(ring):
    # Check the wire structure before GEOS, which can silently close open rings.
    return (
        isinstance(ring, list) and len(ring) >= 4 and ring[0] == ring[-1]
        and all(isinstance(point, list) and len(point) == 2
                and all(type(v) in (int, float) and -limit <= v <= limit
                        for v, limit in zip(point, (180, 90))) for point in ring)
    )


def _polygon_geometry(geometry):
    if not isinstance(geometry, dict):
        raise ValueError('expected Polygon or MultiPolygon geometry')
    kind, coordinates = geometry.get('type'), geometry.get('coordinates')
    polygons = [coordinates] if kind == 'Polygon' else coordinates if kind == 'MultiPolygon' else None
    if not isinstance(polygons, list) or not polygons or not all(
        isinstance(polygon, list) and polygon and all(_valid_ring(ring) for ring in polygon)
        for polygon in polygons
    ):
        raise ValueError('invalid polygon coordinates')
    geom = shape(geometry)
    if not geom.is_valid or geom.is_empty or geom.area <= 0:
        raise ValueError('invalid polygon topology')
    return geom


def _read_detail(path: Path) -> tuple[str, dict[str, BaseGeometry]]:
    collection = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(collection, dict) or collection.get('type') != 'FeatureCollection':
        raise ValueError('expected a survey-detail FeatureCollection')
    region, features = collection.get('region'), collection.get('features')
    if not isinstance(region, str) or not region.strip() or not isinstance(features, list):
        raise ValueError('expected a region ID and a features array')
    if 'crs' in collection:
        raise ValueError('expected survey-detail GeoJSON in longitude/latitude without a CRS override')

    groups = defaultdict(list)
    for index, feature in enumerate(features):
        try:
            if not isinstance(feature, dict) or feature.get('type') != 'Feature':
                raise ValueError('expected a GeoJSON Feature')
            geometry = _polygon_geometry(feature.get('geometry'))
            props = feature.get('properties')
            tier = props.get('tier') if isinstance(props, dict) else None
            if not isinstance(tier, str) or tier not in TIERS:
                raise ValueError('missing or unknown properties.tier')
        except (ShapelyError, ValueError) as exc:
            raise ValueError(f'feature {index}: {exc}') from exc
        groups[tier].append(geometry)
    # A pair describes unique area, not the sum of overlapping feature matches.
    return region, {tier: union_all(geoms) for tier, geoms in groups.items()}


def review(paths: list[Path]) -> dict:
    """Read one or two files; only two distinct regions can yield comparisons.

    Keep each tier aligned with its region (both in sorted region order).
    Different tier pairs can cover the same ground; do not sum across pairs.
    Incomplete input withholds findings, so [] never implies zero on its own.
    """
    if not 1 <= len(paths) <= 2:
        raise ValueError('provide one or two survey-detail fixture files')
    report = {'status': 'incomplete', 'area_crs': AREA_CRS, 'regions': [], 'disagreements': []}
    inputs = []
    for number, path in enumerate(paths, 1):
        try:
            inputs.append(_read_detail(path))
        except (OSError, UnicodeError, ShapelyError, ValueError) as exc:
            reason = exc.strerror if isinstance(exc, OSError) else str(exc)
            return {**report, 'issue': f'input {number}: {reason}'}
    report['regions'] = sorted(region for region, _ in inputs)
    if len(set(report['regions'])) != 2:
        return {**report, 'issue': 'two distinct regions are needed for a comparison'}

    (left, left_tiers), (right, right_tiers) = sorted(inputs, key=lambda detail: detail[0])
    project = Transformer.from_crs('EPSG:4326', AREA_CRS, always_xy=True)
    findings = []
    try:
        for left_tier, left_geometry in sorted(left_tiers.items()):
            for right_tier, right_geometry in sorted(right_tiers.items()):
                if left_tier == right_tier:
                    continue
                # Intersect the saved GeoJSON shapes before projection. Projecting
                # independently can turn a shared edge into a sliver when just
                # one region has intermediate vertices along that edge.
                overlap = intersection(left_geometry, right_geometry)
                if overlap.area <= 0:
                    continue
                projected = transform(overlap, partial(project.transform, errcheck=True), interleaved=False)
                area = projected.area
                if not projected.is_valid or not math.isfinite(area) or area <= 0:
                    return {**report, 'issue': 'invalid projected intersection'}
                findings.append({'regions': [left, right], 'tiers': [left_tier, right_tier], 'area_m2': area})
    except (ProjError, ShapelyError):
        return {**report, 'issue': 'could not intersect or project the footprints'}
    return {**report, 'status': 'complete', 'disagreements': findings}


def main() -> int:
    parser = argparse.ArgumentParser(description='Select cross-region seam QA candidates from saved fixtures.')
    parser.add_argument('fixtures', type=Path, nargs='+', help='one or two local survey-detail fixture files')
    args = parser.parse_args()
    if len(args.fixtures) > 2:
        parser.error('provide at most two survey-detail fixture files')
    report = review(args.fixtures)
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
