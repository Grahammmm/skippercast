#!/usr/bin/env python3
"""Rehearse a regional relief rollback without changing the source checkout."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

BRANCH = 'rollback-rehearsal'
LINEAGE_FIELDS = ('generation', 'release_sha256', 'envelope_sha256', 'sha256')


def _run(repo: Path, env: dict[str, str], *argv: str) -> bytes:
    return subprocess.run(list(argv), cwd=repo, env=env, capture_output=True, check=True).stdout


def _git(repo: Path, env: dict[str, str], *args: str) -> bytes:
    return _run(repo, env, 'git', *args)


def _snapshot(repo: Path, env: dict[str, str]) -> tuple[str, bytes]:
    head = _git(repo, env, 'rev-parse', '--verify', 'HEAD').decode('ascii').strip()
    # A normal status may refresh the source index on disk.
    status = _git(repo, env, '--no-optional-locks', '-c', 'core.fsmonitor=false',
                  'status', '--porcelain')
    return head, status


def _blob(repo: Path, env: dict[str, str], commit: str | None, path: str) -> bytes | None:
    if commit is None or not _git(repo, env, 'ls-tree', commit, '--', path):
        return None
    return _git(repo, env, 'cat-file', 'blob', f'{commit}:{path}')


def _parents(repo: Path, env: dict[str, str], commit: str) -> list[bytes]:
    # Read stored parents even in shallow history, where log may hide one.
    headers = _git(repo, env, 'cat-file', 'commit', commit).split(b'\n\n', 1)[0]
    return [line[7:] for line in headers.split(b'\n') if line.startswith(b'parent ')]


def _lineage_matches(current: bytes | None, restored: bytes | None) -> bool:
    try:
        previous = json.loads(current)['previous'] if current is not None else None
        if restored is None:
            return current is not None and previous is None
        pointer = json.loads(restored)
        return isinstance(previous, dict) and all(
            type(previous[key]) is str and previous[key] == pointer[key] for key in LINEAGE_FIELDS
        )
    except (ValueError, TypeError, KeyError):
        return False


def _sha(data: bytes | None) -> str | None:
    return sha256(data).hexdigest() if data is not None else None


def _write_report(path: Path, report: dict) -> None:
    stream = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.rollback-report-', delete=False)
    staged = Path(stream.name)
    try:
        with stream:
            json.dump(report, stream, indent=2)
            stream.write('\n')
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def _error(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
        return exc.stderr.decode(errors='replace').strip()
    return str(exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path, help='root of the source clone')
    parser.add_argument('--region', required=True)
    parser.add_argument('--report', required=True, type=Path, help='output JSON outside the clone')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', args.region):
        parser.error(f'invalid region id: {args.region!r}')

    # Do not inherit overrides that could point clone commands at a different
    # worktree, index or object store. The disposable commit needs no user config.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_ALLOW_PROTOCOL='file',
               GIT_AUTHOR_NAME='Rollback Rehearsal', GIT_COMMITTER_NAME='Rollback Rehearsal',
               GIT_AUTHOR_EMAIL='rollback@example.invalid', GIT_COMMITTER_EMAIL='rollback@example.invalid')

    try:
        repo = args.repo.resolve(strict=True)
        root = _git(repo, env, 'rev-parse', '--show-prefix', '--is-inside-work-tree')
        if root != b'\ntrue\n':
            parser.error('--repo must point to the root of a working clone')
        git_roots = _git(repo, env, 'rev-parse', '--path-format=absolute', '--git-dir',
                         '--git-common-dir').splitlines()
        roots = [repo, *(Path(os.fsdecode(root)).resolve() for root in git_roots)]
        report_entry = args.report.parent.resolve() / args.report.name
        report_path = report_entry.resolve()
        if any(path.is_relative_to(root) for path in (report_entry, report_path) for root in roots):
            parser.error('--report must lie outside the source clone')
        before = _snapshot(repo, env)
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        parser.error(_error(exc))

    head, _ = before
    paths = (f'catalog/relief/{args.region}.json', f'catalog/depth-contours/{args.region}.geojson')
    expected = dict.fromkeys(paths)
    got = dict.fromkeys(paths)
    commit = None
    lineage_ok = False
    compared = False
    scope_ok = False
    try:
        # An explicit outside directory also keeps a source-local TMPDIR from
        # causing transient writes in the original checkout.
        with tempfile.TemporaryDirectory(prefix='.rollback-rehearsal-', dir=report_path.parent) as scratch:
            clone = Path(scratch) / 'repo'
            _git(Path(scratch), env, 'clone', '--no-hardlinks', '--no-checkout', '--template=',
                 '--', str(repo), str(clone))
            _git(clone, env, 'remote', 'remove', 'origin')
            _git(clone, env, 'switch', '--detach', head)
            # Compute the oracle separately from previous_state and from the
            # rollback command's output.
            change = _git(clone, env, 'log', '--first-parent', '-1', '--format=%H', head, '--', *paths).strip()
            if not change:
                raise ValueError(f'no catalog history for region {args.region}')
            parents = _parents(clone, env, change.decode('ascii'))
            parent = parents[0].decode('ascii') if parents else None
            expected = {path: _blob(clone, env, parent, path) for path in paths}
            current = {path: _blob(clone, env, head, path) for path in paths}
            _run(clone, env, sys.executable, '-B', 'scripts/relief/region.py', 'rollback',
                 '--repo', str(clone), '--region', args.region, '--branch', BRANCH)
            commit = _git(clone, env, 'rev-parse', '--verify', f'refs/heads/{BRANCH}').decode('ascii').strip()
            got = {path: _blob(clone, env, commit, path) for path in paths}
            lineage_ok = _lineage_matches(current[paths[0]], got[paths[0]])
            compared = True
            if _parents(clone, env, commit) != [head.encode('ascii')]:
                raise ValueError('rollback commit must have the pinned source HEAD as its sole parent')
            needed = {os.fsencode(path) for path in paths if current[path] != expected[path]}
            diff = _git(clone, env, 'diff-tree', '-r', '--no-commit-id', '--name-only', '-z',
                        '--no-renames', '--ignore-submodules=none', head, commit, '--')
            if set(diff.split(b'\0')) - {b''} != needed:
                raise ValueError("rollback commit's changed paths do not match the required catalog changes")
            scope_ok = True
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f'rollback rehearsal: {_error(exc)}', file=sys.stderr)
    finally:
        try:
            unchanged = _snapshot(repo, env) == before
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f'rollback rehearsal: {_error(exc)}', file=sys.stderr)
            unchanged = False
    if not unchanged:
        print('rollback rehearsal: could not verify unchanged source HEAD and porcelain status', file=sys.stderr)
        return 1

    files = [{'path': path, 'expected_sha256': _sha(expected[path]), 'got_sha256': _sha(got[path]),
              'ok': compared and expected[path] == got[path]} for path in paths]
    passed = scope_ok and lineage_ok and all(item['ok'] for item in files)
    report = {'region': args.region, 'repo_head': head, 'rollback_commit': commit,
              'files': files, 'lineage_ok': lineage_ok, 'verdict': 'PASS' if passed else 'FAIL'}
    try:
        _write_report(report_path, report)
    except OSError as exc:
        print(f'rollback rehearsal: {_error(exc)}', file=sys.stderr)
        return 1
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
