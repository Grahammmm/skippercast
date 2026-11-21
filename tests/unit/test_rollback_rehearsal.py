"""Offline rehearsals with real Git and the checked-in rollback command."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.relief import rollback_rehearsal as rehearsal
from tests._support import ROOT

REGION = 'fixture-coast'
POINTER = f'catalog/relief/{REGION}.json'
CONTOURS = f'catalog/depth-contours/{REGION}.geojson'
FIELDS = {'generation': '1' * 64, 'release_sha256': '2' * 64,
          'envelope_sha256': '3' * 64, 'sha256': '4' * 64}
OLD = {POINTER: (json.dumps({**FIELDS, 'previous': None}, indent=1) + '\r\n').encode(),
       CONTOURS: b'{"features": []}\n\n'}
NEW_CONTOURS = b'{"features": []}\n'


def git(repo, *args):
    return subprocess.check_output(['git', '--no-optional-locks', *args], cwd=repo)


def put(repo, path, data):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def commit(repo, message, files):
    for path, data in files.items():
        put(repo, path, data)
    git(repo, 'add', '--', *files)
    git(repo, 'commit', '-m', message)
    return git(repo, 'rev-parse', 'HEAD').decode().strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_ALLOW_PROTOCOL', 'file')
    monkeypatch.setenv('LC_ALL', 'C')
    root = tmp_path / 'source clone'
    root.mkdir()
    git(root, 'init', '--initial-branch=main', '--template=')
    git(root, 'config', 'user.name', 'Fixture Builder')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    git(root, 'remote', 'add', 'origin', str(tmp_path / 'never-contact'))
    tool_paths = ('scripts/relief/region.py', 'src/skippercast/__init__.py', 'src/skippercast/paths.py',
                  'src/skippercast/relief/__init__.py', 'src/skippercast/relief/receipts.py',
                  'src/skippercast/relief/rollback.py')
    commit(root, 'Rollback tooling', {path: (ROOT / path).read_bytes() for path in tool_paths})
    return root


def release(repo, *, first=False, wrong=None):
    previous = None if first else dict(FIELDS)
    if wrong and previous is not None:
        previous[wrong] = '0' * 64
    if not first:
        commit(repo, 'Previous release', {**OLD, CONTOURS: NEW_CONTOURS})
        git(repo, 'switch', '-c', 'staged-release')
    pointer = json.dumps({'generation': '5' * 64, 'previous': previous}).encode()
    commit(repo, 'Current release', {POINTER: pointer, **({CONTOURS: NEW_CONTOURS} if first else {})})
    if not first:
        git(repo, 'switch', 'main')
        # The merge's first parent, not the side commit's parent, contains
        # the latest contours for the previous pointer.
        commit(repo, 'Update previous contours before activation', {CONTOURS: OLD[CONTOURS]})
        git(repo, 'merge', '--no-ff', '-m', 'Activate release', 'staged-release')
    return commit(repo, 'Later unrelated change', {'notes.txt': b'keep\n'})


def args(repo, report):
    return ['--repo', str(repo), '--region', REGION, '--report', str(report)]


def digest(data):
    return None if data is None else sha256(data).hexdigest()


def receipt(head, rollback, expected, got, *, lineage_ok, bad=()):
    return {'region': REGION, 'repo_head': head, 'rollback_commit': rollback,
            'files': [{'path': path, 'expected_sha256': digest(expected.get(path)),
                       'got_sha256': digest(got.get(path)), 'ok': path not in bad}
                      for path in (POINTER, CONTOURS)],
            'lineage_ok': lineage_ok, 'verdict': 'PASS' if lineage_ok and not bad else 'FAIL'}


def observe_rollback(monkeypatch, repo, head, after=None):
    real_run = subprocess.run
    observations = []

    def run(argv, *args, **kwargs):
        assert isinstance(argv, list) and kwargs.get('shell', False) is False
        if argv[:2] == ['git', 'clone']:
            assert '--no-hardlinks' in argv
        if argv[0] == 'git':
            assert 'push' not in argv[1:]
        if argv[:4] != [sys.executable, '-B', 'scripts/relief/region.py', 'rollback']:
            return real_run(argv, *args, **kwargs)
        clone = Path(kwargs['cwd'])
        assert clone != repo and not clone.is_relative_to(repo)
        assert git(clone, 'remote') == b''
        assert git(clone, 'rev-parse', 'HEAD') == (head + '\n').encode()
        oid = head[:2] + '/' + head[2:]
        assert not (clone / '.git/objects' / oid).samefile(repo / '.git/objects' / oid)
        result = real_run(argv, *args, **kwargs)
        if after:
            after(clone)
        assert git(clone, 'rev-parse', 'HEAD^').decode().strip() == head
        observations.append((clone, git(clone, 'rev-parse', 'HEAD').decode().strip()))
        return result

    monkeypatch.setattr(subprocess, 'run', run)
    return observations


@pytest.mark.parametrize('first', [False, True], ids=['two-releases', 'first-release'])
def test_c1_restores_exact_history_and_isolates_git(repo, tmp_path, monkeypatch, first):
    """C1: A wrong parent, JSON reformatting, missed removal or connected clone changes the result."""
    head = release(repo, first=first)
    observations = observe_rollback(monkeypatch, repo, head)
    report = tmp_path / 'report.json'
    assert rehearsal.main(args(repo, report)) == 0
    [(clone, rollback)] = observations
    expected = {} if first else OLD
    assert json.loads(report.read_bytes()) == receipt(head, rollback, expected, expected, lineage_ok=True)
    assert not clone.parent.exists()


@pytest.mark.parametrize('field', list(FIELDS))
def test_c1_wrong_previous_fails_even_when_bytes_match(repo, tmp_path, monkeypatch, field):
    """C1: Skipping any of the four lineage fields could bless the wrong release identity."""
    head = release(repo, wrong=field)
    observations = observe_rollback(monkeypatch, repo, head)
    report = tmp_path / 'report.json'
    assert rehearsal.main(args(repo, report)) == 1
    [(_, rollback)] = observations
    assert json.loads(report.read_bytes()) == receipt(head, rollback, OLD, OLD, lineage_ok=False)


def test_c1_byte_mismatch_fails_even_when_lineage_matches(repo, tmp_path, monkeypatch):
    """C1: Trusting rollback's stdout, exit code or parsed JSON could hide altered bytes."""
    head = release(repo)
    changed = b'{"features":[]}\n'

    def corrupt(clone):
        put(clone, CONTOURS, changed)
        git(clone, 'add', '--', CONTOURS)
        git(clone, '-c', 'user.name=Fixture Builder', '-c', 'user.email=fixture@example.invalid',
            'commit', '--amend', '--no-edit')

    observations = observe_rollback(monkeypatch, repo, head, corrupt)
    report = tmp_path / 'report.json'
    assert rehearsal.main(args(repo, report)) == 1
    [(_, rollback)] = observations
    assert json.loads(report.read_bytes()) == receipt(
        head, rollback, OLD, {**OLD, CONTOURS: changed}, lineage_ok=True, bad=(CONTOURS,),
    )


