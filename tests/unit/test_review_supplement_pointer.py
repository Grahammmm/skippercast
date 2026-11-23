"""Numbered offline acceptance for the R8 supplement's pointer preview."""
import json
from pathlib import Path
import subprocess

import pytest

from scripts.relief import review_supplement
from skippercast.relief import envelope, package
from tests.unit import test_relief_package as fixture
from tests.unit.test_pointer_diff import git
from tests.unit.test_r8_packet import _snapshot, build  # noqa: F401 (pytest fixture)
from tests.unit.test_relief_package import assembly  # noqa: F401 (pytest fixture)

_REGION = 'fixture-west'
_HEADING = 'Depth coverage fixture-west (supplement only)\n  depth: not computed (run region.py depth-coverage)\n'
_SOURCE = ('{"attribution": "Synthetic survey", "id": "synthetic-grid", "label": "estimated", '
           '"rights": {"license": "public-domain", "public_display": "allowed"}, "rights_class": "public", '
           '"survey_dates": ["2020"], "vertical_datum": "NAVD88"}')
_STYLE = {'baked': 'f' * 64, 'contours': None, 'habitat': '1' * 64, 'built_with': 'fixture'}


@pytest.fixture
def released(build):  # noqa: F811
    """One verified release for fixture-west and a clone whose origin/main has no pointer yet."""
    out, make = build
    _, release, _, review = make(_REGION)
    repo = out.parent / 'clone'
    repo.mkdir()
    git(repo, 'init', '-b', 'main')
    git(repo, 'commit', '--allow-empty', '-m', 'No pointer')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    return out, repo, json.loads(release.read_bytes()), review


def _base(release, **changes):
    pointer = {key: release[key] for key in package.METADATA}
    pointer.update(schema='sc-relief-pointer/1', status='reviewed', private=False, generation='a' * 64,
                   release_sha256='b' * 64, envelope_sha256='c' * 64, sha256='d' * 64, bytes=42,
                   digest_root_sha256='e' * 64, previous=None)
    return pointer | changes


def _commit(repo, value, region=_REGION):
    path = repo / 'catalog' / 'relief' / f'{region}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8')
    git(repo, 'add', '--', str(path))
    git(repo, 'commit', '-m', 'Pointer')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')


def _changed_base(release):
    retired = json.loads(_SOURCE) | {'id': 'retired-grid'}
    old = json.loads(_SOURCE) | {'attribution': 'Old survey'}
    return _base(release, minzoom=9, maxzoom=10, sources=[retired, old], style=_STYLE)


def _changed_rows(release):
    gen = release['generation'][:12]
    retired = _SOURCE.replace('"synthetic-grid"', '"retired-grid"')
    return [
        ('pointer preview', 'against origin/main, changed fields: 6'),
        ('previous will be', 'aaaaaaaaaaaa'),
        ('pointer generation', f'"aaaaaaaaaaaa" -> "{gen}"'),
        ('pointer maxzoom', '10 -> 8'),
        ('pointer minzoom', '9 -> 8'),
        ('pointer sources["retired-grid"]', f'{retired} -> null'),
        ('pointer sources["synthetic-grid"].attribution', '"Old survey" -> "Synthetic survey"'),
        ('pointer style', '{"baked": "ffffffffffff", "built_with": "fixture", "contours": null, '
                          '"habitat": "111111111111"} -> null'),
    ]


def _text(rows):
    return ''.join(f'  {key}: {value}\n' for key, value in rows)


def _observe(capsys, *args):
    capsys.readouterr()
    code = review_supplement.main([str(arg) for arg in args])
    return code, *capsys.readouterr()


def test_C1_without_repo_says_not_compared(released, capsys):
    """C1: Catch reading a base or the release, or staying silent, when --repo is absent."""
    out, *_ = released
    assert _observe(capsys, '--out', out, _REGION) == (
        0, _HEADING + '  pointer preview: not compared (no --repo)\n', '')


