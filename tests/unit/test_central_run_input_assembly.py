import hashlib
import json
import subprocess
import sys

import pytest

from scripts.relief import central_run_input_assembly, run_region
from tests._support import ROOT

REGION = 'cambria-san-simeon'


def pin(path, content):
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / 'norm').mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def bindings(workspace):
    # The spelling with link/.. opens a different file than lexical normalization.
    (workspace / 'tiles' / 'child').mkdir(parents=True)
    (workspace / 'link').symlink_to('tiles/child', target_is_directory=True)
    pin(workspace / 'basemap tiles.pmtiles', b'decoy')
    return {
        'census': ('census.json', pin(workspace / 'census.json', census_bytes(REGION))),
        'basemap': ('link/../basemap tiles.pmtiles', pin(workspace / 'tiles/basemap tiles.pmtiles', b'base')),
    }


def census_bytes(region):
    return json.dumps({'summary': {'region': region}, 'files': []}).encode()


def argv(workspace, bindings, *extra):
    return ['--scratch-root', str(workspace), '--region', REGION, '--norm', 'norm', *extra,
            *(token for role, entry in bindings.items() for token in ('--input', role, *entry))]


@pytest.mark.parametrize(('explicit_zone', 'fresh_out'), [(False, False), (True, False), (False, True)],
                         ids=['receipt-zone', 'explicit-zone', 'fresh-receipt-zone'])
def test_stdout_round_trips_through_runner(workspace, bindings, explicit_zone, fresh_out):
    # Catch emitted schema/role drift, an accidentally normalized file spelling,
    # or placeholder paths/metadata displacing the runner's receipt fallback.
    extra = ['--fresh-out'] if fresh_out else []
    if explicit_zone:
        for role in ('coarse', 'water', 'qa_support'):
            bindings[role] = (role, pin(workspace / role, role.encode()))
        extra += ['--coarse-source', 'fixture-family', '--coarse-date', '2026-01-01']
    command = argv(workspace, bindings, *extra)
    command[-1] = command[-1].upper()  # same reviewed pin, different hex case
    result = subprocess.run(
        [sys.executable, '-B', str(ROOT / 'scripts/relief/central_run_input_assembly.py'), *command],
        cwd=workspace, capture_output=True, check=True,
    )
    assert not result.stderr
    record = workspace / 'assembled.json'
    record.write_bytes(result.stdout)
    parser, options = run_region.parse([REGION, '--out', str(workspace), '--through', 'envelope',
                                        '--inputs', str(record)])
    digest, pins = run_region.load_inputs(options, parser)
    run_region.resolve_options(options, parser, pins)
    assert digest == hashlib.sha256(result.stdout).hexdigest()
    assert pins == {role: reviewed for role, (_, reviewed) in bindings.items()}
    assert options.norm == workspace / 'norm'
    assert options.census_sha256 == bindings['census'][1]
    for role, (spelling, reviewed) in bindings.items():
        assert getattr(options, role) == f'{workspace}/{spelling}'
        assert run_region.input_problem(run_region.Config(basemap_roots=(workspace,)), role,
                                        getattr(options, role), reviewed) is None
    if explicit_zone:
        assert (options.coarse_source, options.coarse_date) == ('fixture-family', '2026-01-01')
    else:
        assert (options.coarse, options.water, options.coarse_source, options.coarse_date) == (None,) * 4


def assert_refused(command, capsys, reason):
    with pytest.raises(SystemExit) as exc:
        central_run_input_assembly.main(command)
    result = capsys.readouterr()
    assert exc.value.code == 2
    assert result.out == ''
    assert reason in result.err


@pytest.mark.parametrize(('path', 'content', 'extra'), [
    ('tiles/basemap tiles.pmtiles', b'basf', ()),
    ('census.json', census_bytes(REGION) + b'\n', ('--fresh-out', '--through', 'select')),
], ids=['envelope-basemap', 'fresh-select-census'])
def test_refuses_changed_input_bytes(workspace, bindings, capsys, path, content, extra):
    # Catch self-pinning, or comparing parsed census content instead of pinned bytes.
    (workspace / path).write_bytes(content)
    assert_refused(argv(workspace, bindings, *extra), capsys, 'expected sha256')


@pytest.mark.parametrize('extra', [(), ('--fresh-out', '--through', 'select')], ids=['envelope', 'fresh-select'])
def test_refuses_other_region_even_with_matching_census_pin(workspace, bindings, capsys, extra):
    # Hash success does not establish that the census belongs to this region.
    bindings['census'] = ('census.json', pin(workspace / 'census.json', census_bytes('big-sur-coast')))
    assert_refused(argv(workspace, bindings, *extra), capsys, 'census region mismatch')


@pytest.mark.parametrize('missing', ['census', 'basemap'])
def test_envelope_rejects_incomplete_inputs_but_earlier_form_accepts(workspace, bindings, capsys, missing):
    # Catch a partial record presented as complete, or early prep requiring an envelope's files.
    del bindings[missing]
    assert_refused(argv(workspace, bindings), capsys, 'envelope requires pinned census and basemap')
    assert_refused(argv(workspace, bindings, '--fresh-out'), capsys, 'envelope requires pinned census and basemap')
    assert central_run_input_assembly.main(argv(workspace, bindings, '--through', 'select')) == 0
    assert set(json.loads(capsys.readouterr().out)['inputs']) == set(bindings)


