#!/usr/bin/env python3
"""Compare two explicit R8 release candidates, without approval or publication."""
import argparse
from pathlib import Path
import sys

from skippercast.relief import envelope
from skippercast.relief.package import ReleaseError


def _identity(candidate: envelope.VerifiedArtifacts) -> dict:
    return {
        'generation': candidate.generation,
        'envelope_sha256': candidate.envelope_sha256,
        'release_sha256': candidate.release_sha256,
        'qa_sha256': candidate.qa_sha256,
        'layer_names': ', '.join(row['path'] for row in candidate.layers),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Exit codes: 0 exact match, 1 different candidates, 2 unusable input or different regions.'))
    parser.add_argument('left', type=Path, metavar='LEFT_ENVELOPE')
    parser.add_argument('right', type=Path, metavar='RIGHT_ENVELOPE')
    args = parser.parse_args(argv)

    verified = []
    for side, path in (('left', args.left), ('right', args.right)):
        try:
            verified.append(envelope.verify_artifacts(path))
        except (ReleaseError, RecursionError) as exc:
            reason = ' '.join(str(exc).splitlines())
            print(f'Unusable {side} envelope: {reason}', file=sys.stderr)
            return 2

    left, right = verified
    left_region, right_region = left.release['region'], right.release['region']
    if left_region != right_region:
        print(f'Cannot compare candidates from different regions: {left_region} vs {right_region}',
              file=sys.stderr)
        return 2

    left_fields, right_fields = _identity(left), _identity(right)
    changes = [f'{field}: {value} -> {right_fields[field]}'
               for field, value in left_fields.items() if value != right_fields[field]]
    if changes:
        print(f'Different R8 candidates for {left_region} (left -> right):', *changes, sep='\n')
        return 1
    print(f'Exact R8 candidate match for {left_region}.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
