#!/usr/bin/env python3
"""Compare local copies with the file pins in a trusted sc-run-inputs/1 record.

    python scripts/relief/run_input_transfer.py central --inputs RECORD \
        --copy coarse LOCAL_TIF --copy water LOCAL_GEOJSON

The record's saved file paths are not used. Only caller-supplied copies are
opened. Exit 0 if all checked roles match, 1 if any fail, 2 for invalid usage
or a rejected record. This checks file bytes, not readiness to run a region.
"""

import argparse
import hashlib
from pathlib import Path

if __package__:
    from .run_region import RECORD_FILES, RECORD_METADATA, load_inputs
else:
    from run_region import RECORD_FILES, RECORD_METADATA, load_inputs


def _verdict(path, expected):
    if expected is None:
        return 'unverifiable (no recorded SHA-256)'
    if path is None:
        return 'missing (no local copy supplied)'
    try:
        if not path.is_file():
            return 'missing (local copy is absent or not a regular file)'
        with path.open('rb') as handle:
            observed = hashlib.file_digest(handle, 'sha256').hexdigest()
    except (OSError, ValueError):
        return 'unreadable (cannot hash local copy)'
    if observed != expected:
        return f'mismatch (expected {expected}, got {observed})'
    return 'match'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verify local copies against a SHA-256-pinned run-input record.')
    parser.add_argument('region', help='region ID in the record')
    parser.add_argument('--inputs', required=True, metavar='RECORD')
    parser.add_argument('--copy', action='append', nargs=2, default=[], metavar=('ROLE', 'PATH'),
                        help='local copy for a file role; repeat for each role')
    args = parser.parse_args(argv)
    copies = {}
    for role, path in args.copy:
        if role not in RECORD_FILES:
            parser.error(f'unknown file role {role!r}')
        if role in copies:
            parser.error(f'duplicate local copy for {role!r}')
        copies[role] = Path(path)

    # Reuse the runner's record validation and digest extraction, not its path
    # resolution or run guards. Keep the record's option values separate.
    record_args = argparse.Namespace(**dict.fromkeys((*RECORD_FILES, *RECORD_METADATA, 'census_sha256')),
                                     region=args.region, inputs=args.inputs)
    _, pins = load_inputs(record_args, parser)
    roles = sorted(pins.keys() | copies.keys())
    if not roles:
        parser.error('no pinned roles or local copies to verify')

    all_match = True
    for role in roles:
        verdict = _verdict(copies.get(role), pins.get(role))
        print(f'{role}: {verdict}')
        all_match = all_match and verdict == 'match'
    return 0 if all_match else 1


if __name__ == '__main__':
    raise SystemExit(main())