@pytest.mark.parametrize('through', ['select', 'qa'])
def test_fresh_out_refuses_census_free_handoff(workspace, bindings, capsys, through):
    # An envelope-only gate can emit a plausible record that needs a leftover OUT census.
    del bindings['census']
    assert_refused(argv(workspace, bindings, '--fresh-out', '--through', through), capsys,
                   'fresh OUT requires pinned census')


def test_fresh_select_round_trips_with_only_census(workspace, bindings, capsys):
    # Requiring envelope or producer inputs here would prevent a census-only select handoff.
    census, reviewed = bindings['census']
    command = argv(workspace, {'census': (census, reviewed)}, '--fresh-out', '--through', 'select')
    assert central_run_input_assembly.main(command) == 0
    result = capsys.readouterr()
    assert not result.err
    record = workspace / 'assembled.json'
    record.write_text(result.out, encoding='utf-8')
    out = workspace / 'empty-out'
    out.mkdir()
    parser, options = run_region.parse([REGION, '--out', str(out), '--through', 'select', '--inputs', str(record)])
    _, pins = run_region.load_inputs(options, parser)
    run_region.resolve_options(options, parser, pins)
    assert pins == {'census': reviewed}
    assert options.census == str(workspace / census)
    assert options.census_sha256 == reviewed
    assert (options.basemap, options.coarse, options.water) == (None, None, None)
    assert not list(out.iterdir())


def test_fresh_out_keeps_basemap_conditional_on_shots(workspace, bindings, capsys):
    # Catch a basemap requirement moving earlier or being dropped before envelope.
    del bindings['basemap']
    assert central_run_input_assembly.main(argv(workspace, bindings, '--fresh-out', '--through', 'package')) == 0
    assert set(json.loads(capsys.readouterr().out)['inputs']) == {'census'}
    assert_refused(argv(workspace, bindings, '--fresh-out', '--through', 'shots'), capsys,
                   'runner requires --basemap')


@pytest.mark.parametrize('role', ['coarse', 'water'])
def test_refuses_half_explicit_zone_pair(workspace, bindings, capsys, role):
    # Catch mixing one byte-pinned file with an unrelated receipt-selected partner.
    bindings[role] = (role, pin(workspace / role, b'one half'))
    assert_refused(argv(workspace, bindings, '--coarse-source', 'fixture-family'), capsys,
                   'supply pinned coarse and water together')


def test_refuses_explicit_zone_pair_without_source(workspace, bindings, capsys):
    # Catch packaging a full-envelope record that the runner rejects at zone.
    for role in ('coarse', 'water'):
        bindings[role] = (role, pin(workspace / role, role.encode()))
    assert_refused(argv(workspace, bindings), capsys, 'runner requires --coarse-source')


@pytest.mark.parametrize('flag', ['--region', '--norm'])
def test_requires_explicit_identity_and_cache(workspace, bindings, capsys, flag):
    # Catch inference from the census, CWD, environment or runner defaults.
    command = argv(workspace, bindings)
    index = command.index(flag)
    del command[index:index + 2]
    assert_refused(command, capsys, flag)


@pytest.mark.parametrize(('role', 'pin_value', 'reason'), [
    ('region_config', 'a' * 64, 'unknown input role'),
    ('basemap', 'a' * 64, 'duplicate input role'),
    ('qa_support', 'not-a-digest', '64 hexadecimal digits'),
], ids=['unrecordable-flag', 'ambiguous-duplicate', 'malformed-sha256'])
def test_rejects_unusable_reviewed_bindings(workspace, bindings, capsys, role, pin_value, reason):
    # Catch confusing runner flags with record roles, silently overwriting reviews, or ignoring pin syntax.
    command = argv(workspace, bindings) + ['--input', role, 'census.json', pin_value]
    assert_refused(command, capsys, reason)


@pytest.mark.parametrize('escape', ['file', 'norm'])
def test_refuses_paths_outside_declared_scratch(workspace, bindings, capsys, escape):
    # A symlink can look local while reaching outside the explicitly allowed tree.
    scratch = workspace / 'sandbox'
    scratch.mkdir()
    (scratch / 'census.json').write_bytes(census_bytes(REGION))
    (scratch / 'basemap').write_bytes(b'base')
    (scratch / 'norm').mkdir()
    bindings['census'] = (str(scratch / 'census.json'), bindings['census'][1])
    bindings['basemap'] = (str(scratch / 'basemap'), bindings['basemap'][1])
    command = argv(scratch, bindings)
    if escape == 'file':
        (scratch / 'alias').symlink_to(workspace / 'tiles/basemap tiles.pmtiles')
        command[-2] = str(scratch / 'alias')
    else:
        (scratch / 'alias').symlink_to(workspace / 'norm', target_is_directory=True)
    command[command.index('--norm') + 1] = str(scratch / ('alias' if escape == 'norm' else 'norm'))
    assert_refused(command, capsys, 'path must stay inside --scratch-root')
