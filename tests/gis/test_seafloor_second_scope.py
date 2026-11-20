"""A fictional second scope: reaches, plan and run stay private, physical-only and held."""
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

import numpy as np
import pytest
from rasterio.transform import Affine
from shapely.geometry import LineString, mapping

from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor import __main__ as cli, grid, rollout, run as run_module, scoped_grid
from skippercast.seafloor.io import sha256
from skippercast.seafloor.manifest import qualify_row
from skippercast.seafloor.source_ingest import ingest
from tests._support import ROOT
from tests.gis import test_seafloor_multibeam_grid as multibeam

REACH = 'demo-region-r01'
CONFIGS = {'catalog/demo-scope.json': 'offline-demo', 'catalog/second-scope.json': 'offline-two'}


@pytest.fixture
def root():
    fixture = multibeam.PrivateGridTests('test_private_source_never_fetches_or_enters_default_run')
    fixture.setUp()
    base = fixture.root
    receipt, _, _ = ingest(fixture.row, fixture.bounds, root=base, local=fixture.source)
    row = qualify_row(fixture.row, receipt, rights_url=fixture.row['url'], physical_only=True)
    (base/'catalog/surveys.json').write_text(json.dumps({'surveys': [row]}))
    rules = json.loads((ROOT/'catalog/habitat-rules.json').read_text())
    rules['substrate_bindings'] = []
    (base/'catalog/habitat-rules.json').write_text(json.dumps(rules))
    (base/'requirements-survey.txt').write_text('fixture')
    (base/'dist/data').mkdir(parents=True)
    (base/'dist/data/atlas.json').write_text('{"points":[],"zones":[],"drift_corridors":[]}')
    (base/'dist/data/seafloor-ledger.json').write_text('{"reaches":[],"totals":{}}')
    shutil.copyfile(ROOT/'catalog/seafloor-scope.json', base/'catalog/seafloor-scope.json')
    for name, ident in CONFIGS.items():
        config = json.loads((ROOT/'catalog/seafloor-scope.json').read_text())
        config.update(id=ident, bounds=[0, 0, 1, 1], priority_anchor=[.5, .5],
                      regions=[{'id': 'demo-region', 'start_anchor': [.1, .1]}])
        (base/name).write_text(json.dumps(config))
    yield base
    fixture.doCleanups()


def reference_patches():
    spine = LineString([(0, 0), (1000, 0)])

    class FakeTransform:
        @staticmethod
        def transform(x, y):
            return np.full(np.shape(x), .5), np.full(np.shape(y), .5)

    reach = {'id': REACH, 'region': 'demo-region', 'order': 1, 'start_m': 0, 'end_m': 1000,
             'length_m': 1000, 'bounds_3310': [0, 0, 1000, 0], 'geometry': mapping(spine)}
    stack = ExitStack()
    for target, name, value in (
            (grid.reference, 'planning_spine', spine),
            (grid.reference, 'scheme_tiles', ({'scheme_sha256': 'fixture', 'scheme_url': 'fixture'}, [])),
            (grid.reference, 'samples', []), (scoped_grid, 'make_reaches', [reach]),
            (scoped_grid, 'mosaic_reference', (np.full((10, 10), 2, dtype='uint8'), Affine(25, 0, 0, 0, -25, 250))),
            (scoped_grid, 'assign_reaches', np.array([0]))):
        stack.enter_context(patch.object(target, name, return_value=value))
    stack.enter_context(patch.object(scoped_grid.Transformer, 'from_crs', return_value=FakeTransform))
    return stack


def build(base, config='catalog/demo-scope.json'):
    with reference_patches():
        return scoped_grid.build(base, scope_config=base/config)


def plan(base, **kwargs):
    return rollout.plan(base, max_new=1, **kwargs)


def scope_dir(base, ident='offline-demo'):
    return base/'var/seafloor/scopes'/ident


def central_layout(base):
    ref = base/'var/seafloor/reference'
    ref.mkdir(parents=True)
    (base/'catalog/reaches.json').write_text(json.dumps({'input_hash': 'grid', 'reaches': [{'id': REACH}]}))
    (ref/'cells.json').write_text(json.dumps({'input_hash': 'grid', 'cells': [{
        'id': '3310:0:0', 'reach': REACH, 'tier': 0, 'band_area_m2': 50000, 'reference_unknown_area_m2': 0}]}))
    (ref/'run.json').write_text(json.dumps({'input_hash': 'grid',
                                            'output_hashes': {'cells.json': sha256(ref/'cells.json')}}))


