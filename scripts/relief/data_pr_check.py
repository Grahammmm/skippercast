#!/usr/bin/env python3
"""Check that a relief data branch changes one region's catalog pair, before review.

Usage: data_pr_check.py --repo CLONE --base REF --head REF [--json]

Read-only: Git objects are read with argv lists (rev-parse, diff, ls-tree,
cat-file, show); nothing is checked out, fetched or written in the clone.

Scope: the changed paths between the base and head trees (two-dot, no rename
detection, so a branch behind its base fails until it is updated) must be one
region's pointer and contours (both), or its contours alone. Anything else
prints `FAIL scope <path>`: another path, a second region's file, a pointer
deleted or changed without its contours; an empty diff prints
`FAIL scope (empty diff)`.

Head tree: the pointer must exist and validate, and every check_catalog row
for the region must pass. Pointer lineage (pointer_diff) against the base
pointer must be `ok` or `first-release` when the pointer changes; an unchanged
pointer (contours alone) replaces nothing, so its lineage is `unchanged`.
Each failing check prints `FAIL <check> <reason>`.

Verdict: `data-pr: PASS <region> <generation 12 hex>` and exit 0, otherwise
`data-pr: FAIL` and exit 1. Exit 2 on usage errors or an unknown ref.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

if __name__ == '__main__':
    # A direct CLI invocation must not leave import caches in the checkout, and
    # should use this checkout's code rather than a foreign editable install.
    sys.dont_write_bytecode = True
    _ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_ROOT / 'src'), str(_ROOT)]

from scripts.relief import pointer_diff  # noqa: E402
from skippercast.relief import catalog_check, package  # noqa: E402
from skippercast.relief.rollback import RollbackError, _region_paths  # noqa: E402

# check_catalog reads these besides the region's pair.
_CATALOG_CONTEXT = ('catalog/relief/pointer.schema.json', 'dist/regions/index.json')
_REGION_FILE = re.compile(r'catalog/(?:relief/(?P<pointer>[^/]+)\.json|depth-contours/(?P<contours>[^/]+)\.geojson)')
_GIT_ENV = {**os.environ, 'LC_ALL': 'C', 'GIT_NO_LAZY_FETCH': '1', 'GIT_ALLOW_PROTOCOL': ''}


class GitError(Exception):
    """The clone or a ref cannot be read (exit 2)."""


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(['git', '--no-pager', '--literal-pathspecs', *args],
                            cwd=repo, capture_output=True, env=_GIT_ENV)
    if result.returncode:
        raise GitError(result.stderr.decode('utf-8', errors='replace').strip())
    return result.stdout


def _commit(repo: Path, ref: str) -> str:
    try:
        out = _git(repo, 'rev-parse', '--verify', '--quiet', '--end-of-options', f'{ref}^{{commit}}')
    except GitError:
        raise GitError(f'unknown ref {ref}') from None
    return out.decode('ascii').strip()


def _changes(repo: Path, base: str, head: str) -> list[tuple[str, str]]:
    out = _git(repo, 'diff', '--name-status', '-z', '--no-renames', base, head, '--')
    fields = out.decode('utf-8', errors='surrogateescape').split('\0')[:-1]
    return list(zip(fields[::2], fields[1::2]))


def _blob(repo: Path, commit: str, path: str) -> bytes | None:
    """Return a file's bytes at a commit, or None when the tree has no such entry."""
    entry = _git(repo, 'ls-tree', '-z', '--full-tree', commit, '--', path)
    if not entry:
        return None
    oid = entry.split(b'\t', 1)[0].split()[2].decode('ascii')
    return _git(repo, 'cat-file', 'blob', oid)


def _region_file(path: str) -> tuple[str, str] | None:
    """Return (kind, region) for a region's pointer or contours path, else None."""
    match = _REGION_FILE.fullmatch(path)
    if match is None:
        return None
    kind = 'pointer' if match['pointer'] is not None else 'contours'
    region = match[kind]
    try:
        # The rollback paths are the region's catalog pair; this rejects an
        # invalid region id such as the pointer schema's own file name.
        paths = _region_paths(region)
    except RollbackError:
        return None
    return (kind, region) if path in paths else None


