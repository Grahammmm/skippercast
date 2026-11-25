"""C1-C3 of the `region.py rollback --to <generation>` card, on a tmp repo with three releases.

Each test names the contract it pins and the believable bug that fails it.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
import subprocess

import pytest

from skippercast.relief.rollback import GitCli, RollbackError, main, target_state

REGION = 'fixture-coast'
POINTER = f'catalog/relief/{REGION}.json'
CONTOURS = f'catalog/depth-contours/{REGION}.geojson'
PATHS = (POINTER, CONTOURS)
GEN = {n: sha256(f'generation {n}'.encode()).hexdigest() for n in (1, 2, 3)}


def pointer(generation, note=''):
    return json.dumps({'generation': generation, 'note': note}).encode() + b'\n'


# Release 1 has no contours file; releases 2 and 3 do, with odd bytes that a text round trip would change.
R1 = {POINTER: pointer(GEN[1]), CONTOURS: None}
R2 = {POINTER: pointer(GEN[2]), CONTOURS: b'{"features": []}\r\n\n'}
R3 = {POINTER: pointer(GEN[3]), CONTOURS: b'{"features":[1]}\n'}
SIGNOFF = 'Fixture Builder <fixture@example.invalid>'


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_ALLOW_PROTOCOL', 'file')
    monkeypatch.setenv('LC_ALL', 'C')
    root = tmp_path / 'clone'
    root.mkdir()

    def git(*args, cwd=root):
        return subprocess.check_output(['git', *args], cwd=cwd).decode().strip()

    git('init', '--initial-branch=main', '--template=')
    git('config', 'user.name', 'Fixture Builder')
    git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'commit.gpgsign', 'false')
    git('config', 'core.autocrlf', 'false')
    return root, git


def release(repo, message, files):
    root, git = repo
    for path, data in files.items():
        target = root / path
        if data is None:
            git('rm', '-q', '--ignore-unmatch', '--', path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        git('add', '--', path)
    git('commit', '--allow-empty', '-m', message)
    return git('rev-parse', 'HEAD')


@pytest.fixture
def three(repo):
    """Three releases, then an unrelated commit: HEAD state is release 3."""
    release(repo, 'Release 1', {POINTER: R1[POINTER]})
    release(repo, 'Release 2', R2)
    release(repo, 'Release 3', R3)
    release(repo, 'Unrelated change', {'notes.txt': b'keep\n'})
    return repo


def run_main(root, *extra, region=REGION):
    return main(['--region', region, '--repo', str(root), *extra])


def refusal(capsys, root, git, *extra, region=REGION):
    """Run the command expecting a refusal; assert nothing was switched or written."""
    refs, status, head = git('show-ref', '--heads'), git('status', '--porcelain'), git('rev-parse', 'HEAD')
    code = run_main(root, *extra, region=region)
    out, err = capsys.readouterr()
    assert (code, out) == (1, '')
    assert (git('show-ref', '--heads'), git('status', '--porcelain'), git('rev-parse', 'HEAD')) == (refs, status, head)
    assert git('branch', '--show-current') == 'main'
    return err


# ---- C1: target selection and its three refusals ----

def test_c1_selects_an_older_release_by_prefix_with_both_files(three):
    """C1: Restoring only the previous release, or reading contours from HEAD, fails this exact whole value."""
    root, _ = three
    git = GitCli(root)
    assert target_state(git, REGION, GEN[1][:12]) == R1
    assert target_state(git, REGION, GEN[2][:12]) == R2
    assert target_state(git, REGION, GEN[2]) == R2  # a full 64-hex generation is also a prefix


def test_c1_newest_commit_wins_when_a_generation_was_released_twice(three):
    """C1: A generation restored later has newer contours; picking the oldest commit would restore the stale pair."""
    root, _ = three
    again = {POINTER: pointer(GEN[1], 'released again'), CONTOURS: b'{"features": "again"}\n'}
    release(three, 'Release 1 again', again)
    release(three, 'Release 3 again', R3)
    assert target_state(GitCli(root), REGION, GEN[1][:12]) == again


def test_c1_skips_absent_and_unreadable_historical_pointers(three):
    """C1: A deleted or garbled pointer commit has no generation and must neither match nor abort selection."""
    root, _ = three
    release(three, 'Remove pointer', {POINTER: None})
    release(three, 'Garbled pointer', {POINTER: b'\xff not json'})
    release(three, 'List pointer', {POINTER: b'[]'})
    release(three, 'Numeric generation', {POINTER: b'{"generation": 7}'})
    assert target_state(GitCli(root), REGION, GEN[2][:12]) == R2


def test_c1_ambiguous_prefix_names_both_generations(three, capsys):
    """C1: Two different generations sharing the prefix must be refused, not resolved to the newer one."""
    root, git = three
    twin_a, twin_b = 'ab' * 6 + '0' * 52, 'ab' * 6 + '1' * 52
    release(three, 'Twin A', {POINTER: pointer(twin_a)})
    release(three, 'Twin B', {POINTER: pointer(twin_b)})
    release(three, 'Release 3 again', R3)
    with pytest.raises(RollbackError) as raised:
        target_state(GitCli(root), REGION, 'ab' * 6)
    assert raised.type is RollbackError
    expected = f'ambiguous generation prefix {"ab" * 6}: matches {twin_a}, {twin_b}'
    assert str(raised.value) == expected
    assert refusal(capsys, root, git, '--to', 'ab' * 6) == f'region.py rollback: {expected}\n'
    # one more digit makes the prefix unique again
    assert target_state(GitCli(root), REGION, 'ab' * 6 + '1') == {POINTER: pointer(twin_b), CONTOURS: R3[CONTOURS]}


def test_c1_no_match_is_a_refusal(three, capsys):
    """C1: An unknown prefix must exit 1 naming the prefix, not fall back to the previous release."""
    root, git = three
    absent = '0' * 12
    expected = f'no release of region {REGION} has a generation starting with {absent}'
    with pytest.raises(RollbackError) as raised:
        target_state(GitCli(root), REGION, absent)
    assert (raised.type, str(raised.value)) == (RollbackError, expected)
    assert refusal(capsys, root, git, '--to', absent) == f'region.py rollback: {expected}\n'


def test_c1_no_match_without_any_history(repo, capsys):
    """C1: A region with no catalog history is a no-match refusal under --to."""
    root, git = repo
    release(repo, 'Neighbor only', {'notes.txt': b'x'})
    err = refusal(capsys, root, git, '--to', GEN[1][:12])
    assert err == f'region.py rollback: no release of region {REGION} has a generation starting with {GEN[1][:12]}\n'


def test_c1_target_equal_to_head_state_is_a_refusal(three, capsys):
    """C1: Rolling back to what is already live would make an empty commit and a misleading receipt."""
    root, git = three
    err = refusal(capsys, root, git, '--to', GEN[3][:12])
    assert err == f'region.py rollback: generation prefix {GEN[3][:12]} already matches the current state of region {REGION}\n'


def test_c1_same_pointer_but_different_contours_is_not_equal_to_head(three):
    """C1: Equality is on both files; comparing the pointer alone would refuse a real contours-only restore."""
    root, git = three
    release(three, 'Contours-only change', {CONTOURS: b'{"features":[2]}\n'})
    assert run_main(root, '--to', GEN[3][:12]) == 0
    assert (root / CONTOURS).read_bytes() == R3[CONTOURS]
    assert git('branch', '--show-current') == f'rollback/{REGION}-to-{GEN[3][:12]}'
    assert git('diff', '--name-only', 'HEAD^').splitlines() == [CONTOURS]


@pytest.mark.parametrize('prefix', ['abc', 'a' * 11, 'a' * 65, 'ABCDEF012345', 'xyzxyzxyzxyz', ''])
def test_c1_malformed_prefix_is_usage_not_a_search(three, capsys, prefix):
    """C1: Fewer than 12 hex digits would match many releases; reject at parse time (exit 2, no git writes)."""
    root, git = three
    head = git('rev-parse', 'HEAD')
    with pytest.raises(SystemExit) as raised:
        run_main(root, '--to', prefix)
    assert raised.value.code == 2
    out, err = capsys.readouterr()
    assert out == '' and 'expected 12 to 64 lowercase hex digits' in err
    assert (git('rev-parse', 'HEAD'), git('branch', '--list')) == (head, '* main')


def test_c1_target_state_rejects_a_malformed_prefix_directly(three):
    """C1: The library entry point enforces the same rule, so a caller cannot bypass the CLI parse."""
    with pytest.raises(RollbackError) as raised:
        target_state(GitCli(three[0]), REGION, 'abc')
    assert (raised.type, str(raised.value)) == (RollbackError, "invalid generation prefix: 'abc'")


def test_c1_invalid_region_id_is_refused_first(three):
    """C1: Path traversal in the region is refused before any history is read."""
    with pytest.raises(RollbackError) as raised:
        target_state(GitCli(three[0]), '../other', GEN[1][:12])
    assert (raised.type, str(raised.value)) == (RollbackError, "invalid region id: '../other'")


def test_c1_shallow_clone_is_refused(three, tmp_path, capsys):
    """C1: A shallow clone hides older releases, so a prefix could look unique or absent; refuse it by name."""
    root, _ = three
    shallow = tmp_path / 'shallow'
    subprocess.check_call(['git', 'clone', '-q', '--depth=1', f'file://{root}', str(shallow)])
    code = run_main(shallow, '--to', GEN[1][:12])
    out, err = capsys.readouterr()
    assert (code, out, err) == (1, '', 'region.py rollback: --to needs the full history (not a shallow clone)\n')
    assert not subprocess.check_output(['git', 'branch', '--list', 'rollback/*'], cwd=shallow)


# ---- C2: two-file signed branch, receipt, and unchanged plain rollback ----

def test_c2_rolls_back_past_the_previous_release_on_a_signed_two_file_branch(three, capsys):
    """C2: The branch carries exactly the two catalog paths at the target bytes, signed off, on the default name."""
    root, git = three
    head = git('rev-parse', 'HEAD')
    before = {path: (root / path).read_bytes() for path in PATHS}
    assert run_main(root, '--to', GEN[1][:12]) == 0
    out, err = capsys.readouterr()
    branch = f'rollback/{REGION}-to-{GEN[1][:12]}'
    assert err == ''
    assert git('branch', '--show-current') == branch
    assert git('rev-list', '--parents', '-1', 'HEAD').split()[1:] == [head]
    assert git('diff', '--name-status', 'HEAD^').splitlines() == [f'D\t{CONTOURS}', f'M\t{POINTER}']
    assert git('show', f'HEAD:{POINTER}') == R1[POINTER].decode().strip()
    assert (root / POINTER).read_bytes() == R1[POINTER] and not (root / CONTOURS).exists()
    assert (root / 'notes.txt').read_bytes() == b'keep\n'
    assert git('log', '-1', '--format=%(trailers:key=Signed-off-by,valueonly)') == SIGNOFF
    assert git('status', '--porcelain') == ''
    commit = git('rev-parse', 'HEAD')
    assert out.splitlines()[:4] == [
        f'Branch: {branch}', f'Commit: {commit}',
        f'{POINTER}: {sha256(before[POINTER]).hexdigest()} -> {sha256(R1[POINTER]).hexdigest()}',
        f'{CONTOURS}: {sha256(before[CONTOURS]).hexdigest()} -> removed',
    ]
    assert out.splitlines()[4] == (
        f"Next: in the clone, run `git push origin refs/heads/{branch}`, "
        f'then open one PR into main titled "Roll back relief release for {REGION}".')


def test_c2_restores_exact_contours_bytes_of_the_target_release(three, capsys):
    """C2: A text round trip or HEAD-side read would change the CRLF contours bytes of release 2."""
    root, git = three
    assert run_main(root, '--to', GEN[2][:20]) == 0
    capsys.readouterr()
    assert {path: git('show', f'HEAD:{path}') for path in PATHS} == {
        POINTER: R2[POINTER].decode().strip(), CONTOURS: R2[CONTOURS].decode().strip()}
    assert [(root / path).read_bytes() for path in PATHS] == [R2[POINTER], R2[CONTOURS]]
    assert git('branch', '--show-current') == f'rollback/{REGION}-to-{GEN[2][:12]}'
    assert git('diff', '--name-only', 'HEAD^').splitlines() == sorted(PATHS)


def test_c2_explicit_branch_overrides_the_default_name(three, capsys):
    """C2: --branch must still win over the generated --to name."""
    root, git = three
    assert run_main(root, '--to', GEN[1][:12], '--branch', 'local/undo') == 0
    assert capsys.readouterr().out.splitlines()[0] == 'Branch: local/undo'
    assert git('branch', '--show-current') == 'local/undo'


def test_c2_refuses_a_dirty_checkout_and_an_existing_default_branch(three, capsys):
    """C2: write_branch's guards still apply: dirty tree and an existing target branch both refuse with no change."""
    root, git = three
    (root / 'notes.txt').write_bytes(b'local edit\n')
    err = refusal(capsys, root, git, '--to', GEN[1][:12])
    assert err == 'region.py rollback: rollback requires a clean worktree and index\n'
    git('checkout', '--', 'notes.txt')
    git('branch', f'rollback/{REGION}-to-{GEN[1][:12]}')
    err = refusal(capsys, root, git, '--to', GEN[1][:12])
    assert err == f"region.py rollback: fatal: a branch named 'rollback/{REGION}-to-{GEN[1][:12]}' already exists\n"


