"""scripts/relief/run_region.py: the guarded per-region stage runner (DATA-LIVE-6).

The runner is the only thing between a held-data build and the shared box, so each test pins one
contract a careless edit could break. region.py is replaced by a stub that logs its argv and
exits with a scripted code; no test starts a real stage.
"""
import ast
import importlib.util
import json
import os
import re
import sys

import pytest

from tests._support import ROOT


def _load():
    spec = importlib.util.spec_from_file_location('relief_run_region_cli', ROOT / 'scripts' / 'relief' / 'run_region.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RR = _load()
STAGE_ORDER = ['normalize', 'select', 'mosaic', 'tiles', 'contours', 'zone', 'digests', 'package', 'qa', 'envelope']
ZONE_ARGS = ['--coarse', '/in/coarse.tif', '--water', '/in/water.geojson', '--coarse-source', 'src-1']
SOURCE_ARGS = ['--source', '/in/dem']
PACKAGE_ARGS = ['--manifest', '/in/layers.json', '--upstream', 'tiles:public', '--upstream', 'zone:public']
GEN = 'a' * 64
SHA = 'c' * 64
QA_ARGS = ['--qa-elevation', '/in/elev.tif', '--qa-contributor', '/in/contrib.tif', '--qa-shots', '/in/shots.json']
QA_SEAM = ['--generation', GEN, '--release-sha256', SHA, '--elevation', '/in/elev.tif', '--contributor', '/in/contrib.tif',
           '--shots', '/in/shots.json', '--upstream', 'tiles:public', '--upstream', 'zone:public']
NORM_ARGS = ['--cache', RR.DEFAULT_NORM]  # normalize always gets the effective cache; the fixture clears $SC_RELIEF_NORM
SEAM = {'normalize': [*SOURCE_ARGS, *NORM_ARGS], 'mosaic': ['--scope', 'public'], 'tiles': ['--scope', 'public'],
        'zone': ['--scope', 'public', *ZONE_ARGS], 'package': PACKAGE_ARGS, 'qa': QA_SEAM, 'envelope': ['--generation', GEN]}
STUB = '''\
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
stage = sys.argv[1]
with open(os.path.join(here, 'calls.jsonl'), 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
plan = json.load(open(os.path.join(here, 'codes.json')))
trip = plan.get('trip_after')
if trip == stage:  # a guard condition appearing while the stage runs
    open(plan['trip_file'], 'w').close()
sys.exit(plan.get('codes', {}).get(stage, 0))
'''


class Box:
    """A temporary host: OUT, a fake region.py, stop files and a scripted /proc."""

    def __init__(self, root):
        self.root = root
        self.out = root / 'out'
        self.out.mkdir()
        self.stub_dir = root / 'stub'
        self.stub_dir.mkdir()
        (self.stub_dir / 'region.py').write_text(STUB)
        self.codes({})
        self.local_stop = root / 'LOCAL-STOP'
        self.unitfeed_stop = root / 'UNITFEED-STOP'
        self.proc = root / 'proc'
        self.proc.mkdir()
        self.pressure_cpu = self.proc / 'pressure' / 'cpu'
        self.pressure_cpu.parent.mkdir()
        self.pressure_cpu.write_text('some avg10=1.00 avg60=1.00 avg300=1.00 total=1000\n')
        self.slots = root / 'slots'
        self.free = {'/': 900 * RR.GB, '/mnt/agentorange-backup': 900 * RR.GB}
        self.cfg = RR.Config(region_py=self.stub_dir / 'region.py', stop_files=(self.local_stop, self.unitfeed_stop),
                             proc_root=str(self.proc), prefix=(), pid=424242, slot_dir=self.slots,
                             free_bytes=lambda path: self.free[path],
                             is_mount=lambda path: True)

    def codes(self, codes, **extra):
        (self.stub_dir / 'codes.json').write_text(json.dumps({'codes': codes, **extra}))

    def calls(self):
        log = self.stub_dir / 'calls.jsonl'
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def ran(self):
        return [call[0] for call in self.calls()]

    def fake_process(self, pid, *argv):
        directory = self.proc / str(pid)
        directory.mkdir()
        (directory / 'cmdline').write_bytes(b'\0'.join(a.encode() for a in argv) + b'\0')

    def run(self, *args, region='morro-bay', through='envelope', generation=True, release=True):
        """Run the chain with every input the stages up to ``through`` require (the generation and qa's
        release hash too, unless ``generation``/``release`` is false: then they are read from the package receipt)."""
        reaches = lambda stage: STAGE_ORDER.index(through) >= STAGE_ORDER.index(stage)
        extra = [*SOURCE_ARGS, *(ZONE_ARGS if reaches('zone') else []), *(PACKAGE_ARGS if reaches('package') else []),
                 *(QA_ARGS if reaches('qa') else []), *(['--release-sha256', SHA] if release and reaches('qa') else []),
                 *(['--generation', GEN] if generation and reaches('envelope') else [])]
        return RR.main([region, '--out', str(self.out), '--through', through, *extra, *args], self.cfg)

    def package_receipt(self, generation, release_sha=None):
        path = self.out / 'morro-bay' / 'stages' / 'package.json'
        path.parent.mkdir(parents=True)
        outputs = [{'path': f'release/{generation}/release.json', 'sha256': release_sha}] if release_sha else []
        path.write_text(json.dumps({'generation': generation, 'outputs': outputs}))

    def out_tree(self):
        return sorted(str(p.relative_to(self.out)) for p in self.out.rglob('*'))


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.delenv('SC_RELIEF_NORM', raising=False)
    monkeypatch.delenv('SC_RELIEF_OUT', raising=False)
    return Box(tmp_path)


def test_chain_order_and_stage_arguments(box, capsys):
    # Contract: the ten stages run in the fixed upstream-first order, each as `region.py <stage>
    # --region <id> --out <OUT>` plus that stage's own required inputs (SEAM). Bug caught: a
    # reordered tuple or a dropped/renamed stage.
    assert box.run() == 0
    assert box.calls() == [[stage, '--region', 'morro-bay', '--out', str(box.out), *SEAM.get(stage, [])]
                           for stage in STAGE_ORDER]
    assert 'complete through envelope' in capsys.readouterr().out


def test_through_stops_after_that_stage(box):
    # Contract: --through is inclusive and nothing after it runs. Bug caught: an off-by-one slice.
    assert box.run(through='mosaic') == 0
    assert box.ran() == ['normalize', 'select', 'mosaic']


def test_scoped_stages_get_scope_config_and_zone_inputs_only(box):
    # Contract (DL-5 seam): mosaic/tiles/zone get --scope (default public) and --region-config; only
    # zone gets --coarse/--water/--coarse-source/--coarse-date; no other stage gets any of them.
    # Bug caught: the scoped stages exiting 2 for a missing --scope, or zone flags leaking to others.
    assert box.run('--region-config', '/r/region.json', '--coarse-date', '2026-01-01', '--scope', 'private') == 0
    for call in box.calls():
        stage, tail = call[0], call[5:]
        if stage in ('mosaic', 'tiles'):
            assert tail == ['--scope', 'private', '--region-config', '/r/region.json']
        elif stage == 'zone':
            assert tail == ['--scope', 'private', '--region-config', '/r/region.json', *ZONE_ARGS,
                            '--coarse-date', '2026-01-01']
        else:
            assert tail == {'normalize': [*SOURCE_ARGS, *NORM_ARGS], 'package': PACKAGE_ARGS, 'qa': QA_SEAM,
                            'envelope': ['--generation', GEN]}.get(stage, [])


@pytest.mark.parametrize('drop, through', [
    ('--coarse', 'zone'), ('--water', 'zone'), ('--coarse-source', 'zone'),
    ('--source', 'normalize'), ('--source', 'tiles'),
    ('--manifest', 'package'), ('--upstream', 'package'),
    ('--qa-elevation', 'qa'), ('--qa-contributor', 'qa'), ('--qa-shots', 'qa'),
])
def test_chain_reaching_a_stage_without_its_inputs_is_a_usage_error_before_any_stage(box, drop, through):
    # Contract: every stage's mandatory inputs are checked up front. Bugs caught: the first review
    # return (normalize started without --source, so even `--through normalize` exited 2), and
    # running normalize..tiles for hours before zone/package/qa fails on a missing flag. A chain that
    # stops before the stage needs none of its inputs.
    args = []
    flags = [*SOURCE_ARGS, *ZONE_ARGS, *PACKAGE_ARGS, *QA_ARGS]
    for flag, value in zip(flags[::2], flags[1::2]):  # every option here takes one value
        if flag != drop:  # --upstream is repeatable: this drops all of its uses
            args += [flag, value]
    with pytest.raises(SystemExit) as stop:
        RR.main(['morro-bay', '--out', str(box.out), '--through', through, *args], box.cfg)
    assert stop.value.code == 2 and box.ran() == [] and box.out_tree() == []


def test_chains_that_stop_before_a_stage_do_not_need_its_inputs(box):
    assert RR.main(['morro-bay', '--out', str(box.out), '--through', 'tiles', *SOURCE_ARGS], box.cfg) == 0
    assert box.ran() == ['normalize', 'select', 'mosaic', 'tiles']


def test_normalize_gets_source_family_and_the_cache_the_guard_checks(box):
    # Contract: normalize's own CLI (--source required, --family, --cache) is fed from the runner's
    # options, and --norm is forwarded as --cache so the vault guard watches the path normalize
    # really writes. Bug caught: --norm guarded but a different default cache used.
    assert box.run('--family', 'nbs_bluetopo', '--norm', '/n/cache', through='normalize') == 0
    assert box.calls() == [['normalize', '--region', 'morro-bay', '--out', str(box.out), '--source', '/in/dem',
                            '--family', 'nbs_bluetopo', '--cache', '/n/cache']]


def _vault_box(box, monkeypatch):
    """A box whose forbidden root is ``vault``, with the working directory inside it (the case
    where an empty $SC_RELIEF_NORM resolves to the vault itself)."""
    vault = box.root / 'vault'
    vault.mkdir()
    box.cfg.forbidden_root = str(vault)
    monkeypatch.chdir(vault)
    return vault


def _refused_norm_run(box, capsys, *args):
    assert box.run(*args, through='normalize') == 3
    assert box.ran() == [] and 'norm-root' in capsys.readouterr().out


def test_empty_norm_env_resolves_to_the_working_directory_and_is_guarded(box, monkeypatch, capsys):
    # Contract: the cache the guard checks is the one normalize really writes. normalize reads
    # $SC_RELIEF_NORM with os.environ.get(name, default), so an empty value is kept and Path('')
    # is the working directory. Bug caught (second review return): the runner turned the empty
    # value into "no cache", guarded nothing, and normalize then wrote into a vault cwd.
    vault = _vault_box(box, monkeypatch)
    monkeypatch.setenv('SC_RELIEF_NORM', '')
    _, args = RR.parse(['morro-bay', '--out', str(box.out), '--through', 'normalize', *SOURCE_ARGS])
    assert args.norm == vault.resolve() and RR.stage_extras(args)['normalize'][-2:] == ['--cache', str(vault.resolve())]
    _refused_norm_run(box, capsys)


def test_default_cache_under_the_forbidden_root_is_refused(box, monkeypatch, capsys):
    # Contract: with --norm and $SC_RELIEF_NORM both absent, normalize's built-in default cache is
    # guarded like any other. Bug caught: the default was never checked, as no --cache was passed.
    box.cfg.forbidden_root = str(RR.DEFAULT_NORM)
    _refused_norm_run(box, capsys)


def test_environment_cache_under_the_forbidden_root_is_refused(box, monkeypatch, capsys):
    vault = _vault_box(box, monkeypatch)
    monkeypatch.setenv('SC_RELIEF_NORM', str(vault / 'cache'))
    _refused_norm_run(box, capsys)


def test_the_cache_normalize_receives_is_the_one_the_guard_checked(box, monkeypatch):
    # Contract: an option beats the environment, the environment beats the default, and the same
    # absolute path is both guarded and forwarded.
    monkeypatch.setenv('SC_RELIEF_NORM', '/env/cache')
    assert box.run(through='normalize') == 0
    assert box.calls()[-1][-2:] == ['--cache', '/env/cache']
    assert box.run('--norm', '/opt/cache', through='normalize') == 0
    assert box.calls()[-1][-2:] == ['--cache', '/opt/cache']


def test_default_cache_matches_the_one_normalize_declares():
    # Contract: DEFAULT_NORM is normalize's own --cache default, read from its source (the module
    # needs numpy, so it cannot be imported here). Bug caught: the two defaults drifting apart.
    source = (ROOT / 'src' / 'skippercast' / 'relief' / 'normalize.py').read_text(encoding='utf-8')
    cache = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument'
                 and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == '--cache')
    default = next(k.value for k in cache.keywords if k.arg == 'default')
    assert ast.literal_eval(default.args[1]) == RR.DEFAULT_NORM


