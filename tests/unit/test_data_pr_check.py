"""Runtime acceptance for the read-only relief data PR check (C1-C3).

One fixture clone holds a branch per case; the tool only reads it, so the tests
share it. Its working tree deliberately disagrees with every commit, so a check
that read files instead of Git objects would fail every case.
"""
import json
import shutil
import subprocess
import sys

import pytest

from scripts.relief import data_pr_check
from tests._support import ROOT
from tests.unit.test_pointer_diff import git, pointer, previous_for

POINTER = 'catalog/relief/fixture-bay.json'
CONTOURS = 'catalog/depth-contours/fixture-bay.geojson'
SCHEMA = 'catalog/relief/pointer.schema.json'
OTHER_POINTER = 'catalog/relief/other-bay.json'
OTHER_CONTOURS = 'catalog/depth-contours/other-bay.geojson'
FIRST = pointer()
SECOND = {**FIRST, 'generation': '9' * 64, 'release_sha256': '8' * 64, 'previous': previous_for(FIRST)}
BAD_MINZOOM = 'invalid relief metadata at minzoom: 7 is less than the minimum of 8'


def contours(region='fixture-bay', interval=30):
    return {'type': 'FeatureCollection', 'provenance': {'region_id': region, 'interval_ft': interval},
            'features': []}


FIRST_PAIR = {POINTER: FIRST, CONTOURS: contours()}
# Each branch: (start branch, files to write; None deletes the file).
BRANCHES = {
    'first': ('seed', FIRST_PAIR),
    'second': ('first', {POINTER: SECOND, CONTOURS: contours(interval=20)}),
    'contours-over-first': ('first', {CONTOURS: contours(interval=20)}),
    'contours-over-second': ('second', {CONTOURS: contours(interval=10)}),
    'extra-file': ('seed', {**FIRST_PAIR, 'notes.txt': 'extra'}),
    'extra-readme': ('seed', {**FIRST_PAIR, 'catalog/relief/README.md': 'edited'}),
    'extra-schema': ('seed', {**FIRST_PAIR, 'catalog/relief/pointer.schema.json': None}),
    'bad-region-id': ('seed', {**FIRST_PAIR, 'catalog/relief/Fixture_Bay.json': FIRST}),
    'wrong-extension': ('seed', {**FIRST_PAIR, 'catalog/depth-contours/fixture-bay.json': contours()}),
    'two-regions': ('seed', {**FIRST_PAIR, OTHER_POINTER: {**FIRST, 'region': 'other-bay'},
                             OTHER_CONTOURS: contours('other-bay')}),
    'pointer-only': ('first', {POINTER: SECOND}),
    'pointer-deleted': ('first', {POINTER: None, CONTOURS: None}),
    'pointer-deleted-contours-changed': ('first', {POINTER: None, CONTOURS: contours(interval=20)}),
    'wrong-lineage': ('first', {POINTER: {**SECOND, 'previous': {**previous_for(FIRST), 'generation': '0' * 64}},
                                CONTOURS: contours(interval=20)}),
    'contours-wrong-region': ('seed', {POINTER: FIRST, CONTOURS: contours('other-bay')}),
    'contours-without-pointer': ('seed', {CONTOURS: contours()}),
    'invalid-pointer': ('seed', {POINTER: {**FIRST, 'minzoom': 7}, CONTOURS: contours()}),
    'over-invalid-base': ('invalid-pointer', {POINTER: SECOND, CONTOURS: contours(interval=20)}),
    'foreign-base': ('seed', {POINTER: {**FIRST, 'region': 'other-bay'}, CONTOURS: contours()}),
    'over-foreign-base': ('foreign-base', {POINTER: SECOND, CONTOURS: contours(interval=20)}),
    # Both refs lack a usable pointer schema, so check_catalog has no context to read.
    'no-schema': ('seed', {SCHEMA: None}),
    'no-schema-first': ('no-schema', FIRST_PAIR),
    'bad-schema': ('seed', {SCHEMA: '{}'}),
    'bad-schema-first': ('bad-schema', FIRST_PAIR),
    'garbled-schema': ('seed', {SCHEMA: 'not json'}),
    'garbled-schema-first': ('garbled-schema', FIRST_PAIR),
}


def write_files(repo, files):
    for path, value in files.items():
        target = repo / path
        if value is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8')


@pytest.fixture(scope='module')
def repo(tmp_path_factory):
    repo = tmp_path_factory.mktemp('data-pr') / 'clone with spaces'
    repo.mkdir()
    git(repo, 'init', '-b', 'seed')
    (repo / 'catalog/relief').mkdir(parents=True)
    shutil.copyfile(ROOT / 'catalog/relief/pointer.schema.json', repo / 'catalog/relief/pointer.schema.json')
    write_files(repo, {'catalog/relief/README.md': 'Relief pointers',
                       'dist/regions/index.json': {'regions': [{'id': 'fixture-bay'}, {'id': 'other-bay'}]}})
    git(repo, 'add', '--all')
    git(repo, 'commit', '-m', 'Seed')
    for name, (start, files) in BRANCHES.items():
        git(repo, 'switch', '--quiet', '--create', name, start)
        write_files(repo, files)
        git(repo, 'add', '--all')
        git(repo, 'commit', '-m', name)
    git(repo, 'switch', '--quiet', 'seed')
    # The tool reads Git objects only; these working-tree files must never be read.
    write_files(repo, {POINTER: '[]', CONTOURS: '[]', 'dist/regions/index.json': '[]'})
    return repo