def test_c2_cli_leaves_dirty_clone_unchanged_and_replaces_report(repo, tmp_path, monkeypatch):
    """C2: A real CLI run must neither stage dirty bytes nor change the source refs or index."""
    head = release(repo)
    put(repo, 'notes.txt', b'work in progress\n')
    git(repo, 'add', '--', 'notes.txt')
    put(repo, POINTER, b'unstaged, not a pointer\n')
    put(repo, 'local.txt', b'untracked\n')
    monkeypatch.setenv('TMPDIR', str(repo))
    status = git(repo, 'status', '--porcelain')
    refs = git(repo, 'show-ref', '--head')
    config = (repo / '.git/config').read_bytes()
    index = (repo / '.git/index').read_bytes()
    report = tmp_path / 'report.json'
    report.write_text('old report', encoding='utf-8')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/relief/rollback_rehearsal.py'),
                             *args(repo, report)], capture_output=True)
    assert (result.returncode, result.stdout, result.stderr) == (0, b'', b'')
    actual = json.loads(report.read_bytes())
    assert actual == receipt(head, actual['rollback_commit'], OLD, OLD, lineage_ok=True)
    assert git(repo, 'status', '--porcelain') == status
    assert git(repo, 'show-ref', '--head') == refs
    assert git(repo, 'branch', '--show-current') == b'main\n'
    assert (repo / '.git/config').read_bytes() == config
    assert (repo / '.git/index').read_bytes() == index
    assert (repo / POINTER).read_bytes() == b'unstaged, not a pointer\n'
    assert (repo / 'notes.txt').read_bytes() == b'work in progress\n'
    assert (repo / 'local.txt').read_bytes() == b'untracked\n'
    assert set(tmp_path.iterdir()) == {repo, report}


@pytest.mark.parametrize('change', ['head', 'status'])
def test_c2_refuses_to_certify_source_drift(repo, tmp_path, monkeypatch, capsys, change):
    """C2: Checking only HEAD or only status can emit PASS after source drift."""
    head = release(repo)

    def drift(_clone):
        if change == 'head':
            git(repo, 'commit', '--allow-empty', '-m', 'Concurrent empty commit')
        else:
            put(repo, 'local.txt', b'Concurrent edit')

    observe_rollback(monkeypatch, repo, head, drift)
    report = tmp_path / 'report.json'
    assert rehearsal.main(args(repo, report)) == 1
    assert capsys.readouterr() == (
        '', 'rollback rehearsal: could not verify unchanged source HEAD and porcelain status\n',
    )
    assert not report.exists()