def test_source_path_under_the_vault_is_refused(box, capsys):
    # Contract: the private-vault guard also covers --source/--manifest. Bug caught: a public run
    # normalizing straight off the vault.
    box.cfg.forbidden_root = str(box.root / 'vault')
    assert RR.main(['morro-bay', '--out', str(box.out), '--through', 'normalize',
                    '--source', str(box.root / 'vault' / 'dem')], box.cfg) == 3
    assert box.ran() == [] and 'input-path' in capsys.readouterr().out


def test_qa_generation_and_release_hash_are_read_from_the_package_receipt(box):
    # Contract: qa's required --generation and --release-sha256 are the package receipt's generation and
    # the hash it records for release/<generation>/release.json unless given. Bug caught: qa started
    # without them (it exits 2: the red main this replaced) or with a hash of some other file.
    box.package_receipt('b' * 64, release_sha='d' * 64)
    assert box.run(generation=False, release=False, through='qa') == 0
    assert box.calls()[-1][5:9] == ['--generation', 'b' * 64, '--release-sha256', 'd' * 64]


@pytest.mark.parametrize('receipt, release_sha', [(None, None), ('not-a-generation', None), ('b' * 64, None)],
                         ids=['no-receipt', 'malformed-generation', 'no-release-hash'])
def test_qa_without_a_usable_generation_or_release_hash_stops_before_it_runs(box, capsys, receipt, release_sha):
    # Contract: no generation or release hash (no receipt, a malformed generation, a receipt that does not
    # list release.json) stops the run before qa starts. Bug caught: qa started with a guessed value.
    if receipt:
        box.package_receipt(receipt, release_sha)
    assert box.run(generation=False, release=False) == 2
    assert box.ran() == STAGE_ORDER[:-2]
    assert 'STOPPED before qa' in capsys.readouterr().out


