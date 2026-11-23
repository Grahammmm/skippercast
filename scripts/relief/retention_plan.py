#!/usr/bin/env python3
"""Report local relief generation retention against reviewed pointers on HEAD.

Omit REGION to include both historical catalog regions and local OUT regions.
Local presence means a generation directory exists under release/ or review/;
it does not attest to artifact completeness or the served copy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True
    import release_history as history
else:
    from . import release_history as history

from skippercast.relief import package
from skippercast.relief.receipts import HEX64, REGION_ID, ReceiptError, Region
from skippercast.relief.rollback import GitCli, RollbackError


def directory_names(path: Path, pattern: re.Pattern[str]) -> set[str]:
    try:
        return {entry.name for entry in path.iterdir()
                if pattern.fullmatch(entry.name) and not entry.is_symlink() and entry.is_dir()}
    except FileNotFoundError:
        return set()


def region_plan(git: GitCli, region: Region, schema: dict) -> dict:
    versions = [row.generation for row in history.pointer_versions(git, region.id, schema)
                if row.generation is not None]
    local = directory_names(region.dir / 'release', HEX64) | directory_names(region.dir / 'review', HEX64)
    roles: dict[str, list[str]] = {generation: [] for generation in versions}
    # Mark versions before deduplicating: two versions can name the same build.
    for generation, role in zip(versions, ('live', 'rollback')):
        roles[generation].append(role)
    return {
        'region': region.id,
        'keep': [{'generation': generation, 'roles': marks} for generation, marks in roles.items()],
        'unreferenced': sorted(local - roles.keys()),
        'missing-local': [generation for generation in roles if generation not in local],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path, help='root of a full clone')
    parser.add_argument('--out', required=True, type=Path, help='local build output root')
    parser.add_argument('regions', metavar='REGION', nargs='*')
    parser.add_argument('--json', action='store_true', help='print JSON to stdout')
    args = parser.parse_intermixed_args(argv)
    try:
        git = history.full_history(args.repo)
        out = args.out.expanduser().resolve()
        schema = package.pointer_schema()
        regions = list(dict.fromkeys(args.regions)) or sorted(
            set(history.catalog_regions(git)) | directory_names(out, REGION_ID))
        rows = [region_plan(git, Region(out, region), schema) for region in regions]
    except (ReceiptError, RollbackError, OSError) as exc:
        print(f'retention_plan.py: {exc}', file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({'regions': rows}, indent=2))
    else:
        lines = []
        for row in rows:
            lines.append(f"region {row['region']}")
            for kept in row['keep']:
                generation = kept['generation']
                lines.append('  ' + ' '.join(['keep', generation, *kept['roles']]))
            for kind in ('unreferenced', 'missing-local'):
                lines.extend(f'  {kind} {generation}' for generation in row[kind])
        print('\n'.join(lines) if lines else 'no regional generations')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
