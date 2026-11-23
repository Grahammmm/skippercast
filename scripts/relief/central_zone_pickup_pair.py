#!/usr/bin/env python3
"""Extract Zone's exact coarse and water pins from an explicit, stable saved OUT.

Only the current producer receipts and their recorded outputs are read. This
is a byte check of a saved pair, not a check of upstream currency, stage
readiness, source rights, or authorization. Do not point it at an active run.
On success, stdout contains only the runner fragment: ``inputs``,
``coarse_source`` (verified report family), and ``coarse_date`` (verified
report date or null). A refusal exits 1 with only an ``error`` member.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from skippercast.relief import receipts


def _saved_path(root: Path, path: Path) -> bool:
    return (path != root and path.is_relative_to(root) and '..' not in path.parts
            and path.resolve() == path)


def _producer(region: receipts.Region, stage: str, *names: str) -> tuple[dict, bytes]:
    path = region.receipt_path(stage)
    if not _saved_path(region.dir, path) or not path.is_file():
        raise ValueError(f'{stage}: missing or noncanonical receipt')
    doc = receipts.read_receipt(path)
    if doc is None or receipts.validate_receipt(doc, region.id, stage, None) or doc['status'] != 'ok':
        raise ValueError(f'{stage}: expected an ok receipt for the selected region')

    # Every real producer output belongs to this receipt's target, not an old
    # generation or a separate stage. Never search siblings or receipt history.
    if not isinstance(doc.get('target'), str):
        raise ValueError(f'{stage}: missing output target')
    target = region.resolve(doc['target'])
    if not _saved_path(region.dir, target):
        raise ValueError(f'{stage}: output target is not inside the saved region')
    outputs = [(region.resolve(row['path']), row) for row in doc['outputs']]
    selected = {}
    for name in names:
        matches = [path for path, _ in outputs if path.name == name]
        if len(matches) != 1:
            raise ValueError(f'{stage}: expected exactly one {name} output')
        selected[name] = matches[0]

    hashes, report = {}, b''
    for path, row in outputs:
        if not _saved_path(target, path) or not path.is_file():
            raise ValueError(f'{stage}: missing output or output outside the receipt target')
        if path == selected.get('coarse.json'):
            # Interpret the very bytes that were verified, not a second read.
            report = path.read_bytes()
            size, digest = len(report), receipts.sha256_bytes(report)
        else:
            size, digest = path.stat().st_size, receipts.sha256_file(path)
        if type(row['bytes']) is not int or size != row['bytes'] or digest != row['sha256']:
            raise ValueError(f'{stage}: output size or SHA-256 does not match the receipt')
        hashes[path] = digest
    return {name: {'path': str(path), 'sha256': hashes[path]} for name, path in selected.items()}, report


def pickup_pair(out: Path, region_id: str) -> dict:
    region = receipts.Region(out, region_id)
    coarse, report_bytes = _producer(region, 'coarse', 'coarse-3310.tif', 'coarse.json')
    water, _ = _producer(region, 'water', 'water.geojson')
    report = json.loads(report_bytes)
    if not isinstance(report, dict) or report.get('region', region.id) != region.id:
        raise ValueError('coarse: expected a report for the selected region')
    family, date = report.get('family'), report.get('date')
    if not isinstance(family, str) or not family.strip():
        raise ValueError('coarse: verified report has no family')
    if date is not None and (not isinstance(date, str) or not date.strip()):
        raise ValueError('coarse: invalid date in verified report')
    return {'inputs': {'coarse': coarse['coarse-3310.tif'], 'water': water['water.geojson']},
            'coarse_source': family, 'coarse_date': date}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='saved OUT containing the region directory')
    parser.add_argument('--region', required=True, help='region ID inside OUT')
    args = parser.parse_args(argv)
    try:
        result = pickup_pair(args.out, args.region)
    except (OSError, RuntimeError, receipts.ReceiptError, UnicodeError, json.JSONDecodeError):
        # Do not echo filesystem paths or untrusted receipt fields on refusal.
        print(json.dumps({'error': 'unreadable or invalid saved producer evidence'}))
        return 1
    except ValueError as exc:
        print(json.dumps({'error': str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
