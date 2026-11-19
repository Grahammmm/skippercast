"""Private adoption must not mint a receipt for bytes changed during staging."""
from hashlib import sha256

import pytest

from tests._support import ROOT


@pytest.mark.gis
@pytest.mark.parametrize('changed', [None, 'cells.json', 'habitat.geojson', 'physical.json', 'run.json'],
                         ids=['stable', 'cells', 'screened-output', 'physical-receipt', 'run-receipt'])
def test_adoption_binds_staged_bytes_to_one_private_run(tmp_path, monkeypatch, changed):
    from skippercast.platform.contracts import atomic_json, read_json
    from skippercast.seafloor import adopt
    from skippercast.seafloor.io import sha256 as file_sha256
    from skippercast.seafloor.run import VERSION

    reach = 'fixture-reach'
    root = tmp_path
    private = root / 'var/seafloor/private-reaches' / reach
    destination = root / 'var/seafloor/reaches' / reach
    reference = root / 'var/seafloor/reference'
    rules = {'substrate_bindings': []}
    atomic_json(root / 'catalog/reaches.json', {'input_hash': 'grid', 'reaches': [{'id': reach}]})
    atomic_json(root / 'catalog/habitat-rules.json', rules)
    atomic_json(root / 'catalog/surveys.json', {'surveys': []})
    (root / 'catalog/survey.schema.json').write_bytes((ROOT / 'catalog/survey.schema.json').read_bytes())
    atomic_json(root / 'dist/data/atlas.json', {})
    (root / 'requirements-survey.txt').write_text('fixture')
    atomic_json(reference / 'cells.json', {'input_hash': 'grid', 'cells': []})
    reference_sha = file_sha256(reference / 'cells.json')
    atomic_json(reference / 'run.json', {'input_hash': 'grid', 'output_hashes': {'cells.json': reference_sha}})

    module = ROOT / 'src/skippercast/seafloor'
    inputs = {'reach_id': reach, 'rule_version': VERSION, 'reference_cells_sha256': reference_sha,
              'reaches_sha256': file_sha256(root / 'catalog/reaches.json'),
              'atlas_sha256': file_sha256(root / 'dist/data/atlas.json'),
              'scoring_sha256': file_sha256(module.parent / 'atlas/scoring.py'),
              'requirements_sha256': file_sha256(root / 'requirements-survey.txt'),
              'implementation': {name: file_sha256(module / name) for name in adopt.IMPLEMENTATION},
              'habitat_rules': rules, 'sources': [], 'substrate_bindings': {}}
    input_hash = adopt.digest(inputs)
    for name in adopt.OUTPUTS:
        atomic_json(private / name, {'input_hash': input_hash, 'data': []})
    atomic_json(private / 'physical.json', {'input_hash': input_hash,
                'outputs': {name: file_sha256(private / name) for name in adopt.PHYSICAL}})
    deferred_screen = {'reasons': ['screen-deferred']}
    receipt = {'inputs': dict(inputs, screen=deferred_screen), 'publication_prohibited': True,
               'ledger_summary': {'processing_incomplete': False}, 'physical_input_hash': input_hash,
               'outputs': {name: file_sha256(private / name) for name in adopt.OUTPUTS}}
    atomic_json(private / 'run.json', receipt)
    original_receipt = (private / 'run.json').read_bytes()

    # Change the producer's bytes at the real copy boundary; a pre-copy check
    # misses this, even if the changed JSON remains well formed.
    copyfile = adopt.shutil.copyfile

    def copy_during_refresh(src, dst):
        trigger = 'cells.json' if changed == 'run.json' else changed
        if src == private / trigger:
            path = private / changed
            atomic_json(path, dict(read_json(path), generation='replacement'))
        return copyfile(src, dst)

    if changed is not None:
        monkeypatch.setattr(adopt.shutil, 'copyfile', copy_during_refresh)
        with pytest.raises(ValueError, match='checksum mismatch|receipt changed'):
            adopt.adopt_private(reach, root=root)
        assert not destination.exists()
        assert not list(destination.parent.glob('.adopt-*'))
    else:
        evidence = adopt.adopt_private(reach, root=root)
        assert evidence['private_run_sha256'] == sha256(original_receipt).hexdigest()
        assert evidence['requires_current_screen'] is True
        transitional = read_json(destination / 'run.json')
        assert transitional['publication_prohibited'] is True
        assert transitional['inputs']['screen'] == deferred_screen
        assert transitional['outputs'] == {name: file_sha256(destination / name) for name in adopt.OUTPUTS}
        assert (destination / 'candidates.geojson').read_bytes() == (private / 'candidates.geojson').read_bytes()
