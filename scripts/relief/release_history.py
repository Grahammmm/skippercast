#!/usr/bin/env python3
"""List reviewed regional relief releases on the clone's checked-out HEAD.

Omit REGION to list all regions found in either catalog path's history.
Use a full clone. Dates are UTC committer dates; '-' denotes missing data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

# Prefer the tools checkout over a foreign editable install, as region.py does.
source_root = Path(__file__).resolve().parents[2] / 'src'
if (source_root / 'skippercast' / 'relief' / 'rollback.py').is_file():
    sys.path.insert(0, str(source_root))

from skippercast.relief import package
from skippercast.relief.rollback import GitCli, RollbackError, _region_paths
from skippercast.relief.receipts import REGION_ID

CATALOGS = {'catalog/relief': '.json', 'catalog/depth-contours': '.geojson'}
COLUMNS = 'commit\tdate\tgeneration\tenvelope_sha256\tstyle.built_with\tcontours_sha256\tstatus\trollback'


def catalog_regions(git: GitCli) -> list[str]:
    changes = git.run(['git', 'log', '--first-parent', '--diff-merges=first-parent',
                       '--format=', '--name-only', '-z', '--no-renames', 'HEAD', '--', *CATALOGS])
    regions = set()
    for change in changes.decode('utf-8', errors='surrogateescape').split('\0'):
        directory, _, name = change.rpartition('/')
        suffix = CATALOGS.get(directory)
        if suffix and name.endswith(suffix) and REGION_ID.fullmatch(region := name[:-len(suffix)]):
            regions.add(region)
    return sorted(regions)


def pointer_columns(data: bytes | None, schema: dict) -> tuple[str, str, str, str]:
    if data is None:
        return '-', '-', '-', 'absent'
    try:
        pointer = package.decode_document(data)
        package.validate_schema(pointer, schema)
    except ValueError as exc:
        # Quote the diagnostic so malformed historical text cannot split the table.
        return '-', '-', '-', f'invalid: {json.dumps(str(exc))}'
    return (pointer['generation'], pointer['envelope_sha256'][:12],
            pointer.get('style', {}).get('built_with', '-'), 'reviewed')


def region_lines(git: GitCli, region: str, schema: dict) -> list[str]:
    paths = _region_paths(region)
    commits = git.log_paths(paths)
    if not commits:
        return [f'region {region}', '  no catalog history']
    lines = [f'region {region}', COLUMNS]
    # The latest change's first parent has the same pair as the preceding
    # catalog-changing commit, even across unrelated commits or merge PRs.
    for index, commit in enumerate(commits):
        timestamp = int(git.run(['git', 'show', '-s', '--format=%ct', commit]))
        date = datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace('+00:00', 'Z')
        pointer, contours = (git.show(commit, path) for path in paths)
        generation, envelope, style, status = pointer_columns(pointer, schema)
        digest = sha256(contours).hexdigest()[:12] if contours is not None else '-'
        lines.append('\t'.join((commit, date, generation, envelope, style, digest, status,
                                'restore' if index == 1 else '-')))
    if len(commits) == 1:
        lines.append('  rollback restores no catalog files (first release)')
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path, help='root of a full clone')
    parser.add_argument('regions', metavar='REGION', nargs='*')
    args = parser.parse_args(argv)
    git = GitCli(args.repo)
    try:
        if git.run(['git', 'rev-parse', '--show-prefix']) != b'\n':
            raise RollbackError('--repo must point to the root of the clone')
        if git.run(['git', 'rev-parse', '--is-shallow-repository']) == b'true\n':
            raise RollbackError('--repo must contain full history (not a shallow clone)')
        regions = list(dict.fromkeys(args.regions)) or catalog_regions(git)
        schema = package.pointer_schema()
        lines = [line for region in regions for line in region_lines(git, region, schema)]
    except (RollbackError, OSError) as exc:
        print(f'release_history.py: {exc}', file=sys.stderr)
        return 1
    print('\n'.join(lines) if lines else 'no regional catalog history')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
