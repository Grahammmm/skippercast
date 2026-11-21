"""C1–C3: exercise rollback against offline, disposable release histories."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from skippercast.relief.rollback import GitCli, RollbackError, previous_state, write_branch

REGION = 'test-coast'
POINTER = 'catalog/relief/test-coast.json'
CONTOURS = 'catalog/depth-contours/test-coast.geojson'
NEIGHBOR = 'catalog/relief/other-coast.json'
BRANCH = 'local/undo-test-coast'
SIGNOFF = b'Fixture Builder <fixture@example.invalid>'
FIRST = {POINTER: b'{ "release": 1 }\r\n', CONTOURS: b'{"features": []}\n\n'}
SECOND = {POINTER: b'{"release":2,"previous":null}\n', CONTOURS: b'{"features": []}'}
ABSENT = {POINTER: None, CONTOURS: None}


def put(root, files):
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def snapshot(root):
    return {path: (root / path).read_bytes() if (root / path).exists() else None
            for path in (POINTER, CONTOURS)}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)

    def git(*args):
        return subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True).stdout

    git('init', '--initial-branch=main', '--template=')
    git('config', 'user.name', 'Fixture Builder')
    git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'commit.gpgsign', 'false')
    git('config', 'core.autocrlf', 'false')
    return tmp_path, git


def commit(root, git, message, files):
    put(root, files)
    git('add', '--', *files)
    git('commit', '-s', '-m', message)
    return git('rev-parse', 'HEAD').decode().strip()


def undo(root, state, *, run=None):
    return write_branch(root, REGION, state, branch=BRANCH,
                        run=GitCli(root).run if run is None else run)


def test_c1_invalid_id(repo):
    """C1: Reject path traversal before looking at a region's history."""
    root, _ = repo
    with pytest.raises(RollbackError, match='invalid region id') as raised:
        previous_state(GitCli(root), '../other-coast')
    assert raised.type is RollbackError


def test_c1_empty_region_history(repo):
    """C1: A neighbor's release is not a release of this region."""
    root, git = repo
    other = commit(root, git, 'Other region', {NEIGHBOR: b'other\n'})
    history = GitCli(root)
    assert history.log_paths([POINTER, CONTOURS]) == []
    assert history.parent(other) is None
    with pytest.raises(RollbackError, match='no catalog history') as raised:
        previous_state(history, REGION)
    assert raised.type is RollbackError


@pytest.mark.parametrize('changed', [POINTER, CONTOURS], ids=['pointer', 'contours'])
def test_c1_only_one_path_changed(repo, changed):
    """C1: Read both files at one parent, not at their individual previous revisions."""
    root, git = repo
    commit(root, git, 'Release both files', FIRST)
    commit(root, git, 'Update one file', {changed: SECOND[changed]})
    assert previous_state(GitCli(root), REGION) == FIRST


@pytest.mark.parametrize('first_path', [POINTER, CONTOURS], ids=['pointer', 'contours'])
def test_c1_c2_prior_state_contains_one_file(repo, first_path):
    """C1: A present empty blob and an absent sibling restore differently."""
    root, git = repo
    commit(root, git, 'First release has one empty blob', {first_path: b''})
    commit(root, git, 'Second release has two files', SECOND)
    expect = {**ABSENT, first_path: b''}
    state = previous_state(GitCli(root), REGION)
    assert state == expect
    assert undo(root, state) is None
    assert snapshot(root) == expect
    assert git('diff', '--name-only', 'HEAD~1').decode().splitlines() == sorted(expect)


