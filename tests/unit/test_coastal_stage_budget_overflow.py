"""Stage CLI: an unrepresentable wall budget is a terminal input receipt.

Only the library-version report is stubbed (it imports GIS packages). Job JSON
decoding, confinement, reference hashing, execute, error handling and the result
writer are real.
"""
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest

from skippercast.coastal import stage_cli
from skippercast.coastal.coordinator import source_free
from skippercast.coastal.handoff.common import digest, ref, write
from tests._support import NOW

HOLD = 'invalid_stage_input:ValueError:job wall budget cannot form a supported review horizon'
SENTINEL = '"@@WALL@@"'
FAR_DEADLINE = 32503680000.0


@pytest.fixture(autouse=True)
def no_gis_libraries():
    with patch.object(stage_cli.mapping_input, 'libraries', return_value=dict(synthetic='stub')):
        yield


def make_job(root, *, wall=60, manifest=None, stage='discover'):
    manifest = manifest or {'schema': 'synthetic-unsupported-v1', 'synthetic': True}
    write(root / 'input.json', manifest)
    reference = ref(root, root / 'input.json', manifest['schema'])
    params = {}
    return dict(root=str(root), stage=stage, job_id='synthetic-job',
                segment=dict(segment_id='seg-1', synthetic=True), lease_token='synthetic-token',
                code_sha='a' * 64, deps_sha='b' * 64, params=params, params_sha=digest(params),
                input_manifest=reference, input_manifest_sha=reference['sha256'],
                budget=dict(wall_s=wall, bytes=1000000, requests=0), deadline_utc=FAR_DEADLINE)


def write_job(root, job, wall_text):
    """Write job JSON with the wall budget spelled exactly as ``wall_text``."""
    text = json.dumps(dict(job, budget=dict(job['budget'], wall_s='@@WALL@@')))
    path = root / 'job.json'
    path.write_text(text.replace(SENTINEL, wall_text))
    return path


def run_cli(root, job, wall_text):
    path = write_job(root, job, wall_text)
    code = stage_cli.main(['run', '--job', str(path), '--out', 'out'])
    return code, json.loads((root / 'out' / 'result.json').read_text())


def refused(root, wall_text, capsys):
    job = make_job(root)
    before = (root / 'input.json').read_bytes()
    code, result = run_cli(root, job, wall_text)
    assert code == 5
    assert json.loads(capsys.readouterr().out) == dict(state='failed_terminal', holds=[HOLD])
    assert result['state'] == 'failed_terminal' and result['holds'] == [HOLD]
    assert result['artifacts'] == [] and 'next_job' not in result
    for key in ('job_id', 'stage', 'lease_token', 'code_sha', 'deps_sha', 'input_manifest_sha', 'params_sha'):
        assert result[key] == job[key]
    assert result['segment_id'] == 'seg-1'
    assert result['usage']['requests'] == 0 and 'wall_s' in result['usage']
    assert result['provenance'] == dict(libs=dict(synthetic='stub'), synthetic=True)
    assert (root / 'input.json').read_bytes() == before
    assert sorted(p.name for p in (root / 'out').iterdir()) == ['result.json']
    return result


@pytest.mark.parametrize('wall_text', ['1e100', '-1e100'])
def test_large_finite_wall_budget_is_terminal_input_error(tmp_path, capsys, wall_text):
    refused(tmp_path, wall_text, capsys)


@pytest.mark.parametrize('wall_text', [str(10 ** 400), str(-10 ** 400)])
def test_huge_integer_conversion_is_contained(tmp_path, capsys, wall_text):
    refused(tmp_path, wall_text, capsys)
    job = make_job(tmp_path / 'direct')
    job['budget']['wall_s'] = int(wall_text)
    with pytest.raises(ValueError) as caught:
        stage_cli.execute(job, 'out', now=NOW)
    assert str(caught.value) == 'job wall budget cannot form a supported review horizon'
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