def seal(base, ident='offline-demo'):
    """Rewrite the build receipt over whatever bytes now exist, to reach the next check."""
    folder = scope_dir(base, ident)
    receipt = read_json(folder/'reference/run.json')
    receipt['output_hashes'] = {'seafloor-ledger.json': sha256(folder/'seafloor-ledger.json'),
                                'reaches.json': sha256(folder/'reaches.json'),
                                'cells.json': sha256(folder/'reference/cells.json')}
    atomic_json(folder/'reference/run.json', receipt)


def snapshot(base):
    return {str(p.relative_to(base)): sha256(p) for p in sorted(base.rglob('*'))
            if p.is_file() and 'private-reaches' not in p.parts and 'cache' not in p.parts}


def invoke(monkeypatch, capsys, base, *argv):
    monkeypatch.setattr(cli, 'REPO', base)
    monkeypatch.setattr(sys, 'argv', ['seafloor', *argv])
    cli.main()
    return capsys.readouterr().out


def test_three_commands_fixture_only(root, monkeypatch, capsys):
    with reference_patches():
        out = invoke(monkeypatch, capsys, root, 'reaches', '--scope-config', 'catalog/demo-scope.json')
    assert 'Rebuilt reference baseline' in out
    before = snapshot(root)
    plan = json.loads(invoke(monkeypatch, capsys, root, 'plan', '--scope-config', 'catalog/demo-scope.json',
                             '--json', '--physical-only', '--max-new', '1'))
    assert plan['scope_id'] == 'offline-demo' and plan['new_reaches'] == [REACH]
    assert plan['reaches'][0]['screen_reviewed'] is False
    summary = json.loads(invoke(monkeypatch, capsys, root, 'run', '--reach', REACH, '--physical-only',
                                '--scope-config', 'catalog/demo-scope.json'))
    assert summary['unchanged'] is False and summary['scope_id'] == 'offline-demo'
    assert summary['status'] == 'habitat-held-for-screen' and summary['tier2_km2'] == 0 and summary['tier3_km2'] == 0
    folder = scope_dir(root)/'private-reaches'/REACH
    receipt = read_json(folder/'run.json')
    assert receipt['publication_prohibited'] is True
    assert receipt['outputs'] == {name: sha256(folder/name) for name in receipt['outputs']}
    assert read_json(folder/'habitat.geojson')['features'] == []
    assert read_json(folder/'held.geojson')['features']
    assert snapshot(root) == before  # central files and the isolated reference stay byte-identical
    again = json.loads(invoke(monkeypatch, capsys, root, 'run', '--reach', REACH, '--physical-only',
                              '--scope-config', 'catalog/demo-scope.json'))
    assert again['unchanged'] is True and snapshot(root) == before
    after = json.loads(invoke(monkeypatch, capsys, root, 'plan', '--scope-config', 'catalog/demo-scope.json',
                              '--json', '--physical-only', '--max-new', '1'))
    assert after['reaches'][0]['processed'] and after['reaches'][0]['pending_ledger_merge']
    assert after['new_reaches'] == []


def test_absent_and_explicit_central_options_keep_the_central_path(root):
    central_layout(root)
    result, reused = run_module.run(REACH, root=root, physical_only=True)
    assert not reused
    again, reused = run_module.run(REACH, root=root, physical_only=True, scope_config=root/'catalog/seafloor-scope.json')
    assert reused and again == result
    assert (root/'var/seafloor/private-reaches'/REACH/'run.json').is_file()
    assert not (root/'var/seafloor/scopes').exists()


def mutate(path, change):
    document = read_json(path)
    change(document)
    atomic_json(path, document)


def duplicate_reach(document):
    document['reaches'].append(dict(document['reaches'][0]))


MUTATIONS = {
    'wrong-ledger-scope': ('seafloor-ledger.json', lambda d: d.update(scope='central-coast'), True, 'different scope'),
    'bad-ledger-input-hash': ('seafloor-ledger.json', lambda d: d.update(input_hash='bad'), True, 'input hashes'),
    'duplicate-reach': ('reaches.json', duplicate_reach, True, 'duplicate reach'),
    'catalog-reach-set': ('reaches.json', lambda d: d['reaches'][0].update(id='other-r01'), True, 'different reaches'),
    'foreign-cell-owner': ('reference/cells.json', lambda d: d['cells'][0].update(reach='central-r01'), True, 'foreign owner'),
    'bad-cell-hash': ('reference/cells.json', lambda d: d.update(input_hash='bad'), True, 'input hashes'),
    'tampered-output': ('reference/cells.json', lambda d: d['cells'][0].update(tier=1), False, 'build receipt'),
    'bad-ledger-digest': ('seafloor-ledger.json', lambda d: d.update(reference_cells_sha256='0' * 64), True, 'digest'),
}


