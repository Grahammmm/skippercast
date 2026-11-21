import json
import os
import subprocess
import sys

import pytest

from scripts.relief import pointer_diff
from tests._support import ROOT


def source(source_id):
    return {
        'id': source_id, 'label': f'Synthetic {source_id}', 'attribution': 'Fixture',
        'vertical_datum': 'MLLW', 'survey_dates': ['2001'], 'rights_class': 'public',
        'rights': {'public_display': 'allowed', 'license': 'Synthetic fixture'},
    }


def pointer(*, style=True):
    doc = {
        'schema': 'sc-relief-pointer/1', 'status': 'reviewed', 'private': False,
        'generation': 'a' * 64, 'release_sha256': 'b' * 64, 'envelope_sha256': 'c' * 64,
        'sha256': 'd' * 64, 'bytes': 42, 'digest_root_sha256': 'e' * 64, 'previous': None,
        'region': 'fixture-bay', 'bounds': [-3, 1, -2, 2], 'minzoom': 8, 'maxzoom': 9,
        'sources': [source('matched')],
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [
            {'source_id': 'matched', 'min_depth_m': 0, 'max_depth_m': 3, 'resolution_m': 1},
        ]},
        'native_support_by_zoom': {'8': {'tiles': 1, 'sources': []}},
    }
    if style:
        doc['style'] = {'baked': 'f' * 64, 'contours': None, 'habitat': '1' * 64, 'built_with': 'fixture'}
    return doc


def previous_for(base):
    return {key: base[key] for key in ('generation', 'release_sha256', 'envelope_sha256', 'sha256', 'style')
            if key in base}


