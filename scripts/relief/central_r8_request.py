#!/usr/bin/env python3
"""Print one committed Central batch's R8 packet argv as a JSON array, without running it.

Run from the repository root in the SkipperCast Python environment. OUT is
an explicit local path (use a disposable scratch path for rehearsal).
"""

import argparse
import json
from pathlib import Path

from skippercast.relief.package import decode_document

if __package__:
    from .central_camera_bounds import REGIONS
else:
    from central_camera_bounds import REGIONS

_ROSTER = (Path(__file__).resolve().parents[2]
           / 'docs/operations/fixtures/relief-central-r8-batches.json')
_PACKET_PREFIX = ['python', 'scripts/relief/r8_packet.py', '--out']


class _Once(argparse.Action):
    """Reject competing selectors instead of silently using the last one."""

    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest) is not None:
            parser.error(f'{option_string} may be given only once')
        setattr(namespace, self.dest, values)


def _batches() -> dict[str, dict]:
    rows = decode_document(_ROSTER.read_bytes()).get('batches')
    if not isinstance(rows, list) or not rows:
        raise ValueError('expected a nonempty Central batch roster')
    batches = {}
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id']:
            raise ValueError('expected a Central batch ID')
        batch_id = row['id']
        if batch_id in batches:
            raise ValueError(f'duplicate Central batch ID {batch_id!r}')
        regions = row.get('regions')
        if not isinstance(regions, list) or not 1 <= len(regions) <= 3:
            raise ValueError(f'{batch_id!r}: expected one to three Central region IDs')
        for region in regions:
            if region not in REGIONS:
                raise ValueError(f'{batch_id!r}: not a Central region ID: {region!r}')
            if region in seen:
                raise ValueError(f'{batch_id!r}: repeated Central region ID: {region!r}')
            seen.add(region)
        if row.get('packet_argv') != [*_PACKET_PREFIX, None, *regions]:
            raise ValueError(f'{batch_id!r}: packet argv must match ordered batch membership')
        batches[batch_id] = row
    return batches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--batch', required=True, action=_Once, help='committed Central batch ID')
    parser.add_argument('--out', required=True, action=_Once, metavar='OUT', help='local R8 output root')
    parser.add_argument('--regions', nargs='+', action=_Once, metavar='REGION',
                        help='optional check of the full ordered membership (does not change the batch)')
    args = parser.parse_args(argv)
    if not args.out.strip() or args.out.startswith('-') or '://' in args.out or '\0' in args.out:
        parser.error('--out must be a local path usable as a separate argument')
    try:
        batches = _batches()
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.batch not in batches:
        parser.error(f'unknown Central batch {args.batch!r}')
    batch = batches[args.batch]
    if args.regions is not None and args.regions != batch['regions']:
        parser.error('--regions must match the full ordered membership of the selected batch')

    packet_argv = batch['packet_argv'].copy()
    packet_argv[3] = args.out
    print(json.dumps(packet_argv))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
