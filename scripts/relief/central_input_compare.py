#!/usr/bin/env python3
"""Compare two saved sc-run-inputs/1 records without checking referenced files."""
import argparse
import json
from pathlib import Path

if __package__:
    from . import run_region
else:
    import run_region


def read_record(path: Path) -> dict:
    # The runner's load_inputs binds a record to runner options and a positional
    # region. Here both regions come from the records, and paths stay as recorded.
    if not path.is_file():
        raise ValueError('not a regular record file')
    record = json.loads(path.read_bytes(), object_pairs_hook=run_region.unique_object)
    if (not isinstance(record, dict)
            or record.keys() != {'schema', 'region', 'inputs', *run_region.RECORD_METADATA}
            or record['schema'] != 'sc-run-inputs/1' or not isinstance(record['inputs'], dict)):
        raise ValueError('expected a sc-run-inputs/1 record')
    region = record['region']
    if not isinstance(region, str) or not run_region.REGION_ID.fullmatch(region):
        raise ValueError('invalid region ID')
    for field in run_region.RECORD_METADATA:
        if record[field] is not None and not isinstance(record[field], str):
            raise ValueError(f'{field} must be a string or null')
    for name, binding in record['inputs'].items():
        if name not in run_region.RECORD_FILES:
            raise ValueError(f'unknown input {name!r}')
        if (not isinstance(binding, dict) or binding.keys() != {'path', 'sha256'}
                or not isinstance(binding['path'], str)):
            raise ValueError(f'{name}: expected path and sha256')
        digest = binding['sha256']
        if not isinstance(digest, str) or not run_region.HEX64.fullmatch(digest.lower()):
            raise ValueError(f'{name}: sha256 must be 64 hexadecimal digits')
        binding['sha256'] = digest.lower()
    return record


def compare(before: dict, after: dict) -> dict:
    if before['region'] != after['region']:
        raise ValueError(f"cannot compare different regions: {before['region']} vs {after['region']}")

    left, right = before['inputs'], after['inputs']
    changes = {}
    for name in sorted(left.keys() | right.keys()):
        old, new = left.get(name), right.get(name)
        if old is None:
            kind = 'added'
        elif new is None:
            kind = 'removed'
        elif old['sha256'] != new['sha256']:
            kind = 'changed'
        elif old['path'] != new['path']:
            kind = 'path-only'
        else:
            continue
        changes[name] = {'kind': kind, 'before': old, 'after': new}

    coarse = {field: {'before': before[field], 'after': after[field]}
              for field in ('coarse_source', 'coarse_date') if before[field] != after[field]}
    norm = None
    if before['norm'] != after['norm']:
        norm = {'before': before['norm'], 'after': after['norm']}
    return {'region': before['region'], 'inputs': changes, 'coarse': coarse, 'norm': norm}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Print JSON differences from BEFORE to AFTER. Exit 0 for a completed comparison '
        'and 2 for unusable records or different regions.'))
    parser.add_argument('before', metavar='BEFORE', type=Path)
    parser.add_argument('after', metavar='AFTER', type=Path)
    args = parser.parse_args(argv)
    records = []
    for side, path in (('before', args.before), ('after', args.after)):
        try:
            records.append(read_record(path))
        except (OSError, ValueError, RecursionError) as exc:
            parser.error(f'{side} record {str(path)!r}: {exc}')
    try:
        report = compare(*records)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
