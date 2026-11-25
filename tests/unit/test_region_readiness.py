"""Runtime coverage for the read-only release-region report."""
import json
import shutil
import subprocess
import sys

import pytest

from scripts.relief import region_readiness
from tests._support import ROOT


INDEX = 'dist/regions/index.json'
FIRST, SECOND = 'zeta-test', 'alpha-test'
LEGACY = 'deep-fixed-v1'
AREA = [-10, 10, -8, 12]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture
def repo(tmp_path):
    write_json(tmp_path / INDEX, {'regions': [{'id': FIRST}, {'id': SECOND}]})
    write_json(tmp_path / 'style/index.json', {
        'default': LEGACY,
        'versions': {LEGACY: {'legacy': True, 'status': 'active'}, 'old-v1': {'status': 'retired'}},
    })
    (tmp_path / 'schemas').mkdir()
    shutil.copyfile(ROOT / 'schemas/sc-render-v1.schema.json', tmp_path / 'schemas/sc-render-v1.schema.json')
    for region in FIRST, SECOND:
        folder = tmp_path / 'regions' / region
        write_json(folder / 'region.json', dict(
            schema_version=1, id=region, name=region, status='draft', timezone='Etc/UTC',
            bounds=[-11, 9, -7, 13], fishing_bounds=AREA, jurisdiction='Test waters', jurisdiction_id='test',
            boat=dict(name='Fixture', bottom_depth_limit_ft=250, cruise_knots=15),
            harbor=dict(name='Fixture', latitude=11, longitude=-9,
                        information_url='https://example.invalid/harbor', watch_keywords=[]),
            stations=dict(tide='0000001', airport='TEST', nearshore_buoy='00001', offshore_buoy='00002',
                          nearshore_buoy_name='Near', offshore_buoy_name='Far'),
            marine_zones=dict(coastal='ZZZ001', offshore='ZZZ002'),
            forecast_points=[dict(id='sample', name='Fixture', latitude=11, longitude=-9)],
            species=['fixture-fish'], source_bindings={}, pipeline_sources={},
            assets=dict(atlas=None, habitats=None, bottom_index=None, regulations=None),
            landing_names=[], mpa=dict(bounds=AREA, minimum_features=0), map={}, coverage={}, coverage_note='',
        ))
        write_json(folder / 'coast.json', dict(schema_version=1, slug=region, bbox=AREA, depth_target_ft=300,
                                              sources=['first', 'second'],
                                              source_review_status={'first': 'approved', 'second': 'approved'}))
        # The second preview sits on the boundary; all windows must be checked.
        write_json(folder / 'render.json', dict(schema='sc-render/1', region=region, style=LEGACY, piers=[],
                                               previews=[dict(id='inner', center=[-9, 11], size_m=8000, zoom=11),
                                                         dict(id='edge', center=[-8, 12], size_m=8000, zoom=11)]))
    return tmp_path


def expected(region, **changes):
    return dict(region=region, region_json='ok', coast_json='ok', render='ok',
                style='ok', previews='ok', ready='yes', notes=[]) | changes


def assert_json(repo, capsys, code, rows, *args):
    assert region_readiness.main(['--root', str(repo), '--json', *args]) == code
    output = capsys.readouterr()
    assert (json.loads(output.out), output.err) == (rows, '')


@pytest.mark.parametrize('ids,rows', [
    pytest.param([], [expected(FIRST), expected(SECOND)], id='C1: default uses the full index in order'),
    pytest.param([SECOND, FIRST], [expected(SECOND), expected(FIRST)], id='C1: explicit ids use caller order'),
    pytest.param([SECOND], [expected(SECOND)], id='C1: explicit ids select a subset'),
])
def test_c1_ready_rows(repo, capsys, ids, rows):
    # Catch a glob-based or sorted report, including a selection that ignores the CLI ids.
    assert_json(repo, capsys, 0, rows, *ids)


def test_c1_default_table(repo):
    """C1: The actual script emits readable headers and whole rows without --json."""
    proc = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/relief/region_readiness.py'),
                           '--root', str(repo)], capture_output=True, text=True, cwd=repo)
    assert (proc.returncode, proc.stderr, [line.split() for line in proc.stdout.splitlines()]) == (
        0, '', [['region', 'region_json', 'coast_json', 'render', 'style', 'previews', 'ready'],
                [FIRST, 'ok', 'ok', 'ok', 'ok', 'ok', 'yes'],
                [SECOND, 'ok', 'ok', 'ok', 'ok', 'ok', 'yes']])