def test_envelope_generation_is_read_from_the_package_receipt(box):
    # Contract: envelope's required --generation is the package receipt's generation unless given.
    # Bug caught: a full chain that can never reach envelope because the value is only known after
    # package ran.
    box.package_receipt('b' * 64)
    assert box.run(generation=False) == 0
    assert box.calls()[-1] == ['envelope', '--region', 'morro-bay', '--out', str(box.out), '--generation', 'b' * 64]


def _declared(path):
    """``{flag: required}`` for every ``--flag`` a module adds to an argparse parser: literal ones, and those a
    ``for name in ('a', 'b'):`` loop adds as ``f'--{name}'``."""
    flags = {}

    def add(call, value):
        required = any(k.arg == 'required' and isinstance(k.value, ast.Constant) and k.value.value is True
                       for k in call.keywords)
        flags[value] = flags.get(value, False) or required

    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument'
                and node.args and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).startswith('--')):
            add(node, node.args[0].value)
        elif isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple) and isinstance(node.target, ast.Name):
            names = [e.value for e in node.iter.elts if isinstance(e, ast.Constant)]
            for call in ast.walk(node):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == 'add_argument'
                        and call.args and ast.unparse(call.args[0]) == f"f'--{{{node.target.id}}}'"):
                    for name in names:
                        add(call, f'--{name}')
    return flags


