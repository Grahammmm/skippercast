"""RF0450-4: an unreadable or non-object scope config is a ValueError naming its repo-relative path."""
import json
from json import JSONDecodeError

import pytest

from skippercast.seafloor.scope_paths import resolve_scope


def scope_root(tmp_path, data):
    (tmp_path / 'catalog').mkdir()
    (tmp_path / 'scopes').mkdir()
    config = tmp_path / 'scopes/x.json'
    config.write_bytes(data if isinstance(data, bytes) else data.encode())
    return tmp_path, config


def refusal(root, **kwargs):
    with pytest.raises(ValueError) as caught:
        resolve_scope(root, **kwargs)
    message = str(caught.value)
    assert str(root) not in message
    return caught.value, message


@pytest.mark.parametrize('text', ['[1, 2]', '"text"', 'null', '3', 'true'])
def test_non_object_config_is_named(tmp_path, text):
    root, _ = scope_root(tmp_path, text)
    _, message = refusal(root, scope_config='scopes/x.json')
    assert message == 'Scope config must be a JSON object: scopes/x.json'


def test_absolute_config_path_is_still_named_relative(tmp_path):
    root, config = scope_root(tmp_path, '[]')
    _, message = refusal(root, scope_config=config)
    assert message.endswith('must be a JSON object: scopes/x.json')


def test_truncated_json_is_named_and_chained(tmp_path):
    root, _ = scope_root(tmp_path, '{"id": "a",')
    error, message = refusal(root, scope_config='scopes/x.json')
    assert message == 'Scope config is not valid JSON: scopes/x.json'
    assert isinstance(error.__cause__, JSONDecodeError)


@pytest.mark.parametrize('text', ['{"id": "a", "id": "b"}', '{"id": "a", "depth": NaN}',
                                  '{"id": "a", "depth": Infinity}', ''])
def test_duplicate_key_non_finite_or_empty_is_not_valid_json(tmp_path, text):
    root, _ = scope_root(tmp_path, text)
    error, message = refusal(root, scope_config='scopes/x.json')
    assert message == 'Scope config is not valid JSON: scopes/x.json'
    assert isinstance(error.__cause__, ValueError)


@pytest.mark.parametrize('data', [b'\xff\xfe{}', b'{"id": "caf\xe9"}'])
def test_non_utf8_bytes_are_named(tmp_path, data):
    root, _ = scope_root(tmp_path, data)
    error, message = refusal(root, scope_config='scopes/x.json')
    assert message == 'Scope config is not UTF-8 text: scopes/x.json'
    assert isinstance(error.__cause__, UnicodeDecodeError)


def test_central_default_list_is_named(tmp_path):
    (tmp_path / 'catalog').mkdir()
    (tmp_path / 'catalog/seafloor-scope.json').write_text('[]')
    _, message = refusal(tmp_path, scope_config=None)
    assert message == 'Scope config must be a JSON object: catalog/seafloor-scope.json'


def test_valid_noncentral_config_resolves_unchanged(tmp_path):
    root, config = scope_root(tmp_path, json.dumps({'id': 'offline-demo', 'bounds': [0, 0, 1, 1]}))
    loaded, paths = resolve_scope(root, scope_config='scopes/x.json')
    base = root.resolve() / 'var/seafloor/scopes/offline-demo'
    assert loaded == {'id': 'offline-demo', 'bounds': [0, 0, 1, 1]}
    assert paths.scope_id == 'offline-demo'
    assert paths.config_path == config.resolve()
    assert not paths.is_central_default
    assert paths.reference_dir == base / 'reference'
    assert paths.ledger_path == base / 'seafloor-ledger.json'
    assert paths.reaches_path == base / 'reaches.json'
    assert paths.cells_path == base / 'reference/cells.json'
    assert paths.build_receipt_path == base / 'reference/run.json'
    assert paths.screen_dir == base / 'screen'


def test_object_without_stable_id_keeps_existing_message(tmp_path):
    root, _ = scope_root(tmp_path, '{"id": "Bad ID"}')
    _, message = refusal(root, scope_config='scopes/x.json')
    assert message == 'Scope config needs a stable lowercase ID'
