"""RF0510-9: coast_sample typed input checks (ValueError) and CLI exit 2 with one stderr line."""
import importlib.util
import json

import pytest

from tests._support import ROOT

SCRIPT = ROOT / 'skills' / 'coast-campaign-shared' / 'scripts' / 'coast_sample.py'
_spec = importlib.util.spec_from_file_location('_rf0510_9_coast_sample', SCRIPT)
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

PLAN = 'a' * 64
BRIDGE = '0123456789abcdef' * 4
DONE = ['k%02d' % i for i in range(80)]
ELIGIBLE = DONE[::4]
# Computed on origin/main 03712ec7 (before this change) with the same input.
GOLDEN = {
    'method_version': 'coast-sample-v1',
    'seed': 'c1d40d3fb44e3d0a2151a528faa4fc492e89df276f7ad1d15e165649d892979b',
    'target': 10, 'size': 10,
    'selected': ['k16', 'k28', 'k40', 'k44', 'k52', 'k56', 'k60', 'k64', 'k68', 'k72'],
    'map_done': sorted(DONE), 'eligible': sorted(ELIGIBLE),
}
GOOD = {'map_done': DONE, 'eligible': ELIGIBLE, 'plan_sha256': PLAN, 'bridge_sha256': BRIDGE}


def test_valid_input_selection_unchanged():
    assert cs.sample(DONE, ELIGIBLE, plan_sha256=PLAN, bridge_sha256=BRIDGE) == GOLDEN
    assert cs.sample(tuple(DONE), tuple(ELIGIBLE), plan_sha256=PLAN, bridge_sha256=BRIDGE) == GOLDEN


@pytest.mark.parametrize('grid', [None, 7, 'A' * 64, 'a' * 63, ['a'] * 64])
def test_window_key_bad_grid_is_value_error(grid):
    with pytest.raises(ValueError, match=r'^invalid grid SHA256$'):
        cs.window_key('s', grid, 0)


@pytest.mark.parametrize('field', ['plan_sha256', 'bridge_sha256'])
@pytest.mark.parametrize('digest', [None, 7, 'A' * 64, 'b' * 65])
def test_bad_binding_digest_is_value_error(field, digest):
    kwargs = {'plan_sha256': PLAN, 'bridge_sha256': BRIDGE, field: digest}
    with pytest.raises(ValueError, match=r'^invalid sample binding SHA256$'):
        cs.sample(DONE, ELIGIBLE, **kwargs)


@pytest.mark.parametrize('done,eligible', [
    ([['a']], []), (['a'], [['a']]), (['a', 'b', 'c'], 'abc'), ('abc', []), ([''], []),
    (['a'], ['']), (None, []), (['a'], None), ([1], []), ({'a'}, []),
])
def test_bad_population_is_value_error(done, eligible):
    with pytest.raises(ValueError, match=r'^sample populations must be lists of window keys$'):
        cs.sample(done, eligible, plan_sha256=PLAN, bridge_sha256=BRIDGE)


def test_duplicate_and_subset_checks_follow():
    with pytest.raises(ValueError, match=r'^duplicate sample population$'):
        cs.sample(['x', 'x'], [], plan_sha256=PLAN, bridge_sha256=BRIDGE)
    with pytest.raises(ValueError, match=r'^eligible must be a subset of map_done window keys$'):
        cs.sample(['x'], ['y'], plan_sha256=PLAN, bridge_sha256=BRIDGE)


def _run(tmp_path, capsys, text):
    path = tmp_path / 'in.json'
    if text is not None:
        path.write_text(text, encoding='utf-8')
    status = cs.main([str(path)])
    out, err = capsys.readouterr()
    return status, out, err


def _object(**changes):
    doc = dict(GOOD, **changes)
    return json.dumps({k: v for k, v in doc.items() if v is not ...})


@pytest.mark.parametrize('text,message', [
    (_object(map_done=float('nan')), 'non-finite number NaN refused'),
    (_object(plan_sha256=float('inf')), 'non-finite number Infinity refused'),
    (json.dumps([GOOD]), 'input must be one object with the four sample keys'),
    ('"text"', 'input must be one object with the four sample keys'),
    (_object(x=1), 'input must be one object with the four sample keys'),
    (_object(bridge_sha256=...), 'input must be one object with the four sample keys'),
    (_object(eligible=[['k00']]), 'sample populations must be lists of window keys'),
    (_object(plan_sha256=None), 'invalid sample binding SHA256'),
    ('{"map_done": [', None),
    (None, None),
])
def test_cli_bad_input_exit_2_one_line(tmp_path, capsys, text, message):
    status, out, err = _run(tmp_path, capsys, text)
    assert status == 2 and out == ''
    assert err.endswith('\n') and err.count('\n') == 1 and err.startswith('coast-sample: ')
    if message is not None:
        assert err == 'coast-sample: ' + message + '\n'
    if text is None:
        assert 'No such file' in err


def test_cli_non_utf8_file_exit_2(tmp_path, capsys):
    path = tmp_path / 'in.json'
    path.write_bytes(b'{"map_done": "\xff"}')
    assert cs.main([str(path)]) == 2
    out, err = capsys.readouterr()
    assert out == '' and err.count('\n') == 1 and err.startswith('coast-sample: ')


def test_cli_good_file_compact_sorted_line(tmp_path, capsys):
    status, out, err = _run(tmp_path, capsys, json.dumps(GOOD))
    assert status == 0 and err == ''
    assert out == json.dumps(GOLDEN, sort_keys=True, separators=(',', ':')) + '\n'