@pytest.mark.parametrize('file,changes', [
    pytest.param('region.json', dict(region_json='missing'), id='C1: missing region is not ready'),
    pytest.param('coast.json', dict(coast_json='missing'), id='C1: missing coast is not ready'),
    pytest.param('render.json', dict(render='missing', style='missing', previews='missing'),
                 id='C1: missing render cannot be rescued by resolver defaults'),
])
def test_c1_missing_config(repo, capsys, file, changes):
    folder = repo / 'regions' / FIRST
    (folder / file).rename(folder / (file + '.saved'))
    assert_json(repo, capsys, 1, [expected(FIRST, ready='no', **changes), expected(SECOND)])


@pytest.mark.parametrize('file,edit,changes', [
    pytest.param('region.json', {'name': '', 'timezone': ''},
                 dict(region_json='invalid: name: value is too short (minimum length 1)'),
                 id='C1: first schema error only'),
    pytest.param('region.json', {'id': SECOND},
                 dict(region_json=f'invalid: id must equal {FIRST}'),
                 id='C1: region config cannot substitute for another region'),
    pytest.param('render.json', {'region': SECOND},
                 dict(render='invalid: render config belongs to another region', style='invalid: render config required',
                      previews='invalid: render config required'), id='C1: invalid render is not misreported as style'),
    pytest.param('render.json', {'style': 'old-v1'}, dict(style='unavailable style old-v1'),
                 id='C1: retired style is unavailable even though indexed'),
    pytest.param('render.json', {'style': 'unknown-v1'}, dict(style='unavailable style unknown-v1'),
                 id='C1: unknown style is unavailable'),
    pytest.param('coast.json', {'slug': SECOND}, dict(coast_json=f'invalid: slug must equal {FIRST}'),
                 id='C2: coast for another slug is invalid'),
    pytest.param('coast.json', {'depth_target_ft': 299}, dict(coast_json='invalid: depth_target_ft must be at least 300'),
                 id='C2: depth below 300 is invalid'),
    pytest.param('coast.json', {'sources': 'first'}, dict(coast_json='invalid: sources must be a list of source ids'),
                 id='C2: string is not a source list'),
    pytest.param('coast.json', {'source_review_status': []}, dict(coast_json='invalid: source_review_status must be an object'),
                 id='C2: review status must map source ids to statuses'),
    pytest.param('coast.json', {'source_review_status': {'first': 'approved'}},
                 dict(coast_json='invalid: missing source_review_status for second'), id='C2: every source needs a review entry'),
    pytest.param('coast.json', {'source_review_status': {'first': 'approved', 'second': 'pending'}},
                 dict(coast_json='review: second=pending'), id='C2: do not approve a pending source'),
    pytest.param('render.json', {'previews': [{'id': 'incomplete'}]},
                 dict(render="invalid: invalid relief metadata at previews.0: 'center' is a required property",
                      style='invalid: render config required', previews='invalid: render config required'),
                 id='C2: a malformed preview still blocks readiness'),
])
def test_numbered_config_refusals(repo, capsys, file, edit, changes):
    # A single bad input must change only the intended checks and overall readiness.
    path = repo / 'regions' / FIRST / file
    write_json(path, json.loads(path.read_bytes()) | edit)
    assert_json(repo, capsys, 1, [expected(FIRST, ready='no', **changes)], FIRST)


@pytest.mark.parametrize('centers,ids', [
    pytest.param([[-9, 11], [-7.99, 11]], 'edge', id='C2: check every center against fishing_bounds'),
    pytest.param([[-10.01, 11], [-7.99, 11]], 'inner, edge', id='C2: report all outside IDs in order'),
])
def test_c2_outside_centers_are_informational(repo, capsys, centers, ids):
    # All centers stay within broader bounds; neither a skipped note nor a veto is correct.
    path = repo / 'regions' / FIRST / 'render.json'
    doc = json.loads(path.read_bytes())
    for window, center in zip(doc['previews'], centers):
        window['center'] = center
    write_json(path, doc)
    note = f'outside fishing_bounds: {ids}'
    assert_json(repo, capsys, 0, [expected(FIRST, notes=[note])], FIRST)
    assert region_readiness.main(['--root', str(repo), FIRST]) == 0
    output = capsys.readouterr()
    assert (output.out.splitlines()[-1].split(), output.err) == (
        [FIRST, 'ok', 'ok', 'ok', 'ok', 'ok', 'yes', 'notes:', *note.split()], '')


