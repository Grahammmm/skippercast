"""Exercise the rollback command with disposable, offline Git history."""
from hashlib import sha256
import os
import subprocess
import sys

import pytest

from skippercast.relief.rollback import main
from tests._support import ROOT

REGION = 'fixture-coast'
POINTER = f'catalog/relief/{REGION}.json'
CONTOURS = f'catalog/depth-contours/{REGION}.geojson'
PREVIOUS = {POINTER: b'{ "release": 1 }\r\n', CONTOURS: b'{"features": []}\n\n'}
LATEST = {POINTER: b'{"release":2}\n', CONTOURS: b'{"features": []}\n'}
CLI = ROOT / 'scripts' / 'relief' / 'region.py'


def put(root, path, data):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_ALLOW_PROTOCOL', 'file')
    monkeypatch.setenv('LC_ALL', 'C')

    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path).decode().strip()

    git('init', '--initial-branch=main', '--template=')
    git('config', 'user.name', 'Fixture Builder')
    git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'core.autocrlf', 'false')
    return tmp_path, git


def release(repo, message, files):
    root, git = repo
    for path, data in files.items():
        put(root, path, data)
    git('add', '--', *files)
    git('commit', '-m', message)
    return git('rev-parse', 'HEAD')


def invoke(root, *extra):
    return subprocess.run(
        [sys.executable, str(CLI), 'rollback', '--region', REGION, '--repo', str(root), *extra],
        capture_output=True, text=True,
    )


@pytest.mark.parametrize('first_release', [False, True], ids=['restore', 'remove'])
def test_c1_reports_exact_commit_and_hashes(repo, first_release):
    """C1: Swapped hashes, a wrong branch base or a missing deletion changes the receipt or tree."""
    root, git = repo
    if not first_release:
        release(repo, 'Previous release', PREVIOUS)
    release(repo, 'Bad release', LATEST)
    head = release(repo, 'Unrelated change after release', {'notes.txt': b'keep\n'})
    default = f'rollback/{REGION}-{git("rev-parse", "--short", "HEAD")}'
    branch = 'local/remove-release' if first_release else default
    result = invoke(root, *(['--branch', branch] if first_release else []))

    assert (result.returncode, result.stderr) == (0, '')
    commit = git('rev-parse', 'HEAD')
    assert git('branch', '--show-current') == branch
    assert git('rev-parse', 'HEAD^', 'main').splitlines() == [head, head]
    assert git('diff', '--name-only', 'HEAD^').splitlines() == sorted(LATEST)
    assert git('log', '-1', '--format=%(trailers:key=Signed-off-by,valueonly)') == (
        'Fixture Builder <fixture@example.invalid>'
    )
    receipt = [f'Branch: {branch}', f'Commit: {commit}']
    for path, old in LATEST.items():
        if first_release:
            assert not (root / path).exists()
            new_hash = 'removed'
        else:
            assert (root / path).read_bytes() == PREVIOUS[path]
            new_hash = sha256(PREVIOUS[path]).hexdigest()
        receipt.append(f'{path}: {sha256(old).hexdigest()} -> {new_hash}')
    assert result.stdout.splitlines()[:4] == receipt
    assert git('status', '--porcelain') == ''


@pytest.mark.parametrize('case', ['missing-region', 'missing-repo', 'unknown-option'])
def test_c1_usage_exits_two(repo, case):
    """C1: Bad syntax must be usage (2), not a rollback refusal or a write."""
    root, git = repo
    head = release(repo, 'Release', LATEST)
    region_args = [] if case == 'missing-region' else ['--region', REGION]
    repo_args = [] if case == 'missing-repo' else ['--repo', str(root)]
    extra = ['--unknown'] if case == 'unknown-option' else []
    result = subprocess.run([sys.executable, str(CLI), 'rollback', *region_args, *repo_args, *extra],
                            capture_output=True, text=True)
    assert (result.returncode, result.stdout) == (2, '')
    assert result.stderr.startswith('usage: region.py rollback ')
    assert git('rev-parse', 'HEAD') == head
    assert git('branch', '--list') == '* main'


