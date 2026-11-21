#!/usr/bin/env python3
"""Check configured release bounds, not shoreline geometry or live tiles."""

from __future__ import annotations

import argparse
import json
import re
import sys
from itertools import combinations
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[2]
ISLANDS = ('channel-islands-north', 'outer-islands-borderland')
Bounds = tuple[float, float, float, float]  # west, south, east, north


class Regions(TypedDict):
    south: float
    north: float
    release: dict[str, Bounds]
    islands: dict[str, Bounds]


def load_regions(root: Path) -> Regions:
    """Take membership from the packaged index and geometry from source configs."""
    def bounds(region_id: str) -> Bounds:
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', region_id):
            raise ValueError(f'invalid region id: {region_id!r}')
        path = root / 'regions' / region_id / 'region.json'
        west, south, east, north = json.loads(path.read_text(encoding='utf-8'))['bounds']
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError(f'invalid bounds for {region_id}')
        return west, south, east, north

    index = json.loads((root / 'dist/regions/index.json').read_text(encoding='utf-8'))
    return {
        'south': bounds('san-diego')[1],
        'north': bounds('crescent-city')[3],
        'release': {entry['id']: bounds(entry['id']) for entry in index['regions']},
        'islands': {region_id: bounds(region_id) for region_id in ISLANDS},
    }


def coverage(regions: Regions) -> dict:
    """Report gaps and pairwise latitude overlaps within the anchor window.

    Only positive-width intervals count: touching edges are not gaps or
    overlaps. Island containment uses all four bounds, including shared edges;
    if several release regions qualify, report the lexically first ID.
    """
    south, north = regions['south'], regions['north']
    if not south < north:
        raise ValueError('south anchor must be below north anchor')

    release = regions['release']
    spans = []
    for region_id, (_, low, _, high) in release.items():
        start, end = max(south, low), min(north, high)
        if start < end:
            spans.append((start, end, region_id))
    spans.sort()

    gaps = []
    covered_to = south
    for start, end, _ in spans:
        if start > covered_to:
            gaps.append([covered_to, start])
        covered_to = max(covered_to, end)
    if covered_to < north:
        gaps.append([covered_to, north])

    overlaps = []
    for (start_a, end_a, id_a), (start_b, end_b, id_b) in combinations(spans, 2):
        start, end = max(start_a, start_b), min(end_a, end_b)
        if start < end:
            overlaps.append({'regions': [id_a, id_b], 'latitudes': [start, end]})

    islands_inside = {}
    ordered_release = sorted(release.items())
    for island_id, (west, low, east, high) in sorted(regions['islands'].items()):
        islands_inside[island_id] = next((
            region_id for region_id, (w, s, e, n) in ordered_release
            if w <= west and s <= low and east <= e and high <= n
        ), None)

    return {
        'gaps': gaps,
        'overlaps': overlaps,
        'islands_inside': islands_inside,
        'ok': not gaps and all(region_id is not None for region_id in islands_inside.values()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--json', action='store_true', help='print machine-readable JSON')
    args = parser.parse_args(argv)
    try:
        report = coverage(load_regions(ROOT))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Coast coverage could not be checked: {exc}', file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print('Check      | Region(s) / island           | Result')
        for low, high in report['gaps']:
            print(f'Gap        | -                            | {low} to {high} N')
        for row in report['overlaps']:
            low, high = row['latitudes']
            print(f'Overlap    | {" / ".join(row["regions"])} | {low} to {high} N')
        for island, container in report['islands_inside'].items():
            print(f'Island     | {island} | {container or "outside"}')
        print(f'Configured coast coverage: {"OK" if report["ok"] else "NOT OK"}')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