def test_C1_first_release_compares_against_empty_base(released, capsys):
    """C1: Catch a missing first-release line, non-pointer fields, or a base invented from the release."""
    out, repo, release, _ = released
    gen = release['generation'][:12]
    assert _observe(capsys, '--out', out, '--repo', repo, _REGION) == (0, _HEADING + _text([
        ('pointer preview', 'against origin/main, changed fields: 8'),
        ('previous will be', 'null (first release)'),
        ('pointer bounds', 'null -> [-121.3, 35.1, -121, 35.5]'),
        ('pointer detail_summary', 'null -> {"depth_bands": [{"max_depth_m": 20, "min_depth_m": 0, '
                                   '"resolution_m": 2, "source_id": "synthetic-grid", "support_class": 2}], '
                                   '"mask": "transparent-nodata"}'),
        ('pointer generation', f'null -> "{gen}"'),
        ('pointer maxzoom', 'null -> 8'),
        ('pointer minzoom', 'null -> 8'),
        ('pointer native_support_by_zoom', 'null -> {"8": {"limit_m": 91.44, "sources": [], "tiles": 1}}'),
        ('pointer region', 'null -> "fixture-west"'),
        ('pointer sources["synthetic-grid"]', f'null -> {_SOURCE}'),
    ]), '')


def test_C1_changed_zooms_sources_and_style_against_ref(released, capsys):
    """C1: Catch whole-list source diffs, unsorted rows, a dropped style, or the wrong previous generation."""
    out, repo, release, _ = released
    _commit(repo, _changed_base(release))
    git(repo, 'branch', 'reviewed')
    _commit(repo, _base(release))  # origin/main now matches the release except its generation
    gen = release['generation'][:12]
    assert _observe(capsys, '--out', out, '--repo', repo, _REGION) == (0, _HEADING + _text([
        ('pointer preview', 'against origin/main, changed fields: 1'),
        ('previous will be', 'aaaaaaaaaaaa'),
        ('pointer generation', f'"aaaaaaaaaaaa" -> "{gen}"'),
    ]), '')
    assert _observe(capsys, '--out', out, '--repo', repo, '--ref', 'reviewed', _REGION) == (
        0, _HEADING + _text(_changed_rows(release)).replace('against origin/main', 'against reviewed'), '')


def test_C1_release_style_is_compared(tmp_path, assembly, capsys):  # noqa: F811
    """C1: Catch dropping the release's style, which would show the reviewed style as removed."""
    region, release_path, _, _, _ = fixture.approved(tmp_path / 'out', style=fixture.kit_style())
    release = json.loads(release_path.read_bytes())
    repo = tmp_path / 'clone'
    repo.mkdir()
    git(repo, 'init', '-b', 'main')
    _commit(repo, _base(release, style=release['style']), region.id)
    assert _observe(capsys, '--out', tmp_path / 'out', '--repo', repo, region.id) == (0, (
        f'Depth coverage {region.id} (supplement only)\n'
        '  depth: not computed (run region.py depth-coverage)\n'
        '  pointer preview: against origin/main, changed fields: 1\n'
        '  previous will be: aaaaaaaaaaaa\n'
        f'  pointer generation: "aaaaaaaaaaaa" -> "{release["generation"][:12]}"\n'
    ), '')


@pytest.mark.parametrize(('base', 'reason'), [
    pytest.param(lambda release: _base(release, region='other-bay'), "base pointer is for region 'other-bay'",
                 id='C2: base for another region'),
    pytest.param(lambda release: _base(release, maxzoom=99),
                 'invalid relief metadata at maxzoom: 99 is greater than the maximum of 17', id='C2: schema-invalid base'),
    pytest.param(lambda release: '[', 'Expecting value: line 1 column 2 (char 1)', id='C2: malformed base JSON'),
])
def test_C2_invalid_base_is_reported_and_fails(released, capsys, base, reason):
    """C2: Catch accepting an unusable base, or returning success when the base is invalid."""
    out, repo, release, _ = released
    _commit(repo, base(release))
    assert _observe(capsys, '--out', out, '--repo', repo, _REGION) == (
        1, _HEADING + f'  pointer preview: invalid base ({reason})\n', '')


