"""scripts/relief/run_region.py run log: one OUT/<region>/runs/<stamp>.json per run (Issue #3819 slice A).

The log is how a person sees a pipeline run: each step, its state and its time, and why the run ended.
Uses the fake region.py of test_run_region.py; no real stage runs.
"""
import json

import pytest

from scripts.relief import run_region as RR
from tests.unit.test_run_region import Box, STAGE_ORDER


@pytest.fixture
def box(tmp_path, monkeypatch):
    monkeypatch.delenv('SC_RELIEF_NORM', raising=False)
    monkeypatch.delenv('SC_RELIEF_OUT', raising=False)
    return Box(tmp_path)


def receipt(box, name, ended):
    path = box.out / 'morro-bay' / 'stages' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'ended': ended}))


def the_log(box):
    [path] = sorted((box.out / 'morro-bay' / RR.RUNS_DIR).glob('*.json'))
    return path, json.loads(path.read_text())


def test_complete_run_logs_every_step_with_state_and_time(box, capsys):
    # Old receipt = the stage found itself done (no work); fresh receipt = built; no receipt = ok.
    receipt(box, 'select.json', '2000-01-01T00:00:00Z')
    receipt(box, 'mosaic.public.json', '2999-01-01T00:00:00Z')
    assert box.run(through='tiles') == 0
    path, doc = the_log(box)
    assert path.name.endswith('-p424242.json')
    assert {k: doc[k] for k in ('schema', 'region', 'through', 'outcome', 'exit', 'reason')} == {
        'schema': 'sc-run-log/1', 'region': 'morro-bay', 'through': 'tiles', 'outcome': 'complete',
        'exit': 0, 'reason': None}
    assert doc['started'] <= doc['ended']
    assert [(s['step'], s['exit'], s['state']) for s in doc['steps']] == [
        ('select', 0, 'done'), ('mosaic', 0, 'built'), ('tiles', 0, 'ok')]
    assert all(isinstance(s['seconds'], float) and s['seconds'] >= 0 for s in doc['steps'])
    out = capsys.readouterr().out.splitlines()
    table = out.index(f'run log {path}')
    assert [line.split()[:2] for line in out[table + 1:table + 5]] == [
        ['step', 'state'], ['select', 'done'], ['mosaic', 'built'], ['tiles', 'ok']]
    assert out[-1] == 'run_region: morro-bay complete through tiles'


def test_status_handoff_is_its_own_step(box):
    assert box.run(through='package') == 0
    _, doc = the_log(box)
    assert [s['step'] for s in doc['steps']] == [*STAGE_ORDER[:STAGE_ORDER.index('package') + 1], 'status:package']


@pytest.mark.parametrize('code, state, exit_code', [
    (1, 'failed', 1), (3, 'blocked', 3), (4, 'held', 4), (5, 'busy', 5), (2, 'not available', 2), (7, 'failed', 7)])
def test_run_stops_at_the_first_failed_or_held_stage_and_logs_why(box, capsys, code, state, exit_code):
    box.codes({'mosaic': code})
    assert box.run(through='tiles') == exit_code
    assert box.ran() == ['select', 'mosaic']
    _, doc = the_log(box)
    assert [(s['step'], s['exit'], s['state']) for s in doc['steps']] == [('select', 0, 'ok'), ('mosaic', code, state)]
    assert (doc['outcome'], doc['exit']) == ('stopped', exit_code)
    assert doc['reason'].startswith('STOPPED at mosaic: ')
    assert capsys.readouterr().out.splitlines()[-1] == f'run_region: {doc["reason"]}'


def test_guard_tripped_mid_run_is_logged_as_refused(box):
    box.codes({}, trip_after='mosaic', trip_file=str(box.local_stop))
    assert box.run(through='tiles') == 3
    _, doc = the_log(box)
    assert [s['step'] for s in doc['steps']] == ['select', 'mosaic']
    assert (doc['outcome'], doc['exit']) == ('refused', 3)
    assert doc['reason'].startswith('refused before tiles: ')


def test_run_refused_before_the_lock_writes_no_log(box):
    box.local_stop.touch()
    assert box.run(through='tiles') == 3
    assert box.out_tree() == []


def test_unwritable_log_is_reported_and_the_chain_still_runs(box, capsys):
    (box.out / 'morro-bay').mkdir()
    (box.out / 'morro-bay' / RR.RUNS_DIR).write_text('not a directory')
    assert box.run(through='tiles') == 0
    assert box.ran() == ['select', 'mosaic', 'tiles']
    out = capsys.readouterr().out
    assert out.count('run_region: warning: cannot write the run log') == 1


def test_interrupted_run_keeps_its_finished_steps(box, monkeypatch):
    real = RR.subprocess.run

    def interrupt_at_tiles(command, **kwargs):
        if 'tiles' in command:
            raise KeyboardInterrupt
        return real(command, **kwargs)

    monkeypatch.setattr(RR.subprocess, 'run', interrupt_at_tiles)
    assert box.run(through='tiles') == 130
    _, doc = the_log(box)
    assert [s['step'] for s in doc['steps']] == ['select', 'mosaic']
    assert (doc['outcome'], doc['exit']) == ('interrupted', 130)
