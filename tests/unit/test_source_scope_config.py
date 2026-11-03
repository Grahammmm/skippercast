"""RF0510-7: a damaged deployment config or scope marker is one named ValueError."""
import json

import pytest

from skippercast.seafloor import rights
from skippercast.seafloor.source_scope import processing_scope

CONFIG = 'Invalid deployment config: deployments/production.json'
UNKNOWN = 'Unknown seafloor input source scope'
MARKER = 'Invalid input scope marker'


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.delenv('SKIPPERCAST_SOURCE_SCOPE', raising=False)
    return tmp_path


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode())


def refusal(root):
    with pytest.raises(ValueError) as caught:
        processing_scope(root)
    assert str(root) not in str(caught.value)
    return caught.value


def test_no_config_no_marker_no_env_is_all(root):
    assert processing_scope(root) == 'all'


def test_object_without_source_scope_is_all(root):
    write(root, 'deployments/production.json', '{"use": "nonprofit"}')
    assert processing_scope(root) == 'all'


@pytest.mark.parametrize('text', ['[]', '"all"', 'null', '7', '["all"]'])
def test_non_object_config_is_named(root, text):
    write(root, 'deployments/production.json', text)
    assert str(refusal(root)) == CONFIG


@pytest.mark.parametrize('text', ['{', '', '{"source_scope": "all", "source_scope": "all"}',
                                  '{"source_scope": NaN}', b'\xff{}'])
def test_unreadable_config_is_named_and_chained(root, text):
    write(root, 'deployments/production.json', text)
    error = refusal(root)
    assert str(error) == CONFIG
    assert isinstance(error.__cause__, ValueError)


@pytest.mark.parametrize('value', [['all'], 1, None, {'scope': 'all'}, True])
def test_non_text_source_scope_is_unknown(root, value):
    write(root, 'deployments/production.json', json.dumps({'source_scope': value}))
    assert str(refusal(root)) == UNKNOWN


def test_non_text_source_scope_is_unknown_even_with_env(root, monkeypatch):
    write(root, 'deployments/production.json', '{"source_scope": ["government-only"]}')
    monkeypatch.setenv('SKIPPERCAST_SOURCE_SCOPE', 'government-only')
    assert str(refusal(root)) == UNKNOWN


@pytest.mark.parametrize('text', ['not json', '{', b'\xff\xfe'])
def test_default_scope_with_unreadable_marker_is_named(root, text):
    write(root, 'var/seafloor/input-scope.json', text)
    error = refusal(root)
    assert str(error) == MARKER
    assert isinstance(error.__cause__, ValueError)


@pytest.mark.parametrize('marker', ['{"version": 1}', '[]', '"text"'])
def test_default_scope_with_json_marker_is_unchanged(root, marker):
    write(root, 'var/seafloor/input-scope.json', marker)
    assert str(refusal(root)) == 'Default processing cannot use a scoped isolated root'


def government_root(root, monkeypatch, marker):
    write(root, 'deployments/production.json', '{"source_scope": "government-only"}')
    write(root, 'var/seafloor/input-scope.json', marker)
    monkeypatch.setenv('SKIPPERCAST_SOURCE_SCOPE', 'government-only')
    monkeypatch.setattr(rights, 'deployment_use', lambda _root: 'for-profit')


def test_government_scope_with_matching_marker_is_unchanged(root, monkeypatch):
    marker = {'version': 1, 'scope': 'government-only', 'isolated_root': str(root.resolve())}
    government_root(root, monkeypatch, json.dumps(marker))
    assert processing_scope(root) == 'government-only'


def test_government_scope_with_unreadable_marker_is_named(root, monkeypatch):
    government_root(root, monkeypatch, 'not json')
    assert str(refusal(root)) == MARKER


def test_environment_still_cannot_weaken_configured_government_scope(root, monkeypatch):
    write(root, 'deployments/production.json', '{"source_scope": "government-only"}')
    monkeypatch.setenv('SKIPPERCAST_SOURCE_SCOPE', 'all')
    assert str(refusal(root)) == 'Environment cannot weaken configured government input scope'
