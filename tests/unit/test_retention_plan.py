"""Offline retention-plan CLI acceptance."""
import json
import subprocess
import sys

import pytest

from tests._support import ROOT
from tests.unit.test_release_history import A, CONTOURS, POINTER, REGION, pointer, release, repo

CLI = ROOT / 'scripts' / 'relief' / 'retention_plan.py'
OLD, PREVIOUS, LIVE, EXTRA, OTHER = (letter * 64 for letter in 'abcde')


def invoke(root, *args):
    result = subprocess.run([sys.executable, str(CLI), '--repo', str(root), *map(str, args)],
                            capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def build(out, region, stage, generation):
    path = out / region / stage / generation
    path.mkdir(parents=True)
    (path / 'fixture').write_text('local generation', encoding='utf-8')
    return path


def json_report(result):
    code, text, error = result
    assert (code, error) == (0, '')
    return json.loads(text)


def test_c1_all_reviewed_generations_and_out_only_region(repo):
    """C1: A contour-only commit must not make live its own predecessor or hide older builds."""
    root, git = repo
    other = 'out-only-bay'
    release(repo, 1, {POINTER: pointer(generation='a')})
    release(repo, 2, {POINTER: pointer(generation='b')})
    git('switch', '-c', 'review')
    release(repo, 3, {POINTER: pointer(generation='c')})
    git('switch', 'main')
    git('merge', '--no-ff', 'review', '-m', 'Land latest review', day=4)
    release(repo, 5, {CONTOURS: A})
    out = root / 'out'
    build(out, REGION, 'release', OLD)
    build(out, REGION, 'release', PREVIOUS)
    build(out, REGION, 'review', LIVE)
    build(out, REGION, 'release', EXTRA)
    build(out, REGION, 'review', EXTRA)
    build(out, other, 'review', OTHER)
    build(out, REGION, 'release', EXTRA + '.tmp-12')
    (out / REGION / 'release' / ('f' * 64)).touch()

    assert json_report(invoke(root, '--out', out, '--json')) == {'regions': [
        {'region': REGION, 'keep': [
            {'generation': LIVE, 'roles': ['live']},
            {'generation': PREVIOUS, 'roles': ['rollback']},
            {'generation': OLD, 'roles': []},
        ], 'unreferenced': [EXTRA], 'missing-local': []},
        {'region': other, 'keep': [], 'unreferenced': [OTHER], 'missing-local': []},
    ]}
    assert json_report(invoke(root, '--out', out, other, '--json', other)) == {'regions': [
        {'region': other, 'keep': [], 'unreferenced': [OTHER], 'missing-local': []},
    ]}


def test_c1_same_generation_can_have_both_roles(repo):
    """C1: Deduplication before role assignment would incorrectly give rollback to OLD."""
    root, _ = repo
    out = root / 'out'
    release(repo, 1, {POINTER: pointer()})
    release(repo, 2, {POINTER: pointer(generation='b')})
    release(repo, 3, {POINTER: pointer(generation='b', envelope='e')})
    build(out, REGION, 'release', OLD)
    build(out, REGION, 'review', PREVIOUS)
    assert invoke(root, '--out', out, REGION) == (
        0, f'region {REGION}\n  keep {PREVIOUS} live rollback\n  keep {OLD}\n', '',
    )


@pytest.mark.parametrize(('case', 'keep', 'missing'), [
    ('absent-newest', [(PREVIOUS, ['rollback']), (OLD, [])], []),
    ('invalid-newest', [(PREVIOUS, ['rollback']), (OLD, [])], []),
    ('absent-rollback', [(LIVE, ['live']), (PREVIOUS, []), (OLD, [])], [LIVE]),
], ids=['C1: absent newest pointer', 'C1: invalid newest pointer', 'C1: absent rollback position'])
def test_c1_roles_follow_history_position_when_a_pointer_is_not_reviewed(repo, case, keep, missing):
    """C1: Roles belong to history positions 0 (live) and 1 (rollback), not to reviewed rows only.

    Plausible bugs caught: (1) dropping absent or invalid rows before roles are handed out
    reports the previous release as live although the newest pointer is gone, disagreeing
    with release_history's index-1 restore mark; (2) the same drop shifts rollback onto the
    build after an absent rollback position; (3) the keep list loses or gains a reviewed
    generation while roles are corrected.
    """
    root, git = repo
    out = root / 'out'
    release(repo, 1, {POINTER: pointer(generation='a')})
    release(repo, 2, {POINTER: pointer(generation='b')})
    if case == 'invalid-newest':
        release(repo, 3, {POINTER: b'{'})
    else:
        git('rm', '--cached', '--', POINTER)
        git('commit', '-m', 'Remove pointer', day=3)
    if case == 'absent-rollback':
        release(repo, 4, {POINTER: pointer(generation='c')})
    build(out, REGION, 'release', OLD)
    build(out, REGION, 'review', PREVIOUS)

    assert json_report(invoke(root, '--out', out, REGION, '--json')) == {'regions': [
        {'region': REGION,
         'keep': [{'generation': generation, 'roles': roles} for generation, roles in keep],
         'unreferenced': [], 'missing-local': missing},
    ]}


def test_c2_missing_local_does_not_remove_keep_or_fail_report(repo):
    """C2: Looking only at built directories drops the sole reviewed keep generation."""
    root, _ = repo
    out = root / 'absent-out'
    release(repo, 1, {POINTER: pointer()})
    assert invoke(root, '--out', out, REGION) == (
        0, f'region {REGION}\n  keep {OLD} live\n  missing-local {OLD}\n', '',
    )


def test_c1_no_generations(repo):
    """C1: A repo with no catalog history and no OUT has an empty successful plan."""
    root, _ = repo
    release(repo, 1, {'notes.txt': b'no releases'})
    assert invoke(root, '--out', root / 'out') == (0, 'no regional generations\n', '')


def test_c3_report_leaves_repo_index_and_out_unchanged(repo):
    """C3: Inspecting Git or unreferenced output must neither refresh nor change local state."""
    root, git = repo
    out = root / 'out'
    release(repo, 1, {POINTER: pointer()})
    build(out, REGION, 'release', EXTRA)
    (root / POINTER).write_bytes(pointer(generation='d'))
    git('add', '--', POINTER)

    def snapshot():
        return {p.relative_to(root): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                for p in root.rglob('*')}

    before = snapshot()
    assert invoke(root, '--out', out, REGION) == (0, f'region {REGION}\n'
        f'  keep {OLD} live\n  unreferenced {EXTRA}\n  missing-local {OLD}\n', '')
    assert snapshot() == before


@pytest.mark.parametrize(('case', 'message'), [
    ('region', "invalid region id '../elsewhere'"),
    ('subdir', '--repo must point to the root of the clone'),
    ('shallow', '--repo must contain full history (not a shallow clone)'),
    ('partial', '--repo must contain full history (not a partial clone)'),
], ids=['C3: invalid region', 'C3: non-root clone', 'C3: shallow clone', 'C3: partial clone'])
def test_c3_bad_history_inputs_refuse_without_report(repo, case, message):
    """C3: Unusable history must not yield a plausible but incomplete retention plan."""
    root, git = repo
    head = release(repo, 1, {POINTER: pointer()})
    out = root / 'out'
    regions = [REGION]
    if case == 'region':
        regions.append('../elsewhere')
    elif case == 'subdir':
        root = root / 'catalog'
    elif case == 'shallow':
        (root / '.git' / 'shallow').write_text(head + '\n', encoding='ascii')
    else:
        git('config', 'remote.origin.promisor', 'true')
    assert invoke(root, '--out', out, *regions) == (2, '', f'retention_plan.py: {message}\n')


def test_c3_non_directory_out_refuses(repo):
    """C3: An unreadable inventory path must not look like an empty output root."""
    root, _ = repo
    release(repo, 1, {POINTER: pointer()})
    out = root / 'out'
    out.touch()
    assert invoke(root, '--out', out) == (
        2, '', f'retention_plan.py: [Errno 20] Not a directory: {str(out)!r}\n',
    )


def test_c3_missing_out_returns_usage_error(repo):
    """C3: omitting --out must not silently pick a local output directory."""
    root, _ = repo
    assert invoke(root) == (
        2, '', 'usage: retention_plan.py [-h] --repo REPO --out OUT [--json] [REGION ...]\n'
        'retention_plan.py: error: the following arguments are required: --out\n',
    )
