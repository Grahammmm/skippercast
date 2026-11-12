"""Final serialized verification manifests are bounded before either is replaced."""
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest

from skippercast.pipeline import verification_archive as va
from skippercast.pipeline.verification_archive import load_archive, prune_archive, write_archive

NOW = 1790092800
REGION = 'test-bay'
CURRENT = 'verification-state.json'
PREVIOUS = 'verification-state.previous.json'


def forecasts(n, offset=0):
    return [{'id': f'f{offset + i}', 'station': 'st1', 'model': 'mod1', 'cycle': NOW + 60 * (offset + i),
             'time': NOW + 3600 + 60 * (offset + i)} for i in range(n)]


def observations(n):
    return [{'id': f'o{i}', 'station': 'st1', 'time': NOW + 60 * i} for i in range(n)]


def canonical(path):
    """Test-side oracle: re-serialize the parsed manifest independently of the module helpers."""
    data = json.loads(Path(path).read_text('utf-8'))
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8') + b'\n'


def manifest_installs(spy):
    return [c.args[0].name for c in spy.call_args_list if c.args[0].name in (CURRENT, PREVIOUS)]


def snapshot(directory):
    return {str(p.relative_to(directory)): p.read_bytes() for p in sorted(directory.rglob('*')) if p.is_file()}


def test_newline_counts_toward_current_limit(tmp_path):
    write_archive(tmp_path / 'ref', REGION, forecasts(1), [], NOW)
    raw = (tmp_path / 'ref' / CURRENT).read_bytes()
    assert raw.endswith(b'\n') and raw == canonical(tmp_path / 'ref' / CURRENT)
    body = len(raw) - 1
    with patch.object(va, 'MAX_MANIFEST_BYTES', body):
        with pytest.raises(ValueError, match='size bound'):
            write_archive(tmp_path / 'tight', REGION, forecasts(1), [], NOW)
        assert not (tmp_path / 'tight' / CURRENT).exists()
    with patch.object(va, 'MAX_MANIFEST_BYTES', body + 1):
        write_archive(tmp_path / 'exact', REGION, forecasts(1), [], NOW)
        assert (tmp_path / 'exact' / CURRENT).read_bytes() == raw
        assert len(load_archive(tmp_path / 'exact', REGION, required=True)['forecasts']) == 1
        assert prune_archive(tmp_path / 'exact') == 0


def test_oversized_replacement_preserves_both_prior_manifests(tmp_path):
    live = tmp_path / 'live'
    write_archive(live, REGION, forecasts(1), [], NOW)
    write_archive(live, REGION, forecasts(2), [], NOW + 1)
    (live / 'sentinel.txt').write_text('keep')
    trial = tmp_path / 'trial'
    shutil.copytree(live, trial)
    write_archive(trial, REGION, forecasts(2), observations(1), NOW + 2)
    new_size = len((trial / CURRENT).read_bytes())
    old_size = len((live / CURRENT).read_bytes())
    assert new_size > old_size
    before = snapshot(live)
    with patch.object(va, 'MAX_MANIFEST_BYTES', new_size - 1), \
            patch.object(va, '_atomic_bytes', wraps=va._atomic_bytes) as spy, \
            patch.object(va, 'prune_archive') as prune:
        with pytest.raises(ValueError, match='size bound'):
            write_archive(live, REGION, forecasts(2), observations(1), NOW + 2)
    assert manifest_installs(spy) == []
    prune.assert_not_called()
    after = snapshot(live)
    assert all(after[name] == data for name, data in before.items())
    assert len(load_archive(live, REGION, required=True)['forecasts']) == 2


def _legacy(directory):
    directory.mkdir(parents=True)
    (directory / CURRENT).write_text(json.dumps({'schema_version': 1, 'region_id': REGION,
                                                 'forecasts': forecasts(3), 'observations': observations(2)}))


def test_migration_marker_is_included_before_admission(tmp_path):
    _legacy(tmp_path / 'ref')
    write_archive(tmp_path / 'ref', REGION, [], [], NOW)
    marked = (tmp_path / 'ref' / PREVIOUS).read_bytes()
    assert marked == canonical(tmp_path / 'ref' / PREVIOUS)
    assert json.loads(marked)['migrated_from_schema_version'] == 1
    current_size = len((tmp_path / 'ref' / CURRENT).read_bytes())
    assert current_size < len(marked) - 1

    # one byte short of the complete marked previous manifest: refused, nothing replaced
    _legacy(tmp_path / 'short')
    legacy_bytes = (tmp_path / 'short' / CURRENT).read_bytes()
    with patch.object(va, 'MAX_MANIFEST_BYTES', len(marked) - 1), \
            patch.object(va, '_atomic_bytes', wraps=va._atomic_bytes) as spy:
        with pytest.raises(ValueError, match='size bound'):
            write_archive(tmp_path / 'short', REGION, [], [], NOW)
    assert manifest_installs(spy) == []
    assert (tmp_path / 'short' / CURRENT).read_bytes() == legacy_bytes
    assert not (tmp_path / 'short' / PREVIOUS).exists()

    # exact endpoint: accepted, installed bytes match the independent calculation
    _legacy(tmp_path / 'exact')
    with patch.object(va, 'MAX_MANIFEST_BYTES', len(marked)):
        write_archive(tmp_path / 'exact', REGION, [], [], NOW)
        assert (tmp_path / 'exact' / PREVIOUS).read_bytes() == marked
        previous = load_archive(tmp_path / 'exact', REGION, required=True, manifest_name=PREVIOUS)
        assert len(previous['forecasts']) == 3 and len(previous['observations']) == 2


def test_oversized_current_installs_no_valid_previous(tmp_path):
    live = tmp_path / 'live'
    write_archive(live, REGION, forecasts(1), [], NOW)
    trial = tmp_path / 'trial'
    shutil.copytree(live, trial)
    write_archive(trial, REGION, forecasts(1), observations(3), NOW + 1)
    new_size = len((trial / CURRENT).read_bytes())
    assert new_size > len((live / CURRENT).read_bytes())
    before = snapshot(live)
    with patch.object(va, 'MAX_MANIFEST_BYTES', new_size - 1), \
            patch.object(va, '_atomic_bytes', wraps=va._atomic_bytes) as spy:
        with pytest.raises(ValueError, match='size bound'):
            write_archive(live, REGION, forecasts(1), observations(3), NOW + 1)
    assert manifest_installs(spy) == []
    assert not (live / PREVIOUS).exists()
    after = snapshot(live)
    assert all(after[k] == v for k, v in before.items())
