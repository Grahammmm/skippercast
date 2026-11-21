#!/usr/bin/env python3
"""Report changes between reviewed relief pointers without building or publishing."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

# A direct CLI invocation should not leave import caches in the checkout.
if __name__ == '__main__':
    sys.dont_write_bytecode = True

from skippercast.relief import package  # noqa: E402

_LINEAGE_FIELDS = ('generation', 'release_sha256', 'envelope_sha256', 'sha256', 'style')
_SHA256 = re.compile(r'[a-f0-9]{64}')


def _row(field, base, candidate):
    return {'field': field, 'base': base, 'candidate': candidate}


def _sources_by_id(sources):
    by_id = {}
    for source in sources:
        by_id.setdefault(source['id'], []).append(source)
    return by_id


def _diff_sources(base, candidate):
    old, new = _sources_by_id(base), _sources_by_id(candidate)
    for source_id in sorted(old.keys() | new.keys()):
        field = f'sources[{json.dumps(source_id)}]'
        before, after = old.get(source_id, []), new.get(source_id, [])
        # A schema-valid pointer can contain repeated IDs. Keep all records in
        # that case rather than silently picking one to represent the source.
        if len(before) > 1 or len(after) > 1:
            before, after = (sorted(records, key=lambda row: json.dumps(row, sort_keys=True))
                             for records in (before, after))
            if before != after:
                yield _row(field, before or None, after or None)
        elif not before or not after:
            yield _row(field, before[0] if before else None, after[0] if after else None)
        else:
            for change in _diff_members(before[0], after[0], before[0].keys() | after[0].keys()):
                yield {**change, 'field': f'{field}.{change["field"]}'}


def _diff_members(base, candidate, fields):
    for field in sorted(set(fields)):
        if field in base or field in candidate:
            before, after = base.get(field), candidate.get(field)
            if before != after or (field in base) != (field in candidate):
                yield _row(field, before, after)


def diff_fields(base: dict, candidate: dict, fields=None) -> list[dict]:
    """Return sorted field rows, optionally limited to selected top-level keys.

    Pointer and release metadata both store metadata fields at the top level.
    Sources are keyed by ID, with separate rows for changed members. A missing
    side is represented by None; other values are returned without truncation.
    """
    fields = base.keys() | candidate.keys() if fields is None else fields
    rows = []
    for row in _diff_members(base, candidate, fields):
        if row['field'] == 'sources':
            rows.extend(_diff_sources(row['base'] or [], row['candidate'] or []))
        else:
            rows.append(row)
    return rows


def _read_pointer(data: bytes, label: str, schema: dict) -> dict:
    try:
        pointer = package.decode_document(data)
        package.validate_schema(pointer, schema)
    except ValueError as exc:
        raise ValueError(f'{label}: {exc}') from exc
    return pointer


def _read_git_pointer(repo: Path, ref: str, region: str, schema: dict):
    path = f'catalog/relief/{region}.json'
    result = subprocess.run(
        ['git', '--no-pager', 'show', '--no-textconv', '--no-ext-diff', '--end-of-options', f'{ref}:{path}'],
        cwd=repo, capture_output=True,
        env={**os.environ, 'LC_ALL': 'C', 'GIT_NO_LAZY_FETCH': '1', 'GIT_ALLOW_PROTOCOL': ''},
    )
    if result.returncode:
        error = result.stderr.decode('utf-8', errors='replace').strip()
        if error in (f"fatal: path '{path}' does not exist in '{ref}'",
                     f"fatal: path '{path}' exists on disk, but not in '{ref}'"):
            return None
        raise ValueError(f'base: git show failed: {error}')
    return _read_pointer(result.stdout, 'base', schema)


def _read_base_file(path: Path, schema: dict) -> dict | None:
    try:
        return _read_pointer(path.read_bytes(), 'base', schema)
    except FileNotFoundError:
        return None


def _lineage(base, candidate):
    previous = candidate['previous']
    if base is None:
        return 'first-release' if previous is None else 'MISMATCH previous'
    if previous is None:
        return 'MISMATCH previous'
    for field in _LINEAGE_FIELDS:
        if field == 'style' and field not in base:
            continue
        if previous.get(field) != base.get(field):
            return f'MISMATCH previous.{field}'
    return 'ok'


def _shorten_hashes(value, field):
    if isinstance(value, dict):
        return {key: _shorten_hashes(child, key) for key, child in value.items()}
    if (field == 'generation' or field.endswith('sha256') or field in ('baked', 'contours', 'habitat')):
        if isinstance(value, str) and _SHA256.fullmatch(value):
            return value[:12]
    return value


def _text_value(value, field):
    return json.dumps(_shorten_hashes(value, field), sort_keys=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True, type=Path)
    base_arg = parser.add_mutually_exclusive_group(required=True)
    base_arg.add_argument('--base', type=Path)
    base_arg.add_argument('--repo', type=Path)
    parser.add_argument('--ref', help='Git ref to compare with --repo (default: origin/main)')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if args.base is not None and args.ref is not None:
        parser.error('--ref requires --repo')
    if args.ref is not None and (not args.ref or ':' in args.ref):
        parser.error('--ref must name a Git revision, not an index or tree path')

    try:
        schema = package.pointer_schema()
        candidate = _read_pointer(args.candidate.read_bytes(), 'candidate', schema)
        if args.base is not None:
            base = _read_base_file(args.base, schema)
        else:
            ref = 'origin/main' if args.ref is None else args.ref
            base = _read_git_pointer(args.repo, ref, candidate['region'], schema)
        if base is not None and base['region'] != candidate['region']:
            raise ValueError(f"region mismatch: base {base['region']!r}, candidate {candidate['region']!r}")
    except (OSError, ValueError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1

    lineage = _lineage(base, candidate)
    rows = diff_fields(base if base is not None else {}, candidate)
    if args.json:
        print(json.dumps({'lineage': lineage, 'changes': rows}, indent=2, sort_keys=True))
    else:
        print(f'lineage: {lineage}')
        for row in rows:
            field = row['field']
            print(f'{field}: {_text_value(row["base"], field)} -> {_text_value(row["candidate"], field)}')
    return int(lineage not in ('ok', 'first-release'))


if __name__ == '__main__':
    raise SystemExit(main())
