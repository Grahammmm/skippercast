"""RF0410-3: over-nested JSON yields a per-recipe INVALID row, not a crash."""
import json
import sys

import pytest

from tests._support import ROOT
import validate_recipe as recipe

NESTING = 'input nesting exceeds supported depth'
VALID_PATH = ROOT / 'regions' / 'morro-bay' / 'coast.json'


def _deep(tmp_path, name='deep.json'):
    depth = sys.getrecursionlimit() * 2
    path = tmp_path / name
    path.write_text('[' * depth + '0' + ']' * depth, encoding='utf-8')
    assert path.stat().st_size < recipe.MAX_JSON_BYTES
    return path


def _bad_json(tmp_path):
    path = tmp_path / 'bad.json'
    path.write_text('{"a": ', encoding='utf-8')
    return path


def _run(capsys, tmp_path, paths):
    code = recipe.main([str(p) for p in paths] + ['--workspace-root', str(tmp_path),
                                                  '--metadata-root', str(ROOT)])
    captured = capsys.readouterr()
    assert captured.err == ''
    return code, json.loads(captured.out)


def _assert_nesting_row(row, path):
    assert row == {'path': str(path), 'status': 'INVALID', 'valid': False, 'error': NESTING,
                   'semantic_approval': False, 'execution_allowed': False}


@pytest.mark.parametrize('order', ['DV', 'VD', 'DVD'])
def test_nested_file_batches_keep_order_and_valid_rows(tmp_path, capsys, order):
    deep = [_deep(tmp_path, 'deep%d.json' % i) for i in range(order.count('D'))]
    paths = [deep.pop(0) if ch == 'D' else VALID_PATH for ch in order]
    before = [p.read_bytes() for p in paths]
    code, results = _run(capsys, tmp_path, paths)
    assert code == 1 and len(results) == len(paths)
    for ch, path, row in zip(order, paths, results):
        if ch == 'D':
            _assert_nesting_row(row, path)
        else:
            assert row['status'] == 'REVIEW REQUIRED' and row['valid'] is True
            assert row['semantic_approval'] is False and row['execution_allowed'] is False
    assert [p.read_bytes() for p in paths] == before
    assert list(tmp_path.glob('runs*')) == []


def test_recursion_in_validation_call_is_contained(tmp_path, capsys, monkeypatch):
    def boom(*args, **kwargs):
        raise RecursionError('synthetic')
    monkeypatch.setattr(recipe, 'validate_recipe', boom)
    code, results = _run(capsys, tmp_path, [VALID_PATH])
    assert code == 1
    _assert_nesting_row(results[0], VALID_PATH)


def test_other_runtime_errors_are_not_swallowed(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise MemoryError('synthetic')
    monkeypatch.setattr(recipe, 'validate_recipe', boom)
    with pytest.raises(MemoryError):
        recipe.main([str(VALID_PATH), '--workspace-root', str(tmp_path)])


def test_ordinary_malformed_json_message_unchanged(tmp_path, capsys):
    bad = _bad_json(tmp_path)
    code, results = _run(capsys, tmp_path, [bad])
    assert code == 1
    assert results[0]['error'].startswith('invalid JSON: ')
    assert results[0]['error'] != NESTING
