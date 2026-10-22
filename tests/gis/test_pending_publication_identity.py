"""Pending coverage must match today's complete physical identity."""
import importlib
import pytest
from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor import publish
from skippercast.seafloor.io import sha256
from tests._support import ROOT

runner = importlib.import_module('skippercast.seafloor.physical_identity')


def pending_root(root):
    atomic_json(root/'catalog/surveys.json', {'surveys': []})
    atomic_json(root/'catalog/survey.schema.json', read_json(ROOT/'catalog/survey.schema.json'))
    rules = read_json(ROOT/'catalog/habitat-rules.json')
    rules['substrate_bindings'] = []
    atomic_json(root/'catalog/habitat-rules.json', rules)
    atomic_json(root/'catalog/reaches.json', {'reaches': [{'id': 'r01'}]})
    atomic_json(root/'dist/data/atlas.json', {'areas': [], 'targets': []})
    (root/'requirements-survey.txt').write_text('synthetic requirements')
    ref = root/'var/seafloor/reference/cells.json'
    atomic_json(ref, {'cells': []})
    atomic_json(root/'dist/data/seafloor-ledger.json', {'reference_cells_sha256': sha256(ref),
        'reaches': [{'id': 'r01', 'region': 'synthetic', 'status': 'terrain-pending'}]})
    folder = root/'var/seafloor/reaches/r01'
    atomic_json(folder/'coverage-cells.json', {'cells': []})
    atomic_json(folder/'coverage-checkpoint.json', {
        'physical_input_hash': runner.current_physical_input_hash(root, 'r01'),
        'catalog_sha256': sha256(root/'catalog/surveys.json'),
        'rules_sha256': sha256(root/'catalog/habitat-rules.json'),
        'reference_sha256': sha256(ref), 'cells_sha256': sha256(folder/'coverage-cells.json')})
    return folder


@pytest.mark.parametrize('change', ['code', 'requirements', 'atlas', 'reaches', 'missing-identity'])
@pytest.mark.parametrize('rerun', [False, True])
def test_pending_identity_changes_refused_without_running(tmp_path, monkeypatch, change, rerun):
    folder = pending_root(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail('Pending publication must not execute terrain or overwrite evidence')
    monkeypatch.setattr(publish, 'run', forbidden)
    layers, receipts, _ = publish.region_layers(tmp_path, 'synthetic', rerun=rerun)
    assert layers == {'cells': [], 'habitat': []} and receipts == {}
    if change == 'code':
        original = runner.sha256
        monkeypatch.setattr(runner, 'sha256', lambda p: '0'*64 if p.name == 'coverage.py' else original(p))
    elif change == 'missing-identity':
        path = folder/'coverage-checkpoint.json'
        value = read_json(path); value.pop('physical_input_hash'); atomic_json(path, value)
    else:
        name = {'requirements': 'requirements-survey.txt', 'atlas': 'dist/data/atlas.json',
                'reaches': 'catalog/reaches.json'}[change]
        with (tmp_path/name).open('a') as stream:
            stream.write('\n')
    saved = {p.name: p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(ValueError, match='physical inputs changed'):
        publish.region_layers(tmp_path, 'synthetic', rerun=rerun)
    assert saved == {p.name: p.read_bytes() for p in folder.iterdir()}