@pytest.mark.parametrize('file,changes', [
    pytest.param('region.json', dict(region_json='invalid: expected a JSON object'),
                 id='C1: region must be an object'),
    pytest.param('coast.json', dict(coast_json='invalid: expected a JSON object'), id='C1: coast must be an object'),
    pytest.param('render.json', dict(render='invalid: expected a JSON object', style='invalid: render config required',
                                   previews='invalid: render config required'), id='C1: render must be an object'),
])
def test_c1_wrong_document_type(repo, capsys, file, changes):
    # A non-object config must produce a scoped reason rather than abort the report.
    write_json(repo / 'regions' / FIRST / file, [])
    assert_json(repo, capsys, 1, [expected(FIRST, ready='no', **changes), expected(SECOND)])


def test_c1_style_bytes_verified(repo, capsys):
    """C1: An active index entry alone does not make a style ready."""
    index = repo / 'style/index.json'
    doc = json.loads(index.read_bytes())
    doc['versions']['corrupt-v1'] = {'status': 'active', 'file': 'corrupt.json', 'sha256': '0' * 64}
    write_json(index, doc)
    (index.parent / 'corrupt.json').write_bytes(b'{}')
    render = repo / 'regions' / FIRST / 'render.json'
    write_json(render, json.loads(render.read_bytes()) | {'style': 'corrupt-v1'})
    error = 'invalid: corrupt-v1: sha256 mismatch (expected ' + '0' * 64 + (
        ', got 44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a)')
    assert_json(repo, capsys, 1, [expected(FIRST, ready='no', style=error)], FIRST)


def test_c3_non_release_read_only(repo, capsys):
    """C3: Do not admit a region merely because its local configs exist or rewrite any inputs."""
    shutil.copytree(repo / 'regions' / FIRST, repo / 'regions/other-test')
    coast = repo / 'regions' / FIRST / 'coast.json'
    write_json(coast, json.loads(coast.read_bytes()) | {'source_review_status': {'first': 'denied', 'second': 'approved'}})

    def snapshot():
        return {p: (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                for p in (repo, *repo.rglob('*'))}

    before = snapshot()
    reason = 'invalid: not a release region'
    refused = expected('other-test', region_json=reason, coast_json=reason, render=reason,
                       style=reason, previews=reason, ready='not a release region')
    assert_json(repo, capsys, 1, [refused, expected(SECOND)], 'other-test', SECOND)
    assert_json(repo, capsys, 1, [expected(FIRST, coast_json='review: first=denied', ready='no')], FIRST)
    assert snapshot() == before


@pytest.mark.parametrize('args,index,reason', [
    pytest.param(['--invalid'], {}, 'unrecognized arguments: --invalid', id='C3: unknown flag is usage'),
    pytest.param([], None, f'{INDEX}: missing', id='C3: missing index is not a vacuous success'),
    pytest.param([], {'regions': []}, f'{INDEX}: invalid: expected a nonempty regions list',
                 id='C3: no release rows is an index error'),
    pytest.param([], {'regions': [{'id': '../elsewhere'}]}, f'{INDEX}: invalid: invalid release region id',
                 id='C3: malformed index id is not a region path'),
    pytest.param([], {'regions': [{'id': FIRST}, {'id': FIRST}]}, f'{INDEX}: invalid: duplicate release region id {FIRST}',
                 id='C3: duplicate index row is not a second release region'),
])
def test_c3_usage(repo, capsys, args, index, reason):
    # Bad invocation/index cannot be reported as a successful empty table or ordinary config gap.
    path = repo / INDEX
    if index is None:
        path.rename(path.with_suffix('.saved'))
    else:
        write_json(path, index)
    with pytest.raises(SystemExit) as exc:
        region_readiness.main(['--root', str(repo), *args])
    output = capsys.readouterr()
    assert (exc.value.code, output.out, output.err.splitlines()[-1].split(': error: ')[-1]) == (2, '', reason)