@pytest.mark.parametrize('name', sorted(MUTATIONS))
def test_identity_never_falls_back_to_central_artifacts(root, name):
    build(root)
    central_layout(root)
    target, change, reseal, message = MUTATIONS[name]
    mutate(scope_dir(root)/target, change)
    if reseal:
        seal(root)
    central = snapshot(root)
    with patch.object(run_module, 'ingest', side_effect=AssertionError('ingest before verification')):
        with pytest.raises(ValueError, match=message):
            run_module.run(REACH, root=root, physical_only=True, scope_config=root/'catalog/demo-scope.json')
        with pytest.raises(ValueError, match=message):
            plan(root, physical_only=True, scope_config=root/'catalog/demo-scope.json')
    assert not (scope_dir(root)/'private-reaches').exists() and snapshot(root) == central


def test_missing_receipt_unknown_reach_and_changed_config_refuse(root):
    build(root)
    config = root/'catalog/demo-scope.json'
    with pytest.raises(ValueError, match='Unknown reach'):
        run_module.run('nope-r01', root=root, physical_only=True, scope_config=config)
    mutate(config, lambda d: d.update(tile_sample_m=d['tile_sample_m'] + 1))
    with pytest.raises(ValueError, match='different scope config'):
        run_module.run(REACH, root=root, physical_only=True, scope_config=config)
    (scope_dir(root)/'reference/run.json').unlink()
    with pytest.raises(ValueError, match='build receipt is missing'):
        run_module.run(REACH, root=root, physical_only=True, scope_config=config)


def test_two_scopes_sharing_reach_names_never_share_progress_and_drift_invalidates(root):
    build(root)
    build(root, 'catalog/second-scope.json')
    first, second = root/'catalog/demo-scope.json', root/'catalog/second-scope.json'
    run_module.run(REACH, root=root, physical_only=True, scope_config=first)
    assert (scope_dir(root)/'private-reaches'/REACH/'run.json').is_file()
    assert not (scope_dir(root, 'offline-two')/'private-reaches').exists()
    assert plan(root, physical_only=True, scope_config=first)['reaches'][0]['processed']
    other = plan(root, physical_only=True, scope_config=second)
    assert not other['reaches'][0]['processed'] and other['new_reaches'] == [REACH]
    # Same ID, changed config: the rebuilt reference gets a new identity and old receipts go stale.
    mutate(first, lambda d: d.update(tile_sample_m=d['tile_sample_m'] + 1))
    build(root)
    stale = plan(root, physical_only=True, scope_config=first)
    assert not stale['reaches'][0]['processed'] and stale['new_reaches'] == [REACH]
    _, reused = run_module.run(REACH, root=root, physical_only=True, scope_config=first)
    assert reused is False


def test_paths_and_central_impersonation_refuse(root, tmp_path_factory):
    build(root)
    outside = tmp_path_factory.mktemp('outside')
    private = scope_dir(root)/'private-reaches'
    private.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='escapes its scope directory'):
        run_module.run(REACH, root=root, physical_only=True, scope_config=root/'catalog/demo-scope.json')
    assert not list(outside.iterdir())
    elsewhere = outside/'scope.json'
    shutil.copyfile(root/'catalog/demo-scope.json', elsewhere)
    with pytest.raises(ValueError, match='inside the repository root'):
        plan(root, scope_config=elsewhere)
    fake = root/'catalog/fake-central.json'
    mutate(root/'catalog/demo-scope.json', lambda d: d.update(id='central-coast'))
    shutil.move(root/'catalog/demo-scope.json', fake)
    with pytest.raises(ValueError, match='central scope config cannot be replaced'):
        run_module.run(REACH, root=root, physical_only=True, scope_config=fake)
    garbage = root/'catalog/garbage.json'
    garbage.write_bytes(b'\xff\xfe')
    with pytest.raises(ValueError, match='UTF-8'):
        plan(root, scope_config=garbage)