def test_c2_rollback_restores_two_exact_blobs_on_a_signed_branch(repo):
    """C2: Restore the full bytes, scope and parent even after unrelated changes."""
    root, git = repo
    commit(root, git, 'Release 1', {**FIRST, NEIGHBOR: b'other first\n'})
    commit(root, git, 'Release 2', SECOND)
    head = commit(root, git, 'Update neighbor', {NEIGHBOR: b'other current\n'})
    cli = GitCli(root)
    state = previous_state(cli, REGION)
    assert state == FIRST

    calls = []

    def run(argv):
        assert type(argv) is list and argv[0] == 'git'
        calls.append(argv[1])
        return cli.run(argv)

    assert undo(root, state, run=run) is None
    assert 'commit' in calls and not {'push', 'merge'}.intersection(calls)
    assert git('branch', '--show-current') == (BRANCH + '\n').encode()
    assert git('rev-list', '--parents', '-1', 'HEAD').decode().split()[1:] == [head]
    assert git('rev-parse', 'main').decode().strip() == head
    assert git('diff', '--name-only', 'HEAD~1').decode().splitlines() == sorted(FIRST)
    assert {path: git('show', f'HEAD:{path}') for path in FIRST} == FIRST
    assert snapshot(root) == FIRST
    assert (root / NEIGHBOR).read_bytes() == b'other current\n'
    assert git('status', '--porcelain') == b''
    assert REGION.encode() in git('log', '-1', '--format=%s')
    assert git('log', '-1', '--format=%(trailers:key=Signed-off-by,valueonly)').strip() == SIGNOFF


@pytest.mark.parametrize('root_release', [False, True], ids=['with-parent', 'root-commit'])
def test_c2_rollback_deletes_first_release(repo, root_release):
    """C2: Returning to no release removes both index entries and worktree files."""
    root, git = repo
    if not root_release:
        commit(root, git, 'Before release', {NEIGHBOR: b'keep\n'})
    commit(root, git, 'First release', FIRST)
    state = previous_state(GitCli(root), REGION)
    assert state == ABSENT
    assert undo(root, state) is None
    assert snapshot(root) == ABSENT
    assert git('diff', '--name-status', 'HEAD~1').decode().splitlines() == [
        f'D\t{path}' for path in sorted(ABSENT)
    ]


def test_c2_stages_raw_bytes_despite_clean_conversion(repo):
    """C2: A local clean conversion must not normalize historical CRLF bytes."""
    root, git = repo
    commit(root, git, 'Release 1', FIRST)
    commit(root, git, 'Release 2', SECOND)
    git('config', 'core.autocrlf', 'input')
    assert undo(root, previous_state(GitCli(root), REGION)) is None
    assert {path: git('show', f'HEAD:{path}') for path in FIRST} == FIRST


def test_c2_recreates_deleted_file_without_changing_unchanged_sibling(repo):
    """C2: Restore a deleted catalog path without changing the other blob."""
    root, git = repo
    commit(root, git, 'Release', FIRST)
    git('rm', '--', POINTER)
    git('commit', '-s', '-m', 'Remove pointer')
    state = previous_state(GitCli(root), REGION)
    assert state == FIRST
    assert undo(root, state) is None
    assert snapshot(root) == FIRST
    assert git('diff', '--name-only', 'HEAD~1').decode().splitlines() == [POINTER]


@pytest.mark.parametrize('dirty', ['unstaged', 'staged', 'untracked'])
def test_c2_refuses_dirty_checkout(repo, dirty):
    """C2: Refuse all three kinds of dirty state before switching branches or writing files."""
    root, git = repo
    head = commit(root, git, 'Release', {**SECOND, NEIGHBOR: b'original'})
    path = 'loose.txt' if dirty == 'untracked' else NEIGHBOR
    put(root, {path: b'local changes'})
    if dirty == 'staged':
        git('add', '--', path)
    status = git('status', '--porcelain')
    with pytest.raises(RollbackError, match='clean worktree') as raised:
        undo(root, FIRST)
    assert raised.type is RollbackError
    assert git('status', '--porcelain') == status
    assert git('branch', '--list').splitlines() == [b'* main']
    assert git('rev-parse', 'HEAD').decode().strip() == head
    assert (root / path).read_bytes() == b'local changes'
    assert snapshot(root) == SECOND


def test_c2_refuses_existing_branch(repo):
    """C2: A name collision must neither reset the existing branch nor switch to it."""
    root, git = repo
    existing = commit(root, git, 'Release 1', FIRST)
    git('branch', BRANCH)
    head = commit(root, git, 'Release 2', SECOND)
    with pytest.raises(RollbackError) as raised:
        undo(root, FIRST)
    assert raised.type is RollbackError
    assert git('branch', '--show-current') == b'main\n'
    assert git('rev-parse', 'HEAD', BRANCH).decode().splitlines() == [head, existing]
    assert git('status', '--porcelain') == b''
    assert snapshot(root) == SECOND


