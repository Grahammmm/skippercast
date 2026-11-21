"""Restore a region's catalog files from Git, not the pointer's lineage metadata."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from hashlib import sha256
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Protocol

from skippercast.relief.receipts import REGION_ID


class RollbackError(ValueError):
    """A rollback cannot be prepared."""


class GitHistory(Protocol):
    def log_paths(self, paths: Sequence[str]) -> list[str]: ...
    def show(self, commit: str, path: str) -> bytes | None: ...
    def parent(self, commit: str) -> str | None: ...


def _region_paths(region: str) -> tuple[str, str]:
    if not isinstance(region, str) or not REGION_ID.fullmatch(region):
        raise RollbackError(f'invalid region id: {region!r}')
    return f'catalog/relief/{region}.json', f'catalog/depth-contours/{region}.geojson'


def previous_state(git: GitHistory, region: str) -> dict[str, bytes | None]:
    """Read both files at the same pre-release commit, newest change first."""
    paths = _region_paths(region)
    commits = git.log_paths(paths)
    if not commits:
        raise RollbackError(f'no catalog history for region {region}')
    parent = git.parent(commits[0])
    return {path: git.show(parent, path) if parent is not None else None for path in paths}


class GitCli:
    """Read the checked-out branch's release history using local Git only."""

    def __init__(self, repo_dir: str | Path):
        self.repo_dir = Path(repo_dir)

    def run(self, argv: list[str]) -> bytes:
        """Run a full Git argv in the checkout; return stdout or raise."""
        try:
            return subprocess.run(argv, cwd=self.repo_dir, check=True, capture_output=True).stdout
        except subprocess.CalledProcessError as exc:
            raise RollbackError(exc.stderr.decode(errors='replace').strip()) from exc

    def log_paths(self, paths: Sequence[str]) -> list[str]:
        # A merge PR becomes live at its merge commit, not at a side-branch commit.
        return self.run(['git', '--literal-pathspecs', 'log', '--first-parent',
                         '--format=%H', 'HEAD', '--', *paths]).decode('ascii').splitlines()

    def show(self, commit: str, path: str) -> bytes | None:
        entry = self.run(['git', '--literal-pathspecs', 'ls-tree', '-z', '--full-tree',
                          commit, '--', path])
        if not entry:
            return None
        _, kind, oid = entry.split(b'\t', 1)[0].split()
        if kind != b'blob':
            raise RollbackError(f'not a file at {commit}: {path}')
        return self.run(['git', 'cat-file', 'blob', oid.decode('ascii')])

    def parent(self, commit: str) -> str | None:
        # Read the stored parent even in a shallow clone. A missing ancestor must
        # fail on read, not be mistaken for a first release with no parent.
        headers = self.run(['git', 'cat-file', 'commit', commit]).split(b'\n\n', 1)[0]
        return next((line[7:].decode('ascii') for line in headers.splitlines()
                     if line.startswith(b'parent ')), None)


def write_branch(
    repo_dir: str | Path, region: str, state: Mapping[str, bytes | None], *,
    branch: str, run: Callable[[list[str]], bytes],
) -> None:
    """Commit a local rollback. Use a repo-root runner like ``GitCli(repo_dir).run``."""
    paths = _region_paths(region)
    if state.keys() != set(paths) or any(value is not None and not isinstance(value, bytes)
                                         for value in state.values()):
        raise RollbackError(f'invalid rollback state for region {region}')
    root = Path(repo_dir)
    if run(['git', 'status', '--porcelain=v1', '--untracked-files=all', '--ignore-submodules=none']):
        raise RollbackError('rollback requires a clean worktree and index')
    if run(['git', 'ls-files', '--others', '--ignored', '--exclude-standard', '--', *paths]):
        raise RollbackError('ignored files would be in the way of the rollback')
    for path in map(Path, paths):
        for parent in reversed(path.parents[:-1]):
            directory = root / parent
            if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
                raise RollbackError(f'not a catalog directory: {parent}')
        target = root / path
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise RollbackError(f'not a regular catalog file: {path}')

    try:
        # --create is non-forcing: an existing branch is never reset or checked out.
        run(['git', 'switch', f'--create={branch}'])
    except subprocess.CalledProcessError as exc:
        raise RollbackError(f'cannot create rollback branch {branch!r}') from exc
    for path in paths:
        target = root / path
        payload = state[path]
        target.unlink(missing_ok=True)
        if payload is None:
            run(['git', 'update-index', '--force-remove', '--', path])
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(payload)
            # Stage the raw bytes; git add could renormalize them via clean filters.
            oid = run(['git', 'hash-object', '-w', '--no-filters', '--', path]).decode('ascii').strip()
            run(['git', 'update-index', '--add', '--cacheinfo', f'100644,{oid},{path}'])
    run(['git', 'commit', '-s', '--allow-empty', '-m', f'Roll back relief release for {region}'])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='region.py rollback', description=__doc__)
    parser.add_argument('--region', required=True, help='region id')
    parser.add_argument('--repo', required=True, type=Path, help='root of a clean clone')
    parser.add_argument('--branch', help='new branch (default: rollback/<region>-<short HEAD sha>)')
    args = parser.parse_args(argv)

    git = GitCli(args.repo)
    try:
        if git.run(['git', 'rev-parse', '--show-prefix']) != b'\n':
            raise RollbackError('--repo must point to the root of the clone')
        state = previous_state(git, args.region)
        before = {path: git.show('HEAD', path) for path in state}
        branch = args.branch
        if branch is None:
            short = git.run(['git', 'rev-parse', '--short', 'HEAD']).decode('ascii').strip()
            branch = f'rollback/{args.region}-{short}'
        write_branch(args.repo, args.region, state, branch=branch, run=git.run)
        commit = git.run(['git', 'rev-parse', 'HEAD']).decode('ascii').strip()
    except (RollbackError, OSError) as exc:
        print(f'region.py rollback: {exc}', file=sys.stderr)
        return 1

    print(f'Branch: {branch}\nCommit: {commit}')
    for path, payload in state.items():
        old = before[path]
        old_hash = sha256(old).hexdigest() if old is not None else 'absent'
        new_hash = sha256(payload).hexdigest() if payload is not None else 'removed'
        print(f'{path}: {old_hash} -> {new_hash}')
    push = shlex.join(['git', 'push', 'origin', f'refs/heads/{branch}'])
    print(f'Next: in the clone, run `{push}`, then open one PR into main titled '
          f'"Roll back relief release for {args.region}".')
    return 0
