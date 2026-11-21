#!/usr/bin/env python3
"""Explain saved North water-stage evidence without reopening shoreline or geometry."""

import argparse
import json
import math
from pathlib import Path

from skippercast.relief import receipts

_AUDIT = 'water/water.json'


def _read_audit(region: receipts.Region) -> dict:
    receipt_path = region.receipt_path('water')
    if receipt_path.resolve() != receipt_path:
        raise ValueError('water receipt must not be redirected')
    receipt = receipts.read_receipt(receipt_path)
    if (receipt is None or receipts.validate_receipt(receipt, region.id, 'water', None)
            or receipt['status'] != 'ok'):
        raise ValueError('missing, invalid or unsuccessful water receipt')
    rows = [row for row in receipt['outputs'] if row['path'] == _AUDIT]
    if len(rows) != 1:
        raise ValueError('water receipt must name exactly one water/water.json output')

    path = region.resolve(_AUDIT)
    if path.resolve() != path or not path.is_file():
        raise ValueError('missing or redirected water audit')
    body = path.read_bytes()
    row = rows[0]
    if len(body) != row['bytes'] or receipts.sha256_bytes(body) != row['sha256']:
        raise ValueError('water audit does not match the receipt output digest or size')
    # Parse the same bytes that were hashed, not a second read of the file.
    audit = json.loads(body)
    if not isinstance(audit, dict) or audit.get('region') != region.id:
        raise ValueError('water audit does not identify the requested region')
    return audit


def _positive_distance(value: object) -> bool:
    return ((type(value) is int and value > 0)
            or (type(value) is float and math.isfinite(value) and value > 0))


def summarize(out_root: Path, region_id: str) -> dict:
    """Read only stages/water.json and water/water.json under OUT/<region>.

    A verified result binds the audit bytes to the supplied receipt, not the
    polygon or a new displacement verdict. The producer sets closing distance
    from max stated HOR_ACC and owns the displacement checks and cut exceptions.
    Missing fields are never filled from receipt parameters, defaults, or other
    audit fields. A digest-bound partial audit exposes only its usable evidence.
    """
    try:
        region = receipts.Region(out_root, region_id)
        audit = _read_audit(region)
    except (OSError, RuntimeError, UnicodeError, json.JSONDecodeError):
        return {'status': 'incomplete', 'reason': 'unreadable water receipt or audit'}
    except ValueError as exc:
        return {'status': 'incomplete', 'reason': str(exc)}

    result: dict[str, object] = {'region': region_id, 'status': 'verified'}
    missing: list[str] = []
    accuracies = audit.get('hor_acc_values_m')
    if isinstance(accuracies, list) and accuracies and all(map(_positive_distance, accuracies)):
        result['max_stated_accuracy_m'] = max(accuracies)
    else:
        missing.append('hor_acc_values_m')
    close_m = audit.get('close_m')
    if _positive_distance(close_m):
        result['close_m'] = close_m
    else:
        missing.append('close_m')
    unavailable = audit.get('unavailable_tiles')
    if isinstance(unavailable, list) and all(isinstance(tile, str) and tile for tile in unavailable):
        result['unavailable_tiles'] = unavailable
    else:
        missing.append('unavailable_tiles')
    if missing:
        result.update(status='incomplete', missing_or_invalid=missing)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out_root', type=Path, help='saved output root containing the region directory')
    parser.add_argument('region', help='North region ID in the saved output root')
    args = parser.parse_args()
    report = summarize(args.out_root, args.region)
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