def check(repo, base, head, capsys, *extra):
    code = data_pr_check.main(['--repo', str(repo), '--base', base, '--head', head, *extra])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.mark.parametrize(('base', 'head', 'paths'), [
    pytest.param('seed', 'extra-file', ['notes.txt'], id='C1: extra file'),
    pytest.param('seed', 'extra-readme', ['catalog/relief/README.md'], id='C1: catalog file that is not a pair'),
    pytest.param('seed', 'extra-schema', ['catalog/relief/pointer.schema.json'],
                 id='C1: pointer schema is not a region pointer'),
    pytest.param('seed', 'bad-region-id', ['catalog/relief/Fixture_Bay.json'], id='C1: invalid region id'),
    pytest.param('seed', 'wrong-extension', ['catalog/depth-contours/fixture-bay.json'],
                 id='C1: contours with the wrong extension'),
    pytest.param('seed', 'two-regions', [OTHER_CONTOURS, OTHER_POINTER], id='C1: two regions'),
    pytest.param('first', 'pointer-only', [POINTER], id='C1: pointer without contours'),
    pytest.param('first', 'pointer-deleted', [POINTER], id='C1: pair deleted'),
    pytest.param('first', 'pointer-deleted-contours-changed', [POINTER], id='C1: pointer deleted'),
    pytest.param('first', 'first', ['(empty diff)'], id='C1: empty diff'),
])
def test_c1_scope_failures(repo, capsys, base, head, paths):
    """C1: any path beyond one region's pair (or its contours alone) fails before the head checks."""
    # Believable bug: matching catalog/ by prefix, or picking one region and ignoring the rest.
    expected = ''.join(f'FAIL scope {path}\n' for path in paths) + 'data-pr: FAIL\n'
    assert check(repo, base, head, capsys) == (1, expected, '')


@pytest.mark.parametrize(('base', 'head', 'failures'), [
    pytest.param('first', 'wrong-lineage', ['lineage MISMATCH previous.generation'], id='C2: wrong lineage'),
    pytest.param('seed', 'second', ['lineage MISMATCH previous'], id='C2: predecessor claimed on a first release'),
    pytest.param('seed', 'contours-wrong-region',
                 ['catalog contours: contours provenance.region_id does not match pointer region'],
                 id='C2: contours with mismatched region'),
    pytest.param('seed', 'contours-without-pointer', [f'pointer missing {POINTER}'],
                 id='C2: contours alone without a pointer'),
    pytest.param('seed', 'invalid-pointer', [f'pointer head: {BAD_MINZOOM}', f'catalog schema: {BAD_MINZOOM}'],
                 id='C2: invalid head pointer'),
    pytest.param('invalid-pointer', 'over-invalid-base', [f'lineage base: {BAD_MINZOOM}'],
                 id='C2: invalid base pointer'),
    pytest.param('foreign-base', 'over-foreign-base',
                 ["lineage region mismatch: base 'other-bay', head 'fixture-bay'"], id='C2: base pointer region'),
    pytest.param('no-schema', 'no-schema-first', [f'catalog missing {SCHEMA}'],
                 id='C2: head catalog without the pointer schema'),
    pytest.param('bad-schema', 'bad-schema-first',
                 ["catalog cannot check head catalog: KeyError: '$defs'"], id='C2: head schema without definitions'),
    pytest.param('garbled-schema', 'garbled-schema-first',
                 ['catalog cannot check head catalog: JSONDecodeError: Expecting value: line 1 column 1 (char 0)'],
                 id='C2: head schema that is not JSON'),
])
def test_c2_head_failures(repo, capsys, base, head, failures):
    """C2: the head pointer, its lineage and the catalog pair each fail with their own line."""
    # Believable bug: skipping lineage for a release, or reading the pair check from the wrong tree;
    # or a head catalog with a missing/malformed pointer schema crashing with a traceback, not a FAIL.
    expected = ''.join(f'FAIL {failure}\n' for failure in failures) + 'data-pr: FAIL\n'
    assert check(repo, base, head, capsys) == (1, expected, '')


@pytest.mark.parametrize(('base', 'head', 'verdict'), [
    pytest.param('seed', 'first', 'fixture-bay aaaaaaaaaaaa', id='C3: clean first release'),
    pytest.param('first', 'second', 'fixture-bay 999999999999', id='C3: clean second release'),
    pytest.param('first', 'contours-over-first', 'fixture-bay aaaaaaaaaaaa',
                 id='C3: contours alone over a first release'),
    pytest.param('second', 'contours-over-second', 'fixture-bay 999999999999',
                 id='C3: contours alone over a later release'),
])
def test_c3_pass(repo, capsys, base, head, verdict):
    """C3: a clean branch prints one verdict naming the region and its pointer generation."""
    # Believable bug: demanding adjacent lineage from an unchanged pointer (contours alone).
    assert check(repo, base, head, capsys) == (0, f'data-pr: PASS {verdict}\n', '')


