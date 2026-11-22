#!/usr/bin/env python3
"""Compare proposed North B bindings to a supplied native census, without binding it.

The review census JSON declares one top-level ``source_id``. Its digest is
SHA-256 of the original bytes, not a field in the census. The proposals JSON
maps each North B region to a ``source_id`` and ``source_sha256``. These are
review inputs, not operational region censuses or census-bind receipts.
"""

import argparse
import json
from pathlib import Path
import sys

from skippercast.relief.receipts import sha256_bytes

REGIONS = (
    'fort-bragg-point-arena',
    'shelter-cove-north-mendocino',
    'humboldt-bay-cape-mendocino',
)


def review(census_bytes, proposed):
    """Return the joined identities only when all three proposals match."""
    census = json.loads(census_bytes)
    source_id = census.get('source_id') if isinstance(census, dict) else None
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError('native census requires a source_id')
    if not isinstance(proposed, dict) or proposed.keys() != set(REGIONS):
        raise ValueError('proposals must cover exactly the three North B regions')

    digest = sha256_bytes(census_bytes)
    for region in REGIONS:
        binding = proposed[region]
        if not isinstance(binding, dict) or binding.get('source_id') != source_id:
            raise ValueError(f'{region}: native source_id mismatch')
        if binding.get('source_sha256') != digest:
            raise ValueError(f'{region}: native census SHA-256 mismatch')
    return {region: {'source_id': source_id, 'source_sha256': digest} for region in REGIONS}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('census', type=Path, help='local native census JSON')
    parser.add_argument('proposals', type=Path, help='local proposed binding identities JSON')
    args = parser.parse_args(argv)
    try:
        joined = review(args.census.read_bytes(), json.loads(args.proposals.read_bytes()))
    except (OSError, ValueError) as exc:
        print(f'north-b-census-lineage: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(joined, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
