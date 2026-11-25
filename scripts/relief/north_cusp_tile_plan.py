#!/usr/bin/env python3
"""List expected North Coast CUSP tiles and bound their payload bytes, offline.

Run from an editable checkout with the survey extra. This is a plan, not a
custody manifest: it does not establish availability, measured bytes or rights.
"""

import argparse
import json
from pathlib import Path

from skippercast.relief import water

# The eight NorCal entries in docs/operations/coast-statewide-runsheet.md.
NORTH_REGIONS = (
    'point-reyes-pigeon',
    'bodega-point-reyes',
    'point-arena-bodega',
    'fort-bragg-point-arena',
    'shelter-cove-north-mendocino',
    'humboldt-bay-cape-mendocino',
    'trinidad-klamath',
    'crescent-city',
)


def tile_plan(config_root: Path, budget_bytes: int | None = None) -> dict:
    """Read only regions/<id>/region.json; compare the bound to an explicit ceiling."""
    if budget_bytes is not None and (type(budget_bytes) is not int or budget_bytes < 0):
        raise ValueError('budget must be a nonnegative integer number of bytes')

    cusp = water._cusp()
    tiles = set()
    frames = {}
    for region in NORTH_REGIONS:
        bounds = cusp.checked_bounds(region, root=config_root)
        # Use the exact frame and tile reader from water.build, not a second
        # padding or rounding rule. The current water stage snaps inward.
        frame = water._frame_bounds(bounds)
        frames[region] = list(frame)
        tiles.update(cusp.tiles_for(frame))

    worst_case = len(tiles) * cusp.MAX_TILE_BYTES
    status = 'not_supplied'
    if budget_bytes is not None:
        status = 'exceeded' if worst_case > budget_bytes else 'within_budget'
    return {
        'zoom': cusp.ZOOM,
        'frames_wgs84': frames,
        'expected_tile_ids': [f'{z}/{x}/{y}' for z, x, y in sorted(tiles)],
        'tile_count': len(tiles),
        'max_tile_bytes': cusp.MAX_TILE_BYTES,
        'worst_case_bytes': worst_case,
        'budget_bytes': budget_bytes,
        'budget_status': status,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config_root', type=Path, help='directory containing regions/<id>/region.json')
    parser.add_argument('--budget-bytes', type=int, help='explicit custody ceiling in bytes; no default')
    args = parser.parse_args(argv)
    try:
        report = tile_plan(args.config_root, args.budget_bytes)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True, indent=2))
    return int(report['budget_status'] == 'exceeded')


if __name__ == '__main__':
    raise SystemExit(main())