@pytest.mark.parametrize('wall_text', ['1e400', '-1e400'])
def test_overflowing_json_exponent_is_contained(tmp_path, capsys, wall_text):
    result = refused(tmp_path, wall_text, capsys)
    assert 'inf' not in result['holds'][0] and '1e400' not in result['holds'][0]


def test_datetime_addition_overflow_is_contained(tmp_path):
    job = make_job(tmp_path)
    late = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    timedelta(seconds=1000)  # representable on its own; only the addition overflows
    with pytest.raises(ValueError, match='cannot form a supported review horizon'):
        stage_cli.execute(dict(job, budget=dict(wall_s=1000)), 'out', now=late)


def test_ordinary_budget_and_old_refusals_unchanged(tmp_path, capsys):
    job = make_job(tmp_path)
    code, result = run_cli(tmp_path, job, '60')
    assert code == 3 and result['state'] == 'held'
    assert result['holds'] == ['bounded_catalog_adapter_unavailable']
    assert json.loads(capsys.readouterr().out) == dict(state='held', holds=result['holds'])
    with pytest.raises(ValueError, match='could not convert'):
        stage_cli.execute(dict(job, budget=dict(wall_s='soon')), 'out', now=NOW)
    with pytest.raises(TypeError):
        stage_cli.execute(dict(job, budget=dict(wall_s=None)), 'out', now=NOW)
    with pytest.raises(KeyError):
        stage_cli.execute(dict(job, budget={}), 'out', now=NOW)
    for wall in ('soon', None):  # existing CLI conversion is also unchanged
        code, result = run_cli(tmp_path, job, json.dumps(wall))
        assert code == 5 and result['holds'][0].startswith('invalid_stage_input:')
        assert 'review horizon' not in result['holds'][0]


def qualify_job(root, wall):
    manifest = dict(schema='coastal-native-job-v1', synthetic=True, segment_id='seg-1',
                    source='cell.tif', window={}, vertical={}, rights={})
    return make_job(root, wall=wall, manifest=manifest, stage='qualify')


def test_later_overflow_is_not_input_normalized(tmp_path):
    job = qualify_job(tmp_path, 60)
    with patch.object(stage_cli.mapping_input, 'produce', side_effect=OverflowError('later')):
        with pytest.raises(OverflowError, match='later'):
            stage_cli.execute(job, 'out', now=NOW)
        path = write_job(tmp_path, job, '60')
        with pytest.raises(OverflowError, match='later'):
            stage_cli.main(['run', '--job', str(path), '--out', 'cli-out'])
    assert not (tmp_path / 'cli-out' / 'result.json').exists()


def test_no_work_or_completion_artifacts_on_budget_refusal(tmp_path, capsys):
    job = qualify_job(tmp_path, 60)
    spies = {name: patch.object(stage_cli.mapping_input, name, side_effect=AssertionError(name))
             for name in ('produce', 'observe', 'verify')}
    spies['run'] = patch.object(stage_cli.mapping, 'run', side_effect=AssertionError('run'))
    spies['resolve'] = patch.object(stage_cli, 'resolve', side_effect=AssertionError('resolve'))
    started = [spy.start() for spy in spies.values()]
    try:
        code, result = run_cli(tmp_path, job, '1e400')
    finally:
        for spy in spies.values():
            spy.stop()
    assert code == 5 and result['holds'] == [HOLD]
    assert result['artifacts'] == [] and 'next_job' not in result
    assert sorted(p.name for p in (tmp_path / 'out').iterdir()) == ['result.json']
    assert not any(spy.called for spy in started)
    assert json.loads(capsys.readouterr().out)['state'] == 'failed_terminal'


def test_sourcefree_delegation_stays_before_horizon(tmp_path):
    out = tmp_path / 'out'
    job = dict(sourcefree_contract=True, budget=dict(wall_s=10 ** 400))
    sentinel = dict(state='delegated')
    with patch.object(source_free, 'execute', return_value=sentinel) as delegate:
        assert stage_cli.execute(job, out, now=NOW) is sentinel
    delegate.assert_called_once_with(job, out, now=NOW)