def test_c2_refuses_ignored_target(repo):
    """C2: Do not overwrite an ignored file at a rollback path in an otherwise clean tree."""
    root, git = repo
    commit(root, git, 'Ignore local copy', {'.gitignore': (POINTER + '\n').encode()})
    put(root, {POINTER: b'local ignored copy'})
    assert git('status', '--porcelain') == b''
    with pytest.raises(RollbackError, match='ignored files') as raised:
        undo(root, FIRST)
    assert raised.type is RollbackError
    assert git('branch', '--list').splitlines() == [b'* main']
    assert snapshot(root) == {POINTER: b'local ignored copy', CONTOURS: None}


def test_c2_refuses_symlink_target(repo):
    """C2: A tracked catalog symlink must not redirect the rollback to a neighbor."""
    root, git = repo
    commit(root, git, 'Neighbor data', {NEIGHBOR: b'keep'})
    target = root / POINTER
    target.symlink_to(Path(NEIGHBOR).name)
    git('add', '--', POINTER)
    git('commit', '-s', '-m', 'Track symlink')
    with pytest.raises(RollbackError, match='not a regular catalog file') as raised:
        undo(root, FIRST)
    assert raised.type is RollbackError
    assert git('branch', '--list').splitlines() == [b'* main']
    assert target.is_symlink()
    assert (root / NEIGHBOR).read_bytes() == b'keep'


def test_c2_refuses_blocked_parent_directory(repo):
    """C2: A tracked file where a catalog directory belongs is not replaced."""
    root, git = repo
    commit(root, git, 'Track non-directory', {'catalog/relief': b'keep'})
    with pytest.raises(RollbackError, match='not a catalog directory') as raised:
        undo(root, FIRST)
    assert raised.type is RollbackError
    assert git('branch', '--list').splitlines() == [b'* main']
    assert (root / 'catalog/relief').read_bytes() == b'keep'


def test_c2_refuses_state_for_another_region(repo):
    """C2: Do not start a branch when the supplied snapshot includes another region."""
    root, git = repo
    commit(root, git, 'Release', SECOND)
    with pytest.raises(RollbackError, match='invalid rollback state') as raised:
        undo(root, {**FIRST, NEIGHBOR: b'outside rollback scope'})
    assert raised.type is RollbackError
    assert git('branch', '--list').splitlines() == [b'* main']
    assert snapshot(root) == SECOND


def test_c3_uses_the_merge_commit_and_its_first_parent(repo):
    """C3: A multi-commit data PR rolls back to pre-merge main, not an intermediate commit."""
    root, git = repo
    cli = GitCli(root)
    first = commit(root, git, 'Release 1', FIRST)
    git('switch', '-c', 'data-pr')
    commit(root, git, 'Pointer update', {POINTER: SECOND[POINTER]})
    commit(root, git, 'Contours update', {CONTOURS: SECOND[CONTOURS]})
    git('switch', 'main')
    before = commit(root, git, 'Unrelated main change', {NEIGHBOR: b'keep'})
    git('merge', '--no-ff', 'data-pr', '-m', 'Merge data PR')
    merge = git('rev-parse', 'HEAD').decode().strip()
    assert cli.log_paths([POINTER, CONTOURS]) == [merge, first]
    assert cli.parent(merge) == before
    assert cli.show(before, POINTER) == FIRST[POINTER]
    assert cli.show(before, 'not-present') is None
    assert previous_state(cli, REGION) == FIRST


@pytest.mark.parametrize(('commitish', 'path'), [('no-such-revision', POINTER), ('HEAD', 'catalog/relief')],
                         ids=['unknown-commit', 'not-a-blob'])
def test_c3_read_failure_is_not_an_absent_file(repo, commitish, path):
    """C3: An unavailable commit must not be read as two files to delete."""
    root, git = repo
    commit(root, git, 'Release', FIRST)
    with pytest.raises(RollbackError) as raised:
        GitCli(root).show(commitish, path)
    assert raised.type is RollbackError
