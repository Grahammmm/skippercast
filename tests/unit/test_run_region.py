"""scripts/relief/run_region.py: the guarded per-region stage runner (DATA-LIVE-6).

The runner is the only thing between a held-data build and the shared box, so each test pins one
contract a careless edit could break. region.py is replaced by a stub that logs its argv and
exits with a scripted code; no test starts a real stage.
"""
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
SEAM = {'mosaic': ['--scope', 'public'], 'tiles': ['--scope', 'public'], 'zone': ['--scope', 'public', *ZONE_ARGS]}
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
        self.slots = root / 'slots'
        self.free = {'/': 900 * RR.GB, '/mnt/agentorange-backup': 900 * RR.GB}
        self.load = 1.0
        self.cfg = RR.Config(region_py=self.stub_dir / 'region.py', stop_files=(self.local_stop, self.unitfeed_stop),
                             proc_root=str(self.proc), prefix=(), pid=424242, slot_dir=self.slots,
                             load5=lambda: self.load, free_bytes=lambda path: self.free[path],
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

    def run(self, *args, region='morro-bay', through='envelope', zone_inputs=True):
        reaches_zone = STAGE_ORDER.index(through) >= STAGE_ORDER.index('zone')
        extra = ZONE_ARGS if reaches_zone and zone_inputs else []
        return RR.main([region, '--out', str(self.out), '--through', through, *extra, *args], self.cfg)

    def out_tree(self):
        return sorted(str(p.relative_to(self.out)) for p in self.out.rglob('*'))


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.delenv('SC_RELIEF_NORM', raising=False)
    monkeypatch.delenv('SC_RELIEF_OUT', raising=False)
    return Box(tmp_path)


def test_chain_order_and_stage_arguments(box, capsys):
    # Contract: the ten stages run in the fixed upstream-first order, each as `region.py <stage>
    # --region <id> --out <OUT>`. Bug caught: a reordered tuple or a dropped/renamed stage.
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
            assert tail == []


@pytest.mark.parametrize('drop', ['--coarse', '--water', '--coarse-source'])
def test_chain_reaching_zone_without_its_inputs_is_a_usage_error_before_any_stage(box, drop):
    # Contract: zone's mandatory inputs are checked up front. Bug caught: running normalize..tiles
    # for hours and only then failing zone on a missing flag. A chain that stops before zone needs none.
    args = list(ZONE_ARGS)
    index = args.index(drop)
    del args[index:index + 2]
    with pytest.raises(SystemExit) as stop:
        RR.main(['morro-bay', '--out', str(box.out), '--through', 'zone', *args], box.cfg)
    assert stop.value.code == 2 and box.ran() == []
    assert box.run(through='tiles', zone_inputs=False) == 0


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


def refuse_load(box):
    box.load = 24.0


def refuse_root_disk(box):
    box.free['/'] = 249 * RR.GB


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
    ('load', refuse_load, 'load5'),
    ('root-disk', refuse_root_disk, 'disk-root'),
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
    # `normalize` had already started loading the disk. Boundaries: load 24.0 refuses, floors are strict.
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
    assert RR.main(['morro-bay', '--out', str(box.out), '--through', 'zone', *args], box.cfg) == 3
    assert box.ran() == [] and 'input-path' in capsys.readouterr().out


def test_guards_pass_at_the_boundary_values(box):
    # Contract: load5 23.9 and exactly the disk floors are allowed (>= floor, < 24).
    box.load = 23.9
    box.free.update({'/': 250 * RR.GB, '/mnt/agentorange-backup': 400 * RR.GB})
    assert box.run(through='select') == 0


@pytest.mark.parametrize('trip', [refuse_stop_file, refuse_load, refuse_root_disk, refuse_backup_disk],
                         ids=['stop-file', 'load', 'root-disk', 'backup-disk'])
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
    for name in ('stop-file', 'load5', 'disk-root', 'disk-backup', 'out-root', 'norm-root', 'region-lock', 'run-cap'):
        assert f'ok     {name}' in text
    assert 'a real run would start' in text
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
