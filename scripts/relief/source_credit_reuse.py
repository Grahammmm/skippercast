#!/usr/bin/env python3
"""Build a source-centric JSON review table from explicitly supplied relief pointers.

Run from the repository root with the SkipperCast Python environment:
    python -m scripts.relief.source_credit_reuse saved-north.json saved-south.json

Only the pointer's region and sources[].id are evidence of depth-shading use.
This is not release validation, a rights decision, or a Sources page check.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path

from skippercast.relief.package import decode_document


def _text(row, field):
    value = row.get(field) if isinstance(row, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'expected nonblank text for {field!r}')
    return value  # IDs and credits must not be normalized.


def _sources(doc):
    rows = doc.get('sources')
    if not isinstance(rows, list) or not rows:
        raise ValueError('expected a nonempty sources array')
    return rows


def _read(path, project):
    try:
        return project(decode_document(path.read_bytes()))
    except (OSError, ValueError) as exc:
        raise ValueError(f'{path}: {exc}') from exc


def _register(doc):
    sources = {}
    for row in _sources(doc):
        ident = _text(row, 'id')
        if ident in sources:
            raise ValueError(f'duplicate registered source ID {ident!r}')
        sources[ident] = row
    return sources


def _pointer(doc):
    return _text(doc, 'region'), [_text(row, 'id') for row in _sources(doc)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--register', type=Path, default=Path('catalog/sources.json'),
                        help='local source register (default: catalog/sources.json)')
    parser.add_argument('pointers', type=Path, nargs='+', help='local relief pointer JSON files')
    args = parser.parse_args(argv)
    try:
        sources = _read(args.register, _register)
        uses = defaultdict(set)
        for path in args.pointers:
            region, ids = _read(path, _pointer)
            for ident in ids:
                uses[ident].add((region, 'Depth shading'))
    except ValueError as exc:
        parser.error(str(exc))

    table = []
    for ident, pairs in sorted(uses.items()):
        row = sources.get(ident)
        table.append({
            'source_id': ident,
            'status': 'registered' if row is not None else 'unresolved',
            'name': row.get('name') if row is not None else None,
            'attribution': (row.get('rights') or {}).get('attribution') if row is not None else None,
            'uses': [{'region': region, 'layer': layer} for region, layer in sorted(pairs)],
        })
    print(json.dumps(table, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
