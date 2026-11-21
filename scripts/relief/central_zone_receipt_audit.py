#!/usr/bin/env python3
"""Audit a saved Central Coast zone's recorded inputs, not whether its run is done.

Compare current receipt digests without opening the water or coarse grid inputs,
and verify only the bytes of the coarse producer's JSON report. Use a stable
saved OUT (the parent of the selected region directory), not an active run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from skippercast.relief import receipts


def _saved_file(region: receipts.Region, path: Path) -> Path:
    if not path.is_relative_to(region.dir) or path.resolve() != path:
        raise ValueError(f'{path.name} is not a canonical path inside the saved region')
    if not path.is_file():
        raise ValueError(f'missing or not a regular file: {path.name}')
    return path


def _load(region: receipts.Region, stage: str, scope: str | None = None) -> dict:
    path = region.receipt_path(stage, scope)
    try:
        doc = receipts.read_receipt(_saved_file(region, path))
    except (OSError, RuntimeError, UnicodeError, receipts.ReceiptError):
        raise ValueError(f'unreadable receipt: {path.name}') from None
    if doc is None or receipts.validate_receipt(doc, region.id, stage, scope):
        raise ValueError(f'invalid receipt: {path.name}')
    if doc['status'] != 'ok':
        raise ValueError(f'{path.name} status is {doc["status"]}, not ok')
    return doc


def _sha(row: dict) -> str:
    value = row.get('sha256')
    if not isinstance(value, str) or not receipts.HEX64.fullmatch(value):
        raise ValueError('missing or invalid SHA-256')
    return value


def _zone_digest(zone: dict, role: str) -> str:
    inputs = zone.get('inputs')
    if not isinstance(inputs, list):
        inputs = []
    rows = [row for row in inputs if isinstance(row, dict) and row.get('role') == role]
    if len(rows) != 1:
        raise ValueError(f'zone.public.json must record exactly one {role} input')
    return _sha(rows[0])


def _output(producer: dict, name: str) -> dict:
    rows = [row for row in producer['outputs'] if Path(row['path']).name == name]
    if len(rows) != 1:
        raise ValueError(f'{producer["stage"]}.json must record exactly one {name} output')
    return rows[0]


def _coarse_family(region: receipts.Region, producer: dict) -> str:
    row = _output(producer, 'coarse.json')
    expected = _sha(row)
    try:
        raw = _saved_file(region, region.resolve(row['path'])).read_bytes()
    except (OSError, RuntimeError, ValueError):
        raise ValueError('cannot read receipted coarse.json inside the saved region') from None
    if len(raw) != row['bytes'] or receipts.sha256_bytes(raw) != expected:
        raise ValueError('coarse.json does not match its receipted size and SHA-256')
    # Decode the same bytes that were checked; do not look up family in receipt params.
    try:
        doc = json.loads(raw)
    except ValueError:
        raise ValueError('verified coarse.json is not valid JSON') from None
    family = doc.get('family') if isinstance(doc, dict) else None
    if not isinstance(family, str) or not family.strip():
        raise ValueError('verified coarse.json has no family')
    return family


def _zone_source(zone: dict) -> str:
    params = zone.get('params')
    source = params.get('coarse_source') if isinstance(params, dict) else None
    if not isinstance(source, str) or not source.strip():
        raise ValueError('zone.public.json has no params.coarse_source')
    return source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Exit 0 if all three comparisons match, 1 for a mismatch, or 2 if evidence '
        'is unknown with no known mismatch. A match does not verify raster bytes or run readiness.'
    ))
    parser.add_argument('--out', type=Path, required=True, help='saved OUT containing the region directory')
    parser.add_argument('--region', required=True, help='Central Coast region ID within OUT')
    args = parser.parse_args(argv)
    try:
        region = receipts.Region(args.out, args.region)
    except (OSError, RuntimeError, receipts.ReceiptError):
        parser.error('invalid region ID or unresolvable saved OUT')

    def load(stage: str, scope: str | None = None) -> dict | str:
        try:
            return _load(region, stage, scope)
        except ValueError as exc:
            return str(exc)

    zone = load('zone', 'public')
    water, coarse = load('water'), load('coarse')
    states = set()
    for label, producer, name in (('water', water, 'water.geojson'),
                                  ('coarse', coarse, 'coarse-3310.tif'),
                                  ('coarse_source', coarse, None)):
        try:
            if isinstance(zone, str):
                raise ValueError(zone)
            if isinstance(producer, str):
                raise ValueError(producer)
            if name is None:
                recorded, current = _zone_source(zone), _coarse_family(region, producer)
            else:
                recorded, current = _zone_digest(zone, label), _sha(_output(producer, name))
        except ValueError as exc:
            state, detail = 'unknown', str(exc)
        else:
            state = 'match' if recorded == current else 'mismatch'
            detail = f'zone={recorded!r} producer={current!r}'
        states.add(state)
        print(f'{label}: {state} ({detail})')
    if 'mismatch' in states:
        return 1
    return 2 if 'unknown' in states else 0


if __name__ == '__main__':
    raise SystemExit(main())
