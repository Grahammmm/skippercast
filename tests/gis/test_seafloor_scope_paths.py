"""Offline checks for isolated scope artifacts and fail-closed downstream seams."""
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pytest
from shapely.geometry import LineString, box, mapping

from skippercast.seafloor import grid, publish, run, screen
from skippercast.seafloor.scope_paths import resolve_scope
from skippercast.seafloor import __main__ as cli
from skippercast.seafloor.io import sha256


def fixture_root(tmp_path):
    (tmp_path/'catalog').mkdir()
    source = json.loads(Path('catalog/seafloor-scope.json').read_text())
    source.update(id='offline-demo', bounds=[0, 0, 1, 1], priority_anchor=[.5, .5],
                  regions=[{'id': 'demo-region', 'start_anchor': [.1, .1]}])
    config = tmp_path/'catalog/demo-scope.json'
    config.write_text(json.dumps(source))
    return tmp_path, config


def test_noncentral_grid_build_uses_only_isolated_artifact_paths(tmp_path):
    root, config_path = fixture_root(tmp_path)
    legacy = root/'dist/data/seafloor-ledger.json'
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"scope":"central-sentinel"}')
    (root/'catalog').mkdir(exist_ok=True)
    old_reaches = root/'catalog/reaches.json'
    old_reaches.write_text('{"scope":"central-sentinel"}')
    spine = LineString([(0, 0), (1000, 0)])

    class FakeTransform:
        @staticmethod
        def transform(x, y):
            return np.full(np.shape(x), .5), np.full(np.shape(y), .5)

    with patch.object(grid.reference, 'planning_spine', return_value=spine), \
         patch.object(grid, 'make_reaches', return_value=[{'id': 'demo-region-r01', 'region': 'demo-region',
             'order': 1, 'start_m': 0, 'end_m': 1000, 'length_m': 1000,
             'bounds_3310': [0, 0, 1000, 0], 'geometry': mapping(spine)}]), \
         patch.object(grid.reference, 'scheme_tiles', return_value=({'scheme_sha256': 'fixture', 'scheme_url': 'fixture'}, [])), \
         patch.object(grid.reference, 'samples', return_value=[]), \
         patch.object(grid, 'mosaic_reference', return_value=(np.full((10, 10), 2, dtype='uint8'),
             __import__('rasterio').transform.Affine(25, 0, 0, 0, -25, 250))), \
         patch.object(grid, 'assign_reaches', return_value=np.array([0])), \
         patch.object(grid.Transformer, 'from_crs', return_value=FakeTransform), \
         patch.object(grid, 'sha256', return_value='fixture-hash'):
        ledger, unchanged = grid.build(root, scope_config=config_path)

    paths = resolve_scope(root, scope_config=config_path)[1]
    assert not unchanged
    assert ledger['scope'] == 'offline-demo'
    assert paths.ledger_path.is_file()
    assert paths.reaches_path.is_file()
    assert paths.cells_path.is_file()
    assert json.loads(legacy.read_text())['scope'] == 'central-sentinel'
    assert json.loads(old_reaches.read_text())['scope'] == 'central-sentinel'
    assert not (root/'var/seafloor/reference/cells.json').exists()


def test_noncentral_screen_run_and_publish_fail_closed_without_reusing_central(tmp_path):
    root, config_path = fixture_root(tmp_path)
    central = root/'var/seafloor/screen/snapshot.json'
    central.parent.mkdir(parents=True)
    central.write_text('{"scope_id":"central-coast"}')
    state = screen.load_snapshot(root, 'demo-reach', scope_config=config_path)
    assert state['status'] == 'held'
    assert state['reasons'] == ['screen-missing']
    with pytest.raises(ValueError, match='Non-central processing is disabled'):
        run.run('demo-reach', root=root, scope_config=config_path)
    with pytest.raises(ValueError, match='Non-central publication is disabled'):
        publish.build('demo-region', root=root, tool='unused', scope_config=config_path)
    assert central.read_text() == '{"scope_id":"central-coast"}'


def test_noncentral_scope_requires_explicit_config(tmp_path):
    with pytest.raises(ValueError, match='requires an explicit scope config'):
        resolve_scope(tmp_path, scope_id='offline-demo')


def test_relative_root_resolves_central_default():
    config, paths = resolve_scope(Path('.'))
    assert config['id'] == 'central-coast'
    assert paths.is_central_default
    assert paths.ledger_path == Path('.').resolve()/'dist/data/seafloor-ledger.json'


def test_reaches_cli_defaults_region_to_selected_ledger_scope(monkeypatch, capsys):
    ledger = {'scope': 'central-coast', 'reference': {}, 'reaches': []}
    monkeypatch.setattr(sys, 'argv', ['seafloor', 'reaches'])
    with patch.object(grid, 'build', return_value=(ledger, True)) as build:
        cli.main()
    assert build.call_args.kwargs['region'] is None
    assert 'Reference unchanged' in capsys.readouterr().out


def test_explicit_central_config_keeps_legacy_screen_snapshot_contract(tmp_path):
    root = tmp_path
    catalog = root/'catalog'
    catalog.mkdir()
    config = catalog/'seafloor-scope.json'
    config.write_text(Path('catalog/seafloor-scope.json').read_text())
    policy = catalog/'seafloor-screen.json'
    policy.write_text('{"fixture": true}')
    folder = root/'var/seafloor/screen'
    folder.mkdir(parents=True)
    checked = datetime(2026, 9, 28, tzinfo=timezone.utc).isoformat()
    geometry = mapping(box(-122, 35, -121, 36))
    layers = {}
    for name in ('cdfw-mpa', 'noaa-federal', 'security'):
        source = folder/f'{name}.json'
        source.write_text(json.dumps({'type': 'FeatureCollection', 'features': [{'geometry': geometry}]}))
        layers[name] = {'file': source.name, 'sha256': sha256(source), 'status': 'ok',
                        'feature_count': 1, 'source_url': 'https://example.gov/data',
                        'checked_at': checked, 'evidence': {'up_to_date_as_of': '2026-09-28'}}
    snapshot = {'version': screen.VERSION, 'checked_at': checked, 'reviewed_reaches': ['fixture'],
                'scope': geometry, 'policy_sha256': sha256(policy), 'layers': layers}
    (folder/'snapshot.json').write_text(json.dumps(snapshot))

    state = screen.load_snapshot(root, 'fixture', datetime(2026, 9, 28, tzinfo=timezone.utc),
                                 scope_config=config)
    assert state['status'] == 'ready'
    assert state['reasons'] == []
