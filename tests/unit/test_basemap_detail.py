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