def check_scope(changes: list[tuple[str, str]]) -> tuple[str | None, dict, list[str]]:
    """Return the region, its {kind: status}, and the sorted out-of-scope paths."""
    if not changes:
        return None, {}, ['(empty diff)']
    by_region: dict[str, dict[str, tuple[str, str]]] = {}
    failures = []
    for status, path in changes:
        found = _region_file(path)
        if found is None:
            failures.append(path)
        else:
            by_region.setdefault(found[1], {})[found[0]] = (status, path)
    regions = sorted(by_region)
    for other in regions[1:]:
        failures.extend(path for _, path in by_region[other].values())
    region = regions[0] if regions else None
    files = by_region[region] if region is not None else {}
    pointer = files.get('pointer')
    if pointer is not None and (pointer[0] == 'D' or 'contours' not in files):
        failures.append(pointer[1])
    return region, {kind: status for kind, (status, _) in files.items()}, sorted(failures)


def check_head(repo: Path, base: str, head: str, region: str, pointer_changed: bool):
    """Return (pointer, lineage, failures) for the region on the head tree."""
    pointer_path, contours_path = _region_paths(region)
    schema = package.pointer_schema()
    failures, candidate, lineage = [], None, None
    data = _blob(repo, head, pointer_path)
    if data is None:
        failures.append(('pointer', f'missing {pointer_path}'))
    else:
        try:
            candidate = pointer_diff._read_pointer(data, 'head', schema)
        except ValueError as exc:
            failures.append(('pointer', str(exc)))

    if candidate is not None and not pointer_changed:
        lineage = 'unchanged'
    elif candidate is not None:
        try:
            previous = pointer_diff._read_git_pointer(repo, base, region, schema)
        except ValueError as exc:
            failures.append(('lineage', str(exc)))
        else:
            if previous is not None and previous['region'] != candidate['region']:
                failures.append(('lineage', f"region mismatch: base {previous['region']!r}, "
                                            f"head {candidate['region']!r}"))
            else:
                lineage = pointer_diff._lineage(previous, candidate)
                if lineage not in ('ok', 'first-release'):
                    failures.append(('lineage', lineage))

    # check_catalog reads a directory, so give it only the head files it reads
    # for this region; the clone's working tree is never consulted.
    with tempfile.TemporaryDirectory(prefix='data-pr-check-') as tmp:
        for path in (*_CATALOG_CONTEXT, pointer_path, contours_path):
            data = _blob(repo, head, path)
            if data is not None:
                target = Path(tmp, path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        rows = []
        if not Path(tmp, _CATALOG_CONTEXT[0]).is_file():
            # check_catalog cannot run without the head's pointer schema.
            failures.append(('catalog', f'missing {_CATALOG_CONTEXT[0]}'))
        else:
            try:
                rows = catalog_check.check_catalog(tmp)
            except Exception as exc:  # noqa: BLE001 - a bad head catalog is a reported failure, not a crash
                failures.append(('catalog', f'cannot check head catalog: {type(exc).__name__}: {exc}'))
    failures.extend(('catalog', f"{row['check']}: {row['reason']}") for row in rows
                    if row['region'] == region and row['status'] == 'FAIL')
    return candidate, lineage, failures


def run(repo: Path, base_ref: str, head_ref: str) -> dict:
    base, head = _commit(repo, base_ref), _commit(repo, head_ref)
    changes = _changes(repo, base, head)
    region, files, scope = check_scope(changes)
    report = {'base': base, 'head': head, 'region': region, 'generation': None, 'lineage': None,
              'changed': [{'status': status, 'path': path} for status, path in changes]}
    failures = [('scope', path) for path in scope]
    if region is not None and not scope:
        candidate, report['lineage'], failures = check_head(repo, base, head, region, 'pointer' in files)
        if candidate is not None:
            report['generation'] = candidate['generation']
    report['failures'] = [{'check': check, 'reason': reason} for check, reason in failures]
    report['verdict'] = 'FAIL' if failures else 'PASS'
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    parser.add_argument('--repo', required=True, type=Path, help='clone to read (never modified)')
    parser.add_argument('--base', required=True, help='Git ref of the reviewed base, e.g. origin/main')
    parser.add_argument('--head', required=True, help='Git ref of the data branch')
    parser.add_argument('--json', action='store_true', help='print the report as JSON')
    args = parser.parse_args(argv)
    for name in ('base', 'head'):
        if not getattr(args, name) or ':' in getattr(args, name):
            parser.error(f'--{name} must name a Git revision, not an index or tree path')
    if not args.repo.is_dir():
        parser.error(f'--repo is not a directory: {args.repo}')

    try:
        report = run(args.repo, args.base, args.head)
    except GitError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for failure in report['failures']:
            print('FAIL {check} {reason}'.format(**failure))
        if report['failures']:
            print('data-pr: FAIL')
        else:
            print(f"data-pr: PASS {report['region']} {report['generation'][:12]}")
    return int(report['verdict'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