def test_runner_arguments_match_what_the_real_stage_parsers_declare(box):
    # Contract: the arguments the runner builds for each stage are the ones that stage's real
    # module declares: everything it requires is supplied and nothing it does not know is passed
    # (region.py exits 2 on either). Read from the sources, because the stages import numpy and
    # rasterio and so cannot be dispatched here. Bug caught: the first review return, a runner
    # starting normalize without its required --source.
    relief = ROOT / 'src' / 'skippercast' / 'relief'
    shared = {'digests': ['package.py'], 'package': ['package.py'], 'envelope': ['package.py'], 'tiles': ['mosaic.py'],
              'zone': ['mosaic.py'], 'qa': ['package.py']}
    _, args = RR.parse(['morro-bay', '--out', str(box.out), '--through', 'envelope', *SOURCE_ARGS, '--family', 'dem',
                        '--norm', '/n', *ZONE_ARGS, '--region-config', '/r.json', *PACKAGE_ARGS, *QA_ARGS,
                        '--generation', GEN, '--release-sha256', SHA])
    extra = RR.stage_extras(args)
    extra['qa'] = [*RR.qa_release(box.out, 'morro-bay', extra), *extra['qa']]  # added when qa starts, as run_locked does
    checked = []
    for stage in RR.STAGES:
        module = relief / f'{stage}.py'
        if not module.exists():  # select, contours: not on this checkout; region.py reports them as exit 2
            continue
        checked.append(stage)
        known = {}
        for path in (module, *(relief / name for name in shared.get(stage, ())), ROOT / 'scripts' / 'relief' / 'region.py'):
            known.update(_declared(path))
        given = {token for token in RR.stage_command(box.cfg, stage, 'morro-bay', box.out, extra) if token.startswith('--')}
        required = {flag for flag, needed in _declared(module).items() if needed}
        assert required <= given, f'{stage} requires {sorted(required - given)}'
        assert given <= set(known), f'{stage} is given {sorted(given - set(known))} which it does not declare'
    assert {'normalize', 'mosaic', 'tiles', 'zone', 'digests', 'package', 'qa', 'envelope'} <= set(checked)


def test_runs_under_nice_and_ionice_idle(box):
    # Contract: every stage command is prefixed `nice -n 19 ionice -c3` by default. Bug caught: a
    # default config that drops the load protection (tests blank the prefix to run a stub).
    command = RR.stage_command(RR.Config(python='py', region_py='region.py'), 'tiles', 'morro-bay', '/o')
    assert command == ['nice', '-n', '19', 'ionice', '-c3', 'py', 'region.py', 'tiles', '--region', 'morro-bay', '--out', '/o']