def test_c2_atomic_replace_error_preserves_old_report(repo, tmp_path, monkeypatch, capsys):
    """C2: A failed atomic replace must not truncate the old report or leave scratch files."""
    head = release(repo, first=True)
    observations = observe_rollback(monkeypatch, repo, head)
    report = tmp_path / 'report.json'
    report.write_bytes(b'old report')

    def block_replace(staged, target):
        [(_, rollback)] = observations
        assert staged.parent == target.parent and staged != target == report
        assert json.loads(staged.read_bytes()) == receipt(head, rollback, {}, {}, lineage_ok=True)
        assert target.read_bytes() == b'old report'
        raise PermissionError('fixture refused replace')

    monkeypatch.setattr(Path, 'replace', block_replace)
    assert rehearsal.main(args(repo, report)) == 1
    assert capsys.readouterr() == ('', 'rollback rehearsal: fixture refused replace\n')
    assert report.read_bytes() == b'old report'
    assert set(tmp_path.iterdir()) == {repo, report}


def test_c2_no_history_is_a_failure_not_a_first_release(repo, tmp_path, capsys):
    """C2: No history is not proof of a rollback that deleted both files."""
    head = git(repo, 'rev-parse', 'HEAD').decode().strip()
    report = tmp_path / 'report.json'
    assert rehearsal.main(args(repo, report)) == 1
    assert json.loads(report.read_bytes()) == receipt(
        head, None, {}, {}, lineage_ok=False, bad=(POINTER, CONTOURS),
    )
    assert capsys.readouterr() == ('', f'rollback rehearsal: no catalog history for region {REGION}\n')


def test_c2_rollback_refusal_cannot_certify_restoration(repo, tmp_path, capsys):
    """C2: A child rollback refusal must not be treated as two matching absent files."""
    commit(repo, 'Previous release', OLD)
    (repo / POINTER).unlink()
    (repo / POINTER).symlink_to(f'../depth-contours/{REGION}.geojson')
    git(repo, 'add', '--', POINTER)
    head = commit(repo, 'Invalid release', {CONTOURS: NEW_CONTOURS})
    report = tmp_path / 'report.json'
    assert rehearsal.main(args(repo, report)) == 1
    assert json.loads(report.read_bytes()) == receipt(
        head, None, OLD, {}, lineage_ok=False, bad=(POINTER, CONTOURS),
    )
    assert capsys.readouterr() == ('', f'rollback rehearsal: region.py rollback: not a regular catalog file: {POINTER}\n')


@pytest.mark.parametrize('case', ['missing-report', 'invalid-region', 'not-root', 'missing-repo'])
def test_c2_usage_is_exit_two(repo, tmp_path, case):
    """C2: Invalid input must be usage, never a rollback attempt or report."""
    report = tmp_path / 'report.json'
    argv = args(repo, report)
    if case == 'missing-report':
        argv = argv[:-2]
    elif case == 'invalid-region':
        argv[3] = '../other'
    else:
        argv[1] = str(repo / 'scripts' if case == 'not-root' else tmp_path / 'absent')
    with pytest.raises(SystemExit) as error:
        rehearsal.main(argv)
    assert (type(error.value), error.value.code) == (SystemExit, 2)
    assert not report.exists()


@pytest.mark.parametrize('case', ['inside', 'outside-alias-in', 'inside-alias-out'])
def test_c3_report_cannot_enter_source_clone(repo, tmp_path, capsys, case):
    """C3: Checking only the input spelling or only the final target can allow a report in the clone."""
    inside = repo / 'report.json'
    outside = tmp_path / 'report.json'
    if case == 'outside-alias-in':
        outside.symlink_to(inside)
    elif case == 'inside-alias-out':
        inside.symlink_to(outside)
    with pytest.raises(SystemExit) as error:
        rehearsal.main(args(repo, outside if case == 'outside-alias-in' else inside))
    assert (type(error.value), error.value.code) == (SystemExit, 2)
    assert capsys.readouterr().err.splitlines()[-1].endswith('--report must lie outside the source clone')
    assert not inside.exists() and not outside.exists()


def test_c3_report_cannot_enter_shared_git_metadata(repo, tmp_path):
    """C3: A linked checkout's Git metadata is part of the source even outside its worktree."""
    linked = tmp_path / 'linked'
    git(repo, 'worktree', 'add', '--detach', str(linked))
    report = repo / '.git' / 'report.json'
    with pytest.raises(SystemExit) as error:
        rehearsal.main(args(linked, report))
    assert (type(error.value), error.value.code) == (SystemExit, 2)
    assert not report.exists()