def test_physical_is_not_clearance(root):
    build(root)
    config = root/'catalog/demo-scope.json'
    with pytest.raises(ValueError, match='Non-central processing is disabled'):
        run_module.run(REACH, root=root, scope_config=config)
    with pytest.raises(ValueError, match='Non-central processing is disabled'):
        run_module.run(REACH, root=root, physical_only=True, fetch=True, scope_config=config)
    assert not (scope_dir(root)/'private-reaches').exists()
    forged = root/'var/seafloor/screen/snapshot.json'
    forged.parent.mkdir(parents=True)
    forged.write_text(json.dumps({'status': 'ready', 'scope_id': 'central-coast', 'reviewed_reaches': [REACH]}))
    reference = snapshot(root)
    with patch.object(run_module, 'apply_ledger', side_effect=AssertionError('ledger write')):
        receipt, _ = run_module.run(REACH, root=root, physical_only=True, scope_config=config)
        run_module.run(REACH, root=root, physical_only=True, scope_config=config)  # warm reuse
    summary = receipt['ledger_summary']
    assert receipt['publication_prohibited'] is True and summary['status'] == 'habitat-held-for-screen'
    assert summary['tier2_km2'] == 0 and not any(summary['habitat_by_grade'].values())
    assert receipt['inputs']['screen']['reasons'] == ['scope-screen-contract-unavailable']
    assert snapshot(root) == reference


def test_warm_reuse_old_key_miss_corruption_and_interrupted_checkpoint(root):
    config = root/'catalog/demo-scope.json'
    build(root)
    folder = scope_dir(root)/'private-reaches'/REACH
    with patch.object(run_module, 'terrain_cells', side_effect=RuntimeError('interrupted')):
        with pytest.raises(RuntimeError):
            run_module.run(REACH, root=root, physical_only=True, scope_config=config)
    assert read_json(folder/'coverage-checkpoint.json')['ledger_summary']['processing_incomplete'] is True
    assert not (folder/'run.json').exists()
    assert not plan(root, physical_only=True, scope_config=config)['reaches'][0]['processed']
    run_module.run(REACH, root=root, physical_only=True, scope_config=config)
    _, reused = run_module.run(REACH, root=root, physical_only=True, scope_config=config)
    assert reused
    old = '5228a5150afd9bb298f35c5c29d5a2e39baa7bda18889e1a9875d90b091019d1'
    real = run_module.sha256
    with patch.object(run_module, 'sha256', side_effect=lambda p: old if Path(p).name == 'run.py' else real(p)):
        _, reused = run_module.run(REACH, root=root, physical_only=True, scope_config=config)
    assert reused is False  # the pre-MGL-19 implementation key no longer matches
    run_module.run(REACH, root=root, physical_only=True, scope_config=config)
    (folder/'terrain.json').write_text('{}')
    with pytest.raises(ValueError, match='failed hash verification'):
        run_module.run(REACH, root=root, physical_only=True, scope_config=config)
    with pytest.raises(ValueError, match='checksum mismatch'):
        plan(root, physical_only=True, scope_config=config)


def test_plan_does_not_credit_receipt_with_missing_outputs(root):
    build(root)
    config = root/'catalog/demo-scope.json'
    run_module.run(REACH, root=root, physical_only=True, scope_config=config)
    folder = scope_dir(root)/'private-reaches'/REACH
    assert plan(root, physical_only=True, scope_config=config)['reaches'][0]['processed']
    mutate(folder/'run.json', lambda d: d.update(outputs={'cells.json': d['outputs']['cells.json']}))
    (folder/'terrain.json').unlink()
    pending = plan(root, physical_only=True, scope_config=config)
    assert not pending['reaches'][0]['processed']
    assert pending['new_reaches'] == [REACH]


def test_plan_count_validation_and_held_default(root):
    build(root)
    config = root/'catalog/demo-scope.json'
    for bad in (True, 1.0, 2.5):
        with patch('skippercast.seafloor.scoped_processing.load_context', side_effect=AssertionError('read')):
            with pytest.raises(ValueError, match='max_new must be an integer'):
                rollout.plan(root, max_new=bad, scope_config=config)
    held = plan(root, scope_config=config)
    assert held['new_reaches'] == [] and held['execution']['new_reach_batch_selected'] is False
    assert held['reaches'][0]['action'] == 'held' and held['private_held'] is True
    assert held['execution']['additional_measured_km2'] is None