def test_stops_at_first_failure_and_reports_stage_and_code(box, capsys):
    # Contract: the first non-zero stage ends the run, is named with its code, and its code is the
    # exit status. Bug caught: continuing past a failed stage, or returning 0.
    box.codes({'mosaic': 4})
    assert box.run() == 4
    assert box.ran() == ['normalize', 'select', 'mosaic']
    assert 'STOPPED at mosaic: exit 4' in capsys.readouterr().out


def test_unknown_stage_is_not_available_and_stops(box, capsys):
    # Contract: region.py exit 2 (no module on main yet) is "not available", exit 2, run stops there.
    # Bug caught: treating a missing stage module as success and building on nothing.
    box.codes({'tiles': 2})
    assert box.run() == 2
    assert box.ran() == ['normalize', 'select', 'mosaic', 'tiles']
    assert 'STOPPED at tiles: not available' in capsys.readouterr().out


@pytest.mark.parametrize('bad', [['--through', 'publish'], ['--through', 'ENVELOPE']])
def test_unknown_through_stage_is_a_usage_error(box, bad):
    # Contract: only the ten known stages are accepted for --through (no upload/publish stage can be named).
    with pytest.raises(SystemExit) as stop:
        RR.main(['morro-bay', '--out', str(box.out), *bad], box.cfg)
    assert stop.value.code == 2 and box.ran() == []


@pytest.mark.parametrize('region', ['../escape', 'Morro', 'a/b', '', '-x'])
def test_bad_region_id_is_refused_before_any_path_is_built(box, region):
    # Contract: the region id is a receipts.REGION_ID token. Bug caught: `../x` making the lock
    # file land outside OUT.
    with pytest.raises(SystemExit) as stop:
        box.run(region=region)
    assert stop.value.code == 2 and box.ran() == [] and box.out_tree() == []


def test_out_must_exist(box, tmp_path):
    # Contract: the runner never creates OUT itself (it writes only inside it).
    with pytest.raises(SystemExit):
        RR.main(['morro-bay', '--out', str(tmp_path / 'nope'), '--through', 'select'], box.cfg)
    assert not (tmp_path / 'nope').exists()


def refuse_stop_file(box):
    box.local_stop.write_text('x')


def refuse_unitfeed_stop(box):
    box.unitfeed_stop.write_text('x')


def refuse_stop_unreadable(box):
    # A non-directory parent makes the stop path uncheckable (ENOTDIR), not absent.
    parent = box.root / 'broken-modes'
    parent.touch()
    box.cfg.stop_files = (parent / 'UNITFEED-STOP',)


def refuse_pressure(box):
    # The exact boundary refuses even if avg10, avg300 and the full row are all low.
    box.pressure_cpu.write_text('some avg10=0.00 avg60=25.00 avg300=0.00 total=1000\n'
                                'full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n')


def refuse_pressure_unreadable(box):
    box.pressure_cpu.unlink()
    box.pressure_cpu.mkdir()  # open for reading fails regardless of the test user's privileges


def refuse_pressure_unavailable(box):
    box.pressure_cpu.write_text('full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n')


def refuse_root_disk(box):
    box.free['/'] = 249_000_000_000  # decimal bytes; no dependency on the implementation's units


def refuse_backup_disk(box):
    box.free['/mnt/agentorange-backup'] = 399 * RR.GB


def refuse_backup_unreadable(box):
    def gone(path):
        if path != '/mnt/agentorange-backup':
            return box.free[path]
        raise FileNotFoundError(path)  # an unmounted backup drive must refuse, not pass
    box.cfg.free_bytes = gone


def refuse_backup_unmounted(box):
    # The mountpoint directory exists on the parent filesystem, which has plenty of free space.
    plain_dir = box.root / 'backup-mountpoint'
    plain_dir.mkdir()
    box.cfg.backup_path = str(plain_dir)
    box.cfg.is_mount = os.path.ismount  # the real default check
    box.free[str(plain_dir)] = 900 * RR.GB


def refuse_vault_out(box):
    box.cfg.forbidden_root = str(box.out)  # the OUT root itself is "under privatevault"


def refuse_vault_norm(box):
    box.cfg.forbidden_root = str(box.root / 'vault')
    (box.root / 'vault').mkdir()
    (box.root / 'vault' / 'norm').mkdir()
    box.norm = box.root / 'vault' / 'norm'


def refuse_vault_norm_symlink(box):
    box.cfg.forbidden_root = str(box.root / 'vault')
    (box.root / 'vault').mkdir()
    (box.root / 'link').symlink_to(box.root / 'vault')
    box.norm = box.root / 'link'