def test_C2_unreadable_ref_is_invalid_base_and_next_region_still_prints(released, capsys):
    """C2: Catch treating a bad ref as a first release, or stopping before the next region."""
    out, repo, *_ = released
    assert _observe(capsys, '--out', out, '--repo', repo, '--ref', 'missing-ref', _REGION, 'fixture-east') == (1, (
        _HEADING + "  pointer preview: invalid base (git show failed: fatal: invalid object name 'missing-ref'.)\n"
        'Depth coverage fixture-east (supplement only)\n'
        '  depth: not computed (run region.py depth-coverage)\n'
        "  pointer preview: invalid base (git show failed: fatal: invalid object name 'missing-ref'.)\n"
    ), '')


def test_C2_unverifiable_release_is_unavailable(released, capsys):
    """C2: Catch previewing unverified release bytes or failing the run for a missing release."""
    out, repo, _, review = released
    release_path = review.parents[2] / 'release' / review.parent.name / 'release.json'
    release_path.write_bytes(release_path.read_bytes() + b'\n')
    assert _observe(capsys, '--out', out, '--repo', repo, _REGION, 'fixture-east') == (0, (
        _HEADING + '  pointer preview: unavailable (release.json does not match envelope)\n'
        'Depth coverage fixture-east (supplement only)\n'
        '  depth: not computed (run region.py depth-coverage)\n'
        "  pointer preview: unavailable (artifact is missing or not a file: 'stages/package.json')\n"
    ), '')
    assert not (out / 'fixture-east').exists()


@pytest.mark.parametrize(('args', 'error'), [
    pytest.param(['--ref', 'main'], '--ref requires --repo', id='C2: ref without repo'),
    pytest.param(['--repo', '.', '--ref', ''], '--ref must name a Git revision, not an index or tree path',
                 id='C2: empty ref'),
    pytest.param(['--repo', '.', '--ref', 'main:catalog'], '--ref must name a Git revision, not an index or tree path',
                 id='C2: tree path is not a ref'),
])
def test_C2_ref_usage_refuses_before_printing(args, error, capsys):
    """C2: Catch silently ignoring --ref or reading an index or tree path as the base."""
    with pytest.raises(SystemExit) as exc:
        review_supplement.main(['--out', 'out', *args, _REGION])
    assert type(exc.value) is SystemExit and exc.value.code == 2
    assert capsys.readouterr() == ('', (
        'usage: review_supplement.py [-h] --out OUT [--markdown] [--repo CLONE [--ref REF]] REGION [REGION ...]\n'
        f'review_supplement.py: error: {error}\n'
    ))


def test_C3_markdown_preview_is_read_only_and_needs_no_approval(released, capsys, monkeypatch):
    """C3: Catch a pointer build, an approval read, a write, a non-show git call or Markdown without the block."""
    out, repo, release, review = released
    _commit(repo, _changed_base(release))
    fixture.write_json(review.with_name('approval.json'), {'verdict': 'must not be read'})
    read_bytes, run = Path.read_bytes, subprocess.run
    calls = []

    def no_approval(self):
        assert self.name != 'approval.json'
        return read_bytes(self)

    def show_only(argv, **kwargs):
        assert isinstance(argv, list) and argv[:3] == ['git', '--no-pager', 'show'] and not kwargs.get('shell')
        calls.append(argv[-1])
        return run(argv, **kwargs)

    def refuse(*_args, **_kwargs):
        raise AssertionError('a pointer must not be built or approved here')

    before = _snapshot(out.parent)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'read_bytes', no_approval)
        patch.setattr(subprocess, 'run', show_only)
        patch.setattr(envelope, 'build_pointer', refuse)
        patch.setattr(envelope, 'verify_chain', refuse)
        code, stdout, stderr = _observe(capsys, '--out', out, '--repo', repo, '--markdown', _REGION)
    assert (code, stderr) == (0, '')
    rows = [('depth', 'not computed (run region.py depth-coverage)'), *_changed_rows(release)]
    assert stdout == (
        '| Field | Value |\n| --- | --- |\n| Depth coverage fixture-west (supplement only) |  |\n'
        + ''.join(f'| {key} | {value.replace(">", "&gt;")} |\n' for key, value in rows) + '\n'
    )
    assert calls == ['origin/main:catalog/relief/fixture-west.json']
    assert _snapshot(out.parent) == before
