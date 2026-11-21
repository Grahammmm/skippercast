"""Offline runtime acceptance for the regional release-history CLI."""
from hashlib import sha256
import json
import os
import subprocess
import sys

import pytest

from skippercast.relief.rollback import GitCli, previous_state
from tests._support import ROOT

CLI = ROOT / 'scripts' / 'relief' / 'release_history.py'
REGION = 'fixture-bay'
POINTER = f'catalog/relief/{REGION}.json'
CONTOURS = f'catalog/depth-contours/{REGION}.geojson'
COLUMNS = 'commit\tdate\tgeneration\tenvelope_sha256\tstyle.built_with\tcontours_sha256\tstatus\trollback'
A = b'{"type":"FeatureCollection","features":[]}\n'
B = b'{"type": "FeatureCollection", "features": []}\n'


def pointer(region=REGION, generation='a', envelope='b', style=None):
    doc = {
        'schema': 'sc-relief-pointer/1', 'status': 'reviewed', 'private': False,
        'region': region, 'generation': generation * 64, 'release_sha256': 'f' * 64,
        'envelope_sha256': envelope * 64, 'sha256': '0' * 64, 'bytes': 1,
        'digest_root_sha256': '1' * 64, 'previous': None,
        'bounds': [-122, 36, -121, 37], 'minzoom': 8, 'maxzoom': 8,
        'sources': [{'id': 'fixture', 'label': 'Fixture', 'attribution': 'Fixture',
                     'vertical_datum': 'Fixture datum', 'survey_dates': ['2020'],
                     'release_date': '2021-02-03', 'rights_class': 'public',
                     'rights': {'public_display': 'allowed', 'license': 'Fixture license'}}],
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [
            {'source_id': 'fixture', 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': 2}]},
        'native_support_by_zoom': {'8': {'tiles': 1, 'sources': []}},
    }
    if style is not None:
        doc['style'] = {'baked': '2' * 64, 'contours': None, 'habitat': None, 'built_with': style}
    return json.dumps(doc).encode()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_ALLOW_PROTOCOL', 'file')
    monkeypatch.setenv('LC_ALL', 'C')

    def git(*args, day=1):
        return subprocess.check_output(['git', *args], cwd=tmp_path, env={
            **os.environ, 'GIT_AUTHOR_DATE': '2024-01-01T00:00:00Z',
            'GIT_COMMITTER_DATE': f'2025-02-{day:02}T22:03:04-08:00',
        }, text=True).strip()

    git('init', '--initial-branch=main', '--template=')
    git('config', 'user.name', 'Fixture Builder')
    git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'core.autocrlf', 'false')
    return tmp_path, git


def release(repo, day, files):
    root, git = repo
    for path, data in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    git('add', '--', *files)
    git('commit', '-m', f'Fixture change {day}', day=day)
    return git('rev-parse', 'HEAD')


def invoke(root, *regions):
    result = subprocess.run([sys.executable, str(CLI), '--repo', str(root), *regions],
                            capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def row(commit, date, generation='-', envelope='-', style='-', contours=None,
        status='reviewed', rollback='-'):
    contour_hash = '-' if contours is None else sha256(contours).hexdigest()[:12]
    return '\t'.join((commit, date, generation, envelope, style, contour_hash, status, rollback))


def report(region, *rows):
    return '\n'.join((f'region {region}', COLUMNS, *rows, ''))


def test_c1_three_versions_include_merge_date_and_contours_only_change(repo):
    """C1: A side commit, author/source date, or generation-only target would misreport live history."""
    root, git = repo
    old = release(repo, 1, {POINTER: pointer()})
    git('switch', '-c', 'review')
    reviewed = pointer(generation='c', envelope='d', style='fixture-v2')
    release(repo, 2, {POINTER: reviewed, CONTOURS: A})
    git('switch', 'main')
    git('merge', '--no-ff', 'review', '-m', 'Land reviewed release', day=3)
    merged = git('rev-parse', 'HEAD')
    release(repo, 4, {'notes.txt': b'Unrelated before release\n'})
    latest = release(repo, 5, {CONTOURS: B})
    release(repo, 6, {'notes.txt': b'Unrelated after release\n'})
    # Compare to the real rollback reader (no branch creation or writes).
    assert previous_state(GitCli(root), REGION) == {POINTER: reviewed, CONTOURS: A}
    assert invoke(root) == (0, report(REGION,
        row(latest, '2025-02-06T06:03:04Z', 'c' * 64, 'd' * 12, 'fixture-v2', B),
        row(merged, '2025-02-04T06:03:04Z', 'c' * 64, 'd' * 12, 'fixture-v2', A, rollback='restore'),
        row(old, '2025-02-02T06:03:04Z', 'a' * 64, 'b' * 12),
    ), '')


def test_c1_default_discovery_and_explicit_filter(repo):
    """C1: A HEAD-only region scan would lose removed regions, and filters must not leak other rows."""
    root, git = repo
    other = 'other-bay'
    other_path = f'catalog/depth-contours/{other}.geojson'
    first = release(repo, 1, {POINTER: pointer(), other_path: A,
                             'catalog/relief/pointer.schema.json': b'{}'})
    git('rm', '--cached', '--', other_path)  # still in worktree; absent from the next commit
    git('commit', '-m', 'Remove standalone contours', day=2)
    removed = git('rev-parse', 'HEAD')
    one = report(REGION, row(first, '2025-02-02T06:03:04Z', 'a' * 64, 'b' * 12),
                 '  rollback restores no catalog files (first release)')
    two = report(other, row(removed, '2025-02-03T06:03:04Z', status='absent'),
                 row(first, '2025-02-02T06:03:04Z', contours=A, status='absent', rollback='restore'))
    assert invoke(root) == (0, one + two, '')
    assert invoke(root, other, other, 'unknown-bay') == (0, two + 'region unknown-bay\n  no catalog history\n', '')


def test_c1_no_catalog_history(repo):
    """C1: An unrelated commit is not a release for an implicitly selected region."""
    root, _ = repo
    release(repo, 1, {'notes.txt': b'No uploads\n'})
    assert invoke(root) == (0, 'no regional catalog history\n', '')


@pytest.mark.parametrize(('bad_pointer', 'error'), [
    (pointer().replace(b'"reviewed"', b'"draft"'), 'invalid relief metadata at status: \'reviewed\' was expected'),
    (b'{', 'Expecting property name enclosed in double quotes: line 1 column 2 (char 1)'),
], ids=['C2: schema failure', 'C2: malformed JSON'])
def test_c2_invalid_rollback_target_is_not_skipped(repo, bad_pointer, error):
    """C2: Invalid data must not vanish or make the marker jump to a valid but older state."""
    root, _ = repo
    old = release(repo, 1, {POINTER: pointer()})
    invalid = release(repo, 2, {POINTER: bad_pointer, CONTOURS: A})
    latest = release(repo, 3, {POINTER: pointer(generation='c', envelope='d')})
    assert invoke(root, REGION) == (0, report(REGION,
        row(latest, '2025-02-04T06:03:04Z', 'c' * 64, 'd' * 12, contours=A),
        row(invalid, '2025-02-03T06:03:04Z', contours=A, status=f'invalid: {json.dumps(error)}', rollback='restore'),
        row(old, '2025-02-02T06:03:04Z', 'a' * 64, 'b' * 12),
    ), '')


def test_c2_git_scan_leaves_dirty_checkout_intact(repo):
    """C2: Reading worktree or index instead of blobs gives the wrong row; a write changes the snapshot."""
    root, git = repo
    first = release(repo, 1, {POINTER: pointer(), CONTOURS: A})
    (root / POINTER).write_bytes(b'Staged pointer')
    git('add', '--', POINTER)
    (root / CONTOURS).write_bytes(b'Unstaged contours')

    def snapshot():
        return {path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in root.rglob('*') if path.is_file()}

    before = snapshot()
    assert invoke(root, REGION) == (0, report(REGION,
        row(first, '2025-02-02T06:03:04Z', 'a' * 64, 'b' * 12, contours=A),
        '  rollback restores no catalog files (first release)'), '')
    assert snapshot() == before


@pytest.mark.parametrize('case', ['region', 'subdir', 'shallow', 'no-repo'], ids=[
    'C2: invalid region', 'C2: subdirectory is not root', 'C2: incomplete history', 'C2: missing clone',
])
def test_c2_refuses_unusable_history_inputs(repo, case):
    """C2: Bad inputs must fail, not emit a plausible empty or truncated history."""
    root, git = repo
    head = release(repo, 1, {POINTER: pointer()})
    if case == 'region':
        assert invoke(root, REGION, '../elsewhere') == (1, '', "release_history.py: invalid region id: '../elsewhere'\n")
    elif case == 'subdir':
        assert invoke(root / 'catalog') == (1, '', 'release_history.py: --repo must point to the root of the clone\n')
    elif case == 'shallow':
        (root / '.git/shallow').write_text(head + '\n', encoding='ascii')
        assert invoke(root) == (1, '', 'release_history.py: --repo must contain full history (not a shallow clone)\n')
    else:
        missing = root / 'missing'
        assert invoke(missing) == (1, '', f'release_history.py: [Errno 2] No such file or directory: {missing!r}\n')


def test_c2_missing_repo_option_is_usage_error():
    """C2: A missing --repo cannot silently scan the tools checkout."""
    result = subprocess.run([sys.executable, str(CLI)], capture_output=True, text=True)
    assert (result.returncode, result.stdout, result.stderr) == (
        2, '', 'usage: release_history.py [-h] --repo REPO [REGION ...]\n'
        'release_history.py: error: the following arguments are required: --repo\n',
    )