@pytest.mark.parametrize(('case', 'error'), [
    ('no-history', 'no catalog history for region fixture-coast'),
    ('invalid-id', "invalid region id: '../other'"),
    ('dirty', 'rollback requires a clean worktree and index'),
    ('same-branch', "fatal: a branch named 'existing' already exists"),
    ('ignored', 'ignored files would be in the way of the rollback'),
    ('symlink', f'not a regular catalog file: {POINTER}'),
    ('blocked-directory', 'not a catalog directory: catalog/relief'),
    ('object-is-directory', f'not a file at HEAD: {POINTER}'),
    ('subdirectory', '--repo must point to the root of the clone'),
])
def test_c1_refusal_exits_one_without_a_branch(repo, case, error):
    """C1: Preflight failures must not switch branches, masquerade as usage or print a push step."""
    root, git = repo
    files = dict(LATEST)
    extra = []
    repo_arg = root
    if case == 'no-history':
        files = {'notes.txt': b'No release'}
    elif case in {'ignored', 'blocked-directory', 'object-is-directory'}:
        del files[POINTER]
        if case == 'ignored':
            files['.gitignore'] = (POINTER + '\n').encode()
        elif case == 'blocked-directory':
            files['catalog/relief'] = b'not a directory'
        else:
            files[POINTER + '/nested'] = b'not a blob'
    if case == 'invalid-id':
        extra = ['--region', '../other']
    if case == 'symlink':
        del files[POINTER]
        (root / POINTER).parent.mkdir(parents=True)
        (root / POINTER).symlink_to('../depth-contours/' + REGION + '.geojson')
        git('add', '--', POINTER)
    head = release(repo, 'Release', files)
    if case == 'dirty':
        put(root, POINTER, b'dirty edits')
    elif case == 'same-branch':
        git('branch', 'existing')
        extra = ['--branch', 'existing']
    elif case == 'ignored':
        put(root, POINTER, b'ignored data')
    elif case == 'subdirectory':
        repo_arg = root / 'catalog'
    refs = git('show-ref', '--heads')
    status = git('status', '--porcelain')

    result = invoke(repo_arg, *extra)

    assert (result.returncode, result.stdout, result.stderr) == (1, '', f'region.py rollback: {error}\n')
    assert git('branch', '--show-current') == 'main'
    assert git('rev-parse', 'HEAD') == head
    assert git('show-ref', '--heads') == refs
    assert git('status', '--porcelain') == status


def test_c1_missing_clone_is_refusal(tmp_path, capsys):
    """C1: A nonexistent clone reports a refusal instead of leaking an OS traceback."""
    missing = tmp_path / 'missing'
    assert main(['--region', REGION, '--repo', str(missing)]) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert err.startswith('region.py rollback: [Errno 2] ')
    assert str(missing) in err


def test_c2_reports_manual_publication_without_attempting_it(repo, monkeypatch, capsys):
    """C2: Even a successful rollback may not invoke a publisher or omit the manual next step."""
    root, git = repo
    release(repo, 'Previous release', PREVIOUS)
    release(repo, 'Bad release', LATEST)
    git('remote', 'add', 'origin', str(root / 'never-contact'))
    real_run = subprocess.run

    def local_git_only(argv, *args, **kwargs):
        command = argv[2] if argv[1:2] == ['--literal-pathspecs'] else argv[1]
        assert argv[0] == 'git' and command in {
            'rev-parse', 'log', 'cat-file', 'ls-tree', 'status', 'ls-files',
            'switch', 'hash-object', 'update-index', 'commit',
        }, argv
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', local_git_only)
    branch = 'rollback/fixture-coast-$test'
    assert main(['--region', REGION, '--repo', str(root), '--branch', branch]) == 0
    out, err = capsys.readouterr()
    assert err == ''
    assert out.splitlines()[4:] == [
        "Next: in the clone, run `git push origin 'refs/heads/rollback/fixture-coast-$test'`, "
        'then open one PR into main titled "Roll back relief release for fixture-coast".'
    ]
