#!/usr/bin/env python3
"""Report North Coast seam-review planning bounds as JSON on stdout.

Only the configured release rectangles are read. The candidate intersections
are QA planning bounds, not shoreline or coverage evidence or a render config.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal, TypedDict

# Geographic adjacency is fixed south to north, not inferred from filenames,
# catalog order, or whether the rectangles happen to intersect.
NORTH_RELEASES = (
    'point-reyes-pigeon',
    'bodega-point-reyes',
    'point-arena-bodega',
    'fort-bragg-point-arena',
    'shelter-cove-north-mendocino',
    'humboldt-bay-cape-mendocino',
    'trinidad-klamath',
    'crescent-city',
)

Bounds = tuple[float, float, float, float]  # west, south, east, north in degrees
JoinStatus = Literal['overlap', 'edge_contact', 'point_contact', 'gap']


class Join(TypedDict):
    regions: tuple[str, str]
    status: JoinStatus
    candidate_window: Bounds | None


def _release_bounds(root: Path, region: str) -> Bounds:
    path = root / 'regions' / region / 'region.json'
    config = json.loads(path.read_text(encoding='utf-8'))
    bounds = config.get('bounds') if isinstance(config, dict) else None
    if not isinstance(bounds, list) or len(bounds) != 4 or any(
        type(value) not in (int, float) for value in bounds
    ):
        raise ValueError(f'{region}: expected four numeric release bounds')
    west, south, east, north = bounds
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError(f'{region}: invalid WGS84 release rectangle')
    return west, south, east, north


def plan_windows(root: Path) -> list[Join]:
    """Return all seven adjacent joins; only positive-area intersections get windows."""
    bounds = {region: _release_bounds(root, region) for region in NORTH_RELEASES}
    joins: list[Join] = []
    for southern, northern in zip(NORTH_RELEASES, NORTH_RELEASES[1:]):
        w1, s1, e1, n1 = bounds[southern]
        w2, s2, e2, n2 = bounds[northern]
        west, south = max(w1, w2), max(s1, s2)
        east, north = min(e1, e2), min(n1, n2)
        status: JoinStatus
        window = None
        if west > east or south > north:
            status = 'gap'
        elif west == east and south == north:
            status = 'point_contact'
        elif west == east or south == north:
            status = 'edge_contact'
        else:
            status = 'overlap'
            window = (west, south, east, north)
        joins.append({'regions': (southern, northern), 'status': status, 'candidate_window': window})
    return joins


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    try:
        joins = plan_windows(args.root)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({
        'purpose': 'QA planning bounds only; not shoreline or coverage evidence or a render config.',
        'crs': 'WGS84',
        'bounds_order': ['west', 'south', 'east', 'north'],
        'joins': joins,
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