def rev(repo, ref):
    return subprocess.run(['git', 'rev-parse', ref], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


def test_c3_json_reports(repo, capsys):
    """C3: --json carries the same verdict, exit status and failures as the text report."""
    code, out, err = check(repo, 'first', 'second', capsys, '--json')
    assert (code, json.loads(out), err) == (0, {
        'base': rev(repo, 'first'), 'head': rev(repo, 'second'), 'region': 'fixture-bay',
        'generation': '9' * 64, 'lineage': 'ok', 'verdict': 'PASS', 'failures': [],
        'changed': [{'status': 'M', 'path': CONTOURS}, {'status': 'M', 'path': POINTER}],
    }, '')
    code, out, err = check(repo, 'first', 'contours-over-first', capsys, '--json')
    assert (code, json.loads(out)['lineage'], err) == (0, 'unchanged', '')
    code, out, err = check(repo, 'seed', 'two-regions', capsys, '--json')
    assert (code, json.loads(out), err) == (1, {
        'base': rev(repo, 'seed'), 'head': rev(repo, 'two-regions'), 'region': 'fixture-bay',
        'generation': None, 'lineage': None, 'verdict': 'FAIL',
        'failures': [{'check': 'scope', 'reason': OTHER_CONTOURS}, {'check': 'scope', 'reason': OTHER_POINTER}],
        'changed': [{'status': 'A', 'path': path} for path in (CONTOURS, OTHER_CONTOURS, POINTER, OTHER_POINTER)],
    }, '')


def test_c3_read_only(repo, monkeypatch, capsys):
    """C3: only local Git reads with argv lists; nothing in the clone changes."""
    # Believable bug: a checkout or shell string to read the head tree.
    run = subprocess.run
    commands = []

    def local_git(argv, **kwargs):
        assert isinstance(argv, list) and argv[0] == 'git' and not kwargs.get('shell')
        assert kwargs['env']['GIT_NO_LAZY_FETCH'] == '1' and kwargs['env']['GIT_ALLOW_PROTOCOL'] == ''
        commands.append(next(arg for arg in argv[1:] if not arg.startswith('-')))
        return run(argv, **kwargs)

    def snapshot():
        return {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in repo.rglob('*') if path.is_file()}

    before = snapshot()
    monkeypatch.setattr(subprocess, 'run', local_git)
    assert check(repo, 'first', 'second', capsys) == (0, 'data-pr: PASS fixture-bay 999999999999\n', '')
    assert set(commands) == {'rev-parse', 'diff', 'ls-tree', 'cat-file', 'show'}
    assert snapshot() == before


@pytest.mark.parametrize(('args', 'error'), [
    pytest.param(['--base', 'seed', '--head', 'first'], 'the following arguments are required: --repo',
                 id='C3: repo required'),
    pytest.param(['--repo', '.', '--head', 'first'], 'the following arguments are required: --base',
                 id='C3: base required'),
    pytest.param(['--repo', '.', '--base', 'seed', '--head', ''],
                 '--head must name a Git revision, not an index or tree path', id='C3: empty ref'),
    pytest.param(['--repo', '.', '--base', 'seed:catalog', '--head', 'first'],
                 '--base must name a Git revision, not an index or tree path', id='C3: tree path is not a ref'),
    pytest.param(['--repo', 'no such dir', '--base', 'seed', '--head', 'first'],
                 '--repo is not a directory: no such dir', id='C3: missing repo'),
])
def test_c3_usage(args, error, capsys):
    """C3: usage errors exit 2 before any Git read."""
    with pytest.raises(SystemExit) as exc:
        data_pr_check.main(args)
    assert type(exc.value) is SystemExit and exc.value.code == 2
    out, err = capsys.readouterr()
    assert out == '' and err.splitlines()[-1].endswith(f': error: {error}')


def test_c3_unknown_ref(repo, tmp_path, capsys):
    """C3: an unknown ref, or a directory that is not a clone, exits 2 without a verdict."""
    assert check(repo, 'seed', 'no-such-branch', capsys) == (2, '', 'error: unknown ref no-such-branch\n')
    assert check(tmp_path, 'seed', 'first', capsys) == (2, '', 'error: unknown ref seed\n')


def test_c3_direct_entrypoint(repo):
    """C3: the script runs as a file from outside the checkout and imports this checkout's code."""
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/relief/data_pr_check.py'),
         '--repo', str(repo), '--base', 'seed', '--head', 'first'],
        cwd=repo.parent, capture_output=True, text=True,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, 'data-pr: PASS fixture-bay aaaaaaaaaaaa\n', '')
