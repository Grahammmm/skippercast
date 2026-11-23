#!/usr/bin/env python3
"""Check local fixture inventories without opening or modifying tile archives.

Each inventory is a JSON array of [z, x, y] triples (at most 1 MiB).
The result lists unique IDs in numeric XYZ order. Exit 0 for a pass, 1 for
lost fallback or ineligible emitted fine tiles, and 2 for invalid input.
"""
import argparse
import json
from pathlib import Path

from skippercast.relief.fine_emitted_tiles import audit_emitted_tiles
from skippercast.relief.pmtiles_v3 import Tile

MAX_INVENTORY_BYTES = 1 << 20
COARSE_MAX_ZOOM = 15


def _read_inventory(path: Path) -> set[Tile]:
    with path.open('rb') as source:
        data = source.read(MAX_INVENTORY_BYTES + 1)
    if len(data) > MAX_INVENTORY_BYTES:
        raise ValueError('inventory exceeds 1 MiB')
    rows = json.loads(data)
    if not isinstance(rows, list):
        raise ValueError('inventory must be a JSON array of [z, x, y] triples')
    tiles = set()
    for index, row in enumerate(rows):
        if (not isinstance(row, list) or len(row) != 3
                or any(type(value) is not int for value in row)):
            raise ValueError(f'inventory row {index} must be an integer [z, x, y] triple')
        z, x, y = row
        if not (0 <= z <= 17 and 0 <= x < (1 << z) and 0 <= y < (1 << z)):
            raise ValueError(f'inventory row {index} is outside the supported XYZ grid')
        tiles.add((z, x, y))
    return tiles


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Check coarse fallback and emitted fine eligibility.')
    parser.add_argument('baseline', type=Path, help='baseline JSON XYZ inventory')
    parser.add_argument('candidate', type=Path, help='candidate JSON XYZ inventory')
    parser.add_argument('proof', type=Path, nargs='+', help='one or two local fine-proof GeoTIFFs')
    args = parser.parse_args(argv)
    try:
        baseline = _read_inventory(args.baseline)
        candidate = _read_inventory(args.candidate)
        fine = audit_emitted_tiles(sorted(candidate), args.proof)
    except (OSError, ValueError, RecursionError) as exc:
        parser.error(str(exc))

    lost_fallback = sorted(tile for tile in baseline - candidate if tile[0] <= COARSE_MAX_ZOOM)
    passed = not lost_fallback and fine.passed
    print(json.dumps({
        'passed': passed,
        'lost_fallback': lost_fallback,
        'certified': fine.certified,
        'missing_proof': fine.missing_proof,
        'uncertified': fine.uncertified,
    }))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