def test_c2_without_to_the_plain_rollback_is_unchanged(three, capsys):
    """C2: No --to still restores the state before the last release (release 2) on rollback/<id>-<short HEAD>."""
    root, git = three
    short = git('rev-parse', '--short', 'HEAD')
    assert run_main(root) == 0
    out, _ = capsys.readouterr()
    assert git('branch', '--show-current') == f'rollback/{REGION}-{short}'
    assert [(root / path).read_bytes() for path in PATHS] == [R2[POINTER], R2[CONTOURS]]
    assert out.splitlines()[:2] == [f'Branch: rollback/{REGION}-{short}', f'Commit: {git("rev-parse", "HEAD")}']
    assert git('diff', '--name-only', 'HEAD^').splitlines() == sorted(PATHS)


# ---- C3: read-only git additions ----

def test_c3_is_shallow_reports_a_bool(three, tmp_path):
    """C3: The new read returns exactly True or False; a truthy bytes value would refuse every full clone."""
    root, _ = three
    shallow = tmp_path / 'shallow'
    subprocess.check_call(['git', 'clone', '-q', '--depth=1', f'file://{root}', str(shallow)])
    assert GitCli(root).is_shallow() is False
    assert GitCli(shallow).is_shallow() is True


def test_c3_target_selection_runs_only_read_only_git_argv_lists(three, monkeypatch):
    """C3: Selection may use argv lists with read-only git subcommands, no shell, and leaves the repo untouched."""
    root, git = three
    refs, status = git('show-ref', '--heads'), git('status', '--porcelain')
    seen = []
    real = subprocess.run

    def spy(argv, *args, **kwargs):
        seen.append((argv, kwargs.get('shell')))
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', spy)
    assert target_state(GitCli(root), REGION, GEN[1][:12]) == R1
    monkeypatch.undo()
    assert seen
    subcommands = set()
    for argv, shell in seen:
        assert type(argv) is list and argv[0] == 'git' and not shell
        subcommands.add(argv[2] if argv[1] == '--literal-pathspecs' else argv[1])
    assert subcommands <= {'rev-parse', 'log', 'ls-tree', 'cat-file'}
    assert (git('show-ref', '--heads'), git('status', '--porcelain')) == (refs, status)
