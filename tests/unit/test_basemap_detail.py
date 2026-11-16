"""Offline extraction coverage guard, including the Trinidad–Klamath gap."""
import copy
import json
import subprocess
import sys

import pytest

from scripts.basemap import check_detail, regions
from tests._support import ROOT
from tests.unit.test_basemap_regions import LISTING


def settings():
    planned = regions.plan('20261008', LISTING)
    return planned, regions.detail_region(planned['regions'])


def test_all_22_regions_include_trinidad_at_detail_zooms():
    planned, detail = settings()
    boxes = check_detail.check_detail(planned, detail)
    assert len(boxes) == 22
    assert next(b['bbox'] for b in boxes if b['id'] == 'trinidad-klamath') == [-124.6, 40.95, -124.0, 41.55]


@pytest.mark.parametrize('fault', ['missing', 'bounds', 'duplicate', 'zoom-min', 'zoom-max', 'overview', 'geometry'])
def test_refuses_incomplete_or_inconsistent_settings(fault):
    planned, detail = settings()
    target = next(b for b in planned['regions'] if b['id'] == 'trinidad-klamath')
    if fault == 'missing':
        planned['regions'].remove(target)
        detail = regions.detail_region(planned['regions'])
    elif fault == 'bounds':
        target['bbox'][3] -= 0.1
        detail = regions.detail_region(planned['regions'])
    elif fault == 'duplicate':
        planned['regions'].append(copy.deepcopy(target))
    elif fault == 'zoom-min':
        planned['detail']['minzoom'] = 12
    elif fault == 'zoom-max':
        planned['detail']['maxzoom'] = 13
    elif fault == 'overview':
        planned['overview']['maxzoom'] = 11
    else:
        detail['geometry']['coordinates'].pop()
    with pytest.raises(ValueError):
        check_detail.check_detail(planned, detail)


def test_draft_subregions_use_containment_not_status_promotion(tmp_path):
    planned, detail = settings()
    coverage = check_detail.check_detail(planned, detail)
    assert next(b['containers'] for b in coverage if b['id'] == 'san-diego') == ['southern-california']
    # Keep the real extraction regions, then add a draft beyond every box.
    for path in (ROOT / 'regions').glob('*/region.json'):
        target = tmp_path / 'regions' / path.parent.name / 'region.json'
        target.parent.mkdir(parents=True)
        target.write_text(path.read_text())
    target = tmp_path / 'regions' / 'outside' / 'region.json'
    target.parent.mkdir()
    target.write_text(json.dumps({'id': 'outside', 'status': 'draft', 'bounds': [-125, 42, -124, 43]}))
    with pytest.raises(ValueError, match='No detail box contains region outside'):
        check_detail.check_detail(planned, detail, root=tmp_path)


def test_cli_checks_defaults_and_saved_settings_offline(tmp_path):
    command = [sys.executable, str(ROOT / 'scripts/basemap/check_detail.py')]
    default = subprocess.run(command, capture_output=True, text=True, check=True)
    assert 'PASS trinidad-klamath: zooms 11–14' in default.stdout
    assert '22 of 22 regions inside a detail box' in default.stdout
    planned, detail = settings()
    (tmp_path / 'plan.json').write_text(json.dumps(planned))
    (tmp_path / 'detail.geojson').write_text(json.dumps(detail))
    saved = subprocess.run([*command, '--dir', str(tmp_path)], capture_output=True, text=True, check=True)
    assert saved.stdout == default.stdout
    (tmp_path / 'detail.geojson').write_text('{}')
    bad = subprocess.run([*command, '--dir', str(tmp_path)], capture_output=True, text=True)
    assert bad.returncode == 1
    assert 'FAIL:' in bad.stderr


def test_cli_refuses_unreadable_saved_settings(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/basemap/check_detail.py'), '--dir', str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert 'FAIL:' in result.stderr


def _run_dir(tmp_path, plan, detail=None):
    planned, good = settings()
    plan = plan(planned) if callable(plan) else plan
    (tmp_path / 'plan.json').write_text(plan if isinstance(plan, str) else json.dumps(plan))
    (tmp_path / 'detail.geojson').write_text(json.dumps(good if detail is None else detail))
    return subprocess.run([sys.executable, str(ROOT / 'scripts/basemap/check_detail.py'), '--dir', str(tmp_path)],
                          capture_output=True, text=True)


def _drop(key):
    return lambda p: {**p, 'regions': [{k: v for k, v in p['regions'][0].items() if k != key}]}


@pytest.mark.parametrize('plan,message', [
    (_drop('id'), 'plan.json: regions[0] must be an object with a string "id" and a 4-number "bbox"'),
    (_drop('bbox'), 'plan.json: regions[0] must be an object with a string "id" and a 4-number "bbox"'),
    (lambda p: {**p, 'regions': 'x'}, 'plan.json: "regions" must be a list'),
    ([], 'plan.json: not a JSON object'),
    (lambda p: {**p, 'overview': None}, 'plan.json: "overview" must be an object'),
    (lambda p: {**p, 'detail': 3}, 'plan.json: "detail" must be an object'),
    ('{"regions": ', 'plan.json: not valid JSON (line 1 column 13)'),
    (lambda p: {**p, 'regions': [{'id': 'a', 'bbox': [1, 2, 3]}]}, 'regions[0] must be an object'),
    (lambda p: {**p, 'regions': [{'id': 'a', 'bbox': [1, 2, 3, 'x']}]}, 'regions[0] must be an object'),
    ('{"overview": {}, "detail": {}, "regions": [{"id": "a", "bbox": [1, 2, 3, NaN]}]}', 'regions[0] must be an object'),
])
def test_cli_names_file_and_field_of_misshaped_plan(tmp_path, plan, message):
    result = _run_dir(tmp_path, plan)
    assert result.returncode == 1 and result.stdout == ''
    assert result.stderr.startswith('FAIL: ') and message in result.stderr


def test_cli_names_detail_file_and_missing_dir(tmp_path):
    result = _run_dir(tmp_path, lambda p: p, detail=[])
    assert result.returncode == 1 and result.stdout == ''
    assert 'FAIL: detail.geojson: not a JSON object' in result.stderr
    missing = subprocess.run([sys.executable, str(ROOT / 'scripts/basemap/check_detail.py'), '--dir', str(tmp_path / 'no')],
                             capture_output=True, text=True)
    assert 'FAIL: plan.json: cannot read: No such file or directory' in missing.stderr
