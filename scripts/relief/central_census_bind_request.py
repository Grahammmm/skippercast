"""Print the census-bind argument vector as JSON; never run the binder.

Supply a custodian-reviewed independent census and its separately accepted pin
(JSON with exactly `region` and `sha256`). The pin is an input, not generated from
the census. This tool checks identity, not custody, rights or release readiness.
Keep both files and a fresh OUT under an explicit disposable scratch directory.
"""

import argparse
import json
from pathlib import Path
import sys

from skippercast.relief import census_bind, receipts

# The six Central release regions (not the Morro pilot).
CENTRAL_REGIONS = (
    'big-sur-coast', 'cambria-san-simeon', 'south-big-sur-san-simeon',
    'monterey-point-sur', 'point-arguello-conception', 'santa-cruz-monterey-bay',
)


def _local_path(value):
    if not value or '://' in value:
        raise ValueError('use an explicit local path')
    path = Path(value).expanduser().absolute()
    if '..' in path.parts or path.resolve() != path:
        raise ValueError('use an explicit local path without symlinks or traversal')
    return path


def _unique_pin_fields(pairs):
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError('accepted pin has duplicate fields')
    return fields


def _request(args):
    root = _local_path(args.scratch)
    if not root.is_dir() or root == root.parent:
        raise ValueError('--scratch must be an existing disposable directory')
    source, pin, out = map(_local_path, (args.census, args.accepted_pin, args.out))
    if any(path == root or not path.is_relative_to(root) for path in (source, pin, out)):
        raise ValueError('--census, --accepted-pin and --out must be inside --scratch')
    if not out.parent.is_dir() or out.exists():
        raise ValueError('--out must name a fresh path with an existing parent')
    if not source.is_file() or not pin.is_file() or source.samefile(pin):
        raise ValueError('supply a census file and a separate accepted pin file')

    region = receipts.Region(out, args.region)
    accepted = json.loads(pin.read_bytes(), object_pairs_hook=_unique_pin_fields)
    if not isinstance(accepted, dict) or accepted.keys() != {'region', 'sha256'}:
        raise ValueError('accepted pin requires exactly region and sha256')
    if accepted['region'] != region.id:
        raise ValueError('accepted pin region mismatch')
    expected = accepted['sha256']
    # Mirror bind()'s read-only digest check and use its census validator. There
    # is no public validator that combines these checks without the writer.
    if not isinstance(expected, str) or not receipts.HEX64.fullmatch(expected.lower()):
        raise ValueError('expected a 64-digit hexadecimal SHA-256')
    data = source.read_bytes()
    if receipts.sha256_bytes(data) != expected.lower():
        raise ValueError('source SHA-256 mismatch')
    census_bind._validate_census(data, region.id)
    return ['--region', region.id, '--out', str(region.out_root),
            '--from', str(source), '--sha256', expected.lower()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--region', required=True, choices=CENTRAL_REGIONS)
    parser.add_argument('--scratch', required=True, help='existing disposable directory')
    parser.add_argument('--out', required=True, help='fresh binder OUT path under scratch')
    parser.add_argument('--census', required=True, help='custodian-reviewed independent census file')
    parser.add_argument('--accepted-pin', required=True, help='separate accepted JSON pin with region and sha256')
    args = parser.parse_args(argv)
    try:
        request = _request(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'central-census-bind-request: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(request))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
