#!/usr/bin/env python3
"""Summarize native digest reuse across proposed North A bindings offline.

Supply a JSON array of rows with `region` and lowercase `native_sha256`.
Optional metadata such as `filename` is ignored: the supplied digest alone
identifies the native evidence. No native files or census records are read,
and the report does not qualify a source or admit a binding.
"""

import argparse
import json
from pathlib import Path
import sys

from skippercast.relief.receipts import HEX64, REGION_ID


def summarize(proposals):
    """Return one incidence row per digest, regardless of the proposal count."""
    if not isinstance(proposals, list):
        raise ValueError('proposals must be a JSON array')
    regions_by_digest: dict[str, set[str]] = {}
    for index, row in enumerate(proposals, start=1):
        if not isinstance(row, dict):
            raise ValueError(f'row {index}: expected an object')
        region = row.get('region')
        digest = row.get('native_sha256')
        if not isinstance(region, str) or not REGION_ID.fullmatch(region):
            raise ValueError(f'row {index}: invalid region ID')
        if not isinstance(digest, str) or not HEX64.fullmatch(digest):
            raise ValueError(f'row {index}: native_sha256 must be a lowercase SHA-256 digest')
        regions_by_digest.setdefault(digest, set()).add(region)

    return {
        'unique_digest_count': len(regions_by_digest),
        'reused_digest_count': sum(len(regions) > 1 for regions in regions_by_digest.values()),
        'incidence': [
            {'native_sha256': digest, 'regions': sorted(regions), 'reused': len(regions) > 1}
            for digest, regions in sorted(regions_by_digest.items())
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('proposals', type=Path, help='local JSON array of proposed bindings')
    args = parser.parse_args(argv)
    try:
        report = summarize(json.loads(args.proposals.read_text(encoding='utf-8')))
    except (OSError, ValueError) as exc:
        print(f'north-a-binding-reuse: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
