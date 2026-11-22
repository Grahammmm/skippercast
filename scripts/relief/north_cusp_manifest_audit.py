"""Inventory saved CUSP custody rows for one North water frame.

Run from the repository root with ``python -m scripts.relief.north_cusp_manifest_audit
--region-config FILE --shoreline-manifest FILE``. A served row records a pin; this
report validates its syntax, not the tile bytes or the usability of shoreline.
"""

import argparse
import json
import re
from pathlib import Path

from skippercast.relief.water import _cusp, _frame_bounds

_TILE_ID = re.compile(r'(?:0|[1-9][0-9]*)/(?:0|[1-9][0-9]*)/(?:0|[1-9][0-9]*)')
_SHA256 = re.compile(r'[0-9a-fA-F]{64}')
_STATES = ('served', 'unavailable', 'not_listed')


def _read_object(path):
    doc = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(doc, dict):
        raise ValueError('expected a JSON object')
    return doc


def _bounds(entry):
    bounds = entry.get('bounds') if isinstance(entry, dict) else None
    if not (isinstance(bounds, list) and len(bounds) == 4
            and all(type(value) in (int, float) for value in bounds)
            and -180 <= bounds[0] < bounds[2] <= 180
            and -90 <= bounds[1] < bounds[3] <= 90):
        raise ValueError('expected ordered WGS84 bounds')
    return bounds


def _read_rows(doc):
    source_rows = doc.get('tiles')
    if not isinstance(source_rows, list):
        raise ValueError('custody manifest requires a tiles array')
    rows = {}
    for number, row in enumerate(source_rows, 1):
        tile = row.get('tile') if isinstance(row, dict) else None
        if not isinstance(tile, str) or not _TILE_ID.fullmatch(tile):
            raise ValueError(f'tile row {number}: expected a canonical z/x/y tile ID')
        status = row.get('status')
        if status not in ('served', 'unavailable'):
            raise ValueError(f'tile {tile}: expected served or unavailable status')
        digest = row.get('sha256')
        if status == 'served' or 'sha256' in row:
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                raise ValueError(f'tile {tile}: invalid SHA-256 pin')
        if status == 'served' and not (isinstance(row.get('path'), str) and row['path'].strip()):
            raise ValueError(f'tile {tile}: served row requires a recorded path')
        if tile in rows:
            prior = rows[tile]['status']
            issue = 'duplicate' if prior == status else 'conflicting'
            raise ValueError(f'{issue} rows for tile {tile}: {prior} and {status}')
        rows[tile] = row
    return rows


def audit(region_config: Path, shoreline_manifest: Path) -> dict:
    """Read only the explicit region config and manifest; report frame tile states."""
    config = _read_object(region_config)
    region = config.get('id')
    if not isinstance(region, str) or not region.strip():
        raise ValueError('region config requires an id')
    bounds = _bounds(config)
    frame = _frame_bounds(bounds)

    manifest = _read_object(shoreline_manifest)
    regions = manifest.get('regions')
    try:
        covered = _bounds(regions.get(region) if isinstance(regions, dict) else None)
    except ValueError:
        raise ValueError(f'custody manifest does not declare valid bounds for region {region}') from None
    if not (covered[0] <= bounds[0] and covered[1] <= bounds[1]
            and covered[2] >= bounds[2] and covered[3] >= bounds[3]):
        raise ValueError(f'custody manifest bounds do not cover region {region}')
    rows = _read_rows(manifest)

    tiles = []
    counts = dict.fromkeys(_STATES, 0)
    for z, x, y in _cusp().tiles_for(frame):
        tile = f'{z}/{x}/{y}'
        row = rows.get(tile)
        status = row['status'] if row is not None else 'not_listed'
        result = {'tile': tile, 'status': status}
        if status == 'served':
            result['sha256'] = rows[tile]['sha256']
        tiles.append(result)
        counts[status] += 1
    return {
        'kind': 'custody_inventory_only',
        'region': region,
        'frame_wgs84': list(frame),
        'required_tile_count': len(tiles),
        'outside_frame_row_count': len(rows) - counts['served'] - counts['unavailable'],
        'counts': counts,
        'tiles': tiles,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Inventory saved CUSP custody rows for one water frame.')
    parser.add_argument('--region-config', type=Path, required=True)
    parser.add_argument('--shoreline-manifest', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = audit(args.region_config, args.shoreline_manifest)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