def write(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def invoke(*args, capsys):
    code = pointer_diff.main([str(arg) for arg in args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_c1_identical_comparison_has_no_rows(tmp_path, capsys):
    """C1: identical fields must not produce phantom changes or certify lineage."""
    path = write(tmp_path / 'same.json', pointer())
    assert invoke('--base', path, '--candidate', path, '--json', capsys=capsys) == (
        1, '{\n  "changes": [],\n  "lineage": "MISMATCH previous"\n}\n', '',
    )


def test_c1_source_changes_by_id_and_selection():
    """C1: positional matching would pair unrelated sources after reorder/add/remove."""
    matched, removed, added = (source(name) for name in ('matched', 'removed', 'added'))
    changed = {**matched, 'survey_dates': ['2002'], 'estimated': False}
    base = {'sources': [matched, removed], 'minzoom': 8, 'bounds': [0, 0, 1, 1]}
    candidate = {'sources': [added, changed], 'minzoom': 9, 'bounds': [0, 0, 1, 1]}
    assert pointer_diff.diff_fields(base, {**base, 'sources': [removed, matched]}) == []
    assert pointer_diff.diff_fields(base, candidate, fields=['sources', 'bounds', 'absent']) == [
        {'field': 'sources["added"]', 'base': None, 'candidate': added},
        {'field': 'sources["matched"].estimated', 'base': None, 'candidate': False},
        {'field': 'sources["matched"].survey_dates', 'base': ['2001'], 'candidate': ['2002']},
        {'field': 'sources["removed"]', 'base': removed, 'candidate': None},
    ]
    # The schema doesn't enforce unique IDs; don't silently overwrite a changed record.
    assert pointer_diff.diff_fields({'sources': [changed, matched]}, {'sources': [matched]}) == [
        {'field': 'sources["matched"]', 'base': [changed, matched], 'candidate': [matched]},
    ]


def test_c1_text_and_json_generation_bump(tmp_path, capsys):
    """C1: report metadata as well as generation and keep nested hashes intact in JSON."""
    before = pointer()
    previous = previous_for(before)
    style = {**before['style'], 'contours': '2' * 64}
    new_bounds = [-4, 1, -2, 2]
    after = {**before, 'generation': '9' * 64, 'release_sha256': '8' * 64, 'minzoom': 9,
             'bounds': new_bounds, 'style': style, 'previous': previous}
    args = ('--base', write(tmp_path / 'base.json', before), '--candidate', write(tmp_path / 'after.json', after))
    code, out, err = invoke(*args, '--json', capsys=capsys)
    assert (code, json.loads(out), err) == (0, {'lineage': 'ok', 'changes': [
        {'field': 'bounds', 'base': [-3, 1, -2, 2], 'candidate': new_bounds},
        {'field': 'generation', 'base': 'a' * 64, 'candidate': '9' * 64},
        {'field': 'minzoom', 'base': 8, 'candidate': 9},
        {'field': 'previous', 'base': None, 'candidate': previous},
        {'field': 'release_sha256', 'base': 'b' * 64, 'candidate': '8' * 64},
        {'field': 'style', 'base': before['style'], 'candidate': style},
    ]}, '')
    assert invoke(*args, capsys=capsys) == (0, (
        'lineage: ok\n'
        'bounds: [-3, 1, -2, 2] -> [-4, 1, -2, 2]\n'
        'generation: "aaaaaaaaaaaa" -> "999999999999"\n'
        'minzoom: 8 -> 9\n'
        'previous: null -> {"envelope_sha256": "cccccccccccc", "generation": "aaaaaaaaaaaa", '
        '"release_sha256": "bbbbbbbbbbbb", "sha256": "dddddddddddd", "style": '
        '{"baked": "ffffffffffff", "built_with": "fixture", "contours": null, "habitat": "111111111111"}}\n'
        'release_sha256: "bbbbbbbbbbbb" -> "888888888888"\n'
        'style: {"baked": "ffffffffffff", "built_with": "fixture", "contours": null, "habitat": "111111111111"}'
        ' -> {"baked": "ffffffffffff", "built_with": "fixture", "contours": "222222222222", '
        '"habitat": "111111111111"}\n'
    ), '')


@pytest.mark.parametrize('field', ['generation', 'release_sha256', 'envelope_sha256', 'sha256', 'style', 'style.baked'],
                         ids=lambda field: f'C2: previous.{field}')
def test_c2_checks_every_previous_field(tmp_path, capsys, field):
    """C2: checking only generation would let a different artifact or style pass."""
    base = pointer()
    previous = previous_for(base)
    if field == 'style':
        previous.pop(field)
    elif field == 'style.baked':
        previous['style'] = {**base['style'], 'baked': '0' * 64}
    else:
        previous[field] = '0' * 64
    args = ('--base', write(tmp_path / 'base.json', base),
            '--candidate', write(tmp_path / 'candidate.json', {**base, 'previous': previous}))
    code, out, err = invoke(*args, '--json', capsys=capsys)
    assert (code, json.loads(out), err) == (1, {
        'lineage': f'MISMATCH previous.{field.split(".")[0]}',
        'changes': [{'field': 'previous', 'base': None, 'candidate': previous}],
    }, '')


@pytest.mark.parametrize(('has_base', 'has_previous', 'extra_style', 'lineage', 'status'), [
    pytest.param(False, False, False, 'first-release', 0, id='C2: missing base with null predecessor'),
    pytest.param(False, True, False, 'MISMATCH previous', 1, id='C2: missing base with claimed predecessor'),
    pytest.param(True, True, False, 'ok', 0, id='C2: match an unstyled base'),
    pytest.param(True, True, True, 'MISMATCH previous.style', 1, id='C2: invented style for unstyled base'),
])
def test_c2_absent_base_or_style(tmp_path, capsys, has_base, has_previous, extra_style, lineage, status):
    """C2: missing base and optional style do not excuse a false predecessor claim."""
    base = pointer(style=False)
    path = tmp_path / 'base.json'
    if has_base:
        write(path, base)
    previous = previous_for(base)
    if extra_style:
        previous['style'] = pointer()['style']
    candidate = write(tmp_path / 'candidate.json', {**base, 'previous': previous if has_previous else None})
    code, out, err = invoke('--candidate', candidate, '--base', path, '--json', capsys=capsys)
    assert (code, json.loads(out)['lineage'], err) == (status, lineage, '')


@pytest.mark.parametrize(('before', 'after', 'error'), [
    pytest.param({'region': 'other-bay'}, {}, "region mismatch: base 'other-bay', candidate 'fixture-bay'",
                 id='C2: wrong region'),
    pytest.param({'minzoom': 7}, {}, 'base: invalid relief metadata at minzoom: 7 is less than the minimum of 8',
                 id='C2: invalid base'),
    pytest.param({}, {'minzoom': 7}, 'candidate: invalid relief metadata at minzoom: 7 is less than the minimum of 8',
                 id='C2: invalid candidate'),
])
def test_c2_refusals(tmp_path, capsys, before, after, error):
    """C2: a region mismatch or invalid input must not emit a review report."""
    base = write(tmp_path / 'before.json', {**pointer(), **before})
    candidate = write(tmp_path / 'after.json', {**pointer(), **after})
    assert invoke('--base', base, '--candidate', candidate, capsys=capsys) == (1, '', f'error: {error}\n')


def git(repo, *args):
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    '-c', 'commit.gpgsign=false', *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                        'GIT_ALLOW_PROTOCOL': ''})


@pytest.fixture
def git_pointers(tmp_path):
    repo = tmp_path / 'clone with spaces'
    repo.mkdir()
    git(repo, 'init', '-b', 'main')
    git(repo, 'commit', '--allow-empty', '-m', 'No pointer')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    path = repo / 'catalog/relief/fixture-bay.json'
    path.parent.mkdir(parents=True)
    base = pointer(style=False)
    write(path, base)
    git(repo, 'add', '--', str(path))
    git(repo, 'commit', '-m', 'Add a pointer')
    # Deliberately disagree with both committed states; the command must not open this file.
    path.write_text('[]', encoding='utf-8')
    return repo, base


def test_c2_git_absence_is_distinct_from_bad_ref(tmp_path, capsys, git_pointers):
    """C2: a path absent at origin/main is not the same as an unreadable revision."""
    repo, base = git_pointers
    candidate = write(tmp_path / 'candidate.json', base)
    args = ('--candidate', candidate, '--repo', repo, '--json')
    code, out, err = invoke(*args, capsys=capsys)
    assert (code, json.loads(out)['lineage'], err) == (0, 'first-release', '')
    code, out, err = invoke(*args, '--ref', 'missing-ref', capsys=capsys)
    assert (code, out, err) == (1, '',
                               "error: base: git show failed: fatal: invalid object name 'missing-ref'.\n")


def test_c3_git_report_is_read_only(tmp_path, monkeypatch, capsys, git_pointers):
    """C3: read the selected Git blob without a shell, fetch, checkout or input rewrite."""
    repo, base = git_pointers
    previous = previous_for(base)
    candidate = write(tmp_path / 'candidate.json', {**base, 'previous': previous})
    run = subprocess.run
    calls = []

    def local_git(argv, **kwargs):
        assert isinstance(argv, list) and argv[0] == 'git' and not kwargs.get('shell')
        assert [arg for arg in argv[1:] if not arg.startswith('-')] == ['show', 'main:catalog/relief/fixture-bay.json']
        assert kwargs['cwd'] == repo
        env = kwargs['env']
        assert (env['GIT_NO_LAZY_FETCH'], env['GIT_ALLOW_PROTOCOL']) == ('1', '')
        calls.append(argv)
        return run(argv, **kwargs)

    def snapshot():
        return {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob('*') if path.is_file()}

    before = snapshot()
    monkeypatch.setattr(subprocess, 'run', local_git)
    code, out, err = invoke('--repo', repo, '--ref', 'main', '--candidate', candidate, '--json', capsys=capsys)
    assert (code, json.loads(out), err) == (0, {
        'lineage': 'ok', 'changes': [{'field': 'previous', 'base': None, 'candidate': previous}],
    }, '')
    assert len(calls) == 1
    assert snapshot() == before


@pytest.mark.parametrize(('args', 'error'), [
    pytest.param([], 'the following arguments are required: --candidate', id='C3: candidate required'),
    pytest.param(['--candidate', 'x'], 'one of the arguments --base --repo is required', id='C3: base required'),
    pytest.param(['--candidate', 'x', '--base', 'y', '--repo', '.'],
                 'argument --repo: not allowed with argument --base', id='C3: base and repo exclusive'),
    pytest.param(['--candidate', 'x', '--base', 'y', '--ref', 'main'], '--ref requires --repo', id='C3: stray ref'),
    pytest.param(['--candidate', 'x', '--repo', '.', '--ref', ':'],
                 '--ref must name a Git revision, not an index or tree path', id='C3: index is not a ref'),
])
def test_c3_usage(args, error, capsys):
    """C3: usage errors must exit 2 before attempting to read any input."""
    with pytest.raises(SystemExit) as exc:
        pointer_diff.main(args)
    assert type(exc.value) is SystemExit and exc.value.code == 2
    out, err = capsys.readouterr()
    assert out == '' and err.splitlines()[-1].endswith(f': error: {error}')


def test_c3_direct_entrypoint_reports_invalid_json(tmp_path):
    """C3: the script entrypoint must exit 1 on invalid JSON, without a traceback."""
    candidate = write(tmp_path / 'candidate.json', [])
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/relief/pointer_diff.py'), '--candidate', str(candidate),
         '--base', str(tmp_path / 'absent.json')],
        cwd=tmp_path, env={**os.environ, 'GIT_ALLOW_PROTOCOL': ''}, capture_output=True, text=True, check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (1, '', 'error: candidate: expected a JSON object\n')