GUARDS = [
    ('LOCAL-STOP', refuse_stop_file, 'stop-file'),
    ('UNITFEED-STOP', refuse_unitfeed_stop, 'stop-file'),
    ('stop-unreadable', refuse_stop_unreadable, 'stop-file'),
    ('cpu-avg60-at-25', refuse_pressure, 'cpu-pressure'),
    ('cpu-unreadable', refuse_pressure_unreadable, 'cpu-pressure'),
    ('cpu-no-some-row', refuse_pressure_unavailable, 'cpu-pressure'),
    ('root-249-decimal-gb', refuse_root_disk, 'disk-root'),
    ('backup-disk', refuse_backup_disk, 'disk-backup'),
    ('backup-unreadable', refuse_backup_unreadable, 'disk-backup'),
    ('backup-unmounted', refuse_backup_unmounted, 'disk-backup'),
    ('vault-out', refuse_vault_out, 'out-root'),
    ('vault-norm', refuse_vault_norm, 'norm-root'),
    ('vault-norm-symlink', refuse_vault_norm_symlink, 'norm-root'),
]


@pytest.mark.parametrize('trip,guard', [(g[1], g[2]) for g in GUARDS], ids=[g[0] for g in GUARDS])
def test_each_guard_refuses_before_the_first_stage(box, capsys, trip, guard):
    # Contract: every guard alone refuses (exit 3) before stage one, names itself, runs nothing and
    # leaves no lock/dir behind. Bug caught: a guard dropped, inverted, or checked only after
    # `normalize` started. Mapgate bugs: using <= 25, the wrong PSI window/row, treating unavailable
    # pressure or an unreadable stop as clear, or admitting 249 decimal GB on root.
    box.norm = None
    trip(box)
    args = ['--norm', str(box.norm)] if box.norm else []
    assert box.run(*args) == 3
    assert box.ran() == []
    assert 'refused before normalize' in capsys.readouterr().out
    assert box.out_tree() == []
    names = [name for name, ok, _ in RR.check_guards(box.cfg, box.out, box.norm) if not ok]
    assert names == [guard]


def test_input_paths_under_the_vault_are_refused(box, capsys):
    # Contract: the private-vault guard also covers the zone/config input paths. Bug caught: a
    # public run reading --coarse straight off the vault.
    box.cfg.forbidden_root = str(box.root / 'vault')
    args = ['--coarse', str(box.root / 'vault' / 'c.tif'), '--water', '/in/w.geojson', '--coarse-source', 's']
    assert RR.main(['morro-bay', '--out', str(box.out), '--through', 'zone', *SOURCE_ARGS, *args], box.cfg) == 3
    assert box.ran() == [] and 'input-path' in capsys.readouterr().out


def test_guards_pass_at_the_boundary_values(box):
    # Contract: some avg60 below 25 and exactly the decimal disk floors are allowed. Bug caught:
    # a different PSI window, rounding to 25 before comparing, or using binary GB / exclusive floors.
    box.pressure_cpu.write_text('some avg10=40.00 avg60=24.99 avg300=50.00 total=1000\n')
    box.free.update({'/': 250_000_000_000, '/mnt/agentorange-backup': 400_000_000_000})
    assert box.run(through='select') == 0


@pytest.mark.parametrize('trip', [refuse_stop_file, refuse_pressure, refuse_root_disk, refuse_backup_disk],
                         ids=['stop-file', 'cpu-pressure', 'root-disk', 'backup-disk'])
def test_guards_are_rechecked_before_every_stage(box, capsys, monkeypatch, trip):
    # Contract: a guard that trips while a stage runs stops the run before the next stage. Bug
    # caught: checking guards once at start (a 10-stage run would then ignore a later LOCAL-STOP).
    calls = {'n': 0}
    real_check = RR.check_guards

    def check(cfg, out, norm, inputs=()):
        calls['n'] += 1
        if calls['n'] == 4:  # checks: start, before normalize, before select, before mosaic
            trip(box)
        return real_check(cfg, out, norm, inputs)

    monkeypatch.setattr(RR, 'check_guards', check)
    assert box.run() == 3
    assert box.ran() == ['normalize', 'select']
    assert 'refused before mosaic' in capsys.readouterr().out


def test_stop_file_created_by_a_stage_stops_the_next_one(box):
    # Same contract with the real race: the stage itself (here the stub) is what creates LOCAL-STOP.
    box.codes({}, trip_after='select', trip_file=str(box.local_stop))
    assert box.run() == 3
    assert box.ran() == ['normalize', 'select']


def test_second_run_of_the_same_region_is_refused_and_lock_is_released(box, capsys):
    # Contract: one run per region (lock in OUT/<id>/), freed when the run ends even by failure.
    # Bug caught: no lock, or a lock left behind that blocks the region forever.
    held = RR.acquire_lock(box.cfg, box.out, 'morro-bay')
    assert held is not None
    try:
        assert box.run() == 5
        assert 'already has a run' in capsys.readouterr().out
        assert box.ran() == []
        assert box.run(region='point-arena', through='select') == 0  # another region is free
    finally:
        os.close(held)
    box.codes({'select': 1})
    assert box.run(through='select') == 1  # failing run still releases the lock
    box.codes({})
    assert box.run(through='select') == 0
    assert (box.out / 'morro-bay' / RR.LOCK_NAME).is_file()


def test_region_directory_symlink_out_of_out_is_refused(box, capsys):
    # Contract: nothing is written outside OUT. Bug caught: OUT/<id> being a symlink so the lock
    # file (and region state) lands elsewhere.
    elsewhere = box.root / 'elsewhere'
    elsewhere.mkdir()
    (box.out / 'morro-bay').symlink_to(elsewhere)
    assert box.run() == 3
    assert list(elsewhere.iterdir()) == [] and box.ran() == []
    assert 'leaves' in capsys.readouterr().out


def test_two_runs_already_on_the_box_refuse_a_third(box, capsys):
    # Contract: at most 2 run_region.py processes at once, this one included; wrappers and our own
    # pid are not counted. Bug caught: counting `timeout ... run_region.py` twice, or not at all.
    box.fake_process(424242, 'python3', 'scripts/relief/run_region.py', 'x')  # ourselves
    box.fake_process(101, 'python3', '/repo/scripts/relief/run_region.py', 'a')
    box.fake_process(102, 'timeout', '9h', 'python3', '/repo/scripts/relief/run_region.py', 'a')  # wrapper
    box.fake_process(103, 'grep', 'run_region.py')
    assert RR.other_runs(box.cfg) == [101]
    assert box.run(through='select') == 0  # one other run: this is the second
    box.fake_process(104, 'python3.14', 'run_region.py', 'b')
    assert box.run(through='select') == 5
    assert 'at most 2 at once' in capsys.readouterr().out
    assert box.ran() == ['normalize', 'select']  # only the earlier allowed run


def test_interpreter_options_do_not_hide_a_run(box, capsys):
    # Contract: `python3 -u run_region.py` (and -X/-W options) counts as a run; `-c`, other scripts and
    # a bare mention of the name as an argument do not. Bug caught: reading only argv[1] as the script,
    # so two unbuffered runs were invisible and a third started.
    box.fake_process(101, 'python3', '-u', '/repo/scripts/relief/run_region.py', 'a')
    box.fake_process(102, 'python3.14', '-X', 'dev', '-W', 'ignore', 'run_region.py', 'b')
    box.fake_process(103, 'python3', '-c', 'x', 'run_region.py')
    box.fake_process(104, 'python3', 'other.py', 'run_region.py')
    box.fake_process(105, 'python3', '-m', 'pytest', 'run_region.py')
    assert RR.other_runs(box.cfg) == [101, 102]
    assert box.run(through='select') == 5 and box.ran() == []
    assert 'at most 2 at once' in capsys.readouterr().out


@pytest.mark.parametrize('proc_change, expected, reason', [
    ('extra-run', 5, 'at most 2 at once'),
    ('unreadable-cmdline', 3, 'cannot establish how many runs'),
])
def test_process_count_is_rechecked_between_stages(box, monkeypatch, capsys, proc_change, expected, reason):
    # Contract: holding a slot does not substitute for checking legacy runners or a broken /proc
    # before the next stage. Bug caught: retaining the process-table check only at startup.
    box.fake_process(101, 'python3', 'run_region.py', 'other')
    run = RR.subprocess.run

    def change_proc_after_stage(*args, **kwargs):
        result = run(*args, **kwargs)
        if proc_change == 'extra-run':
            box.fake_process(102, 'python3', 'run_region.py', 'third')
        else:
            cmdline = box.proc / '101' / 'cmdline'
            cmdline.unlink()
            cmdline.mkdir()
        return result

    monkeypatch.setattr(RR.subprocess, 'run', change_proc_after_stage)
    assert box.run(through='select') == expected
    assert box.ran() == ['normalize']
    text = capsys.readouterr().out
    assert 'refused before select:' in text and reason in text
    assert RR.slots_held(box.cfg) == 0


@pytest.mark.parametrize('unreadable', ['proc-missing', 'cmdline-unreadable'])
def test_unreadable_process_table_refuses_instead_of_counting_zero(box, capsys, unreadable):
    # Contract: when the other-run count cannot be established the run is refused (exit 3), not
    # started. Bug caught: `except OSError: return []`, which let a third run start whenever /proc
    # could not be read.
    if unreadable == 'proc-missing':
        box.cfg.proc_root = str(box.root / 'no-such-proc')
    else:
        (box.proc / '101').mkdir()
        (box.proc / '101' / 'cmdline').mkdir()  # reading it fails with something other than "gone"
    assert box.run(through='select') == 3
    assert box.ran() == [] and 'cannot establish how many runs' in capsys.readouterr().out
    assert box.run('--dry-run') == 0 and 'REFUSE run-cap: cannot establish' in capsys.readouterr().out


def test_run_cap_is_atomic_through_slot_locks(box, capsys):
    # Contract: the box-wide cap is a pair of kernel locks, so it holds with nothing in /proc and
    # when starts are simultaneous (each start takes a distinct slot or is refused). Bug caught: a
    # count-then-start check that lets two racing runs both see one other run and both start.
    first, second = RR.acquire_slot(box.cfg), RR.acquire_slot(box.cfg)
    try:
        assert first is not None and second is not None
        assert RR.acquire_slot(box.cfg) is None  # a third racer gets no slot
        assert RR.slots_held(box.cfg) == 2
        assert box.run(through='select') == 5 and box.ran() == []
        assert 'run slots' in capsys.readouterr().out
        assert box.run('--dry-run') == 0 and 'REFUSE run-cap' in capsys.readouterr().out
    finally:
        os.close(first)
        os.close(second)
    assert box.run(through='select') == 0  # slots are free again (and a finished run frees its own)
    assert box.run(through='select') == 0
    assert RR.slots_held(box.cfg) == 0


@pytest.mark.parametrize('make', ['file', 'symlink'])
def test_unsafe_slot_directory_refuses(box, capsys, make):
    # Contract: a slot directory that is not a real private directory of ours cannot be trusted, so
    # the run is refused (3) rather than started uncapped. Bug caught: ignoring a slot-setup error.
    if make == 'file':
        box.slots.write_text('x')
    else:
        (box.root / 'elsewhere').mkdir()
        box.slots.symlink_to(box.root / 'elsewhere')
    assert box.run(through='select') == 3
    assert box.ran() == [] and 'cannot take a run slot' in capsys.readouterr().out


def test_dry_run_prints_chain_and_guard_state_and_touches_nothing(box, capsys):
    # Contract: --dry-run shows the commands in order and every guard's state, runs nothing and
    # creates no file or directory (not even the lock). Bug caught: dry run that starts stage one.
    assert box.run('--dry-run', through='mosaic') == 0
    text = capsys.readouterr().out
    lines = [line for line in text.splitlines() if re.match(r'\s+\d+\. ', line)]
    assert [line.split()[3] for line in lines] == ['normalize', 'select', 'mosaic']  # '<n>. python region.py <stage>'
    assert '--scope public' in lines[2] and '--scope' not in lines[0]
    assert 'not run: tiles, contours, zone, digests, package, qa, envelope' in text
    for name in ('stop-file', 'cpu-pressure', 'disk-root', 'disk-backup', 'out-root', 'norm-root', 'region-lock', 'run-cap'):
        assert f'ok     {name}' in text
    assert 'a real run would start' in text
    assert box.ran() == [] and box.out_tree() == [] and not box.slots.exists()


@pytest.mark.parametrize('partial', [[], ['--coarse', '/in/coarse.tif']], ids=['bare', 'partial-zone-inputs'])
def test_dry_run_without_through_previews_full_chain_only(box, capsys, partial):
    # Contract: the bare dry run prints all ten stages without launching or writing. Bugs caught:
    # requiring --through/zone inputs for that preview or crashing while formatting partial inputs.
    args = ['morro-bay', '--out', str(box.out), *partial]
    assert RR.main([*args, '--dry-run'], box.cfg) == 0
    text = capsys.readouterr().out
    lines = [line for line in text.splitlines() if re.match(r'\s+\d+\. ', line)]
    assert [line.split()[3] for line in lines] == STAGE_ORDER
    assert 'REFUSE zone inputs' in text and 'REFUSE normalize inputs' in text and 'a real run would be refused' in text
    assert '--generation <generation of the current package receipt>' in text
    with pytest.raises(SystemExit) as stop:
        RR.main(args, box.cfg)
    assert stop.value.code == 2  # real runs still require --through
    assert box.ran() == [] and box.out_tree() == [] and not box.slots.exists()


def test_dry_run_reports_a_refusal_without_running(box, capsys):
    # Contract: the dry run shows which guard would refuse (and a held lock), still exit 0.
    box.local_stop.write_text('x')
    held = RR.acquire_lock(box.cfg, box.out, 'morro-bay')
    try:
        assert box.run('--dry-run') == 0
    finally:
        os.close(held)
    text = capsys.readouterr().out
    assert 'REFUSE stop-file' in text and 'REFUSE region-lock' in text
    assert 'a real run would be refused now' in text and box.ran() == []


def test_script_runs_as_a_command(box):
    # Contract: the file is runnable as `python3 run_region.py` (argparse wiring, __main__ guard).
    import subprocess
    done = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'relief' / 'run_region.py'), 'morro-bay',
                           '--out', str(box.out), '--through', 'bogus'], capture_output=True, text=True)
    assert done.returncode == 2 and 'unknown stage' in done.stderr
